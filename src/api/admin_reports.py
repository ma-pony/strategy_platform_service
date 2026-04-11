"""管理员研报 CRUD API。

提供管理员专属研报管理端点：
  - POST /admin/reports：创建研报
  - PUT /admin/reports/{id}：更新研报
  - DELETE /admin/reports/{id}：删除研报

所有端点通过 Depends(require_admin_or_api_key) 强制管理员鉴权。
"""

import datetime
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.core.deps import get_db, require_admin_or_api_key
from src.core.exceptions import NotFoundError
from src.core.response import ApiResponse, ok
from src.models.report import ReportCoin, ResearchReport

router = APIRouter(prefix="/admin/reports", tags=["admin-reports"])


# ─────────────────────────────────────────────
# Request / Response Schemas
# ─────────────────────────────────────────────


class ReportCreateRequest(BaseModel):
    """创建研报请求。"""

    title: str = Field(..., max_length=256)
    summary: str
    content: str
    related_coins: list[str] = Field(default_factory=list, description="关联币种列表，如 ['BTC', 'ETH']")


class ReportUpdateRequest(BaseModel):
    """更新研报请求（所有字段可选）。"""

    title: str | None = Field(None, max_length=256)
    summary: str | None = None
    content: str | None = None
    related_coins: list[str] | None = Field(None, description="关联币种列表（传入则全量替换）")


class ReportResponse(BaseModel):
    """研报响应。"""

    id: int
    title: str
    summary: str
    content: str
    generated_at: datetime.datetime
    related_coins: list[str] = Field(default_factory=list)

    model_config = {"from_attributes": True}


# ─────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────


@router.post("", response_model=ApiResponse[ReportResponse])
async def create_report(
    body: ReportCreateRequest,
    db: AsyncSession = Depends(get_db),
    admin: Any = Depends(require_admin_or_api_key),
) -> ApiResponse[ReportResponse]:
    """创建研报。"""
    report = ResearchReport(
        title=body.title,
        summary=body.summary,
        content=body.content,
        generated_at=datetime.datetime.now(tz=datetime.timezone.utc),
    )
    db.add(report)
    await db.flush()

    for coin_symbol in body.related_coins:
        db.add(ReportCoin(report_id=report.id, coin_symbol=coin_symbol.upper()))

    await db.commit()
    await db.refresh(report, attribute_names=["coins"])

    return ok(data=_to_response(report).model_dump())


@router.put("/{report_id}", response_model=ApiResponse[ReportResponse])
async def update_report(
    report_id: int,
    body: ReportUpdateRequest,
    db: AsyncSession = Depends(get_db),
    admin: Any = Depends(require_admin_or_api_key),
) -> ApiResponse[ReportResponse]:
    """更新研报。"""
    from sqlalchemy import select

    stmt = select(ResearchReport).options(selectinload(ResearchReport.coins)).where(ResearchReport.id == report_id)
    result = await db.execute(stmt)
    report = result.scalar_one_or_none()

    if report is None:
        raise NotFoundError(f"研报 {report_id} 不存在")

    if body.title is not None:
        report.title = body.title
    if body.summary is not None:
        report.summary = body.summary
    if body.content is not None:
        report.content = body.content

    if body.related_coins is not None:
        await db.execute(delete(ReportCoin).where(ReportCoin.report_id == report_id))
        for coin_symbol in body.related_coins:
            db.add(ReportCoin(report_id=report.id, coin_symbol=coin_symbol.upper()))

    await db.commit()
    await db.refresh(report, attribute_names=["coins"])

    return ok(data=_to_response(report).model_dump())


@router.delete("/{report_id}", response_model=ApiResponse[Any])
async def delete_report(
    report_id: int,
    db: AsyncSession = Depends(get_db),
    admin: Any = Depends(require_admin_or_api_key),
) -> ApiResponse[Any]:
    """删除研报。"""
    from sqlalchemy import select

    stmt = select(ResearchReport).where(ResearchReport.id == report_id)
    result = await db.execute(stmt)
    report = result.scalar_one_or_none()

    if report is None:
        raise NotFoundError(f"研报 {report_id} 不存在")

    await db.delete(report)
    await db.commit()

    return ok(data={"id": report_id, "deleted": True})


def _to_response(report: ResearchReport) -> ReportResponse:
    """将 ORM 对象转换为响应 Schema。"""
    return ReportResponse(
        id=report.id,
        title=report.title,
        summary=report.summary,
        content=report.content,
        generated_at=report.generated_at,
        related_coins=[coin.coin_symbol for coin in (report.coins or [])],
    )
