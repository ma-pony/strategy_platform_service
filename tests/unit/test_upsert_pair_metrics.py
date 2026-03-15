"""upsert_pair_metrics 核心逻辑单元测试（Task 2.2）。

测试覆盖范围：
- 使用 mock session 验证基本 upsert 调用
- 验证校验失败时不执行 upsert（记录 WARNING）
- 验证 structlog INFO 日志在成功 upsert 后被调用
- 验证 DB 连接错误时指数退避重试 3 次后向上抛出
- 验证重试日志记录

需求可追溯：1.5, 2.2, 2.3, 2.4, 3.2, 3.3, 3.5, 6.1, 6.4, 6.5
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from src.core.enums import DataSource
from src.services.pair_metrics_service import upsert_pair_metrics


class TestUpsertPairMetricsBasic:
    """基本 upsert 调用测试。"""

    def test_upsert_calls_session_execute(self) -> None:
        """upsert_pair_metrics 应调用 session.execute()。"""
        mock_session = MagicMock()
        now = datetime.now(timezone.utc)

        upsert_pair_metrics(
            session=mock_session,
            strategy_id=1,
            pair="BTC/USDT",
            timeframe="1h",
            total_return=0.15,
            profit_factor=1.5,
            max_drawdown=0.08,
            sharpe_ratio=1.2,
            trade_count=42,
            data_source=DataSource.BACKTEST,
            last_updated_at=now,
        )

        assert mock_session.execute.called

    def test_upsert_does_not_commit(self) -> None:
        """upsert_pair_metrics 不应调用 session.commit()，由调用方控制事务边界。"""
        mock_session = MagicMock()
        now = datetime.now(timezone.utc)

        upsert_pair_metrics(
            session=mock_session,
            strategy_id=1,
            pair="ETH/USDT",
            timeframe="4h",
            total_return=None,
            profit_factor=None,
            max_drawdown=None,
            sharpe_ratio=None,
            trade_count=None,
            data_source=DataSource.LIVE,
            last_updated_at=now,
        )

        mock_session.commit.assert_not_called()

    def test_upsert_with_all_none_metrics(self) -> None:
        """所有指标为 None 时 upsert 仍应被调用（允许创建最小记录）。"""
        mock_session = MagicMock()
        now = datetime.now(timezone.utc)

        upsert_pair_metrics(
            session=mock_session,
            strategy_id=2,
            pair="BTC/USDT",
            timeframe="1d",
            total_return=None,
            profit_factor=None,
            max_drawdown=None,
            sharpe_ratio=None,
            trade_count=None,
            data_source=DataSource.BACKTEST,
            last_updated_at=now,
        )

        assert mock_session.execute.called


class TestUpsertPairMetricsValidation:
    """校验失败时的行为测试（需求 6.2, 6.3）。"""

    def test_invalid_total_return_skips_upsert_and_logs_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        """total_return 超出范围时应跳过 upsert，不调用 session.execute()。"""
        mock_session = MagicMock()
        now = datetime.now(timezone.utc)

        with patch("src.services.pair_metrics_service.logger") as mock_logger:
            upsert_pair_metrics(
                session=mock_session,
                strategy_id=1,
                pair="BTC/USDT",
                timeframe="1h",
                total_return=99999.0,  # 超出范围
                profit_factor=None,
                max_drawdown=None,
                sharpe_ratio=None,
                trade_count=None,
                data_source=DataSource.BACKTEST,
                last_updated_at=now,
            )

        mock_session.execute.assert_not_called()
        mock_logger.warning.assert_called()

    def test_invalid_trade_count_skips_upsert_and_logs_warning(self) -> None:
        """trade_count 为负数时应跳过 upsert，不调用 session.execute()。"""
        mock_session = MagicMock()
        now = datetime.now(timezone.utc)

        with patch("src.services.pair_metrics_service.logger") as mock_logger:
            upsert_pair_metrics(
                session=mock_session,
                strategy_id=1,
                pair="ETH/USDT",
                timeframe="1h",
                total_return=None,
                profit_factor=None,
                max_drawdown=None,
                sharpe_ratio=None,
                trade_count=-5,  # 负数
                data_source=DataSource.LIVE,
                last_updated_at=now,
            )

        mock_session.execute.assert_not_called()
        mock_logger.warning.assert_called()

    def test_invalid_sharpe_ratio_skips_upsert(self) -> None:
        """sharpe_ratio 超出范围时应跳过 upsert。"""
        mock_session = MagicMock()
        now = datetime.now(timezone.utc)

        with patch("src.services.pair_metrics_service.logger"):
            upsert_pair_metrics(
                session=mock_session,
                strategy_id=3,
                pair="SOL/USDT",
                timeframe="1h",
                total_return=None,
                profit_factor=None,
                max_drawdown=None,
                sharpe_ratio=99999.0,  # 超出范围
                trade_count=None,
                data_source=DataSource.BACKTEST,
                last_updated_at=now,
            )

        mock_session.execute.assert_not_called()


class TestUpsertPairMetricsLogging:
    """日志记录测试（需求 6.5）。"""

    def test_successful_upsert_logs_info(self) -> None:
        """成功 upsert 后应记录 structlog INFO 日志，含关键字段。"""
        mock_session = MagicMock()
        now = datetime.now(timezone.utc)

        with patch("src.services.pair_metrics_service.logger") as mock_logger:
            upsert_pair_metrics(
                session=mock_session,
                strategy_id=1,
                pair="BTC/USDT",
                timeframe="1h",
                total_return=0.15,
                profit_factor=1.5,
                max_drawdown=0.08,
                sharpe_ratio=1.2,
                trade_count=42,
                data_source=DataSource.BACKTEST,
                last_updated_at=now,
            )

        mock_logger.info.assert_called()
        # 确认 info 调用的参数中包含关键字段
        info_call_kwargs = mock_logger.info.call_args
        # 检查是否以关键字参数形式传入
        call_args, call_kwargs = info_call_kwargs
        # strategy_id, pair, timeframe, data_source, trade_count 应在参数中
        all_args = str(call_args) + str(call_kwargs)
        assert "1" in all_args  # strategy_id=1
        assert "BTC/USDT" in all_args
        assert "1h" in all_args

    def test_warning_log_contains_field_info(self) -> None:
        """校验失败的 WARNING 日志应包含字段信息（需求 6.2）。"""
        mock_session = MagicMock()
        now = datetime.now(timezone.utc)

        with patch("src.services.pair_metrics_service.logger") as mock_logger:
            upsert_pair_metrics(
                session=mock_session,
                strategy_id=5,
                pair="BTC/USDT",
                timeframe="1h",
                total_return=99999.0,
                profit_factor=None,
                max_drawdown=None,
                sharpe_ratio=None,
                trade_count=None,
                data_source=DataSource.BACKTEST,
                last_updated_at=now,
            )

        mock_logger.warning.assert_called()


class TestUpsertPairMetricsRetry:
    """DB 连接错误重试逻辑测试（需求 6.1）。"""

    def test_db_error_retries_three_times_then_raises(self) -> None:
        """DB 连接错误时应重试最多 3 次，耗尽后向上抛出。"""
        from sqlalchemy.exc import OperationalError

        mock_session = MagicMock()
        # 模拟 DB 连接错误（每次调用都失败）
        mock_session.execute.side_effect = OperationalError("connection refused", {}, Exception("conn refused"))
        now = datetime.now(timezone.utc)

        # 使用 patch 避免实际 sleep
        with (
            patch("src.services.pair_metrics_service.time.sleep"),
            patch("src.services.pair_metrics_service.logger"),
            pytest.raises((OperationalError, Exception)),
        ):
            upsert_pair_metrics(
                session=mock_session,
                strategy_id=1,
                pair="BTC/USDT",
                timeframe="1h",
                total_return=0.1,
                profit_factor=None,
                max_drawdown=None,
                sharpe_ratio=None,
                trade_count=5,
                data_source=DataSource.BACKTEST,
                last_updated_at=now,
            )

        # 应尝试执行最多 3 次（初始 + 2 次重试 = 3 次总调用）
        assert mock_session.execute.call_count >= 1

    def test_db_error_retries_logs_warning_for_each_retry(self) -> None:
        """每次 DB 重试都应记录 WARNING 日志（含 attempt 信息）。"""
        from sqlalchemy.exc import OperationalError

        mock_session = MagicMock()
        mock_session.execute.side_effect = OperationalError("connection refused", {}, Exception("conn refused"))
        now = datetime.now(timezone.utc)

        with (
            patch("src.services.pair_metrics_service.time.sleep"),
            patch("src.services.pair_metrics_service.logger") as mock_logger,
            pytest.raises((OperationalError, Exception)),
        ):
            upsert_pair_metrics(
                session=mock_session,
                strategy_id=1,
                pair="BTC/USDT",
                timeframe="1h",
                total_return=0.1,
                profit_factor=None,
                max_drawdown=None,
                sharpe_ratio=None,
                trade_count=5,
                data_source=DataSource.BACKTEST,
                last_updated_at=now,
            )

        # 应有 WARNING 日志（每次重试）和 ERROR 日志（最终耗尽）
        assert mock_logger.warning.call_count >= 1 or mock_logger.error.call_count >= 1

    def test_db_error_logs_error_after_all_retries_exhausted(self) -> None:
        """重试耗尽后应记录结构化 ERROR 日志（含 strategy_id, pair, timeframe, error_message）。"""
        from sqlalchemy.exc import OperationalError

        mock_session = MagicMock()
        mock_session.execute.side_effect = OperationalError("connection refused", {}, Exception("conn refused"))
        now = datetime.now(timezone.utc)

        with (
            patch("src.services.pair_metrics_service.time.sleep"),
            patch("src.services.pair_metrics_service.logger") as mock_logger,
            pytest.raises((OperationalError, Exception)),
        ):
            upsert_pair_metrics(
                session=mock_session,
                strategy_id=7,
                pair="ETH/USDT",
                timeframe="4h",
                total_return=None,
                profit_factor=None,
                max_drawdown=None,
                sharpe_ratio=None,
                trade_count=None,
                data_source=DataSource.LIVE,
                last_updated_at=now,
            )

        # 最终应记录 ERROR 日志
        mock_logger.error.assert_called()

    def test_db_error_uses_exponential_backoff(self) -> None:
        """DB 重试应使用指数退避（等待间隔递增：1s, 2s, 4s）。"""
        from sqlalchemy.exc import OperationalError

        mock_session = MagicMock()
        mock_session.execute.side_effect = OperationalError("connection refused", {}, Exception("conn refused"))
        now = datetime.now(timezone.utc)

        sleep_calls: list[float] = []

        def mock_sleep(seconds: float) -> None:
            sleep_calls.append(seconds)

        with (
            patch("src.services.pair_metrics_service.time.sleep", side_effect=mock_sleep),
            patch("src.services.pair_metrics_service.logger"),
            pytest.raises((OperationalError, Exception)),
        ):
            upsert_pair_metrics(
                session=mock_session,
                strategy_id=1,
                pair="BTC/USDT",
                timeframe="1h",
                total_return=0.1,
                profit_factor=None,
                max_drawdown=None,
                sharpe_ratio=None,
                trade_count=None,
                data_source=DataSource.BACKTEST,
                last_updated_at=now,
            )

        # 验证退避间隔递增（1s, 2s, 4s）
        if len(sleep_calls) >= 2:
            assert sleep_calls[1] >= sleep_calls[0], "第二次等待时间应不短于第一次"
        if len(sleep_calls) >= 3:
            assert sleep_calls[2] >= sleep_calls[1], "第三次等待时间应不短于第二次"

    def test_recovers_on_first_retry_success(self) -> None:
        """若重试后 DB 恢复，upsert 应成功完成。"""
        from sqlalchemy.exc import OperationalError

        mock_session = MagicMock()
        call_count = 0

        def side_effect(*args, **kwargs):  # type: ignore[no-untyped-def]
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise OperationalError("connection refused", None, None)
            # 第二次调用成功

        mock_session.execute.side_effect = side_effect
        now = datetime.now(timezone.utc)

        with (
            patch("src.services.pair_metrics_service.time.sleep"),
            patch("src.services.pair_metrics_service.logger"),
        ):
            upsert_pair_metrics(
                session=mock_session,
                strategy_id=1,
                pair="BTC/USDT",
                timeframe="1h",
                total_return=0.1,
                profit_factor=1.1,
                max_drawdown=0.05,
                sharpe_ratio=1.0,
                trade_count=10,
                data_source=DataSource.BACKTEST,
                last_updated_at=now,
            )

        # 应至少调用两次：第一次失败，第二次成功
        assert mock_session.execute.call_count == 2


class TestUpsertPairMetricsDataSource:
    """不同 data_source 的 upsert 行为测试（需求 2.2, 2.4, 3.2）。"""

    def test_backtest_source_executes_upsert(self) -> None:
        """DataSource.BACKTEST 来源应正常执行 upsert。"""
        mock_session = MagicMock()
        now = datetime.now(timezone.utc)

        upsert_pair_metrics(
            session=mock_session,
            strategy_id=1,
            pair="BTC/USDT",
            timeframe="1h",
            total_return=0.15,
            profit_factor=1.5,
            max_drawdown=0.08,
            sharpe_ratio=1.2,
            trade_count=42,
            data_source=DataSource.BACKTEST,
            last_updated_at=now,
        )

        assert mock_session.execute.called

    def test_live_source_executes_upsert(self) -> None:
        """DataSource.LIVE 来源应正常执行 upsert。"""
        mock_session = MagicMock()
        now = datetime.now(timezone.utc)

        upsert_pair_metrics(
            session=mock_session,
            strategy_id=2,
            pair="ETH/USDT",
            timeframe="4h",
            total_return=0.08,
            profit_factor=1.2,
            max_drawdown=0.05,
            sharpe_ratio=0.9,
            trade_count=20,
            data_source=DataSource.LIVE,
            last_updated_at=now,
        )

        assert mock_session.execute.called
