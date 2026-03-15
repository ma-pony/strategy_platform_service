"""回测任务与结果数据模型。

BacktestTask：回测任务实体，记录任务生命周期状态。
BacktestResult：回测结果值对象，归属于 Strategy 和 BacktestTask。
"""

import datetime

from sqlalchemy import (
    JSON,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from src.core.enums import TaskStatus
from src.models.base import Base


class BacktestTask(Base):
    """回测任务模型。

    联合唯一约束 (strategy_id, scheduled_date) 防止同日重复回测。
    任务状态只能单向流转：PENDING → RUNNING → DONE | FAILED。
    """

    __tablename__ = "backtest_tasks"

    __table_args__ = (
        UniqueConstraint(
            "strategy_id",
            "scheduled_date",
            name="uq_btask_strategy_date",
        ),
        Index("idx_btask_strategy_status", "strategy_id", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    strategy_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("strategies.id", ondelete="CASCADE"),
        nullable=False,
    )
    scheduled_date: Mapped[datetime.date] = mapped_column(Date, nullable=False)
    status: Mapped[TaskStatus] = mapped_column(
        Enum(TaskStatus, name="taskstatus", values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=TaskStatus.PENDING,
        server_default=TaskStatus.PENDING.value,
    )
    timerange: Mapped[str | None] = mapped_column(String(64), nullable=True)
    result_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class BacktestResult(Base):
    """回测结果模型。

    存储 freqtrade 回测完成后的核心指标数据。
    字段可见性通过 BacktestResultRead Schema 的 @model_serializer 控制。
    """

    __tablename__ = "backtest_results"

    __table_args__ = (
        Index("idx_bresult_strategy_id", "strategy_id"),
        Index("idx_bresult_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    strategy_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("strategies.id", ondelete="CASCADE"),
        nullable=False,
    )
    task_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("backtest_tasks.id", ondelete="CASCADE"),
        nullable=False,
    )
    total_return: Mapped[float] = mapped_column(Float, nullable=False)
    annual_return: Mapped[float] = mapped_column(Float, nullable=False)
    sharpe_ratio: Mapped[float] = mapped_column(Float, nullable=False)
    max_drawdown: Mapped[float] = mapped_column(Float, nullable=False)
    trade_count: Mapped[int] = mapped_column(Integer, nullable=False)
    win_rate: Mapped[float] = mapped_column(Float, nullable=False)
    period_start: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
