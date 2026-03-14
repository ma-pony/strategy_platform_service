"""认证相关 Pydantic Schema。

定义注册、登录、token 刷新的请求体和响应体 Schema。
"""

from datetime import datetime

from pydantic import BaseModel, Field

from src.core.enums import MembershipTier


class RegisterRequest(BaseModel):
    """注册请求体 Schema。"""

    username: str = Field(..., min_length=1, max_length=64, description="用户名")
    password: str = Field(..., min_length=6, max_length=128, description="密码")


class LoginRequest(BaseModel):
    """登录请求体 Schema。"""

    username: str = Field(..., description="用户名")
    password: str = Field(..., description="密码")


class RefreshRequest(BaseModel):
    """Token 刷新请求体 Schema。"""

    refresh_token: str = Field(..., description="refresh_token 字符串")


class UserRead(BaseModel):
    """用户信息响应 Schema（注册成功时返回）。"""

    id: int
    username: str
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
