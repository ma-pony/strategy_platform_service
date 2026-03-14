"""Aroon 趋势识别策略。

Aroon Up 上穿 Aroon Down 且 Aroon Up > 70 做多，
Aroon Down 上穿 Aroon Up 或 Aroon Up < 30 平仓。
"""

import talib.abstract as ta  # type: ignore[import]
from freqtrade.strategy import IStrategy  # type: ignore[import]
from pandas import DataFrame  # type: ignore[import]


class AroonTrend(IStrategy):
    INTERFACE_VERSION = 3

    minimal_roi = {"0": 0.15, "120": 0.04, "240": 0}
    stoploss = -0.08
    timeframe = "1h"
    can_short = False

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        aroon = ta.AROON(dataframe, timeperiod=25)
        dataframe["aroon_up"] = aroon["aroonup"]
        dataframe["aroon_down"] = aroon["aroondown"]
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (dataframe["aroon_up"] > dataframe["aroon_down"])
            & (dataframe["aroon_up"].shift(1) <= dataframe["aroon_down"].shift(1))
            & (dataframe["aroon_up"] > 70),
            "enter_long",
        ] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (dataframe["aroon_down"] > dataframe["aroon_up"])
            & (dataframe["aroon_down"].shift(1) <= dataframe["aroon_up"].shift(1))
            | (dataframe["aroon_up"] < 30),
            "exit_long",
        ] = 1
        return dataframe
