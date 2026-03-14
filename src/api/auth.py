"""认证 API 路由层。

实现 POST /api/v1/auth/register、/login、/refresh 三个端点。
所有响应使用统一信封格式（ApiResponse）。
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.deps import get_db
from src.core.response import ApiResponse, ok
from src.schemas.auth import (
    AccessToken,
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    TokenPair,
    UserRead,
)
from src.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["认证"])
_auth_service = AuthService()


@router.post(
    "/register",
    response_model=ApiResponse[UserRead],
    summary="用户注册",
    description="注册新用户账户，初始会员等级为 FREE。用户名重复时返回 code:2001。",
)
async def register(
    body: RegisterRequest,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[UserRead]:
    """用户注册端点。

    - 成功：返回 code:0 及用户基本信息（id, username, membership, created_at）
    - 用户名重复：返回 code:2001 HTTP 400
    - 参数校验失败：返回 code:2001 HTTP 422
    """
    user = await _auth_service.register(db, body.username, body.password)
    user_read = UserRead.model_validate(user)
    return ok(data=user_read)


@router.post(
    "/login",
    response_model=ApiResponse[TokenPair],
    summary="用户登录",
    description="使用用户名和密码登录，返回 access_token 和 refresh_token。",
)
async def login(
    body: LoginRequest,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[TokenPair]:
    """用户登录端点。

    - 成功：返回 code:0 及 {access_token, refresh_token, token_type}
    - 凭证错误：返回 code:1001 HTTP 401
    """
    access_token, refresh_token = await _auth_service.login(
        db, body.username, body.password
    )
    return ok(data=TokenPair(access_token=access_token, refresh_token=refresh_token))


@router.post(
    "/refresh",
    response_model=ApiResponse[AccessToken],
    summary="刷新 access token",
    description="使用有效的 refresh_token 签发新的 access_token。",
)
async def refresh_token(
    body: RefreshRequest,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[AccessToken]:
    """Token 刷新端点。

    - 成功：返回 code:0 及 {access_token, token_type}
    - token 无效/过期/类型错误：返回 code:1001 HTTP 401
    """
    new_access_token = await _auth_service.refresh_access_token(
        db, body.refresh_token
    )
    return ok(data=AccessToken(access_token=new_access_token))
