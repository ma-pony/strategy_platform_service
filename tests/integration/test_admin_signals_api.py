"""任务 9.4 集成测试：管理员信号接口（POST /api/v1/admin/signals/refresh）。

验证：
  - 非管理员请求返回 1002/403
  - 管理员请求时任务成功入队并返回 task_id

涵盖需求：5.5
"""

from collections.abc import AsyncGenerator
from unittest.mock import MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

TEST_SECRET = "test-secret-key-for-admin-signals-api-tests-256bits-long"  # pragma: allowlist secret


@pytest.fixture()
def env_setup(monkeypatch: pytest.MonkeyPatch):
    """注入测试环境变量并清除 settings 缓存。"""
    monkeypatch.setenv("SECRET_KEY", TEST_SECRET)
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")
    monkeypatch.setenv("DATABASE_SYNC_URL", "postgresql+psycopg2://u:p@localhost/db")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")

    from src.core import app_settings

    app_settings.get_settings.cache_clear()
    yield
    app_settings.get_settings.cache_clear()


@pytest.fixture()
def app(env_setup):
    """创建测试用 FastAPI 应用实例。"""
    from src.api.main_router import create_app

    application = create_app()
    return application


@pytest.fixture()
async def client(app) -> AsyncGenerator[AsyncClient, None]:
    """提供绑定测试应用的异步 HTTP 客户端。"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


class TestAdminSignalsRefresh:
    """POST /api/v1/admin/signals/refresh 端点测试（需求 5.5）。"""

    @pytest.mark.asyncio
    async def test_non_admin_returns_403(self, app, client: AsyncClient) -> None:
        """非管理员用户请求返回 1002/403（需求 5.5）。"""
        from src.core.deps import require_admin
        from src.core.exceptions import PermissionError as AppPermissionError

        async def _fake_require_admin():
            raise AppPermissionError("需要管理员权限")

        app.dependency_overrides[require_admin] = _fake_require_admin
        try:
            response = await client.post("/api/v1/admin/signals/refresh")
        finally:
            app.dependency_overrides.pop(require_admin, None)

        assert response.status_code == 403
        data = response.json()
        assert data["code"] == 1002

    @pytest.mark.asyncio
    async def test_admin_triggers_task_and_returns_task_id(
        self,
        app,
        client: AsyncClient,
    ) -> None:
        """管理员请求时任务入队并返回 task_id（需求 5.5）。"""
        from src.core.deps import require_admin

        mock_admin_user = MagicMock()
        mock_admin_user.is_admin = True

        async def _fake_require_admin():
            return mock_admin_user

        app.dependency_overrides[require_admin] = _fake_require_admin

        mock_async_result = MagicMock()
        mock_async_result.id = "mock-task-id-12345"

        try:
            with patch(
                "src.workers.tasks.signal_coord_task.generate_all_signals_task.delay",
                return_value=mock_async_result,
            ):
                response = await client.post("/api/v1/admin/signals/refresh")
        finally:
            app.dependency_overrides.pop(require_admin, None)

        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        assert data["data"]["task_id"] == "mock-task-id-12345"
        assert "message" in data["data"]
