"""实盘信号 Worker 绩效指标更新链路测试（Task 7.6）。

验证：
  - 信号任务完成后 strategy_pair_metrics 被更新，data_source=live
  - 写入失败时信号任务主流程不中断

需求可追溯：3.1, 3.2, 3.4
"""

from unittest.mock import MagicMock, patch, AsyncMock

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


class TestLiveMetricsChain:
    """实盘信号 Worker 指标更新链路测试（需求 3.1, 3.2, 3.4）。"""

    def test_try_upsert_with_live_data_source(self, env_setup: None) -> None:
        """try_upsert_live_metrics 应以 DataSource.LIVE 调用 upsert（需求 3.2）。"""
        from src.core.enums import DataSource
        from src.workers.tasks.signal_tasks import try_upsert_live_metrics

        mock_metrics = {
            "total_return": 0.05,
            "profit_factor": 1.1,
            "max_drawdown": 0.03,
            "sharpe_ratio": 0.8,
            "trade_count": 8,
        }
        mock_session = MagicMock()

        with (
            patch(
                "src.workers.tasks.signal_tasks.SyncSessionLocal",
                return_value=MagicMock(
                    __enter__=MagicMock(return_value=mock_session),
                    __exit__=MagicMock(return_value=False),
                ),
            ),
            patch(
                "src.workers.tasks.signal_tasks.compute_live_metrics",
                return_value=mock_metrics,
            ),
            patch(
                "src.workers.tasks.signal_tasks.upsert_pair_metrics"
            ) as mock_upsert,
        ):
            try_upsert_live_metrics(
                strategy_id=1,
                pair="BTC/USDT",
                timeframe="1h",
            )

        assert mock_upsert.called
        assert mock_upsert.call_args.kwargs["data_source"] == DataSource.LIVE

    def test_db_error_does_not_interrupt_signal_task(self, env_setup: None) -> None:
        """DB 写入失败时不应向上传播异常，不中断信号任务（需求 3.4）。"""
        from src.workers.tasks.signal_tasks import try_upsert_live_metrics

        with (
            patch(
                "src.workers.tasks.signal_tasks.SyncSessionLocal",
                return_value=MagicMock(
                    __enter__=MagicMock(return_value=MagicMock()),
                    __exit__=MagicMock(return_value=False),
                ),
            ),
            patch(
                "src.workers.tasks.signal_tasks.compute_live_metrics",
                side_effect=Exception("DB 连接中断"),
            ),
            patch("src.workers.tasks.signal_tasks.logger"),
        ):
            # 不应抛出异常
            try_upsert_live_metrics(
                strategy_id=1,
                pair="BTC/USDT",
                timeframe="1h",
            )

    def test_compute_live_metrics_returns_all_keys(self, env_setup: None) -> None:
        """compute_live_metrics 返回字典应包含全部 5 个指标键（需求 3.1）。"""
        from src.workers.tasks.signal_tasks import compute_live_metrics

        mock_session = MagicMock()
        mock_signals = [
            MagicMock(direction="buy", confidence_score=0.8),
            MagicMock(direction="sell", confidence_score=0.5),
            MagicMock(direction="buy", confidence_score=0.7),
            MagicMock(direction="buy", confidence_score=0.6),
            MagicMock(direction="sell", confidence_score=0.4),
            MagicMock(direction="buy", confidence_score=0.75),
        ]
        mock_session.execute.return_value.fetchall.return_value = mock_signals

        result = compute_live_metrics(
            session=mock_session,
            strategy_id=1,
            pair="BTC/USDT",
            timeframe="1h",
        )

        assert "total_return" in result
        assert "profit_factor" in result
        assert "max_drawdown" in result
        assert "sharpe_ratio" in result
        assert "trade_count" in result

    def test_live_metrics_uses_independent_session(self, env_setup: None) -> None:
        """try_upsert_live_metrics 应使用独立的 SyncSessionLocal，不污染信号写入事务（需求 3.4）。"""
        from src.workers.tasks.signal_tasks import try_upsert_live_metrics

        mock_metrics = {"total_return": 0.1, "profit_factor": None, "max_drawdown": None, "sharpe_ratio": None, "trade_count": 5}

        session_factory_calls = []

        class MockSessionCtx:
            def __enter__(self):
                session_factory_calls.append("new_session")
                return MagicMock()

            def __exit__(self, *args):
                return False

        with (
            patch(
                "src.workers.tasks.signal_tasks.SyncSessionLocal",
                side_effect=lambda: MockSessionCtx(),
            ),
            patch(
                "src.workers.tasks.signal_tasks.compute_live_metrics",
                return_value=mock_metrics,
            ),
            patch("src.workers.tasks.signal_tasks.upsert_pair_metrics"),
        ):
            try_upsert_live_metrics(
                strategy_id=1,
                pair="ETH/USDT",
                timeframe="4h",
            )

        # 应创建独立 session
        assert len(session_factory_calls) == 1
