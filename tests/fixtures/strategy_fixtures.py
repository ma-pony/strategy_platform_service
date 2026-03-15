"""策略种子数据 pytest fixture。

提供与 seed_strategies.py 等效的测试数据，用于测试环境。
"""

from types import SimpleNamespace

import pytest


# 与 seed_strategies.py 中的 SEED_STRATEGIES 完全一致
STRATEGY_SEED_DATA = [
    {"name": "TurtleTradingStrategy", "description": "海龟交易策略", "strategy_type": "trend_following"},
    {"name": "BollingerBandMeanReversionStrategy", "description": "布林带均值回归策略", "strategy_type": "mean_reversion"},
    {"name": "RsiMeanReversionStrategy", "description": "RSI 均值回归策略", "strategy_type": "mean_reversion"},
    {"name": "MacdTrendFollowingStrategy", "description": "MACD 趋势策略", "strategy_type": "trend_following"},
    {"name": "IchimokuCloudTrendStrategy", "description": "一目均衡表趋势策略", "strategy_type": "trend_following"},
    {"name": "ParabolicSarTrendStrategy", "description": "抛物线 SAR 趋势策略", "strategy_type": "trend_following"},
    {"name": "KeltnerChannelBreakoutStrategy", "description": "凯尔特纳通道突破策略", "strategy_type": "breakout"},
    {"name": "AroonTrendSystemStrategy", "description": "Aroon 趋势识别策略", "strategy_type": "trend_following"},
    {"name": "Nr7VolatilityContractionBreakoutStrategy", "description": "NR7 窄幅突破策略", "strategy_type": "breakout"},
    {"name": "StochasticOscillatorReversalStrategy", "description": "随机指标反转策略", "strategy_type": "mean_reversion"},
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
