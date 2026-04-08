from datetime import datetime

import pandas as pd
import talib.abstract as ta
from freqtrade.persistence import Trade
from freqtrade.strategy import DecimalParameter, IStrategy, stoploss_from_open
from pandas import DataFrame


class ParabolicSarTrendStrategy(IStrategy):
    INTERFACE_VERSION = 3

    timeframe = "1d"
    can_short: bool = False

    minimal_roi = {
        "0": 100,
    }

    stoploss = -0.15
    trailing_stop = False
    use_custom_stoploss = False

    process_only_new_candles = True
    use_exit_signal = True
    exit_profit_only = False
    ignore_roi_if_entry_signal = False
    startup_candle_count: int = 240

    sar_acc = DecimalParameter(0.005, 0.05, default=0.02, space="buy")
    sar_max = DecimalParameter(0.05, 0.5, default=0.2, space="buy")

    atr_multiplier = DecimalParameter(1.5, 3.0, default=2.0, space="sell")
    trail_atr_multiplier = DecimalParameter(1.0, 2.0, default=1.5, space="sell")

    order_types = {
        "entry": "limit",
        "exit": "limit",
        "stoploss": "market",
        "stoploss_on_exchange": False,
    }

    order_time_in_force = {
        "entry": "GTC",
        "exit": "GTC",
    }

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["sar"] = ta.SAR(dataframe, acceleration=float(self.sar_acc.value), maximum=float(self.sar_max.value))
        dataframe["atr"] = ta.ATR(dataframe, timeperiod=14)
        dataframe["volume_mean"] = dataframe["volume"].rolling(window=20).mean()
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["enter_long"] = 0
        dataframe["enter_short"] = 0
        dataframe["enter_tag"] = ""

        prev_close = dataframe["close"].shift(1)
        prev_sar = dataframe["sar"].shift(1)

        cross_up = (dataframe["close"] > dataframe["sar"]) & (prev_close <= prev_sar)
        cross_dn = (dataframe["close"] < dataframe["sar"]) & (prev_close >= prev_sar)

        vol_ok = dataframe["volume"] > 0
        dataframe.loc[cross_up & vol_ok, ["enter_long", "enter_tag"]] = [1, "sar_cross_up"]
        dataframe.loc[cross_dn & vol_ok, ["enter_short", "enter_tag"]] = [1, "sar_cross_down"]

        conflict = (dataframe["enter_long"] == 1) & (dataframe["enter_short"] == 1)
        dataframe.loc[conflict, ["enter_long", "enter_short", "enter_tag"]] = [0, 0, ""]
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["exit_long"] = 0
        dataframe["exit_short"] = 0

        prev_close = dataframe["close"].shift(1)
        prev_sar = dataframe["sar"].shift(1)

        cross_dn = (dataframe["close"] < dataframe["sar"]) & (prev_close >= prev_sar)
        cross_up = (dataframe["close"] > dataframe["sar"]) & (prev_close <= prev_sar)

        vol_ok = dataframe["volume"] > 0
        dataframe.loc[cross_dn & vol_ok, "exit_long"] = 1
        dataframe.loc[cross_up & vol_ok, "exit_short"] = 1
        return dataframe

    def custom_stoploss(
        self, pair: str, trade: Trade, current_time: datetime, current_rate: float, current_profit: float, **kwargs
    ) -> float:
        try:
            dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
            if dataframe is None or len(dataframe) < 20:
                return 1.0

            if "date" in dataframe.columns:
                df = dataframe
                if not pd.api.types.is_datetime64_any_dtype(df["date"]):
                    df = df.copy()
                    df["date"] = pd.to_datetime(df["date"], utc=True, errors="coerce")
                df = df.dropna(subset=["date"]).sort_values("date")
            else:
                df = dataframe.copy()
                df["date"] = pd.to_datetime(df.index, utc=True, errors="coerce")
                df = df.dropna(subset=["date"]).sort_values("date")

            entry_date = pd.Timestamp(trade.open_date_utc)
            if entry_date.tzinfo is None:
                entry_date = entry_date.tz_localize("UTC")
            else:
                entry_date = entry_date.tz_convert("UTC")

            hist = df.loc[df["date"] <= entry_date]
            if hist.empty:
                return 1.0

            entry_row = hist.iloc[-1]
            atr_at_entry = float(entry_row.get("atr", 0.0) or 0.0)
            if atr_at_entry <= 0.0 or pd.isna(atr_at_entry):
                return 1.0

            current_atr = float(df["atr"].iloc[-1] or 0.0)
            if current_atr <= 0.0 or pd.isna(current_atr):
                return 1.0

            initial_mult = float(self.atr_multiplier.value)
            trail_mult = float(self.trail_atr_multiplier.value)

            atr_pct_entry = atr_at_entry / float(trade.open_rate)
            open_relative_stop = -atr_pct_entry * initial_mult

            if current_profit > 1.5 * atr_pct_entry:
                trail_distance = current_atr * trail_mult
                if bool(getattr(trade, "is_short", False)):
                    stop_price = float(current_rate) + float(trail_distance)
                    if stop_price > float(trade.open_rate):
                        stop_price = float(trade.open_rate)
                    open_relative_stop = max(
                        open_relative_stop, (float(trade.open_rate) - stop_price) / float(trade.open_rate)
                    )
                else:
                    stop_price = float(current_rate) - float(trail_distance)
                    if stop_price < float(trade.open_rate):
                        stop_price = float(trade.open_rate)
                    open_relative_stop = max(open_relative_stop, (stop_price / float(trade.open_rate)) - 1.0)

            sl = float(stoploss_from_open(open_relative_stop, current_profit))
            if sl <= 0.0:
                return 1.0
            return sl
        except Exception as e:
            if hasattr(self, "log"):
                self.log.error(f"Custom stoploss error for {pair}: {e!s}")
            return 1.0

    def custom_exit(
        self, pair: str, trade: Trade, current_time: datetime, current_rate: float, current_profit: float, **kwargs
    ) -> str | None:
        if current_profit <= 0:
            return None

        max_profit = trade.max_profit if hasattr(trade, "max_profit") else current_profit

        # 只在高盈利位置回撤时才出，给趋势足够空间
        if max_profit > 0.40 and (max_profit - current_profit) > 0.15:
            return "trailing_profit_15pct"
        if max_profit > 0.20 and (max_profit - current_profit) > 0.10:
            return "trailing_profit_10pct"

        return None

    @property
    def plot_config(self):
        return {
            "main_plot": {"close": {"color": "black"}, "sar": {"color": "white"}},
            "subplots": {
                "ATR": {"atr": {"color": "white"}},
                "Volume": {"volume": {"color": "gray", "type": "bar"}, "volume_mean": {"color": "blue"}},
            },
        }
