"""信号 API 路由层（任务 9.2）。

提供交易信号只读接口：
  - GET /strategies/{id}/signals：信号列表（含 last_updated_at 时效字段）
  - GET /signals：全局信号聚合列表

字段权限过滤：
  - VIP 用户响应含 confidence_score
  - 匿名和 Free 用户该字段不返回或返回 null

使用 get_optional_user 注入可选用户（无 token 时返回 None 即匿名）。
"""

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.deps import get_db, get_optional_user
from src.core.response import ApiResponse, ok
from src.schemas.strategy import SignalRead
from src.services.signal_service import SignalService

router = APIRouter(tags=["signals"])

_signal_service = SignalService()


async def _check_paywall(request: Request, current_user: Any) -> None:
    """统一 paywall 鉴权检查。

    - 未登录用户：需有效 X-Visitor-ID + 有效 trial，否则 4032/4031
    - Free 用户：需有效 trial，否则 4033
    - VIP/admin：直接通过
    Redis 不可用时静默降级为拒绝访问。
    同步 Redis 调用放入线程池避免阻塞事件循环。
    """
    from src.core.enums import MembershipTier
    from src.core.exceptions import LoginRequiredError, MembershipRequiredError, TrialExpiredError
    from src.services.trial_service import is_trial_active
    from src.workers.redis_client import get_redis_client

    async def _has_active_trial(visitor_id: str) -> bool:
        try:
            return await asyncio.to_thread(is_trial_active, get_redis_client(), visitor_id)
        except Exception:
            return False

    if current_user is None:
        visitor_id = request.headers.get("X-Visitor-ID", "").strip()
        if not visitor_id:
            raise LoginRequiredError
        if not await _has_active_trial(visitor_id):
            raise TrialExpiredError
        return

    membership_val = current_user.membership
    if isinstance(membership_val, MembershipTier):
        is_free = membership_val == MembershipTier.FREE
    else:
        is_free = str(membership_val).upper() == "FREE"

    if is_free:
        visitor_id = request.headers.get("X-Visitor-ID", "").strip()
        if not visitor_id or not await _has_active_trial(visitor_id):
            raise MembershipRequiredError


def _is_vip(membership: Any) -> bool:
    from src.core.enums import MembershipTier

    if membership is None:
        return False
    if isinstance(membership, MembershipTier):
        return membership in (MembershipTier.VIP1, MembershipTier.VIP2)
    return str(membership).upper() in ("VIP1", "VIP2")


@router.get("/strategies/{strategy_id}/signals", response_model=ApiResponse[Any])
async def get_signals(
    strategy_id: int,
    request: Request,
    limit: int = Query(default=20, ge=1, le=100, description="返回信号数量（最大 100）"),
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(get_optional_user),
) -> ApiResponse[Any]:
    """获取指定策略的交易信号列表。"""
    await _check_paywall(request, current_user)

    signals, last_updated_at = await _signal_service.get_signals(db, strategy_id=strategy_id, limit=limit)

    membership = current_user.membership if current_user is not None else None
    signal_items = [SignalRead.model_validate(s).model_dump(context={"membership": membership}) for s in signals]

    return ok(data={"signals": signal_items, "last_updated_at": last_updated_at.isoformat()})


@router.get("/signals/latest-per-pair", response_model=ApiResponse[Any])
async def get_latest_per_pair(
    request: Request,
    timeframe: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(get_optional_user),
) -> ApiResponse[Any]:
    """每个 pair × strategy 取最新一条信号，前端首页聚合用。"""
    await _check_paywall(request, current_user)

    signals = await _signal_service.get_latest_per_pair(db, timeframe=timeframe)

    membership = current_user.membership if current_user is not None else None
    show_confidence = _is_vip(membership)
    items = [
        {
            "id": s.id,
            "strategy_id": s.strategy_id,
            "strategy_name": s.strategy_name,
            "pair": s.pair,
            "timeframe": s.timeframe,
            "direction": s.direction.value if hasattr(s.direction, "value") else s.direction,
            "signal_at": s.signal_at.isoformat(),
            "created_at": s.created_at.isoformat(),
            "confidence_score": s.confidence_score if show_confidence else None,
        }
        for s in signals
    ]
    return ok(data={"items": items, "total": len(items)})


@router.get("/signals", response_model=ApiResponse[Any])
async def list_all_signals(
    request: Request,
    pair: str | None = Query(default=None),
    timeframe: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=200, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(get_optional_user),
) -> ApiResponse[Any]:
    """全局信号列表，跨所有策略聚合，支持 pair/timeframe 过滤和分页。"""
    await _check_paywall(request, current_user)

    signals, total, _ = await _signal_service.list_signals(
        db, pair=pair, timeframe=timeframe, page=page, page_size=page_size
    )

    membership = current_user.membership if current_user is not None else None
    show_confidence = _is_vip(membership)
    items = [
        {
            "id": s.id,
            "strategy_id": s.strategy_id,
            "strategy_name": getattr(s, "strategy_name", None),
            "pair": s.pair,
            "timeframe": s.timeframe,
            "direction": s.direction.value if hasattr(s.direction, "value") else s.direction,
            "signal_at": s.signal_at.isoformat(),
            "created_at": s.created_at.isoformat(),
            "confidence_score": s.confidence_score if show_confidence else None,
        }
        for s in signals
    ]

    return ok(data={"items": items, "total": total, "page": page, "page_size": page_size})
