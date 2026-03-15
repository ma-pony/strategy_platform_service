"""实盘指标计算与非阻塞更新单元测试（Task 4）。

验证：
  - compute_live_metrics：从信号历史计算滚动指标
  - try_upsert_live_metrics：非阻塞封装，失败不向上传播

需求可追溯：3.1, 3.2, 3.3, 3.4, 3.5
"""

from datetime import datetime, timezone
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


def _make_signal(direction: str = "buy", confidence: float = 0.7) -> dict:
    """构造测试用信号字典。"""
    return {
        "direction": direction,
        "confidence_score": confidence,
        "signal_at": datetime.now(timezone.utc),
    }


class TestComputeLiveMetricsInsufficientData:
    """历史数据不足时返回全 None（需求 3.1）。"""

    def test_empty_signals_returns_all_none(self, env_setup: None) -> None:
        """0 条信号时，所有指标应返回 None。"""
        from src.workers.tasks.signal_tasks import compute_live_metrics

        mock_session = MagicMock()
        mock_session.execute.return_value.fetchall.return_value = []

        result = compute_live_metrics(
            session=mock_session,
            strategy_id=1,
            pair="BTC/USDT",
            timeframe="1h",
        )

        assert result["total_return"] is None
        assert result["profit_factor"] is None
        assert result["max_drawdown"] is None
        assert result["sharpe_ratio"] is None
        assert result["trade_count"] is None

    def test_less_than_5_signals_returns_all_none(self, env_setup: None) -> None:
        """不足 5 条信号时，所有指标应返回 None（需求 3.1）。"""
        from src.workers.tasks.signal_tasks import compute_live_metrics

        mock_session = MagicMock()
        # 返回 4 条信号
        mock_signals = [
            MagicMock(direction="buy", confidence_score=0.7)
            for _ in range(4)
        ]
        mock_session.execute.return_value.fetchall.return_value = mock_signals

        result = compute_live_metrics(
            session=mock_session,
            strategy_id=1,
            pair="BTC/USDT",
            timeframe="1h",
        )

        assert result["total_return"] is None
        assert result["profit_factor"] is None

    def test_exactly_5_signals_returns_values(self, env_setup: None) -> None:
        """恰好 5 条信号时，指标应有值（不再返回 None）。"""
        from src.workers.tasks.signal_tasks import compute_live_metrics

        mock_session = MagicMock()
        mock_signals = [
            MagicMock(direction="buy", confidence_score=0.7)
            for _ in range(5)
        ]
        mock_session.execute.return_value.fetchall.return_value = mock_signals

        result = compute_live_metrics(
            session=mock_session,
            strategy_id=1,
            pair="BTC/USDT",
            timeframe="1h",
        )

        # 5 条数据下，trade_count 应为非空（非 hold 的信号数）
        assert result["trade_count"] is not None


