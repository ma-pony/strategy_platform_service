"""策略数据模型。

Strategy 模型：量化策略聚合根，包含策略配置、交易对等信息。
策略由运营后台维护，不提供公开写入接口。
"""

from sqlalchemy import Boolean, Float, Index, Integer, String
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, TimestampMixin


class Strategy(Base, TimestampMixin):
    """量化策略模型。

    is_active=True 的策略才纳入定时回测调度。
    所有策略数据仅通过 sqladmin 后台维护。
    """

    __tablename__ = "strategies"

    __table_args__ = (Index("idx_strategies_is_active", "is_active"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    strategy_type: Mapped[str] = mapped_column(String(64), nullable=False)
    pairs: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    config_params: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")

    # 回测结果指标（由 backtest_tasks DONE 后自动填充 NULL 字段）
    trade_count: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    max_drawdown: Mapped[float | None] = mapped_column(Float, nullable=True, default=None)
    sharpe_ratio: Mapped[float | None] = mapped_column(Float, nullable=True, default=None)
    win_rate: Mapped[float | None] = mapped_column(Float, nullable=True, default=None)
