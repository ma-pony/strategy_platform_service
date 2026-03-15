"""集成测试目录级 fixtures：真实 PostgreSQL 数据库集成测试基础设施（RealDBFixture）。

职责：
  - real_db_engine：session 作用域，读取 TEST_DATABASE_URL，连接不可达时 pytest.skip
  - alembic_setup：session 作用域，在真实 DB 就绪后执行 alembic upgrade head，
                   session teardown 时执行 alembic downgrade base
  - real_db_session：function 作用域，每个测试获得独立 AsyncSession，
                     测试后 TRUNCATE 所有业务表实现数据隔离

辅助函数 _check_test_database_url() 供 TDD 测试直接调用，验证跳过逻辑。

要求的环境变量：
  - TEST_DATABASE_URL：格式 postgresql+asyncpg://user:pass@host:port/dbname
  - TEST_DATABASE_SYNC_URL（可选）：格式 postgresql+psycopg2://...
    若未设置，则通过替换驱动名从 TEST_DATABASE_URL 推导

对应需求：8.1（真实 PostgreSQL + Alembic）、8.5（不可达时 skip）
"""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator, Generator
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

# 测试结束后 TRUNCATE 的业务表（按外键依赖顺序，子表先于父表）
_TABLES_TO_TRUNCATE: tuple[str, ...] = (
    "backtest_results",
    "backtest_tasks",
    "trading_signals",
    "report_coins",
    "research_reports",
    "strategies",
    "users",
)


# ─── 辅助函数（供 TDD 测试直接调用）─────────────────────────────────────────────

def _check_test_database_url() -> str:
    """检查 TEST_DATABASE_URL 环境变量是否已设置。

    若未设置，调用 pytest.skip() 跳过并输出明确原因。

    Returns:
        str: TEST_DATABASE_URL 的值（已验证非空）

    Raises:
        pytest.skip.Exception: 若 TEST_DATABASE_URL 未设置
    """
    url = os.environ.get("TEST_DATABASE_URL", "").strip()
    if not url:
        pytest.skip(
            "TEST_DATABASE_URL 未设置，跳过真实数据库集成测试。"
            "若要运行这些测试，请先启动测试 PostgreSQL 实例并设置环境变量，例如：\n"
            "  export TEST_DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/test_db"
        )
    return url


def _derive_sync_url(async_url: str) -> str:
    """从异步 URL 推导同步 URL（供 Alembic 使用）。

    将 asyncpg 驱动替换为 psycopg2：
      postgresql+asyncpg://... → postgresql+psycopg2://...

    Args:
        async_url: asyncpg 格式的数据库 URL

    Returns:
        str: psycopg2 格式的同步 URL
    """
    return async_url.replace("postgresql+asyncpg://", "postgresql+psycopg2://", 1)


# ─── Session 作用域：真实 DB 引擎 ────────────────────────────────────────────────

@pytest.fixture(scope="session")
def real_db_engine() -> Generator[AsyncEngine, None, None]:
    """Session 作用域的真实 PostgreSQL 异步引擎 fixture（需求 8.1、8.5）。

    行为：
      1. 读取 TEST_DATABASE_URL 环境变量
      2. 若未设置，调用 pytest.skip() 跳过整个 session 的 integration_db 测试
      3. 若已设置，尝试建立连接；若连接失败，同样 skip
      4. yield 引擎供其他 fixtures 使用
      5. teardown 时关闭引擎连接池

    Yields:
        AsyncEngine: 已验证连通的 SQLAlchemy 异步引擎
    """
    db_url = _check_test_database_url()

    engine = create_async_engine(
        db_url,
        echo=False,
        pool_pre_ping=True,
        pool_size=2,
        max_overflow=0,
    )

    # 同步验证连接可达性（通过 run_sync 在同步上下文测试连接）
    import asyncio

    async def _ping() -> None:
        async with engine.begin() as conn:
            from sqlalchemy import text
            await conn.execute(text("SELECT 1"))

    try:
        asyncio.get_event_loop().run_until_complete(_ping())
    except Exception as exc:
        pytest.skip(
            f"TEST_DATABASE_URL 设置了，但无法连接到数据库（{exc}）。"
            "请确认 PostgreSQL 实例已启动且连接参数正确。"
        )

    yield engine

    # teardown：关闭连接池
    asyncio.get_event_loop().run_until_complete(engine.dispose())


