"""抛物线 SAR 趋势策略 — 趋势跟随。

SAR 翻转至价格下方做多，翻转至价格上方平仓。
结合 ADX 过滤震荡行情。
"""

import talib.abstract as ta  # type: ignore[import]
from freqtrade.strategy import IStrategy  # type: ignore[import]
from pandas import DataFrame  # type: ignore[import]


class ParabolicSarTrend(IStrategy):
    INTERFACE_VERSION = 3

    minimal_roi = {"0": 0.12, "90": 0.04, "180": 0}
    stoploss = -0.07
    timeframe = "1h"
    can_short = False

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["sar"] = ta.SAR(dataframe, acceleration=0.02, maximum=0.2)
        dataframe["adx"] = ta.ADX(dataframe, timeperiod=14)
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (dataframe["sar"] < dataframe["close"])
            & (dataframe["sar"].shift(1) >= dataframe["close"].shift(1))
            & (dataframe["adx"] > 20),
            "enter_long",
        ] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (dataframe["sar"] > dataframe["close"])
            & (dataframe["sar"].shift(1) <= dataframe["close"].shift(1)),
            "exit_long",
        ] = 1
        return dataframe
