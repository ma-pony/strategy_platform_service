"""FastAPI 主入口 app 实例测试（任务 12.1）。

验证：
  - src.main 模块暴露 app 变量（uvicorn src.main:app）
  - app 是 FastAPI 实例
  - app 包含正确的路由和异常处理器
"""

import pytest


@pytest.fixture()
def env_setup(monkeypatch: pytest.MonkeyPatch):
    """注入测试环境变量。"""
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-main-fastapi-256bits-xx")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")
    monkeypatch.setenv("DATABASE_SYNC_URL", "postgresql+psycopg2://u:p@localhost/db")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")

    from src.core import app_settings

    app_settings.get_settings.cache_clear()
    yield
    app_settings.get_settings.cache_clear()


class TestMainFastAPIApp:
    """src.main 模块的 FastAPI app 实例测试。"""

    def test_main_module_exposes_app_variable(self, env_setup) -> None:
        """src.main 应暴露 app 变量，供 uvicorn 使用。"""
        from unittest.mock import MagicMock, patch

        # mock sqlalchemy.create_engine 避免真实数据库连接
        with patch("sqlalchemy.create_engine") as mock_engine:
            mock_engine.return_value = MagicMock()

            import src.main as main_module

            assert hasattr(main_module, "app"), "src.main 未暴露 'app' 变量"

    def test_main_app_is_fastapi_instance(self, env_setup) -> None:
        """src.main.app 应是 FastAPI 实例。"""
        from unittest.mock import MagicMock, patch

        from fastapi import FastAPI

        with patch("sqlalchemy.create_engine") as mock_engine:
            mock_engine.return_value = MagicMock()

            import src.main as main_module

            # 重新加载确保 env 变量生效
            assert isinstance(main_module.app, FastAPI)

    def test_main_app_has_api_routes(self, env_setup) -> None:
        """src.main.app 应包含 /api/v1 路由。"""
        from unittest.mock import MagicMock, patch

        with patch("sqlalchemy.create_engine") as mock_engine:
            mock_engine.return_value = MagicMock()

            import src.main as main_module

            routes = [r.path for r in main_module.app.routes]  # type: ignore[attr-defined]
            api_routes = [r for r in routes if r.startswith("/api/v1")]
            assert len(api_routes) > 0, "src.main.app 未包含 /api/v1 路由"
