"""交易信号数据模型。

TradingSignal：信号实体，归属于 Strategy，含时间戳和方向枚举。
信号数据由 Celery Worker 通过 freqtrade 定期生成，
写入 Redis 热缓存和 PostgreSQL 历史表。
"""

import datetime

from sqlalchemy import (
    JSON,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from src.core.enums import SignalDirection
from src.models.base import Base


class TradingSignal(Base):
    """交易信号模型。

    优先从 Redis 缓存读取（key: signal:{strategy_id}），缓存未命中时回退至本表。
    confidence_score 字段仅对 VIP 用户可见（通过 SignalRead Schema 控制）。
    """

    __tablename__ = "trading_signals"

    __table_args__ = (
        Index("idx_signal_strategy_at", "strategy_id", "signal_at"),
        Index("idx_signal_strategy_source", "strategy_id", "signal_source"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    strategy_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("strategies.id", ondelete="CASCADE"),
        nullable=False,
    )
    pair: Mapped[str] = mapped_column(String(32), nullable=False)
    direction: Mapped[SignalDirection] = mapped_column(
        Enum(SignalDirection, name="signaldirection", values_callable=lambda x: [e.value for e in x]),
        nullable=False,
    )
    confidence_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    signal_source: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="realtime"
    )
    entry_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    stop_loss: Mapped[float | None] = mapped_column(Float, nullable=True)
    take_profit: Mapped[float | None] = mapped_column(Float, nullable=True)
    indicator_values: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    timeframe: Mapped[str | None] = mapped_column(String(16), nullable=True)
    signal_strength: Mapped[float | None] = mapped_column(Float, nullable=True)
    volume: Mapped[float | None] = mapped_column(Float, nullable=True)
    volatility: Mapped[float | None] = mapped_column(Float, nullable=True)
    signal_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
