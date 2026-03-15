"""回测任务状态流转集成测试（任务 11.2）。

验证：
  - run_backtest_task（Mock freqtrade）：PENDING → RUNNING → DONE 状态流转
  - BacktestResult 六项指标正确写入，trading_signals 扩展 11 字段以 signal_source='backtest' 正确 INSERT
  - Strategy NULL 字段在 DONE 后被回测结果填充，非 NULL 字段不被覆盖
  - 任务结束后临时目录自动清理（finally 块）

Requirements: 1.4, 1.5, 1.6, 2.5, 3.3
"""

import datetime
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from src.core.enums import SignalDirection, TaskStatus


@pytest.fixture()
def env_setup(monkeypatch: pytest.MonkeyPatch):
    """设置测试所需环境变量并清除 settings 缓存。"""
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-backtest-status-flow-256bits!!")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")
    monkeypatch.setenv("DATABASE_SYNC_URL", "postgresql+psycopg2://u:p@localhost/db")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")

    from src.core import app_settings
    app_settings.get_settings.cache_clear()
    yield
    app_settings.get_settings.cache_clear()


def _make_mock_session():
    """创建配置好的 mock session，带有上下文管理器支持。"""
    mock_session = MagicMock()
    mock_session.add = MagicMock()
    mock_session.commit = MagicMock()
    mock_session.flush = MagicMock()
    return mock_session


def _make_session_factory(mock_session):
    """创建 mock session factory（支持 with 语句）。"""
    mock_factory = MagicMock()
    mock_ctx = MagicMock()
    mock_ctx.__enter__ = MagicMock(return_value=mock_session)
    mock_ctx.__exit__ = MagicMock(return_value=False)
    mock_factory.return_value = mock_ctx
    return mock_factory


def _make_mock_strategy(
    strategy_id: int = 1,
    name: str = "TurtleTradingStrategy",
    trade_count=None,
    max_drawdown=None,
    sharpe_ratio=None,
    win_rate=None,
):
    """创建 mock Strategy 对象，支持自定义 NULL/非 NULL 指标字段。"""
    mock_strategy = MagicMock()
    mock_strategy.id = strategy_id
    mock_strategy.name = name
    mock_strategy.config_params = {"timeframe": "1h"}
    mock_strategy.trade_count = trade_count
    mock_strategy.max_drawdown = max_drawdown
    mock_strategy.sharpe_ratio = sharpe_ratio
    mock_strategy.win_rate = win_rate
    return mock_strategy


def _make_backtest_output(with_signals: bool = True):
    """构造 freqtrade 回测输出字典，含六项指标和可选信号列表。"""
    output = {
        "total_return": 0.18,
        "annual_return": 0.54,
        "sharpe_ratio": 2.1,
        "max_drawdown": 0.08,
        "trade_count": 120,
        "win_rate": 0.65,
        "period_start": "2024-01-01T00:00:00",
        "period_end": "2024-06-30T23:59:59",
    }
    if with_signals:
        output["signals"] = [
            {
                "pair": "BTC/USDT",
                "direction": "buy",
                "confidence_score": 0.85,
                "entry_price": 45000.0,
                "stop_loss": 43000.0,
                "take_profit": 50000.0,
                "indicator_values": {"rsi": 35.5, "macd": 0.002},
                "timeframe": "1h",
                "signal_strength": 0.75,
                "volume": 1200000.0,
                "volatility": 0.032,
                "signal_at": "2024-03-15T10:00:00",
            },
            {
                "pair": "ETH/USDT",
                "direction": "sell",
                "confidence_score": 0.70,
                "entry_price": 2800.0,
                "stop_loss": 2900.0,
                "take_profit": 2600.0,
                "indicator_values": {"rsi": 72.0, "bb_upper": 2950.0},
                "timeframe": "1h",
                "signal_strength": 0.60,
                "volume": 800000.0,
                "volatility": 0.028,
                "signal_at": "2024-03-16T14:00:00",
            },
        ]
    return output


def _make_registry_entry(file_exists: bool = False):
    """创建 mock 策略注册表条目。"""
    mock_file_path = MagicMock(spec=Path)
    mock_file_path.exists.return_value = file_exists
    mock_file_path.name = "turtle_trading.py"
    return {
        "class_name": "TurtleTradingStrategy",
        "file_path": mock_file_path,
    }


