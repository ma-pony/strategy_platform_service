"""信号生成 Celery 任务。

generate_signals_task：周期性触发，调用 freqtrade 生成最新交易信号。
刷新周期通过 SIGNAL_REFRESH_INTERVAL 配置项控制（默认 5 分钟）。

核心设计：
  - 信号结果写入 Redis（key: signal:{strategy_id}，TTL=3600s）
  - 同时持久化至 PostgreSQL TradingSignal 历史表（只 INSERT，不 UPDATE/DELETE）
  - 失败时记录结构化错误日志（含策略名、交易对、错误、时间戳），跳过写入，不影响 API
  - 每次成功生成记录结构化 info 日志（策略名、交易对、信号类型、来源 realtime、执行耗时）
"""

import datetime
import json
import time
from typing import Any

import structlog
from celery import shared_task
from sqlalchemy.orm import Session

from src.core.enums import DataSource
from src.freqtrade_bridge.exceptions import FreqtradeExecutionError
from src.freqtrade_bridge.signal_fetcher import fetch_signals_sync
from src.services.pair_metrics_service import upsert_pair_metrics
from src.workers.db import SyncSessionLocal
from src.workers.redis_client import get_redis_client

logger = structlog.get_logger(__name__)

# Redis 信号缓存 TTL（秒）
_SIGNAL_CACHE_TTL = 3600


@shared_task(
    name="src.workers.tasks.signal_tasks.generate_signals_task",
    bind=False,
    acks_late=True,
    queue="signal",
)
def generate_signals_task(strategy_id: int, pair: str) -> None:
    """生成指定策略和交易对的交易信号。

    流程：
      1. 调用 FreqtradeBridge.fetch_signals_sync 获取信号（Celery Worker 为同步上下文）
      2. 将结果写入 Redis key `signal:{strategy_id}`（TTL=3600s）
      3. 持久化新的 TradingSignal 历史记录至 PostgreSQL（只增不删）

    失败处理：
      - 信号获取失败时记录结构化错误日志，不向外抛出异常
      - 不覆盖现有 Redis 缓存（保留历史数据可用性）

    Args:
        strategy_id: 策略数据库 ID
        pair: 交易对（如 "BTC/USDT"）
    """
    start_time = time.monotonic()

    # 获取策略名称（用于日志）
    strategy_name = str(strategy_id)

    try:
        signals_data = fetch_signals_sync(strategy=str(strategy_id), pair=pair)
    except (FreqtradeExecutionError, Exception) as exc:
        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        logger.error(
            "signal generation failed",
            strategy_name=strategy_name,
            pair=pair,
            error=str(exc),
            timestamp=datetime.datetime.now(tz=datetime.timezone.utc).isoformat(),
            elapsed_ms=elapsed_ms,
        )
        # 失败时不覆盖现有缓存，直接返回
        return

    elapsed_ms = int((time.monotonic() - start_time) * 1000)

    # 写入 Redis 缓存
    redis_key = f"signal:{strategy_id}"
    redis_client = get_redis_client()
    try:
        redis_client.set(
            redis_key,
            json.dumps(signals_data, default=str),
            ex=_SIGNAL_CACHE_TTL,
        )
        logger.info(
            "signal written to redis",
            strategy_name=strategy_name,
            strategy_id=strategy_id,
            pair=pair,
            key=redis_key,
        )
    except Exception as exc:
        logger.warning(
            "redis write failed for signal",
            strategy_name=strategy_name,
            strategy_id=strategy_id,
            pair=pair,
            error=str(exc),
        )

    # 持久化至 PostgreSQL（只 INSERT，不 UPDATE/DELETE）
    _persist_signals_to_db(
        strategy_id=strategy_id,
        pair=pair,
        signals_data=signals_data,
        strategy_name=strategy_name,
    )

    # 记录每次信号生成的结构化 info 日志
    signals_list = signals_data.get("signals", [])
    for signal_item in signals_list:
        direction = signal_item.get("direction", "hold")
        logger.info(
            "signal generated",
            strategy_name=strategy_name,
            pair=pair,
            direction=direction,
            source="realtime",
            duration_ms=elapsed_ms,
        )

    # 持久化完成后，非阻塞更新实盘绩效指标（需求 3.1, 3.4）
    # 使用信号中携带的 timeframe，默认 "1h"
    signal_timeframe = "1h"
    if signals_list:
        signal_timeframe = signals_list[0].get("timeframe") or "1h"
    try_upsert_live_metrics(
        strategy_id=strategy_id,
        pair=pair,
        timeframe=signal_timeframe,
    )


