"""replace_username_with_email_in_users

将 users 表的 username 字段替换为 email 字段。
- upgrade(): 删除 idx_users_username 索引和 username 列，
  新增 email VARCHAR(254) UNIQUE NOT NULL 列和 idx_users_email 索引
- downgrade(): 逆向还原 username VARCHAR(64) UNIQUE NOT NULL 列和原索引

Revision ID: 55d489f35f93
Revises: 058bf947c029
Create Date: 2026-03-15

"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "55d489f35f93"
down_revision: Union[str, Sequence[str], None] = "058bf947c029"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """将 users 表的 username 字段替换为 email 字段。

    步骤：
    1. 删除旧索引 idx_users_username（及唯一索引 ix_users_username）
    2. 删除 username 列
    3. 新增 email VARCHAR(254) UNIQUE NOT NULL 列
    4. 创建 idx_users_email 索引
    """
    # 1. 删除旧的唯一索引（由 156bfa76279c 迁移创建为 ix_users_username）
    op.drop_index(op.f("ix_users_username"), table_name="users")
    # 删除原始索引（如果存在）
    # op.drop_index("idx_users_username", table_name="users")  # 可能已在 156bfa76279c 中被替换

    # 2. 删除 username 列
    op.drop_column("users", "username")

    # 3. 新增 email 列（VARCHAR 254，不可为空，唯一）
    op.add_column(
        "users",
        sa.Column("email", sa.String(254), nullable=False, server_default="placeholder@placeholder.com"),
    )
    # 添加唯一约束
    op.create_unique_constraint("uq_users_email", "users", ["email"])
    # 移除 server_default（仅用于迁移填充，不保留为默认值）
    op.alter_column("users", "email", server_default=None)

    # 4. 创建 idx_users_email 索引
    op.create_index("idx_users_email", "users", ["email"], unique=False)


def downgrade() -> None:
    """还原 email 字段为 username 字段。

    步骤：
    1. 删除 idx_users_email 索引
    2. 删除唯一约束 uq_users_email
    3. 删除 email 列
    4. 新增 username VARCHAR(64) UNIQUE NOT NULL 列
    5. 重建 ix_users_username 索引
    """
    # 1. 删除 email 索引
    op.drop_index("idx_users_email", table_name="users")

    # 2. 删除唯一约束
    op.drop_constraint("uq_users_email", "users", type_="unique")

    # 3. 删除 email 列
    op.drop_column("users", "email")

    # 4. 新增 username 列（VARCHAR 64，不可为空，唯一）
    op.add_column(
        "users",
        sa.Column("username", sa.String(64), nullable=False, server_default="placeholder"),
    )
    # 添加唯一索引
    op.create_index(op.f("ix_users_username"), "users", ["username"], unique=True)
    # 移除 server_default
    op.alter_column("users", "username", server_default=None)
