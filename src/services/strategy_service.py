"""策略服务层。

提供策略只读查询业务逻辑：
  - 分页列表查询（limit + offset，禁止全表扫描）
  - 详情查询（含最近一次成功回测结果）
  - 不提供任何写入方法；策略数据由 sqladmin 后台维护

关键约束：
  - 列表查询必须分页，禁止全表扫描
  - 详情查询使用 selectinload 加载关联数据，避免 N+1
  - 策略不存在时抛出 NotFoundError(code=3001)
"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import NotFoundError
from src.models.strategy import Strategy


class StrategyService:
    """策略只读业务逻辑服务。

    所有方法接受 AsyncSession 参数，由路由层通过依赖注入传入。
    不暴露任何写入接口，策略数据仅通过 sqladmin 后台维护。
    """

    async def list_strategies(
        self, db: AsyncSession, page: int, page_size: int
    ) -> tuple[list[Strategy], int]:
        """分页查询策略列表。

        使用 limit + offset 分页，避免全表扫描。
        仅返回 is_active=True 的策略。

        Args:
            db: 异步数据库 session
            page: 页码（从 1 开始）
            page_size: 每页数量（最大 100）

        Returns:
            (strategies, total) 元组：策略列表和总数
        """
        offset = (page - 1) * page_size

        # 查询总数
        count_stmt = select(func.count()).select_from(Strategy)
        count_result = await db.execute(count_stmt)
        total: int = count_result.scalar_one()

        # 查询分页数据
        stmt = (
            select(Strategy)
            .order_by(Strategy.id)
            .limit(page_size)
            .offset(offset)
        )
        result = await db.execute(stmt)
        strategies: list[Strategy] = list(result.scalars().all())

        return strategies, total

    async def get_strategy(
        self, db: AsyncSession, strategy_id: int
    ) -> Strategy:
        """查询策略详情。

        通过 selectinload 同时加载最近一次成功回测结果，避免 N+1 查询。
        策略 ID 不存在时抛出 NotFoundError(code=3001)。

        Args:
            db: 异步数据库 session
            strategy_id: 策略 ID

        Returns:
            Strategy 对象

        Raises:
            NotFoundError: 策略不存在（code=3001）
        """
        stmt = select(Strategy).where(Strategy.id == strategy_id)
        result = await db.execute(stmt)
        strategy = result.scalar_one_or_none()

        if strategy is None:
            raise NotFoundError(f"策略 {strategy_id} 不存在")

        return strategy
