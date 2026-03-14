"""平台核心应用配置。

通过 pydantic-settings 从环境变量加载，所有敏感配置禁止硬编码。
必填字段：SECRET_KEY、DATABASE_URL、DATABASE_SYNC_URL、REDIS_URL。
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    """应用核心配置，从环境变量读取。

    敏感字段（SECRET_KEY 等）无默认值，缺失时 pydantic 抛出 ValidationError。
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # 必填：安全配置
    secret_key: str

    # 必填：数据库配置
    database_url: str  # asyncpg 驱动，用于 Web 请求路径
    database_sync_url: str  # psycopg2 驱动，用于 sqladmin / Alembic

    # 必填：Redis 配置
    redis_url: str

    # 可选：应用配置
    app_env: str = "development"
    debug: bool = False
    log_level: str = "INFO"

    # 数据库连接池配置
    db_pool_size: int = 10
    db_max_overflow: int = 20

    # 信号生成配置
    signal_max_workers: int = 2  # ProcessPoolExecutor 最大并发进程数
    signal_refresh_interval: int = 5  # 信号刷新周期（分钟），默认 5 分钟

    # freqtrade 回测配置
    freqtrade_datadir: str = "/tmp/freqtrade_data"  # OHLCV 数据目录


@lru_cache(maxsize=1)
def get_settings() -> AppSettings:
    """返回 AppSettings 单例，lru_cache 保证进程内唯一实例。

    缺失必填字段时抛出 pydantic ValidationError。
    """
    return AppSettings()
