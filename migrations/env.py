"""Alembic 迁移环境配置。

使用同步 SQLAlchemy engine（psycopg2 驱动）执行迁移，
target_metadata 指向 Base.metadata，支持 autogenerate。
"""

from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context

# 导入所有模型以注册到 Base.metadata
import src.models  # noqa: F401 - 触发所有模型注册

from src.models.base import Base

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# target_metadata 指向 Base.metadata，供 autogenerate 使用
target_metadata = Base.metadata

# 从 pydantic-settings 配置中读取同步数据库 URL（仅在未通过代码设置时）
if not config.get_main_option("sqlalchemy.url"):
    from src.core.app_settings import get_settings

    _settings = get_settings()
    config.set_main_option("sqlalchemy.url", _settings.database_sync_url)


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.
    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
