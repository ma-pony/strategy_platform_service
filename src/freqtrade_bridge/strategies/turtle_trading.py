"""海龟交易策略 — 趋势跟随。

基于 Donchian 通道突破：价格突破 20 日最高价做多，跌破 10 日最低价平仓。
使用 ATR 进行仓位管理和止损计算。
"""

from freqtrade.strategy import IStrategy, IntParameter  # type: ignore[import]
from pandas import DataFrame  # type: ignore[import]


class TurtleTrading(IStrategy):
    INTERFACE_VERSION = 3

    minimal_roi = {"0": 0.2, "120": 0.05, "240": 0}
    stoploss = -0.1
    timeframe = "1h"
    can_short = False

    entry_period = IntParameter(10, 30, default=20, space="buy")
    exit_period = IntParameter(5, 20, default=10, space="sell")

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        period = self.entry_period.value
        exit_p = self.exit_period.value

        dataframe["dc_upper"] = dataframe["high"].rolling(window=period).max()
        dataframe["dc_lower"] = dataframe["low"].rolling(window=exit_p).min()

        # ATR for position sizing reference
        high_low = dataframe["high"] - dataframe["low"]
        high_close = (dataframe["high"] - dataframe["close"].shift(1)).abs()
        low_close = (dataframe["low"] - dataframe["close"].shift(1)).abs()
        tr = high_low.combine(high_close, max).combine(low_close, max)
        dataframe["atr"] = tr.rolling(window=20).mean()

        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            dataframe["close"] > dataframe["dc_upper"].shift(1),
            "enter_long",
        ] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            dataframe["close"] < dataframe["dc_lower"].shift(1),
            "exit_long",
        ] = 1
        return dataframe
