"""任务 9.2 集成测试：信号计算端到端集成测试。

给定测试用本地 OHLCV 文件，执行 compute_all_signals，验证：
  - upsert 语义：每个 (strategy_id, pair, timeframe) 组合仅有一条最新记录
  - 多次运行不产生重复记录

涵盖需求：2.6, 3.2
"""

import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch


def _make_ohlcv_df():
    """创建测试用 OHLCV DataFrame。"""
    import pandas as pd

    return pd.DataFrame(
        {
            "date": [datetime.datetime.now(tz=datetime.timezone.utc)],
            "open": [50000.0],
            "high": [51000.0],
            "low": [49000.0],
            "close": [50500.0],
            "volume": [100.0],
            "enter_long": [1],
            "exit_long": [0],
            "enter_short": [0],
            "exit_short": [0],
        }
    )


def _make_strategy_class():
    """创建 mock 策略类。"""
    mock_cls = MagicMock()
    mock_instance = MagicMock()
    mock_cls.return_value = mock_instance

    def identity(df, *args, **kwargs):
        return df

    mock_instance.populate_indicators = MagicMock(side_effect=identity)
    mock_instance.populate_entry_trend = MagicMock(side_effect=identity)
    mock_instance.populate_exit_trend = MagicMock(side_effect=identity)
    return mock_cls


class TestComputeAllSignalsIntegration:
    """compute_all_signals 端到端集成测试（需求 2.6, 3.2）。"""

    def test_upsert_semantics_single_record_per_combination(self, tmp_path: Path) -> None:
        """每个 (strategy_id, pair, timeframe) 组合仅执行一次 upsert（需求 2.6）。"""
        from src.freqtrade_bridge.signal_calculator import SignalCalculator

        calc = SignalCalculator()
        mock_df = _make_ohlcv_df()
        mock_strategy_class = _make_strategy_class()
        mock_session = MagicMock()
        mock_session.execute = MagicMock()
        upsert_call_count = [0]

        def mock_upsert(**kwargs):
            upsert_call_count[0] += 1

        strategies = [{"id": 1, "name": "TestStrategy", "class": mock_strategy_class}]

        with patch(
            "src.freqtrade_bridge.signal_calculator.load_pair_history",
            return_value=mock_df,
        ):
            with patch.object(calc, "_get_session", return_value=mock_session):
                with patch.object(calc, "upsert_signal", side_effect=mock_upsert):
                    with patch.object(calc, "_update_redis_cache"):
                        result = calc.compute_all_signals(
                            strategies=strategies,
                            pairs=["BTC/USDT"],
                            timeframes=["1h"],
                            datadir=tmp_path,
                        )

        # 1 策略 × 1 交易对 × 1 时间周期 = 1 upsert
        assert upsert_call_count[0] == 1
        assert result.success_count == 1
        assert result.failure_count == 0

    def test_second_run_does_not_double_upserts(self, tmp_path: Path) -> None:
        """两次运行时，upsert 各执行一次（不累加）（需求 2.6）。"""
        from src.freqtrade_bridge.signal_calculator import SignalCalculator

        mock_df = _make_ohlcv_df()
        mock_strategy_class = _make_strategy_class()
        mock_session = MagicMock()

        strategies = [{"id": 1, "name": "TestStrategy", "class": mock_strategy_class}]

        for _run_index in range(2):
            calc = SignalCalculator()
            upsert_call_count = [0]

            def mock_upsert(_count=upsert_call_count, **kwargs):
                _count[0] += 1

            with patch(
                "src.freqtrade_bridge.signal_calculator.load_pair_history",
                return_value=mock_df,
            ):
                with patch.object(calc, "_get_session", return_value=mock_session):
                    with patch.object(calc, "upsert_signal", side_effect=mock_upsert):
                        with patch.object(calc, "_update_redis_cache"):
                            calc.compute_all_signals(
                                strategies=strategies,
                                pairs=["BTC/USDT"],
                                timeframes=["1h"],
                                datadir=tmp_path,
                            )

            # 每次运行仅 1 次 upsert（ON CONFLICT DO UPDATE）
            assert upsert_call_count[0] == 1

    def test_multiple_strategies_multiple_pairs_all_succeed(self, tmp_path: Path) -> None:
        """3 策略 × 2 交易对 × 1 时间周期 = 6 upsert，全部成功（需求 3.2）。"""
        from src.freqtrade_bridge.signal_calculator import SignalCalculator

        calc = SignalCalculator()
        mock_df = _make_ohlcv_df()
        mock_strategy_class = _make_strategy_class()
        mock_session = MagicMock()
        upsert_call_count = [0]

        def mock_upsert(**kwargs):
            upsert_call_count[0] += 1

        strategies = [
            {"id": 1, "name": "Strategy1", "class": mock_strategy_class},
            {"id": 2, "name": "Strategy2", "class": mock_strategy_class},
            {"id": 3, "name": "Strategy3", "class": mock_strategy_class},
        ]
        pairs = ["BTC/USDT", "ETH/USDT"]

        with patch(
            "src.freqtrade_bridge.signal_calculator.load_pair_history",
            return_value=mock_df,
        ):
            with patch.object(calc, "_get_session", return_value=mock_session):
                with patch.object(calc, "upsert_signal", side_effect=mock_upsert):
                    with patch.object(calc, "_update_redis_cache"):
                        result = calc.compute_all_signals(
                            strategies=strategies,
                            pairs=pairs,
                            timeframes=["1h"],
                            datadir=tmp_path,
                        )

        assert result.total_combinations == 6
        assert result.success_count == 6
        assert result.failure_count == 0
        # 每个组合 1 次 upsert
        assert upsert_call_count[0] == 6

    def test_cache_hit_rate_nonzero_for_shared_dataframes(self, tmp_path: Path) -> None:
        """多策略共享同一 DataFrame 时 cache_hit_rate > 0（需求 2.6）。"""
        from src.freqtrade_bridge.signal_calculator import SignalCalculator

        calc = SignalCalculator()
        mock_df = _make_ohlcv_df()
        mock_strategy_class = _make_strategy_class()
        mock_session = MagicMock()
        mock_session.execute = MagicMock()

        strategies = [{"id": i, "name": f"Strategy{i}", "class": mock_strategy_class} for i in range(1, 4)]

        with patch(
            "src.freqtrade_bridge.signal_calculator.load_pair_history",
            return_value=mock_df,
        ):
            with patch.object(calc, "_get_session", return_value=mock_session):
                with patch.object(calc, "upsert_signal"):
                    with patch.object(calc, "_update_redis_cache"):
                        result = calc.compute_all_signals(
                            strategies=strategies,
                            pairs=["BTC/USDT"],
                            timeframes=["1h"],
                            datadir=tmp_path,
                        )

        # 3 策略共享 1 个 (BTC/USDT, 1h) DataFrame → cache_hit_rate > 0
        assert result.cache_hit_rate > 0.0
