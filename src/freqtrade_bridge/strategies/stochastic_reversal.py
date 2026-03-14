"""随机指标反转策略 — 均值回归。

Stochastic %K 从超卖区（<20）上穿 %D 做多，从超买区（>80）下穿 %D 平仓。
"""

import talib.abstract as ta  # type: ignore[import]
from freqtrade.strategy import IStrategy  # type: ignore[import]
from pandas import DataFrame  # type: ignore[import]


class StochasticReversal(IStrategy):
    INTERFACE_VERSION = 3

    minimal_roi = {"0": 0.08, "60": 0.03, "120": 0}
    stoploss = -0.06
    timeframe = "1h"
    can_short = False

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        stoch = ta.STOCH(
            dataframe,
            fastk_period=14,
            slowk_period=3,
            slowk_matype=0,
            slowd_period=3,
            slowd_matype=0,
        )
        dataframe["slowk"] = stoch["slowk"]
        dataframe["slowd"] = stoch["slowd"]
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (dataframe["slowk"] > dataframe["slowd"])
            & (dataframe["slowk"].shift(1) <= dataframe["slowd"].shift(1))
            & (dataframe["slowk"] < 20),
            "enter_long",
        ] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (dataframe["slowk"] < dataframe["slowd"])
            & (dataframe["slowk"].shift(1) >= dataframe["slowd"].shift(1))
            & (dataframe["slowk"] > 80),
            "exit_long",
        ] = 1
        return dataframe