class TestBacktestStatusFlow:
    """回测任务 PENDING → RUNNING → DONE 状态流转测试。"""

    def test_status_transitions_pending_running_done(self, env_setup) -> None:
        """验证任务状态依次经历 PENDING → RUNNING → DONE。"""
        from src.workers.tasks.backtest_tasks import run_backtest_task

        mock_session = _make_mock_session()

        # 第一次查询：无当日任务（允许执行）
        no_existing = MagicMock()
        no_existing.scalar_one_or_none.return_value = None

        # 第二次查询：获取 Strategy
        mock_strategy = _make_mock_strategy()
        strategy_result = MagicMock()
        strategy_result.scalar_one_or_none.return_value = mock_strategy

        # 第三次查询：无 PENDING 任务（新建）
        no_pending = MagicMock()
        no_pending.scalar_one_or_none.return_value = None
        mock_session.execute.side_effect = [no_existing, strategy_result, no_pending]

        # 跟踪 status 赋值顺序
        status_changes: list[TaskStatus] = []

        def track_task_status(value):
            if isinstance(value, TaskStatus):
                status_changes.append(value)

        # 使用真实 BacktestTask 来跟踪状态流转
        from src.models.backtest import BacktestTask, BacktestResult

        added_records: list = []

        def capture_add(record):
            added_records.append(record)
            # 如果是 BacktestTask，给它设置 id 以便后续使用
            if isinstance(record, BacktestTask):
                record.id = 42

        mock_session.add.side_effect = capture_add

        def capture_flush():
            # flush 后 BacktestTask 应已有 id
            pass

        mock_session.flush.side_effect = capture_flush

        with patch("src.workers.tasks.backtest_tasks.SyncSessionLocal", _make_session_factory(mock_session)):
            with patch("src.freqtrade_bridge.strategy_registry.lookup", return_value=_make_registry_entry()):
                with patch("src.workers.tasks.backtest_tasks.run_backtest_subprocess", return_value=_make_backtest_output()):
                    with patch("src.workers.tasks.backtest_tasks.generate_config", return_value=MagicMock()):
                        with patch("src.workers.tasks.backtest_tasks.cleanup_task_dir"):
                            run_backtest_task(strategy_id=1)

        # 验证添加了 BacktestTask 和 BacktestResult
        task_records = [r for r in added_records if isinstance(r, BacktestTask)]
        result_records = [r for r in added_records if isinstance(r, BacktestResult)]
        assert len(task_records) == 1, "应创建一条 BacktestTask 记录"
        assert len(result_records) == 1, "应创建一条 BacktestResult 记录"

        # 验证 BacktestTask 最终状态为 DONE
        task_record = task_records[0]
        assert task_record.status == TaskStatus.DONE, f"最终状态应为 DONE，实际为 {task_record.status}"

    def test_initial_status_is_pending(self, env_setup) -> None:
        """验证任务创建时初始状态为 PENDING。"""
        from src.models.backtest import BacktestTask
        from src.workers.tasks.backtest_tasks import run_backtest_task

        mock_session = _make_mock_session()
        no_existing = MagicMock()
        no_existing.scalar_one_or_none.return_value = None
        strategy_result = MagicMock()
        strategy_result.scalar_one_or_none.return_value = _make_mock_strategy()
        # 第三次查询：无 PENDING 任务（新建）
        no_pending = MagicMock()
        no_pending.scalar_one_or_none.return_value = None
        mock_session.execute.side_effect = [no_existing, strategy_result, no_pending]

        initial_statuses: list[TaskStatus] = []

        def capture_add(record):
            if isinstance(record, BacktestTask):
                record.id = 1
                initial_statuses.append(record.status)

        mock_session.add.side_effect = capture_add

        with patch("src.workers.tasks.backtest_tasks.SyncSessionLocal", _make_session_factory(mock_session)):
            with patch("src.freqtrade_bridge.strategy_registry.lookup", return_value=_make_registry_entry()):
                with patch("src.workers.tasks.backtest_tasks.run_backtest_subprocess", return_value=_make_backtest_output()):
                    with patch("src.workers.tasks.backtest_tasks.generate_config", return_value=MagicMock()):
                        with patch("src.workers.tasks.backtest_tasks.cleanup_task_dir"):
                            run_backtest_task(strategy_id=1)

        # 验证 BacktestTask 创建时状态为 PENDING
        assert len(initial_statuses) >= 1
        assert initial_statuses[0] == TaskStatus.PENDING, "创建时状态应为 PENDING"

    def test_status_set_to_running_before_subprocess(self, env_setup) -> None:
        """验证执行子进程前状态已设为 RUNNING。"""
        from src.models.backtest import BacktestTask
        from src.workers.tasks.backtest_tasks import run_backtest_task

        mock_session = _make_mock_session()
        no_existing = MagicMock()
        no_existing.scalar_one_or_none.return_value = None
        strategy_result = MagicMock()
        strategy_result.scalar_one_or_none.return_value = _make_mock_strategy()
        # 第三次查询：无 PENDING 任务（新建）
        no_pending = MagicMock()
        no_pending.scalar_one_or_none.return_value = None
        mock_session.execute.side_effect = [no_existing, strategy_result, no_pending]

        # 记录调用 run_backtest_subprocess 时 task 的状态
        status_at_subprocess_call: list[TaskStatus] = []
        task_ref: list = []

        def capture_add(record):
            if isinstance(record, BacktestTask):
                record.id = 1
                task_ref.append(record)

        mock_session.add.side_effect = capture_add

        def mock_subprocess(**kwargs):
            # 此时 task_record.status 应已为 RUNNING
            if task_ref:
                status_at_subprocess_call.append(task_ref[0].status)
            return _make_backtest_output()

        with patch("src.workers.tasks.backtest_tasks.SyncSessionLocal", _make_session_factory(mock_session)):
            with patch("src.freqtrade_bridge.strategy_registry.lookup", return_value=_make_registry_entry()):
                with patch("src.workers.tasks.backtest_tasks.run_backtest_subprocess", side_effect=mock_subprocess):
                    with patch("src.workers.tasks.backtest_tasks.generate_config", return_value=MagicMock()):
                        with patch("src.workers.tasks.backtest_tasks.cleanup_task_dir"):
                            run_backtest_task(strategy_id=1)

        assert len(status_at_subprocess_call) == 1
        assert status_at_subprocess_call[0] == TaskStatus.RUNNING, "子进程执行前状态应已为 RUNNING"


