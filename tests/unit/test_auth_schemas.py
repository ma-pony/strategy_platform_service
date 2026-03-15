"""认证 Schema 单元测试（任务 4.1 & 4.2 / 需求 1.1, 1.2, 1.5, 1.6, 1.7, 2.1, 3.4, 4.3）。

验证：
  - RegisterRequest 将 username 替换为 email 字段，使用 EmailValidator 校验
  - RegisterRequest 密码最低长度为 8 字符（从原来的 6 升级）
  - LoginRequest 将 username 替换为 email 字段，使用 EmailValidator 校验
  - UserRead 将 username 替换为 email 字段
"""

import pytest
from pydantic import ValidationError


class TestRegisterRequestSchema:
    """RegisterRequest Schema 单元测试（任务 4.1）。"""

    def test_register_request_has_email_field(self) -> None:
        """RegisterRequest 应包含 email 字段，不含 username。"""
        from src.schemas.auth import RegisterRequest

        req = RegisterRequest(email="user@example.com", password="password123")
        assert req.email == "user@example.com"
        assert not hasattr(req, "username")

    def test_register_request_valid_email_and_password(self) -> None:
        """合法邮箱和满足长度要求的密码应正常解析。"""
        from src.schemas.auth import RegisterRequest

        req = RegisterRequest(email="test@example.com", password="abcdefgh")
        assert req.email == "test@example.com"
        assert req.password == "abcdefgh"

    def test_register_request_email_normalized(self) -> None:
        """邮箱字段经过 EmailValidator 归一化（仅域名部分小写化）。

        根据 RFC 5321，本地部分（@前）区分大小写，email-validator 仅归一化域名部分。
        """
        from src.schemas.auth import RegisterRequest

        req = RegisterRequest(email="user@EXAMPLE.COM", password="password123")
        # 域名部分应被归一化为小写，本地部分原样保留
        assert req.email == "user@example.com"

    def test_register_request_invalid_email_raises_validation_error(self) -> None:
        """邮箱格式非法时抛出 Pydantic ValidationError。"""
        from src.schemas.auth import RegisterRequest

        with pytest.raises(ValidationError):
            RegisterRequest(email="not-an-email", password="password123")

    def test_register_request_missing_at_raises_validation_error(self) -> None:
        """邮箱缺少 @ 时抛出 Pydantic ValidationError。"""
        from src.schemas.auth import RegisterRequest

        with pytest.raises(ValidationError):
            RegisterRequest(email="invalidemail.com", password="password123")

    def test_register_request_password_min_length_is_8(self) -> None:
        """密码最低长度为 8 字符，7 字符应抛出 ValidationError。"""
        from src.schemas.auth import RegisterRequest

        with pytest.raises(ValidationError):
            RegisterRequest(email="user@example.com", password="short1!")

    def test_register_request_password_exactly_8_chars_passes(self) -> None:
        """密码恰好 8 字符时校验通过。"""
        from src.schemas.auth import RegisterRequest

        req = RegisterRequest(email="user@example.com", password="exactly8")
        assert len(req.password) == 8

    def test_register_request_password_7_chars_raises_validation_error(self) -> None:
        """密码 7 字符时抛出 ValidationError（需求 1.6, 1.7）。"""
        from src.schemas.auth import RegisterRequest

        with pytest.raises(ValidationError):
            RegisterRequest(email="user@example.com", password="only7ch")

    def test_register_request_password_max_length_128(self) -> None:
        """密码最长 128 字符，超出时抛出 ValidationError。"""
        from src.schemas.auth import RegisterRequest

        with pytest.raises(ValidationError):
            RegisterRequest(email="user@example.com", password="a" * 129)

    def test_register_request_email_max_length_254(self) -> None:
        """邮箱最大长度 254 字符，超出时抛出 ValidationError。"""
        from src.schemas.auth import RegisterRequest

        long_local = "a" * 245
        with pytest.raises(ValidationError):
            RegisterRequest(email=f"{long_local}@example.com", password="password123")

    def test_register_request_has_no_username_field(self) -> None:
        """RegisterRequest 模型定义中不含 username 字段（已替换为 email）。"""
        from src.schemas.auth import RegisterRequest

        # 确认 model_fields 中不存在 username，只有 email 和 password
        assert "username" not in RegisterRequest.model_fields
        assert "email" in RegisterRequest.model_fields
        assert "password" in RegisterRequest.model_fields


class TestLoginRequestSchema:
    """LoginRequest Schema 单元测试（任务 4.2）。"""

    def test_login_request_has_email_field(self) -> None:
        """LoginRequest 应包含 email 字段，不含 username。"""
        from src.schemas.auth import LoginRequest

        req = LoginRequest(email="user@example.com", password="password123")
        assert req.email == "user@example.com"
        assert not hasattr(req, "username")

    def test_login_request_valid_email_passes(self) -> None:
        """合法邮箱的登录请求应正常解析。"""
        from src.schemas.auth import LoginRequest

        req = LoginRequest(email="test@example.com", password="anypassword")
        assert req.email == "test@example.com"

    def test_login_request_invalid_email_raises_validation_error(self) -> None:
        """邮箱格式非法时抛出 Pydantic ValidationError。"""
        from src.schemas.auth import LoginRequest

        with pytest.raises(ValidationError):
            LoginRequest(email="not-an-email", password="anypassword")

    def test_login_request_email_normalized(self) -> None:
        """登录邮箱经过 EmailValidator 归一化（仅域名部分小写化）。

        根据 RFC 5321，本地部分（@前）区分大小写，email-validator 仅归一化域名部分。
        """
        from src.schemas.auth import LoginRequest

        req = LoginRequest(email="user@EXAMPLE.COM", password="anypassword")
        # 域名部分应被归一化为小写，本地部分原样保留
        assert req.email == "user@example.com"

    def test_login_request_missing_at_raises_validation_error(self) -> None:
        """邮箱缺少 @ 时抛出 ValidationError。"""
        from src.schemas.auth import LoginRequest

        with pytest.raises(ValidationError):
            LoginRequest(email="invalidemail.com", password="anypassword")


class TestUserReadSchema:
    """UserRead Schema 单元测试（任务 4.2）。"""

    def test_user_read_has_email_field(self) -> None:
        """UserRead 应包含 email 字段，不含 username。"""
        from src.core.enums import MembershipTier
        from src.schemas.auth import UserRead

        user = UserRead(id=1, email="user@example.com", membership=MembershipTier.FREE)
        assert user.email == "user@example.com"
        assert not hasattr(user, "username")

    def test_user_read_from_attributes(self) -> None:
        """UserRead 应支持 from_attributes 模式（从 ORM 对象构造）。"""
        from unittest.mock import MagicMock

        from src.core.enums import MembershipTier
        from src.schemas.auth import UserRead

        mock_user = MagicMock()
        mock_user.id = 1
        mock_user.email = "user@example.com"
        mock_user.membership = MembershipTier.FREE
        mock_user.created_at = None

        user = UserRead.model_validate(mock_user)
        assert user.id == 1
        assert user.email == "user@example.com"
        assert user.membership == MembershipTier.FREE

    def test_user_read_does_not_expose_password(self) -> None:
        """UserRead 不应包含 hashed_password 字段（需求 1.5, 6.4）。"""
        from src.schemas.auth import UserRead

        assert not hasattr(UserRead.model_fields, "hashed_password")
