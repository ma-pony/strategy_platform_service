"""策略 API 路由层（任务 5.2）。

提供策略只读接口：
  - GET /strategies：分页列表，匿名和已登录用户均可访问
  - GET /strategies/{id}：策略详情，字段按会员等级过滤

字段权限过滤通过 StrategyRead.model_dump(context={"membership": tier}) 实现。
使用 get_optional_user 注入可选用户（无 token 时返回 None 即匿名）。
"""

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.deps import get_db, get_optional_user
from src.core.response import ApiResponse, PaginatedData, ok, paginated
from src.schemas.strategy import StrategyRead
from src.services.strategy_service import StrategyService

router = APIRouter(prefix="/strategies", tags=["strategies"])

_strategy_service = StrategyService()


@router.get("", response_model=ApiResponse[PaginatedData[Any]])
async def list_strategies(
    page: int = Query(default=1, ge=1, description="页码（从 1 开始）"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页数量（最大 100）"),
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(get_optional_user),
) -> ApiResponse[PaginatedData[Any]]:
    """获取策略分页列表。

    匿名和已登录用户均可访问。
    字段按会员等级过滤：匿名仅基础字段，Free 含中级指标，VIP 含全部字段。
    """
    strategies, total = await _strategy_service.list_strategies(db, page=page, page_size=page_size)

    # 确定当前用户会员等级
    membership = current_user.membership if current_user is not None else None

    # 序列化并按权限过滤字段
    items: list[Any] = []
    for strategy in strategies:
        schema = StrategyRead.model_validate(strategy)
        items.append(schema.model_dump(context={"membership": membership}))

    return paginated(items=items, total=total, page=page, page_size=page_size)


@router.get("/{strategy_id}", response_model=ApiResponse[Any])
async def get_strategy(
    strategy_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(get_optional_user),
) -> ApiResponse[Any]:
    """获取策略详情。

    匿名和已登录用户均可访问。
    字段按会员等级过滤，策略不存在时返回 code:3001 HTTP 404。
    """
    strategy = await _strategy_service.get_strategy(db, strategy_id=strategy_id)

    # 确定当前用户会员等级
    membership = current_user.membership if current_user is not None else None

    # 序列化并按权限过滤字段
    schema = StrategyRead.model_validate(strategy)
    filtered_data = schema.model_dump(context={"membership": membership})

    return ok(data=filtered_data)
