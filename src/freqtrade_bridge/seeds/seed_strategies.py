"""幂等策略种子数据脚本。

使用 SQLAlchemy 同步 session（psycopg2 驱动），兼容迁移脚本和 CLI 调用。
同名策略已存在则跳过，不破坏已有数据。
"""

import sqlalchemy as sa
from sqlalchemy.orm import Session

from src.models.strategy import Strategy

# 十大经典策略种子数据
SEED_STRATEGIES: list[dict[str, str]] = [
    {
        "name": "TurtleTradingStrategy",
        "description": "海龟交易策略 — 基于 Donchian 通道快慢双突破的趋势跟随系统，支持多空双向",
        "strategy_type": "trend_following",
    },
    {
        "name": "BollingerBandMeanReversionStrategy",
        "description": "布林带均值回归策略 — 基于布林带上下轨触碰的均值回归交易，支持多空双向",
        "strategy_type": "mean_reversion",
    },
    {
        "name": "RsiMeanReversionStrategy",
        "description": "RSI 均值回归策略 — 基于 RSI 超买超卖区域的反转交易，支持多空双向",
        "strategy_type": "mean_reversion",
    },
    {
        "name": "MacdTrendFollowingStrategy",
        "description": "MACD 趋势跟随策略 — 基于 MACD 金叉死叉的趋势跟随系统，支持多空双向",
        "strategy_type": "trend_following",
    },
    {
        "name": "IchimokuCloudTrendStrategy",
        "description": "一目均衡表云层趋势策略 — 基于云层突破和转换/基准线交叉的趋势跟随，支持多空双向",
        "strategy_type": "trend_following",
    },
    {
        "name": "ParabolicSarTrendStrategy",
        "description": "抛物线 SAR 趋势策略 — 基于 SAR 翻转信号的趋势跟随系统，支持多空双向",
        "strategy_type": "trend_following",
    },
    {
        "name": "KeltnerChannelBreakoutStrategy",
        "description": "凯尔特纳通道突破策略 — 基于 EMA+ATR 通道突破的动量交易系统，支持多空双向",
        "strategy_type": "breakout",
    },
    {
        "name": "AroonTrendSystemStrategy",
        "description": "Aroon 趋势系统策略 — 基于 Aroon 指标交叉和阈值过滤的趋势判断，支持多空双向",
        "strategy_type": "trend_following",
    },
    {
        "name": "Nr7VolatilityContractionBreakoutStrategy",
        "description": "NR7 波动收缩突破策略 — 基于窄幅 K 线识别和突破方向的交易系统，支持多空双向",
        "strategy_type": "breakout",
    },
    {
        "name": "StochasticOscillatorReversalStrategy",
        "description": "随机振荡器反转策略 — 基于 Stochastic K/D 交叉配合超买超卖区域的反转交易，支持多空双向",
        "strategy_type": "mean_reversion",
    },
]


def seed_strategies(session: Session) -> int:
    """幂等写入十大策略种子数据。

    已存在同名策略时跳过，返回实际新增条数。

    Args:
        session: SQLAlchemy 同步 Session

    Returns:
        新增策略数量
    """
    existing = {row[0] for row in session.execute(sa.select(Strategy.name)).fetchall()}

    inserted = 0
    for data in SEED_STRATEGIES:
        if data["name"] not in existing:
            strategy = Strategy(
                name=data["name"],
                description=data["description"],
                strategy_type=data["strategy_type"],
                pairs=["BTC/USDT", "ETH/USDT", "BNB/USDT", "SOL/USDT", "XRP/USDT"],
                config_params={},
                is_active=True,
            )
            session.add(strategy)
            inserted += 1

    if inserted > 0:
        session.commit()

    return inserted


if __name__ == "__main__":
    from src.core.app_settings import get_settings

    settings = get_settings()
    engine = sa.create_engine(settings.database_sync_url)
    with Session(engine) as session:
        count = seed_strategies(session)
        print(f"插入 {count} 条策略种子数据")
