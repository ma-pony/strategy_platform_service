"""枚举类型与基础配置单元测试。

测试 MembershipTier、TaskStatus、SignalDirection 枚举，
以及 pydantic-settings 配置加载逻辑。
"""

import pytest


class TestMembershipTier:
    """MembershipTier 枚举测试。"""

    def test_enum_values_exist(self) -> None:
        from src.core.enums import MembershipTier

        assert MembershipTier.FREE == "free"
        assert MembershipTier.VIP1 == "vip1"
        assert MembershipTier.VIP2 == "vip2"

    def test_enum_is_string_type(self) -> None:
        from src.core.enums import MembershipTier

        assert isinstance(MembershipTier.FREE, str)
        assert isinstance(MembershipTier.VIP1, str)
        assert isinstance(MembershipTier.VIP2, str)

    def test_enum_members_count(self) -> None:
        from src.core.enums import MembershipTier

        assert len(MembershipTier) == 3


class TestTaskStatus:
    """TaskStatus 枚举测试。"""

    def test_enum_values_exist(self) -> None:
        from src.core.enums import TaskStatus

        assert TaskStatus.PENDING == "pending"
        assert TaskStatus.RUNNING == "running"
        assert TaskStatus.DONE == "done"
        assert TaskStatus.FAILED == "failed"

    def test_enum_is_string_type(self) -> None:
        from src.core.enums import TaskStatus

        assert isinstance(TaskStatus.PENDING, str)

    def test_enum_members_count(self) -> None:
        from src.core.enums import TaskStatus

        assert len(TaskStatus) == 4


class TestSignalDirection:
    """SignalDirection 枚举测试。"""

    def test_enum_values_exist(self) -> None:
        from src.core.enums import SignalDirection

        assert SignalDirection.BUY == "buy"
        assert SignalDirection.SELL == "sell"
        assert SignalDirection.HOLD == "hold"

    def test_enum_is_string_type(self) -> None:
        from src.core.enums import SignalDirection

        assert isinstance(SignalDirection.BUY, str)

    def test_enum_members_count(self) -> None:
        from src.core.enums import SignalDirection

        assert len(SignalDirection) == 3


class TestAppSettings:
    """应用配置 pydantic-settings 测试。"""

    def test_settings_loads_secret_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """SECRET_KEY 能从环境变量正确读取。"""
        monkeypatch.setenv("SECRET_KEY", "test-secret-key-value")
        monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/db")
        monkeypatch.setenv("DATABASE_SYNC_URL", "postgresql+psycopg2://user:pass@localhost/db")
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")

        # 清除 lru_cache 以确保重新加载
        from src.core import app_settings

        app_settings.get_settings.cache_clear()
        settings = app_settings.get_settings()
        assert settings.secret_key == "test-secret-key-value"

    def test_settings_loads_database_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """DATABASE_URL 能从环境变量正确读取。"""
        monkeypatch.setenv("SECRET_KEY", "test-secret-key-value")
        monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/testdb")
        monkeypatch.setenv("DATABASE_SYNC_URL", "postgresql+psycopg2://user:pass@localhost/testdb")
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")

        from src.core import app_settings

        app_settings.get_settings.cache_clear()
        settings = app_settings.get_settings()
        assert "testdb" in settings.database_url

    def test_settings_loads_redis_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """REDIS_URL 能从环境变量正确读取。"""
        monkeypatch.setenv("SECRET_KEY", "test-secret-key-value")
        monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/db")
        monkeypatch.setenv("DATABASE_SYNC_URL", "postgresql+psycopg2://user:pass@localhost/db")
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/2")

        from src.core import app_settings

        app_settings.get_settings.cache_clear()
        settings = app_settings.get_settings()
        assert settings.redis_url == "redis://localhost:6379/2"

    def test_settings_no_hardcoded_secret(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """SECRET_KEY 必须通过环境变量注入，缺失时应抛出校验异常。"""
        monkeypatch.delenv("SECRET_KEY", raising=False)
        monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/db")
        monkeypatch.setenv("DATABASE_SYNC_URL", "postgresql+psycopg2://user:pass@localhost/db")
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")

        from src.core.app_settings import AppSettings

        # 禁用 .env 文件读取，确保仅从环境变量加载
        with pytest.raises(Exception):  # noqa: B017
            AppSettings(_env_file=None)
