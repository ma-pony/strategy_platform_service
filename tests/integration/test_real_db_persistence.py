"""真实数据库持久化集成测试（任务 10.1）。

通过真实 PostgreSQL 异步 session 验证 ORM 写入与查询一致性：
  - BacktestTask + BacktestResult 六项核心指标持久化与查询验证
  - User 会员等级持久化与查询验证

所有测试标记 @pytest.mark.integration_db，依赖真实 PostgreSQL。
若 TEST_DATABASE_URL 未设置或无法连接，测试将被跳过（非失败）。

对应需求：3.8（回测结果数据持久化）、8.1（真实 PostgreSQL + Alembic）
"""

from __future__ import annotations

import datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


pytestmark = pytest.mark.integration_db


class TestBacktestPersistence:
    """回测任务与结果持久化测试（需求 3.8）。

    通过真实 async session 插入 BacktestTask + BacktestResult，
    commit 后重新查询，断言六项核心指标值与写入值一致。
    """

    async def test_backtest_task_and_result_persist_correctly(
        self, real_db_session: AsyncSession
    ) -> None:
        """插入 BacktestTask + BacktestResult，commit 后重查，验证六项核心指标一致。

        六项核心指标：
          total_return、annual_return、sharpe_ratio、
          max_drawdown、trade_count、win_rate
        """
        from src.core.enums import MembershipTier, TaskStatus
        from src.models.backtest import BacktestResult, BacktestTask
        from src.models.strategy import Strategy
        from src.models.user import User

        # 1. 插入 User（FK 依赖）
        user = User(
            username="db_persist_test_user",
            hashed_password="hashed_pw_placeholder",
            membership=MembershipTier.VIP1,
            is_active=True,
            is_admin=False,
        )
        real_db_session.add(user)
        await real_db_session.flush()  # 获取 user.id

        # 2. 插入 Strategy（FK 依赖）
        strategy = Strategy(
            name="PersistTestStrategy",
            description="用于持久化测试的策略",
            strategy_type="mean_reversion",
            pairs=["BTC/USDT"],
            config_params={"timeframe": "5m"},
            is_active=True,
        )
        real_db_session.add(strategy)
        await real_db_session.flush()  # 获取 strategy.id

        # 3. 插入 BacktestTask
        task = BacktestTask(
            strategy_id=strategy.id,
            scheduled_date=datetime.date(2024, 6, 1),
            status=TaskStatus.DONE,
            timerange="20240101-20240601",
        )
        real_db_session.add(task)
        await real_db_session.flush()  # 获取 task.id

        # 4. 定义六项核心指标
        expected_total_return = 0.1523
        expected_annual_return = 0.2041
        expected_sharpe_ratio = 1.35
        expected_max_drawdown = 0.0821
        expected_trade_count = 47
        expected_win_rate = 0.6383

        # 5. 插入 BacktestResult（含六项核心指标）
        result = BacktestResult(
            strategy_id=strategy.id,
            task_id=task.id,
            total_return=expected_total_return,
            annual_return=expected_annual_return,
            sharpe_ratio=expected_sharpe_ratio,
            max_drawdown=expected_max_drawdown,
            trade_count=expected_trade_count,
            win_rate=expected_win_rate,
            period_start=datetime.datetime(2024, 1, 1, tzinfo=datetime.timezone.utc),
            period_end=datetime.datetime(2024, 6, 1, tzinfo=datetime.timezone.utc),
        )
        real_db_session.add(result)

        # 6. Commit 持久化到真实 DB
        await real_db_session.commit()

        # 7. 重新查询，验证数据一致性
        stmt = select(BacktestResult).where(BacktestResult.task_id == task.id)
        query_result = await real_db_session.execute(stmt)
        persisted = query_result.scalar_one_or_none()

        assert persisted is not None, "BacktestResult 应已持久化，但查询返回 None"
        assert persisted.strategy_id == strategy.id
        assert persisted.task_id == task.id

        # 验证六项核心指标写入与查询一致
        assert abs(persisted.total_return - expected_total_return) < 1e-6, (
            f"total_return 不匹配：期望 {expected_total_return}，实际 {persisted.total_return}"
        )
        assert abs(persisted.annual_return - expected_annual_return) < 1e-6, (
            f"annual_return 不匹配：期望 {expected_annual_return}，实际 {persisted.annual_return}"
        )
        assert abs(persisted.sharpe_ratio - expected_sharpe_ratio) < 1e-6, (
            f"sharpe_ratio 不匹配：期望 {expected_sharpe_ratio}，实际 {persisted.sharpe_ratio}"
        )
        assert abs(persisted.max_drawdown - expected_max_drawdown) < 1e-6, (
            f"max_drawdown 不匹配：期望 {expected_max_drawdown}，实际 {persisted.max_drawdown}"
        )
        assert persisted.trade_count == expected_trade_count, (
            f"trade_count 不匹配：期望 {expected_trade_count}，实际 {persisted.trade_count}"
        )
        assert abs(persisted.win_rate - expected_win_rate) < 1e-6, (
            f"win_rate 不匹配：期望 {expected_win_rate}，实际 {persisted.win_rate}"
        )

    async def test_backtest_task_status_persists(
        self, real_db_session: AsyncSession
    ) -> None:
        """验证 BacktestTask 状态流转后持久化正确。"""
        from src.core.enums import TaskStatus
        from src.models.backtest import BacktestTask
        from src.models.strategy import Strategy

        strategy = Strategy(
            name="StatusPersistStrategy",
            description="状态持久化测试",
            strategy_type="trend_following",
            pairs=["ETH/USDT"],
            config_params={},
            is_active=True,
        )
        real_db_session.add(strategy)
        await real_db_session.flush()

        task = BacktestTask(
            strategy_id=strategy.id,
            scheduled_date=datetime.date(2024, 7, 1),
            status=TaskStatus.PENDING,
            timerange="20240601-20240701",
        )
        real_db_session.add(task)
        await real_db_session.commit()

        # 状态流转：PENDING → RUNNING → DONE
        task.status = TaskStatus.RUNNING
        await real_db_session.commit()

        task.status = TaskStatus.DONE
        await real_db_session.commit()

        # 重查验证状态
        stmt = select(BacktestTask).where(BacktestTask.id == task.id)
        query_result = await real_db_session.execute(stmt)
        persisted_task = query_result.scalar_one_or_none()

        assert persisted_task is not None
        assert persisted_task.status == TaskStatus.DONE


