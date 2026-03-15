"""带 lifespan 的完整 FastAPI 应用工厂。

create_app_with_lifespan() 创建包含完整生命周期管理的 FastAPI 实例：
  - lifespan 上下文管理器：启动时创建同步 engine 并初始化 sqladmin，关闭时释放资源
  - 挂载 sqladmin 管理后台至 /admin 路径
  - 注册全局异常处理器
  - 挂载所有 API 路由（前缀 /api/v1）

适用于生产环境和 uvicorn 启动的主入口。
集成测试和单元测试仍使用 create_app()（来自 main_router），不带 sqladmin。
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import sqlalchemy
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError

from src.core.exception_handlers import (
    app_error_handler,
    generic_exception_handler,
    validation_exception_handler,
)
from src.core.exceptions import AppError


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """FastAPI lifespan 上下文管理器。

    启动时（yield 前）：
      1. 从配置读取同步数据库连接串（psycopg2 驱动）
      2. 创建同步 SQLAlchemy engine（pool_size=5，供 sqladmin 使用）
      3. 初始化 sqladmin 管理后台并挂载至 app

    关闭时（yield 后）：
      1. 调用 engine.dispose() 释放数据库连接池

    关键约束：
      - 使用 psycopg2 驱动（同步），不复用 Web 层的 asyncpg 引擎
      - sqladmin 挂载必须在 lifespan 内完成，确保路由已注册
    """
    from src.admin import setup_admin
    from src.core.app_settings import get_settings

    settings = get_settings()

    # 创建独立同步 engine（psycopg2 驱动，供 sqladmin 使用）
    sync_engine = sqlalchemy.create_engine(
        settings.database_sync_url,
        pool_size=5,
        max_overflow=10,
    )

    # 初始化 sqladmin 管理后台并挂载至 app
    setup_admin(app, sync_engine)

    yield

    # 应用关闭时释放数据库连接池
    sync_engine.dispose()


def create_app_with_lifespan() -> FastAPI:
    """创建带完整生命周期管理的 FastAPI 应用实例。

    此函数是生产环境主入口，包含：
      - lifespan 上下文管理器（数据库连接池初始化、sqladmin 挂载）
      - 全局异常处理器
      - 所有 API 路由（/api/v1 前缀）

    Returns:
        配置完毕的 FastAPI 实例，可直接交给 uvicorn 启动。
    """
    app = FastAPI(
        title="量化平台后端 API",
        description="strategy_platform_service — 面向数字货币量化交易入门用户的策略科普展示平台",
        version="1.0.0",
        lifespan=_lifespan,
    )

    # 注册全局异常处理器
    app.add_exception_handler(RequestValidationError, validation_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(AppError, app_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, generic_exception_handler)

    # 挂载所有 API 路由
    _register_routers(app)

    return app


def _register_routers(app: FastAPI) -> None:
    """注册所有 API 路由至 /api/v1 前缀。"""
    from src.api.admin_backtests import router as admin_backtests_router
    from src.api.admin_reports import router as admin_reports_router
    from src.api.auth import router as auth_router
    from src.api.backtests import router as backtests_router
    from src.api.health import router as health_router
    from src.api.pair_metrics import router as pair_metrics_router
    from src.api.reports import router as reports_router
    from src.api.signals import router as signals_router
    from src.api.strategies import router as strategies_router

    api_v1_prefix = "/api/v1"

    app.include_router(health_router, prefix=api_v1_prefix)
    app.include_router(auth_router, prefix=api_v1_prefix)
    app.include_router(strategies_router, prefix=api_v1_prefix)
    app.include_router(backtests_router, prefix=api_v1_prefix)
    app.include_router(signals_router, prefix=api_v1_prefix)
    app.include_router(reports_router, prefix=api_v1_prefix)
    app.include_router(admin_backtests_router, prefix=api_v1_prefix)
    app.include_router(admin_reports_router, prefix=api_v1_prefix)
    app.include_router(pair_metrics_router, prefix=api_v1_prefix)