class TestBacktestResultMetrics:
    """验证 BacktestResult 六项指标正确写入。"""

    def test_six_metrics_correctly_written_to_backtest_result(self, env_setup) -> None:
        """BacktestResult 六项指标（total_return、annual_return、sharpe_ratio、max_drawdown、trade_count、win_rate）值正确。"""
        from src.models.backtest import BacktestResult, BacktestTask
        from src.workers.tasks.backtest_tasks import run_backtest_task

        mock_session = _make_mock_session()
        no_existing = MagicMock()
        no_existing.scalar_one_or_none.return_value = None
        strategy_result = MagicMock()
        strategy_result.scalar_one_or_none.return_value = _make_mock_strategy()
        # 第三次查询：无 PENDING 任务（新建）
        no_pending = MagicMock()
        no_pending.scalar_one_or_none.return_value = None
        mock_session.execute.side_effect = [no_existing, strategy_result, no_pending]

        added_records: list = []

        def capture_add(record):
            added_records.append(record)
            if isinstance(record, BacktestTask):
                record.id = 42

        mock_session.add.side_effect = capture_add

        backtest_output = _make_backtest_output()

        with patch("src.workers.tasks.backtest_tasks.SyncSessionLocal", _make_session_factory(mock_session)):
            with patch("src.freqtrade_bridge.strategy_registry.lookup", return_value=_make_registry_entry()):
                with patch("src.workers.tasks.backtest_tasks.run_backtest_subprocess", return_value=backtest_output):
                    with patch("src.workers.tasks.backtest_tasks.generate_config", return_value=MagicMock()):
                        with patch("src.workers.tasks.backtest_tasks.cleanup_task_dir"):
                            run_backtest_task(strategy_id=1)

        result_records = [r for r in added_records if isinstance(r, BacktestResult)]
        assert len(result_records) == 1, "应创建一条 BacktestResult 记录"

        result = result_records[0]
        assert result.total_return == 0.18
        assert result.annual_return == 0.54
        assert result.sharpe_ratio == 2.1
        assert result.max_drawdown == 0.08
        assert result.trade_count == 120
        assert result.win_rate == 0.65
        assert result.strategy_id == 1
        assert result.task_id == 42

    def test_result_json_contains_six_metrics(self, env_setup) -> None:
        """BacktestTask.result_json 包含完整的六项指标。"""
        from src.models.backtest import BacktestTask
        from src.workers.tasks.backtest_tasks import run_backtest_task

        mock_session = _make_mock_session()
        no_existing = MagicMock()
        no_existing.scalar_one_or_none.return_value = None
        strategy_result = MagicMock()
        strategy_result.scalar_one_or_none.return_value = _make_mock_strategy()
        # 第三次查询：无 PENDING 任务（新建）
        no_pending = MagicMock()
        no_pending.scalar_one_or_none.return_value = None
        mock_session.execute.side_effect = [no_existing, strategy_result, no_pending]

        task_records: list = []

        def capture_add(record):
            if isinstance(record, BacktestTask):
                record.id = 1
                task_records.append(record)

        mock_session.add.side_effect = capture_add

        backtest_output = _make_backtest_output()

        with patch("src.workers.tasks.backtest_tasks.SyncSessionLocal", _make_session_factory(mock_session)):
            with patch("src.freqtrade_bridge.strategy_registry.lookup", return_value=_make_registry_entry()):
                with patch("src.workers.tasks.backtest_tasks.run_backtest_subprocess", return_value=backtest_output):
                    with patch("src.workers.tasks.backtest_tasks.generate_config", return_value=MagicMock()):
                        with patch("src.workers.tasks.backtest_tasks.cleanup_task_dir"):
                            run_backtest_task(strategy_id=1)

        assert len(task_records) == 1
        task = task_records[0]
        result_json = task.result_json
        assert result_json is not None, "result_json 不应为 None"
        assert "total_return" in result_json
        assert "annual_return" in result_json
        assert "sharpe_ratio" in result_json
        assert "max_drawdown" in result_json
        assert "trade_count" in result_json
        assert "win_rate" in result_json


