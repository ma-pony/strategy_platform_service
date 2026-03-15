"""JWT 安全工具单元测试（任务 1.3 / 13.1）。

验证：
  - create_access_token 生成 claims 含 sub/membership/exp/iat/type
  - decode_token 在 token 过期、签名无效、type 不匹配时均抛出 AuthenticationError
  - hash_password / verify_password 一致性
  - 错误密码校验返回 False
"""

import time

import pytest

# 测试用固定密钥（仅测试环境使用）
TEST_SECRET = "test-secret-key-for-unit-tests-only-256bits"


@pytest.fixture()
def security(monkeypatch: pytest.MonkeyPatch):
    """提供已注入测试密钥的 SecurityUtils 实例。"""
    monkeypatch.setenv("SECRET_KEY", TEST_SECRET)
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")
    monkeypatch.setenv("DATABASE_SYNC_URL", "postgresql+psycopg2://u:p@localhost/db")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")

    from src.core import app_settings
    from src.core.security import SecurityUtils

    app_settings.get_settings.cache_clear()
    return SecurityUtils()


class TestCreateAccessToken:
    """create_access_token 测试。"""

    def test_access_token_claims_contain_sub(self, security) -> None:
        from src.core.enums import MembershipTier

        token = security.create_access_token(sub="42", membership=MembershipTier.FREE)
        payload = security.decode_token(token)
        assert payload["sub"] == "42"

    def test_access_token_claims_contain_membership(self, security) -> None:
        from src.core.enums import MembershipTier

        token = security.create_access_token(sub="1", membership=MembershipTier.VIP1)
        payload = security.decode_token(token)
        assert payload["membership"] == MembershipTier.VIP1.value

    def test_access_token_claims_contain_exp(self, security) -> None:
        from src.core.enums import MembershipTier

        token = security.create_access_token(sub="1", membership=MembershipTier.FREE)
        payload = security.decode_token(token)
        assert "exp" in payload
        assert payload["exp"] > int(time.time())

    def test_access_token_claims_contain_iat(self, security) -> None:
        from src.core.enums import MembershipTier

        token = security.create_access_token(sub="1", membership=MembershipTier.FREE)
        payload = security.decode_token(token)
        assert "iat" in payload

    def test_access_token_type_is_access(self, security) -> None:
        from src.core.enums import MembershipTier

        token = security.create_access_token(sub="1", membership=MembershipTier.FREE)
        payload = security.decode_token(token)
        assert payload["type"] == "access"

    def test_access_token_expires_in_30_minutes(self, security) -> None:
        from src.core.enums import MembershipTier

        before = int(time.time())
        token = security.create_access_token(sub="1", membership=MembershipTier.FREE)
        payload = security.decode_token(token)
        # exp 应在 30 分钟内（1800 秒 ± 5 秒容差）
        assert 1795 <= payload["exp"] - before <= 1805


class TestCreateRefreshToken:
    """create_refresh_token 测试。"""

    def test_refresh_token_type_is_refresh(self, security) -> None:
        token = security.create_refresh_token(sub="1")
        # refresh token 不应通过 decode_token（type="access" 校验）
        from src.core.exceptions import AuthenticationError

        with pytest.raises(AuthenticationError):
            security.decode_token(token)

    def test_refresh_token_can_be_decoded_with_type_check_disabled(self, security) -> None:
        """refresh token 本身是合法 JWT，只是 type 字段为 refresh。"""
        token = security.create_refresh_token(sub="99")
        payload = security.decode_token(token, expected_type="refresh")
        assert payload["sub"] == "99"
        assert payload["type"] == "refresh"

    def test_refresh_token_expires_in_7_days(self, security) -> None:
        before = int(time.time())
        token = security.create_refresh_token(sub="1")
        payload = security.decode_token(token, expected_type="refresh")
        seven_days = 7 * 24 * 3600
        assert seven_days - 5 <= payload["exp"] - before <= seven_days + 5


class TestDecodeToken:
    """decode_token 失败场景测试。"""

    def test_invalid_signature_raises_authentication_error(self, security) -> None:
        from src.core.enums import MembershipTier
        from src.core.exceptions import AuthenticationError

        token = security.create_access_token(sub="1", membership=MembershipTier.FREE)
        tampered = token[:-4] + "xxxx"
        with pytest.raises(AuthenticationError):
            security.decode_token(tampered)

    def test_expired_token_raises_authentication_error(self, monkeypatch: pytest.MonkeyPatch, security) -> None:
        """past exp 时间的 token 应抛出 AuthenticationError。"""
        from datetime import datetime, timedelta, timezone

        # 手动创建过期 token
        from jose import jwt

        from src.core.enums import MembershipTier
        from src.core.exceptions import AuthenticationError

        payload = {
            "sub": "1",
            "membership": MembershipTier.FREE.value,
            "exp": datetime.now(timezone.utc) - timedelta(seconds=10),
            "iat": datetime.now(timezone.utc) - timedelta(minutes=31),
            "type": "access",
        }
        expired_token = jwt.encode(payload, TEST_SECRET, algorithm="HS256")
        with pytest.raises(AuthenticationError):
            security.decode_token(expired_token)

    def test_wrong_type_raises_authentication_error(self, security) -> None:
        """将 refresh_token 用于 decode_token（期望 type=access）时应抛出 AuthenticationError。"""
        from src.core.exceptions import AuthenticationError

        refresh_token = security.create_refresh_token(sub="1")
        with pytest.raises(AuthenticationError):
            security.decode_token(refresh_token)  # 默认期望 type=access

    def test_malformed_token_raises_authentication_error(self, security) -> None:
        from src.core.exceptions import AuthenticationError

        with pytest.raises(AuthenticationError):
            security.decode_token("not.a.valid.token")


class TestPasswordUtils:
    """密码哈希工具测试。"""

    def test_hash_password_returns_non_empty_string(self, security) -> None:
        hashed = security.hash_password("my_password")
        assert isinstance(hashed, str)
        assert len(hashed) > 0

    def test_hash_password_is_different_from_plaintext(self, security) -> None:
        plain = "my_password"
        hashed = security.hash_password(plain)
        assert hashed != plain

    def test_verify_password_returns_true_for_correct_password(self, security) -> None:
        plain = "correct_password"
        hashed = security.hash_password(plain)
        assert security.verify_password(plain, hashed) is True

    def test_verify_password_returns_false_for_wrong_password(self, security) -> None:
        hashed = security.hash_password("correct_password")
        assert security.verify_password("wrong_password", hashed) is False

    def test_two_hashes_of_same_password_are_different(self, security) -> None:
        """bcrypt 使用随机 salt，相同密码每次哈希结果不同。"""
        plain = "same_password"
        hash1 = security.hash_password(plain)
        hash2 = security.hash_password(plain)
        assert hash1 != hash2
        # 但两者都能通过校验
        assert security.verify_password(plain, hash1) is True
        assert security.verify_password(plain, hash2) is True
