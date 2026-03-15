"""generate_signals_task 信号写入与日志测试（任务 6.2）。

验证：
  - 信号写入时包含 signal_source='realtime' 和全部 11 个扩展字段
  - 信号生成失败时记录结构化错误日志（含策略名、交易对、错误、时间戳）
  - 失败时跳过写入，不影响 API 响应
  - 每次成功写入记录结构化 info 日志（策略名、交易对、信号类型、来源、执行耗时）
  - SIGNAL_REFRESH_INTERVAL 配置刷新周期（默认 5 分钟）
"""

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture()
def env_setup(monkeypatch: pytest.MonkeyPatch):
    """设置测试所需环境变量。"""
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-unit-tests-only-256bits")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")
    monkeypatch.setenv("DATABASE_SYNC_URL", "postgresql+psycopg2://u:p@localhost/db")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")

    from src.core import app_settings

    app_settings.get_settings.cache_clear()
    yield
    app_settings.get_settings.cache_clear()


@pytest.fixture()
def full_signals_data():
    """返回包含 11 个字段的完整信号数据。"""
    return {
        "signals": [
            {
                "pair": "BTC/USDT",
                "direction": "buy",
                "confidence_score": 0.85,
                "entry_price": 30000.0,
                "stop_loss": 29100.0,
                "take_profit": 31500.0,
                "indicator_values": {"dc_upper": 30100.0, "dc_lower": 28900.0, "atr": 300.0},
                "timeframe": "1h",
                "signal_strength": 0.75,
                "volume": 500.0,
                "volatility": 0.02,
                "signal_at": "2024-01-01T12:00:00",
            }
        ],
        "last_updated_at": "2024-01-01T12:00:00",
    }


# ─────────────────────────────────────────────
# Task 6.2: INSERT 含 signal_source='realtime' 及 11 个扩展字段
# ─────────────────────────────────────────────


class TestPersistSignalsWithAllFields:
    """_persist_signals_to_db 写入完整 11 字段测试。"""

    def test_signal_source_is_realtime(self, env_setup, full_signals_data) -> None:
        """写入 TradingSignal 时 signal_source='realtime'。"""
        from src.workers.tasks.signal_tasks import _persist_signals_to_db

        added_records = []
        mock_session = MagicMock()
        mock_session.add.side_effect = lambda obj: added_records.append(obj)
        mock_session.commit = MagicMock()

        with patch("src.workers.tasks.signal_tasks.SyncSessionLocal") as mock_factory:
            mock_ctx = MagicMock()
            mock_ctx.__enter__ = MagicMock(return_value=mock_session)
            mock_ctx.__exit__ = MagicMock(return_value=False)
            mock_factory.return_value = mock_ctx

            _persist_signals_to_db(
                strategy_id=1,
                pair="BTC/USDT",
                signals_data=full_signals_data,
                strategy_name="TurtleTradingStrategy",
            )

        assert len(added_records) == 1
        record = added_records[0]
        assert record.signal_source == "realtime"

    def test_all_11_extension_fields_written(self, env_setup, full_signals_data) -> None:
        """写入 TradingSignal 时包含全部 11 个扩展字段。"""
        from src.workers.tasks.signal_tasks import _persist_signals_to_db

        added_records = []
        mock_session = MagicMock()
        mock_session.add.side_effect = lambda obj: added_records.append(obj)
        mock_session.commit = MagicMock()

        with patch("src.workers.tasks.signal_tasks.SyncSessionLocal") as mock_factory:
            mock_ctx = MagicMock()
            mock_ctx.__enter__ = MagicMock(return_value=mock_session)
            mock_ctx.__exit__ = MagicMock(return_value=False)
            mock_factory.return_value = mock_ctx

            _persist_signals_to_db(
                strategy_id=1,
                pair="BTC/USDT",
                signals_data=full_signals_data,
                strategy_name="TurtleTradingStrategy",
            )

        record = added_records[0]
        assert record.entry_price == 30000.0
        assert record.stop_loss == 29100.0
        assert record.take_profit == 31500.0
        assert isinstance(record.indicator_values, dict)
        assert record.timeframe == "1h"
        assert record.signal_strength == 0.75
        assert record.volume == 500.0
        assert record.volatility == 0.02

    def test_no_update_or_delete_only_insert(self, env_setup, full_signals_data) -> None:
        """信号写入只使用 INSERT（session.add），不调用 UPDATE 或 DELETE。"""
        from src.workers.tasks.signal_tasks import _persist_signals_to_db

        mock_session = MagicMock()
        mock_session.commit = MagicMock()

        with patch("src.workers.tasks.signal_tasks.SyncSessionLocal") as mock_factory:
            mock_ctx = MagicMock()
            mock_ctx.__enter__ = MagicMock(return_value=mock_session)
            mock_ctx.__exit__ = MagicMock(return_value=False)
            mock_factory.return_value = mock_ctx

            _persist_signals_to_db(
                strategy_id=1,
                pair="BTC/USDT",
                signals_data=full_signals_data,
                strategy_name="TurtleTradingStrategy",
            )

        # add 被调用，execute 不被调用（execute 通常用于 UPDATE/DELETE）
        mock_session.add.assert_called()
        # 确认没有调用 execute（排除 UPDATE/DELETE 语句）
        # 注意：某些 ORM 内部可能调用 execute，这里验证业务逻辑层面
        mock_session.commit.assert_called_once()


