"""基于真实 OHLCV 数据运行策略并提取信号的种子脚本。

使用 freqtrade 策略的 populate_indicators / populate_entry_trend / populate_exit_trend
在真实 K 线数据上运行，提取所有入场/出场信号写入 trading_signals 表。

用法：
    uv run python -m src.freqtrade_bridge.seeds.seed_signals
"""

import math
from datetime import timezone
from pathlib import Path
from typing import Any

import pandas as pd
import sqlalchemy as sa
from sqlalchemy.orm import Session

from src.models.signal import TradingSignal

# 真实 OHLCV 数据路径（freqtrade download-data 输出目录）
_DATA_DIR = Path("/tmp/freqtrade_data/binance")

# 排名前五的币种及对应数据文件
_PAIR_FILES = {
    "BTC/USDT": _DATA_DIR / "BTC_USDT-4h.feather",
    "ETH/USDT": _DATA_DIR / "ETH_USDT-4h.feather",
    "BNB/USDT": _DATA_DIR / "BNB_USDT-4h.feather",
    "SOL/USDT": _DATA_DIR / "SOL_USDT-4h.feather",
    "XRP/USDT": _DATA_DIR / "XRP_USDT-4h.feather",
}

# 策略文件所在目录
_STRATEGIES_DIR = Path(__file__).resolve().parent.parent / "strategies"

# 10 个策略：(文件名, 类名)
_STRATEGIES = [
    ("turtle_trading.py", "TurtleTradingStrategy"),
    ("bollinger_mean_reversion.py", "BollingerBandMeanReversionStrategy"),
    ("rsi_mean_reversion.py", "RsiMeanReversionStrategy"),
    ("macd_trend.py", "MacdTrendFollowingStrategy"),
    ("ichimoku_trend.py", "IchimokuCloudTrendStrategy"),
    ("parabolic_sar_trend.py", "ParabolicSarTrendStrategy"),
    ("keltner_breakout.py", "KeltnerChannelBreakoutStrategy"),
    ("aroon_trend.py", "AroonTrendSystemStrategy"),
    ("nr7_breakout.py", "Nr7VolatilityContractionBreakoutStrategy"),
    ("stochastic_reversal.py", "StochasticOscillatorReversalStrategy"),
]


