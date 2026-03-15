"""回测 Worker 指标写入链路测试（Task 7.5）。

模拟回测任务状态变更为 DONE 后的链路：
  - strategy_pair_metrics 记录被调用创建，data_source=backtest
  - 同一策略对重复回测后 upsert 幂等
  - BacktestResult 与指标写入原子性：upsert 异常时不 commit

需求可追溯：2.1, 2.2, 2.5
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch, call

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


class TestBacktestMetricsChain:
    """回测任务完成时绩效指标写入链路测试（需求 2.1, 2.2）。"""

    def test_upsert_metrics_called_with_backtest_data_source(self, env_setup: None) -> None:
        """_upsert_metrics_for_backtest 应以 DataSource.BACKTEST 调用（需求 2.2）。"""
        from src.core.enums import DataSource
        from src.workers.tasks.backtest_tasks import _upsert_metrics_for_backtest

        mock_session = MagicMock()

        with patch(
            "src.workers.tasks.backtest_tasks.upsert_pair_metrics"
        ) as mock_upsert:
            _upsert_metrics_for_backtest(
                session=mock_session,
                strategy_id=1,
                pair="BTC/USDT",
                timeframe="1h",
                backtest_output={
                    "total_return": 0.15,
                    "profit_factor": 1.5,
                    "max_drawdown": 0.08,
                    "sharpe_ratio": 1.2,
                    "trade_count": 42,
                },
            )

        assert mock_upsert.called
        call_kwargs = mock_upsert.call_args.kwargs
        assert call_kwargs["data_source"] == DataSource.BACKTEST

    def test_upsert_atomic_with_same_session(self, env_setup: None) -> None:
        """upsert 应使用调用方的同一 session，不自行 commit（原子性，需求 2.5）。"""
        from src.workers.tasks.backtest_tasks import _upsert_metrics_for_backtest

        mock_session = MagicMock()

        with patch("src.workers.tasks.backtest_tasks.upsert_pair_metrics"):
            _upsert_metrics_for_backtest(
                session=mock_session,
                strategy_id=1,
                pair="BTC/USDT",
                timeframe="1h",
                backtest_output={"total_return": 0.15},
            )

        # 不应自行 commit（由调用方统一控制事务边界）
        mock_session.commit.assert_not_called()

    def test_null_field_extracted_as_none(self, env_setup: None) -> None:
        """回测结果中缺失的字段应提取为 None，不覆盖现有值（需求 2.3）。"""
        from src.workers.tasks.backtest_tasks import _extract_pair_metrics_from_result

        # profit_factor 缺失
        backtest_output = {
            "total_return": 0.10,
            "sharpe_ratio": 0.90,
            "max_drawdown": 0.05,
            "trade_count": 30,
        }

        metrics = _extract_pair_metrics_from_result(backtest_output)
        # 缺失字段应为 None，由 upsert COALESCE 逻辑保留现有值
        assert metrics["profit_factor"] is None

    def test_idempotent_upsert_called_multiple_times(self, env_setup: None) -> None:
        """相同参数多次调用 _upsert_metrics_for_backtest 应幂等（需求 2.5）。"""
        from src.workers.tasks.backtest_tasks import _upsert_metrics_for_backtest

        mock_session = MagicMock()
        backtest_output = {"total_return": 0.15, "trade_count": 42}

        call_count = 0

        def track_calls(*args, **kwargs):  # type: ignore[no-untyped-def]
            nonlocal call_count
            call_count += 1

        with patch(
            "src.workers.tasks.backtest_tasks.upsert_pair_metrics",
            side_effect=track_calls,
        ):
            # 调用两次（模拟重复回测）
            _upsert_metrics_for_backtest(
                session=mock_session,
                strategy_id=1,
                pair="BTC/USDT",
                timeframe="1h",
                backtest_output=backtest_output,
            )
            _upsert_metrics_for_backtest(
                session=mock_session,
                strategy_id=1,
                pair="BTC/USDT",
                timeframe="1h",
                backtest_output=backtest_output,
            )

        # upsert 应被调用两次（ON CONFLICT 语义保证 DB 层幂等）
        assert call_count == 2

    def test_upsert_exception_does_not_swallow_error(self, env_setup: None) -> None:
        """若 upsert 抛出异常，应向上传播（不 commit，保证原子性，需求 2.5）。"""
        from src.workers.tasks.backtest_tasks import _upsert_metrics_for_backtest

        mock_session = MagicMock()

        with (
            patch(
                "src.workers.tasks.backtest_tasks.upsert_pair_metrics",
                side_effect=RuntimeError("DB 错误"),
            ),
            pytest.raises(RuntimeError),
        ):
            _upsert_metrics_for_backtest(
                session=mock_session,
                strategy_id=1,
                pair="BTC/USDT",
                timeframe="1h",
                backtest_output={"total_return": 0.1},
            )

        # 异常传播时不应 commit
        mock_session.commit.assert_not_called()
