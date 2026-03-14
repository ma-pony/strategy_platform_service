"""pytest 全局 fixtures。"""

import os

from collections.abc import Generator

import pytest

from config import settings_factory


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
