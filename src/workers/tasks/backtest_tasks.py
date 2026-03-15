"""回测 Celery 任务。

run_backtest_task：对指定策略执行 freqtrade 回测。
支持两种触发方式：
  1. Celery Beat 每日定时触发（所有 is_active 策略）
  2. 管理员 API 手动触发（指定策略）

核心设计：
  - acks_late=True：Worker 崩溃时任务重新入队
  - 无超时限制：回测任务运行至自然结束
  - concurrency=1 串行执行：由 Celery Worker 配置保证
  - 隔离目录：每个任务在 /tmp/freqtrade_jobs/{task_id}/ 下生成配置
  - finally 清理：无论成功或失败均清理临时目录

状态流转：
  PENDING → RUNNING → DONE（成功）
                    → FAILED（执行失败）
"""

import datetime
import shutil
import time
from pathlib import Path
from typing import Any

import structlog
from celery import shared_task
from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from src.core.enums import DataSource, TaskStatus
from src.freqtrade_bridge.backtester import run_backtest_subprocess
from src.freqtrade_bridge.exceptions import FreqtradeExecutionError, FreqtradeTimeoutError
from src.freqtrade_bridge.runner import cleanup_task_dir, generate_config
from src.services.pair_metrics_service import upsert_pair_metrics
from src.workers.db import SyncSessionLocal

logger = structlog.get_logger(__name__)


