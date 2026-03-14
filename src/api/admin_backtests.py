"""管理员回测 API 路由层。

提供管理员专属回测端点：
  - POST /admin/backtests：提交回测任务
  - GET /admin/backtests/{task_id}：查询任务详情
  - GET /admin/backtests：分页列表

所有端点通过 Depends(require_admin) 强制管理员鉴权。
"""

import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.deps import get_db, require_admin
from src.core.enums import TaskStatus
from src.core.response import ApiResponse, PaginatedData, ok, paginated
from src.services.admin_backtest_service import AdminBacktestService

router = APIRouter(prefix="/admin/backtests", tags=["admin-backtests"])

_service = AdminBacktestService()


# ─────────────────────────────────────────────
# Request / Response Schemas
# ─────────────────────────────────────────────


class BacktestSubmitRequest(BaseModel):
    """回测提交请求。"""

    strategy_id: int
    timerange: str = Field(
        ...,
        description="回测时间范围，格式 YYYYMMDD-YYYYMMDD",
        pattern=r"^\d{8}-\d{8}$",
    )


class BacktestResultSummary(BaseModel):
    """回测结果摘要。"""

    total_return: float | None = None
    annual_return: float | None = None
    sharpe_ratio: float | None = None
    max_drawdown: float | None = None
    trade_count: int | None = None
    win_rate: float | None = None


class BacktestTaskRead(BaseModel):
    """回测任务响应。"""

    id: int
    strategy_id: int
    status: TaskStatus
    timerange: str | None = None
    error_message: str | None = None
    result_summary: BacktestResultSummary | None = None
    created_at: datetime.datetime
    updated_at: datetime.datetime

    model_config = {"from_attributes": True}


# ─────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────


@router.post("", response_model=ApiResponse[BacktestTaskRead])
async def submit_backtest(
    body: BacktestSubmitRequest,
    db: AsyncSession = Depends(get_db),
    admin: Any = Depends(require_admin),
) -> ApiResponse[BacktestTaskRead]:
    """提交回测任务，异步入队后立即返回。"""
    task = await _service.submit_backtest(
        db,
        strategy_id=body.strategy_id,
        timerange=body.timerange,
    )
    task_read = _task_to_read(task)
    return ok(data=task_read.model_dump())


@router.get("/{task_id}", response_model=ApiResponse[BacktestTaskRead])
async def get_backtest_task(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    admin: Any = Depends(require_admin),
) -> ApiResponse[BacktestTaskRead]:
    """查询单个回测任务详情。"""
    task = await _service.get_task(db, task_id=task_id)
    task_read = _task_to_read(task)
    return ok(data=task_read.model_dump())


@router.get("", response_model=ApiResponse[PaginatedData[BacktestTaskRead]])
async def list_backtest_tasks(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    strategy_name: str | None = Query(default=None),
    status: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    admin: Any = Depends(require_admin),
) -> ApiResponse[PaginatedData[Any]]:
    """分页查询回测任务列表，支持按策略名和状态筛选。"""
    tasks, total = await _service.list_tasks(
        db,
        page=page,
        page_size=page_size,
        strategy_name=strategy_name,
        status=status,
    )
    items = [_task_to_read(t).model_dump() for t in tasks]
    return paginated(items=items, total=total, page=page, page_size=page_size)


def _task_to_read(task: Any) -> BacktestTaskRead:
    """将 BacktestTask ORM 对象转换为响应 Schema。"""
    result_summary = None
    if task.result_json:
        result_summary = BacktestResultSummary(
            total_return=task.result_json.get("total_return"),
            annual_return=task.result_json.get("annual_return"),
            sharpe_ratio=task.result_json.get("sharpe_ratio"),
            max_drawdown=task.result_json.get("max_drawdown"),
            trade_count=task.result_json.get("trade_count"),
            win_rate=task.result_json.get("win_rate"),
        )
    return BacktestTaskRead(
        id=task.id,
        strategy_id=task.strategy_id,
        status=task.status,
        timerange=task.timerange,
        error_message=task.error_message,
        result_summary=result_summary,
        created_at=task.created_at,
        updated_at=task.updated_at,
    )
