"""凯尔特纳通道突破策略。

价格突破凯尔特纳通道上轨做多（动量突破），跌回中轨或下轨平仓。
结合 ATR 过滤低波动行情。
"""

import talib.abstract as ta  # type: ignore[import]
from freqtrade.strategy import IStrategy  # type: ignore[import]
from pandas import DataFrame  # type: ignore[import]


class KeltnerBreakout(IStrategy):
    INTERFACE_VERSION = 3

    minimal_roi = {"0": 0.15, "90": 0.05, "180": 0}
    stoploss = -0.08
    timeframe = "1h"
    can_short = False

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["ema20"] = ta.EMA(dataframe, timeperiod=20)
        dataframe["atr"] = ta.ATR(dataframe, timeperiod=14)
        dataframe["kc_upper"] = dataframe["ema20"] + 2 * dataframe["atr"]
        dataframe["kc_lower"] = dataframe["ema20"] - 2 * dataframe["atr"]
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (dataframe["close"] > dataframe["kc_upper"])
            & (dataframe["close"].shift(1) <= dataframe["kc_upper"].shift(1)),
            "enter_long",
        ] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (dataframe["close"] < dataframe["ema20"]),
            "exit_long",
        ] = 1
        return dataframe
