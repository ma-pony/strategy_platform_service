"""SQLAlchemy 基础模型与公共 Mixin。

所有业务模型继承 Base（DeclarativeBase 子类），
公共时间戳字段通过 TimestampMixin 复用。
"""

from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """所有 SQLAlchemy 模型的基类。"""


class TimestampMixin:
    """自动维护 created_at 和 updated_at 字段的 Mixin。

    所有时间列使用 DateTime(timezone=True)（UTC 存储）。
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
