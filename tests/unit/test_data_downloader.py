"""任务 8.1 / 2.1-2.3 单元测试：DataDownloader 组件。

测试新鲜度检查、子进程调用、降级逻辑等核心路径。

涵盖需求：1.2, 1.3, 1.6, 1.9
"""

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


class TestDataFreshness:
    """任务 2.1：测试新鲜度检查逻辑（_is_data_fresh）。"""

    def test_data_is_fresh_within_current_period(self, tmp_path: Path) -> None:
        """数据在当前 1h 周期内时，_is_data_fresh 返回 True（跳过下载）。"""
        import datetime

        from src.freqtrade_bridge.data_downloader import DataDownloader

        # 创建模拟数据文件（pair=BTC/USDT, timeframe=1h）
        datadir = tmp_path / "data" / "binance"
        datadir.mkdir(parents=True)

        # 文件名格式：BTC_USDT-1h-futures.json
        data_file = datadir / "BTC_USDT-1h-futures.json"

        # 构造最后一根 K 线时间戳为 30 分钟前（在当前 1h 周期内）
        now = datetime.datetime.now(tz=datetime.timezone.utc)
        last_candle_ts = int((now - datetime.timedelta(minutes=30)).timestamp() * 1000)

        # freqtrade OHLCV 格式：[timestamp, open, high, low, close, volume]
        data = [[last_candle_ts, 50000.0, 51000.0, 49000.0, 50500.0, 100.0]]
        data_file.write_text(json.dumps(data))

        downloader = DataDownloader()
        result = downloader._is_data_fresh(tmp_path, "BTC/USDT", "1h")
        assert result is True

    def test_data_is_stale_exceeds_period(self, tmp_path: Path) -> None:
        """数据超过 1h 周期时，_is_data_fresh 返回 False（触发下载）。"""
        import datetime

        from src.freqtrade_bridge.data_downloader import DataDownloader

        datadir = tmp_path / "data" / "binance"
        datadir.mkdir(parents=True)
        data_file = datadir / "BTC_USDT-1h-futures.json"

        # 最后一根 K 线为 2 小时前（超过 1h 周期）
        now = datetime.datetime.now(tz=datetime.timezone.utc)
        last_candle_ts = int((now - datetime.timedelta(hours=2)).timestamp() * 1000)

        data = [[last_candle_ts, 50000.0, 51000.0, 49000.0, 50500.0, 100.0]]
        data_file.write_text(json.dumps(data))

        downloader = DataDownloader()
        result = downloader._is_data_fresh(tmp_path, "BTC/USDT", "1h")
        assert result is False

    def test_file_not_exist_returns_false(self, tmp_path: Path) -> None:
        """文件不存在时，_is_data_fresh 返回 False（触发下载）。"""
        from src.freqtrade_bridge.data_downloader import DataDownloader

        downloader = DataDownloader()
        # 不创建任何数据文件
        result = downloader._is_data_fresh(tmp_path, "BTC/USDT", "1h")
        assert result is False

    def test_corrupted_file_returns_false(self, tmp_path: Path) -> None:
        """文件内容损坏时，_is_data_fresh 返回 False（触发下载）。"""
        from src.freqtrade_bridge.data_downloader import DataDownloader

        datadir = tmp_path / "data" / "binance"
        datadir.mkdir(parents=True)
        data_file = datadir / "BTC_USDT-1h-futures.json"
        data_file.write_text("not_valid_json{{{")

        downloader = DataDownloader()
        result = downloader._is_data_fresh(tmp_path, "BTC/USDT", "1h")
        assert result is False

    def test_empty_file_returns_false(self, tmp_path: Path) -> None:
        """空文件时，_is_data_fresh 返回 False。"""
        from src.freqtrade_bridge.data_downloader import DataDownloader

        datadir = tmp_path / "data" / "binance"
        datadir.mkdir(parents=True)
        data_file = datadir / "BTC_USDT-1h-futures.json"
        data_file.write_text("[]")  # 空列表

        downloader = DataDownloader()
        result = downloader._is_data_fresh(tmp_path, "BTC/USDT", "1h")
        assert result is False


