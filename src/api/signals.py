"""信号 API 路由层（任务 9.2）。

提供交易信号只读接口：
  - GET /strategies/{id}/signals：信号列表（含 last_updated_at 时效字段）

字段权限过滤：
  - VIP 用户响应含 confidence_score
  - 匿名和 Free 用户该字段不返回或返回 null

使用 get_optional_user 注入可选用户（无 token 时返回 None 即匿名）。
"""

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.deps import get_db, get_optional_user
from src.core.response import ApiResponse, ok
from src.schemas.strategy import SignalRead
from src.services.signal_service import SignalService

router = APIRouter(tags=["signals"])

_signal_service = SignalService()


@router.get("/strategies/{strategy_id}/signals", response_model=ApiResponse[Any])
async def get_signals(
    strategy_id: int,
    limit: int = Query(default=20, ge=1, le=100, description="返回信号数量（最大 100）"),
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(get_optional_user),
) -> ApiResponse[Any]:
    """获取指定策略的交易信号列表。

    响应结构：
      {
        "code": 0,
        "data": {
          "signals": [...],
          "last_updated_at": "..."
        }
      }

    字段权限过滤：
      - 所有用户可见：id, strategy_id, pair, direction, signal_at, created_at
      - VIP 专属：confidence_score（匿名/Free 用户该字段为 null）

    策略不存在时返回 code:3001 HTTP 404。
    """
    signals, last_updated_at = await _signal_service.get_signals(db, strategy_id=strategy_id, limit=limit)

    # 确定当前用户会员等级
    membership = current_user.membership if current_user is not None else None

    # 序列化并按权限过滤字段
    signal_items: list[Any] = []
    for signal in signals:
        schema = SignalRead.model_validate(signal)
        signal_items.append(schema.model_dump(context={"membership": membership}))

    response_data = {
        "signals": signal_items,
        "last_updated_at": last_updated_at.isoformat(),
    }

    return ok(data=response_data)