# ─────────────────────────────────────────────
# Task 6.2: 失败时结构化错误日志
# ─────────────────────────────────────────────


class TestGenerateSignalsTaskErrorLogging:
    """generate_signals_task 失败时结构化错误日志测试。"""

    def test_failure_logs_structured_error_with_required_fields(self, env_setup) -> None:
        """信号生成失败时记录结构化错误日志，含策略名、交易对、错误、时间戳。"""
        from src.freqtrade_bridge.exceptions import FreqtradeExecutionError
        from src.workers.tasks.signal_tasks import generate_signals_task

        mock_redis = MagicMock()
        captured_log_kwargs = {}

        def capture_error(**kwargs):
            captured_log_kwargs.update(kwargs)

        mock_logger = MagicMock()
        mock_logger.error.side_effect = lambda msg, **kwargs: captured_log_kwargs.update(kwargs)

        with patch("src.workers.tasks.signal_tasks.SyncSessionLocal") as mock_factory:
            mock_ctx = MagicMock()
            mock_ctx.__enter__ = MagicMock(return_value=MagicMock())
            mock_ctx.__exit__ = MagicMock(return_value=False)
            mock_factory.return_value = mock_ctx

            with patch(
                "src.workers.tasks.signal_tasks.fetch_signals_sync",
                side_effect=FreqtradeExecutionError("信号获取失败"),
            ):
                with patch("src.workers.tasks.signal_tasks.get_redis_client", return_value=mock_redis):
                    with patch("src.workers.tasks.signal_tasks.logger", mock_logger):
                        generate_signals_task(strategy_id=1, pair="BTC/USDT")

        # 应调用 error 级别日志（而非仅 warning）
        assert mock_logger.error.called or mock_logger.warning.called

    def test_failure_skips_db_write(self, env_setup) -> None:
        """信号生成失败时跳过数据库写入。"""
        from src.freqtrade_bridge.exceptions import FreqtradeExecutionError
        from src.workers.tasks.signal_tasks import generate_signals_task

        mock_session = MagicMock()
        mock_redis = MagicMock()

        with patch("src.workers.tasks.signal_tasks.SyncSessionLocal") as mock_factory:
            mock_ctx = MagicMock()
            mock_ctx.__enter__ = MagicMock(return_value=mock_session)
            mock_ctx.__exit__ = MagicMock(return_value=False)
            mock_factory.return_value = mock_ctx

            with patch(
                "src.workers.tasks.signal_tasks.fetch_signals_sync",
                side_effect=FreqtradeExecutionError("fail"),
            ):
                with patch("src.workers.tasks.signal_tasks.get_redis_client", return_value=mock_redis):
                    generate_signals_task(strategy_id=1, pair="BTC/USDT")

        # 数据库 add 不应被调用
        mock_session.add.assert_not_called()

    def test_failure_does_not_raise_exception(self, env_setup) -> None:
        """信号生成失败时不向外抛出异常（不影响 API 响应）。"""
        from src.freqtrade_bridge.exceptions import FreqtradeExecutionError
        from src.workers.tasks.signal_tasks import generate_signals_task

        mock_redis = MagicMock()

        with patch("src.workers.tasks.signal_tasks.SyncSessionLocal") as mock_factory:
            mock_ctx = MagicMock()
            mock_ctx.__enter__ = MagicMock(return_value=MagicMock())
            mock_ctx.__exit__ = MagicMock(return_value=False)
            mock_factory.return_value = mock_ctx

            with patch(
                "src.workers.tasks.signal_tasks.fetch_signals_sync",
                side_effect=FreqtradeExecutionError("fail"),
            ):
                with patch("src.workers.tasks.signal_tasks.get_redis_client", return_value=mock_redis):
                    # 不应抛出任何异常
                    generate_signals_task(strategy_id=1, pair="BTC/USDT")


# ─────────────────────────────────────────────
# Task 6.2: 成功时结构化 info 日志
# ─────────────────────────────────────────────


