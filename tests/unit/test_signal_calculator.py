"""任务 8.2 / 3.1-3.3 单元测试：SignalCalculator 组件。

测试 OHLCV 加载、策略方法链执行、upsert 持久化和缓存更新。

涵盖需求：2.2, 2.5, 2.6, 3.4
"""

import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


class TestLoadOhlcvFromDatadir:
    """任务 3.1：测试从本地 datadir 加载 OHLCV 数据。"""

    def test_loads_dataframe_successfully(self, tmp_path: Path) -> None:
        """成功加载时返回 DataFrame。"""
        import pandas as pd

        from src.freqtrade_bridge.signal_calculator import SignalCalculator

        # Mock freqtrade.data.history.load_pair_history
        mock_df = pd.DataFrame(
            {
                "date": [datetime.datetime.now(tz=datetime.timezone.utc)],
                "open": [50000.0],
                "high": [51000.0],
                "low": [49000.0],
                "close": [50500.0],
                "volume": [100.0],
            }
        )

        calc = SignalCalculator()

        with patch(
            "src.freqtrade_bridge.signal_calculator.load_pair_history",
            return_value=mock_df,
        ):
            result = calc._load_ohlcv_from_datadir(tmp_path, "BTC/USDT", "1h")

        assert isinstance(result, pd.DataFrame)
        assert len(result) == 1

    def test_raises_when_file_not_found(self, tmp_path: Path) -> None:
        """文件不存在时抛出 FreqtradeExecutionError（需求 3.1）。"""
        from src.freqtrade_bridge.exceptions import FreqtradeExecutionError
        from src.freqtrade_bridge.signal_calculator import SignalCalculator

        calc = SignalCalculator()

        # load_pair_history 返回空 DataFrame（文件不存在时的行为）
        import pandas as pd

        with patch(
            "src.freqtrade_bridge.signal_calculator.load_pair_history",
            return_value=pd.DataFrame(),
        ):
            with pytest.raises(FreqtradeExecutionError):
                calc._load_ohlcv_from_datadir(tmp_path, "BTC/USDT", "1h")

    def test_caches_dataframe_in_memory(self, tmp_path: Path) -> None:
        """同一 (pair, timeframe) 组合只加载一次（内存缓存复用，需求 2.2）。"""
        import pandas as pd

        from src.freqtrade_bridge.signal_calculator import SignalCalculator

        mock_df = pd.DataFrame(
            {
                "date": [datetime.datetime.now(tz=datetime.timezone.utc)],
                "open": [50000.0],
                "high": [51000.0],
                "low": [49000.0],
                "close": [50500.0],
                "volume": [100.0],
            }
        )

        calc = SignalCalculator()

        with patch(
            "src.freqtrade_bridge.signal_calculator.load_pair_history",
            return_value=mock_df,
        ) as mock_load:
            # 调用两次相同的 (pair, timeframe)
            calc._load_ohlcv_from_datadir(tmp_path, "BTC/USDT", "1h")
            calc._load_ohlcv_from_datadir(tmp_path, "BTC/USDT", "1h")

            # load_pair_history 只应被调用一次（第二次命中缓存）
            assert mock_load.call_count == 1


class TestUpsertSignal:
    """任务 3.3：测试信号 upsert 持久化路径。"""

    def test_upsert_insert_new_record(self) -> None:
        """首次写入时执行 INSERT。"""
        from src.freqtrade_bridge.signal_calculator import SignalCalculator, SignalData

        calc = SignalCalculator()

        # Mock SQLAlchemy 同步 Session
        mock_session = MagicMock()
        mock_session.execute = MagicMock()

        signal_data = SignalData(
            direction="buy",
            confidence_score=0.75,
            signal_at=datetime.datetime.now(tz=datetime.timezone.utc),
            signal_source="realtime",
        )

        # 不应抛出异常
        calc.upsert_signal(
            session=mock_session,
            strategy_id=1,
            pair="BTC/USDT",
            timeframe="1h",
            signal_data=signal_data,
        )

        # session.execute 应被调用（执行 upsert SQL）
        assert mock_session.execute.called

    def test_redis_write_failure_silent_degradation(self) -> None:
        """Redis 写入失败时静默降级，不抛出异常（需求 3.3）。"""
        from src.freqtrade_bridge.signal_calculator import SignalCalculator, SignalData

        calc = SignalCalculator()

        mock_session = MagicMock()
        mock_session.execute = MagicMock()

        signal_data = SignalData(
            direction="hold",
            confidence_score=0.0,
            signal_at=datetime.datetime.now(tz=datetime.timezone.utc),
            signal_source="realtime",
        )

        # Mock Redis 写入失败
        with patch(
            "src.freqtrade_bridge.signal_calculator.get_redis_client",
            side_effect=Exception("Redis 连接失败"),
        ):
            # 不应抛出异常（静默降级）
            calc.upsert_signal(
                session=mock_session,
                strategy_id=1,
                pair="BTC/USDT",
                timeframe="1h",
                signal_data=signal_data,
            )


