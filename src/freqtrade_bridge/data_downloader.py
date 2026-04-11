"""DataDownloader：freqtrade download-data 子进程封装。

封装 freqtrade download-data CLI 调用，管理本地 OHLCV datadir 持久化文件。
提供增量行情更新（新鲜度检查）和降级逻辑（本地文件回退）。

核心设计原则：
  - 禁止删除或清空 datadir 下任何已有 OHLCV 文件（需求 1.8）
  - 生成隔离的 freqtrade 配置文件（无账户凭据，dry_run=true，禁用 Telegram）
  - 任务完成后清理临时配置目录（需求 6.5），不影响 datadir
  - 子进程超时 300 秒强制终止（需求 6.3）
"""

import json
import shutil
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import structlog

from src.freqtrade_bridge.exceptions import FreqtradeExecutionError, FreqtradeTimeoutError

logger = structlog.get_logger(__name__)

# 子进程默认超时（秒）
_DEFAULT_SUBPROCESS_TIMEOUT = 300

# 交易所名称（当前只支持 binance）
_EXCHANGE_NAME = "binance"


@dataclass
class DownloadResult:
    """download_market_data 方法的汇总返回值。

    Attributes:
        data_source: 数据来源标记（exchange=新下载，local_fallback=降级，cached=跳过）
        pairs_downloaded: 成功下载的交易对数量
        pairs_skipped: 新鲜度检查通过、跳过下载的数量
        pairs_failed: 失败的交易对数量（下载失败且无本地文件）
        elapsed_seconds: 整个下载流程耗时（秒）
        failed_pairs: 失败的交易对列表（用于日志）
    """

    data_source: Literal["exchange", "local_fallback", "cached"]
    pairs_downloaded: int = 0
    pairs_skipped: int = 0
    pairs_failed: int = 0
    elapsed_seconds: float = 0.0
    failed_pairs: list[str] = field(default_factory=list)


