"""研报 API 路由层（任务 10.2）。

提供 AI 市场研报只读接口：
  - GET /reports：分页列表，允许匿名访问
  - GET /reports/{id}：单条研报详情（含完整 content），允许匿名访问

关键约束：
  - 两个接口均允许匿名访问，不使用 get_current_user（无需 JWT 鉴权）
  - 研报不存在时返回 code:3001 HTTP 404
  - 响应符合统一信封格式
  - 列表接口返回摘要字段（不含 content）；详情接口返回全量字段
  - 关联币种通过 coins 关系属性加载后序列化为 related_coins 列表
"""

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.deps import get_db
from src.core.response import ApiResponse, PaginatedData, ok, paginated
from src.schemas.strategy import ReportDetailRead, ReportRead
from src.services.report_service import ReportService

router = APIRouter(tags=["reports"])

_report_service = ReportService()


def _serialize_report_read(report: Any) -> dict[str, Any]:
    """将 ResearchReport ORM 对象序列化为 ReportRead 格式（列表摘要）。

    关联币种从 report.coins 关系属性读取并转换为 related_coins 列表。
    """
    # 提取关联币种
    related_coins = [coin.coin_symbol for coin in (report.coins or [])]

    return ReportRead(
        id=report.id,
        title=report.title,
        summary=report.summary,
        generated_at=report.generated_at,
        related_coins=related_coins,
    ).model_dump()


def _serialize_report_detail_read(report: Any) -> dict[str, Any]:
    """将 ResearchReport ORM 对象序列化为 ReportDetailRead 格式（含完整 content）。

    关联币种从 report.coins 关系属性读取并转换为 related_coins 列表。
    """
    related_coins = [coin.coin_symbol for coin in (report.coins or [])]

    return ReportDetailRead(
        id=report.id,
        title=report.title,
        summary=report.summary,
        content=report.content,
        generated_at=report.generated_at,
        related_coins=related_coins,
    ).model_dump()


@router.get("/reports", response_model=ApiResponse[PaginatedData[Any]])
async def list_reports(
    page: int = Query(default=1, ge=1, description="页码（从 1 开始）"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页数量（最大 100）"),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[PaginatedData[Any]]:
    """获取研报分页列表。

    允许匿名访问，无需 JWT 鉴权。
    返回摘要字段（id、title、summary、generated_at、related_coins），不含 content。
    默认 page_size=20，最大 100。
    """
    reports, total = await _report_service.list_reports(
        db, page=page, page_size=page_size
    )

    items: list[Any] = [_serialize_report_read(report) for report in reports]

    return paginated(items=items, total=total, page=page, page_size=page_size)


@router.get("/reports/{report_id}", response_model=ApiResponse[Any])
async def get_report(
    report_id: int,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[Any]:
    """获取单条研报详情（含完整 content 字段）。

    允许匿名访问，无需 JWT 鉴权。
    研报不存在时返回 code:3001 HTTP 404。
    """
    report = await _report_service.get_report(db, report_id=report_id)

    return ok(data=_serialize_report_detail_read(report))
