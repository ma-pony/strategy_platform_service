"""Celery 异步任务单元测试（任务 7.1, 7.2, 7.3）。

验证：
  - Celery 应用初始化正确（broker/backend 配置）
  - 两条独立队列：backtest 和 signal
  - Celery Beat 定时计划配置正确
  - run_backtest_task 状态流转（PENDING → RUNNING → DONE | FAILED）
  - run_backtest_task 幂等性（当日已有 RUNNING/DONE 时跳过）
  - run_backtest_task acks_late=True、max_retries=3
  - generate_signals_task 写入 Redis 和持久化 DB
  - generate_signals_task 失败时记录警告日志，不影响缓存数据
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


class TestCeleryAppInit:
    """Celery 应用初始化测试。"""

    def test_celery_app_can_be_imported(self, env_setup) -> None:
        """Celery 应用模块可以被导入。"""
        from src.workers.celery_app import celery_app

        assert celery_app is not None

    def test_celery_app_has_correct_broker_config(self, env_setup) -> None:
        """Celery 以 Redis 作为 broker。"""
        from src.workers.celery_app import celery_app

        # broker_url 应包含 redis
        assert "redis" in celery_app.conf.broker_url.lower()

    def test_celery_app_has_correct_backend_config(self, env_setup) -> None:
        """Celery 以 Redis 作为 result backend。"""
        from src.workers.celery_app import celery_app

        assert celery_app.conf.result_backend is not None
        assert "redis" in celery_app.conf.result_backend.lower()

    def test_celery_app_has_backtest_queue(self, env_setup) -> None:
        """Celery 配置了 backtest 队列。"""
        from src.workers.celery_app import celery_app

        queue_names = [q.name for q in celery_app.conf.task_queues]
        assert "backtest" in queue_names

    def test_celery_app_has_signal_queue(self, env_setup) -> None:
        """Celery 配置了 signal 队列。"""
        from src.workers.celery_app import celery_app

        queue_names = [q.name for q in celery_app.conf.task_queues]
        assert "signal" in queue_names

    def test_celery_beat_schedule_contains_backtest_task(self, env_setup) -> None:
        """Celery Beat 定时计划包含回测任务（每日 02:00 UTC）。"""
        from src.workers.celery_app import celery_app

        schedule = celery_app.conf.beat_schedule
        assert schedule is not None
        # 至少有一个包含回测相关的任务
        schedule_names = list(schedule.keys())
        backtest_schedules = [name for name in schedule_names if "backtest" in name.lower()]
        assert len(backtest_schedules) >= 1

    def test_celery_beat_schedule_contains_signal_task(self, env_setup) -> None:
        """Celery Beat 定时计划包含信号生成任务（每 15 分钟）。"""
        from src.workers.celery_app import celery_app

        schedule = celery_app.conf.beat_schedule
        schedule_names = list(schedule.keys())
        signal_schedules = [name for name in schedule_names if "signal" in name.lower()]
        assert len(signal_schedules) >= 1


class TestRunBacktestTask:
    """run_backtest_task Celery 任务测试。"""

    def test_task_has_acks_late_true(self, env_setup) -> None:
        """run_backtest_task 配置 acks_late=True。"""
        from src.workers.tasks.backtest_tasks import run_backtest_task

        assert run_backtest_task.acks_late is True

    def test_task_has_max_retries_3(self, env_setup) -> None:
        """run_backtest_task 配置 max_retries=3。"""
        from src.workers.tasks.backtest_tasks import run_backtest_task

        assert run_backtest_task.max_retries == 3

    def test_task_skips_when_today_done_exists(self, env_setup) -> None:
        """当日已有 DONE 状态记录时，任务跳过（幂等设计）。"""
        from src.core.enums import TaskStatus
        from src.workers.tasks.backtest_tasks import run_backtest_task

        mock_session = MagicMock()
        mock_result = MagicMock()
        # 模拟存在 DONE 状态的回测任务
        mock_existing_task = MagicMock()
        mock_existing_task.status = TaskStatus.DONE
        mock_result.scalar_one_or_none.return_value = mock_existing_task
        mock_session.execute.return_value = mock_result

        with patch("src.workers.tasks.backtest_tasks.SyncSessionLocal") as mock_session_factory:
            mock_ctx = MagicMock()
            mock_ctx.__enter__ = MagicMock(return_value=mock_session)
            mock_ctx.__exit__ = MagicMock(return_value=False)
            mock_session_factory.return_value = mock_ctx

            # 任务应当跳过，不调用 freqtrade bridge
            with patch("src.workers.tasks.backtest_tasks.run_backtest_subprocess") as mock_bridge:
                run_backtest_task(strategy_id=1)
                mock_bridge.assert_not_called()

    def test_task_skips_when_today_running_exists(self, env_setup) -> None:
        """当日已有 RUNNING 状态记录时，任务跳过。"""
        from src.core.enums import TaskStatus
        from src.workers.tasks.backtest_tasks import run_backtest_task

        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_existing_task = MagicMock()
        mock_existing_task.status = TaskStatus.RUNNING
        mock_result.scalar_one_or_none.return_value = mock_existing_task
        mock_session.execute.return_value = mock_result

        with patch("src.workers.tasks.backtest_tasks.SyncSessionLocal") as mock_session_factory:
            mock_ctx = MagicMock()
            mock_ctx.__enter__ = MagicMock(return_value=mock_session)
            mock_ctx.__exit__ = MagicMock(return_value=False)
            mock_session_factory.return_value = mock_ctx

            with patch("src.workers.tasks.backtest_tasks.run_backtest_subprocess") as mock_bridge:
                run_backtest_task(strategy_id=1)
                mock_bridge.assert_not_called()

    def test_task_creates_backtest_result_on_success(self, env_setup) -> None:
        """任务成功时创建 BacktestResult 并更新 Task 为 DONE。"""
        from src.workers.tasks.backtest_tasks import run_backtest_task

        mock_session = MagicMock()

        # 第一次查询：无当日任务（允许执行）
        no_existing_result = MagicMock()
        no_existing_result.scalar_one_or_none.return_value = None

        # 第二次查询：获取 strategy
        mock_strategy = MagicMock()
        mock_strategy.id = 1
        mock_strategy.name = "TestStrategy"
        mock_strategy.config_params = {"timeframe": "5m"}
        strategy_result = MagicMock()
        strategy_result.scalar_one_or_none.return_value = mock_strategy

        # 第三次查询：无 PENDING 任务（新建）
        no_pending_result = MagicMock()
        no_pending_result.scalar_one_or_none.return_value = None
        mock_session.execute.side_effect = [no_existing_result, strategy_result, no_pending_result]
        mock_session.add = MagicMock()
        mock_session.commit = MagicMock()
        mock_session.flush = MagicMock()

        backtest_output = {
            "total_return": 0.15,
            "annual_return": 0.45,
            "sharpe_ratio": 1.8,
            "max_drawdown": 0.12,
            "trade_count": 100,
            "win_rate": 0.62,
            "period_start": "2024-01-01T00:00:00",
            "period_end": "2024-12-31T23:59:59",
        }

        mock_file_path = MagicMock()
        mock_file_path.exists.return_value = False
        mock_registry_entry = {
            "class_name": "TestStrategy",
            "file_path": mock_file_path,
        }

        with patch("src.workers.tasks.backtest_tasks.SyncSessionLocal") as mock_session_factory:
            mock_ctx = MagicMock()
            mock_ctx.__enter__ = MagicMock(return_value=mock_session)
            mock_ctx.__exit__ = MagicMock(return_value=False)
            mock_session_factory.return_value = mock_ctx

            with patch("src.freqtrade_bridge.strategy_registry.lookup", return_value=mock_registry_entry):
                with patch("src.workers.tasks.backtest_tasks.run_backtest_subprocess", return_value=backtest_output):
                    with patch("src.workers.tasks.backtest_tasks.generate_config") as mock_gen_config:
                        with patch("src.workers.tasks.backtest_tasks.cleanup_task_dir"):
                            mock_config_path = MagicMock()
                            mock_gen_config.return_value = mock_config_path

                            run_backtest_task(strategy_id=1)

                            # 应当 add 多次：BacktestTask 和 BacktestResult
                            assert mock_session.add.call_count >= 2

    def test_task_marks_failed_on_execution_error(self, env_setup) -> None:
        """FreqtradeExecutionError 时更新 Task 为 FAILED。"""
        from src.freqtrade_bridge.exceptions import FreqtradeExecutionError
        from src.workers.tasks.backtest_tasks import run_backtest_task

        mock_session = MagicMock()

        no_existing_result = MagicMock()
        no_existing_result.scalar_one_or_none.return_value = None

        mock_strategy = MagicMock()
        mock_strategy.id = 1
        mock_strategy.name = "TestStrategy"
        mock_strategy.config_params = {}
        strategy_result = MagicMock()
        strategy_result.scalar_one_or_none.return_value = mock_strategy

        # 第三次查询：无 PENDING 任务（新建）
        no_pending_result = MagicMock()
        no_pending_result.scalar_one_or_none.return_value = None
        mock_session.execute.side_effect = [no_existing_result, strategy_result, no_pending_result]
        mock_session.add = MagicMock()
        mock_session.commit = MagicMock()
        mock_session.flush = MagicMock()

        mock_file_path = MagicMock()
        mock_file_path.exists.return_value = False
        mock_registry_entry = {
            "class_name": "TestStrategy",
            "file_path": mock_file_path,
        }

        with patch("src.workers.tasks.backtest_tasks.SyncSessionLocal") as mock_session_factory:
            mock_ctx = MagicMock()
            mock_ctx.__enter__ = MagicMock(return_value=mock_session)
            mock_ctx.__exit__ = MagicMock(return_value=False)
            mock_session_factory.return_value = mock_ctx

            with patch("src.freqtrade_bridge.strategy_registry.lookup", return_value=mock_registry_entry):
                with patch(
                    "src.workers.tasks.backtest_tasks.run_backtest_subprocess",
                    side_effect=FreqtradeExecutionError("backtest failed"),
                ):
                    with patch("src.workers.tasks.backtest_tasks.generate_config") as mock_gen:
                        with patch("src.workers.tasks.backtest_tasks.cleanup_task_dir"):
                            mock_gen.return_value = MagicMock()
                            run_backtest_task(strategy_id=1)

                            # 即使失败也应当 commit（写入 FAILED 状态）
                            assert mock_session.commit.call_count >= 1

    def test_task_cleanup_called_on_failure(self, env_setup) -> None:
        """任务失败时，隔离目录清理函数仍被调用（finally 块）。"""
        from src.freqtrade_bridge.exceptions import FreqtradeExecutionError
        from src.workers.tasks.backtest_tasks import run_backtest_task

        mock_session = MagicMock()

        no_existing_result = MagicMock()
        no_existing_result.scalar_one_or_none.return_value = None

        mock_strategy = MagicMock()
        mock_strategy.id = 1
        mock_strategy.name = "TestStrategy"
        mock_strategy.config_params = {}
        strategy_result = MagicMock()
        strategy_result.scalar_one_or_none.return_value = mock_strategy

        # 第三次查询：无 PENDING 任务（新建）
        no_pending_result = MagicMock()
        no_pending_result.scalar_one_or_none.return_value = None
        mock_session.execute.side_effect = [no_existing_result, strategy_result, no_pending_result]
        mock_session.add = MagicMock()
        mock_session.commit = MagicMock()
        mock_session.flush = MagicMock()

        mock_file_path = MagicMock()
        mock_file_path.exists.return_value = False
        mock_registry_entry = {
            "class_name": "TestStrategy",
            "file_path": mock_file_path,
        }

        with patch("src.workers.tasks.backtest_tasks.SyncSessionLocal") as mock_session_factory:
            mock_ctx = MagicMock()
            mock_ctx.__enter__ = MagicMock(return_value=mock_session)
            mock_ctx.__exit__ = MagicMock(return_value=False)
            mock_session_factory.return_value = mock_ctx

            with patch("src.freqtrade_bridge.strategy_registry.lookup", return_value=mock_registry_entry):
                with patch(
                    "src.workers.tasks.backtest_tasks.run_backtest_subprocess",
                    side_effect=FreqtradeExecutionError("fail"),
                ):
                    with patch("src.workers.tasks.backtest_tasks.generate_config") as mock_gen:
                        with patch("src.workers.tasks.backtest_tasks.cleanup_task_dir") as mock_cleanup:
                            mock_gen.return_value = MagicMock()
                            run_backtest_task(strategy_id=1)

                            # cleanup 必须被调用（通过 finally）
                            mock_cleanup.assert_called_once()


class TestGenerateSignalsTask:
    """generate_signals_task Celery 任务测试。"""

    def test_task_writes_to_redis_on_success(self, env_setup) -> None:
        """信号生成成功时，结果写入 Redis（key: signal:{strategy_id}，TTL=3600）。"""
        from src.workers.tasks.signal_tasks import generate_signals_task

        mock_session = MagicMock()
        mock_session.add = MagicMock()
        mock_session.commit = MagicMock()

        signals_data = {
            "signals": [
                {
                    "pair": "BTC/USDT",
                    "direction": "buy",
                    "confidence_score": 0.85,
                    "signal_at": "2024-01-01T12:00:00",
                }
            ],
            "last_updated_at": "2024-01-01T12:00:00",
        }

        mock_redis = MagicMock()

        with patch("src.workers.tasks.signal_tasks.SyncSessionLocal") as mock_session_factory:
            mock_ctx = MagicMock()
            mock_ctx.__enter__ = MagicMock(return_value=mock_session)
            mock_ctx.__exit__ = MagicMock(return_value=False)
            mock_session_factory.return_value = mock_ctx

            with patch("src.workers.tasks.signal_tasks.fetch_signals_sync", return_value=signals_data):
                with patch("src.workers.tasks.signal_tasks.get_redis_client", return_value=mock_redis):
                    generate_signals_task(strategy_id=1, pair="BTC/USDT")

                    # 验证 Redis SET 被调用，key 包含 strategy_id
                    mock_redis.set.assert_called_once()
                    call_args = mock_redis.set.call_args
                    # 第一个参数应为 key，包含 "signal:1"
                    key_arg = call_args[0][0] if call_args[0] else call_args.kwargs.get("name", "")
                    assert "signal:1" in str(key_arg)
                    # 验证 TTL 为 3600
                    assert call_args.kwargs.get("ex") == 3600 or (len(call_args[0]) > 2 and call_args[0][2] == 3600)

    def test_task_persists_signal_to_db(self, env_setup) -> None:
        """信号生成成功时，持久化新的 TradingSignal 至数据库。"""
        from src.workers.tasks.signal_tasks import generate_signals_task

        mock_session = MagicMock()
        mock_session.add = MagicMock()
        mock_session.commit = MagicMock()

        signals_data = {
            "signals": [
                {
                    "pair": "BTC/USDT",
                    "direction": "buy",
                    "confidence_score": 0.85,
                    "signal_at": "2024-01-01T12:00:00",
                }
            ],
            "last_updated_at": "2024-01-01T12:00:00",
        }

        mock_redis = MagicMock()

        with patch("src.workers.tasks.signal_tasks.SyncSessionLocal") as mock_session_factory:
            mock_ctx = MagicMock()
            mock_ctx.__enter__ = MagicMock(return_value=mock_session)
            mock_ctx.__exit__ = MagicMock(return_value=False)
            mock_session_factory.return_value = mock_ctx

            with patch("src.workers.tasks.signal_tasks.fetch_signals_sync", return_value=signals_data):
                with patch("src.workers.tasks.signal_tasks.get_redis_client", return_value=mock_redis):
                    generate_signals_task(strategy_id=1, pair="BTC/USDT")

                    # 数据库 add 应被调用（持久化 TradingSignal）
                    mock_session.add.assert_called()
                    mock_session.commit.assert_called()

    def test_task_logs_warning_on_failure_not_exception(self, env_setup) -> None:
        """信号生成失败时记录 WARNING 日志，不向外抛出异常。"""
        from src.freqtrade_bridge.exceptions import FreqtradeExecutionError
        from src.workers.tasks.signal_tasks import generate_signals_task

        mock_redis = MagicMock()

        with patch("src.workers.tasks.signal_tasks.SyncSessionLocal") as mock_session_factory:
            mock_ctx = MagicMock()
            mock_ctx.__enter__ = MagicMock(return_value=MagicMock())
            mock_ctx.__exit__ = MagicMock(return_value=False)
            mock_session_factory.return_value = mock_ctx

            with patch(
                "src.workers.tasks.signal_tasks.fetch_signals_sync",
                side_effect=FreqtradeExecutionError("signal generation failed"),
            ):
                with patch("src.workers.tasks.signal_tasks.get_redis_client", return_value=mock_redis):
                    # 不应抛出异常
                    generate_signals_task(strategy_id=1, pair="BTC/USDT")

    def test_task_does_not_overwrite_redis_on_failure(self, env_setup) -> None:
        """信号生成失败时，不覆盖现有 Redis 缓存。"""
        from src.freqtrade_bridge.exceptions import FreqtradeExecutionError
        from src.workers.tasks.signal_tasks import generate_signals_task

        mock_redis = MagicMock()

        with patch("src.workers.tasks.signal_tasks.SyncSessionLocal") as mock_session_factory:
            mock_ctx = MagicMock()
            mock_ctx.__enter__ = MagicMock(return_value=MagicMock())
            mock_ctx.__exit__ = MagicMock(return_value=False)
            mock_session_factory.return_value = mock_ctx

            with patch(
                "src.workers.tasks.signal_tasks.fetch_signals_sync",
                side_effect=FreqtradeExecutionError("fail"),
            ):
                with patch("src.workers.tasks.signal_tasks.get_redis_client", return_value=mock_redis):
                    generate_signals_task(strategy_id=1, pair="BTC/USDT")

                    # Redis SET 不应被调用（不覆盖历史缓存）
                    mock_redis.set.assert_not_called()
