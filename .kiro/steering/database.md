# Database Standards

平台使用 SQLAlchemy 2.x 声明式 ORM，Alembic 管理迁移，sqladmin 通过 SQLAlchemy 模型提供管理界面。

## Model Declaration Pattern

所有模型继承同一 `DeclarativeBase`，公共字段通过 Mixin 复用：

```python
# src/models/base.py
from datetime import datetime
from sqlalchemy import DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

class Base(DeclarativeBase):
    pass

class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
```

业务模型示例：

```python
# src/models/user.py
from sqlalchemy import String, Boolean
from sqlalchemy.orm import Mapped, mapped_column
from src.models.base import Base, TimestampMixin
from src.core.enums import MembershipTier

class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(128), nullable=False)
    membership: Mapped[MembershipTier] = mapped_column(default=MembershipTier.FREE)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
```

## Naming Conventions

- 表名：`snake_case`，复数（`users`, `strategies`, `backtest_results`）
- 列名：`snake_case`（`created_at`, `user_id`）
- 外键：`{table_singular}_id`（`user_id` → `users.id`）
- 时间列：始终使用 `timezone=True`（UTC 存储）

## Session Management

使用 FastAPI `Depends` 管理 DB Session，每次请求一个 session，结束后自动关闭：

```python
# src/core/deps.py
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

engine = create_async_engine(settings.database_url, echo=settings.debug)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session
```

- 异步引擎（`asyncpg` 驱动）用于 Web 请求路径
- 同步引擎（`psycopg2`）仅用于 Alembic 迁移脚本和 sqladmin（sqladmin 不支持异步 session）

## sqladmin Integration

每个 SQLAlchemy 模型对应一个 `ModelView`，集中注册到 sqladmin `Admin` 实例：

```python
# src/admin/__init__.py
from sqladmin import Admin, ModelView
from src.models.user import User

class UserAdmin(ModelView, model=User):
    column_list = [User.id, User.username, User.membership, User.is_active, User.created_at]
    column_searchable_list = [User.username]
    column_sortable_list = [User.created_at]
    can_delete = False  # 根据业务决定是否允许后台删除

def setup_admin(app, engine) -> None:
    admin = Admin(app, engine, authentication_backend=AdminAuth())
    admin.add_view(UserAdmin)
    # 注册其他 ModelView...
```

**注意**：sqladmin 使用同步 SQLAlchemy engine，与 Web 层的异步 engine 实例分开创建。

## Migrations

- 所有 Schema 变更通过 Alembic 迁移，禁止直接修改生产数据库
- 迁移文件命名：`{seq}_{action}_{object}.py`（如 `002_add_membership_to_users.py`）
- 每次迁移必须实现 `upgrade()` 和 `downgrade()`
- `env.py` 中 `target_metadata = Base.metadata`，自动检测模型变更

## Query Patterns

- 简单 CRUD 使用 SQLAlchemy ORM（`session.get()`, `select()`, `session.add()`）
- 复杂统计查询可使用 `text()` 原生 SQL，但通过 `bindparams` 防止注入
- 避免 N+1：关联数据使用 `selectinload()` 或 `joinedload()` 预加载
- 列表接口必须分页（`limit` + `offset`），禁止无限制全表查询

---
_Focus on patterns. No connection strings or credentials._