class TestRunDownloadSubprocess:
    """任务 2.2：测试 download-data 子进程调用（_run_download_subprocess）。"""

    def test_timeout_raises_freqtrade_timeout_error(self, tmp_path: Path) -> None:
        """子进程超时时，抛出 FreqtradeTimeoutError（需求 6.3）。"""
        from src.freqtrade_bridge.data_downloader import DataDownloader
        from src.freqtrade_bridge.exceptions import FreqtradeTimeoutError

        downloader = DataDownloader()

        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="freqtrade", timeout=300)):
            with pytest.raises(FreqtradeTimeoutError):
                downloader._run_download_subprocess(
                    pairs=["BTC/USDT"],
                    timeframes=["1h"],
                    datadir=tmp_path,
                    days=30,
                    timeout=300,
                )

    def test_nonzero_exit_code_raises_freqtrade_execution_error(self, tmp_path: Path) -> None:
        """非零退出码时，抛出 FreqtradeExecutionError（需求 1.3）。"""
        from src.freqtrade_bridge.data_downloader import DataDownloader
        from src.freqtrade_bridge.exceptions import FreqtradeExecutionError

        downloader = DataDownloader()

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "freqtrade error output"

        with patch("subprocess.run", return_value=mock_result):
            with pytest.raises(FreqtradeExecutionError):
                downloader._run_download_subprocess(
                    pairs=["BTC/USDT"],
                    timeframes=["1h"],
                    datadir=tmp_path,
                    days=30,
                )

    def test_success_returns_normally(self, tmp_path: Path) -> None:
        """成功执行时，_run_download_subprocess 正常返回（不抛异常）。"""
        from src.freqtrade_bridge.data_downloader import DataDownloader

        downloader = DataDownloader()

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result):
            downloader._run_download_subprocess(
                pairs=["BTC/USDT"],
                timeframes=["1h"],
                datadir=tmp_path,
                days=30,
            )  # 不抛异常即通过

    def test_config_file_contains_dry_run_true(self, tmp_path: Path) -> None:
        """生成的 freqtrade 配置文件应包含 dry_run: true（需求 6.1）。"""

        from src.freqtrade_bridge.data_downloader import DataDownloader

        downloader = DataDownloader()

        captured_config: dict = {}

        def capture_subprocess(*args, **kwargs):
            """捕获子进程调用，检查传入的配置文件内容。"""
            cmd = args[0] if args else kwargs.get("args", [])
            # 找到 --config 参数后的配置文件路径
            for i, arg in enumerate(cmd):
                if arg == "--config" and i + 1 < len(cmd):
                    config_path = Path(cmd[i + 1])
                    if config_path.exists():
                        captured_config.update(json.loads(config_path.read_text()))
                    break
            result = MagicMock()
            result.returncode = 0
            return result

        with patch("subprocess.run", side_effect=capture_subprocess):
            downloader._run_download_subprocess(
                pairs=["BTC/USDT"],
                timeframes=["1h"],
                datadir=tmp_path,
                days=30,
            )

        assert captured_config.get("dry_run") is True, "配置文件必须包含 dry_run: true"

    def test_config_file_no_exchange_credentials(self, tmp_path: Path) -> None:
        """生成的配置文件不应含 exchange.key / exchange.secret（需求 6.1）。"""
        from src.freqtrade_bridge.data_downloader import DataDownloader

        downloader = DataDownloader()

        captured_config: dict = {}

        def capture_subprocess(*args, **kwargs):
            cmd = args[0] if args else kwargs.get("args", [])
            for i, arg in enumerate(cmd):
                if arg == "--config" and i + 1 < len(cmd):
                    config_path = Path(cmd[i + 1])
                    if config_path.exists():
                        captured_config.update(json.loads(config_path.read_text()))
                    break
            result = MagicMock()
            result.returncode = 0
            return result

        with patch("subprocess.run", side_effect=capture_subprocess):
            downloader._run_download_subprocess(
                pairs=["BTC/USDT"],
                timeframes=["1h"],
                datadir=tmp_path,
                days=30,
            )

        exchange = captured_config.get("exchange", {})
        assert "key" not in exchange, "配置不应包含 exchange.key"
        assert "secret" not in exchange, "配置不应包含 exchange.secret"

    def test_config_disables_telegram(self, tmp_path: Path) -> None:
        """生成的配置文件应禁用 telegram 通知（需求 6.2）。"""
        from src.freqtrade_bridge.data_downloader import DataDownloader

        downloader = DataDownloader()

        captured_config: dict = {}

        def capture_subprocess(*args, **kwargs):
            cmd = args[0] if args else kwargs.get("args", [])
            for i, arg in enumerate(cmd):
                if arg == "--config" and i + 1 < len(cmd):
                    config_path = Path(cmd[i + 1])
                    if config_path.exists():
                        captured_config.update(json.loads(config_path.read_text()))
                    break
            result = MagicMock()
            result.returncode = 0
            return result

        with patch("subprocess.run", side_effect=capture_subprocess):
            downloader._run_download_subprocess(
                pairs=["BTC/USDT"],
                timeframes=["1h"],
                datadir=tmp_path,
                days=30,
            )

        # telegram 应被禁用（不存在或 enabled=false）
        telegram = captured_config.get("telegram", {})
        assert telegram.get("enabled", True) is False, "telegram 通知应被禁用"


