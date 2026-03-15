"""一键初始化全量种子数据：策略 → 信号 → 回测结果 → 绩效指标。

基于真实 OHLCV 数据运行 10 个策略，从信号中计算回测级指标，
原子性写入所有关联表（strategies、trading_signals、backtest_tasks、
backtest_results、strategy_pair_metrics），并更新策略表汇总指标。

用法：
    uv run python -m src.freqtrade_bridge.seeds.seed_all
"""

import datetime
import math
from collections import defaultdict
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from src.core.enums import DataSource, TaskStatus
from src.freqtrade_bridge.seeds.seed_signals import (
    _PAIR_FILES,
    _STRATEGIES,
    _extract_all_signals,
    _load_strategy_class,
    _run_strategy,
)
from src.freqtrade_bridge.seeds.seed_strategies import seed_strategies
from src.models.backtest import BacktestResult, BacktestTask
from src.models.signal import TradingSignal
from src.models.strategy import Strategy
from src.models.strategy_pair_metrics import StrategyPairMetrics

_TIMEFRAME = "4h"
_UTC = datetime.timezone.utc


# ---------------------------------------------------------------------------
# 指标计算
# ---------------------------------------------------------------------------


def _compute_pair_metrics(signals: list[dict[str, Any]]) -> dict[str, Any]:
    """从信号列表中计算一个交易对的五个绩效指标。

    使用买入/卖出信号对模拟交易，计算：
    - total_return: 累计收益率
    - profit_factor: 盈利交易收益总和 / 亏损交易亏损总和
    - max_drawdown: 最大回撤
    - sharpe_ratio: 夏普比率近似值
    - trade_count: 完成的交易数
    """
    if len(signals) < 2:
        return {
            "total_return": 0.0,
            "profit_factor": 1.0,
            "max_drawdown": 0.0,
            "sharpe_ratio": 0.0,
            "trade_count": 0,
        }

    # 按时间排序
    sorted_signals = sorted(signals, key=lambda s: s["signal_at"])

    # 配对交易：buy → sell 为一笔完整交易
    trades: list[dict[str, float]] = []
    pending_buy: dict[str, Any] | None = None

    for sig in sorted_signals:
        if sig["direction"] == "buy" and pending_buy is None:
            pending_buy = sig
        elif sig["direction"] == "sell" and pending_buy is not None:
            entry_price = pending_buy["entry_price"]
            exit_price = sig["entry_price"]
            if entry_price > 0:
                pnl = (exit_price - entry_price) / entry_price
                trades.append({"pnl": pnl, "entry": entry_price, "exit": exit_price})
            pending_buy = None

    trade_count = len(trades)
    if trade_count == 0:
        return {
            "total_return": 0.0,
            "profit_factor": 1.0,
            "max_drawdown": 0.0,
            "sharpe_ratio": 0.0,
            "trade_count": 0,
        }

    # total_return: 累乘
    cumulative = 1.0
    peak = 1.0
    max_dd = 0.0
    returns = []
    gross_profit = 0.0
    gross_loss = 0.0

    for t in trades:
        pnl = t["pnl"]
        cumulative *= 1 + pnl
        returns.append(pnl)

        if pnl > 0:
            gross_profit += pnl
        else:
            gross_loss += abs(pnl)

        if cumulative > peak:
            peak = cumulative
        dd = (peak - cumulative) / peak if peak > 0 else 0
        if dd > max_dd:
            max_dd = dd

    total_return = cumulative - 1.0

    # profit_factor
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else (10.0 if gross_profit > 0 else 1.0)

    # sharpe_ratio (年化近似，4h 周期 → 每年约 2190 根 K 线)
    if len(returns) > 1:
        mean_ret = sum(returns) / len(returns)
        var = sum((r - mean_ret) ** 2 for r in returns) / (len(returns) - 1)
        std_ret = math.sqrt(var) if var > 0 else 0.001
        sharpe_ratio = (mean_ret / std_ret) * math.sqrt(min(len(returns), 252))
    else:
        sharpe_ratio = 0.0

    return {
        "total_return": round(total_return, 6),
        "profit_factor": round(min(profit_factor, 9999.0), 4),
        "max_drawdown": round(max_dd, 6),
        "sharpe_ratio": round(max(min(sharpe_ratio, 9999.0), -9999.0), 4),
        "trade_count": trade_count,
    }


