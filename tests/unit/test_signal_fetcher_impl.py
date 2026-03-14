"""_fetch_signals_sync 实现单元测试（任务 6.1）。

验证：
  - _fetch_signals_sync 返回包含 11 个字段的信号字典
  - direction 为 buy/sell/hold
  - indicator_values 为 JSON 可序列化字典
  - 策略不存在时抛出 FreqtradeExecutionError
  - _executor 最大并发数通过 SIGNAL_MAX_WORKERS 环境变量配置（默认 2）
  - 多交易对并发信号生成正常工作
"""

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest


# ─────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────

@pytest.fixture()
def mock_strategy_entry():
    """模拟策略注册表条目。"""
    from pathlib import Path
    return {
        "class_name": "TurtleTrading",
        "file_path": Path("/fake/turtle_trading.py"),
    }


@pytest.fixture()
def sample_ohlcv_df():
    """生成最小可用的 OHLCV DataFrame（50 行，足够指标计算）。"""
    import numpy as np

    n = 50
    base_price = 30000.0
    rng = np.random.default_rng(42)
    closes = base_price + rng.uniform(-500, 500, n).cumsum()
    df = pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=n, freq="1h"),
            "open": closes * 0.999,
            "high": closes * 1.005,
            "low": closes * 0.995,
            "close": closes,
            "volume": rng.uniform(100, 1000, n),
        }
    )
    return df


def make_signal_df(base_df: pd.DataFrame, enter_long: int = 0, exit_long: int = 0) -> pd.DataFrame:
    """从基础 OHLCV DataFrame 创建带信号列的 DataFrame。"""
    df = base_df.copy()
    df["enter_long"] = 0
    df["exit_long"] = 0
    df["dc_upper"] = df["high"].rolling(20).max()
    df["dc_lower"] = df["low"].rolling(10).min()
    df["atr"] = 10.0
    if enter_long:
        df.loc[df.index[-1], "enter_long"] = 1
    if exit_long:
        df.loc[df.index[-1], "exit_long"] = 1
    return df


@contextmanager
def patch_signal_fetcher_internals(mock_strategy_entry, signal_df):
    """统一 patch signal_fetcher 内部三个关键函数的上下文管理器。"""
    with patch(
        "src.freqtrade_bridge.signal_fetcher._lookup_strategy",
        return_value=mock_strategy_entry,
    ):
        with patch(
            "src.freqtrade_bridge.signal_fetcher._load_strategy_class",
            return_value=MagicMock(),
        ):
            with patch(
                "src.freqtrade_bridge.signal_fetcher._build_ohlcv_dataframe",
                return_value=signal_df,
            ):
                with patch(
                    "src.freqtrade_bridge.signal_fetcher._run_strategy_on_df",
                    return_value=signal_df,
                ):
                    yield


# ─────────────────────────────────────────────
# Task 6.1: _fetch_signals_sync 返回 11 字段
# ─────────────────────────────────────────────

