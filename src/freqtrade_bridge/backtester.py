"""freqtrade 回测子进程封装。

通过 subprocess.run 执行 freqtrade CLI，在隔离目录中运行回测任务。
应在 Celery Worker 进程中调用，禁止在 FastAPI 事件循环中直接调用。

错误处理约定：
  - 超时（>600s）→ FreqtradeTimeoutError
  - 非零退出码 → FreqtradeExecutionError
  - 原始 stderr 记录至结构化日志，不透传给调用方
"""

import json
import subprocess
import zipfile
from pathlib import Path
from typing import Any

import structlog

from src.freqtrade_bridge.exceptions import FreqtradeExecutionError, FreqtradeTimeoutError

logger = structlog.get_logger(__name__)


def run_backtest_subprocess(
    config_path: Path,
    strategy: str,
    timeout: int | None = None,
) -> dict[str, Any]:
    """在独立子进程中执行 freqtrade 回测，阻塞等待结果。

    应在 Worker 进程中调用，不可在 Web 线程中直接调用。
    任务完成或失败后，调用方有责任通过 finally 块清理隔离目录。

    Args:
        config_path: freqtrade 配置文件路径
        strategy: 策略类名（freqtrade --strategy 参数）
        timeout: 最大等待时间（秒），默认 None（无超时限制，任务运行至自然结束）

    Returns:
        freqtrade 回测结果 JSON 字典

    Raises:
        FreqtradeTimeoutError: 执行超时（仅在指定 timeout 时）
        FreqtradeExecutionError: 非零退出码或其他执行错误
    """
    task_dir = config_path.parent
    results_dir = task_dir / "results"
    results_dir.mkdir(parents=True, exist_ok=True)

    # 从配置文件中读取参数
    config_data = json.loads(config_path.read_text())
    timerange = config_data.get("timerange", "")
    datadir = config_data.get("datadir", "")
    strategy_path = config_data.get("strategy_path", "")

    cmd = [
        "freqtrade",
        "backtesting",
        "--config",
        str(config_path),
        "--strategy",
        strategy,
        "--export",
        "trades",
        "--backtest-directory",
        str(results_dir),
        "--userdir",
        str(task_dir),
    ]
    if timerange:
        cmd.extend(["--timerange", timerange])
    if datadir:
        cmd.extend(["--datadir", datadir])
    if strategy_path:
        cmd.extend(["--strategy-path", strategy_path])

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        logger.warning(
            "freqtrade backtest timeout",
            strategy=strategy,
            timeout=timeout,
        )
        raise FreqtradeTimeoutError(
            f"回测任务超时（>{timeout}s），策略: {strategy}"
        ) from exc

    if result.returncode != 0:
        logger.error(
            "freqtrade backtest failed",
            strategy=strategy,
            returncode=result.returncode,
            stderr=result.stderr[:2000],
        )
        raise FreqtradeExecutionError(
            f"回测执行失败，策略: {strategy}，退出码: {result.returncode}"
        )

    # freqtrade 将结果写入文件，从结果文件中读取
    return _parse_backtest_result(results_dir, strategy)


def _parse_backtest_result(results_dir: Path, strategy: str) -> dict[str, Any]:
    """解析 freqtrade 回测结果文件，提取核心指标。

    freqtrade 2026.x 输出 zip 格式，内含 JSON + 附件。
    JSON 结构：{ "strategy": { "<StrategyName>": { ... metrics ... } } }

    Returns:
        统一格式的回测结果字典
    """
    raw = _load_result_json(results_dir)
    if not raw:
        return {}

    # 提取策略级别数据
    strategy_data = raw.get("strategy", {}).get(strategy, {})
    if not strategy_data:
        strategies = raw.get("strategy", {})
        if strategies:
            strategy_data = next(iter(strategies.values()))

    trades = strategy_data.get("trades", [])
    total_trades = strategy_data.get("total_trades", len(trades))
    winning_trades = sum(1 for t in trades if t.get("profit_ratio", 0) > 0)

    # 将 trades 转换为信号记录
    signals = _trades_to_signals(trades)

    return {
        "total_return": strategy_data.get("profit_total", 0.0) or 0.0,
        "annual_return": strategy_data.get("profit_total_abs", 0.0) or 0.0,
        "sharpe_ratio": strategy_data.get("sharpe", 0.0) or 0.0,
        "max_drawdown": strategy_data.get("max_drawdown_abs", 0.0) or 0.0,
        "trade_count": total_trades,
        "win_rate": (winning_trades / total_trades) if total_trades > 0 else 0.0,
        "period_start": strategy_data.get("backtest_start", ""),
        "period_end": strategy_data.get("backtest_end", ""),
        "signals": signals,
    }


def _trades_to_signals(trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """将 freqtrade 回测 trades 转换为 trading_signals 格式。

    每笔 trade 的入场动作转为一条 buy/sell 信号。
    """
    signals = []
    for trade in trades:
        direction = "sell" if trade.get("is_short") else "buy"
        profit_ratio = trade.get("profit_ratio", 0.0)

        signals.append({
            "pair": trade.get("pair", "BTC/USDT"),
            "direction": direction,
            "confidence_score": min(abs(profit_ratio) * 10, 1.0) if profit_ratio else None,
            "entry_price": trade.get("open_rate"),
            "stop_loss": trade.get("stop_loss_abs"),
            "take_profit": trade.get("close_rate"),
            "timeframe": None,
            "signal_strength": profit_ratio,
            "volume": trade.get("stake_amount"),
            "volatility": None,
            "indicator_values": {
                "exit_reason": trade.get("exit_reason", ""),
                "trade_duration": trade.get("trade_duration", 0),
                "profit_abs": trade.get("profit_abs", 0),
            },
            "signal_at": trade.get("open_date", ""),
        })
    return signals


def _load_result_json(results_dir: Path) -> dict[str, Any]:
    """从 zip 或 json 文件加载回测结果。"""
    # freqtrade 2026.x: zip 格式
    zip_files = sorted(results_dir.glob("backtest-result*.zip"))
    if zip_files:
        with zipfile.ZipFile(zip_files[0]) as zf:
            json_names = [n for n in zf.namelist() if n.endswith(".json")]
            if json_names:
                content = zf.read(json_names[0])
                return json.loads(content)

    # fallback: 直接 json 文件
    json_files = sorted(results_dir.glob("backtest-result*.json"))
    # 排除 meta 文件
    json_files = [f for f in json_files if "meta" not in f.name]
    if json_files:
        return json.loads(json_files[0].read_text())

    logger.warning("no backtest result file found", results_dir=str(results_dir))
    return {}
