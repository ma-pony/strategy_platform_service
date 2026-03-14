"""回测 API 路由层（任务 8.2）。

提供回测只读接口：
  - GET /strategies/{id}/backtests：分页列表，字段按会员等级过滤
  - GET /backtests/{id}：单条回测详情，字段按会员等级过滤

字段权限过滤通过 BacktestResultRead.model_dump(context={"membership": tier}) 实现。
使用 get_optional_user 注入可选用户（无 token 时返回 None 即匿名）。
"""

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.deps import get_db, get_optional_user
from src.core.response import ApiResponse, PaginatedData, ok, paginated
from src.schemas.strategy import BacktestResultRead
from src.services.backtest_service import BacktestService

router = APIRouter(tags=["backtests"])

_backtest_service = BacktestService()


@router.get("/strategies/{strategy_id}/backtests", response_model=ApiResponse[PaginatedData[Any]])
async def list_backtests(
    strategy_id: int,
    page: int = Query(default=1, ge=1, description="页码（从 1 开始）"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页数量（最大 100）"),
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(get_optional_user),
) -> ApiResponse[PaginatedData[Any]]:
    """获取指定策略的回测结果分页列表。

    匿名和已登录用户均可访问。
    字段按会员等级过滤：
      - 匿名：仅基础字段（id, strategy_id, task_id, period_start, period_end, created_at）
      - Free：含 total_return, trade_count, max_drawdown
      - VIP：含全部字段（含 sharpe_ratio, win_rate, annual_return）
    策略不存在时返回 code:3001 HTTP 404。
    """
    results, total = await _backtest_service.list_backtests(
        db, strategy_id=strategy_id, page=page, page_size=page_size
    )

    # 确定当前用户会员等级
    membership = current_user.membership if current_user is not None else None

    # 序列化并按权限过滤字段
    items: list[Any] = []
    for result in results:
        schema = BacktestResultRead.model_validate(result)
        items.append(schema.model_dump(context={"membership": membership}))

    return paginated(items=items, total=total, page=page, page_size=page_size)


@router.get("/backtests/{backtest_id}", response_model=ApiResponse[Any])
async def get_backtest(
    backtest_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(get_optional_user),
) -> ApiResponse[Any]:
    """获取单条回测结果详情。

    匿名和已登录用户均可访问。
    字段按会员等级过滤，回测记录不存在时返回 code:3001 HTTP 404。
    """
    backtest = await _backtest_service.get_backtest(db, backtest_id=backtest_id)

    # 确定当前用户会员等级
    membership = current_user.membership if current_user is not None else None

    # 序列化并按权限过滤字段
    schema = BacktestResultRead.model_validate(backtest)
    filtered_data = schema.model_dump(context={"membership": membership})

    return ok(data=filtered_data)
