"""任务 1.1 单元测试：实时信号配置扩展。

验证 AppSettings 新增的 FREQTRADE_DATADIR、SIGNAL_REFRESH_INTERVAL、
SIGNAL_PAIRS、SIGNAL_TIMEFRAMES 四个配置项。
"""

from pathlib import Path

import pytest


class TestSignalConfigExtension:
    """测试实时信号相关配置项的默认值和环境变量覆盖。"""

    def test_freqtrade_datadir_default(self, env_setup: None) -> None:
        """FREQTRADE_DATADIR 默认值为 /opt/freqtrade_data（持久化路径）。"""
        from src.core.app_settings import AppSettings

        settings = AppSettings()
        # 默认值应为 /opt/freqtrade_data（需求 1.7）
        assert str(settings.freqtrade_datadir) == "/opt/freqtrade_data"

    def test_freqtrade_datadir_returns_path_type(self, env_setup: None) -> None:
        """freqtrade_datadir 应返回 Path 类型以支持路径操作。"""
        from src.core.app_settings import AppSettings

        settings = AppSettings()
        assert isinstance(settings.freqtrade_datadir, Path)

    def test_freqtrade_datadir_env_override(self, env_setup: None, monkeypatch: pytest.MonkeyPatch) -> None:
        """FREQTRADE_DATADIR 环境变量可覆盖默认值。"""
        monkeypatch.setenv("FREQTRADE_DATADIR", "/custom/data/path")
        from src.core import app_settings

        app_settings.get_settings.cache_clear()
        try:
            from src.core.app_settings import AppSettings

            settings = AppSettings()
            assert str(settings.freqtrade_datadir) == "/custom/data/path"
        finally:
            app_settings.get_settings.cache_clear()

    def test_signal_refresh_interval_default(self, env_setup: None) -> None:
        """SIGNAL_REFRESH_INTERVAL 默认值为 '0 * * * *'（每小时）。"""
        from src.core.app_settings import AppSettings

        settings = AppSettings()
        assert settings.signal_refresh_interval_cron == "0 * * * *"

    def test_signal_refresh_interval_env_override(self, env_setup: None, monkeypatch: pytest.MonkeyPatch) -> None:
        """SIGNAL_REFRESH_INTERVAL 支持环境变量覆盖（需求 5.1）。"""
        monkeypatch.setenv("SIGNAL_REFRESH_INTERVAL_CRON", "*/30 * * * *")
        from src.core import app_settings

        app_settings.get_settings.cache_clear()
        try:
            from src.core.app_settings import AppSettings

            settings = AppSettings()
            assert settings.signal_refresh_interval_cron == "*/30 * * * *"
        finally:
            app_settings.get_settings.cache_clear()

    def test_signal_pairs_default(self, env_setup: None) -> None:
        """SIGNAL_PAIRS 默认包含 10 个主流交易对。"""
        from src.core.app_settings import AppSettings

        settings = AppSettings()
        assert isinstance(settings.signal_pairs, list)
        assert len(settings.signal_pairs) == 10
        assert "BTC/USDT" in settings.signal_pairs
        assert "ETH/USDT" in settings.signal_pairs

    def test_signal_timeframes_default(self, env_setup: None) -> None:
        """SIGNAL_TIMEFRAMES 默认值为 ['1d']（所有策略均为 1d 周期）。"""
        from src.core.app_settings import AppSettings

        settings = AppSettings()
        assert isinstance(settings.signal_timeframes, list)
        assert settings.signal_timeframes == ["1d"]

    def test_settings_backward_compatible(self, env_setup: None) -> None:
        """新增配置项不影响原有配置项（向后兼容）。"""
        from src.core.app_settings import AppSettings

        settings = AppSettings()
        # 原有配置项仍正常访问
        assert settings.secret_key == "test-secret-key-for-shared-conftest-256bits!!"  # pragma: allowlist secret
        assert settings.redis_url == "redis://localhost:6379/15"
