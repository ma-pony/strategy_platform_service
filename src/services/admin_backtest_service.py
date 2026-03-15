"""管理员回测服务层。

提供管理员专属的回测任务提交、查询功能：
  - submit_backtest: 校验策略 → 创建 PENDING 任务 → 异步入队 → 返回 task_id
  - get_task: 查询单个回测任务详情
  - list_tasks: 分页列表，支持按策略名和状态筛选

关键约束：
  - 任务始终可入队，不检查 RUNNING 数量
  - 提交后立即返回，不等待回测执行结果
"""

import datetime
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.enums import TaskStatus
from src.core.exceptions import NotFoundError
from src.freqtrade_bridge.strategy_registry import lookup
from src.models.backtest import BacktestTask
from src.models.strategy import Strategy


class AdminBacktestService:
    """管理员回测业务逻辑服务。"""

    async def submit_backtest(
        self,
        db: AsyncSession,
        strategy_id: int,
        timerange: str,
    ) -> BacktestTask:
        """提交回测任务。

        校验策略在注册表中存在，创建 PENDING 任务后通过 Celery 异步入队。

        Args:
            db: 异步数据库 session
            strategy_id: 策略 ID
            timerange: 回测时间范围（YYYYMMDD-YYYYMMDD）

        Returns:
            创建的 BacktestTask 对象（status=PENDING）

        Raises:
            NotFoundError: 策略不存在
            UnsupportedStrategyError: 策略不在注册表中
        """
        # 1. 查询策略
        strategy = await db.get(Strategy, strategy_id)
        if strategy is None:
            raise NotFoundError(f"策略 {strategy_id} 不存在")

        # 2. 校验策略在注册表中
        lookup(strategy.name)  # 不存在则抛 UnsupportedStrategyError

        # 3. 预检临时目录可用性
        tmp_base = Path("/tmp/freqtrade_jobs")  # noqa: S108
        try:
            tmp_base.mkdir(parents=True, exist_ok=True)  # noqa: ASYNC240
        except OSError:
            from src.core.exceptions import FreqtradeError

            raise FreqtradeError("临时目录不可用，请联系管理员") from None

        # 4. 创建 PENDING 任务
        task = BacktestTask(
            strategy_id=strategy_id,
            scheduled_date=datetime.date.today(),
            status=TaskStatus.PENDING,
            timerange=timerange,
        )
        db.add(task)
        await db.flush()

        # 5. 通过 Celery 异步入队
        from src.workers.celery_app import celery_app

        celery_app.send_task(
            "src.workers.tasks.backtest_tasks.run_backtest_task",
            args=[strategy_id],
            queue="backtest",
        )

        await db.commit()
        await db.refresh(task)
        return task

    async def get_task(
        self,
        db: AsyncSession,
        task_id: int,
    ) -> BacktestTask:
        """查询单个回测任务。

        Raises:
            NotFoundError: 任务不存在
        """
        task = await db.get(BacktestTask, task_id)
        if task is None:
            raise NotFoundError(f"回测任务 {task_id} 不存在")
        return task

    async def list_tasks(
        self,
        db: AsyncSession,
        page: int,
        page_size: int,
        strategy_name: str | None = None,
        status: str | None = None,
    ) -> tuple[list[BacktestTask], int]:
        """分页查询回测任务列表。

        Args:
            db: 异步数据库 session
            page: 页码（从 1 开始）
            page_size: 每页数量
            strategy_name: 按策略名筛选（可选）
            status: 按状态筛选（可选）

        Returns:
            (tasks, total) 元组
        """
        offset = (page - 1) * page_size

        # 构建基础查询
        base_query = select(BacktestTask)
        count_query = select(func.count()).select_from(BacktestTask)

        # 按策略名筛选
        if strategy_name:
            strategy_stmt = select(Strategy.id).where(Strategy.name == strategy_name)
            result = await db.execute(strategy_stmt)
            strategy_id = result.scalar_one_or_none()
            if strategy_id is None:
                return [], 0
            base_query = base_query.where(BacktestTask.strategy_id == strategy_id)
            count_query = count_query.where(BacktestTask.strategy_id == strategy_id)

        # 按状态筛选
        if status:
            try:
                task_status = TaskStatus(status)
            except ValueError:
                return [], 0
            base_query = base_query.where(BacktestTask.status == task_status)
            count_query = count_query.where(BacktestTask.status == task_status)

        # 总数
        count_result = await db.execute(count_query)
        total: int = count_result.scalar_one()

        # 分页数据
        stmt = base_query.order_by(BacktestTask.created_at.desc()).limit(page_size).offset(offset)
        result = await db.execute(stmt)
        tasks: list[BacktestTask] = list(result.scalars().all())

        return tasks, total
