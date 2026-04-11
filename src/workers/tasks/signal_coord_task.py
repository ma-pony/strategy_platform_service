"""CoordTask：全局信号协调 Celery 任务。

generate_all_signals_task：两阶段流水线（DataDownloader → SignalCalculator）。

核心设计：
  - 分布式锁：Redis SET lock:signal_refresh NX EX 600（需求 2.7）
  - 幂等调度：锁已存在时直接返回，不执行任何操作
  - 两阶段串行执行：阶段一行情拉取 → 阶段二信号计算（需求 2.1）
  - 连续失败告警：Redis 计数器 signal:consecutive_failures，达 3 时 ERROR 日志（需求 5.4）
  - 结构化汇总日志：总耗时、阶段耗时、成功/失败数、缓存命中率（需求 5.2）
"""

import time
from pathlib import Path
from typing import Any

import structlog
from celery import shared_task

from src.freqtrade_bridge.data_downloader import DataDownloader
from src.freqtrade_bridge.signal_calculator import SignalCalculator
from src.workers.redis_client import get_redis_client

logger = structlog.get_logger(__name__)

# 分布式锁 Redis key 和 TTL
_LOCK_KEY = "lock:signal_refresh"
_LOCK_TTL = 600  # 秒

# 连续失败计数器 Redis key
_FAILURE_COUNTER_KEY = "signal:consecutive_failures"

# 触发 ERROR 告警的失败阈值
_ALERT_THRESHOLD = 3


def _get_active_strategies_and_pairs() -> tuple[list[dict[str, Any]], list[str]]:
    """从数据库读取所有激活策略及其关联交易对。

    Returns:
        (strategies, pairs) 元组：
          - strategies: 策略信息列表，每项含 id、name、class 字段
          - pairs: 所有激活策略的并集交易对列表（去重）
    """
    from src.core.app_settings import get_settings
    from src.workers.db import SyncSessionLocal

    settings = get_settings()

    try:
        from sqlalchemy import select

        from src.models.strategy import Strategy

        with SyncSessionLocal() as session:
            stmt = select(Strategy).where(Strategy.is_active.is_(True))
            strategies_orm = session.execute(stmt).scalars().all()

        strategies = []
        all_pairs: set[str] = set()

        for s in strategies_orm:
            # 尝试动态加载策略类（当前简化为 None，由调用方处理）
            strategy_class = _load_strategy_class(s.name)
            strategies.append(
                {
                    "id": s.id,
                    "name": s.name,
                    "class": strategy_class,
                }
            )
            # 合并交易对
            if s.pairs:
                all_pairs.update(s.pairs)

        # 若数据库无配置交易对，回退到 settings.signal_pairs
        if not all_pairs:
            all_pairs = set(settings.signal_pairs)

        return strategies, list(all_pairs)

    except Exception as exc:
        logger.warning(
            "读取激活策略失败，回退到配置文件交易对",
            error=str(exc),
        )
        return [], list(settings.signal_pairs)


def _load_strategy_class(strategy_name: str) -> Any:
    """通过策略注册表动态加载 freqtrade 策略类。

    使用 strategy_registry.lookup() 获取策略文件路径和类名，
    再通过 importlib 从文件路径动态导入策略类。

    加载失败时返回 None（调用方负责处理 None 策略类）。
    """
    import importlib.util
    import sys

    try:
        from src.freqtrade_bridge.strategy_registry import lookup

        entry = lookup(strategy_name)
        file_path = entry["file_path"]
        class_name = entry["class_name"]

        spec = importlib.util.spec_from_file_location(class_name, str(file_path))
        if spec is None or spec.loader is None:
            logger.warning("无法加载策略文件", strategy=strategy_name, file_path=str(file_path))
            return None
        module = importlib.util.module_from_spec(spec)
        sys.modules[class_name] = module
        spec.loader.exec_module(module)  # type: ignore[union-attr]
        return getattr(module, class_name)
    except Exception as exc:
        logger.warning("策略类加载失败", strategy=strategy_name, error=str(exc))
        return None


