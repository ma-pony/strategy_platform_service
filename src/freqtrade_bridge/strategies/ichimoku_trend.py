"""一目均衡表趋势策略 — 趋势跟随。

价格在云层上方且转换线上穿基准线做多，跌入云层或转换线下穿基准线平仓。
"""

from freqtrade.strategy import IStrategy  # type: ignore[import]
from pandas import DataFrame  # type: ignore[import]


class IchimokuTrend(IStrategy):
    INTERFACE_VERSION = 3

    minimal_roi = {"0": 0.2, "180": 0.05, "360": 0}
    stoploss = -0.1
    timeframe = "1h"
    can_short = False

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        high = dataframe["high"]
        low = dataframe["low"]

        # 转换线 (Tenkan-sen): 9 期
        nine_high = high.rolling(window=9).max()
        nine_low = low.rolling(window=9).min()
        dataframe["tenkan"] = (nine_high + nine_low) / 2

        # 基准线 (Kijun-sen): 26 期
        twenty_six_high = high.rolling(window=26).max()
        twenty_six_low = low.rolling(window=26).min()
        dataframe["kijun"] = (twenty_six_high + twenty_six_low) / 2

        # 先行带 A (Senkou Span A)
        dataframe["senkou_a"] = ((dataframe["tenkan"] + dataframe["kijun"]) / 2).shift(26)

        # 先行带 B (Senkou Span B): 52 期
        fifty_two_high = high.rolling(window=52).max()
        fifty_two_low = low.rolling(window=52).min()
        dataframe["senkou_b"] = ((fifty_two_high + fifty_two_low) / 2).shift(26)

        dataframe["cloud_top"] = dataframe[["senkou_a", "senkou_b"]].max(axis=1)
        dataframe["cloud_bottom"] = dataframe[["senkou_a", "senkou_b"]].min(axis=1)

        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (dataframe["close"] > dataframe["cloud_top"])
            & (dataframe["tenkan"] > dataframe["kijun"])
            & (dataframe["tenkan"].shift(1) <= dataframe["kijun"].shift(1)),
            "enter_long",
        ] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (dataframe["close"] < dataframe["cloud_bottom"])
            | (
                (dataframe["tenkan"] < dataframe["kijun"])
                & (dataframe["tenkan"].shift(1) >= dataframe["kijun"].shift(1))
            ),
            "exit_long",
        ] = 1
        return dataframe