class TestBacktestSignalInsert:
    """验证回测信号以 signal_source='backtest' 正确 INSERT，含 11 个扩展字段。"""

    def test_signals_inserted_with_source_backtest(self, env_setup) -> None:
        """回测信号 signal_source 应为 'backtest'。"""
        from src.models.backtest import BacktestTask
        from src.models.signal import TradingSignal
        from src.workers.tasks.backtest_tasks import run_backtest_task

        mock_session = _make_mock_session()
        no_existing = MagicMock()
        no_existing.scalar_one_or_none.return_value = None
        strategy_result = MagicMock()
        strategy_result.scalar_one_or_none.return_value = _make_mock_strategy()
        # 第三次查询：无 PENDING 任务（新建）
        no_pending = MagicMock()
        no_pending.scalar_one_or_none.return_value = None
        mock_session.execute.side_effect = [no_existing, strategy_result, no_pending]

        added_records: list = []

        def capture_add(record):
            added_records.append(record)
            if isinstance(record, BacktestTask):
                record.id = 1

        mock_session.add.side_effect = capture_add

        backtest_output = _make_backtest_output(with_signals=True)

        with patch("src.workers.tasks.backtest_tasks.SyncSessionLocal", _make_session_factory(mock_session)):
            with patch("src.freqtrade_bridge.strategy_registry.lookup", return_value=_make_registry_entry()):
                with patch("src.workers.tasks.backtest_tasks.run_backtest_subprocess", return_value=backtest_output):
                    with patch("src.workers.tasks.backtest_tasks.generate_config", return_value=MagicMock()):
                        with patch("src.workers.tasks.backtest_tasks.cleanup_task_dir"):
                            run_backtest_task(strategy_id=1)

        signal_records = [r for r in added_records if isinstance(r, TradingSignal)]
        assert len(signal_records) == 2, f"应插入 2 条信号记录，实际 {len(signal_records)}"

        for signal in signal_records:
            assert signal.signal_source == "backtest", f"signal_source 应为 'backtest'，实际为 {signal.signal_source!r}"

    def test_signals_all_11_fields_populated(self, env_setup) -> None:
        """回测信号应包含全部 11 个扩展字段的正确值。"""
        from src.models.backtest import BacktestTask
        from src.models.signal import TradingSignal
        from src.workers.tasks.backtest_tasks import run_backtest_task

        mock_session = _make_mock_session()
        no_existing = MagicMock()
        no_existing.scalar_one_or_none.return_value = None
        strategy_result = MagicMock()
        strategy_result.scalar_one_or_none.return_value = _make_mock_strategy()
        # 第三次查询：无 PENDING 任务（新建）
        no_pending = MagicMock()
        no_pending.scalar_one_or_none.return_value = None
        mock_session.execute.side_effect = [no_existing, strategy_result, no_pending]

        added_records: list = []

        def capture_add(record):
            added_records.append(record)
            if isinstance(record, BacktestTask):
                record.id = 1

        mock_session.add.side_effect = capture_add

        backtest_output = _make_backtest_output(with_signals=True)

        with patch("src.workers.tasks.backtest_tasks.SyncSessionLocal", _make_session_factory(mock_session)):
            with patch("src.freqtrade_bridge.strategy_registry.lookup", return_value=_make_registry_entry()):
                with patch("src.workers.tasks.backtest_tasks.run_backtest_subprocess", return_value=backtest_output):
                    with patch("src.workers.tasks.backtest_tasks.generate_config", return_value=MagicMock()):
                        with patch("src.workers.tasks.backtest_tasks.cleanup_task_dir"):
                            run_backtest_task(strategy_id=1)

        signal_records = [r for r in added_records if isinstance(r, TradingSignal)]
        assert len(signal_records) >= 1

        btc_signal = next((s for s in signal_records if s.pair == "BTC/USDT"), None)
        assert btc_signal is not None, "应存在 BTC/USDT 信号"

        # 验证 11 个字段
        assert btc_signal.pair == "BTC/USDT"
        assert btc_signal.direction == SignalDirection.BUY
        assert btc_signal.confidence_score == pytest.approx(0.85)
        assert btc_signal.entry_price == pytest.approx(45000.0)
        assert btc_signal.stop_loss == pytest.approx(43000.0)
        assert btc_signal.take_profit == pytest.approx(50000.0)
        assert btc_signal.indicator_values == {"rsi": 35.5, "macd": 0.002}
        assert btc_signal.timeframe == "1h"
        assert btc_signal.signal_strength == pytest.approx(0.75)
        assert btc_signal.volume == pytest.approx(1200000.0)
        assert btc_signal.volatility == pytest.approx(0.032)

    def test_signals_insert_only_no_update_or_delete(self, env_setup) -> None:
        """回测信号只执行 INSERT，不执行 UPDATE 或 DELETE。"""
        from src.models.backtest import BacktestTask
        from src.workers.tasks.backtest_tasks import run_backtest_task

        mock_session = _make_mock_session()
        no_existing = MagicMock()
        no_existing.scalar_one_or_none.return_value = None
        strategy_result = MagicMock()
        strategy_result.scalar_one_or_none.return_value = _make_mock_strategy()
        # 第三次查询：无 PENDING 任务（新建）
        no_pending = MagicMock()
        no_pending.scalar_one_or_none.return_value = None
        mock_session.execute.side_effect = [no_existing, strategy_result, no_pending]

        added_records: list = []

        def capture_add(record):
            added_records.append(record)
            if isinstance(record, BacktestTask):
                record.id = 1

        mock_session.add.side_effect = capture_add

        with patch("src.workers.tasks.backtest_tasks.SyncSessionLocal", _make_session_factory(mock_session)):
            with patch("src.freqtrade_bridge.strategy_registry.lookup", return_value=_make_registry_entry()):
                with patch("src.workers.tasks.backtest_tasks.run_backtest_subprocess", return_value=_make_backtest_output()):
                    with patch("src.workers.tasks.backtest_tasks.generate_config", return_value=MagicMock()):
                        with patch("src.workers.tasks.backtest_tasks.cleanup_task_dir"):
                            run_backtest_task(strategy_id=1)

        # 验证没有调用 delete 方法
        mock_session.delete.assert_not_called()
        # 验证 execute 只用于 SELECT（查询当日任务和策略），没有执行 UPDATE/DELETE
        # 注意：列名 "updated_at" 包含 "update"，需要检查语句开头而非整体包含
        for c in mock_session.execute.call_args_list:
            sql_str = str(c.args[0]).strip() if c.args else ""
            first_word = sql_str.split()[0].upper() if sql_str.split() else ""
            assert first_word != "UPDATE", f"不应执行 UPDATE 语句，但执行了：{sql_str[:100]}"
            assert first_word != "DELETE", f"不应执行 DELETE 语句，但执行了：{sql_str[:100]}"