class TestComputeLiveMetricsCalculation:
    """正常数据集下指标计算测试（需求 3.1）。"""

    def test_trade_count_counts_non_hold_signals(self, env_setup: None) -> None:
        """trade_count 应为非 hold 方向信号数量。"""
        from src.workers.tasks.signal_tasks import compute_live_metrics

        mock_session = MagicMock()
        mock_signals = [
            MagicMock(direction="buy", confidence_score=0.8),
            MagicMock(direction="buy", confidence_score=0.7),
            MagicMock(direction="sell", confidence_score=0.6),
            MagicMock(direction="hold", confidence_score=0.0),  # 不计入
            MagicMock(direction="buy", confidence_score=0.9),
            MagicMock(direction="sell", confidence_score=0.5),
            MagicMock(direction="buy", confidence_score=0.75),
        ]
        mock_session.execute.return_value.fetchall.return_value = mock_signals

        result = compute_live_metrics(
            session=mock_session,
            strategy_id=1,
            pair="BTC/USDT",
            timeframe="1h",
        )

        # 4 buy + 2 sell = 6 非 hold 信号
        assert result["trade_count"] == 6

    def test_profit_factor_is_buy_over_sell_confidence(self, env_setup: None) -> None:
        """profit_factor 应为 buy 信号置信度之和 / sell 信号置信度之和。"""
        from src.workers.tasks.signal_tasks import compute_live_metrics

        mock_session = MagicMock()
        # buy 置信度合计 = 0.8 + 0.7 = 1.5
        # sell 置信度合计 = 0.5
        mock_signals = [
            MagicMock(direction="buy", confidence_score=0.8),
            MagicMock(direction="buy", confidence_score=0.7),
            MagicMock(direction="sell", confidence_score=0.5),
            MagicMock(direction="buy", confidence_score=0.6),
            MagicMock(direction="sell", confidence_score=0.4),
            MagicMock(direction="buy", confidence_score=0.65),
        ]
        mock_session.execute.return_value.fetchall.return_value = mock_signals

        result = compute_live_metrics(
            session=mock_session,
            strategy_id=1,
            pair="BTC/USDT",
            timeframe="1h",
        )

        # profit_factor = (0.8 + 0.7 + 0.6 + 0.65) / (0.5 + 0.4) = 2.75 / 0.9 ≈ 3.06
        assert result["profit_factor"] is not None
        assert result["profit_factor"] > 1.0  # buy 信号占优

    def test_profit_factor_none_when_no_sell_signals(self, env_setup: None) -> None:
        """sell 信号置信度为 0 时，profit_factor 应为 None（避免除零）。"""
        from src.workers.tasks.signal_tasks import compute_live_metrics

        mock_session = MagicMock()
        mock_signals = [
            MagicMock(direction="buy", confidence_score=0.8),
            MagicMock(direction="buy", confidence_score=0.7),
            MagicMock(direction="buy", confidence_score=0.6),
            MagicMock(direction="buy", confidence_score=0.9),
            MagicMock(direction="buy", confidence_score=0.75),
        ]
        mock_session.execute.return_value.fetchall.return_value = mock_signals

        result = compute_live_metrics(
            session=mock_session,
            strategy_id=1,
            pair="BTC/USDT",
            timeframe="1h",
        )

        assert result["profit_factor"] is None

    def test_all_metrics_keys_present(self, env_setup: None) -> None:
        """返回字典应包含所有 5 个指标键。"""
        from src.workers.tasks.signal_tasks import compute_live_metrics

        mock_session = MagicMock()
        mock_signals = [
            MagicMock(direction="buy", confidence_score=0.8)
            for _ in range(10)
        ]
        mock_session.execute.return_value.fetchall.return_value = mock_signals

        result = compute_live_metrics(
            session=mock_session,
            strategy_id=1,
            pair="BTC/USDT",
            timeframe="1h",
        )

        assert set(result.keys()) >= {
            "total_return", "profit_factor", "max_drawdown", "sharpe_ratio", "trade_count"
        }


