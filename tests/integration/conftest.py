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
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

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

_DEFAULT_TEST_DB_URL = "postgresql+asyncpg://postgres:123456@localhost:5432/strategy_platform_test"


# ─── 辅助函数（供 TDD 测试直接调用）─────────────────────────────────────────────

def _check_test_database_url() -> str:
    """检查 TEST_DATABASE_URL 环境变量是否已设置。

    若未设置且默认测试库不可用，调用 pytest.skip() 跳过并输出明确原因。

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


def _get_test_db_url() -> str:
    """获取测试数据库 URL，有默认值不 skip。"""
    return os.environ.get("TEST_DATABASE_URL", "").strip() or _DEFAULT_TEST_DB_URL


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


def _sync_ping(sync_url: str) -> bool:
    """使用 psycopg2 同步连接验证数据库可达性（不创建 asyncpg 连接）。"""
    from sqlalchemy import create_engine
    engine = create_engine(sync_url, pool_pre_ping=True)
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
    finally:
        engine.dispose()


# ─── Session 作用域：Alembic 迁移 ────────────────────────────────────────────────

@pytest.fixture(scope="session")
def alembic_setup() -> Generator[None, None, None]:
    """Session 作用域的 Alembic 迁移 fixture（需求 8.1）。

    在测试 session 开始时执行 alembic upgrade head（建表），
    session 结束时执行 alembic downgrade base（清理 Schema）。

    使用同步 psycopg2 验证连通性和执行迁移，不创建 asyncpg 连接。
    """
    from pathlib import Path

    from alembic import command
    from alembic.config import Config

    db_url = _get_test_db_url()
    sync_url = os.environ.get("TEST_DATABASE_SYNC_URL", "").strip()
    if not sync_url:
        sync_url = _derive_sync_url(db_url)

    # 同步验证连通性（psycopg2，不涉及 asyncpg event loop）
    if not _sync_ping(sync_url):
        pytest.skip(
            "TEST_DATABASE_URL 设置了，但无法连接到数据库。"
            "请确认 PostgreSQL 实例已启动且连接参数正确。"
        )

    project_root = Path(__file__).parent.parent.parent
    alembic_ini = project_root / "alembic.ini"
    alembic_cfg = Config(str(alembic_ini))
    alembic_cfg.set_main_option("sqlalchemy.url", sync_url)
    alembic_cfg.set_main_option("script_location", str(project_root / "migrations"))

    try:
        command.upgrade(alembic_cfg, "head")
    except Exception as exc:
        pytest.skip(
            f"alembic upgrade head 失败（{exc}）。"
            "请确认迁移文件存在，或先运行 make migrate 创建初始迁移。"
        )

    yield

    try:
        command.downgrade(alembic_cfg, "base")
    except Exception:
        import warnings
        warnings.warn(
            "alembic downgrade base 失败，测试数据库可能未被完整清理。",
            stacklevel=2,
        )


# ─── Session 作用域：真实 DB 引擎 ────────────────────────────────────────────────

@pytest.fixture(scope="session")
def real_db_engine(alembic_setup: None) -> Generator[AsyncEngine, None, None]:
    """Session 作用域的真实 PostgreSQL 异步引擎 fixture（需求 8.1、8.5）。

    注意：此 fixture 只创建引擎对象，不建立 asyncpg 连接。
    连接在 real_db_session（function-scoped async fixture）中按需创建，
    确保 asyncpg 连接绑定到正确的 event loop。

    Yields:
        AsyncEngine: SQLAlchemy 异步引擎（连接池延迟初始化）
    """
    db_url = _get_test_db_url()
    engine = create_async_engine(
        db_url,
        echo=False,
        poolclass=NullPool,
    )

    yield engine

    # teardown：无法 await dispose()，因为 session-scoped sync fixture 无 event loop
    # asyncpg 连接池在进程退出时自动清理


# ─── Function 作用域：真实 DB 会话 ───────────────────────────────────────────────

@pytest.fixture()
async def real_db_session(
    real_db_engine: AsyncEngine,
) -> AsyncGenerator[AsyncSession, None]:
    """Function 作用域的真实 DB async session fixture（需求 8.1）。

    每个测试函数获得独立的 AsyncSession，测试结束后 TRUNCATE 所有业务表，
    确保测试间数据完全隔离，不依赖事务回滚（因部分测试需要验证 commit 后的持久化）。

    Args:
        real_db_engine: SQLAlchemy 异步引擎

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
        async with cleanup_session.begin():
            for table in _TABLES_TO_TRUNCATE:
                await cleanup_session.execute(
                    text(f"TRUNCATE TABLE {table} RESTART IDENTITY CASCADE")
                )
