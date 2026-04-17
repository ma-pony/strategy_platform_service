"""SignalCalculator：从本地 OHLCV 数据计算信号并持久化。

替换 signal_fetcher.py 中的合成数据层（_build_ohlcv_dataframe），
使用 freqtrade.data.history.load_pair_history 从本地 datadir 加载真实 OHLCV 数据。

核心设计：
  - 同一 (pair, timeframe) 的 DataFrame 在内存中仅加载一次，供所有策略复用（需求 2.2）
  - 策略实例化通过 strategy_class(config={}) 执行，不启动真实 bot（需求 2.3）
  - 信号通过 upsert 语义写入数据库（需求 2.6）
  - 单个组合失败时记录 ERROR 日志，继续处理其余（需求 2.5）
  - Redis 写入失败时静默降级，不影响主流程（需求 3.3）
"""

import datetime
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog

from src.freqtrade_bridge.exceptions import FreqtradeExecutionError

logger = structlog.get_logger(__name__)

# freqtrade CLI download-data 会将文件落在 {datadir}/{exchange}/ 子目录下，
# 但 load_pair_history API 的 datadir 参数不会自动加该前缀。
# 为和 DataDownloader 的写入路径对齐，此处读取时显式拼接 exchange 子目录。
_EXCHANGE_NAME = "binance"

if TYPE_CHECKING:
    import pandas as pd
    from sqlalchemy.orm import Session


# Redis 信号缓存 TTL（秒）
_SIGNAL_CACHE_TTL = 3600


@dataclass
class SignalData:
    """信号计算结果值对象。

    Attributes:
        direction: 信号方向（buy/sell/hold）
        confidence_score: 置信度（0.0–1.0）
        signal_at: K 线时间戳
        signal_source: 数据来源（realtime 等）
    """

    direction: str
    confidence_score: float | None
    signal_at: datetime.datetime
    signal_source: str = "realtime"


@dataclass
class SignalComputeResult:
    """compute_all_signals 方法的汇总返回值。

    Attributes:
        total_combinations: 总 (strategy × pair × timeframe) 组合数
        success_count: 成功处理的组合数
        failure_count: 失败的组合数
        elapsed_seconds: 总耗时（秒）
        cache_hit_rate: 内存 DataFrame 复用率（pair+timeframe 维度）
        failed_combinations: 失败的组合列表 (strategy_name, pair, timeframe)
    """

    total_combinations: int
    success_count: int
    failure_count: int
    elapsed_seconds: float
    cache_hit_rate: float
    failed_combinations: list[tuple[str, str, str]] = field(default_factory=list)


def load_pair_history(
    datadir: Path,
    pair: str,
    timeframe: str,
    **kwargs: Any,
) -> "pd.DataFrame":
    """从本地 datadir 加载 OHLCV DataFrame（可 Mock 的模块级函数）。

    实际调用 freqtrade.data.history.load_pair_history。
    设计为模块级函数便于测试时 Mock。
    """
    try:
        from freqtrade.data.history import load_pair_history as _load_pair_history  # type: ignore[import]

        return _load_pair_history(
            pair=pair,
            timeframe=timeframe,
            datadir=datadir,
            **kwargs,
        )
    except ImportError:
        # freqtrade 未安装时（单元测试环境），返回空 DataFrame
        import pandas as pd

        return pd.DataFrame()


def get_redis_client() -> Any:
    """获取 Redis 客户端（可 Mock 的模块级函数）。"""
    from src.workers.redis_client import get_redis_client as _get_redis_client

    return _get_redis_client()