class TestStrategyNullFieldUpdate:
    """验证 Strategy NULL 字段在 DONE 后被回测结果填充，非 NULL 字段不被覆盖。"""

    def test_null_strategy_fields_populated_after_done(self, env_setup) -> None:
        """Strategy 中为 NULL 的指标字段应被回测结果填充。"""
        from src.models.backtest import BacktestTask
        from src.workers.tasks.backtest_tasks import run_backtest_task

        # 创建全部为 NULL 的 strategy
        mock_strategy = _make_mock_strategy(
            trade_count=None,
            max_drawdown=None,
            sharpe_ratio=None,
            win_rate=None,
        )

        mock_session = _make_mock_session()
        no_existing = MagicMock()
        no_existing.scalar_one_or_none.return_value = None
        strategy_result = MagicMock()
        strategy_result.scalar_one_or_none.return_value = mock_strategy
        # 第三次查询：无 PENDING 任务（新建）
        no_pending = MagicMock()
        no_pending.scalar_one_or_none.return_value = None
        mock_session.execute.side_effect = [no_existing, strategy_result, no_pending]

        def capture_add(record):
            if isinstance(record, BacktestTask):
                record.id = 1

        mock_session.add.side_effect = capture_add

        backtest_output = _make_backtest_output(with_signals=False)

        with patch("src.workers.tasks.backtest_tasks.SyncSessionLocal", _make_session_factory(mock_session)):
            with patch("src.freqtrade_bridge.strategy_registry.lookup", return_value=_make_registry_entry()):
                with patch("src.workers.tasks.backtest_tasks.run_backtest_subprocess", return_value=backtest_output):
                    with patch("src.workers.tasks.backtest_tasks.generate_config", return_value=MagicMock()):
                        with patch("src.workers.tasks.backtest_tasks.cleanup_task_dir"):
                            run_backtest_task(strategy_id=1)

        # 验证 NULL 字段已被回测结果填充
        assert mock_strategy.trade_count == 120, "NULL 的 trade_count 应被填充为 120"
        assert mock_strategy.max_drawdown == pytest.approx(0.08), "NULL 的 max_drawdown 应被填充"
        assert mock_strategy.sharpe_ratio == pytest.approx(2.1), "NULL 的 sharpe_ratio 应被填充"
        assert mock_strategy.win_rate == pytest.approx(0.65), "NULL 的 win_rate 应被填充"

    def test_non_null_strategy_fields_not_overwritten(self, env_setup) -> None:
        """Strategy 中非 NULL 的指标字段不应被回测结果覆盖。"""
        from src.models.backtest import BacktestTask
        from src.workers.tasks.backtest_tasks import run_backtest_task

        # 创建部分有值、部分为 NULL 的 strategy
        original_sharpe = 3.5
        original_win_rate = 0.72
        mock_strategy = _make_mock_strategy(
            trade_count=None,     # NULL，应被填充
            max_drawdown=None,    # NULL，应被填充
            sharpe_ratio=original_sharpe,    # 非 NULL，不应被覆盖
            win_rate=original_win_rate,      # 非 NULL，不应被覆盖
        )

        mock_session = _make_mock_session()
        no_existing = MagicMock()
        no_existing.scalar_one_or_none.return_value = None
        strategy_result = MagicMock()
        strategy_result.scalar_one_or_none.return_value = mock_strategy
        # 第三次查询：无 PENDING 任务（新建）
        no_pending = MagicMock()
        no_pending.scalar_one_or_none.return_value = None
        mock_session.execute.side_effect = [no_existing, strategy_result, no_pending]

        def capture_add(record):
            if isinstance(record, BacktestTask):
                record.id = 1

        mock_session.add.side_effect = capture_add

        backtest_output = _make_backtest_output(with_signals=False)

        with patch("src.workers.tasks.backtest_tasks.SyncSessionLocal", _make_session_factory(mock_session)):
            with patch("src.freqtrade_bridge.strategy_registry.lookup", return_value=_make_registry_entry()):
                with patch("src.workers.tasks.backtest_tasks.run_backtest_subprocess", return_value=backtest_output):
                    with patch("src.workers.tasks.backtest_tasks.generate_config", return_value=MagicMock()):
                        with patch("src.workers.tasks.backtest_tasks.cleanup_task_dir"):
                            run_backtest_task(strategy_id=1)

        # 验证 NULL 字段已被填充
        assert mock_strategy.trade_count == 120, "NULL 的 trade_count 应被填充"
        assert mock_strategy.max_drawdown == pytest.approx(0.08), "NULL 的 max_drawdown 应被填充"

        # 验证非 NULL 字段未被覆盖
        assert mock_strategy.sharpe_ratio == pytest.approx(original_sharpe), \
            f"非 NULL 的 sharpe_ratio ({original_sharpe}) 不应被覆盖"
        assert mock_strategy.win_rate == pytest.approx(original_win_rate), \
            f"非 NULL 的 win_rate ({original_win_rate}) 不应被覆盖"

    def test_all_non_null_fields_unchanged(self, env_setup) -> None:
        """所有字段均非 NULL 时，Strategy 不被修改。"""
        from src.models.backtest import BacktestTask
        from src.workers.tasks.backtest_tasks import run_backtest_task

        original_values = {
            "trade_count": 200,
            "max_drawdown": 0.15,
            "sharpe_ratio": 1.5,
            "win_rate": 0.55,
        }
        mock_strategy = _make_mock_strategy(**original_values)

        mock_session = _make_mock_session()
        no_existing = MagicMock()
        no_existing.scalar_one_or_none.return_value = None
        strategy_result = MagicMock()
        strategy_result.scalar_one_or_none.return_value = mock_strategy
        # 第三次查询：无 PENDING 任务（新建）
        no_pending = MagicMock()
        no_pending.scalar_one_or_none.return_value = None
        mock_session.execute.side_effect = [no_existing, strategy_result, no_pending]

        def capture_add(record):
            if isinstance(record, BacktestTask):
                record.id = 1

        mock_session.add.side_effect = capture_add

        backtest_output = _make_backtest_output(with_signals=False)

        with patch("src.workers.tasks.backtest_tasks.SyncSessionLocal", _make_session_factory(mock_session)):
            with patch("src.freqtrade_bridge.strategy_registry.lookup", return_value=_make_registry_entry()):
                with patch("src.workers.tasks.backtest_tasks.run_backtest_subprocess", return_value=backtest_output):
                    with patch("src.workers.tasks.backtest_tasks.generate_config", return_value=MagicMock()):
                        with patch("src.workers.tasks.backtest_tasks.cleanup_task_dir"):
                            run_backtest_task(strategy_id=1)

        # 所有字段应保持原值
        assert mock_strategy.trade_count == 200
        assert mock_strategy.max_drawdown == pytest.approx(0.15)
        assert mock_strategy.sharpe_ratio == pytest.approx(1.5)
        assert mock_strategy.win_rate == pytest.approx(0.55)


