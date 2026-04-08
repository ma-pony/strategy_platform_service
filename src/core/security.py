"""JWT 安全工具与密码哈希工具。

提供 SecurityUtils 类，封装：
  - JWT access_token / refresh_token 的签发与校验
  - bcrypt 密码哈希与验证

安全约定：
  - 密钥从环境变量 SECRET_KEY 注入，禁止硬编码
  - 密码校验仅比较哈希，禁止在任何日志中记录明文密码
  - decode_token 默认校验 type="access"，防止 refresh_token 被误用于接口调用
"""

from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
import jwt
from jwt import PyJWTError

from src.core.app_settings import get_settings
from src.core.enums import MembershipTier
from src.core.exceptions import AuthenticationError

# JWT 算法
_ALGORITHM = "HS256"

# Token 有效期
_ACCESS_TOKEN_EXPIRE_MINUTES = 30
_REFRESH_TOKEN_EXPIRE_DAYS = 7


class SecurityUtils:
    """JWT 签发/校验与 bcrypt 密码工具。

    通过依赖注入 settings 获取密钥，不在类内缓存 secret_key
    （支持测试时动态替换环境变量）。
    """

    def _get_secret_key(self) -> str:
        return get_settings().secret_key

    def create_access_token(self, sub: str, membership: MembershipTier) -> str:
        """签发 access_token，有效期 30 分钟。

        JWT claims 包含：sub、membership、exp、iat、type="access"。
        """
        now = datetime.now(timezone.utc)
        expire = now + timedelta(minutes=_ACCESS_TOKEN_EXPIRE_MINUTES)
        payload: dict[str, Any] = {
            "sub": sub,
            "membership": membership.value,
            "exp": expire,
            "iat": now,
            "type": "access",
        }
        return jwt.encode(payload, self._get_secret_key(), algorithm=_ALGORITHM)

    def create_refresh_token(self, sub: str) -> str:
        """签发 refresh_token，有效期 7 天。

        JWT claims 包含：sub、exp、iat、type="refresh"。
        refresh_token 不含 membership，不可用于接口鉴权。
        """
        now = datetime.now(timezone.utc)
        expire = now + timedelta(days=_REFRESH_TOKEN_EXPIRE_DAYS)
        payload: dict[str, Any] = {
            "sub": sub,
            "exp": expire,
            "iat": now,
            "type": "refresh",
        }
        return jwt.encode(payload, self._get_secret_key(), algorithm=_ALGORITHM)

    def decode_token(self, token: str, expected_type: str = "access") -> dict[str, Any]:
        """校验并解码 JWT token。

        校验项：
          1. 签名有效性（密钥匹配）
          2. 过期时间（exp 字段）
          3. type 字段（防止 refresh_token 被用于接口调用）

        Args:
            token: JWT 字符串
            expected_type: 期望的 token 类型，默认 "access"

        Returns:
            解码后的 payload dict

        Raises:
            AuthenticationError: 签名无效、token 过期或 type 不匹配
        """
        try:
            payload: dict[str, Any] = jwt.decode(
                token,
                self._get_secret_key(),
                algorithms=[_ALGORITHM],
            )
        except PyJWTError:
            raise AuthenticationError("token 无效或已过期") from None

        if payload.get("type") != expected_type:
            raise AuthenticationError(f"token 类型错误，期望 {expected_type}，实际 {payload.get('type')}")

        return payload

    def hash_password(self, plain: str) -> str:
        """使用 bcrypt 哈希明文密码，返回哈希字符串。

        禁止在任何日志中记录 plain 参数。
        """
        hashed_bytes = bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt())
        return hashed_bytes.decode("utf-8")

    def verify_password(self, plain: str, hashed: str) -> bool:
        """校验明文密码与 bcrypt 哈希是否匹配。

        返回 True（匹配）或 False（不匹配），禁止记录 plain 参数。
        """
        try:
            return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
        except Exception:
            return False