class SignalCalculator:
    """从本地 datadir 加载 OHLCV 数据，运行策略，upsert 信号至 DB 和 Redis。

    内存缓存机制：
      - `_df_cache`：dict[(pair, timeframe), DataFrame]
      - 同一 (pair, timeframe) 在所有策略间共享，避免重复文件 I/O
    """

    def __init__(self) -> None:
        # 内存 DataFrame 缓存：{(pair, timeframe): pd.DataFrame}
        self._df_cache: dict[tuple[str, str], Any] = {}
        # 缓存命中计数
        self._cache_hits = 0
        self._cache_misses = 0

    def compute_all_signals(
        self,
        strategies: list[dict[str, Any]],
        pairs: list[str],
        timeframes: list[str],
        datadir: Path,
    ) -> SignalComputeResult:
        """遍历所有 (strategy × pair × timeframe) 组合，计算并持久化信号。

        DataFrame 按 (pair, timeframe) 缓存在内存，避免重复加载文件。

        Args:
            strategies: 策略信息列表，每项含 id、name、class 字段
            pairs: 交易对列表
            timeframes: 时间周期列表
            datadir: OHLCV 数据根目录

        Returns:
            SignalComputeResult，含成功/失败计数和各组合结果摘要
        """
        start_time = time.monotonic()

        # 重置缓存计数
        self._df_cache.clear()
        self._cache_hits = 0
        self._cache_misses = 0

        total_combinations = len(strategies) * len(pairs) * len(timeframes)
        success_count = 0
        failure_count = 0
        failed_combinations: list[tuple[str, str, str]] = []

        session = self._get_session()

        try:
            for strategy_info in strategies:
                strategy_id = strategy_info["id"]
                strategy_name = strategy_info.get("name", str(strategy_id))
                strategy_class = strategy_info.get("class")

                for pair in pairs:
                    for timeframe in timeframes:
                        # 每组合独立 SAVEPOINT，失败回滚到组合边界不影响其他组合
                        savepoint = session.begin_nested()
                        try:
                            # 加载 OHLCV 数据（内存缓存复用）
                            df = self._load_ohlcv_from_datadir(datadir, pair, timeframe)

                            # 实例化策略并运行方法链
                            df_with_signals = self._run_strategy_on_df(strategy_class, df, pair)

                            # 提取信号数据
                            signal_data = self._extract_signal_data(df_with_signals, pair, timeframe)

                            # upsert 到数据库并更新 Redis
                            self.upsert_signal(
                                session=session,
                                strategy_id=strategy_id,
                                pair=pair,
                                timeframe=timeframe,
                                signal_data=signal_data,
                            )

                            savepoint.commit()

                            # Redis 更新放在 SAVEPOINT 提交后（Redis 失败静默不影响 DB）
                            self._update_redis_cache(strategy_id, pair, timeframe, signal_data)

                            success_count += 1

                        except Exception as exc:
                            savepoint.rollback()
                            failure_count += 1
                            failed_combinations.append((strategy_name, pair, timeframe))
                            logger.error(
                                "信号计算失败，跳过该组合",
                                strategy_name=strategy_name,
                                strategy_id=strategy_id,
                                pair=pair,
                                timeframe=timeframe,
                                error=str(exc),
                            )

            # 所有组合处理完后统一提交外层事务（需求 2.6）
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

        elapsed = time.monotonic() - start_time

        # 计算内存 DataFrame 复用率
        total_loads = self._cache_hits + self._cache_misses
        cache_hit_rate = self._cache_hits / total_loads if total_loads > 0 else 0.0

        return SignalComputeResult(
            total_combinations=total_combinations,
            success_count=success_count,
            failure_count=failure_count,
            elapsed_seconds=elapsed,
            cache_hit_rate=cache_hit_rate,
            failed_combinations=failed_combinations,
        )

    def _load_ohlcv_from_datadir(
        self,
        datadir: Path,
        pair: str,
        timeframe: str,
    ) -> "pd.DataFrame":
        """从本地 datadir 加载 OHLCV DataFrame，内存缓存复用。

        调用模块级 load_pair_history 函数（便于 Mock）。

        Raises:
            FreqtradeExecutionError: 文件不存在或加载失败（返回空 DataFrame）
        """
        cache_key = (pair, timeframe)

        if cache_key in self._df_cache:
            self._cache_hits += 1
            return self._df_cache[cache_key]

        self._cache_misses += 1

        try:
            df = load_pair_history(datadir=datadir / _EXCHANGE_NAME, pair=pair, timeframe=timeframe)
        except Exception as exc:
            raise FreqtradeExecutionError(f"加载 OHLCV 数据失败，pair: {pair}, timeframe: {timeframe}") from exc

        if df is None or len(df) == 0:
            raise FreqtradeExecutionError(f"OHLCV 数据为空，文件可能不存在，pair: {pair}, timeframe: {timeframe}")

        # 存入内存缓存
        self._df_cache[cache_key] = df
        return df

    def _run_strategy_on_df(
        self,
        strategy_class: Any,
        df: "pd.DataFrame",
        pair: str,
    ) -> "pd.DataFrame":
        """实例化策略并执行三段式方法链。

        Args:
            strategy_class: freqtrade IStrategy 子类（未实例化的类）
            df: OHLCV DataFrame
            pair: 交易对

        Returns:
            填充了指标列和信号列的 DataFrame
        """
        strategy = strategy_class(config={})
        metadata = {"pair": pair}

        df = strategy.populate_indicators(df, metadata)
        df = strategy.populate_entry_trend(df, metadata)
        df = strategy.populate_exit_trend(df, metadata)

        return df

    def _extract_signal_data(
        self,
        df: "pd.DataFrame",
        pair: str,
        timeframe: str,
    ) -> SignalData:
        """从策略输出 DataFrame 最后一行提取信号数据。

        Args:
            df: 经策略处理的 DataFrame（含指标列和信号列）
            pair: 交易对
            timeframe: 时间周期

        Returns:
            SignalData 值对象
        """
        last_row = df.iloc[-1]

        # 判断信号方向（与现有 signal_fetcher.py 逻辑一致）
        enter_long = last_row.get("enter_long", 0)
        exit_long = last_row.get("exit_long", 0)
        enter_short = last_row.get("enter_short", 0)
        exit_short = last_row.get("exit_short", 0)

        if enter_long == 1:
            direction = "buy"
        elif enter_short == 1 or exit_long == 1:
            direction = "sell"
        elif exit_short == 1:
            direction = "buy"
        else:
            direction = "hold"

        # 置信度（与 signal_fetcher.py 逻辑一致）

        is_entry = enter_long == 1 or enter_short == 1
        if direction == "hold":
            confidence_score = 0.0
        else:
            confidence_score = 0.50
            if is_entry:
                confidence_score += 0.10
            confidence_score = min(confidence_score, 0.95)

        # K 线时间戳
        signal_at_raw = last_row.get("date")
        if signal_at_raw is None:
            signal_at = datetime.datetime.now(tz=datetime.timezone.utc)
        elif hasattr(signal_at_raw, "to_pydatetime"):
            signal_at = signal_at_raw.to_pydatetime()
            if signal_at.tzinfo is None:
                signal_at = signal_at.replace(tzinfo=datetime.timezone.utc)
        else:
            signal_at = datetime.datetime.now(tz=datetime.timezone.utc)

        return SignalData(
            direction=direction,
            confidence_score=confidence_score,
            signal_at=signal_at,
            signal_source="realtime",
        )

    def upsert_signal(
        self,
        session: "Session",
        strategy_id: int,
        pair: str,
        timeframe: str,
        signal_data: SignalData,
    ) -> None:
        """以 upsert 语义写入 trading_signals 表。

        基于 (strategy_id, pair, timeframe) 唯一约束：
        冲突时 UPDATE 现有记录，否则 INSERT。

        使用 PostgreSQL `INSERT ... ON CONFLICT DO UPDATE` 语法。

        Raises:
            Exception: 数据库写入失败时向上抛出（由 compute_all_signals 记录 ERROR）
        """
        from sqlalchemy import text

        from src.core.enums import SignalDirection

        try:
            direction_enum = SignalDirection(signal_data.direction.lower())
        except ValueError:
            direction_enum = SignalDirection.HOLD

        now = datetime.datetime.now(tz=datetime.timezone.utc)

        upsert_sql = text(
            """
            INSERT INTO trading_signals
                (strategy_id, pair, timeframe, direction, confidence_score,
                 signal_source, signal_at, created_at)
            VALUES
                (:strategy_id, :pair, :timeframe, :direction, :confidence_score,
                 :signal_source, :signal_at, :created_at)
            ON CONFLICT (strategy_id, pair, timeframe) WHERE signal_source = 'realtime'
            DO UPDATE SET
                direction = EXCLUDED.direction,
                confidence_score = EXCLUDED.confidence_score,
                signal_source = EXCLUDED.signal_source,
                signal_at = EXCLUDED.signal_at,
                created_at = EXCLUDED.created_at
            """
        )

        session.execute(
            upsert_sql,
            {
                "strategy_id": strategy_id,
                "pair": pair,
                "timeframe": timeframe,
                "direction": direction_enum.value,
                "confidence_score": signal_data.confidence_score,
                "signal_source": signal_data.signal_source,
                "signal_at": signal_data.signal_at,
                "created_at": now,
            },
        )

    def _update_redis_cache(
        self,
        strategy_id: int,
        pair: str,
        timeframe: str,
        signal_data: SignalData,
    ) -> None:
        """将最新信号写入 Redis 缓存（TTL: 3600s）。

        写入失败时静默降级（记录 WARNING），不影响主流程（需求 3.3）。
        """
        try:
            redis_client = get_redis_client()
            cache_key = f"signal:{strategy_id}"

            # 读取现有缓存数据
            existing_raw = redis_client.get(cache_key)
            if existing_raw:
                try:
                    existing_data = json.loads(existing_raw)
                except (json.JSONDecodeError, ValueError):
                    existing_data = {"signals": []}
            else:
                existing_data = {"signals": []}

            # 更新或插入该 (pair, timeframe) 的信号
            signals_list = existing_data.get("signals", [])
            updated = False
            for i, sig in enumerate(signals_list):
                if sig.get("pair") == pair and sig.get("timeframe") == timeframe:
                    signals_list[i] = {
                        "strategy_id": strategy_id,
                        "pair": pair,
                        "timeframe": timeframe,
                        "direction": signal_data.direction,
                        "confidence_score": signal_data.confidence_score,
                        "signal_at": signal_data.signal_at.isoformat(),
                        "created_at": datetime.datetime.now(tz=datetime.timezone.utc).isoformat(),
                    }
                    updated = True
                    break

            if not updated:
                signals_list.append(
                    {
                        "strategy_id": strategy_id,
                        "pair": pair,
                        "timeframe": timeframe,
                        "direction": signal_data.direction,
                        "confidence_score": signal_data.confidence_score,
                        "signal_at": signal_data.signal_at.isoformat(),
                        "created_at": datetime.datetime.now(tz=datetime.timezone.utc).isoformat(),
                    }
                )

            existing_data["signals"] = signals_list
            existing_data["last_updated_at"] = datetime.datetime.now(tz=datetime.timezone.utc).isoformat()

            redis_client.set(
                cache_key,
                json.dumps(existing_data),
                ex=_SIGNAL_CACHE_TTL,
            )

        except Exception as exc:
            logger.warning(
                "Redis 信号缓存更新失败，静默降级",
                strategy_id=strategy_id,
                pair=pair,
                timeframe=timeframe,
                error=str(exc),
            )

    def _get_session(self) -> Any:
        """获取同步数据库 Session（可 Mock 的方法）。"""
        from src.workers.db import SyncSessionLocal

        return SyncSessionLocal()