class TestDownloadMarketData:
    """任务 2.3：测试 download_market_data 降级与汇总逻辑。"""

    def test_local_fallback_when_download_fails_but_file_exists(self, tmp_path: Path) -> None:
        """download-data 失败但本地文件存在时，降级使用本地数据（需求 1.9）。"""
        import datetime
        import json as _json

        from src.freqtrade_bridge.data_downloader import DataDownloader, DownloadResult
        from src.freqtrade_bridge.exceptions import FreqtradeExecutionError

        # 创建本地数据文件（新鲜度已过期，触发下载）
        datadir = tmp_path / "data" / "binance"
        datadir.mkdir(parents=True)
        data_file = datadir / "BTC_USDT-1h-futures.json"

        # 2 小时前的数据（过期，会触发下载尝试）
        now = datetime.datetime.now(tz=datetime.timezone.utc)
        stale_ts = int((now - datetime.timedelta(hours=2)).timestamp() * 1000)
        data_file.write_text(_json.dumps([[stale_ts, 50000.0, 51000.0, 49000.0, 50500.0, 100.0]]))

        downloader = DataDownloader()

        # Mock _run_download_subprocess 使其失败
        with patch.object(downloader, "_run_download_subprocess", side_effect=FreqtradeExecutionError("下载失败")):
            result = downloader.download_market_data(
                pairs=["BTC/USDT"],
                timeframes=["1h"],
                datadir=tmp_path,
                days=30,
            )

        assert isinstance(result, DownloadResult)
        assert result.data_source == "local_fallback"
        assert result.pairs_failed == 0  # 降级成功，不算失败

    def test_raises_when_download_fails_and_no_local_file(self, tmp_path: Path) -> None:
        """download-data 失败且无本地文件时，抛出异常（需求 1.9）。"""
        from src.freqtrade_bridge.data_downloader import DataDownloader
        from src.freqtrade_bridge.exceptions import FreqtradeExecutionError

        downloader = DataDownloader()

        # 不创建本地数据文件
        with patch.object(downloader, "_run_download_subprocess", side_effect=FreqtradeExecutionError("下载失败")):
            with pytest.raises(FreqtradeExecutionError):
                downloader.download_market_data(
                    pairs=["BTC/USDT"],
                    timeframes=["1h"],
                    datadir=tmp_path,
                    days=30,
                )

    def test_skips_fresh_data(self, tmp_path: Path) -> None:
        """新鲜数据跳过下载，pairs_skipped 计数正确（需求 1.2）。"""
        import datetime

        from src.freqtrade_bridge.data_downloader import DataDownloader, DownloadResult

        datadir = tmp_path / "data" / "binance"
        datadir.mkdir(parents=True)
        data_file = datadir / "BTC_USDT-1h-futures.json"

        # 30 分钟前（新鲜）
        now = datetime.datetime.now(tz=datetime.timezone.utc)
        fresh_ts = int((now - datetime.timedelta(minutes=30)).timestamp() * 1000)
        data_file.write_text(json.dumps([[fresh_ts, 50000.0, 51000.0, 49000.0, 50500.0, 100.0]]))

        downloader = DataDownloader()

        # _run_download_subprocess 不应被调用
        with patch.object(downloader, "_run_download_subprocess") as mock_dl:
            result = downloader.download_market_data(
                pairs=["BTC/USDT"],
                timeframes=["1h"],
                datadir=tmp_path,
                days=30,
            )
            mock_dl.assert_not_called()

        assert isinstance(result, DownloadResult)
        assert result.pairs_skipped >= 1
        assert result.data_source == "cached"

    def test_successful_download_result(self, tmp_path: Path) -> None:
        """成功下载时，DownloadResult 包含正确统计（pairs_downloaded）。"""
        from src.freqtrade_bridge.data_downloader import DataDownloader, DownloadResult

        downloader = DataDownloader()

        # Mock 成功的下载
        with patch.object(downloader, "_run_download_subprocess", return_value=None):
            result = downloader.download_market_data(
                pairs=["BTC/USDT"],
                timeframes=["1h"],
                datadir=tmp_path,
                days=30,
            )

        assert isinstance(result, DownloadResult)
        assert result.pairs_downloaded >= 1
        assert result.data_source == "exchange"

    def test_cleanup_temp_config_after_completion(self, tmp_path: Path) -> None:
        """任务完成后，临时配置目录应被清理（需求 6.5）。"""
        import os

        from src.freqtrade_bridge.data_downloader import DataDownloader

        downloader = DataDownloader()

        created_temp_dirs: list[str] = []

        def capture_and_succeed(*args, **kwargs):
            cmd = args[0] if args else kwargs.get("args", [])
            for i, arg in enumerate(cmd):
                if arg == "--config" and i + 1 < len(cmd):
                    config_path = Path(cmd[i + 1])
                    created_temp_dirs.append(str(config_path.parent))
            result = MagicMock()
            result.returncode = 0
            return result

        with patch("subprocess.run", side_effect=capture_and_succeed):
            downloader.download_market_data(
                pairs=["BTC/USDT"],
                timeframes=["1h"],
                datadir=tmp_path,
                days=30,
            )

        # 临时配置目录应已被清理
        for temp_dir in created_temp_dirs:
            assert not os.path.exists(temp_dir), f"临时目录未被清理: {temp_dir}"

    def test_download_result_has_elapsed_seconds(self, tmp_path: Path) -> None:
        """DownloadResult 应包含 elapsed_seconds 字段。"""
        from src.freqtrade_bridge.data_downloader import DataDownloader, DownloadResult

        downloader = DataDownloader()

        with patch.object(downloader, "_run_download_subprocess", return_value=None):
            result = downloader.download_market_data(
                pairs=["BTC/USDT"],
                timeframes=["1h"],
                datadir=tmp_path,
                days=30,
            )

        assert isinstance(result, DownloadResult)
        assert result.elapsed_seconds >= 0.0
