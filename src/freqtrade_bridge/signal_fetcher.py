"""freqtrade 信号获取进程池封装。

通过 ProcessPoolExecutor（max_workers 由 SIGNAL_MAX_WORKERS 环境变量控制，默认 2）
在独立进程中调用 freqtrade 信号逻辑，避免污染 FastAPI 主进程的事件循环。

注意：fetch_signals 为异步函数，供异步上下文调用；
      fetch_signals_sync 为同步函数，供 Celery Worker 直接调用（Worker 无事件循环）。

错误处理：
  - 失败时抛出 FreqtradeExecutionError，不向调用方暴露 freqtrade 内部错误细节
"""

import asyncio
import datetime
import os
from concurrent.futures import ProcessPoolExecutor
from typing import Any

import structlog

from src.freqtrade_bridge.exceptions import FreqtradeExecutionError

logger = structlog.get_logger(__name__)

# 最大并发进程数通过环境变量 SIGNAL_MAX_WORKERS 配置，默认 2
_MAX_WORKERS = int(os.environ.get("SIGNAL_MAX_WORKERS", "2"))

# 共享进程池，限制最大并发，避免耗尽系统资源
_executor = ProcessPoolExecutor(max_workers=_MAX_WORKERS)


# ─────────────────────────────────────────────
# 内部 Helper 函数
# ─────────────────────────────────────────────


def _lookup_strategy(strategy_name: str) -> dict[str, Any]:
    """查找策略注册表条目。

    Args:
        strategy_name: 策略名称（数据库 Strategy.name 或类名）

    Returns:
        StrategyRegistryEntry 字典

    Raises:
        UnsupportedStrategyError: 策略不存在于注册表
    """
    from src.freqtrade_bridge.strategy_registry import lookup

    return lookup(strategy_name)


def _build_ohlcv_dataframe(pair: str, timeframe: str = "1h", limit: int = 100) -> Any:
    """构建 OHLCV DataFrame 用于策略指标计算。

    MVP 实现：使用合成数据生成 OHLCV DataFrame，避免依赖实时交易所数据。
    生产环境可替换为 ccxt 真实数据拉取。

    Args:
        pair: 交易对（如 "BTC/USDT"）
        timeframe: 时间周期（如 "1h"）
        limit: K 线数量

    Returns:
        包含 date/open/high/low/close/volume 列的 pandas DataFrame
    """
    import numpy as np
    import pandas as pd

    # 基于交易对名称生成确定性种子，保证同一交易对数据一致
    seed = hash(pair) % (2**31)
    rng = np.random.default_rng(abs(seed))

    # 模拟基础价格（根据常见交易对粗略估算）
    base_prices = {
        "BTC/USDT": 30000.0,
        "ETH/USDT": 2000.0,
        "BNB/USDT": 300.0,
        "SOL/USDT": 100.0,
    }
    base_price = base_prices.get(pair, 1000.0)

    closes = base_price + rng.uniform(-base_price * 0.02, base_price * 0.02, limit).cumsum()
    closes = np.abs(closes)  # 避免负价格

    highs = closes * (1 + rng.uniform(0.001, 0.01, limit))
    lows = closes * (1 - rng.uniform(0.001, 0.01, limit))
    opens = closes * (1 + rng.uniform(-0.005, 0.005, limit))
    volumes = rng.uniform(100, 2000, limit)

    df = pd.DataFrame(
        {
            "date": pd.date_range(
                end=datetime.datetime.now(tz=datetime.timezone.utc),
                periods=limit,
                freq="1h",
            ),
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": volumes,
        }
    )
    return df


def _run_strategy_on_df(strategy_class: Any, df: Any, pair: str) -> Any:
    """在 DataFrame 上运行策略，生成技术指标和买卖信号。

    Args:
        strategy_class: freqtrade IStrategy 子类（未实例化的类）
        df: OHLCV DataFrame
        pair: 交易对

    Returns:
        填充了指标列和信号列（enter_long/exit_long）的 DataFrame
    """
    # 实例化策略（freqtrade IStrategy 构造函数需要 config 参数）
    strategy = strategy_class(config={})

    metadata = {"pair": pair}

    # 执行策略的三个核心方法
    df = strategy.populate_indicators(df, metadata)
    df = strategy.populate_entry_trend(df, metadata)
    df = strategy.populate_exit_trend(df, metadata)

    return df


