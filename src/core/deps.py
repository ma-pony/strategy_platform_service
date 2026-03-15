"""FastAPI 依赖注入函数集合。

提供：
  - get_db：异步 session 生命周期管理（asyncpg 驱动）
  - get_current_user：强制鉴权，从 DB 实时读取用户状态
  - get_optional_user：宽松鉴权，无 token 或无效 token 时返回 None
  - require_membership：会员等级校验工厂函数

关键约束：
  - get_current_user 和 get_optional_user 均从 DB 实时查询用户 membership 和 is_active，
    不信任 JWT claims 中的 membership 值，确保运营后台修改即时生效。
"""

from collections.abc import AsyncGenerator, Callable
from typing import Any

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.core.app_settings import get_settings
from src.core.enums import MembershipTier
from src.core.exceptions import AuthenticationError, MembershipError, PermissionError
from src.core.security import SecurityUtils

# Bearer token 鉴权方案（auto_error=False 支持可选鉴权）
_bearer_scheme = HTTPBearer(auto_error=False)

# SecurityUtils 单例
_security = SecurityUtils()

# 会员等级层次（低 → 高），用于等级比较
_TIER_ORDER: list[MembershipTier] = [
    MembershipTier.FREE,
    MembershipTier.VIP1,
    MembershipTier.VIP2,
]


# 模块级异步 engine 和 session factory（进程内单例）
_settings = get_settings()
_async_engine = create_async_engine(
    _settings.database_url,
    pool_size=_settings.db_pool_size,
    max_overflow=_settings.db_max_overflow,
    pool_pre_ping=True,
    echo=_settings.debug,
)
_async_session_factory = async_sessionmaker(_async_engine, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """异步数据库 session 依赖注入。

    每次 HTTP 请求创建独立 session，请求结束后自动关闭。
    使用 asyncpg 异步驱动，适用于 Web 请求路径。
    """
    async with _async_session_factory() as session:
        yield session


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """强制鉴权依赖注入：解析 Bearer token 并从 DB 实时查询用户。

    流程：
      1. 解析 Authorization: Bearer {token}
      2. 校验 token 签名、过期时间、type="access"
      3. 从 DB 实时查询 User 对象（获取最新 membership 和 is_active）
      4. is_active=False 时抛出 AuthenticationError(1001)

    注意：不使用 JWT claims 中的 membership，以 DB 为准。

    Raises:
        AuthenticationError: token 无效、用户不存在或账户被禁用
    """
    if credentials is None:
        raise AuthenticationError("缺少 Authorization header")

    # 1. 解码并校验 token
    payload = _security.decode_token(credentials.credentials)
    user_id_str: str = payload.get("sub", "")

    # 2. 从 DB 实时查询用户
    # 注意：import 放在函数内，避免循环引用（deps <- models）
    from src.models.user import User  # type: ignore[attr-defined]

    try:
        user_id = int(user_id_str)
    except (ValueError, TypeError):
        raise AuthenticationError("token sub 字段无效") from None

    user = await db.get(User, user_id)

    # 3. 校验用户状态
    if user is None:
        raise AuthenticationError("用户不存在")

    if not user.is_active:
        raise AuthenticationError("用户账户已被禁用")

    return user


async def get_optional_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Any | None:
    """宽松鉴权依赖注入：有效 token 时返回用户，否则返回 None。

    规则：
      - 未携带 Authorization header → 返回 None
      - Authorization header 格式非法 → 返回 None
      - token 无效或过期 → 返回 None
      - 用户不存在或已禁用 → 返回 None
      - 有效 token 且用户正常 → 返回 User 对象（从 DB 实时读取）

    始终返回，不抛出任何异常，供展示类接口使用。
    """
    # headers 可能是 Starlette MutableHeaders 或普通 dict（测试场景）
    headers = request.headers
    auth_header = ""
    # Starlette Headers 支持大小写不敏感查找；dict 则直接取
    try:
        auth_header = headers.get("authorization") or headers.get("Authorization") or ""
    except Exception:
        return None

    if not auth_header.startswith("Bearer "):
        return None

    token = auth_header[len("Bearer ") :].strip()
    if not token:
        return None

    try:
        payload = _security.decode_token(token)
        user_id_str: str = payload.get("sub", "")
        user_id = int(user_id_str)
    except Exception:
        return None

    try:
        from src.models.user import User  # type: ignore[attr-defined]

        user = await db.get(User, user_id)
    except Exception:
        return None

    if user is None or not user.is_active:
        return None

    return user


async def require_admin(
    current_user: Any = Depends(get_current_user),
) -> Any:
    """管理员鉴权依赖注入：校验 user.is_admin。

    Raises:
        PermissionError: 非管理员用户，code=1002
    """
    if not getattr(current_user, "is_admin", False):
        raise PermissionError("需要管理员权限")
    return current_user


def require_membership(min_tier: MembershipTier) -> Callable[..., Any]:
    """会员等级校验工厂函数。

    返回一个 FastAPI 可用的 Depends 校验函数，以 DB 用户对象的
    membership 字段为准执行等级校验，不足时抛出 MembershipError(1003)。

    用法：
        @router.get("/vip-only")
        async def vip_endpoint(
            user = Depends(require_membership(MembershipTier.VIP1))
        ):
            ...
    """

    async def checker(
        current_user: Any = Depends(get_current_user),
    ) -> Any:
        user_tier = current_user.membership
        # 支持字符串和枚举两种形式
        if isinstance(user_tier, str):
            try:
                user_tier = MembershipTier(user_tier)
            except ValueError:
                raise MembershipError("无效的会员等级") from None

        if _TIER_ORDER.index(user_tier) < _TIER_ORDER.index(min_tier):
            raise MembershipError("会员等级不足，请升级后访问")

        return current_user

    return checker
