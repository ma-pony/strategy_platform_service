"""信号服务层（任务 9.1）。

提供交易信号查询业务逻辑：
  - 优先读取 Redis key signal:{strategy_id}，缓存未命中时回退至 PostgreSQL
  - Redis 不可用时静默回退至 DB，记录 WARNING 日志，不向客户端暴露缓存错误
  - 响应中必须携带 last_updated_at 字段标注数据时效
  - 策略不存在时抛出 NotFoundError(code=3001)

Redis 键设计：
  key: signal:{strategy_id}
  value: JSON（含 signals 列表和 last_updated_at）
  TTL: 3600s（由信号 Worker 写入时设定）
"""

import json
import logging
from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import NotFoundError
from src.models.signal import TradingSignal
from src.models.strategy import Strategy
from src.workers.redis_client import get_redis_client

logger = structlog.get_logger(__name__)


class SignalService:
    """交易信号查询业务逻辑服务。

    所有方法接受 AsyncSession 参数，由路由层通过依赖注入传入。
    信号数据写入由 Celery Worker 负责，本服务仅提供读取能力。
    """

    async def get_signals(
        self,
        db: AsyncSession,
        strategy_id: int,
        limit: int = 20,
    ) -> tuple[list[TradingSignal], datetime]:
        """查询指定策略的交易信号。

        查询策略：
          1. 验证策略存在（不存在时抛出 NotFoundError）
          2. 尝试从 Redis 缓存读取（key: signal:{strategy_id}）
          3. 缓存命中时解析 JSON 并返回
          4. 缓存未命中或 Redis 不可用时，从 PostgreSQL 查询最近信号

        Args:
            db: 异步数据库 session
            strategy_id: 策略 ID
            limit: 返回信号数量限制（默认 20）

        Returns:
            (signals, last_updated_at) 元组：
              - signals: TradingSignal 对象列表（或 dict 列表，来自 Redis 时）
              - last_updated_at: 数据时效时间戳

        Raises:
            NotFoundError: 策略不存在（code=3001）
        """
        # Step 1: 验证策略存在
        strategy_stmt = select(Strategy).where(Strategy.id == strategy_id)
        strategy_result = await db.execute(strategy_stmt)
        strategy = strategy_result.scalar_one_or_none()

        if strategy is None:
            raise NotFoundError(f"策略 {strategy_id} 不存在")

        # Step 2: 尝试从 Redis 读取
        cache_key = f"signal:{strategy_id}"
        try:
            redis_client = get_redis_client()
            cached = redis_client.get(cache_key)
            if cached is not None:
                data: dict[str, Any] = json.loads(cached)
                signals_raw = data.get("signals", [])
                last_updated_at_str: str = data.get(
                    "last_updated_at", datetime.now(timezone.utc).isoformat()
                )
                last_updated_at = datetime.fromisoformat(last_updated_at_str)

                # 将 dict 转换为 TradingSignal-like 对象
                signal_objects = _dicts_to_signals(signals_raw, strategy_id)
                return signal_objects[:limit], last_updated_at
        except Exception as exc:
            logger.warning(
                "Redis 读取失败，回退至数据库查询",
                strategy_id=strategy_id,
                error=str(exc),
            )

        # Step 3: 从数据库回退查询
        return await self._get_signals_from_db(db, strategy_id, limit)

    async def _get_signals_from_db(
        self,
        db: AsyncSession,
        strategy_id: int,
        limit: int,
    ) -> tuple[list[TradingSignal], datetime]:
        """从 PostgreSQL 查询最近信号记录。

        按 signal_at 降序返回最近 limit 条记录。
        无信号时返回空列表和当前 UTC 时间。
        """
        stmt = (
            select(TradingSignal)
            .where(TradingSignal.strategy_id == strategy_id)
            .order_by(TradingSignal.signal_at.desc())
            .limit(limit)
        )
        result = await db.execute(stmt)
        signals: list[TradingSignal] = list(result.scalars().all())

        if signals:
            last_updated_at = signals[0].signal_at
        else:
            last_updated_at = datetime.now(timezone.utc)

        return signals, last_updated_at


def _dicts_to_signals(
    signals_raw: list[dict[str, Any]],
    strategy_id: int,
) -> list[Any]:
    """将 Redis 缓存的 dict 列表转换为类 TradingSignal 对象。

    使用简单的 Namespace 对象承载数据，兼容 SignalRead schema 的 from_attributes 模式。
    """
    from types import SimpleNamespace

    from src.core.enums import SignalDirection

    result = []
    for raw in signals_raw:
        obj = SimpleNamespace(
            id=raw.get("id", 0),
            strategy_id=raw.get("strategy_id", strategy_id),
            pair=raw.get("pair", ""),
            direction=SignalDirection(raw.get("direction", "hold")),
            confidence_score=raw.get("confidence_score"),
            signal_at=datetime.fromisoformat(raw.get("signal_at", datetime.now(timezone.utc).isoformat())),
            created_at=datetime.fromisoformat(raw.get("created_at", datetime.now(timezone.utc).isoformat())),
        )
        result.append(obj)
    return result
