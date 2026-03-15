"""seed_signals._extract_all_signals 信号提取逻辑单元测试。

验证：
  - 边沿触发：连续相同方向不重复生成信号
  - 方向优先级：enter_long > enter_short > exit_long > exit_short
  - stop_loss/take_profit 随方向正确翻转
  - confidence_score 基于成交量/信号类型/ATR 计算，非伪随机
  - signal_strength 入场 0.75 / 出场 0.50
  - volatility 前 20 根 K 线收益率标准差
  - indicator_values 排除 OHLCV 和信号列
"""

import numpy as np
import pandas as pd

from src.freqtrade_bridge.seeds.seed_signals import _extract_all_signals


def _make_strategy_df(
    n: int = 30,
    signals: list[dict] | None = None,
) -> pd.DataFrame:
    """构建带指标和信号列的 DataFrame。

    Args:
        n: K 线数量
        signals: 列表，每个 dict 指定 index 及 enter_long/exit_long/enter_short/exit_short
    """
    rng = np.random.default_rng(42)
    closes = 30000.0 + rng.uniform(-200, 200, n).cumsum()
    df = pd.DataFrame(
        {
            "date": pd.date_range("2025-01-01", periods=n, freq="4h", tz="UTC"),
            "open": closes * 0.999,
            "high": closes * 1.005,
            "low": closes * 0.995,
            "close": closes,
            "volume": rng.uniform(500, 2000, n),
        }
    )
    df["atr"] = 100.0
    df["volume_mean"] = df["volume"].rolling(20).mean()
    df["rsi"] = 50.0
    df["enter_long"] = 0
    df["exit_long"] = 0
    df["enter_short"] = 0
    df["exit_short"] = 0

    if signals:
        for sig in signals:
            idx = sig["index"]
            for col in ["enter_long", "exit_long", "enter_short", "exit_short"]:
                if col in sig:
                    df.loc[idx, col] = sig[col]

    return df


class TestEdgeTriggeredExtraction:
    """边沿触发：连续同方向不重复生成。"""

    def test_consecutive_same_direction_produces_single_signal(self) -> None:
        """连续两根 enter_long=1 只生成一条 buy 信号。"""
        df = _make_strategy_df(
            signals=[
                {"index": 25, "enter_long": 1},
                {"index": 26, "enter_long": 1},
            ]
        )
        signals = _extract_all_signals(df, "BTC/USDT", 1)
        buy_signals = [s for s in signals if s["signal_at"] >= df.loc[25, "date"]]
        assert len(buy_signals) == 1

    def test_direction_change_produces_new_signal(self) -> None:
        """buy → sell 方向变化产生两条信号。"""
        df = _make_strategy_df(
            signals=[
                {"index": 25, "enter_long": 1},
                {"index": 27, "enter_short": 1},
            ]
        )
        signals = _extract_all_signals(df, "BTC/USDT", 1)
        late_signals = [s for s in signals if s["signal_at"] >= df.loc[25, "date"]]
        assert len(late_signals) == 2
        assert late_signals[0]["direction"] == "buy"
        assert late_signals[1]["direction"] == "sell"

    def test_gap_resets_edge_trigger(self) -> None:
        """中间有无信号 K 线后，同方向信号视为新信号。"""
        df = _make_strategy_df(
            signals=[
                {"index": 22, "enter_long": 1},
                # index 23-24 无信号 → prev_direction 重置
                {"index": 25, "enter_long": 1},
            ]
        )
        signals = _extract_all_signals(df, "BTC/USDT", 1)
        buy_signals = [s for s in signals if s["direction"] == "buy" and s["signal_at"] >= df.loc[22, "date"]]
        assert len(buy_signals) == 2


class TestDirectionPriority:
    """方向优先级测试。"""

    def test_enter_short_priority_over_exit_long(self) -> None:
        """enter_short 和 exit_long 同时为 1 时，enter_short 优先。"""
        df = _make_strategy_df(
            signals=[
                {"index": 25, "enter_short": 1, "exit_long": 1},
            ]
        )
        signals = _extract_all_signals(df, "BTC/USDT", 1)
        sig = [s for s in signals if s["signal_at"] == df.loc[25, "date"]]
        assert len(sig) == 1
        assert sig[0]["direction"] == "sell"
        assert sig[0]["signal_strength"] == 0.75  # 入场优先


