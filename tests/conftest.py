"""pytest 全局 fixtures。

提供可跨所有测试文件复用的无状态 fixtures，消除各文件重复的
env_setup / app / client / mock_db 定义模式。

设计约束：
  - 所有 fixture 均不依赖全局状态，通过 monkeypatch 和 lru_cache 清除实现隔离
  - env_setup 必须在 FastAPI 应用创建前调用，以确保 settings 正确注入
  - token_factory 按 MembershipTier 枚举生成有效 JWT，固定 user_id 映射
"""

import os
from collections.abc import AsyncGenerator, Callable, Generator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from config import settings_factory

# 共享测试密钥（供 token_factory 使用，与 env_setup 保持一致）
_TEST_SECRET_KEY = "test-secret-key-for-shared-conftest-256bits!!"

# MembershipTier → 固定 user_id 映射（匿名=None，Free=1，VIP1=2，VIP2=3）
_TIER_USER_ID_MAP = {
    "free": "1",
    "vip1": "2",
    "vip2": "3",
}


@pytest.fixture(autouse=False)
def clear_settings_cache() -> Generator[None, None, None]:
    """在每个测试前后清除 settings_factory 的 lru_cache，确保测试间隔离。"""
    settings_factory.cache_clear()
    # 清理可能影响测试的环境变量
    _saved = {k: os.environ.get(k) for k in ("APP_ENV", "LOG_LEVEL", "APP_NAME")}
    yield  # type: ignore[misc]
    settings_factory.cache_clear()
    # 恢复环境变量
    for k, v in _saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


@pytest.fixture()
def env_setup(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    """注入测试环境变量并清除 settings lru_cache，确保测试间隔离。

    注入的值：
      - SECRET_KEY：固定测试密钥
      - DATABASE_URL：asyncpg 格式测试 URL（不连接真实数据库）
      - DATABASE_SYNC_URL：psycopg2 格式测试 URL
      - REDIS_URL：测试 Redis URL（不连接真实 Redis）

    退出时 monkeypatch 自动恢复环境变量，并手动清除 get_settings 缓存。
    """
    monkeypatch.setenv("SECRET_KEY", _TEST_SECRET_KEY)
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/testdb")
    monkeypatch.setenv("DATABASE_SYNC_URL", "postgresql+psycopg2://u:p@localhost/testdb")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/15")

    from src.core import app_settings

    app_settings.get_settings.cache_clear()
    yield
    app_settings.get_settings.cache_clear()


@pytest.fixture()
def app(env_setup: None) -> FastAPI:
    """创建并返回隔离的 FastAPI 应用实例（function 作用域，确保测试间隔离）。

    依赖 env_setup 确保环境变量在 create_app() 前已注入。
    create_app() 延迟导入，避免模块级 get_settings() 调用使用错误配置。
    """
    from src.api.main_router import create_app

    return create_app()


@pytest.fixture()
async def async_client(app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    """提供绑定测试应用的异步 HTTP 客户端（ASGITransport，无真实网络端口）。

    使用 async with 上下文管理确保连接正确关闭（需求 8.2）。
    """
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac


@pytest.fixture()
def token_factory(env_setup: None) -> Callable[..., str]:
    """令牌工厂 fixture：按 MembershipTier 枚举签发有效 JWT（需求 8.4）。

    固定 user_id 映射：
      - MembershipTier.FREE  → sub="1"
      - MembershipTier.VIP1  → sub="2"
      - MembershipTier.VIP2  → sub="3"

    内部调用 SecurityUtils().create_access_token()，使用 env_setup 注入的
    SECRET_KEY 签名，确保与应用层校验逻辑一致。

    Returns:
        callable: 接受 MembershipTier 参数，返回已签名 JWT 字符串
    """
    from src.core.enums import MembershipTier
    from src.core.security import SecurityUtils

    security = SecurityUtils()

    def _factory(tier: MembershipTier) -> str:
        user_id = _TIER_USER_ID_MAP.get(tier.value, "1")
        return security.create_access_token(sub=user_id, membership=tier)

    return _factory


@pytest.fixture()
def mock_db() -> AsyncMock:
    """预配置的 AsyncMock 数据库 session（需求 8.3）。

    提供常用方法的 AsyncMock 配置，作为 app.dependency_overrides[get_db]
    的覆盖项使用。

    预配置方法：
      - add：MagicMock（同步，SQLAlchemy session.add 为同步）
      - commit：AsyncMock（可 await）
      - refresh：AsyncMock（可 await）
      - execute：AsyncMock（可 await，返回值需按需配置）
      - get：AsyncMock（可 await）
    """
    db: AsyncMock = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.execute = AsyncMock()
    db.get = AsyncMock()
    return db