@shared_task(
    name="src.workers.tasks.backtest_tasks.run_backtest_task",
    bind=True,
    acks_late=True,
    max_retries=3,
    soft_time_limit=None,  # 无超时，任务运行至自然结束
    queue="backtest",
)
def run_backtest_task(self: Any, strategy_id: int) -> None:  # type: ignore[misc]
    """执行指定策略的 freqtrade 回测任务。

    任务启动时先检查当日是否已有 RUNNING/DONE 状态记录，存在则跳过（幂等设计）。

    Args:
        strategy_id: 策略数据库 ID
    """
    # 延迟导入，避免循环引用
    from src.freqtrade_bridge.strategy_registry import lookup
    from src.models.backtest import BacktestResult, BacktestTask
    from src.models.strategy import Strategy

    today = datetime.date.today()
    start_time = time.monotonic()

    with SyncSessionLocal() as session:
        # 1. 幂等检查：当日是否已有 RUNNING 或 DONE 状态的任务
        existing_stmt = select(BacktestTask).where(
            and_(
                BacktestTask.strategy_id == strategy_id,
                BacktestTask.scheduled_date == today,
                BacktestTask.status.in_([TaskStatus.RUNNING, TaskStatus.DONE]),
            )
        )
        existing = session.execute(existing_stmt).scalar_one_or_none()
        if existing is not None:
            logger.info(
                "backtest task skipped (already exists)",
                strategy_id=strategy_id,
                date=str(today),
                status=existing.status.value,
            )
            return

        # 2. 查询策略配置
        strategy_stmt = select(Strategy).where(Strategy.id == strategy_id)
        strategy = session.execute(strategy_stmt).scalar_one_or_none()
        if strategy is None:
            logger.error("strategy not found", strategy_id=strategy_id)
            return

        # 2.5 校验策略在注册表中，获取策略文件路径
        try:
            registry_entry = lookup(strategy.name)
        except Exception as exc:
            logger.error(
                "strategy not in registry",
                strategy_id=strategy_id,
                strategy_name=strategy.name,
                error=str(exc),
            )
            # 创建一个 FAILED 任务记录
            task_record = BacktestTask(
                strategy_id=strategy_id,
                scheduled_date=today,
                status=TaskStatus.FAILED,
                error_message=f"策略 '{strategy.name}' 不在注册表中",
            )
            session.add(task_record)
            session.commit()
            return

        # 3. 查找已有的 PENDING 任务（管理员 API 预创建的），或新建
        pending_stmt = select(BacktestTask).where(
            and_(
                BacktestTask.strategy_id == strategy_id,
                BacktestTask.scheduled_date == today,
                BacktestTask.status == TaskStatus.PENDING,
            )
        )
        task_record = session.execute(pending_stmt).scalar_one_or_none()
        if task_record is None:
            # Celery Beat 触发场景：尚无记录，新建
            task_record = BacktestTask(
                strategy_id=strategy_id,
                scheduled_date=today,
                status=TaskStatus.PENDING,
            )
            session.add(task_record)
            session.flush()  # 获取 task_record.id

        task_dir = Path("/tmp/freqtrade_jobs") / str(task_record.id)  # noqa: S108

        try:
            # 4. 更新状态为 RUNNING
            task_record.status = TaskStatus.RUNNING
            session.commit()

            logger.info(
                "backtest task started",
                strategy_id=strategy_id,
                task_id=task_record.id,
                strategy=strategy.name,
                date=str(today),
            )

            # 5. 创建隔离目录并复制策略文件
            strategy_dir = task_dir / "strategy"
            results_dir = task_dir / "results"
            strategy_dir.mkdir(parents=True, exist_ok=True)
            results_dir.mkdir(parents=True, exist_ok=True)

            # 复制策略文件到隔离目录
            strategy_file = registry_entry["file_path"]
            if strategy_file.exists():
                shutil.copy2(strategy_file, strategy_dir / strategy_file.name)

            # 6. 生成隔离配置文件
            config_path = generate_config(
                task_dir,
                strategy.config_params or {},
                timerange=task_record.timerange or "20240101-20240601",
            )

            # 7. 执行 freqtrade 回测子进程（无 timeout 参数）
            backtest_output = run_backtest_subprocess(
                config_path=config_path,
                strategy=registry_entry["class_name"],
            )

            duration_ms = int((time.monotonic() - start_time) * 1000)

            # 8. 提取六项核心指标并写入 result_json
            result_data = {
                "total_return": float(backtest_output.get("total_return", 0.0)),
                "annual_return": float(backtest_output.get("annual_return", 0.0)),
                "sharpe_ratio": float(backtest_output.get("sharpe_ratio", 0.0)),
                "max_drawdown": float(backtest_output.get("max_drawdown", 0.0)),
                "trade_count": int(backtest_output.get("trade_count", 0)),
                "win_rate": float(backtest_output.get("win_rate", 0.0)),
            }
            task_record.result_json = result_data

            # 9. 持久化 BacktestResult
            result_record = BacktestResult(
                strategy_id=strategy_id,
                task_id=task_record.id,
                total_return=result_data["total_return"],
                annual_return=result_data["annual_return"],
                sharpe_ratio=result_data["sharpe_ratio"],
                max_drawdown=result_data["max_drawdown"],
                trade_count=result_data["trade_count"],
                win_rate=result_data["win_rate"],
                period_start=_parse_datetime(backtest_output.get("period_start", "")),
                period_end=_parse_datetime(backtest_output.get("period_end", "")),
            )
            session.add(result_record)

            # 10. DONE 后更新 Strategy 表 NULL 指标字段
            _update_strategy_metrics(strategy, result_data)

            # 11. 将回测信号追加写入 trading_signals
            signals = backtest_output.get("signals", [])
            _insert_backtest_signals(session, strategy_id, signals)

            # 11.5 在 commit 前写入策略对绩效指标（与 BacktestResult 同一事务，需求 2.5）
            # 从策略配置获取 pair 和 timeframe（取第一个交易对）
            pairs = strategy.pairs if hasattr(strategy, "pairs") and strategy.pairs else []
            timeframe_val = (
                strategy.config_params.get("timeframe", "1h")
                if hasattr(strategy, "config_params") and strategy.config_params
                else "1h"
            )
            backtest_output_full = {
                "total_return": result_data.get("total_return"),
                "profit_factor": backtest_output.get("profit_factor"),
                "max_drawdown": result_data.get("max_drawdown"),
                "sharpe_ratio": result_data.get("sharpe_ratio"),
                "trade_count": result_data.get("trade_count"),
            }
            for _pair in pairs if pairs else ["BTC/USDT"]:
                _upsert_metrics_for_backtest(
                    session=session,
                    strategy_id=strategy_id,
                    pair=_pair,
                    timeframe=timeframe_val,
                    backtest_output=backtest_output_full,
                )

            # 12. 更新任务状态为 DONE
            task_record.status = TaskStatus.DONE
            session.commit()

            logger.info(
                "backtest task completed",
                strategy_id=strategy_id,
                task_id=task_record.id,
                strategy=strategy.name,
                duration_ms=duration_ms,
                total_return=result_data["total_return"],
            )

        except (FreqtradeExecutionError, FreqtradeTimeoutError) as exc:
            duration_ms = int((time.monotonic() - start_time) * 1000)
            logger.warning(
                "backtest task failed",
                strategy_id=strategy_id,
                task_id=task_record.id,
                strategy=strategy.name,
                exit_code=-1,
                duration_ms=duration_ms,
                error=str(exc),
            )
            task_record.status = TaskStatus.FAILED
            task_record.error_message = str(exc)[:2000]
            session.commit()

        except Exception:
            duration_ms = int((time.monotonic() - start_time) * 1000)
            logger.error(
                "unexpected error in backtest task",
                strategy_id=strategy_id,
                task_id=task_record.id,
                strategy=strategy.name,
                duration_ms=duration_ms,
                exc_info=True,
            )
            try:
                task_record.status = TaskStatus.FAILED
                task_record.error_message = "内部错误，请查看日志"
                session.commit()
            except Exception:
                pass

        finally:
            # 13. 无论成功或失败，清理临时目录
            cleanup_task_dir(task_dir)


