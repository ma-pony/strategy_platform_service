"""用户数据模型。

User 模型：平台用户聚合根，拥有会员等级，通过 JWT 携带至 API 层。
"""

from sqlalchemy import Boolean, Enum, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from src.core.enums import MembershipTier
from src.models.base import Base, TimestampMixin


class User(Base, TimestampMixin):
    """平台用户模型。

    membership 默认为 FREE，由运营后台手动升级。
    is_active=False 时，所有 API 请求均被拦截（code=1001）。
    """

    __tablename__ = "users"

    __table_args__ = (Index("idx_users_email", "email"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(254), unique=True, nullable=False, index=True)
    hashed_password: Mapped[str] = mapped_column(String(256), nullable=False)
    membership: Mapped[MembershipTier] = mapped_column(
        Enum(MembershipTier, name="membershiptier", values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=MembershipTier.FREE,
        server_default=MembershipTier.FREE.value,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    is_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