# ─── Session 作用域：Alembic 迁移 ────────────────────────────────────────────────

@pytest.fixture(scope="session")
def alembic_setup(real_db_engine: AsyncEngine) -> Generator[None, None, None]:
    """Session 作用域的 Alembic 迁移 fixture（需求 8.1）。

    在测试 session 开始时执行 alembic upgrade head（建表），
    session 结束时执行 alembic downgrade base（清理 Schema）。

    使用 alembic.config.Config API 而非 subprocess，确保路径与当前进程一致。
    同步 URL 由 TEST_DATABASE_SYNC_URL 或从 TEST_DATABASE_URL 推导。

    Args:
        real_db_engine: 已验证连通的异步引擎（确保 DB 可达后才执行迁移）

    Yields:
        None
    """
    import os
    from pathlib import Path

    from alembic import command
    from alembic.config import Config

    # 确定项目根目录（alembic.ini 所在位置）
    project_root = Path(__file__).parent.parent.parent

    # 构建 Alembic Config，指向项目根的 alembic.ini
    alembic_ini = project_root / "alembic.ini"
    alembic_cfg = Config(str(alembic_ini))

    # 注入同步 DB URL（Alembic 使用 psycopg2 同步驱动）
    sync_url = os.environ.get("TEST_DATABASE_SYNC_URL", "").strip()
    if not sync_url:
        async_url = os.environ.get("TEST_DATABASE_URL", "")
        sync_url = _derive_sync_url(async_url)

    alembic_cfg.set_main_option("sqlalchemy.url", sync_url)

    # 确保迁移脚本路径正确（相对于 alembic.ini 所在目录）
    alembic_cfg.set_main_option("script_location", str(project_root / "migrations"))

    # setup：升级到最新版本
    try:
        command.upgrade(alembic_cfg, "head")
    except Exception as exc:
        pytest.skip(
            f"alembic upgrade head 失败（{exc}）。"
            "请确认迁移文件存在，或先运行 make migrate 创建初始迁移。"
        )

    yield

    # teardown：降级到 base（清理所有表和 Schema）
    try:
        command.downgrade(alembic_cfg, "base")
    except Exception:
        # teardown 失败不应中断测试报告，仅记录警告
        import warnings
        warnings.warn(
            "alembic downgrade base 失败，测试数据库可能未被完整清理。",
            stacklevel=2,
        )


# ─── Function 作用域：真实 DB 会话 ───────────────────────────────────────────────

@pytest.fixture()
async def real_db_session(
    real_db_engine: AsyncEngine,
    alembic_setup: None,  # 确保 Schema 已初始化
) -> AsyncGenerator[AsyncSession, None]:
    """Function 作用域的真实 DB async session fixture（需求 8.1）。

    每个测试函数获得独立的 AsyncSession，测试结束后 TRUNCATE 所有业务表，
    确保测试间数据完全隔离，不依赖事务回滚（因部分测试需要验证 commit 后的持久化）。

    Args:
        real_db_engine: 已验证连通的异步引擎
        alembic_setup: 确保 Schema 已初始化（隐式依赖）

    Yields:
        AsyncSession: 独立的异步数据库会话
    """
    session_factory = async_sessionmaker(
        real_db_engine,
        expire_on_commit=False,
        autoflush=False,
    )

    async with session_factory() as session:
        yield session

    # teardown：TRUNCATE 所有业务表（使用 CASCADE 处理外键约束）
    async with session_factory() as cleanup_session:
        from sqlalchemy import text

        async with cleanup_session.begin():
            for table in _TABLES_TO_TRUNCATE:
                await cleanup_session.execute(
                    text(f"TRUNCATE TABLE {table} RESTART IDENTITY CASCADE")
                )