def _load_strategy_class(filename: str, class_name: str) -> Any:
    """动态加载策略类。"""
    import importlib.util
    import sys

    file_path = _STRATEGIES_DIR / filename
    spec = importlib.util.spec_from_file_location(class_name, str(file_path))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载策略: {file_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[class_name] = module
    spec.loader.exec_module(module)
    return getattr(module, class_name)


def _run_strategy(strategy_class: Any, df: pd.DataFrame, pair: str) -> pd.DataFrame:
    """在 DataFrame 上运行策略的三个核心方法。"""
    strategy = strategy_class(config={"stake_currency": "USDT"})
    metadata = {"pair": pair}

    df_copy = df.copy()
    df_copy = strategy.populate_indicators(df_copy, metadata)
    df_copy = strategy.populate_entry_trend(df_copy, metadata)
    df_copy = strategy.populate_exit_trend(df_copy, metadata)
    return df_copy


def _extract_all_signals(
    df: pd.DataFrame,
    pair: str,
    strategy_id: int,
) -> list[dict[str, Any]]:
    """从策略输出 DataFrame 中提取边沿触发信号（方向变化时才产生新信号）。

    只在信号方向发生变化的 K 线上生成一条信号记录，
    连续相同方向的 K 线不重复生成，确保每条信号代表一个离散交易决策。
    """
    signals = []
    prev_direction: str | None = None

    for _, row in df.iterrows():
        enter_long = row.get("enter_long", 0)
        exit_long = row.get("exit_long", 0)
        enter_short = row.get("enter_short", 0)
        exit_short = row.get("exit_short", 0)

        # 确定方向
        if enter_long == 1:
            direction = "buy"
        elif enter_short == 1:
            direction = "sell"
        elif exit_long == 1:
            direction = "sell"
        elif exit_short == 1:
            direction = "buy"
        else:
            prev_direction = None  # 重置，下次出信号视为新信号
            continue

        # 边沿触发：只有方向变化时才产生新信号
        if direction == prev_direction:
            continue
        prev_direction = direction

        close_price = float(row["close"])
        volume = float(row["volume"])

        # ATR 止损止盈
        atr = row.get("atr", None)
        if atr is not None and not math.isnan(float(atr)):
            atr_val = float(atr)
            stop_loss = close_price - 2.0 * atr_val if direction == "buy" else close_price + 2.0 * atr_val
            take_profit = close_price + 3.0 * atr_val if direction == "buy" else close_price - 3.0 * atr_val
        else:
            factor = 1 if direction == "buy" else -1
            stop_loss = close_price * (1 - factor * 0.03)
            take_profit = close_price * (1 + factor * 0.05)

        # 信号强度：入场信号 > 出场信号
        is_entry = enter_long == 1 or enter_short == 1
        signal_strength = 0.75 if is_entry else 0.50

        # 置信度：基于成交量确认 + 信号类型 + 波动稳定性
        confidence = 0.50
        # 成交量确认：放量信号更可信
        volume_mean = row.get("volume_mean", None)
        if volume_mean is not None and not math.isnan(float(volume_mean)) and float(volume_mean) > 0:
            vol_ratio = volume / float(volume_mean)
            if vol_ratio > 1.5:
                confidence += 0.20
            elif vol_ratio > 1.0:
                confidence += 0.10
        # 入场信号比出场信号置信度更高
        if is_entry:
            confidence += 0.10
        # ATR 相对价格越低说明市场越平稳，信号越可靠
        if atr is not None and not math.isnan(float(atr)):
            atr_pct = float(atr) / close_price
            if atr_pct < 0.02:
                confidence += 0.10
            elif atr_pct < 0.04:
                confidence += 0.05
        confidence = min(confidence, 0.95)

        # 收集指标快照
        _skip_cols = {
            "date", "open", "high", "low", "close", "volume",
            "enter_long", "exit_long", "enter_short", "exit_short",
            "enter_tag", "exit_tag",
        }
        indicator_values: dict[str, Any] = {}
        for col in df.columns:
            if col in _skip_cols:
                continue
            val = row.get(col)
            if val is None:
                continue
            try:
                fval = float(val)
                if not math.isnan(fval) and not math.isinf(fval):
                    indicator_values[col] = round(fval, 6)
            except (TypeError, ValueError):
                pass

        # 波动率：基于前 20 根 K 线
        idx = df.index.get_loc(row.name)
        if idx >= 20:
            recent = df.iloc[idx - 19 : idx + 1]["close"]
            returns = recent.pct_change().dropna()
            volatility = float(returns.std()) if len(returns) > 1 else 0.0
        else:
            volatility = 0.0

        signal_at = row["date"]
        if signal_at.tzinfo is None:
            signal_at = signal_at.replace(tzinfo=timezone.utc)

        signals.append({
            "strategy_id": strategy_id,
            "pair": pair,
            "direction": direction,
            "confidence_score": round(confidence, 4),
            "signal_at": signal_at,
            "signal_source": "backtest",
            "entry_price": round(close_price, 2),
            "stop_loss": round(stop_loss, 2),
            "take_profit": round(take_profit, 2),
            "timeframe": "4h",
            "signal_strength": round(signal_strength, 4),
            "volume": round(volume, 2),
            "volatility": round(volatility, 8),
            "indicator_values": indicator_values,
        })

    return signals


def seed_signals(session: Session) -> int:
    """运行所有策略并将真实信号写入数据库。"""
    from src.models.strategy import Strategy

    # 获取策略 ID 映射
    strategies = {
        row.name: row.id
        for row in session.execute(sa.select(Strategy.name, Strategy.id)).fetchall()
    }

    total_inserted = 0

    for filename, class_name in _STRATEGIES:
        strategy_id = strategies.get(class_name)
        if strategy_id is None:
            print(f"  ⚠ 跳过 {class_name}：数据库中未找到")
            continue

        print(f"  🔄 运行策略: {class_name} (id={strategy_id})")

        try:
            strategy_class = _load_strategy_class(filename, class_name)
        except Exception as e:
            print(f"    ❌ 加载失败: {e}")
            continue

        strategy_signals = 0
        for pair, data_file in _PAIR_FILES.items():
            if not data_file.exists():
                print(f"    ⚠ 数据文件不存在: {data_file}")
                continue

            df = pd.read_feather(data_file)

            try:
                df_result = _run_strategy(strategy_class, df, pair)
            except Exception as e:
                print(f"    ❌ {pair} 运行失败: {e}")
                continue

            signals = _extract_all_signals(df_result, pair, strategy_id)

            for sig_data in signals:
                indicator_vals = sig_data.pop("indicator_values", {})
                signal = TradingSignal(**sig_data, indicator_values=indicator_vals)
                session.add(signal)
                total_inserted += 1
                strategy_signals += 1

        print(f"    ✅ {class_name}: {strategy_signals} 条信号")

    if total_inserted > 0:
        session.commit()

    return total_inserted


if __name__ == "__main__":
    from src.core.app_settings import get_settings

    settings = get_settings()
    engine = sa.create_engine(settings.database_sync_url)

    with Session(engine) as session:
        # 先清空旧信号
        deleted = session.execute(sa.text("DELETE FROM trading_signals")).rowcount
        session.commit()
        print(f"🗑 已清除 {deleted} 条旧信号")

        count = seed_signals(session)
        print(f"\n✅ 共插入 {count} 条真实回测信号")
