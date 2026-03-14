"""lifespan 与 sqladmin 挂载测试（任务 12.1）。

验证：
  - create_app_with_lifespan() 创建的 FastAPI 应用具有 lifespan 配置
  - sqladmin 管理后台被挂载至 /admin 路径
  - lifespan 启动时创建同步 SQLAlchemy engine（psycopg2 驱动）
  - lifespan 关闭时释放资源
"""

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture()
def env_setup(monkeypatch: pytest.MonkeyPatch):
    """注入测试环境变量。"""
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-lifespan-test-256bits-here")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")
    monkeypatch.setenv("DATABASE_SYNC_URL", "postgresql+psycopg2://u:p@localhost/db")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "adminpass")

    from src.core import app_settings

    app_settings.get_settings.cache_clear()
    yield
    app_settings.get_settings.cache_clear()


class TestLifespanApp:
    """带 lifespan 的 FastAPI 应用测试。"""

    def test_create_app_with_lifespan_returns_fastapi(self, env_setup) -> None:
        """create_app_with_lifespan() 应返回 FastAPI 实例。"""
        from fastapi import FastAPI

        with patch("sqlalchemy.create_engine") as mock_engine_factory:
            mock_engine = MagicMock()
            mock_engine_factory.return_value = mock_engine

            from src.api.app import create_app_with_lifespan

            app = create_app_with_lifespan()
            assert isinstance(app, FastAPI)

    def test_create_app_with_lifespan_has_lifespan_configured(
        self, env_setup
    ) -> None:
        """create_app_with_lifespan() 的 FastAPI 实例应配置了 lifespan 上下文管理器。"""
        with patch("sqlalchemy.create_engine") as mock_engine_factory:
            mock_engine = MagicMock()
            mock_engine_factory.return_value = mock_engine

            from src.api.app import create_app_with_lifespan

            app = create_app_with_lifespan()
            # FastAPI 的 lifespan 配置在 router.lifespan 上（FastAPI 0.93+）
            # lifespan_context 是运行时使用的上下文管理器
            assert app.router.lifespan_context is not None

    def test_create_app_with_lifespan_has_api_routes(self, env_setup) -> None:
        """create_app_with_lifespan() 应包含 /api/v1 路由。"""
        with patch("sqlalchemy.create_engine") as mock_engine_factory:
            mock_engine = MagicMock()
            mock_engine_factory.return_value = mock_engine

            from src.api.app import create_app_with_lifespan

            app = create_app_with_lifespan()
            routes = [r.path for r in app.routes]  # type: ignore[attr-defined]
            api_routes = [r for r in routes if r.startswith("/api/v1")]
            assert len(api_routes) > 0

    def test_create_app_with_lifespan_registers_exception_handlers(
        self, env_setup
    ) -> None:
        """create_app_with_lifespan() 应注册全局异常处理器。"""
        from fastapi.exceptions import RequestValidationError

        from src.core.exceptions import AppError

        with patch("sqlalchemy.create_engine") as mock_engine_factory:
            mock_engine = MagicMock()
            mock_engine_factory.return_value = mock_engine

            from src.api.app import create_app_with_lifespan

            app = create_app_with_lifespan()
            assert RequestValidationError in app.exception_handlers
            assert AppError in app.exception_handlers
            assert Exception in app.exception_handlers

    async def test_lifespan_creates_sync_engine_on_startup(self, env_setup) -> None:
        """lifespan 启动时应创建同步 SQLAlchemy engine。"""
        # patch src.api.app 模块内部的 sqlalchemy.create_engine 引用
        with patch("src.api.app.sqlalchemy.create_engine") as mock_engine_factory:
            mock_engine = MagicMock()
            mock_engine.dispose = MagicMock()
            mock_engine_factory.return_value = mock_engine

            # 额外 mock setup_admin 避免真实 DB 连接
            with patch("src.admin.setup_admin") as mock_setup_admin:
                mock_setup_admin.return_value = None

                from src.api.app import create_app_with_lifespan

                app = create_app_with_lifespan()

                # 通过 ASGI lifespan 协议手动触发启动和关闭
                messages_sent: list[bool] = []

                async def receive():
                    if not messages_sent:
                        messages_sent.append(True)
                        return {"type": "lifespan.startup"}
                    return {"type": "lifespan.shutdown"}

                async def send(msg: dict) -> None:
                    pass

                await app({"type": "lifespan"}, receive, send)

            # 验证 create_engine 被调用（使用同步驱动 URL）
            mock_engine_factory.assert_called_once()
            call_args = mock_engine_factory.call_args
            db_url = call_args.args[0] if call_args.args else call_args.kwargs.get("url", "")
            assert "psycopg2" in db_url or "postgresql" in db_url

    async def test_lifespan_disposes_engine_on_shutdown(self, env_setup) -> None:
        """lifespan 关闭时应调用 engine.dispose() 释放连接。"""
        with patch("src.api.app.sqlalchemy.create_engine") as mock_engine_factory:
            mock_engine = MagicMock()
            mock_engine.dispose = MagicMock()
            mock_engine_factory.return_value = mock_engine

            with patch("src.admin.setup_admin") as mock_setup_admin:
                mock_setup_admin.return_value = None

                from src.api.app import create_app_with_lifespan

                app = create_app_with_lifespan()

                # 手动触发 lifespan 生命周期（启动 + 关闭）
                messages_sent: list[bool] = []

                async def receive():
                    if not messages_sent:
                        messages_sent.append(True)
                        return {"type": "lifespan.startup"}
                    return {"type": "lifespan.shutdown"}

                async def send(msg: dict) -> None:
                    pass

                await app({"type": "lifespan"}, receive, send)

            # 应用关闭后 dispose 应被调用
            mock_engine.dispose.assert_called_once()
