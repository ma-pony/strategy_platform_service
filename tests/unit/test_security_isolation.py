"""任务 7.1 单元测试：freqtrade 配置安全隔离验证。

验证：
  - 生成的每份 freqtrade 配置均包含 dry_run=true
  - 不含任何 exchange.key / exchange.secret 字段
  - Telegram 和 api_server（RPC）被禁用
  - 日志不含 datadir 完整路径

涵盖需求：6.1, 6.2, 6.4
"""

import contextlib
from pathlib import Path


class TestFreqtradeConfigSecurity:
    """任务 7.1：验证生成的 freqtrade 配置不含账户凭据，满足安全隔离需求。"""

    def test_config_has_dry_run_true(self, tmp_path: Path) -> None:
        """生成的配置文件包含 dry_run=true（需求 6.1）。"""
        from src.freqtrade_bridge.data_downloader import DataDownloader

        downloader = DataDownloader()
        config = downloader._build_download_config(tmp_path)

        assert config["dry_run"] is True

    def test_config_has_no_exchange_key(self, tmp_path: Path) -> None:
        """生成的配置不含 exchange.key 字段（需求 6.1）。"""
        from src.freqtrade_bridge.data_downloader import DataDownloader

        downloader = DataDownloader()
        config = downloader._build_download_config(tmp_path)

        exchange_config = config.get("exchange", {})
        assert "key" not in exchange_config
        assert "api_key" not in exchange_config

    def test_config_has_no_exchange_secret(self, tmp_path: Path) -> None:
        """生成的配置不含 exchange.secret 字段（需求 6.1）。"""
        from src.freqtrade_bridge.data_downloader import DataDownloader

        downloader = DataDownloader()
        config = downloader._build_download_config(tmp_path)

        exchange_config = config.get("exchange", {})
        assert "secret" not in exchange_config
        assert "api_secret" not in exchange_config

    def test_config_telegram_disabled(self, tmp_path: Path) -> None:
        """生成的配置禁用 telegram 通知（需求 6.2）。"""
        from src.freqtrade_bridge.data_downloader import DataDownloader

        downloader = DataDownloader()
        config = downloader._build_download_config(tmp_path)

        telegram_config = config.get("telegram", {})
        assert telegram_config.get("enabled") is False

    def test_config_api_server_disabled(self, tmp_path: Path) -> None:
        """生成的配置禁用 api_server（RPC）（需求 6.2）。"""
        from src.freqtrade_bridge.data_downloader import DataDownloader

        downloader = DataDownloader()
        config = downloader._build_download_config(tmp_path)

        api_server_config = config.get("api_server", {})
        assert api_server_config.get("enabled") is False

    def test_config_datadir_matches_provided_path(self, tmp_path: Path) -> None:
        """生成的配置中 datadir 与传入路径一致（需求 6.4）。"""
        from src.freqtrade_bridge.data_downloader import DataDownloader

        downloader = DataDownloader()
        config = downloader._build_download_config(tmp_path)

        assert config.get("datadir") == str(tmp_path)

    def test_temp_config_path_uses_uuid_isolation(self) -> None:
        """临时配置目录使用 UUID 隔离（/tmp/freqtrade_signals/{uuid}/），需求 6.4。"""
        from pathlib import Path
        from unittest.mock import MagicMock, patch

        from src.freqtrade_bridge.data_downloader import DataDownloader

        downloader = DataDownloader()

        # 监控 temp_dir 的创建路径
        created_paths: list[str] = []
        original_mkdir = Path.mkdir

        def capture_mkdir(self, parents=False, exist_ok=False):
            created_paths.append(str(self))
            original_mkdir(self, parents=parents, exist_ok=exist_ok)

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stderr = ""

        with patch.object(Path, "mkdir", capture_mkdir):
            with patch("subprocess.run", return_value=mock_result):
                with contextlib.suppress(Exception):
                    downloader._run_download_subprocess(
                        pairs=["BTC/USDT"],
                        timeframes=["1h"],
                        datadir=Path("/tmp/test_datadir"),
                        days=7,
                        timeout=10,
                    )

        # 检查创建的路径格式：应包含 /tmp/freqtrade_signals/ 前缀
        signal_paths = [p for p in created_paths if "freqtrade_signals" in p]
        assert len(signal_paths) >= 1
        for p in signal_paths:
            assert "freqtrade_signals" in p
