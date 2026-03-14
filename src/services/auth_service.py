"""认证服务层。

提供用户注册、登录和 token 刷新的业务逻辑。

职责与约束：
  - 注册时检查用户名唯一性，密码以 bcrypt 哈希存储
  - 登录时校验 bcrypt 哈希，凭证错误时抛出 AuthenticationError(1001)
  - 刷新时校验 refresh_token 类型和有效性，签发新 access_token
  - 不依赖 FastAPI 或 HTTP 层，可独立测试
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import AuthenticationError, ValidationError
from src.core.security import SecurityUtils
from src.models.user import User

_security = SecurityUtils()


class AuthService:
    """用户认证业务逻辑服务。

    所有方法接受 AsyncSession 参数，由路由层通过依赖注入传入。
    """

    async def register(
        self, db: AsyncSession, username: str, password: str
    ) -> User:
        """注册新用户。

        步骤：
          1. 查询用户名是否已存在
          2. 以 bcrypt 哈希存储密码
          3. 创建新用户（membership=FREE）

        Args:
            db: 异步数据库 session
            username: 用户名（长度校验由 Schema 层负责）
            password: 明文密码

        Returns:
            新创建的 User 对象

        Raises:
            ValidationError: 用户名已存在（code=2001）
        """
        # 1. 检查用户名唯一性
        stmt = select(User).where(User.username == username)
        result = await db.execute(stmt)
        existing = result.scalar_one_or_none()
        if existing is not None:
            raise ValidationError("用户名已被使用")

        # 2. 哈希密码
        hashed_pw = _security.hash_password(password)

        # 3. 创建用户
        user = User(
            username=username,
            hashed_password=hashed_pw,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user

    async def login(
        self, db: AsyncSession, username: str, password: str
    ) -> tuple[str, str]:
        """用户登录，返回 (access_token, refresh_token) 元组。

        步骤：
          1. 查询用户
          2. 校验 bcrypt 密码哈希
          3. 校验 is_active 状态
          4. 签发 access_token + refresh_token

        Args:
            db: 异步数据库 session
            username: 用户名
            password: 明文密码

        Returns:
            (access_token, refresh_token) 字符串元组

        Raises:
            AuthenticationError: 用户不存在、密码错误或账户被禁用（code=1001）
        """
        # 1. 查询用户
        stmt = select(User).where(User.username == username)
        result = await db.execute(stmt)
        user = result.scalar_one_or_none()

        # 2. 验证凭证（统一返回相同错误消息，防止用户名枚举攻击）
        if user is None or not _security.verify_password(password, user.hashed_password):
            raise AuthenticationError("用户名或密码错误")

        # 3. 校验账户状态
        if not user.is_active:
            raise AuthenticationError("用户账户已被禁用")

        # 4. 签发 token 对
        access_token = _security.create_access_token(
            sub=str(user.id),
            membership=user.membership,
        )
        refresh_token = _security.create_refresh_token(sub=str(user.id))

        return access_token, refresh_token

    async def refresh_access_token(
        self, db: AsyncSession, refresh_token: str
    ) -> str:
        """刷新 access_token。

        步骤：
          1. 校验 refresh_token 类型（type="refresh"）和有效性
          2. 从 DB 查询用户获取最新 membership
          3. 签发新 access_token

        Args:
            db: 异步数据库 session
            refresh_token: 客户端提交的 refresh_token 字符串

        Returns:
            新的 access_token 字符串

        Raises:
            AuthenticationError: token 无效、过期或 type 不匹配（code=1001）
        """
        # 1. 校验 refresh_token（decode_token 会检查 type="refresh"）
        payload = _security.decode_token(refresh_token, expected_type="refresh")
        user_id_str: str = payload.get("sub", "")

        try:
            user_id = int(user_id_str)
        except (ValueError, TypeError):
            raise AuthenticationError("token sub 字段无效")

        # 2. 从 DB 获取最新用户状态（不信任 JWT claims）
        user = await db.get(User, user_id)
        if user is None or not user.is_active:
            raise AuthenticationError("用户不存在或已被禁用")

        # 3. 签发新 access_token（使用 DB 中最新的 membership）
        new_access_token = _security.create_access_token(
            sub=str(user.id),
            membership=user.membership,
        )
        return new_access_token
