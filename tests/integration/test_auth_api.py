"""认证 API 集成测试（任务 3.2 / 13.5）。

使用 httpx.AsyncClient + ASGITransport 对注册、登录、刷新完整 HTTP 流程进行端到端测试。
外部依赖（数据库）通过依赖覆盖（override）隔离。
"""

from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

# 测试用固定密钥
TEST_SECRET = "test-secret-key-for-unit-tests-only-256bits"


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


def _make_mock_db() -> AsyncMock:
    """创建一个通用 mock AsyncSession。"""
    db = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db


@pytest.fixture()
def app(env_setup):
    """创建测试用 FastAPI 应用实例，覆盖 get_db 依赖。"""
    from src.api.main_router import create_app

    application = create_app()
    return application


@pytest.fixture()
async def client(app) -> AsyncGenerator[AsyncClient, None]:
    """提供绑定测试应用的异步 HTTP 客户端。"""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac


class TestRegisterEndpoint:
    """POST /api/v1/auth/register 端点测试。"""

    async def test_register_success_returns_code_0_and_user_info(
        self, client: AsyncClient, env_setup
    ) -> None:
        """成功注册返回 code:0 及用户基本信息。"""
        from src.core.deps import get_db
        from src.api.main_router import create_app
        from src.core.enums import MembershipTier
        from src.models.user import User

        app = create_app()

        # mock 数据库 session
        mock_db = _make_mock_db()
        # 查询用户名不存在
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        def capture_add(user: User) -> None:
            user.id = 1
            user.membership = MembershipTier.FREE
            user.is_active = True
            user.created_at = None  # type: ignore[assignment]

        mock_db.add.side_effect = capture_add

        async def override_get_db() -> AsyncGenerator:
            yield mock_db

        app.dependency_overrides[get_db] = override_get_db

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            response = await ac.post(
                "/api/v1/auth/register",
                json={"username": "newuser", "password": "password123"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        assert data["data"]["username"] == "newuser"
        assert data["data"]["membership"] == "free"

    async def test_register_duplicate_username_returns_code_2001(
        self, client: AsyncClient, env_setup
    ) -> None:
        """用户名重复时返回 code:2001 HTTP 400。"""
        from src.core.deps import get_db
        from src.api.main_router import create_app
        from src.models.user import User

        app = create_app()

        mock_db = _make_mock_db()
        # 模拟用户名已存在
        mock_result = MagicMock()
        existing_user = MagicMock(spec=User)
        existing_user.username = "existinguser"
        mock_result.scalar_one_or_none.return_value = existing_user
        mock_db.execute.return_value = mock_result

        async def override_get_db() -> AsyncGenerator:
            yield mock_db

        app.dependency_overrides[get_db] = override_get_db

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            response = await ac.post(
                "/api/v1/auth/register",
                json={"username": "existinguser", "password": "password123"},
            )

        assert response.status_code == 400
        data = response.json()
        assert data["code"] == 2001

    async def test_register_missing_fields_returns_422(
        self, env_setup
    ) -> None:
        """缺少必填字段时返回 HTTP 422（信封格式 code:2001）。"""
        from src.api.main_router import create_app
        from src.core.deps import get_db

        app = create_app()

        # 覆盖 get_db 避免尝试真实数据库连接
        mock_db = _make_mock_db()

        async def override_get_db() -> AsyncGenerator:
            yield mock_db

        app.dependency_overrides[get_db] = override_get_db

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            response = await ac.post(
                "/api/v1/auth/register",
                json={"username": "onlyusername"},  # 缺少 password
            )

        assert response.status_code == 422
        data = response.json()
        assert data["code"] == 2001


class TestLoginEndpoint:
    """POST /api/v1/auth/login 端点测试。"""

    async def test_login_success_returns_code_0_and_tokens(
        self, env_setup
    ) -> None:
        """凭证正确时返回 code:0 及 access_token + refresh_token。"""
        from src.core.deps import get_db
        from src.api.main_router import create_app
        from src.core.enums import MembershipTier
        from src.core.security import SecurityUtils
        from src.models.user import User

        security = SecurityUtils()
        hashed_pw = security.hash_password("correctpassword")

        app = create_app()
        mock_db = _make_mock_db()
        mock_result = MagicMock()
        mock_user = MagicMock(spec=User)
        mock_user.id = 1
        mock_user.username = "testuser"
        mock_user.hashed_password = hashed_pw
        mock_user.membership = MembershipTier.FREE
        mock_user.is_active = True
        mock_result.scalar_one_or_none.return_value = mock_user
        mock_db.execute.return_value = mock_result

        async def override_get_db() -> AsyncGenerator:
            yield mock_db

        app.dependency_overrides[get_db] = override_get_db

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            response = await ac.post(
                "/api/v1/auth/login",
                json={"username": "testuser", "password": "correctpassword"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        assert "access_token" in data["data"]
        assert "refresh_token" in data["data"]
        assert data["data"]["token_type"] == "bearer"

    async def test_login_wrong_password_returns_code_1001(
        self, env_setup
    ) -> None:
        """密码错误时返回 code:1001 HTTP 401。"""
        from src.core.deps import get_db
        from src.api.main_router import create_app
        from src.core.enums import MembershipTier
        from src.core.security import SecurityUtils
        from src.models.user import User

        security = SecurityUtils()
        hashed_pw = security.hash_password("correctpassword")

        app = create_app()
        mock_db = _make_mock_db()
        mock_result = MagicMock()
        mock_user = MagicMock(spec=User)
        mock_user.id = 1
        mock_user.hashed_password = hashed_pw
        mock_user.membership = MembershipTier.FREE
        mock_user.is_active = True
        mock_result.scalar_one_or_none.return_value = mock_user
        mock_db.execute.return_value = mock_result

        async def override_get_db() -> AsyncGenerator:
            yield mock_db

        app.dependency_overrides[get_db] = override_get_db

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            response = await ac.post(
                "/api/v1/auth/login",
                json={"username": "testuser", "password": "wrongpassword"},
            )

        assert response.status_code == 401
        data = response.json()
        assert data["code"] == 1001

    async def test_login_nonexistent_user_returns_code_1001(
        self, env_setup
    ) -> None:
        """用户不存在时返回 code:1001 HTTP 401。"""
        from src.core.deps import get_db
        from src.api.main_router import create_app

        app = create_app()
        mock_db = _make_mock_db()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        async def override_get_db() -> AsyncGenerator:
            yield mock_db

        app.dependency_overrides[get_db] = override_get_db

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            response = await ac.post(
                "/api/v1/auth/login",
                json={"username": "ghost", "password": "password"},
            )

        assert response.status_code == 401
        data = response.json()
        assert data["code"] == 1001


class TestRefreshEndpoint:
    """POST /api/v1/auth/refresh 端点测试。"""

    async def test_refresh_with_valid_token_returns_new_access_token(
        self, env_setup
    ) -> None:
        """有效 refresh_token 时返回 code:0 及新 access_token。"""
        from src.core.deps import get_db
        from src.api.main_router import create_app
        from src.core.enums import MembershipTier
        from src.core.security import SecurityUtils
        from src.models.user import User

        security = SecurityUtils()
        refresh_token = security.create_refresh_token(sub="5")

        app = create_app()
        mock_db = _make_mock_db()
        mock_user = MagicMock(spec=User)
        mock_user.id = 5
        mock_user.membership = MembershipTier.VIP1
        mock_user.is_active = True
        mock_db.get.return_value = mock_user

        async def override_get_db() -> AsyncGenerator:
            yield mock_db

        app.dependency_overrides[get_db] = override_get_db

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            response = await ac.post(
                "/api/v1/auth/refresh",
                json={"refresh_token": refresh_token},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        assert "access_token" in data["data"]
        assert data["data"]["token_type"] == "bearer"

    async def test_refresh_with_invalid_token_returns_code_1001(
        self, env_setup
    ) -> None:
        """无效/过期 refresh_token 时返回 code:1001 HTTP 401。"""
        from src.api.main_router import create_app
        from src.core.deps import get_db

        app = create_app()
        mock_db = _make_mock_db()

        async def override_get_db() -> AsyncGenerator:
            yield mock_db

        app.dependency_overrides[get_db] = override_get_db

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            response = await ac.post(
                "/api/v1/auth/refresh",
                json={"refresh_token": "invalid.token.here"},
            )

        assert response.status_code == 401
        data = response.json()
        assert data["code"] == 1001

    async def test_refresh_with_access_token_returns_code_1001(
        self, env_setup
    ) -> None:
        """传入 access_token（type 错误）时返回 code:1001 HTTP 401。"""
        from src.api.main_router import create_app
        from src.core.deps import get_db
        from src.core.enums import MembershipTier
        from src.core.security import SecurityUtils

        security = SecurityUtils()
        access_token = security.create_access_token(
            sub="1", membership=MembershipTier.FREE
        )

        app = create_app()
        mock_db = _make_mock_db()

        async def override_get_db() -> AsyncGenerator:
            yield mock_db

        app.dependency_overrides[get_db] = override_get_db

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            response = await ac.post(
                "/api/v1/auth/refresh",
                json={"refresh_token": access_token},
            )

        assert response.status_code == 401
        data = response.json()
        assert data["code"] == 1001
