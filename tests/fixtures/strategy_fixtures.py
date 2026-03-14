"""策略种子数据 pytest fixture。

提供与 seed_strategies.py 等效的测试数据，用于测试环境。
"""

from types import SimpleNamespace

import pytest


# 与 seed_strategies.py 中的 SEED_STRATEGIES 完全一致
STRATEGY_SEED_DATA = [
    {"name": "TurtleTrading", "description": "海龟交易策略", "strategy_type": "trend_following"},
    {"name": "BollingerMeanReversion", "description": "布林带均值回归策略", "strategy_type": "mean_reversion"},
    {"name": "RsiMeanReversion", "description": "RSI 均值回归策略", "strategy_type": "mean_reversion"},
    {"name": "MacdTrend", "description": "MACD 趋势策略", "strategy_type": "trend_following"},
    {"name": "IchimokuTrend", "description": "一目均衡表趋势策略", "strategy_type": "trend_following"},
    {"name": "ParabolicSarTrend", "description": "抛物线 SAR 趋势策略", "strategy_type": "trend_following"},
    {"name": "KeltnerBreakout", "description": "凯尔特纳通道突破策略", "strategy_type": "breakout"},
    {"name": "AroonTrend", "description": "Aroon 趋势识别策略", "strategy_type": "trend_following"},
    {"name": "Nr7Breakout", "description": "NR7 窄幅突破策略", "strategy_type": "breakout"},
    {"name": "StochasticReversal", "description": "随机指标反转策略", "strategy_type": "mean_reversion"},
]


@pytest.fixture()
def strategy_seeds() -> list[SimpleNamespace]:
    """提供十大策略种子数据作为 SimpleNamespace 对象列表。"""
    return [
        SimpleNamespace(
            id=i + 1,
            name=data["name"],
            description=data["description"],
            strategy_type=data["strategy_type"],
            pairs=["BTC/USDT", "ETH/USDT", "BNB/USDT", "SOL/USDT"],
            config_params={},
            is_active=True,
        )
        for i, data in enumerate(STRATEGY_SEED_DATA)
    ]
