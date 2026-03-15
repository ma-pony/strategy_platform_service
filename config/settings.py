"""多环境配置加载模块。"""

import os
from functools import lru_cache
from typing import Literal, Union

from pydantic_settings import BaseSettings, SettingsConfigDict

AppEnv = Literal["development", "test", "production"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]


class BaseAppSettings(BaseSettings):
    """所有环境配置的基类。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: AppEnv = "development"
    log_level: LogLevel = "INFO"
    app_name: str = "strategy_platform_service"


class DevSettings(BaseAppSettings):
    """开发环境配置。"""

    app_env: AppEnv = "development"
    debug: bool = True


class TestSettings(BaseAppSettings):
    """测试环境配置。"""

    app_env: AppEnv = "test"
    debug: bool = True


class ProdSettings(BaseAppSettings):
    """生产环境配置。"""

    app_env: AppEnv = "production"
    debug: bool = False


Settings = Union[DevSettings, TestSettings, ProdSettings]


@lru_cache(maxsize=1)
def settings_factory() -> Settings:
    """根据 APP_ENV 返回对应的 Settings 实例。

    缺失必填字段或非法 APP_ENV 时抛出 ValidationError。
    使用 lru_cache 保证进程内单例。
    """
    env = os.environ.get("APP_ENV", "development")
    if env == "production":
        return ProdSettings()
    if env == "test":
        return TestSettings()
    # development 或未知值均通过 Pydantic 校验捕获
    return DevSettings(app_env=env)  # type: ignore[arg-type]
