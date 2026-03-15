"""回测 Worker 指标原子写入单元测试（Task 3）。

验证回测任务完成时，指标被正确提取并通过 upsert_pair_metrics 写入，
且与 BacktestResult 在同一事务内（原子性）。

需求可追溯：2.1, 2.2, 2.3, 2.4, 2.5
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


class TestExtractMetricsFromBacktestResult:
    """从回测结果提取指标字段的逻辑测试（需求 2.1）。"""

    def test_extract_total_return_from_profit_total(self, env_setup: None) -> None:
        """total_return 应映射自 backtest_output['total_return']（即 freqtrade profit_total）。"""
        from src.workers.tasks.backtest_tasks import _extract_pair_metrics_from_result

        backtest_output = {
            "total_return": 0.15,
            "annual_return": 0.20,
            "sharpe_ratio": 1.2,
            "max_drawdown": 0.08,
            "trade_count": 42,
            "win_rate": 0.60,
            "profit_factor": 1.5,
        }

        metrics = _extract_pair_metrics_from_result(backtest_output)
        assert metrics["total_return"] == 0.15

    def test_extract_profit_factor_from_result(self, env_setup: None) -> None:
        """profit_factor 应从回测结果中独立提取（需求 2.1）。"""
        from src.workers.tasks.backtest_tasks import _extract_pair_metrics_from_result

        backtest_output = {
            "total_return": 0.15,
            "profit_factor": 1.75,
            "sharpe_ratio": 1.2,
            "max_drawdown": 0.08,
            "trade_count": 42,
        }

        metrics = _extract_pair_metrics_from_result(backtest_output)
        assert metrics["profit_factor"] == 1.75

    def test_extract_all_five_metrics(self, env_setup: None) -> None:
        """应提取全部五个绩效指标（total_return, profit_factor, max_drawdown, sharpe_ratio, trade_count）。"""
        from src.workers.tasks.backtest_tasks import _extract_pair_metrics_from_result

        backtest_output = {
            "total_return": 0.10,
            "profit_factor": 1.30,
            "max_drawdown": 0.05,
            "sharpe_ratio": 0.90,
            "trade_count": 30,
        }

        metrics = _extract_pair_metrics_from_result(backtest_output)
        assert "total_return" in metrics
        assert "profit_factor" in metrics
        assert "max_drawdown" in metrics
        assert "sharpe_ratio" in metrics
        assert "trade_count" in metrics

    def test_missing_profit_factor_returns_none(self, env_setup: None) -> None:
        """回测结果中缺失 profit_factor 时，应返回 None（不覆盖现有值，需求 2.3）。"""
        from src.workers.tasks.backtest_tasks import _extract_pair_metrics_from_result

        backtest_output = {
            "total_return": 0.10,
            "sharpe_ratio": 0.90,
            "max_drawdown": 0.05,
            "trade_count": 30,
            # 故意省略 profit_factor
        }

        metrics = _extract_pair_metrics_from_result(backtest_output)
        assert metrics.get("profit_factor") is None


class TestBacktestTaskUpsertIntegration:
    """回测任务调用 upsert_pair_metrics 的集成行为测试（需求 2.1, 2.2, 2.5）。"""

    def test_upsert_pair_metrics_called_with_backtest_source(self, env_setup: None) -> None:
        """回测任务完成后应以 DataSource.BACKTEST 调用 upsert_pair_metrics（需求 2.2）。"""
        from src.core.enums import DataSource
        from src.workers.tasks.backtest_tasks import _upsert_metrics_for_backtest

        mock_session = MagicMock()

        with patch("src.workers.tasks.backtest_tasks.upsert_pair_metrics") as mock_upsert:
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

        mock_upsert.assert_called_once()
        call_kwargs = mock_upsert.call_args.kwargs
        assert call_kwargs["data_source"] == DataSource.BACKTEST

    def test_upsert_pair_metrics_called_with_correct_session(self, env_setup: None) -> None:
        """upsert_pair_metrics 应传入调用方提供的 session（不自行创建 session）。"""
        from src.workers.tasks.backtest_tasks import _upsert_metrics_for_backtest

        mock_session = MagicMock()

        with patch("src.workers.tasks.backtest_tasks.upsert_pair_metrics") as mock_upsert:
            _upsert_metrics_for_backtest(
                session=mock_session,
                strategy_id=1,
                pair="ETH/USDT",
                timeframe="4h",
                backtest_output={
                    "total_return": 0.08,
                    "profit_factor": 1.2,
                    "max_drawdown": 0.05,
                    "sharpe_ratio": 0.9,
                    "trade_count": 20,
                },
            )

        call_kwargs = mock_upsert.call_args.kwargs
        assert call_kwargs["session"] is mock_session

    def test_last_updated_at_is_utc_datetime(self, env_setup: None) -> None:
        """last_updated_at 应为当前 UTC datetime（需求 2.2）。"""
        from src.workers.tasks.backtest_tasks import _upsert_metrics_for_backtest

        mock_session = MagicMock()
        before = datetime.now(timezone.utc)

        with patch("src.workers.tasks.backtest_tasks.upsert_pair_metrics") as mock_upsert:
            _upsert_metrics_for_backtest(
                session=mock_session,
                strategy_id=1,
                pair="BTC/USDT",
                timeframe="1h",
                backtest_output={"total_return": 0.1, "trade_count": 10},
            )

        after = datetime.now(timezone.utc)
        call_kwargs = mock_upsert.call_args.kwargs
        last_updated_at = call_kwargs["last_updated_at"]

        assert last_updated_at.tzinfo is not None  # 必须含时区
        assert before <= last_updated_at <= after

    def test_upsert_not_committed_by_helper(self, env_setup: None) -> None:
        """_upsert_metrics_for_backtest 不应自行调用 session.commit()（原子性保证）。"""
        from src.workers.tasks.backtest_tasks import _upsert_metrics_for_backtest

        mock_session = MagicMock()

        with patch("src.workers.tasks.backtest_tasks.upsert_pair_metrics"):
            _upsert_metrics_for_backtest(
                session=mock_session,
                strategy_id=1,
                pair="BTC/USDT",
                timeframe="1h",
                backtest_output={"total_return": 0.1},
            )

        mock_session.commit.assert_not_called()
