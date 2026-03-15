"""数据模型层：SQLAlchemy 声明式模型。

导入所有模型以确保它们注册到 Base.metadata，
供 Alembic 迁移和 sqladmin 使用。
"""

from src.models.backtest import BacktestResult, BacktestTask
from src.models.base import Base, TimestampMixin
from src.models.report import ReportCoin, ResearchReport
from src.models.signal import TradingSignal
from src.models.strategy import Strategy
from src.models.strategy_pair_metrics import StrategyPairMetrics
from src.models.user import User

__all__ = [
    "BacktestResult",
    "BacktestTask",
    "Base",
    "ReportCoin",
    "ResearchReport",
    "Strategy",
    "StrategyPairMetrics",
    "TimestampMixin",
    "TradingSignal",
    "User",
]
