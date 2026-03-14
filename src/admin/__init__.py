"""sqladmin 管理后台初始化模块（任务 11.3）。

提供 setup_admin() 函数：
  - 创建独立同步 SQLAlchemy engine（psycopg2 驱动，pool_size=5）
  - 初始化 Admin 实例，注册 UserAdmin、StrategyAdmin、ReportAdmin 三个视图
  - 挂载至 FastAPI app 的 /admin 路径

关键约束：
  - 使用独立同步 engine，不复用 Web 层的异步 engine
  - sqladmin 不支持异步 session，必须使用同步 engine
  - AdminAuth 与普通用户 JWT 体系完全隔离
"""

from fastapi import FastAPI
from sqladmin import Admin
from sqlalchemy.engine import Engine

from src.admin.auth import AdminAuth
from src.admin.views import ReportAdmin, StrategyAdmin, UserAdmin


def setup_admin(app: FastAPI, sync_engine: Engine) -> None:
    """注册 sqladmin Admin 实例和所有 ModelView，挂载至 FastAPI app。

    使用独立同步 SQLAlchemy engine（psycopg2 驱动），不复用 Web 层的异步 engine。
    AdminAuth 提供独立管理员认证，与普通用户 JWT 体系完全隔离。
    未认证请求访问 /admin 时自动重定向至 /admin/login。

    Args:
        app: FastAPI 应用实例
        sync_engine: 同步 SQLAlchemy engine（psycopg2 驱动）
    """
    # 从配置读取 secret_key（用于 Session 签名）
    from src.core.app_settings import get_settings

    settings = get_settings()

    # 创建独立管理员认证后端
    auth_backend = AdminAuth(secret_key=settings.secret_key)

    # 初始化 Admin 实例
    admin = Admin(
        app,
        engine=sync_engine,
        authentication_backend=auth_backend,
        title="量化平台管理后台",
        base_url="/admin",
    )

    # 注册三个 ModelView
    admin.add_view(UserAdmin)
    admin.add_view(StrategyAdmin)
    admin.add_view(ReportAdmin)