class TestStopLossTakeProfitSeed:
    """止损止盈方向正确性。"""

    def test_buy_sl_below_tp_above(self) -> None:
        df = _make_strategy_df(signals=[{"index": 25, "enter_long": 1}])
        signals = _extract_all_signals(df, "BTC/USDT", 1)
        sig = [s for s in signals if s["signal_at"] == df.loc[25, "date"]][0]
        assert sig["stop_loss"] < sig["entry_price"]
        assert sig["take_profit"] > sig["entry_price"]

    def test_sell_sl_above_tp_below(self) -> None:
        df = _make_strategy_df(signals=[{"index": 25, "enter_short": 1}])
        signals = _extract_all_signals(df, "BTC/USDT", 1)
        sig = [s for s in signals if s["signal_at"] == df.loc[25, "date"]][0]
        assert sig["stop_loss"] > sig["entry_price"]
        assert sig["take_profit"] < sig["entry_price"]

    def test_atr_based_sl_tp_values(self) -> None:
        """ATR=100 时，buy 的 SL = entry-200, TP = entry+300。"""
        df = _make_strategy_df(signals=[{"index": 25, "enter_long": 1}])
        signals = _extract_all_signals(df, "BTC/USDT", 1)
        sig = [s for s in signals if s["signal_at"] == df.loc[25, "date"]][0]
        assert abs(sig["stop_loss"] - (sig["entry_price"] - 200.0)) < 0.01
        assert abs(sig["take_profit"] - (sig["entry_price"] + 300.0)) < 0.01


class TestConfidenceScoreSeed:
    """confidence_score 基于真实指标。"""

    def test_confidence_deterministic_across_runs(self) -> None:
        """同样的输入数据，两次调用产出相同 confidence。"""
        df = _make_strategy_df(signals=[{"index": 25, "enter_long": 1}])
        s1 = _extract_all_signals(df.copy(), "BTC/USDT", 1)
        s2 = _extract_all_signals(df.copy(), "BTC/USDT", 1)
        c1 = [s for s in s1 if s["signal_at"] == df.loc[25, "date"]][0]["confidence_score"]
        c2 = [s for s in s2 if s["signal_at"] == df.loc[25, "date"]][0]["confidence_score"]
        assert c1 == c2

    def test_confidence_within_valid_range(self) -> None:
        """confidence 在 [0.50, 0.95] 范围内。"""
        df = _make_strategy_df(
            signals=[
                {"index": 22, "enter_long": 1},
                {"index": 25, "enter_short": 1},
                {"index": 28, "exit_long": 1},
            ]
        )
        signals = _extract_all_signals(df, "BTC/USDT", 1)
        for s in signals:
            assert 0.50 <= s["confidence_score"] <= 0.95


class TestSignalStrengthSeed:
    """signal_strength 入场/出场区分。"""

    def test_entry_strength_075(self) -> None:
        df = _make_strategy_df(signals=[{"index": 25, "enter_long": 1}])
        signals = _extract_all_signals(df, "BTC/USDT", 1)
        sig = [s for s in signals if s["signal_at"] == df.loc[25, "date"]][0]
        assert sig["signal_strength"] == 0.75

    def test_exit_strength_050(self) -> None:
        df = _make_strategy_df(signals=[{"index": 25, "exit_long": 1}])
        signals = _extract_all_signals(df, "BTC/USDT", 1)
        sig = [s for s in signals if s["signal_at"] == df.loc[25, "date"]][0]
        assert sig["signal_strength"] == 0.50


class TestVolatility:
    """volatility 计算测试。"""

    def test_early_index_returns_zero(self) -> None:
        """index < 20 时 volatility = 0.0。"""
        df = _make_strategy_df(n=25, signals=[{"index": 5, "enter_long": 1}])
        signals = _extract_all_signals(df, "BTC/USDT", 1)
        sig = [s for s in signals if s["signal_at"] == df.loc[5, "date"]][0]
        assert sig["volatility"] == 0.0

    def test_later_index_returns_positive_volatility(self) -> None:
        """index >= 20 时 volatility > 0。"""
        df = _make_strategy_df(n=30, signals=[{"index": 25, "enter_long": 1}])
        signals = _extract_all_signals(df, "BTC/USDT", 1)
        sig = [s for s in signals if s["signal_at"] == df.loc[25, "date"]][0]
        assert sig["volatility"] > 0.0


class TestIndicatorValues:
    """indicator_values 快照测试。"""

    def test_contains_strategy_indicators(self) -> None:
        """indicator_values 包含策略计算的指标（atr, rsi 等）。"""
        df = _make_strategy_df(signals=[{"index": 25, "enter_long": 1}])
        signals = _extract_all_signals(df, "BTC/USDT", 1)
        sig = [s for s in signals if s["signal_at"] == df.loc[25, "date"]][0]
        assert "atr" in sig["indicator_values"]
        assert "rsi" in sig["indicator_values"]

    def test_excludes_ohlcv_and_signal_columns(self) -> None:
        """indicator_values 不包含 OHLCV 和信号列。"""
        df = _make_strategy_df(signals=[{"index": 25, "enter_long": 1}])
        signals = _extract_all_signals(df, "BTC/USDT", 1)
        sig = [s for s in signals if s["signal_at"] == df.loc[25, "date"]][0]
        forbidden = {
            "date",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "enter_long",
            "exit_long",
            "enter_short",
            "exit_short",
        }
        assert forbidden.isdisjoint(sig["indicator_values"].keys())
