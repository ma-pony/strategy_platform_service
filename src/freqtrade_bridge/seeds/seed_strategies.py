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
        "name": "TurtleTrading",
        "description": "海龟交易策略 — 基于 Donchian 通道突破的趋势跟随系统",
        "strategy_type": "trend_following",
    },
    {
        "name": "BollingerMeanReversion",
        "description": "布林带均值回归策略 — 基于布林带上下轨的超买超卖反转",
        "strategy_type": "mean_reversion",
    },
    {
        "name": "RsiMeanReversion",
        "description": "RSI 均值回归策略 — 基于 RSI 超卖区域的反弹交易",
        "strategy_type": "mean_reversion",
    },
    {
        "name": "MacdTrend",
        "description": "MACD 趋势策略 — 基于 MACD 金叉死叉的趋势跟随系统",
        "strategy_type": "trend_following",
    },
    {
        "name": "IchimokuTrend",
        "description": "一目均衡表趋势策略 — 基于云层和转换/基准线交叉的趋势跟随",
        "strategy_type": "trend_following",
    },
    {
        "name": "ParabolicSarTrend",
        "description": "抛物线 SAR 趋势策略 — 基于 SAR 翻转的趋势跟随系统",
        "strategy_type": "trend_following",
    },
    {
        "name": "KeltnerBreakout",
        "description": "凯尔特纳通道突破策略 — 基于通道突破的动量交易系统",
        "strategy_type": "breakout",
    },
    {
        "name": "AroonTrend",
        "description": "Aroon 趋势识别策略 — 基于 Aroon 指标的趋势方向判断",
        "strategy_type": "trend_following",
    },
    {
        "name": "Nr7Breakout",
        "description": "NR7 窄幅突破策略 — 基于 7 日最窄振幅 K 线的突破交易",
        "strategy_type": "breakout",
    },
    {
        "name": "StochasticReversal",
        "description": "随机指标反转策略 — 基于 Stochastic 超买超卖的反转交易",
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
    existing = {
        row[0]
        for row in session.execute(sa.select(Strategy.name)).fetchall()
    }

    inserted = 0
    for data in SEED_STRATEGIES:
        if data["name"] not in existing:
            strategy = Strategy(
                name=data["name"],
                description=data["description"],
                strategy_type=data["strategy_type"],
                pairs=["BTC/USDT", "ETH/USDT", "BNB/USDT", "SOL/USDT"],
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
