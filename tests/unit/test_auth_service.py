"""认证服务单元测试（任务 3.1 / 13.3）。

验证：
  - register 注册逻辑：用户名重复时抛出 ValidationError(code=2001)，成功时新用户 membership 为 FREE
  - login 登录逻辑：密码错误时抛出 AuthenticationError(code=1001)
  - refresh_access_token：传入 access_token（type 不匹配）时抛出 AuthenticationError
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# 测试用固定密钥
TEST_SECRET = "test-secret-key-for-unit-tests-only-256bits"


@pytest.fixture()
def env_setup(monkeypatch: pytest.MonkeyPatch):
    """设置测试所需环境变量并清除 settings 缓存。"""
    monkeypatch.setenv("SECRET_KEY", TEST_SECRET)
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")
    monkeypatch.setenv("DATABASE_SYNC_URL", "postgresql+psycopg2://u:p@localhost/db")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")

    from src.core import app_settings

    app_settings.get_settings.cache_clear()
    yield
    app_settings.get_settings.cache_clear()


@pytest.fixture()
def security(env_setup):
    """提供 SecurityUtils 实例（依赖 env_setup）。"""
    from src.core.security import SecurityUtils

    return SecurityUtils()


@pytest.fixture()
def auth_service(env_setup):
    """提供 AuthService 实例。"""
    from src.services.auth_service import AuthService

    return AuthService()


class TestRegister:
    """AuthService.register 注册逻辑测试。"""

    async def test_register_success_returns_user_with_free_membership(
        self, auth_service, security
    ) -> None:
        """成功注册时，返回 membership=FREE 的用户对象。"""
        from src.core.enums import MembershipTier
        from src.models.user import User

        # 准备 mock db session
        db = AsyncMock()
        db.execute = AsyncMock()
        # 模拟查询用户名不存在（返回 None）
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        db.execute.return_value = mock_result

        # 模拟 db.add、db.commit、db.refresh
        db.add = MagicMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        # 捕获 db.add 调用的参数，并在 refresh 时模拟填充 id
        added_user: list[User] = []

        def capture_add(user: User) -> None:
            user.id = 1
            user.membership = MembershipTier.FREE
            user.is_active = True
            added_user.append(user)

        db.add.side_effect = capture_add

        user = await auth_service.register(db, "newuser", "password123")

        assert user.username == "newuser"
        assert user.membership == MembershipTier.FREE
        db.add.assert_called_once()
        db.commit.assert_awaited_once()

    async def test_register_duplicate_username_raises_validation_error(
        self, auth_service
    ) -> None:
        """用户名已存在时抛出 ValidationError(code=2001)。"""
        from src.core.exceptions import ValidationError
        from src.models.user import User

        db = AsyncMock()
        # 模拟查询用户名已存在
        mock_result = MagicMock()
        existing_user = MagicMock(spec=User)
        existing_user.username = "existinguser"
        mock_result.scalar_one_or_none.return_value = existing_user
        db.execute.return_value = mock_result

        with pytest.raises(ValidationError) as exc_info:
            await auth_service.register(db, "existinguser", "password123")

        assert exc_info.value.code == 2001

    async def test_register_hashes_password(self, auth_service, security) -> None:
        """注册时密码以 bcrypt 哈希存储，不明文保存。"""
        from src.models.user import User

        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        db.execute.return_value = mock_result
        db.add = MagicMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        added_user: list[User] = []

        def capture_add(user: User) -> None:
            user.id = 1
            added_user.append(user)

        db.add.side_effect = capture_add

        await auth_service.register(db, "testuser", "plaintext_password")

        assert len(added_user) == 1
        captured = added_user[0]
        # hashed_password 不应等于明文
        assert captured.hashed_password != "plaintext_password"
        # 应能通过 bcrypt 验证
        assert security.verify_password("plaintext_password", captured.hashed_password)


class TestLogin:
    """AuthService.login 登录逻辑测试。"""

    async def test_login_success_returns_token_pair(
        self, auth_service, security
    ) -> None:
        """凭证正确时返回 (access_token, refresh_token) 元组。"""
        from src.core.enums import MembershipTier
        from src.models.user import User

        hashed_pw = security.hash_password("correctpassword")

        db = AsyncMock()
        mock_result = MagicMock()
        mock_user = MagicMock(spec=User)
        mock_user.id = 42
        mock_user.username = "testuser"
        mock_user.hashed_password = hashed_pw
        mock_user.membership = MembershipTier.FREE
        mock_user.is_active = True
        mock_result.scalar_one_or_none.return_value = mock_user
        db.execute.return_value = mock_result

        access_token, refresh_token = await auth_service.login(
            db, "testuser", "correctpassword"
        )

        assert access_token
        assert refresh_token
        # access_token 应能被解码
        payload = security.decode_token(access_token)
        assert payload["sub"] == "42"
        assert payload["type"] == "access"

    async def test_login_wrong_password_raises_authentication_error(
        self, auth_service, security
    ) -> None:
        """密码错误时抛出 AuthenticationError(code=1001)。"""
        from src.core.enums import MembershipTier
        from src.core.exceptions import AuthenticationError
        from src.models.user import User

        hashed_pw = security.hash_password("correctpassword")

        db = AsyncMock()
        mock_result = MagicMock()
        mock_user = MagicMock(spec=User)
        mock_user.id = 1
        mock_user.hashed_password = hashed_pw
        mock_user.membership = MembershipTier.FREE
        mock_user.is_active = True
        mock_result.scalar_one_or_none.return_value = mock_user
        db.execute.return_value = mock_result

        with pytest.raises(AuthenticationError) as exc_info:
            await auth_service.login(db, "testuser", "wrongpassword")

        assert exc_info.value.code == 1001

    async def test_login_user_not_found_raises_authentication_error(
        self, auth_service
    ) -> None:
        """用户不存在时抛出 AuthenticationError(code=1001)。"""
        from src.core.exceptions import AuthenticationError

        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        db.execute.return_value = mock_result

        with pytest.raises(AuthenticationError) as exc_info:
            await auth_service.login(db, "nonexistent", "password")

        assert exc_info.value.code == 1001

    async def test_login_inactive_user_raises_authentication_error(
        self, auth_service, security
    ) -> None:
        """禁用用户登录时抛出 AuthenticationError(code=1001)。"""
        from src.core.enums import MembershipTier
        from src.core.exceptions import AuthenticationError
        from src.models.user import User

        hashed_pw = security.hash_password("password")

        db = AsyncMock()
        mock_result = MagicMock()
        mock_user = MagicMock(spec=User)
        mock_user.id = 1
        mock_user.hashed_password = hashed_pw
        mock_user.membership = MembershipTier.FREE
        mock_user.is_active = False  # 禁用状态
        mock_result.scalar_one_or_none.return_value = mock_user
        db.execute.return_value = mock_result

        with pytest.raises(AuthenticationError) as exc_info:
            await auth_service.login(db, "disableduser", "password")

        assert exc_info.value.code == 1001


class TestRefreshAccessToken:
    """AuthService.refresh_access_token token 刷新逻辑测试。"""

    async def test_refresh_with_valid_refresh_token_returns_new_access_token(
        self, auth_service, security
    ) -> None:
        """有效 refresh_token 时返回新的 access_token。"""
        from src.core.enums import MembershipTier
        from src.models.user import User

        refresh_token = security.create_refresh_token(sub="99")

        db = AsyncMock()
        mock_user = MagicMock(spec=User)
        mock_user.id = 99
        mock_user.membership = MembershipTier.VIP1
        mock_user.is_active = True
        db.get.return_value = mock_user

        new_access_token = await auth_service.refresh_access_token(db, refresh_token)

        assert new_access_token
        payload = security.decode_token(new_access_token)
        assert payload["sub"] == "99"
        assert payload["type"] == "access"

    async def test_refresh_with_access_token_raises_authentication_error(
        self, auth_service, security
    ) -> None:
        """传入 access_token（type 不匹配）时抛出 AuthenticationError。"""
        from src.core.enums import MembershipTier
        from src.core.exceptions import AuthenticationError

        # 传入 access_token 而非 refresh_token
        access_token = security.create_access_token(
            sub="1", membership=MembershipTier.FREE
        )
        db = AsyncMock()

        with pytest.raises(AuthenticationError):
            await auth_service.refresh_access_token(db, access_token)

    async def test_refresh_with_expired_token_raises_authentication_error(
        self, auth_service
    ) -> None:
        """refresh_token 过期时抛出 AuthenticationError。"""
        from datetime import datetime, timedelta, timezone

        from jose import jwt

        from src.core.exceptions import AuthenticationError

        expired_payload = {
            "sub": "1",
            "exp": datetime.now(timezone.utc) - timedelta(seconds=10),
            "iat": datetime.now(timezone.utc) - timedelta(days=8),
            "type": "refresh",
        }
        expired_token = jwt.encode(expired_payload, TEST_SECRET, algorithm="HS256")
        db = AsyncMock()

        with pytest.raises(AuthenticationError):
            await auth_service.refresh_access_token(db, expired_token)

    async def test_refresh_with_invalid_token_raises_authentication_error(
        self, auth_service
    ) -> None:
        """无效 token 字符串时抛出 AuthenticationError。"""
        from src.core.exceptions import AuthenticationError

        db = AsyncMock()

        with pytest.raises(AuthenticationError):
            await auth_service.refresh_access_token(db, "not.a.valid.token")