def _persist_signals_to_db(
    strategy_id: int,
    pair: str,
    signals_data: dict[str, Any],
    strategy_name: str = "",
) -> None:
    """将信号数据持久化至 TradingSignal 历史表（只 INSERT，不 UPDATE/DELETE）。

    Args:
        strategy_id: 策略 ID
        pair: 交易对
        signals_data: 从 freqtrade 获取的信号字典，含 11 个扩展字段
        strategy_name: 策略名称（用于日志）
    """
    from src.core.enums import SignalDirection
    from src.models.signal import TradingSignal

    signals_list = signals_data.get("signals", [])
    if not signals_list:
        return

    with SyncSessionLocal() as session:
        try:
            for signal_item in signals_list:
                direction_str = signal_item.get("direction", "hold").lower()
                try:
                    direction = SignalDirection(direction_str)
                except ValueError:
                    direction = SignalDirection.HOLD

                signal_at_str = signal_item.get("signal_at", "")
                signal_at = _parse_datetime(signal_at_str)

                # 提取扩展字段（允许 None）
                entry_price = signal_item.get("entry_price")
                stop_loss = signal_item.get("stop_loss")
                take_profit = signal_item.get("take_profit")
                indicator_values = signal_item.get("indicator_values")
                timeframe = signal_item.get("timeframe")
                signal_strength = signal_item.get("signal_strength")
                volume = signal_item.get("volume")
                volatility = signal_item.get("volatility")

                # 安全转换数值字段
                confidence_score_raw = signal_item.get("confidence_score", 0.0)
                try:
                    confidence_score = float(confidence_score_raw) if confidence_score_raw is not None else None
                except (TypeError, ValueError):
                    confidence_score = None

                signal_record = TradingSignal(
                    strategy_id=strategy_id,
                    pair=pair,
                    direction=direction,
                    confidence_score=confidence_score,
                    signal_source="realtime",  # 显式传入，不依赖 server_default
                    entry_price=float(entry_price) if entry_price is not None else None,
                    stop_loss=float(stop_loss) if stop_loss is not None else None,
                    take_profit=float(take_profit) if take_profit is not None else None,
                    indicator_values=indicator_values if isinstance(indicator_values, dict) else None,
                    timeframe=str(timeframe) if timeframe is not None else None,
                    signal_strength=float(signal_strength) if signal_strength is not None else None,
                    volume=float(volume) if volume is not None else None,
                    volatility=float(volatility) if volatility is not None else None,
                    signal_at=signal_at,
                )
                session.add(signal_record)

            session.commit()
            logger.info(
                "signals persisted to db",
                strategy_name=strategy_name,
                strategy_id=strategy_id,
                pair=pair,
                count=len(signals_list),
                source="realtime",
            )
        except Exception as exc:
            logger.error(
                "failed to persist signals to db",
                strategy_name=strategy_name,
                strategy_id=strategy_id,
                pair=pair,
                error=str(exc),
                timestamp=datetime.datetime.now(tz=datetime.timezone.utc).isoformat(),
                exc_info=True,
            )


