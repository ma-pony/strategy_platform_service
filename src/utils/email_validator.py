"""邮箱格式校验工具（需求 4.1–4.4）。

主路径：使用 email-validator 库执行 RFC 5321/5322 合规校验。
降级路径：email-validator 不可用时，回退至基础正则校验，并记录 WARNING 日志。

校验失败时抛出 ValueError，由 Pydantic field_validator 捕获转为 ValidationError。
"""

import logging
import re

logger = logging.getLogger(__name__)

# 在模块加载时检测 email-validator 库可用性
_EMAIL_VALIDATOR_AVAILABLE = False
try:
    import email_validator as _ev_lib  # noqa: F401

    _EMAIL_VALIDATOR_AVAILABLE = True
except ImportError:
    logger.warning(
        "email-validator 库不可用，邮箱校验降级为基础正则模式",
        extra={"reason": "email_validator import failed"},
    )

# 降级用的基础正则（宽松于 RFC 标准，仅做基本结构检查）
_FALLBACK_EMAIL_RE = re.compile(r"^[^@]+@[^@]+\.[^@]+$")


class EmailValidator:
    """邮箱格式校验工具类。

    提供统一的邮箱校验入口，封装 email-validator 库调用，支持降级。
    所有方法均为静态方法，无实例状态。
    """

    @staticmethod
    def validate(email: str) -> str:
        """校验并归一化邮箱地址。

        Args:
            email: 用户提交的原始邮箱字符串。

        Returns:
            归一化后的合法邮箱字符串（如小写化、去除多余空白）。

        Raises:
            ValueError: 邮箱格式不合法，含具体原因描述。
        """
        if not email:
            raise ValueError("邮箱地址不能为空")

        if _EMAIL_VALIDATOR_AVAILABLE:
            return EmailValidator._validate_with_library(email)
        return EmailValidator._validate_with_fallback(email)

    @staticmethod
    def _validate_with_library(email: str) -> str:
        """使用 email-validator 库执行 RFC 5321/5322 校验。"""
        import email_validator

        try:
            validated = email_validator.validate_email(email, check_deliverability=False)
            return str(validated.normalized)
        except email_validator.EmailNotValidError as exc:
            raise ValueError(str(exc)) from exc

    @staticmethod
    def _validate_with_fallback(email: str) -> str:
        """降级模式：使用基础正则执行邮箱格式校验。"""
        if not _FALLBACK_EMAIL_RE.match(email):
            raise ValueError(f"邮箱格式无效（降级校验）: {email!r}")
        return email.lower()
