"""AI 市场研报数据模型。

ResearchReport：研报聚合根，存储 AI 生成的市场研报内容。
ReportCoin：研报关联币种表，支持研报与多个币种的多对多关联。
"""

from __future__ import annotations

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import Base, TimestampMixin


class ResearchReport(Base, TimestampMixin):
    """AI 市场研报模型。

    研报数据通过 sqladmin 后台维护，提供只读公开 API。
    允许匿名访问，无需 JWT 鉴权。
    """

    __tablename__ = "research_reports"

    __table_args__ = (Index("idx_report_generated_at", "generated_at"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    generated_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)

    # 关联币种列表（一对多）
    coins: Mapped[list[ReportCoin]] = relationship(
        "ReportCoin",
        back_populates="report",
        lazy="select",
        cascade="all, delete-orphan",
    )


class ReportCoin(Base):
    """研报关联币种表。

    实现研报与多个币种的关联关系（如 BTC、ETH 等）。
    """

    __tablename__ = "report_coins"

    __table_args__ = (Index("idx_reportcoin_report_id", "report_id"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    report_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("research_reports.id", ondelete="CASCADE"),
        nullable=False,
    )
    coin_symbol: Mapped[str] = mapped_column(String(32), nullable=False)

    # 反向关联
    report: Mapped[ResearchReport] = relationship(
        "ResearchReport",
        back_populates="coins",
    )
