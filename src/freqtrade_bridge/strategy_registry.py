"""策略注册表：数据库 Strategy.name ↔ freqtrade 类名 ↔ 策略文件路径 三元映射。

提供 lookup(strategy_name) 辅助函数，策略不存在时抛 UnsupportedStrategyError。
file_path 在模块加载时基于 __file__ 解析为绝对路径，进程生命周期内不可变。
"""

from pathlib import Path
from typing import TypedDict

import structlog

from src.core.exceptions import UnsupportedStrategyError

logger = structlog.get_logger(__name__)

# 策略文件所在目录
_STRATEGIES_DIR = Path(__file__).resolve().parent / "strategies"


class StrategyRegistryEntry(TypedDict):
    """策略注册表条目。"""

    class_name: str
    file_path: Path


# 全局常量：数据库 Strategy.name → StrategyRegistryEntry
STRATEGY_REGISTRY: dict[str, StrategyRegistryEntry] = {
    "TurtleTrading": StrategyRegistryEntry(
        class_name="TurtleTrading",
        file_path=_STRATEGIES_DIR / "turtle_trading.py",
    ),
    "BollingerMeanReversion": StrategyRegistryEntry(
        class_name="BollingerMeanReversion",
        file_path=_STRATEGIES_DIR / "bollinger_mean_reversion.py",
    ),
    "RsiMeanReversion": StrategyRegistryEntry(
        class_name="RsiMeanReversion",
        file_path=_STRATEGIES_DIR / "rsi_mean_reversion.py",
    ),
    "MacdTrend": StrategyRegistryEntry(
        class_name="MacdTrend",
        file_path=_STRATEGIES_DIR / "macd_trend.py",
    ),
    "IchimokuTrend": StrategyRegistryEntry(
        class_name="IchimokuTrend",
        file_path=_STRATEGIES_DIR / "ichimoku_trend.py",
    ),
    "ParabolicSarTrend": StrategyRegistryEntry(
        class_name="ParabolicSarTrend",
        file_path=_STRATEGIES_DIR / "parabolic_sar_trend.py",
    ),
    "KeltnerBreakout": StrategyRegistryEntry(
        class_name="KeltnerBreakout",
        file_path=_STRATEGIES_DIR / "keltner_breakout.py",
    ),
    "AroonTrend": StrategyRegistryEntry(
        class_name="AroonTrend",
        file_path=_STRATEGIES_DIR / "aroon_trend.py",
    ),
    "Nr7Breakout": StrategyRegistryEntry(
        class_name="Nr7Breakout",
        file_path=_STRATEGIES_DIR / "nr7_breakout.py",
    ),
    "StochasticReversal": StrategyRegistryEntry(
        class_name="StochasticReversal",
        file_path=_STRATEGIES_DIR / "stochastic_reversal.py",
    ),
}


def lookup(strategy_name: str) -> StrategyRegistryEntry:
    """查找策略注册信息。

    Args:
        strategy_name: 数据库 Strategy.name

    Returns:
        StrategyRegistryEntry，含 class_name 和 file_path

    Raises:
        UnsupportedStrategyError: 策略不在注册表中
    """
    entry = STRATEGY_REGISTRY.get(strategy_name)
    if entry is None:
        raise UnsupportedStrategyError(f"策略 '{strategy_name}' 不受支持")

    if not entry["file_path"].exists():
        logger.warning(
            "strategy file missing",
            strategy=strategy_name,
            file_path=str(entry["file_path"]),
        )

    return entry