@shared_task(
    name="src.workers.tasks.signal_coord_task.generate_all_signals_task",
    bind=False,
    acks_late=True,
    queue="signal",
)
def generate_all_signals_task() -> None:
    """两阶段信号生成协调任务。

    流程：
      1. 尝试获取 Redis 分布式锁（NX）；锁已存在则幂等返回
      2. 从数据库读取所有激活策略和关联交易对
      3. 阶段一：DataDownloader.download_market_data（行情拉取）
      4. 阶段二：SignalCalculator.compute_all_signals（信号计算）
      5. finally：释放锁、记录汇总日志、更新连续失败计数器
    """
    from src.core.app_settings import get_settings

    settings = get_settings()
    redis_client = get_redis_client()

    # ── 获取分布式锁 ──────────────────────────────────────────────
    lock_acquired = redis_client.set(_LOCK_KEY, "1", nx=True, ex=_LOCK_TTL)
    if not lock_acquired:
        logger.info(
            "分布式锁已被占用，任务幂等跳过",
            lock_key=_LOCK_KEY,
        )
        return

    start_time = time.monotonic()

    try:
        # ── 读取激活策略和交易对 ──────────────────────────────────
        strategies, pairs = _get_active_strategies_and_pairs()
        timeframes = settings.signal_timeframes
        datadir = Path(settings.freqtrade_datadir)

        logger.info(
            "开始两阶段信号生成",
            strategy_count=len(strategies),
            pair_count=len(pairs),
            timeframes=timeframes,
        )

        # ── 阶段一：DataDownloader ────────────────────────────────
        phase1_start = time.monotonic()
        downloader = DataDownloader()
        download_result = downloader.download_market_data(
            pairs=pairs,
            timeframes=timeframes,
            datadir=datadir,
        )
        phase1_elapsed = time.monotonic() - phase1_start

        logger.info(
            "阶段一完成：行情拉取",
            data_source=download_result.data_source,
            pairs_downloaded=download_result.pairs_downloaded,
            pairs_skipped=download_result.pairs_skipped,
            pairs_failed=download_result.pairs_failed,
            phase1_elapsed=round(phase1_elapsed, 2),
        )

        # ── 阶段二：SignalCalculator ──────────────────────────────
        calculator = SignalCalculator()
        compute_result = calculator.compute_all_signals(
            strategies=strategies,
            pairs=pairs,
            timeframes=timeframes,
            datadir=datadir,
        )

        total_elapsed = time.monotonic() - start_time

        # ── 汇总日志 ──────────────────────────────────────────────
        logger.info(
            "两阶段信号生成完成",
            total_elapsed=round(total_elapsed, 2),
            phase1_elapsed=round(phase1_elapsed, 2),
            data_source=download_result.data_source,
            pairs_downloaded=download_result.pairs_downloaded,
            total_combinations=compute_result.total_combinations,
            success_count=compute_result.success_count,
            failure_count=compute_result.failure_count,
            cache_hit_rate=round(compute_result.cache_hit_rate, 4),
        )

        # ── 成功时重置连续失败计数器 ──────────────────────────────
        try:
            redis_client.set(_FAILURE_COUNTER_KEY, 0)
        except Exception as exc:
            logger.warning(
                "重置连续失败计数器失败",
                error=str(exc),
            )

    except Exception as exc:
        total_elapsed = time.monotonic() - start_time

        logger.error(
            "两阶段信号生成失败",
            error=str(exc),
            total_elapsed=round(total_elapsed, 2),
        )

        # ── 失败时增加连续失败计数器 ──────────────────────────────
        try:
            failure_count = redis_client.incr(_FAILURE_COUNTER_KEY)
            if failure_count >= _ALERT_THRESHOLD:
                logger.error(
                    "信号生成连续失败次数达到告警阈值",
                    consecutive_failures=failure_count,
                    threshold=_ALERT_THRESHOLD,
                )
        except Exception as counter_exc:
            logger.warning(
                "更新连续失败计数器失败",
                error=str(counter_exc),
            )

        raise

    finally:
        # ── 释放分布式锁 ──────────────────────────────────────────
        try:
            redis_client.delete(_LOCK_KEY)
        except Exception as exc:
            logger.warning(
                "释放分布式锁失败",
                lock_key=_LOCK_KEY,
                error=str(exc),
            )
