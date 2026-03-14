"""管理员认证后端（任务 11.1）。

实现独立的 AdminAuth 认证后端（AuthenticationBackend），与普通用户 JWT 体系完全隔离：
  - 管理员账户独立于普通用户表（通过环境变量或配置管理）
  - 使用 Session cookie 机制，与普通用户 JWT 体系完全隔离
  - 未认证请求访问 /admin 路径时自动重定向至 /admin/login

安全约束：
  - 管理员凭证通过环境变量注入（ADMIN_USERNAME / ADMIN_PASSWORD）
  - 不与 User 表共用认证逻辑
  - session token 使用简单标识符，由 starlette session 中间件管理
"""

import os

from sqladmin.authentication import AuthenticationBackend
from starlette.requests import Request


class AdminAuth(AuthenticationBackend):
    """sqladmin 独立管理员认证后端。

    管理员账户完全独立于普通用户表，使用环境变量配置凭证。
    Session cookie 机制由 starlette SessionMiddleware 管理。

    Args:
        secret_key: Session 签名密钥
        admin_username: 管理员用户名（默认从 ADMIN_USERNAME 环境变量读取）
        admin_password: 管理员密码（默认从 ADMIN_PASSWORD 环境变量读取）
    """

    def __init__(
        self,
        secret_key: str,
        admin_username: str | None = None,
        admin_password: str | None = None,
    ) -> None:
        super().__init__(secret_key=secret_key)
        # 优先使用传入参数，否则从环境变量读取
        self._admin_username = admin_username or os.environ.get(
            "ADMIN_USERNAME", "admin"
        )
        self._admin_password = admin_password or os.environ.get(
            "ADMIN_PASSWORD", "admin"
        )

    async def login(self, request: Request) -> bool:
        """验证管理员凭证并在成功时设置 session token。

        Args:
            request: 包含 form 数据（username, password）的请求对象

        Returns:
            True 表示认证成功，False 表示失败
        """
        form = await request.form()
        username = form.get("username", "")
        password = form.get("password", "")

        if username == self._admin_username and password == self._admin_password:
            # 认证成功，在 session 中设置 token 标识
            request.session["admin_token"] = "authenticated"
            return True

        return False

    async def logout(self, request: Request) -> bool:
        """清除管理员 session。

        Args:
            request: 当前请求对象

        Returns:
            始终返回 True
        """
        request.session.pop("admin_token", None)
        return True

    async def authenticate(self, request: Request) -> bool:
        """校验请求是否已认证（session 中是否有有效 token）。

        Args:
            request: 当前请求对象

        Returns:
            True 表示已认证，False 表示未认证（将重定向至登录页）
        """
        return "admin_token" in request.session