class DataDownloader:
    """封装 freqtrade download-data 子进程，管理 OHLCV 数据目录。

    职责：
      1. 新鲜度检查：判断本地数据文件最后一根 K 线是否在当前周期内
      2. 增量下载：通过子进程调用 freqtrade download-data CLI
      3. 降级逻辑：下载失败时使用本地数据并标记 data_source=local_fallback
      4. 清理：任务完成后清理临时配置目录（不影响 datadir）

    不变式：不删除 datadir 下任何已有 OHLCV 文件。
    """

    def download_market_data(
        self,
        pairs: list[str],
        timeframes: list[str],
        datadir: Path,
        days: int = 30,
        timeout: int = _DEFAULT_SUBPROCESS_TIMEOUT,
    ) -> DownloadResult:
        """执行两阶段行情拉取：新鲜度检查 + 增量 download-data。

        对每个 (pair, timeframe) 组合：
          1. 检查本地文件新鲜度
          2. 若新鲜则跳过（pairs_skipped++）
          3. 否则尝试 download-data 子进程
          4. 若失败但本地文件存在，降级（local_fallback）
          5. 若失败且无本地文件，抛出 FreqtradeExecutionError

        Returns:
            DownloadResult，含 data_source 标记和跳过/成功/失败统计

        Raises:
            FreqtradeExecutionError: download-data 失败且无本地文件可降级
        """
        start_time = time.monotonic()

        pairs_downloaded = 0
        pairs_skipped = 0
        pairs_failed = 0
        failed_pairs: list[str] = []
        has_local_fallback = False

        # 检查每个 (pair, timeframe) 组合的新鲜度
        stale_pairs = []
        for pair in pairs:
            all_fresh = True
            for timeframe in timeframes:
                if not self._is_data_fresh(datadir, pair, timeframe):
                    all_fresh = False
                    break
            if all_fresh:
                pairs_skipped += 1
            else:
                stale_pairs.append(pair)

        if stale_pairs:
            # 尝试批量下载过期的交易对
            try:
                self._run_download_subprocess(
                    pairs=stale_pairs,
                    timeframes=timeframes,
                    datadir=datadir,
                    days=days,
                    timeout=timeout,
                )
                pairs_downloaded = len(stale_pairs)

            except (FreqtradeExecutionError, FreqtradeTimeoutError) as exc:
                # 下载失败，检查每个 pair 是否有可用的本地文件
                logger.warning(
                    "download-data 失败，尝试降级使用本地数据",
                    error=str(exc),
                    stale_pairs=stale_pairs,
                )

                for pair in stale_pairs:
                    has_any_local_file = False
                    for timeframe in timeframes:
                        data_file = self._get_data_file_path(datadir, pair, timeframe)
                        if data_file.exists():
                            has_any_local_file = True
                            break

                    if has_any_local_file:
                        has_local_fallback = True
                        logger.warning(
                            "降级使用本地数据",
                            pair=pair,
                            data_source="local_fallback",
                        )
                    else:
                        pairs_failed += 1
                        failed_pairs.append(pair)
                        logger.error(
                            "download-data 失败且无本地数据，跳过该交易对",
                            pair=pair,
                        )

                # 如果所有 stale_pairs 都失败且无本地文件，则抛出异常
                if pairs_failed == len(stale_pairs) and not has_local_fallback:
                    raise FreqtradeExecutionError(f"行情拉取失败且无本地数据可降级，pairs: {stale_pairs}") from exc

        # 确定数据来源标记
        if has_local_fallback:
            data_source: Literal["exchange", "local_fallback", "cached"] = "local_fallback"
        elif pairs_downloaded > 0:
            data_source = "exchange"
        else:
            data_source = "cached"

        elapsed = time.monotonic() - start_time

        return DownloadResult(
            data_source=data_source,
            pairs_downloaded=pairs_downloaded,
            pairs_skipped=pairs_skipped,
            pairs_failed=pairs_failed,
            elapsed_seconds=elapsed,
            failed_pairs=failed_pairs,
        )

    def _is_data_fresh(
        self,
        datadir: Path,
        pair: str,
        timeframe: str,
    ) -> bool:
        """检查本地数据文件最后一根 K 线是否在当前时间周期内。

        Args:
            datadir: OHLCV 数据根目录
            pair: 交易对（如 "BTC/USDT"）
            timeframe: 时间周期（如 "1h"）

        Returns:
            True 表示数据足够新鲜，可跳过拉取；
            False 表示数据过期或文件不存在，需要下载
        """
        import datetime

        data_file = self._get_data_file_path(datadir, pair, timeframe)

        if not data_file.exists():
            return False

        try:
            import pandas as pd

            df = pd.read_feather(data_file)
            if df.empty:
                return False

            # freqtrade feather 格式含 date 列（datetime64[ns, UTC]）
            last_date = pd.Timestamp(df["date"].iloc[-1])
            if last_date.tzinfo is None:
                last_date = last_date.tz_localize("UTC")

            # 计算时间周期对应的秒数
            period_seconds = self._timeframe_to_seconds(timeframe)

            # 检查最后一根 K 线是否在当前周期内（2 倍容差）
            now = datetime.datetime.now(tz=datetime.timezone.utc)
            age_seconds = (now - last_date).total_seconds()

            return age_seconds <= period_seconds * 2

        except Exception:
            return False

    def _run_download_subprocess(
        self,
        pairs: list[str],
        timeframes: list[str],
        datadir: Path,
        days: int,
        timeout: int = _DEFAULT_SUBPROCESS_TIMEOUT,
    ) -> None:
        """以子进程方式调用 freqtrade download-data CLI。

        生成隔离的 freqtrade 配置文件（无账户凭据，dry_run=true，禁用 Telegram/RPC）。
        配置文件写入 /tmp/freqtrade_signals/{task_id}/config.json。

        Args:
            pairs: 要下载的交易对列表
            timeframes: 时间周期列表
            datadir: OHLCV 数据输出目录
            days: 下载历史天数
            timeout: 子进程超时秒数（超时后强制终止）

        Raises:
            FreqtradeTimeoutError: 超过 timeout 秒
            FreqtradeExecutionError: 非零退出码
        """
        task_id = str(uuid.uuid4())
        temp_dir = Path(f"/tmp/freqtrade_signals/{task_id}")  # noqa: S108
        temp_dir.mkdir(parents=True, exist_ok=True)

        config_path = temp_dir / "config.json"

        try:
            # 生成隔离的 freqtrade 配置（无账户凭据）
            config = self._build_download_config(datadir)
            config_path.write_text(json.dumps(config, indent=2))

            # 构建命令参数
            pairs_str = " ".join(pairs)
            timeframes_str = " ".join(timeframes)

            cmd = [
                "freqtrade",
                "download-data",
                "--config",
                str(config_path),
                "--exchange",
                _EXCHANGE_NAME,
                "--pairs",
                *pairs,
                "--timeframes",
                *timeframes,
                "--days",
                str(days),
                "--datadir",
                str(datadir),
                "--trading-mode",
                "spot",
            ]

            logger.info(
                "启动 freqtrade download-data 子进程",
                pairs=pairs_str,
                timeframes=timeframes_str,
                days=days,
                timeout=timeout,
            )

            result = subprocess.run(  # noqa: S603
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )

            if result.returncode != 0:
                logger.error(
                    "freqtrade download-data 返回非零退出码",
                    returncode=result.returncode,
                    stderr=result.stderr[:500] if result.stderr else "",
                )
                raise FreqtradeExecutionError(f"freqtrade download-data 失败，退出码: {result.returncode}")

            logger.info(
                "freqtrade download-data 完成",
                pairs=pairs_str,
            )

        except subprocess.TimeoutExpired:
            logger.warning(
                "freqtrade download-data 超时，强制终止子进程",
                timeout=timeout,
                pairs=pairs,
            )
            raise FreqtradeTimeoutError(f"freqtrade download-data 超时（{timeout}秒），已强制终止") from None
        finally:
            # 清理临时配置目录（不影响 datadir）
            if temp_dir.exists():
                try:
                    shutil.rmtree(temp_dir)
                except Exception as cleanup_exc:
                    logger.warning(
                        "临时目录清理失败",
                        temp_dir=str(temp_dir),
                        error=str(cleanup_exc),
                    )

    def _build_download_config(self, datadir: Path) -> dict:
        """生成隔离的 freqtrade 配置文件（仅用于 download-data）。

        配置原则（需求 6.1, 6.2）：
          - dry_run: true
          - 不含 exchange.key / exchange.secret
          - 禁用 telegram 通知
          - 禁用 api_server（RPC）
        """
        return {
            "dry_run": True,
            "exchange": {
                "name": _EXCHANGE_NAME,
                # 不含 key / secret，使用公开行情接口
            },
            "telegram": {
                "enabled": False,
            },
            "api_server": {
                "enabled": False,
            },
            "datadir": str(datadir),
        }

    def _get_data_file_path(self, datadir: Path, pair: str, timeframe: str) -> Path:
        """获取 (pair, timeframe) 对应的 OHLCV 数据文件路径。

        freqtrade 默认文件命名格式（spot feather）：
          {datadir}/{pair_normalized}-{timeframe}.feather
          例如：BTC/USDT → BTC_USDT-1d.feather
        """
        pair_normalized = pair.replace("/", "_")
        filename = f"{pair_normalized}-{timeframe}.feather"
        return datadir / filename

    @staticmethod
    def _timeframe_to_seconds(timeframe: str) -> float:
        """将时间周期字符串转换为秒数。

        支持：1m, 5m, 15m, 30m, 1h, 4h, 1d, 1w
        """
        timeframe_seconds = {
            "1m": 60,
            "3m": 180,
            "5m": 300,
            "15m": 900,
            "30m": 1800,
            "1h": 3600,
            "2h": 7200,
            "4h": 14400,
            "6h": 21600,
            "8h": 28800,
            "12h": 43200,
            "1d": 86400,
            "3d": 259200,
            "1w": 604800,
        }
        return float(timeframe_seconds.get(timeframe, 3600))
