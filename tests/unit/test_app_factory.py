"""FastAPI 应用工厂单元测试（任务 12.1）。

验证：
  - create_app() 返回有效的 FastAPI 实例
  - lifespan 上下文管理器被正确配置
  - 全局异常处理器已注册（RequestValidationError, AppError, Exception）
  - 所有 API 路由已挂载（auth, strategies, backtests, signals, reports）
  - 路由前缀为 /api/v1
"""

import pytest


@pytest.fixture()
def env_setup(monkeypatch: pytest.MonkeyPatch):
    """注入测试环境变量并清除 settings 缓存。"""
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-app-factory-tests-256bits")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")
    monkeypatch.setenv("DATABASE_SYNC_URL", "postgresql+psycopg2://u:p@localhost/db")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")

    from src.core import app_settings

    app_settings.get_settings.cache_clear()
    yield
    app_settings.get_settings.cache_clear()


class TestCreateApp:
    """create_app() 工厂函数测试。"""

    def test_create_app_returns_fastapi_instance(self, env_setup) -> None:
        """create_app() 应返回 FastAPI 实例。"""
        from fastapi import FastAPI

        from src.api.main_router import create_app

        app = create_app()
        assert isinstance(app, FastAPI)

    def test_create_app_has_exception_handlers(self, env_setup) -> None:
        """create_app() 注册全局异常处理器。"""
        from fastapi.exceptions import RequestValidationError

        from src.api.main_router import create_app
        from src.core.exceptions import AppError

        app = create_app()

        # FastAPI 异常处理器存在
        assert RequestValidationError in app.exception_handlers
        assert AppError in app.exception_handlers
        assert Exception in app.exception_handlers

    def test_create_app_has_api_v1_prefix_routes(self, env_setup) -> None:
        """create_app() 挂载的路由应包含 /api/v1 前缀。"""
        from src.api.main_router import create_app

        app = create_app()
        routes = [r.path for r in app.routes]  # type: ignore[attr-defined]

        # 检查至少有一个 /api/v1 路由存在
        api_routes = [r for r in routes if r.startswith("/api/v1")]
        assert len(api_routes) > 0, "未找到 /api/v1 前缀路由"

    def test_create_app_includes_auth_router(self, env_setup) -> None:
        """create_app() 应包含认证路由。"""
        from src.api.main_router import create_app

        app = create_app()
        routes = [r.path for r in app.routes]  # type: ignore[attr-defined]

        auth_routes = [r for r in routes if "/auth/" in r or r.endswith("/auth")]
        assert len(auth_routes) > 0, "未找到认证路由"

    def test_create_app_includes_strategies_router(self, env_setup) -> None:
        """create_app() 应包含策略路由。"""
        from src.api.main_router import create_app

        app = create_app()
        routes = [r.path for r in app.routes]  # type: ignore[attr-defined]

        strategy_routes = [r for r in routes if "strategies" in r]
        assert len(strategy_routes) > 0, "未找到策略路由"

    def test_create_app_includes_backtests_router(self, env_setup) -> None:
        """create_app() 应包含回测路由。"""
        from src.api.main_router import create_app

        app = create_app()
        routes = [r.path for r in app.routes]  # type: ignore[attr-defined]

        backtest_routes = [r for r in routes if "backtests" in r]
        assert len(backtest_routes) > 0, "未找到回测路由"

    def test_create_app_includes_signals_router(self, env_setup) -> None:
        """create_app() 应包含信号路由。"""
        from src.api.main_router import create_app

        app = create_app()
        routes = [r.path for r in app.routes]  # type: ignore[attr-defined]

        signal_routes = [r for r in routes if "signals" in r]
        assert len(signal_routes) > 0, "未找到信号路由"

    def test_create_app_includes_reports_router(self, env_setup) -> None:
        """create_app() 应包含研报路由。"""
        from src.api.main_router import create_app

        app = create_app()
        routes = [r.path for r in app.routes]  # type: ignore[attr-defined]

        report_routes = [r for r in routes if "reports" in r]
        assert len(report_routes) > 0, "未找到研报路由"

    def test_app_title_is_set(self, env_setup) -> None:
        """FastAPI 实例的 title 应已设置。"""
        from src.api.main_router import create_app

        app = create_app()
        assert app.title == "量化平台后端 API"


class TestFastAPIAppEndpoints:
    """通过 HTTP 客户端验证主应用端点可达性。"""

    async def test_unknown_route_returns_404(self, env_setup) -> None:
        """访问未注册路由应返回 404（FastAPI 默认）。"""
        from httpx import ASGITransport, AsyncClient

        from src.api.main_router import create_app

        app = create_app()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            response = await ac.get("/api/v1/nonexistent")
        assert response.status_code == 404

    async def test_validation_error_returns_code_2001(self, env_setup) -> None:
        """Pydantic 422 校验错误被全局处理器拦截，返回 code:2001 信封格式。"""
        from collections.abc import AsyncGenerator
        from unittest.mock import AsyncMock

        from httpx import ASGITransport, AsyncClient

        from src.api.main_router import create_app
        from src.core.deps import get_db

        app = create_app()
        mock_db = AsyncMock()

        async def override_get_db() -> AsyncGenerator:
            yield mock_db

        app.dependency_overrides[get_db] = override_get_db

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            # 缺少必填字段，触发 422
            response = await ac.post(
                "/api/v1/auth/register",
                json={"username": "onlyone"},  # 缺少 password
            )

        assert response.status_code == 422
        body = response.json()
        assert body["code"] == 2001
        assert "message" in body

    async def test_app_error_returns_proper_envelope(self, env_setup) -> None:
        """AppError 被全局处理器拦截，返回统一信封格式。"""
        from collections.abc import AsyncGenerator
        from unittest.mock import AsyncMock, MagicMock

        from httpx import ASGITransport, AsyncClient

        from src.api.main_router import create_app
        from src.core.deps import get_db
        from src.core.exceptions import LoginNotFoundError

        app = create_app()
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        async def override_get_db() -> AsyncGenerator:
            yield mock_db

        app.dependency_overrides[get_db] = override_get_db

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            # 使用不存在的邮箱登录触发 LoginNotFoundError
            response = await ac.post(
                "/api/v1/auth/login",
                json={"email": "ghost@example.com", "password": "wrong"},
            )

        assert response.status_code == 401
        body = response.json()
        assert body["code"] == 1004
        assert "message" in body
        assert body["data"] is None