def _extract_signal_from_df(df: Any, pair: str, timeframe: str = "1h") -> dict[str, Any]:
    """从策略输出 DataFrame 的最后一行提取信号数据。

    Args:
        df: 经策略处理的 DataFrame（含指标列和信号列）
        pair: 交易对
        timeframe: 时间周期

    Returns:
        包含 11 个字段的信号字典
    """
    import math

    last_row = df.iloc[-1]

    # 判断信号方向（优先级：入场 > 出场，与 seed_signals 一致）
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

    close_price = float(last_row["close"])
    volume = float(last_row["volume"])

    # 计算止损/止盈（基于 ATR 或固定比例，区分方向）
    atr = last_row.get("atr", None)
    if atr is not None and not math.isnan(float(atr)):
        atr_val = float(atr)
        if direction == "buy":
            stop_loss = close_price - 2.0 * atr_val
            take_profit = close_price + 3.0 * atr_val
        else:
            stop_loss = close_price + 2.0 * atr_val
            take_profit = close_price - 3.0 * atr_val
    else:
        factor = 1 if direction == "buy" else -1
        stop_loss = close_price * (1 - factor * 0.03)
        take_profit = close_price * (1 + factor * 0.05)

    # 信号强度与置信度
    is_entry = enter_long == 1 or enter_short == 1
    if direction == "hold":
        confidence_score = 0.0
        signal_strength = 0.0
    else:
        signal_strength = 0.75 if is_entry else 0.50
        # 置信度：基于成交量确认 + 信号类型 + 波动稳定性
        confidence_score = 0.50
        volume_mean = last_row.get("volume_mean", None)
        if volume_mean is not None and not math.isnan(float(volume_mean)) and float(volume_mean) > 0:
            vol_ratio = volume / float(volume_mean)
            if vol_ratio > 1.5:
                confidence_score += 0.20
            elif vol_ratio > 1.0:
                confidence_score += 0.10
        if is_entry:
            confidence_score += 0.10
        if atr is not None and not math.isnan(float(atr)):
            atr_pct = float(atr) / close_price
            if atr_pct < 0.02:
                confidence_score += 0.10
            elif atr_pct < 0.04:
                confidence_score += 0.05
        confidence_score = min(confidence_score, 0.95)

    # 收集技术指标快照（过滤掉 OHLCV 基础列和信号列，保留指标列）
    _base_cols = {
        "date",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "enter_long",
        "exit_long",
        "enter_short",
        "exit_short",
        "enter_tag",
        "exit_tag",
    }
    indicator_values: dict[str, Any] = {}
    for col in df.columns:
        if col in _base_cols:
            continue
        val = last_row.get(col)
        if val is None:
            continue
        try:
            fval = float(val)
            if not math.isnan(fval) and not math.isinf(fval):
                indicator_values[col] = round(fval, 6)
        except (TypeError, ValueError):
            pass

    # 计算波动率（最近 20 根 K 线收益率标准差）
    try:
        recent_closes = df["close"].tail(20)
        returns = recent_closes.pct_change().dropna()
        volatility = float(returns.std()) if len(returns) > 1 else 0.0
        if math.isnan(volatility):
            volatility = 0.0
    except Exception:
        volatility = 0.0

    return {
        "pair": pair,
        "direction": direction,
        "confidence_score": confidence_score,
        "entry_price": round(close_price, 6),
        "stop_loss": round(stop_loss, 6),
        "take_profit": round(take_profit, 6),
        "indicator_values": indicator_values,
        "timeframe": timeframe,
        "signal_strength": signal_strength,
        "volume": round(volume, 6),
        "volatility": round(volatility, 8),
        "signal_at": datetime.datetime.now(tz=datetime.timezone.utc).isoformat(),
    }


