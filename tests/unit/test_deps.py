"""FastAPI 依赖注入函数单元测试（任务 1.4）。

测试：
  - get_current_user 从 DB 实时读取用户状态（不信任 JWT claims 中的 membership）
  - get_current_user 在 is_active=False 时抛出 AuthenticationError
  - get_optional_user 在无 token 或无效 token 时返回 None（不拦截请求）
  - require_membership 在等级不足时抛出 MembershipError（code=1003）
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

# 测试用固定密钥
TEST_SECRET = "test-secret-key-for-deps-tests-256bits"


@pytest.fixture()
def setup_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SECRET_KEY", TEST_SECRET)
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")
    monkeypatch.setenv("DATABASE_SYNC_URL", "postgresql+psycopg2://u:p@localhost/db")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")

    from src.core import app_settings

    app_settings.get_settings.cache_clear()


@pytest.fixture()
def security_utils(setup_env):
    from src.core.security import SecurityUtils

    return SecurityUtils()


def make_mock_user(
    user_id: int = 1,
    membership: str = "free",
    is_active: bool = True,
) -> MagicMock:
    """构造模拟 User 对象。"""
    user = MagicMock()
    user.id = user_id
    user.is_active = is_active
    user.membership = membership
    return user


class TestGetCurrentUser:
    """get_current_user 依赖注入测试。"""

    @pytest.mark.asyncio
    async def test_returns_user_when_token_valid(self, setup_env, security_utils) -> None:
        from src.core.enums import MembershipTier

        token = security_utils.create_access_token(sub="1", membership=MembershipTier.FREE)
        mock_user = make_mock_user(user_id=1, membership="free", is_active=True)
        mock_db = AsyncMock()
        mock_db.get.return_value = mock_user

        mock_credentials = MagicMock()
        mock_credentials.credentials = token

        from src.core.deps import get_current_user

        result = await get_current_user(credentials=mock_credentials, db=mock_db)
        assert result == mock_user
        mock_db.get.assert_called_once()

    @pytest.mark.asyncio
    async def test_raises_when_user_is_inactive(self, setup_env, security_utils) -> None:
        from src.core.enums import MembershipTier
        from src.core.exceptions import AuthenticationError

        token = security_utils.create_access_token(sub="1", membership=MembershipTier.FREE)
        mock_user = make_mock_user(user_id=1, is_active=False)
        mock_db = AsyncMock()
        mock_db.get.return_value = mock_user

        mock_credentials = MagicMock()
        mock_credentials.credentials = token

        from src.core.deps import get_current_user

        with pytest.raises(AuthenticationError):
            await get_current_user(credentials=mock_credentials, db=mock_db)

    @pytest.mark.asyncio
    async def test_raises_when_user_not_found(self, setup_env, security_utils) -> None:
        from src.core.enums import MembershipTier
        from src.core.exceptions import AuthenticationError

        token = security_utils.create_access_token(sub="999", membership=MembershipTier.FREE)
        mock_db = AsyncMock()
        mock_db.get.return_value = None  # 用户不存在

        mock_credentials = MagicMock()
        mock_credentials.credentials = token

        from src.core.deps import get_current_user

        with pytest.raises(AuthenticationError):
            await get_current_user(credentials=mock_credentials, db=mock_db)

    @pytest.mark.asyncio
    async def test_raises_when_token_invalid(self, setup_env) -> None:
        from src.core.exceptions import AuthenticationError

        mock_db = AsyncMock()
        mock_credentials = MagicMock()
        mock_credentials.credentials = "invalid.token.here"

        from src.core.deps import get_current_user

        with pytest.raises(AuthenticationError):
            await get_current_user(credentials=mock_credentials, db=mock_db)


class TestGetOptionalUser:
    """get_optional_user 依赖注入测试。"""

    @pytest.mark.asyncio
    async def test_returns_none_when_no_auth_header(self, setup_env) -> None:
        from starlette.requests import Request

        mock_request = MagicMock(spec=Request)
        mock_request.headers = {}
        mock_db = AsyncMock()

        from src.core.deps import get_optional_user

        result = await get_optional_user(request=mock_request, db=mock_db)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_token_invalid(self, setup_env) -> None:
        from starlette.requests import Request

        mock_request = MagicMock(spec=Request)
        mock_request.headers = {"authorization": "Bearer invalid.token"}
        mock_db = AsyncMock()

        from src.core.deps import get_optional_user

        result = await get_optional_user(request=mock_request, db=mock_db)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_user_when_token_valid(self, setup_env, security_utils) -> None:
        from starlette.requests import Request

        from src.core.enums import MembershipTier

        token = security_utils.create_access_token(sub="1", membership=MembershipTier.VIP1)
        mock_user = make_mock_user(user_id=1, membership="vip1", is_active=True)
        mock_db = AsyncMock()
        mock_db.get.return_value = mock_user

        mock_request = MagicMock(spec=Request)
        mock_request.headers = {"authorization": f"Bearer {token}"}

        from src.core.deps import get_optional_user

        result = await get_optional_user(request=mock_request, db=mock_db)
        assert result == mock_user

    @pytest.mark.asyncio
    async def test_returns_none_when_user_inactive(self, setup_env, security_utils) -> None:
        """is_active=False 的用户，get_optional_user 应返回 None（不抛异常）。"""
        from starlette.requests import Request

        from src.core.enums import MembershipTier

        token = security_utils.create_access_token(sub="1", membership=MembershipTier.FREE)
        mock_user = make_mock_user(user_id=1, is_active=False)
        mock_db = AsyncMock()
        mock_db.get.return_value = mock_user

        mock_request = MagicMock(spec=Request)
        mock_request.headers = {"authorization": f"Bearer {token}"}

        from src.core.deps import get_optional_user

        result = await get_optional_user(request=mock_request, db=mock_db)
        assert result is None


class TestRequireMembership:
    """require_membership 工厂函数测试。"""

    @pytest.mark.asyncio
    async def test_passes_when_user_meets_tier(self, setup_env) -> None:
        from src.core.deps import require_membership
        from src.core.enums import MembershipTier

        mock_user = make_mock_user(membership=MembershipTier.VIP1)
        checker = require_membership(MembershipTier.VIP1)
        result = await checker(current_user=mock_user)
        assert result == mock_user

    @pytest.mark.asyncio
    async def test_passes_when_user_exceeds_tier(self, setup_env) -> None:
        from src.core.deps import require_membership
        from src.core.enums import MembershipTier

        mock_user = make_mock_user(membership=MembershipTier.VIP2)
        checker = require_membership(MembershipTier.VIP1)
        result = await checker(current_user=mock_user)
        assert result == mock_user

    @pytest.mark.asyncio
    async def test_raises_when_user_below_tier(self, setup_env) -> None:
        from src.core.deps import require_membership
        from src.core.enums import MembershipTier
        from src.core.exceptions import MembershipError

        mock_user = make_mock_user(membership=MembershipTier.FREE)
        checker = require_membership(MembershipTier.VIP1)
        with pytest.raises(MembershipError):
            await checker(current_user=mock_user)

    @pytest.mark.asyncio
    async def test_free_user_passes_free_tier(self, setup_env) -> None:
        from src.core.deps import require_membership
        from src.core.enums import MembershipTier

        mock_user = make_mock_user(membership=MembershipTier.FREE)
        checker = require_membership(MembershipTier.FREE)
        result = await checker(current_user=mock_user)
        assert result == mock_user
