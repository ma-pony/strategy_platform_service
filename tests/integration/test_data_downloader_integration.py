"""任务 9.1 集成测试：DataDownloader + 本地文件集成测试。

使用测试 fixtures 的本地 OHLCV 文件（非真实 Binance 请求）：
  - 验证新鲜度检查正确跳过已有新鲜数据
  - 验证降级逻辑：download-data 子进程失败时，现有本地文件被正确使用

涵盖需求：1.2, 1.9
"""

import json
import time
from pathlib import Path

import pytest


def _write_ohlcv_fixture(datadir: Path, pair: str, timeframe: str, age_seconds: float = 0) -> Path:
    """在 datadir 中写入测试用 OHLCV 文件。

    Args:
        datadir: 数据目录
        pair: 交易对（如 BTC/USDT）
        timeframe: 时间周期
        age_seconds: K 线时间戳距当前的秒数（0=新鲜）
    """
    pair_normalized = pair.replace("/", "_")
    filename = f"{pair_normalized}-{timeframe}-futures.json"
    exchange_dir = datadir / "data" / "binance"
    exchange_dir.mkdir(parents=True, exist_ok=True)
    file_path = exchange_dir / filename

    now_ms = int((time.time() - age_seconds) * 1000)
    # freqtrade OHLCV 格式：[timestamp_ms, open, high, low, close, volume]
    ohlcv_data = [
        [now_ms, 50000.0, 51000.0, 49000.0, 50500.0, 100.0],
    ]
    file_path.write_text(json.dumps(ohlcv_data))
    return file_path


class TestDataDownloaderFreshnessIntegration:
    """DataDownloader 新鲜度检查集成测试（需求 1.2）。"""

    def test_fresh_data_skips_download(self, tmp_path: Path) -> None:
        """本地数据足够新鲜时，跳过下载（pairs_skipped 增加）。"""
        from src.freqtrade_bridge.data_downloader import DataDownloader

        # 写入新鲜数据（0 秒前）
        _write_ohlcv_fixture(tmp_path, "BTC/USDT", "1h", age_seconds=0)

        downloader = DataDownloader()
        result = downloader.download_market_data(
            pairs=["BTC/USDT"],
            timeframes=["1h"],
            datadir=tmp_path,
        )

        assert result.pairs_skipped == 1
        assert result.pairs_downloaded == 0
        assert result.data_source == "cached"

    def test_stale_data_triggers_download_attempt(self, tmp_path: Path) -> None:
        """数据过期时触发下载尝试（即使子进程失败，本地文件存在时降级）。"""
        from unittest.mock import patch

        from src.freqtrade_bridge.data_downloader import DataDownloader
        from src.freqtrade_bridge.exceptions import FreqtradeExecutionError

        # 写入过期数据（比时间周期更旧）
        _write_ohlcv_fixture(tmp_path, "BTC/USDT", "1h", age_seconds=7200)  # 2h 前

        downloader = DataDownloader()

        # download-data 子进程失败
        with patch.object(
            downloader,
            "_run_download_subprocess",
            side_effect=FreqtradeExecutionError("下载失败"),
        ):
            result = downloader.download_market_data(
                pairs=["BTC/USDT"],
                timeframes=["1h"],
                datadir=tmp_path,
            )

        # 本地文件存在 → 降级
        assert result.data_source == "local_fallback"
        assert result.pairs_failed == 0

    def test_no_local_file_fresh_check_returns_false(self, tmp_path: Path) -> None:
        """本地文件不存在时新鲜度检查返回 False。"""
        from src.freqtrade_bridge.data_downloader import DataDownloader

        downloader = DataDownloader()
        is_fresh = downloader._is_data_fresh(tmp_path, "ETH/USDT", "1h")

        assert is_fresh is False

    def test_fresh_check_with_recent_candle_returns_true(self, tmp_path: Path) -> None:
        """最后一根 K 线在周期内时返回 True。"""
        from src.freqtrade_bridge.data_downloader import DataDownloader

        _write_ohlcv_fixture(tmp_path, "BTC/USDT", "1h", age_seconds=30)

        downloader = DataDownloader()
        is_fresh = downloader._is_data_fresh(tmp_path, "BTC/USDT", "1h")

        assert is_fresh is True

    def test_fresh_check_with_old_candle_returns_false(self, tmp_path: Path) -> None:
        """最后一根 K 线超过周期时返回 False。"""
        from src.freqtrade_bridge.data_downloader import DataDownloader

        _write_ohlcv_fixture(tmp_path, "BTC/USDT", "1h", age_seconds=4000)  # > 3600s

        downloader = DataDownloader()
        is_fresh = downloader._is_data_fresh(tmp_path, "BTC/USDT", "1h")

        assert is_fresh is False


class TestDataDownloaderFallbackIntegration:
    """DataDownloader 降级逻辑集成测试（需求 1.9）。"""

    def test_fallback_used_when_download_fails_and_local_exists(
        self,
        tmp_path: Path,
    ) -> None:
        """download-data 失败且本地文件存在时，标记 local_fallback（需求 1.9）。"""
        from unittest.mock import patch

        from src.freqtrade_bridge.data_downloader import DataDownloader
        from src.freqtrade_bridge.exceptions import FreqtradeExecutionError

        # 写入过期数据（需要更新）
        _write_ohlcv_fixture(tmp_path, "ETH/USDT", "1h", age_seconds=7200)

        downloader = DataDownloader()

        with patch.object(
            downloader,
            "_run_download_subprocess",
            side_effect=FreqtradeExecutionError("Binance API 限速"),
        ):
            result = downloader.download_market_data(
                pairs=["ETH/USDT"],
                timeframes=["1h"],
                datadir=tmp_path,
            )

        assert result.data_source == "local_fallback"
        assert result.pairs_downloaded == 0
        assert result.pairs_failed == 0

    def test_no_fallback_and_raises_when_no_local_file(
        self,
        tmp_path: Path,
    ) -> None:
        """download-data 失败且无本地文件时抛出异常（需求 1.9）。"""
        from unittest.mock import patch

        from src.freqtrade_bridge.data_downloader import DataDownloader
        from src.freqtrade_bridge.exceptions import FreqtradeExecutionError

        downloader = DataDownloader()

        with patch.object(
            downloader,
            "_run_download_subprocess",
            side_effect=FreqtradeExecutionError("下载失败"),
        ):
            with pytest.raises(FreqtradeExecutionError):
                downloader.download_market_data(
                    pairs=["DOGE/USDT"],
                    timeframes=["1h"],
                    datadir=tmp_path,
                )