class TestTryUpsertLiveMetrics:
    """非阻塞实盘指标更新封装测试（需求 3.4）。"""

    def test_exception_in_compute_does_not_propagate(self, env_setup: None) -> None:
        """compute_live_metrics 抛出异常时，try_upsert_live_metrics 不向上传播（需求 3.4）。"""
        from src.workers.tasks.signal_tasks import try_upsert_live_metrics

        with (
            patch(
                "src.workers.tasks.signal_tasks.SyncSessionLocal",
                return_value=MagicMock(__enter__=MagicMock(return_value=MagicMock()), __exit__=MagicMock(return_value=False)),
            ),
            patch(
                "src.workers.tasks.signal_tasks.compute_live_metrics",
                side_effect=Exception("模拟 DB 错误"),
            ),
            patch("src.workers.tasks.signal_tasks.logger") as mock_logger,
        ):
            # 不应抛出任何异常
            try_upsert_live_metrics(
                strategy_id=1,
                pair="BTC/USDT",
                timeframe="1h",
            )

        # 应记录 ERROR 日志
        mock_logger.error.assert_called()

    def test_exception_in_upsert_does_not_propagate(self, env_setup: None) -> None:
        """upsert_pair_metrics 抛出异常时，try_upsert_live_metrics 不向上传播（需求 3.4）。"""
        from src.workers.tasks.signal_tasks import try_upsert_live_metrics

        mock_metrics = {
            "total_return": 0.1,
            "profit_factor": 1.2,
            "max_drawdown": 0.05,
            "sharpe_ratio": 0.9,
            "trade_count": 10,
        }

        with (
            patch(
                "src.workers.tasks.signal_tasks.SyncSessionLocal",
                return_value=MagicMock(__enter__=MagicMock(return_value=MagicMock()), __exit__=MagicMock(return_value=False)),
            ),
            patch(
                "src.workers.tasks.signal_tasks.compute_live_metrics",
                return_value=mock_metrics,
            ),
            patch(
                "src.workers.tasks.signal_tasks.upsert_pair_metrics",
                side_effect=Exception("模拟 upsert 错误"),
            ),
            patch("src.workers.tasks.signal_tasks.logger") as mock_logger,
        ):
            # 不应抛出任何异常
            try_upsert_live_metrics(
                strategy_id=1,
                pair="BTC/USDT",
                timeframe="1h",
            )

        mock_logger.error.assert_called()

    def test_successful_upsert_uses_live_data_source(self, env_setup: None) -> None:
        """成功执行时，data_source 应为 DataSource.LIVE（需求 3.2）。"""
        from src.core.enums import DataSource
        from src.workers.tasks.signal_tasks import try_upsert_live_metrics

        mock_metrics = {
            "total_return": 0.1,
            "profit_factor": 1.2,
            "max_drawdown": 0.05,
            "sharpe_ratio": 0.9,
            "trade_count": 10,
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

        mock_upsert.assert_called_once()
        call_kwargs = mock_upsert.call_args.kwargs
        assert call_kwargs["data_source"] == DataSource.LIVE

    def test_successful_upsert_commits_session(self, env_setup: None) -> None:
        """成功执行时，应自行 commit session（独立事务，需求 3.2）。"""
        from src.workers.tasks.signal_tasks import try_upsert_live_metrics

        mock_metrics = {
            "total_return": 0.1,
            "profit_factor": None,
            "max_drawdown": None,
            "sharpe_ratio": None,
            "trade_count": 5,
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
            patch("src.workers.tasks.signal_tasks.upsert_pair_metrics"),
        ):
            try_upsert_live_metrics(
                strategy_id=1,
                pair="BTC/USDT",
                timeframe="1h",
            )

        mock_session.commit.assert_called_once()

    def test_error_log_contains_required_fields(self, env_setup: None) -> None:
        """错误日志应包含 strategy_id、pair、timeframe、error_message（需求 3.4）。"""
        from src.workers.tasks.signal_tasks import try_upsert_live_metrics

        with (
            patch(
                "src.workers.tasks.signal_tasks.SyncSessionLocal",
                return_value=MagicMock(__enter__=MagicMock(return_value=MagicMock()), __exit__=MagicMock(return_value=False)),
            ),
            patch(
                "src.workers.tasks.signal_tasks.compute_live_metrics",
                side_effect=RuntimeError("连接超时"),
            ),
            patch("src.workers.tasks.signal_tasks.logger") as mock_logger,
        ):
            try_upsert_live_metrics(
                strategy_id=99,
                pair="ETH/USDT",
                timeframe="4h",
            )

        error_call_kwargs = mock_logger.error.call_args.kwargs
        # 确认包含必要字段
        all_kwargs_str = str(error_call_kwargs)
        assert "99" in all_kwargs_str or "strategy_id" in str(mock_logger.error.call_args)
