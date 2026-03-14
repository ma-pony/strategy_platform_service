"""NR7 窄幅突破策略。

NR7（近 7 根 K 线中振幅最小的一根）出现后，突破该 K 线最高价做多。
窄幅区间通常预示大幅波动即将到来。
"""

from freqtrade.strategy import IStrategy  # type: ignore[import]
from pandas import DataFrame  # type: ignore[import]


class Nr7Breakout(IStrategy):
    INTERFACE_VERSION = 3

    minimal_roi = {"0": 0.12, "60": 0.04, "120": 0}
    stoploss = -0.06
    timeframe = "1h"
    can_short = False

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["range"] = dataframe["high"] - dataframe["low"]
        dataframe["range_min7"] = dataframe["range"].rolling(window=7).min()
        dataframe["is_nr7"] = dataframe["range"] == dataframe["range_min7"]
        dataframe["nr7_high"] = dataframe["high"].where(dataframe["is_nr7"]).ffill()
        dataframe["nr7_low"] = dataframe["low"].where(dataframe["is_nr7"]).ffill()
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (dataframe["close"] > dataframe["nr7_high"].shift(1))
            & (dataframe["is_nr7"].shift(1)),
            "enter_long",
        ] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (dataframe["close"] < dataframe["nr7_low"].shift(1)),
            "exit_long",
        ] = 1
        return dataframe