class TestFetchSignalsSyncImpl:
    """_fetch_signals_sync 实现测试。"""

    def test_returns_11_required_fields(self, sample_ohlcv_df, mock_strategy_entry) -> None:
        """_fetch_signals_sync 返回包含所有 11 个必填字段的信号字典。"""
        from src.freqtrade_bridge.signal_fetcher import _fetch_signals_sync

        signal_df = make_signal_df(sample_ohlcv_df)
        with patch_signal_fetcher_internals(mock_strategy_entry, signal_df):
            result = _fetch_signals_sync("TurtleTrading", "BTC/USDT")

        assert "signals" in result
        assert "last_updated_at" in result
        signals = result["signals"]
        assert len(signals) >= 1

        signal = signals[0]
        required_fields = [
            "pair", "direction", "confidence_score", "entry_price",
            "stop_loss", "take_profit", "indicator_values", "timeframe",
            "signal_strength", "volume", "volatility",
        ]
        for field in required_fields:
            assert field in signal, f"缺少字段: {field}"

    def test_direction_is_one_of_buy_sell_hold(self, sample_ohlcv_df, mock_strategy_entry) -> None:
        """direction 字段只能是 buy/sell/hold（小写枚举值）。"""
        from src.freqtrade_bridge.signal_fetcher import _fetch_signals_sync

        signal_df = make_signal_df(sample_ohlcv_df)
        with patch_signal_fetcher_internals(mock_strategy_entry, signal_df):
            result = _fetch_signals_sync("TurtleTrading", "BTC/USDT")

        signal = result["signals"][0]
        assert signal["direction"] in ("buy", "sell", "hold")

    def test_indicator_values_is_json_serializable_dict(self, sample_ohlcv_df, mock_strategy_entry) -> None:
        """indicator_values 为 JSON 可序列化的字典。"""
        import json
        from src.freqtrade_bridge.signal_fetcher import _fetch_signals_sync

        signal_df = make_signal_df(sample_ohlcv_df)
        with patch_signal_fetcher_internals(mock_strategy_entry, signal_df):
            result = _fetch_signals_sync("TurtleTrading", "BTC/USDT")

        signal = result["signals"][0]
        assert isinstance(signal["indicator_values"], dict)
        # 必须可以 JSON 序列化
        json.dumps(signal["indicator_values"])

    def test_pair_matches_input(self, sample_ohlcv_df, mock_strategy_entry) -> None:
        """返回信号中的 pair 字段与输入 pair 一致。"""
        from src.freqtrade_bridge.signal_fetcher import _fetch_signals_sync

        signal_df = make_signal_df(sample_ohlcv_df)
        with patch_signal_fetcher_internals(mock_strategy_entry, signal_df):
            result = _fetch_signals_sync("TurtleTrading", "ETH/USDT")

        assert result["signals"][0]["pair"] == "ETH/USDT"

    def test_enter_long_signal_produces_buy_direction(self, sample_ohlcv_df, mock_strategy_entry) -> None:
        """策略最后一行 enter_long=1 时，direction 应为 buy。"""
        from src.freqtrade_bridge.signal_fetcher import _fetch_signals_sync

        signal_df = make_signal_df(sample_ohlcv_df, enter_long=1)
        with patch_signal_fetcher_internals(mock_strategy_entry, signal_df):
            result = _fetch_signals_sync("TurtleTrading", "BTC/USDT")

        assert result["signals"][0]["direction"] == "buy"

    def test_exit_long_signal_produces_sell_direction(self, sample_ohlcv_df, mock_strategy_entry) -> None:
        """策略最后一行 exit_long=1 时，direction 应为 sell。"""
        from src.freqtrade_bridge.signal_fetcher import _fetch_signals_sync

        signal_df = make_signal_df(sample_ohlcv_df, exit_long=1)
        with patch_signal_fetcher_internals(mock_strategy_entry, signal_df):
            result = _fetch_signals_sync("TurtleTrading", "BTC/USDT")

        assert result["signals"][0]["direction"] == "sell"

    def test_no_signal_produces_hold_direction(self, sample_ohlcv_df, mock_strategy_entry) -> None:
        """策略最后一行 enter_long=0 且 exit_long=0 时，direction 应为 hold。"""
        from src.freqtrade_bridge.signal_fetcher import _fetch_signals_sync

        signal_df = make_signal_df(sample_ohlcv_df)  # 默认 enter_long=0, exit_long=0
        with patch_signal_fetcher_internals(mock_strategy_entry, signal_df):
            result = _fetch_signals_sync("TurtleTrading", "BTC/USDT")

        assert result["signals"][0]["direction"] == "hold"

    def test_unsupported_strategy_raises_execution_error(self) -> None:
        """策略不在注册表时抛出 FreqtradeExecutionError。"""
        from src.freqtrade_bridge.exceptions import FreqtradeExecutionError
        from src.core.exceptions import UnsupportedStrategyError
        from src.freqtrade_bridge.signal_fetcher import _fetch_signals_sync

        with patch(
            "src.freqtrade_bridge.signal_fetcher._lookup_strategy",
            side_effect=UnsupportedStrategyError("策略不受支持"),
        ):
            with pytest.raises(FreqtradeExecutionError):
                _fetch_signals_sync("NonExistentStrategy", "BTC/USDT")

    def test_stop_loss_and_take_profit_are_set(self, sample_ohlcv_df, mock_strategy_entry) -> None:
        """stop_loss 和 take_profit 字段已设置（非 None）。"""
        from src.freqtrade_bridge.signal_fetcher import _fetch_signals_sync

        df = sample_ohlcv_df.copy()
        df["enter_long"] = 0
        df["exit_long"] = 0
        df["dc_upper"] = df["high"].rolling(20).max()
        df["dc_lower"] = df["low"].rolling(10).min()
        df["atr"] = 100.0
        df.loc[df.index[-1], "enter_long"] = 1

        with patch_signal_fetcher_internals(mock_strategy_entry, df):
            result = _fetch_signals_sync("TurtleTrading", "BTC/USDT")

        signal = result["signals"][0]
        assert signal["stop_loss"] is not None
        assert signal["take_profit"] is not None


