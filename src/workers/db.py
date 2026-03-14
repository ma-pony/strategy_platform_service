"""Celery Worker 层同步数据库 session 工厂。

Celery Worker 不使用 asyncio，因此需要同步 SQLAlchemy session（psycopg2 驱动）。
与 Web 层的异步 engine 实例分开创建，互不影响。
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.core.app_settings import get_settings

_sync_engine = None
_sync_session_factory = None


def _get_sync_engine():
    """懒加载同步 engine（避免模块加载时连接数据库）。"""
    global _sync_engine
    if _sync_engine is None:
        settings = get_settings()
        _sync_engine = create_engine(
            settings.database_sync_url,
            pool_size=5,
            max_overflow=10,
            echo=settings.debug,
        )
    return _sync_engine


def SyncSessionLocal() -> Session:  # noqa: N802
    """返回同步 SQLAlchemy session context manager。

    用法（Celery 任务中）：
        with SyncSessionLocal() as session:
            ...
    """
    engine = _get_sync_engine()
    factory = sessionmaker(engine, expire_on_commit=False)
    return factory()