def _extract_pair_metrics_from_result(
    backtest_output: dict[str, Any],
) -> dict[str, float | int | None]:
    """从回测输出字典中提取五个绩效指标字段。

    total_return 映射自 backtest_output['total_return']（即 freqtrade profit_total）。
    profit_factor 为独立字段，可为 None（缺失时不覆盖现有值，需求 2.3）。
    其余字段若缺失也返回 None。

    Args:
        backtest_output: run_backtest_subprocess 返回的回测结果字典

    Returns:
        含五个指标键的字典，值可为 None
    """

    def _safe_float(val: Any) -> float | None:
        if val is None:
            return None
        try:
            return float(val)
        except (TypeError, ValueError):
            return None

    def _safe_int(val: Any) -> int | None:
        if val is None:
            return None
        try:
            return int(val)
        except (TypeError, ValueError):
            return None

    return {
        "total_return": _safe_float(backtest_output.get("total_return")),
        "profit_factor": _safe_float(backtest_output.get("profit_factor")),
        "max_drawdown": _safe_float(backtest_output.get("max_drawdown")),
        "sharpe_ratio": _safe_float(backtest_output.get("sharpe_ratio")),
        "trade_count": _safe_int(backtest_output.get("trade_count")),
    }


def _upsert_metrics_for_backtest(
    session: Session,
    strategy_id: int,
    pair: str,
    timeframe: str,
    backtest_output: dict[str, Any],
) -> None:
    """在回测任务状态变更为 DONE 前，将绩效指标 upsert 至 strategy_pair_metrics 表。

    在调用方的同一 session 中执行，不自行 commit，保证与 BacktestResult 写入的原子性（需求 2.5）。

    data_source 固定为 DataSource.BACKTEST，last_updated_at 为当前 UTC 时间（需求 2.2）。

    Args:
        session: 调用方的同步 SQLAlchemy Session
        strategy_id: 策略 ID
        pair: 交易对（如 "BTC/USDT"）
        timeframe: 时间周期（如 "1h"）
        backtest_output: run_backtest_subprocess 返回的回测结果字典
    """
    metrics = _extract_pair_metrics_from_result(backtest_output)

    upsert_pair_metrics(
        session=session,
        strategy_id=strategy_id,
        pair=pair,
        timeframe=timeframe,
        total_return=metrics.get("total_return"),
        profit_factor=metrics.get("profit_factor"),
        max_drawdown=metrics.get("max_drawdown"),
        sharpe_ratio=metrics.get("sharpe_ratio"),
        trade_count=metrics.get("trade_count"),  # type: ignore[arg-type]
        data_source=DataSource.BACKTEST,
        last_updated_at=datetime.datetime.now(tz=datetime.timezone.utc),
    )


def _update_strategy_metrics(strategy: Any, result_data: dict[str, Any]) -> None:
    """DONE 后更新 Strategy 表 NULL 指标字段为回测结果值。

    非 NULL 字段不覆盖。
    """
    field_mapping = {
        "trade_count": "trade_count",
        "max_drawdown": "max_drawdown",
        "sharpe_ratio": "sharpe_ratio",
        "win_rate": "win_rate",
    }
    for result_key, strategy_field in field_mapping.items():
        if hasattr(strategy, strategy_field):
            current_value = getattr(strategy, strategy_field, None)
            if current_value is None:
                setattr(strategy, strategy_field, result_data.get(result_key))


def _insert_backtest_signals(
    session: Session,
    strategy_id: int,
    signals: list[dict[str, Any]],
) -> None:
    """将回测信号以 INSERT 方式追加写入 trading_signals。"""
    from src.core.enums import SignalDirection
    from src.models.signal import TradingSignal

    datetime.datetime.now(tz=datetime.timezone.utc)

    for sig in signals:
        direction_str = sig.get("direction", "hold").lower()
        try:
            direction = SignalDirection(direction_str)
        except ValueError:
            direction = SignalDirection.HOLD

        signal_record = TradingSignal(
            strategy_id=strategy_id,
            pair=sig.get("pair", "BTC/USDT"),
            direction=direction,
            confidence_score=sig.get("confidence_score"),
            signal_source="backtest",
            entry_price=sig.get("entry_price"),
            stop_loss=sig.get("stop_loss"),
            take_profit=sig.get("take_profit"),
            indicator_values=sig.get("indicator_values"),
            timeframe=sig.get("timeframe"),
            signal_strength=sig.get("signal_strength"),
            volume=sig.get("volume"),
            volatility=sig.get("volatility"),
            signal_at=_parse_datetime(sig.get("signal_at")),
        )
        session.add(signal_record)


def _parse_datetime(value: str | None) -> datetime.datetime:
    """解析 freqtrade 输出的日期时间字符串。

    Args:
        value: ISO 格式日期时间字符串（如 "2024-01-01T00:00:00"）

    Returns:
        datetime 对象；解析失败时返回当前 UTC 时间
    """
    if not value:
        return datetime.datetime.now(tz=datetime.timezone.utc)
    try:
        dt = datetime.datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        return dt
    except (ValueError, TypeError):
        return datetime.datetime.now(tz=datetime.timezone.utc)
