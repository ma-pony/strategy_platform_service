"""RSI 均值回归策略。

RSI 跌入超卖区（<30）做多，回升至超买区（>70）或中性区（>50）平仓。
结合 SMA 确认不处于强下跌趋势。
"""

import talib.abstract as ta  # type: ignore[import]
from freqtrade.strategy import IStrategy  # type: ignore[import]
from pandas import DataFrame  # type: ignore[import]


class RsiMeanReversion(IStrategy):
    INTERFACE_VERSION = 3

    minimal_roi = {"0": 0.1, "60": 0.04, "120": 0}
    stoploss = -0.07
    timeframe = "1h"
    can_short = False

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=14)
        dataframe["sma50"] = ta.SMA(dataframe, timeperiod=50)
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (dataframe["rsi"] < 30)
            & (dataframe["rsi"].shift(1) >= 30)
            & (dataframe["close"] > dataframe["sma50"]),
            "enter_long",
        ] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (dataframe["rsi"] > 70)
            | ((dataframe["rsi"] > 50) & (dataframe["rsi"].shift(1) <= 50)),
            "exit_long",
        ] = 1
        return dataframe
