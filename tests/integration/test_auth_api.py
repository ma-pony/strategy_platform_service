"""认证 API 集成测试（任务 8 / email-auth）。

使用 httpx.AsyncClient + ASGITransport 对注册、登录、刷新完整 HTTP 流程进行端到端测试。
外部依赖（数据库）通过依赖覆盖（override）隔离。

需求覆盖：
  - 8.1 注册接口：合法请求 code:0，非法邮箱 code:2001，邮箱重复 code:3010，密码不足 code:2001
  - 8.2 登录接口：合法凭证 code:0，邮箱不存在 code:1004，密码错误 code:1004，账号禁用 code:1005
  - 8.3 Token 刷新接口：有效 refresh token 返回新 access_token，无效/类型错误返回 code:1001
"""

from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock

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
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


# ---------------------------------------------------------------------------
# 任务 8.1：注册接口集成测试
# ---------------------------------------------------------------------------


class TestRegisterEndpoint:
    """POST /api/v1/auth/register 端点测试（任务 8.1）。"""

    async def test_register_success_returns_code_0_and_user_info(self, env_setup) -> None:
        """合法请求返回 code:0，data 中包含 id 和 email，不含密码信息（需求 1.5, 6.2）。"""
        from src.api.main_router import create_app
        from src.core.deps import get_db
        from src.core.enums import MembershipTier
        from src.models.user import User

        app = create_app()
        mock_db = _make_mock_db()
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

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.post(
                "/api/v1/auth/register",
                json={"email": "newuser@example.com", "password": "password123"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        assert data["data"]["email"] == "newuser@example.com"
        assert data["data"]["membership"] == "free"
        # 响应中不含密码字段
        assert "hashed_password" not in data["data"]
        assert "password" not in data["data"]

    async def test_register_success_response_includes_id_and_email(self, env_setup) -> None:
        """注册成功响应中 data 包含整数 id 及 email 字段（需求 1.5）。"""
        from datetime import datetime, timezone

        from src.api.main_router import create_app
        from src.core.deps import get_db
        from src.core.enums import MembershipTier
        from src.models.user import User

        app = create_app()
        mock_db = _make_mock_db()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        def capture_add(user: User) -> None:
            user.id = 42
            user.membership = MembershipTier.FREE
            user.is_active = True
            user.created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)

        mock_db.add.side_effect = capture_add

        async def override_get_db() -> AsyncGenerator:
            yield mock_db

        app.dependency_overrides[get_db] = override_get_db

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.post(
                "/api/v1/auth/register",
                json={"email": "newuser42@example.com", "password": "password123"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        user_data = data["data"]
        assert isinstance(user_data["id"], int)
        assert "email" in user_data
        assert "created_at" in user_data

    async def test_register_invalid_email_returns_code_2001_http_422(self, env_setup) -> None:
        """邮箱格式非法时返回 code:2001，HTTP 422（需求 1.2, 6.3）。"""
        from src.api.main_router import create_app
        from src.core.deps import get_db

        app = create_app()
        mock_db = _make_mock_db()

        async def override_get_db() -> AsyncGenerator:
            yield mock_db

        app.dependency_overrides[get_db] = override_get_db

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.post(
                "/api/v1/auth/register",
                json={"email": "not-an-email", "password": "password123"},
            )

        assert response.status_code == 422
        data = response.json()
        assert data["code"] == 2001

    async def test_register_missing_at_in_email_returns_422_code_2001(self, env_setup) -> None:
        """邮箱缺少 @ 时返回 code:2001，HTTP 422。"""
        from src.api.main_router import create_app
        from src.core.deps import get_db

        app = create_app()
        mock_db = _make_mock_db()

        async def override_get_db() -> AsyncGenerator:
            yield mock_db

        app.dependency_overrides[get_db] = override_get_db

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.post(
                "/api/v1/auth/register",
                json={"email": "invalidemail.com", "password": "password123"},
            )

        assert response.status_code == 422
        data = response.json()
        assert data["code"] == 2001

    async def test_register_duplicate_email_returns_code_3010_http_409(self, env_setup) -> None:
        """邮箱已注册时返回 code:3010，HTTP 409（需求 1.3）。"""
        from src.api.main_router import create_app
        from src.core.deps import get_db
        from src.models.user import User

        app = create_app()
        mock_db = _make_mock_db()
        mock_result = MagicMock()
        existing_user = MagicMock(spec=User)
        existing_user.email = "existing@example.com"
        mock_result.scalar_one_or_none.return_value = existing_user
        mock_db.execute.return_value = mock_result

        async def override_get_db() -> AsyncGenerator:
            yield mock_db

        app.dependency_overrides[get_db] = override_get_db

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.post(
                "/api/v1/auth/register",
                json={"email": "existing@example.com", "password": "password123"},
            )

        assert response.status_code == 409
        data = response.json()
        assert data["code"] == 3010

    async def test_register_password_too_short_returns_code_2001_http_422(self, env_setup) -> None:
        """密码不足 8 位时返回 code:2001，HTTP 422（需求 1.6, 1.7）。"""
        from src.api.main_router import create_app
        from src.core.deps import get_db

        app = create_app()
        mock_db = _make_mock_db()

        async def override_get_db() -> AsyncGenerator:
            yield mock_db

        app.dependency_overrides[get_db] = override_get_db

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.post(
                "/api/v1/auth/register",
                json={"email": "user@example.com", "password": "short"},
            )

        assert response.status_code == 422
        data = response.json()
        assert data["code"] == 2001

    async def test_register_password_exactly_7_chars_returns_422(self, env_setup) -> None:
        """密码恰好 7 字符（不足 8）时返回 HTTP 422 + code:2001。"""
        from src.api.main_router import create_app
        from src.core.deps import get_db

        app = create_app()
        mock_db = _make_mock_db()

        async def override_get_db() -> AsyncGenerator:
            yield mock_db

        app.dependency_overrides[get_db] = override_get_db

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.post(
                "/api/v1/auth/register",
                json={"email": "user@example.com", "password": "only7ch"},
            )

        assert response.status_code == 422
        data = response.json()
        assert data["code"] == 2001

    async def test_register_missing_fields_returns_422_code_2001(self, env_setup) -> None:
        """缺少必填字段时返回 HTTP 422（信封格式 code:2001）。"""
        from src.api.main_router import create_app
        from src.core.deps import get_db

        app = create_app()
        mock_db = _make_mock_db()

        async def override_get_db() -> AsyncGenerator:
            yield mock_db

        app.dependency_overrides[get_db] = override_get_db

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.post(
                "/api/v1/auth/register",
                json={"email": "user@example.com"},  # 缺少 password
            )

        assert response.status_code == 422
        data = response.json()
        assert data["code"] == 2001

    async def test_register_missing_email_returns_422_code_2001(self, env_setup) -> None:
        """缺少 email 字段时返回 HTTP 422 + code:2001。"""
        from src.api.main_router import create_app
        from src.core.deps import get_db

        app = create_app()
        mock_db = _make_mock_db()

        async def override_get_db() -> AsyncGenerator:
            yield mock_db

        app.dependency_overrides[get_db] = override_get_db

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.post(
                "/api/v1/auth/register",
                json={"password": "password123"},  # 缺少 email
            )

        assert response.status_code == 422
        data = response.json()
        assert data["code"] == 2001

    async def test_register_empty_body_returns_422_code_2001(self, env_setup) -> None:
        """空请求体 {} 时返回 HTTP 422 + code:2001。"""
        from src.api.main_router import create_app
        from src.core.deps import get_db

        app = create_app()
        mock_db = _make_mock_db()

        async def override_get_db() -> AsyncGenerator:
            yield mock_db

        app.dependency_overrides[get_db] = override_get_db

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.post("/api/v1/auth/register", json={})

        assert response.status_code == 422
        data = response.json()
        assert data["code"] == 2001

    async def test_register_response_does_not_expose_hashed_password(self, env_setup) -> None:
        """任何注册响应均不包含 hashed_password（需求 6.4）。"""
        from src.api.main_router import create_app
        from src.core.deps import get_db
        from src.core.enums import MembershipTier
        from src.models.user import User

        app = create_app()
        mock_db = _make_mock_db()
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

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.post(
                "/api/v1/auth/register",
                json={"email": "user@example.com", "password": "password123"},
            )

        response_text = response.text
        assert "hashed_password" not in response_text


# ---------------------------------------------------------------------------
# 任务 8.2：登录接口集成测试
# ---------------------------------------------------------------------------


class TestLoginEndpoint:
    """POST /api/v1/auth/login 端点测试（任务 8.2）。"""

    async def test_login_success_returns_code_0_and_tokens(self, env_setup) -> None:
        """合法邮箱和密码登录返回 code:0，data 中包含
        access_token、refresh_token 和 token_type: bearer（需求 2.5, 2.6）。"""
        from src.api.main_router import create_app
        from src.core.deps import get_db
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
        mock_user.email = "testuser@example.com"
        mock_user.hashed_password = hashed_pw
        mock_user.membership = MembershipTier.FREE
        mock_user.is_active = True
        mock_result.scalar_one_or_none.return_value = mock_user
        mock_db.execute.return_value = mock_result

        async def override_get_db() -> AsyncGenerator:
            yield mock_db

        app.dependency_overrides[get_db] = override_get_db

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.post(
                "/api/v1/auth/login",
                json={"email": "testuser@example.com", "password": "correctpassword"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        assert "access_token" in data["data"]
        assert "refresh_token" in data["data"]
        assert data["data"]["token_type"] == "bearer"

    async def test_login_nonexistent_email_returns_code_1004_http_401(self, env_setup) -> None:
        """邮箱不存在时返回 code:1004，HTTP 401（需求 2.2）。"""
        from src.api.main_router import create_app
        from src.core.deps import get_db

        app = create_app()
        mock_db = _make_mock_db()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        async def override_get_db() -> AsyncGenerator:
            yield mock_db

        app.dependency_overrides[get_db] = override_get_db

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.post(
                "/api/v1/auth/login",
                json={"email": "ghost@example.com", "password": "anypassword"},
            )

        assert response.status_code == 401
        data = response.json()
        assert data["code"] == 1004

    async def test_login_wrong_password_returns_code_1004_http_401(self, env_setup) -> None:
        """密码错误时返回 code:1004，HTTP 401（需求 2.3）。"""
        from src.api.main_router import create_app
        from src.core.deps import get_db
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

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.post(
                "/api/v1/auth/login",
                json={"email": "testuser@example.com", "password": "wrongpassword"},
            )

        assert response.status_code == 401
        data = response.json()
        assert data["code"] == 1004

    async def test_login_wrong_password_same_code_as_nonexistent_email(self, env_setup) -> None:
        """密码错误与邮箱不存在返回相同 code:1004（防止用户枚举，需求 2.2, 2.3）。"""
        from src.api.main_router import create_app
        from src.core.deps import get_db
        from src.core.enums import MembershipTier
        from src.core.security import SecurityUtils
        from src.models.user import User

        security = SecurityUtils()
        hashed_pw = security.hash_password("correctpassword")

        app = create_app()
        mock_db = _make_mock_db()

        # 场景 1：邮箱不存在
        mock_result_none = MagicMock()
        mock_result_none.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result_none

        async def override_get_db() -> AsyncGenerator:
            yield mock_db

        app.dependency_overrides[get_db] = override_get_db

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response_nouser = await ac.post(
                "/api/v1/auth/login",
                json={"email": "ghost@example.com", "password": "anypassword"},
            )

        # 场景 2：密码错误
        mock_user = MagicMock(spec=User)
        mock_user.id = 1
        mock_user.hashed_password = hashed_pw
        mock_user.membership = MembershipTier.FREE
        mock_user.is_active = True
        mock_result_user = MagicMock()
        mock_result_user.scalar_one_or_none.return_value = mock_user
        mock_db.execute.return_value = mock_result_user

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response_wrongpw = await ac.post(
                "/api/v1/auth/login",
                json={"email": "testuser@example.com", "password": "wrongpassword"},
            )

        # 两种场景返回相同错误码
        assert response_nouser.json()["code"] == response_wrongpw.json()["code"] == 1004
        assert response_nouser.status_code == response_wrongpw.status_code == 401

    async def test_login_disabled_account_returns_code_1005_http_403(self, env_setup) -> None:
        """账号禁用（is_active=false）时返回 code:1005，HTTP 403（需求 2.4）。"""
        from src.api.main_router import create_app
        from src.core.deps import get_db
        from src.core.enums import MembershipTier
        from src.core.security import SecurityUtils
        from src.models.user import User

        security = SecurityUtils()
        hashed_pw = security.hash_password("password123")

        app = create_app()
        mock_db = _make_mock_db()
        mock_result = MagicMock()
        mock_user = MagicMock(spec=User)
        mock_user.id = 1
        mock_user.hashed_password = hashed_pw
        mock_user.membership = MembershipTier.FREE
        mock_user.is_active = False  # 禁用状态
        mock_result.scalar_one_or_none.return_value = mock_user
        mock_db.execute.return_value = mock_result

        async def override_get_db() -> AsyncGenerator:
            yield mock_db

        app.dependency_overrides[get_db] = override_get_db

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.post(
                "/api/v1/auth/login",
                json={"email": "disabled@example.com", "password": "password123"},
            )

        assert response.status_code == 403
        data = response.json()
        assert data["code"] == 1005

    async def test_login_response_does_not_contain_hashed_password(self, env_setup) -> None:
        """登录失败响应不含 hashed_password 或堆栈信息（需求 6.4）。"""
        from src.api.main_router import create_app
        from src.core.deps import get_db
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

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.post(
                "/api/v1/auth/login",
                json={"email": "testuser@example.com", "password": "wrongpassword"},
            )

        assert response.status_code == 401
        data = response.json()
        assert data["code"] == 1004
        response_data = data.get("data") or {}
        assert "access_token" not in response_data
        assert "refresh_token" not in response_data

    async def test_login_missing_email_returns_422_code_2001(self, env_setup) -> None:
        """缺少 email 字段时返回 HTTP 422 + code:2001。"""
        from src.api.main_router import create_app
        from src.core.deps import get_db

        app = create_app()
        mock_db = _make_mock_db()

        async def override_get_db() -> AsyncGenerator:
            yield mock_db

        app.dependency_overrides[get_db] = override_get_db

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.post(
                "/api/v1/auth/login",
                json={"password": "password123"},  # 缺少 email
            )

        assert response.status_code == 422
        data = response.json()
        assert data["code"] == 2001

    async def test_login_invalid_email_format_returns_422_code_2001(self, env_setup) -> None:
        """邮箱格式非法时返回 HTTP 422 + code:2001。"""
        from src.api.main_router import create_app
        from src.core.deps import get_db

        app = create_app()
        mock_db = _make_mock_db()

        async def override_get_db() -> AsyncGenerator:
            yield mock_db

        app.dependency_overrides[get_db] = override_get_db

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.post(
                "/api/v1/auth/login",
                json={"email": "not-an-email", "password": "password123"},
            )

        assert response.status_code == 422
        data = response.json()
        assert data["code"] == 2001

    async def test_login_missing_password_returns_422_code_2001(self, env_setup) -> None:
        """缺少 password 字段时返回 HTTP 422 + code:2001。"""
        from src.api.main_router import create_app
        from src.core.deps import get_db

        app = create_app()
        mock_db = _make_mock_db()

        async def override_get_db() -> AsyncGenerator:
            yield mock_db

        app.dependency_overrides[get_db] = override_get_db

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.post(
                "/api/v1/auth/login",
                json={"email": "testuser@example.com"},  # 缺少 password
            )

        assert response.status_code == 422
        data = response.json()
        assert data["code"] == 2001

    async def test_login_empty_body_returns_422_code_2001(self, env_setup) -> None:
        """空请求体 {} 时返回 HTTP 422 + code:2001。"""
        from src.api.main_router import create_app
        from src.core.deps import get_db

        app = create_app()
        mock_db = _make_mock_db()

        async def override_get_db() -> AsyncGenerator:
            yield mock_db

        app.dependency_overrides[get_db] = override_get_db

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.post("/api/v1/auth/login", json={})

        assert response.status_code == 422
        data = response.json()
        assert data["code"] == 2001


# ---------------------------------------------------------------------------
# 任务 8.3：Token 刷新接口集成测试
# ---------------------------------------------------------------------------


class TestRefreshEndpoint:
    """POST /api/v1/auth/refresh 端点测试（任务 8.3）。"""

    async def test_refresh_with_valid_token_returns_new_access_token(self, env_setup) -> None:
        """有效 refresh token 返回新 access_token，不重新签发 refresh token（需求 5.4, 5.5）。"""
        from src.api.main_router import create_app
        from src.core.deps import get_db
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

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.post(
                "/api/v1/auth/refresh",
                json={"refresh_token": refresh_token},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        assert "access_token" in data["data"]
        assert data["data"]["token_type"] == "bearer"
        # 响应中不应包含 refresh_token（只返回新 access_token）
        assert "refresh_token" not in data["data"]

    async def test_refresh_with_invalid_token_returns_code_1001_http_401(self, env_setup) -> None:
        """过期或签名无效的 refresh token 返回 code:1001，HTTP 401（需求 5.2）。"""
        from src.api.main_router import create_app
        from src.core.deps import get_db

        app = create_app()
        mock_db = _make_mock_db()

        async def override_get_db() -> AsyncGenerator:
            yield mock_db

        app.dependency_overrides[get_db] = override_get_db

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.post(
                "/api/v1/auth/refresh",
                json={"refresh_token": "invalid.token.here"},
            )

        assert response.status_code == 401
        data = response.json()
        assert data["code"] == 1001

    async def test_refresh_with_access_token_as_refresh_returns_code_1001(self, env_setup) -> None:
        """传入 access token 作为 refresh token 时返回 code:1001，HTTP 401（type 字段校验，需求 5.3）。"""
        from src.api.main_router import create_app
        from src.core.deps import get_db
        from src.core.enums import MembershipTier
        from src.core.security import SecurityUtils

        security = SecurityUtils()
        access_token = security.create_access_token(sub="1", membership=MembershipTier.FREE)

        app = create_app()
        mock_db = _make_mock_db()

        async def override_get_db() -> AsyncGenerator:
            yield mock_db

        app.dependency_overrides[get_db] = override_get_db

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.post(
                "/api/v1/auth/refresh",
                json={"refresh_token": access_token},
            )

        assert response.status_code == 401
        data = response.json()
        assert data["code"] == 1001

    async def test_refresh_missing_body_field_returns_422_code_2001(self, env_setup) -> None:
        """请求体中缺少 refresh_token 字段时返回 HTTP 422 + code:2001。"""
        from src.api.main_router import create_app
        from src.core.deps import get_db

        app = create_app()
        mock_db = _make_mock_db()

        async def override_get_db() -> AsyncGenerator:
            yield mock_db

        app.dependency_overrides[get_db] = override_get_db

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.post("/api/v1/auth/refresh", json={})

        assert response.status_code == 422
        data = response.json()
        assert data["code"] == 2001

    async def test_refresh_nonexistent_user_returns_401_code_1001(self, env_setup) -> None:
        """db.get 返回 None（用户不存在）时，刷新端点返回 HTTP 401 + code:1001。"""
        from src.api.main_router import create_app
        from src.core.deps import get_db
        from src.core.security import SecurityUtils

        security = SecurityUtils()
        refresh_token = security.create_refresh_token(sub="9999")

        app = create_app()
        mock_db = _make_mock_db()
        mock_db.get.return_value = None

        async def override_get_db() -> AsyncGenerator:
            yield mock_db

        app.dependency_overrides[get_db] = override_get_db

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.post(
                "/api/v1/auth/refresh",
                json={"refresh_token": refresh_token},
            )

        assert response.status_code == 401
        data = response.json()
        assert data["code"] == 1001

    async def test_refresh_free_user_new_token_carries_correct_membership(self, env_setup) -> None:
        """Free 用户刷新后新 access_token 的 membership claim 为 free。"""
        from src.api.main_router import create_app
        from src.core.deps import get_db
        from src.core.enums import MembershipTier
        from src.core.security import SecurityUtils
        from src.models.user import User

        security = SecurityUtils()
        refresh_token = security.create_refresh_token(sub="1")

        app = create_app()
        mock_db = _make_mock_db()
        mock_user = MagicMock(spec=User)
        mock_user.id = 1
        mock_user.membership = MembershipTier.FREE
        mock_user.is_active = True
        mock_db.get.return_value = mock_user

        async def override_get_db() -> AsyncGenerator:
            yield mock_db

        app.dependency_overrides[get_db] = override_get_db

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.post(
                "/api/v1/auth/refresh",
                json={"refresh_token": refresh_token},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        new_access_token = data["data"]["access_token"]
        payload = security.decode_token(new_access_token, expected_type="access")
        assert payload["membership"] == MembershipTier.FREE.value


# ---------------------------------------------------------------------------
# 会员权限拦截测试（保留原有测试，不依赖 username/email 字段）
# ---------------------------------------------------------------------------


class TestMembershipPermissionEndpoint:
    """会员等级权限拦截测试（需求 1.6、1.7、1.8）。"""

    async def test_free_user_calling_vip1_endpoint_returns_403_code_1003(self, env_setup) -> None:
        """Free 用户携带合法 token 调用 VIP1 专属接口，验证 HTTP 403 + code:1003（需求 1.6）。"""
        from src.api.main_router import create_app
        from src.core.deps import get_db, require_membership
        from src.core.enums import MembershipTier
        from src.core.security import SecurityUtils
        from src.models.user import User

        security = SecurityUtils()
        free_token = security.create_access_token(sub="1", membership=MembershipTier.FREE)

        mock_free_user = MagicMock(spec=User)
        mock_free_user.id = 1
        mock_free_user.membership = MembershipTier.FREE
        mock_free_user.is_active = True

        app = create_app()
        mock_db = _make_mock_db()
        mock_db.get.return_value = mock_free_user

        async def override_get_db() -> AsyncGenerator:
            yield mock_db

        app.dependency_overrides[get_db] = override_get_db

        from fastapi import Depends

        from src.core.response import ok

        @app.get("/api/v1/test-vip1-only")
        async def _test_vip1_endpoint(
            user: object = Depends(require_membership(MembershipTier.VIP1)),
        ) -> dict:
            return ok(data={"status": "ok"}).model_dump()

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.get(
                "/api/v1/test-vip1-only",
                headers={"Authorization": f"Bearer {free_token}"},
            )

        assert response.status_code == 403
        data = response.json()
        assert data["code"] == 1003

    async def test_refresh_token_exchanges_for_new_access_token_code_0(self, env_setup) -> None:
        """使用 refresh_token 调用刷新端点，验证系统签发新 access_token 且响应 code:0（需求 1.7）。"""
        from src.api.main_router import create_app
        from src.core.deps import get_db
        from src.core.enums import MembershipTier
        from src.core.security import SecurityUtils
        from src.models.user import User

        security = SecurityUtils()
        refresh_token = security.create_refresh_token(sub="2")

        mock_user = MagicMock(spec=User)
        mock_user.id = 2
        mock_user.membership = MembershipTier.VIP1
        mock_user.is_active = True

        app = create_app()
        mock_db = _make_mock_db()
        mock_db.get.return_value = mock_user

        async def override_get_db() -> AsyncGenerator:
            yield mock_db

        app.dependency_overrides[get_db] = override_get_db

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.post(
                "/api/v1/auth/refresh",
                json={"refresh_token": refresh_token},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        assert "access_token" in data["data"]
        assert data["data"]["token_type"] == "bearer"

    async def test_valid_access_token_on_protected_endpoint_returns_200(self, env_setup) -> None:
        """有效 access_token 调用受保护接口时正常返回数据，不触发 401（需求 1.2）。"""
        from fastapi import Depends

        from src.api.main_router import create_app
        from src.core.deps import get_current_user, get_db
        from src.core.enums import MembershipTier
        from src.core.response import ok
        from src.core.security import SecurityUtils
        from src.models.user import User

        security = SecurityUtils()
        access_token = security.create_access_token(sub="10", membership=MembershipTier.FREE)

        mock_user = MagicMock(spec=User)
        mock_user.id = 10
        mock_user.membership = MembershipTier.FREE
        mock_user.is_active = True

        app = create_app()
        mock_db = _make_mock_db()
        mock_db.get.return_value = mock_user

        async def override_get_db() -> AsyncGenerator:
            yield mock_db

        app.dependency_overrides[get_db] = override_get_db

        @app.get("/api/v1/test-valid-token-protected")
        async def _test_valid_token_endpoint(
            user: object = Depends(get_current_user),
        ) -> dict:
            return ok(data={"status": "ok"}).model_dump()

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.get(
                "/api/v1/test-valid-token-protected",
                headers={"Authorization": f"Bearer {access_token}"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0

    async def test_invalid_access_token_on_protected_endpoint_returns_401_code_1001(self, env_setup) -> None:
        """过期或签名无效的 access_token 调用受保护业务接口时返回 HTTP 401 + code:1001（需求 1.3）。"""
        from fastapi import Depends

        from src.api.main_router import create_app
        from src.core.deps import get_current_user, get_db
        from src.core.response import ok

        app = create_app()
        mock_db = _make_mock_db()

        async def override_get_db() -> AsyncGenerator:
            yield mock_db

        app.dependency_overrides[get_db] = override_get_db

        @app.get("/api/v1/test-invalid-token-protected")
        async def _test_invalid_token_endpoint(
            user: object = Depends(get_current_user),
        ) -> dict:
            return ok(data={"status": "ok"}).model_dump()

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.get(
                "/api/v1/test-invalid-token-protected",
                headers={"Authorization": "Bearer this.is.an.invalid.token"},
            )

        assert response.status_code == 401
        data = response.json()
        assert data["code"] == 1001

    async def test_no_auth_header_on_protected_endpoint_returns_code_1001(self, env_setup) -> None:
        """未携带 Authorization 头部调用受保护接口时，系统拒绝并返回 code:1001（需求 1.4）。"""
        from fastapi import Depends

        from src.api.main_router import create_app
        from src.core.deps import get_current_user, get_db
        from src.core.response import ok

        app = create_app()
        mock_db = _make_mock_db()

        async def override_get_db() -> AsyncGenerator:
            yield mock_db

        app.dependency_overrides[get_db] = override_get_db

        @app.get("/api/v1/test-no-auth-protected")
        async def _test_no_auth_endpoint(
            user: object = Depends(get_current_user),
        ) -> dict:
            return ok(data={"status": "ok"}).model_dump()

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.get("/api/v1/test-no-auth-protected")

        assert response.status_code == 401
        data = response.json()
        assert data["code"] == 1001

    async def test_refresh_token_calling_normal_endpoint_returns_401_code_1001(self, env_setup) -> None:
        """使用 type=refresh 的令牌调用普通业务接口，验证 HTTP 401 + code:1001（需求 1.8）。"""
        from fastapi import Depends

        from src.api.main_router import create_app
        from src.core.deps import get_current_user, get_db
        from src.core.response import ok
        from src.core.security import SecurityUtils

        security = SecurityUtils()
        refresh_token = security.create_refresh_token(sub="1")

        app = create_app()
        mock_db = _make_mock_db()

        async def override_get_db() -> AsyncGenerator:
            yield mock_db

        app.dependency_overrides[get_db] = override_get_db

        @app.get("/api/v1/test-auth-required-for-refresh-test")
        async def _test_auth_endpoint(
            user: object = Depends(get_current_user),
        ) -> dict:
            return ok(data={"status": "ok"}).model_dump()

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.get(
                "/api/v1/test-auth-required-for-refresh-test",
                headers={"Authorization": f"Bearer {refresh_token}"},
            )

        assert response.status_code == 401
        data = response.json()
        assert data["code"] == 1001
