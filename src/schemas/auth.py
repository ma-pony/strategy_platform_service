"""认证相关 Pydantic Schema。

定义注册、登录、token 刷新的请求体和响应体 Schema。
"""

from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from src.core.enums import MembershipTier
from src.utils.email_validator import EmailValidator


class RegisterRequest(BaseModel):
    """注册请求体 Schema（任务 4.1）。

    将 username 字段替换为 email 字段，密码最低长度从 6 升级为 8。
    邮箱格式校验通过 EmailValidator 在 Pydantic 解析阶段自动触发。
    """

    email: str = Field(..., max_length=254, description="注册邮箱")
    password: str = Field(..., min_length=8, max_length=128, description="密码，至少8个字符")

    @field_validator("email")
    @classmethod
    def validate_email_field(cls, v: str) -> str:
        """调用 EmailValidator 校验并归一化邮箱地址。"""
        return EmailValidator.validate(v)


class LoginRequest(BaseModel):
    """登录请求体 Schema（任务 4.2）。

    将 username 字段替换为 email 字段。
    邮箱格式校验通过 EmailValidator 在 Pydantic 解析阶段自动触发。
    """

    email: str = Field(..., description="登录邮箱")
    password: str = Field(..., description="密码")

    @field_validator("email")
    @classmethod
    def validate_email_field(cls, v: str) -> str:
        """调用 EmailValidator 校验并归一化邮箱地址。"""
        return EmailValidator.validate(v)


class RefreshRequest(BaseModel):
    """Token 刷新请求体 Schema。"""

    refresh_token: str = Field(..., description="refresh_token 字符串")


class UserRead(BaseModel):
    """用户信息响应 Schema（注册成功时返回，任务 4.2）。

    将 username 字段替换为 email 字段，仅暴露安全字段。
    """

    id: int
    email: str
    membership: MembershipTier
    created_at: datetime | None = None

    model_config = {"from_attributes": True}


class TokenPair(BaseModel):
    """登录成功响应 Schema，包含 access_token 和 refresh_token。"""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class AccessToken(BaseModel):
    """Token 刷新成功响应 Schema，仅含 access_token。"""

    access_token: str
    token_type: str = "bearer"