def _compute_strategy_aggregate(
    all_pair_metrics: list[dict[str, Any]],
    all_pair_signals: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    """汇总所有交易对指标到策略级。"""
    if not all_pair_metrics:
        return {"trade_count": 0, "max_drawdown": 0.0, "sharpe_ratio": 0.0, "win_rate": 0.0}

    total_trades = sum(m["trade_count"] for m in all_pair_metrics)
    max_dd = max((m["max_drawdown"] for m in all_pair_metrics), default=0.0)

    # 加权夏普比率
    weighted_sharpe = 0.0
    if total_trades > 0:
        for m in all_pair_metrics:
            weighted_sharpe += m["sharpe_ratio"] * m["trade_count"]
        weighted_sharpe /= total_trades

    # 胜率：从所有交易对的信号对中统计
    total_wins = 0
    total_completed = 0
    for pair, sigs in all_pair_signals.items():
        sorted_sigs = sorted(sigs, key=lambda s: s["signal_at"])
        pending_buy = None
        for sig in sorted_sigs:
            if sig["direction"] == "buy" and pending_buy is None:
                pending_buy = sig
            elif sig["direction"] == "sell" and pending_buy is not None:
                if sig["entry_price"] > pending_buy["entry_price"]:
                    total_wins += 1
                total_completed += 1
                pending_buy = None

    win_rate = total_wins / total_completed if total_completed > 0 else 0.0

    return {
        "trade_count": total_trades,
        "max_drawdown": round(max_dd, 6),
        "sharpe_ratio": round(weighted_sharpe, 4),
        "win_rate": round(win_rate, 4),
    }


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------


def seed_all(session: Session) -> dict[str, int]:
    """一键初始化全量种子数据。

    执行顺序：
    1. 幂等写入 10 个策略
    2. 对每个策略 × 交易对运行策略，提取信号
    3. 从信号计算绩效指标
    4. 写入 trading_signals、backtest_tasks、backtest_results、strategy_pair_metrics
    5. 更新策略表汇总指标

    Args:
        session: SQLAlchemy 同步 Session

    Returns:
        各表写入数量统计字典
    """
    now = datetime.datetime.now(tz=_UTC)
    today = now.date()

    counts = {
        "strategies": 0,
        "signals": 0,
        "backtest_tasks": 0,
        "backtest_results": 0,
        "pair_metrics": 0,
    }

    # ---- 1. 策略种子 ----
    print("=" * 60)
    print("📦 阶段 1/5：写入策略种子数据")
    print("=" * 60)
    counts["strategies"] = seed_strategies(session)
    print(f"  ✅ 新增 {counts['strategies']} 个策略\n")

    # 获取策略映射
    strategy_map: dict[str, int] = {
        row.name: row.id
        for row in session.execute(sa.select(Strategy.name, Strategy.id)).fetchall()
    }

    # ---- 2. 运行策略并提取信号 ----
    print("=" * 60)
    print("📊 阶段 2/5：运行策略提取信号")
    print("=" * 60)

    # strategy_class_name → { pair → [signals] }
    all_strategy_signals: dict[str, dict[str, list[dict[str, Any]]]] = {}

    for filename, class_name in _STRATEGIES:
        strategy_id = strategy_map.get(class_name)
        if strategy_id is None:
            print(f"  ⚠ 跳过 {class_name}：数据库中未找到")
            continue

        print(f"  🔄 {class_name} (id={strategy_id})")

        try:
            strategy_class = _load_strategy_class(filename, class_name)
        except Exception as e:
            print(f"    ❌ 加载失败: {e}")
            continue

        pair_signals: dict[str, list[dict[str, Any]]] = {}

        for pair, data_file in _PAIR_FILES.items():
            if not data_file.exists():
                print(f"    ⚠ 数据文件不存在: {data_file}")
                continue

            import pandas as pd

            df = pd.read_feather(data_file)

            try:
                df_result = _run_strategy(strategy_class, df, pair)
            except Exception as e:
                print(f"    ❌ {pair} 运行失败: {e}")
                continue

            signals = _extract_all_signals(df_result, pair, strategy_id)
            pair_signals[pair] = signals

            # 写入 trading_signals
            for sig_data in signals:
                indicator_vals = sig_data.pop("indicator_values", {})
                signal = TradingSignal(**sig_data, indicator_values=indicator_vals)
                session.add(signal)
                counts["signals"] += 1
                # 恢复 indicator_values 用于后续指标计算
                sig_data["indicator_values"] = indicator_vals

            print(f"    📈 {pair}: {len(signals)} 条信号")

        all_strategy_signals[class_name] = pair_signals

    session.flush()
    print(f"  ✅ 共提取 {counts['signals']} 条信号\n")

    # ---- 3. 计算绩效指标 ----
    print("=" * 60)
    print("📐 阶段 3/5：计算绩效指标")
    print("=" * 60)

    # strategy_class_name → { pair → metrics_dict }
    all_pair_metrics: dict[str, list[dict[str, Any]]] = defaultdict(list)
    pair_level_metrics: dict[str, dict[str, dict[str, Any]]] = {}

    for class_name, pair_signals in all_strategy_signals.items():
        pair_level_metrics[class_name] = {}
        for pair, signals in pair_signals.items():
            metrics = _compute_pair_metrics(signals)
            pair_level_metrics[class_name][pair] = metrics
            all_pair_metrics[class_name].append(metrics)
            print(
                f"  {class_name} / {pair}: "
                f"trades={metrics['trade_count']}, "
                f"return={metrics['total_return']:.4f}, "
                f"sharpe={metrics['sharpe_ratio']:.2f}"
            )

    print()

    # ---- 4. 写入 backtest_tasks + backtest_results ----
    print("=" * 60)
    print("💾 阶段 4/5：写入回测记录与绩效指标")
    print("=" * 60)

    for class_name, pair_signals in all_strategy_signals.items():
        strategy_id = strategy_map[class_name]
        agg = _compute_strategy_aggregate(
            all_pair_metrics[class_name], pair_signals
        )

        # 创建 BacktestTask
        task = BacktestTask(
            strategy_id=strategy_id,
            scheduled_date=today,
            status=TaskStatus.DONE,
            timerange="20200101-",
            result_json={"seeded": True, "strategy": class_name},
        )
        session.add(task)
        session.flush()
        counts["backtest_tasks"] += 1

        # 确定时间范围（从信号中取最早和最晚时间）
        all_signal_times = []
        for sigs in pair_signals.values():
            for s in sigs:
                all_signal_times.append(s["signal_at"])

        if all_signal_times:
            period_start = min(all_signal_times)
            period_end = max(all_signal_times)
            # 确保时区
            if hasattr(period_start, "tzinfo") and period_start.tzinfo is None:
                period_start = period_start.replace(tzinfo=_UTC)
            if hasattr(period_end, "tzinfo") and period_end.tzinfo is None:
                period_end = period_end.replace(tzinfo=_UTC)
        else:
            period_start = now - datetime.timedelta(days=365)
            period_end = now

        # 创建 BacktestResult
        result = BacktestResult(
            strategy_id=strategy_id,
            task_id=task.id,
            total_return=agg.get("sharpe_ratio", 0.0),  # 使用汇总值
            annual_return=0.0,
            sharpe_ratio=agg["sharpe_ratio"],
            max_drawdown=agg["max_drawdown"],
            trade_count=agg["trade_count"],
            win_rate=agg["win_rate"],
            period_start=period_start,
            period_end=period_end,
        )
        # total_return 应该用所有交易对的加权平均
        weighted_return = 0.0
        total_tc = sum(m["trade_count"] for m in all_pair_metrics[class_name])
        if total_tc > 0:
            for m in all_pair_metrics[class_name]:
                weighted_return += m["total_return"] * m["trade_count"]
            weighted_return /= total_tc
        result.total_return = round(weighted_return, 6)

        session.add(result)
        session.flush()
        counts["backtest_results"] += 1

        # 写入 strategy_pair_metrics（每个交易对一条记录）
        for pair, metrics in pair_level_metrics.get(class_name, {}).items():
            spm = StrategyPairMetrics(
                strategy_id=strategy_id,
                pair=pair,
                timeframe=_TIMEFRAME,
                total_return=metrics["total_return"],
                profit_factor=metrics["profit_factor"],
                max_drawdown=metrics["max_drawdown"],
                sharpe_ratio=metrics["sharpe_ratio"],
                trade_count=metrics["trade_count"],
                data_source=DataSource.BACKTEST,
                last_updated_at=now,
            )
            session.add(spm)
            counts["pair_metrics"] += 1

        # 更新策略表汇总指标
        strategy = session.get(Strategy, strategy_id)
        if strategy is not None:
            strategy.trade_count = agg["trade_count"]
            strategy.max_drawdown = agg["max_drawdown"]
            strategy.sharpe_ratio = agg["sharpe_ratio"]
            strategy.win_rate = agg["win_rate"]

        print(
            f"  ✅ {class_name}: "
            f"task_id={task.id}, "
            f"trades={agg['trade_count']}, "
            f"win_rate={agg['win_rate']:.2%}, "
            f"pairs={len(pair_level_metrics.get(class_name, {}))}"
        )

    session.flush()
    print()

    # ---- 5. 提交 ----
    print("=" * 60)
    print("🚀 阶段 5/5：提交事务")
    print("=" * 60)
    session.commit()
    print("  ✅ 事务提交成功\n")

    return counts


def _clear_all(session: Session) -> dict[str, int]:
    """清空所有业务表数据（按外键顺序）。"""
    tables = [
        "strategy_pair_metrics",
        "backtest_results",
        "backtest_tasks",
        "trading_signals",
        "strategies",
    ]
    deleted = {}
    for table in tables:
        count = session.execute(sa.text(f"DELETE FROM {table}")).rowcount  # noqa: S608
        deleted[table] = count
        print(f"  🗑 {table}: 删除 {count} 条")
    session.commit()
    return deleted


if __name__ == "__main__":
    from src.core.app_settings import get_settings

    settings = get_settings()
    engine = sa.create_engine(settings.database_sync_url)

    with Session(engine) as session:
        print("🧹 清空旧数据...\n")
        _clear_all(session)
        print()

        counts = seed_all(session)

        print("=" * 60)
        print("📋 种子数据写入统计")
        print("=" * 60)
        for table, count in counts.items():
            print(f"  {table}: {count}")
        print(f"\n✅ 全量种子数据初始化完成！")