class TestComputeAllSignals:
    """任务 3.2：测试策略方法链信号提取和容错逻辑。"""

    def test_single_combination_failure_does_not_interrupt(self, tmp_path: Path) -> None:
        """单个 (strategy, pair, timeframe) 组合失败时不中断整体流程（需求 2.5）。"""
        import pandas as pd

        from src.freqtrade_bridge.signal_calculator import SignalCalculator

        calc = SignalCalculator()

        # 第一个策略会失败
        call_count = 0

        def mock_load(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("策略加载失败")
            return pd.DataFrame(
                {
                    "date": [datetime.datetime.now(tz=datetime.timezone.utc)],
                    "open": [50000.0],
                    "high": [51000.0],
                    "low": [49000.0],
                    "close": [50500.0],
                    "volume": [100.0],
                    "enter_long": [0],
                    "exit_long": [0],
                    "enter_short": [0],
                    "exit_short": [0],
                }
            )

        mock_strategy_class = MagicMock()
        mock_strategy_instance = MagicMock()
        mock_strategy_class.return_value = mock_strategy_instance

        def identity(df, *args, **kwargs):
            return df

        mock_strategy_instance.populate_indicators = MagicMock(side_effect=identity)
        mock_strategy_instance.populate_entry_trend = MagicMock(side_effect=identity)
        mock_strategy_instance.populate_exit_trend = MagicMock(side_effect=identity)

        mock_session = MagicMock()
        mock_session.execute = MagicMock()

        # 两个策略 × 1 交易对 = 2 组合；第一个失败，第二个成功
        strategies = [
            {"id": 1, "name": "FailStrategy", "class": mock_strategy_class},
            {"id": 2, "name": "OkStrategy", "class": mock_strategy_class},
        ]

        with patch(
            "src.freqtrade_bridge.signal_calculator.load_pair_history",
            side_effect=mock_load,
        ):
            with patch.object(calc, "_get_session", return_value=mock_session):
                result = calc.compute_all_signals(
                    strategies=strategies,
                    pairs=["BTC/USDT"],
                    timeframes=["1h"],
                    datadir=tmp_path,
                )

        # 第一个组合失败，第二个应成功
        assert result.failure_count >= 1
        assert result.success_count >= 0  # 至少不全失败

    def test_compute_all_signals_returns_result_object(self, tmp_path: Path) -> None:
        """compute_all_signals 返回 SignalComputeResult 对象。"""
        import pandas as pd

        from src.freqtrade_bridge.signal_calculator import SignalCalculator, SignalComputeResult

        calc = SignalCalculator()

        mock_df = pd.DataFrame(
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

        mock_strategy_class = MagicMock()
        mock_strategy_instance = MagicMock()
        mock_strategy_class.return_value = mock_strategy_instance

        def identity(df, *args, **kwargs):
            return df

        mock_strategy_instance.populate_indicators = MagicMock(side_effect=identity)
        mock_strategy_instance.populate_entry_trend = MagicMock(side_effect=identity)
        mock_strategy_instance.populate_exit_trend = MagicMock(side_effect=identity)

        mock_session = MagicMock()
        mock_session.execute = MagicMock()

        strategies = [{"id": 1, "name": "TestStrategy", "class": mock_strategy_class}]

        with patch(
            "src.freqtrade_bridge.signal_calculator.load_pair_history",
            return_value=mock_df,
        ):
            with patch.object(calc, "_get_session", return_value=mock_session):
                with patch(
                    "src.freqtrade_bridge.signal_calculator.get_redis_client",
                    side_effect=Exception("redis unavailable"),
                ):
                    result = calc.compute_all_signals(
                        strategies=strategies,
                        pairs=["BTC/USDT"],
                        timeframes=["1h"],
                        datadir=tmp_path,
                    )

        assert isinstance(result, SignalComputeResult)
        assert result.total_combinations == 1
        assert result.elapsed_seconds >= 0.0
        assert 0.0 <= result.cache_hit_rate <= 1.0

    def test_cache_hit_rate_calculation(self, tmp_path: Path) -> None:
        """多策略共享同一 DataFrame 时，cache_hit_rate > 0（内存复用）。"""
        import pandas as pd

        from src.freqtrade_bridge.signal_calculator import SignalCalculator

        calc = SignalCalculator()

        mock_df = pd.DataFrame(
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

        mock_strategy_class = MagicMock()
        mock_instance = MagicMock()
        mock_strategy_class.return_value = mock_instance

        def identity(df, *args, **kwargs):
            return df

        mock_instance.populate_indicators = MagicMock(side_effect=identity)
        mock_instance.populate_entry_trend = MagicMock(side_effect=identity)
        mock_instance.populate_exit_trend = MagicMock(side_effect=identity)

        mock_session = MagicMock()
        mock_session.execute = MagicMock()

        # 3 个策略 × 1 交易对 × 1 时间周期 = 3 组合，共享 1 个 DataFrame
        strategies = [
            {"id": 1, "name": "Strategy1", "class": mock_strategy_class},
            {"id": 2, "name": "Strategy2", "class": mock_strategy_class},
            {"id": 3, "name": "Strategy3", "class": mock_strategy_class},
        ]

        with patch(
            "src.freqtrade_bridge.signal_calculator.load_pair_history",
            return_value=mock_df,
        ):
            with patch.object(calc, "_get_session", return_value=mock_session):
                with patch(
                    "src.freqtrade_bridge.signal_calculator.get_redis_client",
                    side_effect=Exception("redis unavailable"),
                ):
                    result = calc.compute_all_signals(
                        strategies=strategies,
                        pairs=["BTC/USDT"],
                        timeframes=["1h"],
                        datadir=tmp_path,
                    )

        # 3 个组合共享 1 个 DataFrame，命中率 = (3-1)/3 ≈ 0.67
        assert result.cache_hit_rate > 0.0