class TestUserMembershipPersistence:
    """用户会员等级持久化测试（需求 8.1）。

    插入 User 对象后查询，验证 membership 字段正确持久化。
    """

    async def test_user_with_free_membership_persists_correctly(
        self, real_db_session: AsyncSession
    ) -> None:
        """插入 FREE 等级用户，commit 后重查，验证 membership 字段正确持久化。"""
        from src.core.enums import MembershipTier
        from src.models.user import User

        user = User(
            username="free_member_persist_test",
            hashed_password="hashed_free_pw",
            membership=MembershipTier.FREE,
            is_active=True,
            is_admin=False,
        )
        real_db_session.add(user)
        await real_db_session.commit()

        # 重新查询
        stmt = select(User).where(User.username == "free_member_persist_test")
        query_result = await real_db_session.execute(stmt)
        persisted_user = query_result.scalar_one_or_none()

        assert persisted_user is not None
        assert persisted_user.username == "free_member_persist_test"
        assert persisted_user.membership == MembershipTier.FREE
        assert persisted_user.is_active is True
        assert persisted_user.is_admin is False

    async def test_user_with_vip1_membership_persists_correctly(
        self, real_db_session: AsyncSession
    ) -> None:
        """插入 VIP1 等级用户，commit 后重查，验证 membership 字段正确持久化。"""
        from src.core.enums import MembershipTier
        from src.models.user import User

        user = User(
            username="vip1_member_persist_test",
            hashed_password="hashed_vip1_pw",
            membership=MembershipTier.VIP1,
            is_active=True,
            is_admin=False,
        )
        real_db_session.add(user)
        await real_db_session.commit()

        stmt = select(User).where(User.username == "vip1_member_persist_test")
        query_result = await real_db_session.execute(stmt)
        persisted_user = query_result.scalar_one_or_none()

        assert persisted_user is not None
        assert persisted_user.membership == MembershipTier.VIP1

    async def test_user_with_vip2_membership_persists_correctly(
        self, real_db_session: AsyncSession
    ) -> None:
        """插入 VIP2 等级用户，commit 后重查，验证 membership 字段正确持久化。"""
        from src.core.enums import MembershipTier
        from src.models.user import User

        user = User(
            username="vip2_member_persist_test",
            hashed_password="hashed_vip2_pw",
            membership=MembershipTier.VIP2,
            is_active=True,
            is_admin=False,
        )
        real_db_session.add(user)
        await real_db_session.commit()

        stmt = select(User).where(User.username == "vip2_member_persist_test")
        query_result = await real_db_session.execute(stmt)
        persisted_user = query_result.scalar_one_or_none()

        assert persisted_user is not None
        assert persisted_user.membership == MembershipTier.VIP2

    async def test_user_membership_upgrade_persists(
        self, real_db_session: AsyncSession
    ) -> None:
        """验证用户会员等级从 FREE 升级到 VIP2 后，新等级正确持久化。"""
        from src.core.enums import MembershipTier
        from src.models.user import User

        user = User(
            username="upgrade_test_user",
            hashed_password="hashed_pw_upgrade",
            membership=MembershipTier.FREE,
            is_active=True,
            is_admin=False,
        )
        real_db_session.add(user)
        await real_db_session.commit()

        # 升级会员等级
        user.membership = MembershipTier.VIP2
        await real_db_session.commit()

        # 重查验证升级后的等级
        stmt = select(User).where(User.username == "upgrade_test_user")
        query_result = await real_db_session.execute(stmt)
        persisted_user = query_result.scalar_one_or_none()

        assert persisted_user is not None
        assert persisted_user.membership == MembershipTier.VIP2
