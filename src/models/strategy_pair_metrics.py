"""策略对绩效指标数据模型。

StrategyPairMetrics 模型：每个"策略 × 币种 × 周期"组合的绩效指标聚合根。
以 (strategy_id, pair, timeframe) 三元组作为业务唯一键，支持 upsert 语义。

指标字段均声明为 NULLABLE，以支持"缺失字段不覆盖"的 COALESCE upsert 语义。
last_updated_at 由写入方显式传入，不使用 onupdate，以支持幂等判断。
"""

from datetime import datetime

from sqlalchemy import (
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from src.core.enums import DataSource
from src.models.base import Base


class StrategyPairMetrics(Base):
    """策略对绩效指标模型。

    表 strategy_pair_metrics 以 (strategy_id, pair, timeframe) 三元组作为业务唯一键。
    指标字段均可为 NULL（初始或缺失状态），data_source 和 last_updated_at 为必填字段。
    外键 strategy_id 关联 strategies.id，ON DELETE CASCADE。

    Requirements: 1.1, 1.2, 1.3, 1.4, 1.5
    """

    __tablename__ = "strategy_pair_metrics"

    __table_args__ = (
        UniqueConstraint(
            "strategy_id",
            "pair",
            "timeframe",
            name="uq_spm_strategy_pair_tf",
        ),
        Index("idx_spm_strategy_id", "strategy_id"),
        Index("idx_spm_strategy_pair_tf", "strategy_id", "pair", "timeframe"),
        Index("idx_spm_last_updated_at", "last_updated_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # 业务唯一键三元组
    strategy_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("strategies.id", ondelete="CASCADE"),
        nullable=False,
    )
    pair: Mapped[str] = mapped_column(String(32), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(16), nullable=False)

    # 绩效指标字段（均可空，支持 COALESCE upsert 语义）
    total_return: Mapped[float | None] = mapped_column(Float, nullable=True, default=None)
    profit_factor: Mapped[float | None] = mapped_column(Float, nullable=True, default=None)
    max_drawdown: Mapped[float | None] = mapped_column(Float, nullable=True, default=None)
    sharpe_ratio: Mapped[float | None] = mapped_column(Float, nullable=True, default=None)
    trade_count: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)

    # 元数据字段
    data_source: Mapped[DataSource] = mapped_column(
        Enum(DataSource, name="datasource", values_callable=lambda x: [e.value for e in x]),
        nullable=False,
    )
    last_updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        # 不使用 server_default 或 onupdate，由写入方显式传入（需求 3.5：幂等判断）
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
