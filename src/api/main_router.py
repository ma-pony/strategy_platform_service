"""FastAPI 应用工厂函数。

create_app() 创建并配置 FastAPI 实例：
  - 注册全局异常处理器
  - 挂载所有 API 路由，前缀 /api/v1
"""

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError

from src.core.exception_handlers import (
    app_error_handler,
    generic_exception_handler,
    validation_exception_handler,
)
from src.core.exceptions import AppError


def create_app() -> FastAPI:
    """创建并配置 FastAPI 应用实例。

    Returns:
        配置完毕的 FastAPI 实例，可直接交给 uvicorn 启动。
    """
    app = FastAPI(
        title="量化平台后端 API",
        description="strategy_platform_service — 面向数字货币量化交易入门用户的策略科普展示平台",
        version="1.0.0",
    )

    # 注册全局异常处理器
    app.add_exception_handler(RequestValidationError, validation_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(AppError, app_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, generic_exception_handler)

    # 挂载 API 路由
    _register_routers(app)

    return app


def _register_routers(app: FastAPI) -> None:
    """注册所有 API 路由至 /api/v1 前缀。"""
    from src.api.admin_backtests import router as admin_backtests_router
    from src.api.admin_reports import router as admin_reports_router
    from src.api.admin_signals import router as admin_signals_router
    from src.api.auth import router as auth_router
    from src.api.backtests import router as backtests_router
    from src.api.health import router as health_router
    from src.api.pair_metrics import router as pair_metrics_router
    from src.api.reports import router as reports_router
    from src.api.signals import router as signals_router
    from src.api.signals_top import router as signals_top_router
    from src.api.strategies import router as strategies_router

    api_v1_prefix = "/api/v1"

    app.include_router(health_router, prefix=api_v1_prefix)
    app.include_router(auth_router, prefix=api_v1_prefix)
    app.include_router(strategies_router, prefix=api_v1_prefix)
    app.include_router(backtests_router, prefix=api_v1_prefix)
    app.include_router(signals_router, prefix=api_v1_prefix)
    app.include_router(signals_top_router, prefix=api_v1_prefix)
    app.include_router(reports_router, prefix=api_v1_prefix)
    app.include_router(admin_backtests_router, prefix=api_v1_prefix)
    app.include_router(admin_reports_router, prefix=api_v1_prefix)
    app.include_router(admin_signals_router, prefix=api_v1_prefix)
    # 策略对绩效指标端点（prefix="/strategies"，避免与现有策略路由器合并冲突）
    app.include_router(pair_metrics_router, prefix=api_v1_prefix)
