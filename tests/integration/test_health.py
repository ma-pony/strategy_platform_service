"""健康检查 API 集成测试。

验证：
  - GET /api/v1/health：返回 200 + 统一信封格式
  - 响应包含 status: healthy
  - 无需认证即可访问
"""

import pytest
from httpx import ASGITransport, AsyncClient

TEST_SECRET = "test-secret-key-for-health-api-tests-256bits-long!!"


@pytest.fixture()
def env_setup(monkeypatch: pytest.MonkeyPatch):
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
    from src.api.main_router import create_app

    return create_app()


@pytest.fixture()
async def client(app):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac


class TestHealthEndpoint:
    """GET /api/v1/health 接口测试。"""

    @pytest.mark.asyncio
    async def test_health_returns_200(self, client: AsyncClient) -> None:
        """健康检查端点返回 HTTP 200。"""
        resp = await client.get("/api/v1/health")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_health_returns_envelope_format(self, client: AsyncClient) -> None:
        """健康检查响应包含统一信封格式（code, message, data）。"""
        resp = await client.get("/api/v1/health")
        body = resp.json()
        assert "code" in body
        assert "message" in body
        assert "data" in body
        assert body["code"] == 0

    @pytest.mark.asyncio
    async def test_health_returns_healthy_status(self, client: AsyncClient) -> None:
        """健康检查响应数据包含 status: healthy。"""
        resp = await client.get("/api/v1/health")
        body = resp.json()
        assert body["data"]["status"] == "healthy"

    @pytest.mark.asyncio
    async def test_health_no_auth_required(self, client: AsyncClient) -> None:
        """健康检查端点无需认证（无 Authorization header 也返回 200）。"""
        resp = await client.get("/api/v1/health")
        assert resp.status_code == 200
        assert resp.json()["code"] == 0
