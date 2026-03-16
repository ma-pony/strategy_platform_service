"""顶级信号查询路由层（任务 5.3）。

新增两个信号查询端点：
  - GET /api/v1/signals：支持 strategy_id/pair/timeframe 过滤和 page/page_size 分页
  - GET /api/v1/signals/{strategy_id}：返回该策略所有激活交易对的最新信号

字段权限过滤：
  - 匿名/Free 用户：confidence_score 返回 null
  - VIP1 及以上：返回实际置信度数值

使用 get_optional_user 依赖注入，允许匿名访问。
"""

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.deps import get_db, get_optional_user
from src.core.response import ApiResponse, ok
from src.schemas.strategy import SignalRead
from src.services.signal_service import SignalService

router = APIRouter(prefix="/signals", tags=["signals-top"])

_signal_service = SignalService()


@router.get("", response_model=ApiResponse[Any])
async def list_signals(
    strategy_id: int | None = Query(default=None, description="按策略 ID 过滤"),
    pair: str | None = Query(default=None, description="按交易对过滤（如 BTC/USDT）"),
    timeframe: str | None = Query(default=None, description="按时间周期过滤（如 1h）"),
    page: int = Query(default=1, ge=1, description="页码（从 1 开始）"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页数量（最大 100）"),
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(get_optional_user),
) -> ApiResponse[Any]:
    """获取信号列表，支持过滤和分页。

    响应结构：
      {
        "code": 0,
        "data": {
          "items": [...],
          "total": 50,
          "page": 1,
          "page_size": 20
        }
      }

    字段权限过滤：
      - 所有用户可见：id, strategy_id, pair, direction, signal_at, created_at
      - VIP1 专属：confidence_score（匿名/Free 用户为 null）

    strategy_id 不存在时返回 code:3001 HTTP 404。
    """
    signals, total, _last_updated_at = await _signal_service.list_signals(
        db=db,
        strategy_id=strategy_id,
        pair=pair,
        timeframe=timeframe,
        page=page,
        page_size=page_size,
    )

    # 确定当前用户会员等级
    membership = current_user.membership if current_user is not None else None

    # 序列化并按权限过滤字段
    signal_items: list[Any] = []
    for signal in signals:
        schema = SignalRead.model_validate(signal)
        signal_items.append(schema.model_dump(context={"membership": membership}, by_alias=True))

    response_data: dict[str, Any] = {
        "items": signal_items,
        "total": total,
        "page": page,
        "page_size": page_size,
    }

    return ok(data=response_data)


@router.get("/{strategy_id}", response_model=ApiResponse[Any])
async def get_signals_by_strategy(
    strategy_id: int,
    page: int = Query(default=1, ge=1, description="页码（从 1 开始）"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页数量（最大 100）"),
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(get_optional_user),
) -> ApiResponse[Any]:
    """获取指定策略的最新信号（所有激活交易对）。

    响应结构：
      {
        "code": 0,
        "data": {
          "items": [...],
          "total": 10,
          "page": 1,
          "page_size": 20
        }
      }

    strategy_id 不存在时返回 code:3001 HTTP 404。
    """
    signals, total, _last_updated_at = await _signal_service.list_signals(
        db=db,
        strategy_id=strategy_id,
        page=page,
        page_size=page_size,
    )

    # 确定当前用户会员等级
    membership = current_user.membership if current_user is not None else None

    # 序列化并按权限过滤字段
    signal_items: list[Any] = []
    for signal in signals:
        schema = SignalRead.model_validate(signal)
        signal_items.append(schema.model_dump(context={"membership": membership}, by_alias=True))

    response_data: dict[str, Any] = {
        "items": signal_items,
        "total": total,
        "page": page,
        "page_size": page_size,
    }

    return ok(data=response_data)
