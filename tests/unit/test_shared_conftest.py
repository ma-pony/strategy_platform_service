"""共享测试基础设施单元测试（任务 1 / 需求 8.2, 8.3, 8.4）。

验证 tests/conftest.py 中新增的全局 fixtures 行为：
  - env_setup：注入测试环境变量并清除 settings 缓存
  - app：创建隔离的 FastAPI 实例
  - async_client：ASGITransport 绑定的 AsyncClient
  - token_factory：按 MembershipTier 签发有效 JWT
  - mock_db：预配置的 AsyncMock 数据库 session
"""

from unittest.mock import AsyncMock

from fastapi import FastAPI
from httpx import AsyncClient


class TestEnvSetupFixture:
    """验证 env_setup fixture 正确注入环境变量。"""

    def test_env_setup_injects_secret_key(self, env_setup) -> None:
        """env_setup 注入后 get_settings().secret_key 为测试值。"""
        from src.core.app_settings import get_settings

        settings = get_settings()
        assert settings.secret_key == "test-secret-key-for-shared-conftest-256bits!!"

    def test_env_setup_injects_database_url(self, env_setup) -> None:
        """env_setup 注入后 get_settings().database_url 为测试值。"""
        from src.core.app_settings import get_settings

        settings = get_settings()
        assert "asyncpg" in settings.database_url

    def test_env_setup_injects_redis_url(self, env_setup) -> None:
        """env_setup 注入后 get_settings().redis_url 为测试值。"""
        from src.core.app_settings import get_settings

        settings = get_settings()
        assert "redis://" in settings.redis_url


class TestAppFixture:
    """验证 app fixture 返回隔离的 FastAPI 实例。"""

    def test_app_is_fastapi_instance(self, app) -> None:
        """app fixture 返回 FastAPI 实例。"""
        assert isinstance(app, FastAPI)

    def test_app_fixture_depends_on_env_setup(self, app, env_setup) -> None:
        """app fixture 可与 env_setup 一起使用。"""
        assert app is not None

    def test_app_has_routes(self, app) -> None:
        """app 包含已注册的路由（至少有 /api/v1/auth/ 路由）。"""
        route_paths = [route.path for route in app.routes]  # type: ignore[attr-defined]
        assert any("/api/v1" in p for p in route_paths)


class TestAsyncClientFixture:
    """验证 async_client fixture 返回可用的 AsyncClient。"""

    async def test_async_client_is_httpx_async_client(self, async_client) -> None:
        """async_client fixture 返回 httpx.AsyncClient 实例。"""
        assert isinstance(async_client, AsyncClient)

    async def test_async_client_can_access_app(self, async_client) -> None:
        """async_client 可发起 HTTP 请求（health check 或 404）。"""
        response = await async_client.get("/api/v1/health-or-nonexistent")
        # 任何 HTTP 响应均可，关键是无连接错误
        assert response.status_code in (200, 404, 422)


class TestTokenFactoryFixture:
    """验证 token_factory fixture 按会员等级签发有效 JWT。"""

    def test_token_factory_returns_callable(self, token_factory) -> None:
        """token_factory 返回可调用对象。"""
        assert callable(token_factory)

    def test_token_factory_free_tier_returns_string(self, token_factory, env_setup) -> None:
        """token_factory 为 FREE 等级返回字符串 token。"""
        from src.core.enums import MembershipTier

        token = token_factory(MembershipTier.FREE)
        assert isinstance(token, str)
        assert len(token) > 0

    def test_token_factory_vip1_tier_returns_string(self, token_factory, env_setup) -> None:
        """token_factory 为 VIP1 等级返回字符串 token。"""
        from src.core.enums import MembershipTier

        token = token_factory(MembershipTier.VIP1)
        assert isinstance(token, str)
        assert len(token) > 0

    def test_token_factory_vip2_tier_returns_string(self, token_factory, env_setup) -> None:
        """token_factory 为 VIP2 等级返回字符串 token。"""
        from src.core.enums import MembershipTier

        token = token_factory(MembershipTier.VIP2)
        assert isinstance(token, str)
        assert len(token) > 0

    def test_token_factory_produces_valid_jwt(self, token_factory, env_setup) -> None:
        """token_factory 生成的 token 可被 SecurityUtils 解码。"""
        from src.core.enums import MembershipTier
        from src.core.security import SecurityUtils

        token = token_factory(MembershipTier.FREE)
        security = SecurityUtils()
        payload = security.decode_token(token, expected_type="access")
        assert payload["membership"] == "free"
        assert payload["type"] == "access"

    def test_token_factory_free_user_has_fixed_user_id(self, token_factory, env_setup) -> None:
        """token_factory FREE 等级的 sub 为固定用户 ID '1'。"""
        from src.core.enums import MembershipTier
        from src.core.security import SecurityUtils

        token = token_factory(MembershipTier.FREE)
        security = SecurityUtils()
        payload = security.decode_token(token, expected_type="access")
        assert payload["sub"] == "1"

    def test_token_factory_vip1_user_has_fixed_user_id(self, token_factory, env_setup) -> None:
        """token_factory VIP1 等级的 sub 为固定用户 ID '2'。"""
        from src.core.enums import MembershipTier
        from src.core.security import SecurityUtils

        token = token_factory(MembershipTier.VIP1)
        security = SecurityUtils()
        payload = security.decode_token(token, expected_type="access")
        assert payload["sub"] == "2"

    def test_token_factory_vip2_user_has_fixed_user_id(self, token_factory, env_setup) -> None:
        """token_factory VIP2 等级的 sub 为固定用户 ID '3'。"""
        from src.core.enums import MembershipTier
        from src.core.security import SecurityUtils

        token = token_factory(MembershipTier.VIP2)
        security = SecurityUtils()
        payload = security.decode_token(token, expected_type="access")
        assert payload["sub"] == "3"


class TestMockDbFixture:
    """验证 mock_db fixture 返回预配置的 AsyncMock session。"""

    def test_mock_db_is_async_mock(self, mock_db) -> None:
        """mock_db fixture 返回 AsyncMock 实例。"""
        assert isinstance(mock_db, AsyncMock)

    def test_mock_db_has_commit_async(self, mock_db) -> None:
        """mock_db.commit 是 AsyncMock（可 await）。"""
        assert isinstance(mock_db.commit, AsyncMock)

    def test_mock_db_has_refresh_async(self, mock_db) -> None:
        """mock_db.refresh 是 AsyncMock（可 await）。"""
        assert isinstance(mock_db.refresh, AsyncMock)

    async def test_mock_db_commit_is_awaitable(self, mock_db) -> None:
        """mock_db.commit() 可以被 await。"""
        await mock_db.commit()  # 不应抛出异常

    async def test_mock_db_refresh_is_awaitable(self, mock_db) -> None:
        """mock_db.refresh() 可以被 await。"""
        await mock_db.refresh(object())  # 不应抛出异常