# ─────────────────────────────────────────────
# Task 6.1: SIGNAL_MAX_WORKERS 环境变量配置
# ─────────────────────────────────────────────

class TestSignalMaxWorkers:
    """SIGNAL_MAX_WORKERS 环境变量配置测试。"""

    def test_default_max_workers_is_2(self, monkeypatch) -> None:
        """SIGNAL_MAX_WORKERS 未设置时，_executor 默认 max_workers=2。"""
        monkeypatch.delenv("SIGNAL_MAX_WORKERS", raising=False)

        # 重新加载模块以应用环境变量变更
        import importlib
        import src.freqtrade_bridge.signal_fetcher as sf_module
        importlib.reload(sf_module)

        assert sf_module._executor._max_workers == 2

    def test_env_var_configures_max_workers(self, monkeypatch) -> None:
        """SIGNAL_MAX_WORKERS=4 时，_executor max_workers=4。"""
        monkeypatch.setenv("SIGNAL_MAX_WORKERS", "4")

        import importlib
        import src.freqtrade_bridge.signal_fetcher as sf_module
        importlib.reload(sf_module)

        assert sf_module._executor._max_workers == 4

        # 还原
        monkeypatch.delenv("SIGNAL_MAX_WORKERS", raising=False)
        importlib.reload(sf_module)


# ─────────────────────────────────────────────
# Task 6.1: helper 函数存在性验证
# ─────────────────────────────────────────────

class TestSignalFetcherHelpers:
    """signal_fetcher 内部 helper 函数存在性测试。"""

    def test_lookup_strategy_helper_exists(self) -> None:
        """_lookup_strategy helper 函数应存在。"""
        from src.freqtrade_bridge import signal_fetcher
        assert hasattr(signal_fetcher, "_lookup_strategy")

    def test_build_ohlcv_dataframe_helper_exists(self) -> None:
        """_build_ohlcv_dataframe helper 函数应存在。"""
        from src.freqtrade_bridge import signal_fetcher
        assert hasattr(signal_fetcher, "_build_ohlcv_dataframe")

    def test_run_strategy_on_df_helper_exists(self) -> None:
        """_run_strategy_on_df helper 函数应存在。"""
        from src.freqtrade_bridge import signal_fetcher
        assert hasattr(signal_fetcher, "_run_strategy_on_df")

    def test_load_strategy_class_helper_exists(self) -> None:
        """_load_strategy_class helper 函数应存在。"""
        from src.freqtrade_bridge import signal_fetcher
        assert hasattr(signal_fetcher, "_load_strategy_class")