def compute_live_metrics(
    session: Session,
    strategy_id: int,
    pair: str,
    timeframe: str,
) -> dict[str, float | int | None]:
    """从 trading_signals 历史计算实盘滚动绩效指标。

    查询最近 200 条 (strategy_id, pair, timeframe) 匹配的信号记录，
    基于信号方向和置信度估算五个绩效指标（估算值，非精确交易绩效）。

    历史数据不足 5 条时，所有指标返回 None。

    Args:
        session: 同步 SQLAlchemy Session
        strategy_id: 策略 ID
        pair: 交易对（如 "BTC/USDT"）
        timeframe: 时间周期（如 "1h"）

    Returns:
        含 total_return、profit_factor、max_drawdown、sharpe_ratio、trade_count 的字典
    """
    from sqlalchemy import select

    from src.models.signal import TradingSignal

    stmt = (
        select(TradingSignal.direction, TradingSignal.confidence_score)
        .where(
            TradingSignal.strategy_id == strategy_id,
            TradingSignal.pair == pair,
            TradingSignal.timeframe == timeframe,
        )
        .order_by(TradingSignal.signal_at.desc())
        .limit(200)
    )

    rows = session.execute(stmt).fetchall()

    _null_result: dict[str, float | int | None] = {
        "total_return": None,
        "profit_factor": None,
        "max_drawdown": None,
        "sharpe_ratio": None,
        "trade_count": None,
    }

    if len(rows) < 5:
        return _null_result

    # 解析方向和置信度
    directions = [str(row.direction) for row in rows]
    confidences = [float(row.confidence_score or 0.0) for row in rows]

    # trade_count：非 hold 方向信号数（精确值）
    non_hold = [(d, c) for d, c in zip(directions, confidences, strict=False) if d != "hold"]
    trade_count: int = len(non_hold)

    # profit_factor：buy 置信度总和 / sell 置信度总和（近似盈亏比）
    buy_conf_sum = sum(c for d, c in non_hold if d == "buy")
    sell_conf_sum = sum(c for d, c in non_hold if d == "sell")
    profit_factor: float | None = buy_conf_sum / sell_conf_sum if sell_conf_sum > 0 else None

    # total_return：buy 方向信号置信度加权简化累计收益估算
    total_return: float | None = buy_conf_sum - sell_conf_sum

    # sharpe_ratio：置信度序列均值 / 标准差近似
    if len(confidences) > 1:
        import statistics

        mean_conf = statistics.mean(confidences)
        stdev_conf = statistics.stdev(confidences)
        sharpe_ratio: float | None = (mean_conf / stdev_conf) if stdev_conf > 0 else None
    else:
        sharpe_ratio = None

    # max_drawdown：方向序列最大连续负序列归一化简化估算
    max_drawdown: float | None = _compute_max_drawdown(directions)

    return {
        "total_return": total_return,
        "profit_factor": profit_factor,
        "max_drawdown": max_drawdown,
        "sharpe_ratio": sharpe_ratio,
        "trade_count": trade_count,
    }


def _compute_max_drawdown(directions: list[str]) -> float | None:
    """简化估算最大回撤：累计方向序列最大连续负序长度归一化。

    将 sell 视为 -1，buy 视为 +1，hold 视为 0，
    计算累计序列的最大回撤深度（归一化到 [0, 1]）。

    Args:
        directions: 信号方向列表（"buy"/"sell"/"hold"）

    Returns:
        估算最大回撤值（正数），或 None
    """
    if not directions:
        return None

    cumulative = 0.0
    peak = 0.0
    max_dd = 0.0

    for d in directions:
        if d == "buy":
            cumulative += 1
        elif d == "sell":
            cumulative -= 1
        # hold 不影响

        if cumulative > peak:
            peak = cumulative
        drawdown = (peak - cumulative) / max(abs(peak), 1.0)
        if drawdown > max_dd:
            max_dd = drawdown

    return max_dd if max_dd > 0 else None


def try_upsert_live_metrics(
    strategy_id: int,
    pair: str,
    timeframe: str,
) -> None:
    """非阻塞实盘指标更新封装。

    在 _persist_signals_to_db() 完成后调用。使用独立的 SyncSessionLocal() session，
    避免污染信号写入事务。全部逻辑包裹在 try/except Exception，
    失败时记录 structlog ERROR（含 strategy_id、pair、timeframe、error_message），
    不向上抛出，保证不阻塞信号生成主流程（需求 3.4）。

    成功时自行 session.commit()，data_source 设置为 DataSource.LIVE（需求 3.2）。

    Args:
        strategy_id: 策略 ID
        pair: 交易对（如 "BTC/USDT"）
        timeframe: 时间周期（如 "1h"）
    """
    with SyncSessionLocal() as session:
        try:
            metrics = compute_live_metrics(
                session=session,
                strategy_id=strategy_id,
                pair=pair,
                timeframe=timeframe,
            )

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
                data_source=DataSource.LIVE,
                last_updated_at=datetime.datetime.now(tz=datetime.timezone.utc),
            )

            session.commit()

        except Exception as exc:
            logger.error(
                "实盘指标更新失败（非阻塞），不中断信号任务主流程",
                strategy_id=strategy_id,
                pair=pair,
                timeframe=timeframe,
                error_message=str(exc),
            )


def _parse_datetime(value: str | None) -> datetime.datetime:
    """解析日期时间字符串。

    Args:
        value: ISO 格式日期时间字符串

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