class TestBacktestTempDirCleanup:
    """验证任务完成后临时目录自动清理。"""

    def test_cleanup_called_on_success(self, env_setup) -> None:
        """任务成功完成后，cleanup_task_dir 应被调用。"""
        from src.models.backtest import BacktestTask
        from src.workers.tasks.backtest_tasks import run_backtest_task

        mock_session = _make_mock_session()
        no_existing = MagicMock()
        no_existing.scalar_one_or_none.return_value = None
        strategy_result = MagicMock()
        strategy_result.scalar_one_or_none.return_value = _make_mock_strategy()
        # 第三次查询：无 PENDING 任务（新建）
        no_pending = MagicMock()
        no_pending.scalar_one_or_none.return_value = None
        mock_session.execute.side_effect = [no_existing, strategy_result, no_pending]

        def capture_add(record):
            if isinstance(record, BacktestTask):
                record.id = 99

        mock_session.add.side_effect = capture_add

        with patch("src.workers.tasks.backtest_tasks.SyncSessionLocal", _make_session_factory(mock_session)):
            with patch("src.freqtrade_bridge.strategy_registry.lookup", return_value=_make_registry_entry()):
                with patch("src.workers.tasks.backtest_tasks.run_backtest_subprocess", return_value=_make_backtest_output()):
                    with patch("src.workers.tasks.backtest_tasks.generate_config", return_value=MagicMock()):
                        with patch("src.workers.tasks.backtest_tasks.cleanup_task_dir") as mock_cleanup:
                            run_backtest_task(strategy_id=1)

                            mock_cleanup.assert_called_once()
                            # 验证传入了正确的 task_dir
                            cleanup_arg = mock_cleanup.call_args[0][0]
                            assert "99" in str(cleanup_arg), f"清理路径应包含 task_id=99，实际：{cleanup_arg}"

    def test_cleanup_called_on_failure(self, env_setup) -> None:
        """任务失败时，cleanup_task_dir 仍应被调用（finally 块保证）。"""
        from src.freqtrade_bridge.exceptions import FreqtradeExecutionError
        from src.models.backtest import BacktestTask
        from src.workers.tasks.backtest_tasks import run_backtest_task

        mock_session = _make_mock_session()
        no_existing = MagicMock()
        no_existing.scalar_one_or_none.return_value = None
        strategy_result = MagicMock()
        strategy_result.scalar_one_or_none.return_value = _make_mock_strategy()
        # 第三次查询：无 PENDING 任务（新建）
        no_pending = MagicMock()
        no_pending.scalar_one_or_none.return_value = None
        mock_session.execute.side_effect = [no_existing, strategy_result, no_pending]

        def capture_add(record):
            if isinstance(record, BacktestTask):
                record.id = 77

        mock_session.add.side_effect = capture_add

        with patch("src.workers.tasks.backtest_tasks.SyncSessionLocal", _make_session_factory(mock_session)):
            with patch("src.freqtrade_bridge.strategy_registry.lookup", return_value=_make_registry_entry()):
                with patch(
                    "src.workers.tasks.backtest_tasks.run_backtest_subprocess",
                    side_effect=FreqtradeExecutionError("subprocess failed"),
                ):
                    with patch("src.workers.tasks.backtest_tasks.generate_config", return_value=MagicMock()):
                        with patch("src.workers.tasks.backtest_tasks.cleanup_task_dir") as mock_cleanup:
                            run_backtest_task(strategy_id=1)

                            # 即使失败，cleanup 必须被调用
                            mock_cleanup.assert_called_once()
                            cleanup_arg = mock_cleanup.call_args[0][0]
                            assert "77" in str(cleanup_arg), f"清理路径应包含 task_id=77，实际：{cleanup_arg}"

    def test_cleanup_called_on_unexpected_exception(self, env_setup) -> None:
        """意外异常时，cleanup_task_dir 仍应被调用。"""
        from src.models.backtest import BacktestTask
        from src.workers.tasks.backtest_tasks import run_backtest_task

        mock_session = _make_mock_session()
        no_existing = MagicMock()
        no_existing.scalar_one_or_none.return_value = None
        strategy_result = MagicMock()
        strategy_result.scalar_one_or_none.return_value = _make_mock_strategy()
        # 第三次查询：无 PENDING 任务（新建）
        no_pending = MagicMock()
        no_pending.scalar_one_or_none.return_value = None
        mock_session.execute.side_effect = [no_existing, strategy_result, no_pending]

        def capture_add(record):
            if isinstance(record, BacktestTask):
                record.id = 55

        mock_session.add.side_effect = capture_add

        with patch("src.workers.tasks.backtest_tasks.SyncSessionLocal", _make_session_factory(mock_session)):
            with patch("src.freqtrade_bridge.strategy_registry.lookup", return_value=_make_registry_entry()):
                with patch(
                    "src.workers.tasks.backtest_tasks.run_backtest_subprocess",
                    side_effect=RuntimeError("unexpected error"),
                ):
                    with patch("src.workers.tasks.backtest_tasks.generate_config", return_value=MagicMock()):
                        with patch("src.workers.tasks.backtest_tasks.cleanup_task_dir") as mock_cleanup:
                            run_backtest_task(strategy_id=1)

                            mock_cleanup.assert_called_once()

    def test_task_status_failed_on_execution_error(self, env_setup) -> None:
        """FreqtradeExecutionError 时任务状态应变为 FAILED。"""
        from src.freqtrade_bridge.exceptions import FreqtradeExecutionError
        from src.models.backtest import BacktestTask
        from src.workers.tasks.backtest_tasks import run_backtest_task

        mock_session = _make_mock_session()
        no_existing = MagicMock()
        no_existing.scalar_one_or_none.return_value = None
        strategy_result = MagicMock()
        strategy_result.scalar_one_or_none.return_value = _make_mock_strategy()
        # 第三次查询：无 PENDING 任务（新建）
        no_pending = MagicMock()
        no_pending.scalar_one_or_none.return_value = None
        mock_session.execute.side_effect = [no_existing, strategy_result, no_pending]

        task_records: list = []

        def capture_add(record):
            if isinstance(record, BacktestTask):
                record.id = 1
                task_records.append(record)

        mock_session.add.side_effect = capture_add

        with patch("src.workers.tasks.backtest_tasks.SyncSessionLocal", _make_session_factory(mock_session)):
            with patch("src.freqtrade_bridge.strategy_registry.lookup", return_value=_make_registry_entry()):
                with patch(
                    "src.workers.tasks.backtest_tasks.run_backtest_subprocess",
                    side_effect=FreqtradeExecutionError("freqtrade error"),
                ):
                    with patch("src.workers.tasks.backtest_tasks.generate_config", return_value=MagicMock()):
                        with patch("src.workers.tasks.backtest_tasks.cleanup_task_dir"):
                            run_backtest_task(strategy_id=1)

        assert len(task_records) == 1
        assert task_records[0].status == TaskStatus.FAILED, "执行失败时状态应为 FAILED"