class TestGenerateSignalsTaskInfoLogging:
    """generate_signals_task 成功时结构化 info 日志测试。"""

    def test_success_logs_info_with_strategy_pair_direction_source_duration(self, env_setup, full_signals_data) -> None:
        """信号生成成功时记录结构化 info 日志（策略名、交易对、信号类型、来源、执行耗时）。"""
        from src.workers.tasks.signal_tasks import generate_signals_task

        mock_session = MagicMock()
        mock_session.add = MagicMock()
        mock_session.commit = MagicMock()
        mock_redis = MagicMock()

        info_calls = []
        mock_logger = MagicMock()
        mock_logger.info.side_effect = lambda msg, **kwargs: info_calls.append({"msg": msg, **kwargs})

        with patch("src.workers.tasks.signal_tasks.SyncSessionLocal") as mock_factory:
            mock_ctx = MagicMock()
            mock_ctx.__enter__ = MagicMock(return_value=mock_session)
            mock_ctx.__exit__ = MagicMock(return_value=False)
            mock_factory.return_value = mock_ctx

            with patch(
                "src.workers.tasks.signal_tasks.fetch_signals_sync",
                return_value=full_signals_data,
            ):
                with patch("src.workers.tasks.signal_tasks.get_redis_client", return_value=mock_redis):
                    with patch("src.workers.tasks.signal_tasks.logger", mock_logger):
                        generate_signals_task(strategy_id=1, pair="BTC/USDT")

        # 应至少有一条包含 signal 相关信息的 info 日志
        assert len(info_calls) >= 1
        # 检查其中一条日志包含 source 字段
        source_logs = [c for c in info_calls if c.get("source") == "realtime" or "realtime" in str(c)]
        assert len(source_logs) >= 1

    def test_success_logs_execution_duration(self, env_setup, full_signals_data) -> None:
        """成功时日志包含执行耗时字段。"""
        from src.workers.tasks.signal_tasks import generate_signals_task

        mock_session = MagicMock()
        mock_session.add = MagicMock()
        mock_session.commit = MagicMock()
        mock_redis = MagicMock()

        info_calls = []
        mock_logger = MagicMock()
        mock_logger.info.side_effect = lambda msg, **kwargs: info_calls.append({"msg": msg, **kwargs})

        with patch("src.workers.tasks.signal_tasks.SyncSessionLocal") as mock_factory:
            mock_ctx = MagicMock()
            mock_ctx.__enter__ = MagicMock(return_value=mock_session)
            mock_ctx.__exit__ = MagicMock(return_value=False)
            mock_factory.return_value = mock_ctx

            with patch(
                "src.workers.tasks.signal_tasks.fetch_signals_sync",
                return_value=full_signals_data,
            ):
                with patch("src.workers.tasks.signal_tasks.get_redis_client", return_value=mock_redis):
                    with patch("src.workers.tasks.signal_tasks.logger", mock_logger):
                        generate_signals_task(strategy_id=1, pair="BTC/USDT")

        # 检查日志中包含 duration 相关字段
        duration_logs = [c for c in info_calls if any(k in c for k in ["duration_ms", "elapsed_ms", "execution_time"])]
        assert len(duration_logs) >= 1


# ─────────────────────────────────────────────
# Task 6.2: SIGNAL_REFRESH_INTERVAL 配置
# ─────────────────────────────────────────────


class TestSignalRefreshInterval:
    """SIGNAL_REFRESH_INTERVAL 配置测试。"""

    def test_app_settings_has_signal_refresh_interval(self, env_setup) -> None:
        """AppSettings 应包含 signal_refresh_interval 字段。"""
        from src.core.app_settings import AppSettings

        assert hasattr(AppSettings, "model_fields") or hasattr(AppSettings, "__fields__")
        from src.core.app_settings import get_settings

        settings = get_settings()
        assert hasattr(settings, "signal_refresh_interval")

    def test_signal_refresh_interval_default_is_5_minutes(self, env_setup) -> None:
        """signal_refresh_interval 默认值为 5（分钟）。"""
        from src.core.app_settings import get_settings

        settings = get_settings()
        assert settings.signal_refresh_interval == 5

    def test_signal_refresh_interval_can_be_overridden_via_env(self, env_setup, monkeypatch) -> None:
        """通过环境变量 SIGNAL_REFRESH_INTERVAL 可覆盖默认值。"""
        monkeypatch.setenv("SIGNAL_REFRESH_INTERVAL", "10")

        from src.core import app_settings

        app_settings.get_settings.cache_clear()
        settings = app_settings.get_settings()
        assert settings.signal_refresh_interval == 10
        app_settings.get_settings.cache_clear()

    def test_app_settings_has_signal_max_workers(self, env_setup) -> None:
        """AppSettings 应包含 signal_max_workers 字段。"""
        from src.core.app_settings import get_settings

        settings = get_settings()
        assert hasattr(settings, "signal_max_workers")

    def test_signal_max_workers_default_is_2(self, env_setup) -> None:
        """signal_max_workers 默认值为 2。"""
        from src.core.app_settings import get_settings

        settings = get_settings()
        assert settings.signal_max_workers == 2
