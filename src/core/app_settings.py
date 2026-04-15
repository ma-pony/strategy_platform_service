"""平台核心应用配置。

通过 pydantic-settings 从环境变量加载，所有敏感配置禁止硬编码。
必填字段：SECRET_KEY、DATABASE_URL、DATABASE_SYNC_URL、REDIS_URL。
"""

import json
from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# 默认信号生成覆盖交易对（10 个主流交易对）
_DEFAULT_SIGNAL_PAIRS = [
    "BTC/USDT",
    "ETH/USDT",
    "BNB/USDT",
    "SOL/USDT",
    "XRP/USDT",
    "ADA/USDT",
    "DOGE/USDT",
    "AVAX/USDT",
    "DOT/USDT",
    "MATIC/USDT",
]


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

    # 服务间调用 API Key（用于外部服务写入研报等管理接口）
    internal_api_key: str = ""

    # 可信反向代理 CIDR 白名单 — 仅当 request.client.host 落在其中时才信任 X-Forwarded-For
    # 默认包含 Docker/K8s 私网段及环回；生产部署路径 OpenResty (10.255.0.1) → 本服务 都在 10.0.0.0/8
    trusted_proxy_cidrs: list[str] = ["127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"]

    # 可选：应用配置
    app_env: str = "development"
    debug: bool = False
    log_level: str = "INFO"

    # 数据库连接池配置
    db_pool_size: int = 10
    db_max_overflow: int = 20

    # 信号生成配置（旧）
    signal_max_workers: int = 2  # ProcessPoolExecutor 最大并发进程数
    signal_refresh_interval: int = 5  # 信号刷新周期（分钟），默认 5 分钟

    # freqtrade OHLCV 数据目录（持久化路径，需求 1.7）
    # 旧配置项保留用于回测，新实时信号流水线使用 freqtrade_datadir（Path 类型）
    freqtrade_datadir: Path = Path("/opt/freqtrade_data")  # 持久化 OHLCV 数据目录

    # 实时信号调度配置（需求 5.1）
    signal_refresh_interval_cron: str = "0 * * * *"  # crontab 表达式，默认每小时整点

    # 实时信号覆盖范围配置（需求 2.8）
    signal_pairs: list[str] = _DEFAULT_SIGNAL_PAIRS  # type: ignore[assignment]
    signal_timeframes: list[str] = ["1d"]  # type: ignore[assignment]  # 所有策略均为 1d 周期

    @field_validator("trusted_proxy_cidrs", mode="before")
    @classmethod
    def parse_cidr_list(cls, v: object) -> object:
        """支持环境变量以 JSON 列表或逗号分隔字符串传入 CIDR 列表。"""
        if isinstance(v, str):
            try:
                parsed = json.loads(v)
                if isinstance(parsed, list):
                    return parsed
            except (json.JSONDecodeError, ValueError):
                pass
            return [s.strip() for s in v.split(",") if s.strip()]
        return v

    @field_validator("signal_pairs", "signal_timeframes", mode="before")
    @classmethod
    def parse_json_list(cls, v: object) -> object:
        """支持环境变量以 JSON 字符串形式传入列表。

        例如：SIGNAL_PAIRS='["BTC/USDT","ETH/USDT"]'
        """
        if isinstance(v, str):
            try:
                parsed = json.loads(v)
                if isinstance(parsed, list):
                    return parsed
            except (json.JSONDecodeError, ValueError):
                pass
        return v


@lru_cache(maxsize=1)
def get_settings() -> AppSettings:
    """返回 AppSettings 单例，lru_cache 保证进程内唯一实例。

    缺失必填字段时抛出 pydantic ValidationError。
    """
    return AppSettings()
