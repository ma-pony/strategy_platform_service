"""研报服务层（任务 10.1）。

提供 AI 市场研报只读查询业务逻辑：
  - 分页列表查询（limit + offset，按 generated_at 降序）
  - 单条研报详情查询（含完整 content 字段）
  - 研报不存在时抛出 NotFoundError(code=3001)
  - 不提供任何写入操作

关键约束：
  - 所有查询按 generated_at 降序排列（最新的在前）
  - 分页使用 limit + offset，禁止全表扫描
  - 研报不存在时抛出 NotFoundError(code=3001)
  - 使用 selectinload 加载关联 ReportCoin，避免 N+1 查询
"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.core.exceptions import NotFoundError
from src.models.report import ReportCoin, ResearchReport


class ReportService:
    """AI 市场研报只读业务逻辑服务。

    所有方法接受 AsyncSession 参数，由路由层通过依赖注入传入。
    不暴露任何写入接口，研报数据通过 sqladmin 后台维护。
    允许匿名访问，无需 JWT 鉴权。
    """

    async def list_reports(
        self,
        db: AsyncSession,
        page: int,
        page_size: int,
    ) -> tuple[list[ResearchReport], int]:
        """分页查询研报列表。

        结果按 generated_at 降序排列（最新的在前）。
        通过 selectinload 预加载关联 ReportCoin，避免 N+1 查询。

        Args:
            db: 异步数据库 session
            page: 页码（从 1 开始）
            page_size: 每页数量（最大 100）

        Returns:
            (reports, total) 元组：研报列表和总数
        """
        offset = (page - 1) * page_size

        # 查询总数
        count_stmt = select(func.count()).select_from(ResearchReport)
        count_result = await db.execute(count_stmt)
        total: int = count_result.scalar_one()

        # 查询分页数据（按 generated_at 降序），预加载关联币种
        stmt = (
            select(ResearchReport)
            .options(selectinload(ResearchReport.coins))
            .order_by(ResearchReport.generated_at.desc())
            .limit(page_size)
            .offset(offset)
        )
        result = await db.execute(stmt)
        reports: list[ResearchReport] = list(result.scalars().all())

        return reports, total

    async def get_report(
        self,
        db: AsyncSession,
        report_id: int,
    ) -> ResearchReport:
        """查询单条研报详情（含完整 content 字段）。

        通过 selectinload 预加载关联 ReportCoin，避免 N+1 查询。

        Args:
            db: 异步数据库 session
            report_id: 研报 ID

        Returns:
            ResearchReport 对象

        Raises:
            NotFoundError: 研报不存在（code=3001）
        """
        stmt = (
            select(ResearchReport)
            .options(selectinload(ResearchReport.coins))
            .where(ResearchReport.id == report_id)
        )
        result = await db.execute(stmt)
        report = result.scalar_one_or_none()

        if report is None:
            raise NotFoundError(f"研报 {report_id} 不存在")

        return report
