"""Celery Worker 层 Redis 客户端工厂。

提供同步 Redis 客户端，用于信号缓存读写。
与 FastAPI 层的 Redis 客户端分开管理，供 Celery Worker 使用。
"""

from functools import lru_cache

import redis as redis_lib

from src.core.app_settings import get_settings


@lru_cache(maxsize=1)
def get_redis_client() -> redis_lib.Redis:
    """返回同步 Redis 客户端单例（连接池复用）。"""
    settings = get_settings()
    return redis_lib.from_url(
        settings.redis_url,
        decode_responses=True,
    )
