"""回测服务层（任务 8.1）。

提供回测结果只读查询业务逻辑：
  - 按 strategy_id 过滤的分页查询，按 created_at 降序
  - 单条回测结果查询，不存在时抛出 NotFoundError(code=3001)
  - 不提供任何触发回测的方法；业务层不直接调用 freqtrade

关键约束：
  - 所有查询按 created_at 降序排列
  - 分页使用 limit + offset，禁止全表扫描
  - 回测记录不存在时抛出 NotFoundError(code=3001)
"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import NotFoundError
from src.models.backtest import BacktestResult


class BacktestService:
    """回测结果只读业务逻辑服务。

    所有方法接受 AsyncSession 参数，由路由层通过依赖注入传入。
    不暴露任何写入接口，回测由 Celery 任务异步触发。
    """

    async def list_backtests(
        self,
        db: AsyncSession,
        strategy_id: int,
        page: int,
        page_size: int,
    ) -> tuple[list[BacktestResult], int]:
        """按 strategy_id 分页查询回测结果列表。

        结果按 created_at 降序排列（最新的在前）。

        Args:
            db: 异步数据库 session
            strategy_id: 策略 ID（过滤条件）
            page: 页码（从 1 开始）
            page_size: 每页数量（最大 100）

        Returns:
            (results, total) 元组：回测结果列表和该策略下的总数
        """
        offset = (page - 1) * page_size

        # 查询该策略下的总数
        count_stmt = (
            select(func.count())
            .select_from(BacktestResult)
            .where(BacktestResult.strategy_id == strategy_id)
        )
        count_result = await db.execute(count_stmt)
        total: int = count_result.scalar_one()

        # 查询分页数据（按 created_at 降序）
        stmt = (
            select(BacktestResult)
            .where(BacktestResult.strategy_id == strategy_id)
            .order_by(BacktestResult.created_at.desc())
            .limit(page_size)
            .offset(offset)
        )
        result = await db.execute(stmt)
        backtest_results: list[BacktestResult] = list(result.scalars().all())

        return backtest_results, total

    async def get_backtest(
        self,
        db: AsyncSession,
        backtest_id: int,
    ) -> BacktestResult:
        """查询单条回测结果详情。

        Args:
            db: 异步数据库 session
            backtest_id: 回测结果 ID

        Returns:
            BacktestResult 对象

        Raises:
            NotFoundError: 回测记录不存在（code=3001）
        """
        stmt = select(BacktestResult).where(BacktestResult.id == backtest_id)
        result = await db.execute(stmt)
        backtest = result.scalar_one_or_none()

        if backtest is None:
            raise NotFoundError(f"回测记录 {backtest_id} 不存在")

        return backtest
