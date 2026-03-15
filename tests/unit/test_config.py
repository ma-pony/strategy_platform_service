"""ConfigModule 单元测试。"""

import os

import pytest
from pydantic import ValidationError

from config import Settings, settings_factory


class TestSettingsFactory:
    """测试 settings_factory 工厂函数。"""

    def test_settings_dev_default(self, clear_settings_cache: None) -> None:
        """APP_ENV 未设置时默认返回 DevSettings，debug=True。"""
        os.environ.pop("APP_ENV", None)
        settings = settings_factory()
        assert settings.app_env == "development"
        assert settings.debug is True

    def test_settings_dev_explicit(self, clear_settings_cache: None) -> None:
        """APP_ENV=development 时返回 DevSettings。"""
        os.environ["APP_ENV"] = "development"
        settings = settings_factory()
        assert settings.app_env == "development"
        assert settings.debug is True

    def test_settings_prod(self, clear_settings_cache: None) -> None:
        """APP_ENV=production 时返回 ProdSettings，debug=False。"""
        os.environ["APP_ENV"] = "production"
        settings = settings_factory()
        assert settings.app_env == "production"
        assert settings.debug is False

    def test_settings_test_env(self, clear_settings_cache: None) -> None:
        """APP_ENV=test 时返回 TestSettings，debug=True。"""
        os.environ["APP_ENV"] = "test"
        settings = settings_factory()
        assert settings.app_env == "test"
        assert settings.debug is True

    def test_settings_cache_returns_same_instance(self, clear_settings_cache: None) -> None:
        """两次调用 settings_factory() 返回同一实例（lru_cache 验证）。"""
        os.environ.pop("APP_ENV", None)
        s1 = settings_factory()
        s2 = settings_factory()
        assert s1 is s2

    def test_settings_invalid_app_env(self, clear_settings_cache: None) -> None:
        """非法 APP_ENV 值触发 ValidationError。"""
        os.environ["APP_ENV"] = "invalid_env"
        with pytest.raises(ValidationError):
            settings_factory()

    def test_settings_default_log_level(self, clear_settings_cache: None) -> None:
        """默认日志级别为 INFO。"""
        os.environ.pop("APP_ENV", None)
        os.environ.pop("LOG_LEVEL", None)
        settings = settings_factory()
        assert settings.log_level == "INFO"

    def test_settings_default_app_name(self, clear_settings_cache: None) -> None:
        """默认 app_name 为 strategy_platform_service。"""
        os.environ.pop("APP_ENV", None)
        settings = settings_factory()
        assert settings.app_name == "strategy_platform_service"

    def test_settings_type_alias(self, clear_settings_cache: None) -> None:
        """settings_factory 返回值符合 Settings 类型。"""
        os.environ.pop("APP_ENV", None)
        settings = settings_factory()
        assert isinstance(settings, Settings.__args__)  # type: ignore[attr-defined]


class TestSettingsExport:
    """测试 config 包的导出接口。"""

    def test_import_settings_factory(self) -> None:
        """config 包应导出 settings_factory。"""
        from config import settings_factory as sf

        assert callable(sf)

    def test_import_settings_type(self) -> None:
        """config 包应导出 Settings 类型。"""
        from config import Settings

        assert Settings is not None