def _load_strategy_class(entry: dict[str, Any]) -> Any:
    """从策略注册表条目动态导入策略类。

    Args:
        entry: StrategyRegistryEntry，含 class_name 和 file_path

    Returns:
        freqtrade IStrategy 子类（未实例化）

    Raises:
        FreqtradeExecutionError: 策略文件无法加载
    """
    import importlib.util
    import sys

    file_path = entry["file_path"]
    class_name = entry["class_name"]

    spec = importlib.util.spec_from_file_location(class_name, str(file_path))
    if spec is None or spec.loader is None:
        raise FreqtradeExecutionError(f"无法加载策略文件，类名: {class_name}，路径: {file_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[class_name] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return getattr(module, class_name)


def _fetch_signals_sync(strategy: str, pair: str) -> dict[str, Any]:
    """在子进程中同步调用 freqtrade 信号逻辑。

    此函数在 ProcessPoolExecutor 中运行，独立于主进程导入 freqtrade 模块，
    避免 GIL 争用并防止 freqtrade 污染主进程状态。

    Args:
        strategy: 策略名称（数据库 Strategy.name 或类名）
        pair: 交易对（如 "BTC/USDT"）

    Returns:
        信号字典，包含 signals 列表和 last_updated_at
    """
    try:
        # 1. 查找策略注册表
        entry = _lookup_strategy(strategy)

        # 2. 构建 OHLCV DataFrame（使用模块级函数，支持测试 Mock）
        df = _build_ohlcv_dataframe(pair=pair, timeframe="1h", limit=100)

        # 3. 动态加载策略类并在 DataFrame 上运行（使用模块级函数，支持测试 Mock）
        strategy_class = _load_strategy_class(entry)
        df_with_signals = _run_strategy_on_df(strategy_class, df, pair)

        # 4. 从最后一行提取信号数据
        signal = _extract_signal_from_df(df_with_signals, pair=pair, timeframe="1h")

        return {
            "signals": [signal],
            "last_updated_at": datetime.datetime.now(tz=datetime.timezone.utc).isoformat(),
        }

    except FreqtradeExecutionError:
        raise
    except Exception as exc:
        raise FreqtradeExecutionError(f"信号获取失败，策略: {strategy}，交易对: {pair}") from exc


def fetch_signals_sync(strategy: str, pair: str) -> dict[str, Any]:
    """同步版本的信号获取，供 Celery Worker 直接调用。

    Celery Worker 在独立进程中运行，无需通过 ProcessPoolExecutor，
    直接调用 _fetch_signals_sync 即可。

    Args:
        strategy: 策略名称（数据库 Strategy.name 或类名）
        pair: 交易对（如 "BTC/USDT"）

    Returns:
        信号字典

    Raises:
        FreqtradeExecutionError: 信号获取失败
    """
    try:
        return _fetch_signals_sync(strategy, pair)
    except FreqtradeExecutionError:
        raise
    except Exception as exc:
        logger.error(
            "unexpected error in signal fetch",
            strategy=strategy,
            pair=pair,
            exc_info=True,
        )
        raise FreqtradeExecutionError(f"信号获取发生意外错误，策略: {strategy}，交易对: {pair}") from exc


async def fetch_signals(strategy: str, pair: str) -> dict[str, Any]:
    """异步信号获取，通过 ProcessPoolExecutor 在独立进程执行。

    在异步上下文（如 FastAPI 请求处理）中调用，避免阻塞事件循环。

    Args:
        strategy: 策略名称（数据库 Strategy.name 或类名）
        pair: 交易对（如 "BTC/USDT"）

    Returns:
        信号字典

    Raises:
        FreqtradeExecutionError: 信号获取失败
    """
    loop = asyncio.get_event_loop()
    try:
        future = _executor.submit(_fetch_signals_sync, strategy, pair)
        return await loop.run_in_executor(None, future.result)
    except FreqtradeExecutionError:
        raise
    except Exception as exc:
        logger.error(
            "freqtrade signal fetch failed",
            strategy=strategy,
            pair=pair,
            exc_info=True,
        )
        raise FreqtradeExecutionError(f"信号获取失败，策略: {strategy}，交易对: {pair}") from exc
