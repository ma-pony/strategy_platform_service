"""策略对绩效指标模型单元测试（Task 1：数据模型与数据库迁移）。

测试覆盖范围：
- Task 1.1: DataSource 枚举
- Task 1.2: StrategyPairMetrics ORM 模型（字段、约束、索引）
- Task 1.3: Alembic 迁移文件结构验证

需求可追溯：1.1, 1.2, 1.3, 1.4, 1.5
"""

import importlib
from pathlib import Path
from typing import Optional

import pytest
from sqlalchemy import (
    DateTime,
    Float,
    Integer,
    String,
    UniqueConstraint,
    create_engine,
    inspect,
)
from sqlalchemy.orm import Session

MIGRATIONS_DIR = (
    Path(__file__).parent.parent.parent / "migrations" / "versions"
)

PAIR_METRICS_MIGRATION_SLUG = "add_strategy_pair_metrics"


# ============================================================
# Task 1.1 - DataSource 枚举测试
# ============================================================


class TestDataSourceEnum:
    """测试 DataSource 枚举（需求 1.3）。"""

    def test_datasource_enum_exists(self) -> None:
        """DataSource 枚举应存在于 src.core.enums 中。"""
        from src.core.enums import DataSource

        assert DataSource is not None

    def test_datasource_is_str_enum(self) -> None:
        """DataSource 应为 str 枚举（便于 Pydantic 和 SQLAlchemy 使用）。"""
        from enum import Enum

        from src.core.enums import DataSource

        assert issubclass(DataSource, str)
        assert issubclass(DataSource, Enum)

    def test_datasource_has_backtest_value(self) -> None:
        """DataSource 应有 BACKTEST 值，字符串为 'backtest'。"""
        from src.core.enums import DataSource

        assert DataSource.BACKTEST == "backtest"

    def test_datasource_has_live_value(self) -> None:
        """DataSource 应有 LIVE 值，字符串为 'live'。"""
        from src.core.enums import DataSource

        assert DataSource.LIVE == "live"

    def test_datasource_only_two_values(self) -> None:
        """DataSource 应只包含两个枚举值：backtest 和 live。"""
        from src.core.enums import DataSource

        values = {e.value for e in DataSource}
        assert values == {"backtest", "live"}

    def test_datasource_naming_consistent_with_existing_enums(self) -> None:
        """DataSource 命名风格应与现有枚举（MembershipTier、TaskStatus）一致。"""
        from src.core.enums import DataSource, MembershipTier, TaskStatus

        # 所有枚举都在同一模块中
        import src.core.enums as enums_module

        assert hasattr(enums_module, "DataSource")
        assert hasattr(enums_module, "MembershipTier")
        assert hasattr(enums_module, "TaskStatus")


# ============================================================
# Task 1.2 - StrategyPairMetrics ORM 模型测试
# ============================================================


class TestStrategyPairMetricsModel:
    """测试 StrategyPairMetrics 数据模型（需求 1.1, 1.2, 1.3, 1.4）。"""

    def test_model_exists(self) -> None:
        """StrategyPairMetrics 模型应存在于 src.models.strategy_pair_metrics 中。"""
        from src.models.strategy_pair_metrics import StrategyPairMetrics

        assert StrategyPairMetrics is not None

    def test_tablename_is_strategy_pair_metrics(self) -> None:
        """表名应为 strategy_pair_metrics（需求 1.1）。"""
        from src.models.strategy_pair_metrics import StrategyPairMetrics

        assert StrategyPairMetrics.__tablename__ == "strategy_pair_metrics"

    def test_model_inherits_base(self) -> None:
        """StrategyPairMetrics 应继承 Base。"""
        from src.models.base import Base
        from src.models.strategy_pair_metrics import StrategyPairMetrics

        assert issubclass(StrategyPairMetrics, Base)

    def test_has_primary_key_id(self) -> None:
        """id 字段应为主键（autoincrement INTEGER）。"""
        from sqlalchemy.orm import class_mapper

        from src.models.strategy_pair_metrics import StrategyPairMetrics

        mapper = class_mapper(StrategyPairMetrics)
        col = mapper.columns["id"]
        assert col.primary_key is True

    def test_has_strategy_id_field(self) -> None:
        """strategy_id 应存在且为 INTEGER NOT NULL。"""
        from sqlalchemy.orm import class_mapper

        from src.models.strategy_pair_metrics import StrategyPairMetrics

        mapper = class_mapper(StrategyPairMetrics)
        col = mapper.columns["strategy_id"]
        assert col.nullable is False
        assert isinstance(col.type, Integer)

    def test_strategy_id_is_foreign_key(self) -> None:
        """strategy_id 应为外键，指向 strategies.id（需求 1.2）。"""
        from sqlalchemy.orm import class_mapper

        from src.models.strategy_pair_metrics import StrategyPairMetrics

        mapper = class_mapper(StrategyPairMetrics)
        col = mapper.columns["strategy_id"]
        fks = list(col.foreign_keys)
        assert len(fks) > 0
        fk_target = list(fks)[0].target_fullname
        assert "strategies.id" in fk_target

    def test_has_pair_field_varchar32(self) -> None:
        """pair 字段应为 VARCHAR(32) NOT NULL。"""
        from sqlalchemy.orm import class_mapper

        from src.models.strategy_pair_metrics import StrategyPairMetrics

        mapper = class_mapper(StrategyPairMetrics)
        col = mapper.columns["pair"]
        assert col.nullable is False
        assert isinstance(col.type, String)
        assert col.type.length == 32

    def test_has_timeframe_field_varchar16(self) -> None:
        """timeframe 字段应为 VARCHAR(16) NOT NULL。"""
        from sqlalchemy.orm import class_mapper

        from src.models.strategy_pair_metrics import StrategyPairMetrics

        mapper = class_mapper(StrategyPairMetrics)
        col = mapper.columns["timeframe"]
        assert col.nullable is False
        assert isinstance(col.type, String)
        assert col.type.length == 16

    def test_has_total_return_nullable_float(self) -> None:
        """total_return 应为 FLOAT NULLABLE（需求 1.1）。"""
        from sqlalchemy.orm import class_mapper

        from src.models.strategy_pair_metrics import StrategyPairMetrics

        mapper = class_mapper(StrategyPairMetrics)
        col = mapper.columns["total_return"]
        assert col.nullable is True
        assert isinstance(col.type, Float)

    def test_has_profit_factor_nullable_float(self) -> None:
        """profit_factor 应为 FLOAT NULLABLE（需求 1.1）。"""
        from sqlalchemy.orm import class_mapper

        from src.models.strategy_pair_metrics import StrategyPairMetrics

        mapper = class_mapper(StrategyPairMetrics)
        col = mapper.columns["profit_factor"]
        assert col.nullable is True
        assert isinstance(col.type, Float)

    def test_has_max_drawdown_nullable_float(self) -> None:
        """max_drawdown 应为 FLOAT NULLABLE（需求 1.1）。"""
        from sqlalchemy.orm import class_mapper

        from src.models.strategy_pair_metrics import StrategyPairMetrics

        mapper = class_mapper(StrategyPairMetrics)
        col = mapper.columns["max_drawdown"]
        assert col.nullable is True
        assert isinstance(col.type, Float)

    def test_has_sharpe_ratio_nullable_float(self) -> None:
        """sharpe_ratio 应为 FLOAT NULLABLE（需求 1.1）。"""
        from sqlalchemy.orm import class_mapper

        from src.models.strategy_pair_metrics import StrategyPairMetrics

        mapper = class_mapper(StrategyPairMetrics)
        col = mapper.columns["sharpe_ratio"]
        assert col.nullable is True
        assert isinstance(col.type, Float)

    def test_has_trade_count_nullable_integer(self) -> None:
        """trade_count 应为 INTEGER NULLABLE（需求 1.1）。"""
        from sqlalchemy.orm import class_mapper

        from src.models.strategy_pair_metrics import StrategyPairMetrics

        mapper = class_mapper(StrategyPairMetrics)
        col = mapper.columns["trade_count"]
        assert col.nullable is True
        assert isinstance(col.type, Integer)

    def test_has_data_source_not_null(self) -> None:
        """data_source 字段应为非空枚举列（需求 1.3）。"""
        from sqlalchemy.orm import class_mapper

        from src.models.strategy_pair_metrics import StrategyPairMetrics

        mapper = class_mapper(StrategyPairMetrics)
        col = mapper.columns["data_source"]
        assert col.nullable is False

    def test_has_last_updated_at_not_null_with_timezone(self) -> None:
        """last_updated_at 应为 TIMESTAMPTZ NOT NULL，不使用 server_default（需求 1.4）。"""
        from sqlalchemy.orm import class_mapper

        from src.models.strategy_pair_metrics import StrategyPairMetrics

        mapper = class_mapper(StrategyPairMetrics)
        col = mapper.columns["last_updated_at"]
        assert col.nullable is False
        assert isinstance(col.type, DateTime)
        assert col.type.timezone is True
        # 不应有 onupdate（由调用方显式控制）
        assert col.onupdate is None

    def test_has_created_at_with_server_default(self) -> None:
        """created_at 应为 TIMESTAMPTZ NOT NULL 且有 server_default。"""
        from sqlalchemy.orm import class_mapper

        from src.models.strategy_pair_metrics import StrategyPairMetrics

        mapper = class_mapper(StrategyPairMetrics)
        col = mapper.columns["created_at"]
        assert col.nullable is False
        assert isinstance(col.type, DateTime)
        assert col.type.timezone is True
        assert col.server_default is not None

    def test_unique_constraint_strategy_pair_timeframe(self) -> None:
        """应有 (strategy_id, pair, timeframe) 唯一约束（需求 1.2）。"""
        from src.models.strategy_pair_metrics import StrategyPairMetrics

        table = StrategyPairMetrics.__table__
        unique_constraints = [
            c for c in table.constraints if isinstance(c, UniqueConstraint)
        ]
        col_sets = [
            frozenset(col.name for col in uc.columns)
            for uc in unique_constraints
        ]
        assert frozenset({"strategy_id", "pair", "timeframe"}) in col_sets

    def test_unique_constraint_named_correctly(self) -> None:
        """唯一约束应命名为 uq_spm_strategy_pair_tf（需求 1.2）。"""
        from src.models.strategy_pair_metrics import StrategyPairMetrics

        table = StrategyPairMetrics.__table__
        unique_constraint_names = {
            c.name
            for c in table.constraints
            if isinstance(c, UniqueConstraint)
        }
        assert "uq_spm_strategy_pair_tf" in unique_constraint_names

    def test_has_idx_spm_strategy_id_index(self) -> None:
        """应有 idx_spm_strategy_id 索引。"""
        from src.models.strategy_pair_metrics import StrategyPairMetrics

        table = StrategyPairMetrics.__table__
        index_names = {idx.name for idx in table.indexes}
        assert "idx_spm_strategy_id" in index_names

    def test_has_idx_spm_strategy_pair_tf_index(self) -> None:
        """应有 idx_spm_strategy_pair_tf 索引（覆盖唯一约束的查询）。"""
        from src.models.strategy_pair_metrics import StrategyPairMetrics

        table = StrategyPairMetrics.__table__
        index_names = {idx.name for idx in table.indexes}
        assert "idx_spm_strategy_pair_tf" in index_names

    def test_has_idx_spm_last_updated_at_index(self) -> None:
        """应有 idx_spm_last_updated_at 索引。"""
        from src.models.strategy_pair_metrics import StrategyPairMetrics

        table = StrategyPairMetrics.__table__
        index_names = {idx.name for idx in table.indexes}
        assert "idx_spm_last_updated_at" in index_names

    def test_data_source_uses_datasource_enum_type(self) -> None:
        """data_source 字段应使用 DataSource 枚举类型。"""
        from sqlalchemy import Enum as SAEnum
        from sqlalchemy.orm import class_mapper

        from src.core.enums import DataSource
        from src.models.strategy_pair_metrics import StrategyPairMetrics

        mapper = class_mapper(StrategyPairMetrics)
        col = mapper.columns["data_source"]
        assert isinstance(col.type, SAEnum)

    def test_model_can_be_instantiated_with_required_fields(self) -> None:
        """StrategyPairMetrics 应可通过必需字段实例化。"""
        from datetime import datetime, timezone

        from src.core.enums import DataSource
        from src.models.strategy_pair_metrics import StrategyPairMetrics

        metrics = StrategyPairMetrics(
            strategy_id=1,
            pair="BTC/USDT",
            timeframe="1h",
            data_source=DataSource.BACKTEST,
            last_updated_at=datetime.now(timezone.utc),
        )
        assert metrics.strategy_id == 1
        assert metrics.pair == "BTC/USDT"
        assert metrics.timeframe == "1h"
        assert metrics.data_source == DataSource.BACKTEST

    def test_metric_fields_default_to_none(self) -> None:
        """所有指标字段（total_return 等）应默认为 None（支持 upsert 缺失字段语义）。"""
        from datetime import datetime, timezone

        from src.core.enums import DataSource
        from src.models.strategy_pair_metrics import StrategyPairMetrics

        metrics = StrategyPairMetrics(
            strategy_id=1,
            pair="ETH/USDT",
            timeframe="4h",
            data_source=DataSource.LIVE,
            last_updated_at=datetime.now(timezone.utc),
        )
        assert metrics.total_return is None
        assert metrics.profit_factor is None
        assert metrics.max_drawdown is None
        assert metrics.sharpe_ratio is None
        assert metrics.trade_count is None

    def test_model_registered_in_base_metadata(self) -> None:
        """strategy_pair_metrics 表应注册到 Base.metadata（供 Alembic 检测）。"""
        import src.models.strategy_pair_metrics  # noqa: F401

        from src.models.base import Base

        assert "strategy_pair_metrics" in Base.metadata.tables


class TestStrategyPairMetricsInMemoryDB:
    """使用 SQLite 内存数据库验证 StrategyPairMetrics 建表和基本操作（需求 1.5）。"""

    def test_table_can_be_created_in_sqlite(self) -> None:
        """SQLite 内存数据库中应能成功创建 strategy_pair_metrics 表。"""
        import src.models.backtest  # noqa: F401
        import src.models.report  # noqa: F401
        import src.models.signal  # noqa: F401
        import src.models.strategy  # noqa: F401
        import src.models.strategy_pair_metrics  # noqa: F401
        import src.models.user  # noqa: F401

        from src.models.base import Base

        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        insp = inspect(engine)
        assert "strategy_pair_metrics" in insp.get_table_names()
        Base.metadata.drop_all(engine)

    def test_record_can_be_inserted_and_retrieved(self) -> None:
        """策略对绩效指标记录应可写入并读回（需求 1.5：首次写入自动创建）。"""
        from datetime import datetime, timezone

        import src.models.backtest  # noqa: F401
        import src.models.report  # noqa: F401
        import src.models.signal  # noqa: F401
        import src.models.strategy_pair_metrics  # noqa: F401
        import src.models.user  # noqa: F401

        from src.core.enums import DataSource
        from src.models.base import Base
        from src.models.strategy import Strategy
        from src.models.strategy_pair_metrics import StrategyPairMetrics

        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)

        with Session(engine) as session:
            strategy = Strategy(
                name="test_strat",
                description="desc",
                strategy_type="trend",
                pairs=["BTC/USDT"],
                config_params={},
            )
            session.add(strategy)
            session.flush()

            now = datetime.now(timezone.utc)
            metrics = StrategyPairMetrics(
                strategy_id=strategy.id,
                pair="BTC/USDT",
                timeframe="1h",
                total_return=0.15,
                profit_factor=1.5,
                max_drawdown=0.08,
                sharpe_ratio=1.2,
                trade_count=42,
                data_source=DataSource.BACKTEST,
                last_updated_at=now,
            )
            session.add(metrics)
            session.commit()
            session.refresh(metrics)

            assert metrics.id is not None
            assert metrics.total_return == pytest.approx(0.15)
            assert metrics.profit_factor == pytest.approx(1.5)
            assert metrics.trade_count == 42
            assert metrics.data_source == DataSource.BACKTEST

        Base.metadata.drop_all(engine)

    def test_unique_constraint_prevents_duplicate_records(self) -> None:
        """(strategy_id, pair, timeframe) 唯一约束应阻止重复记录（需求 1.2）。"""
        from datetime import datetime, timezone

        import src.models.backtest  # noqa: F401
        import src.models.report  # noqa: F401
        import src.models.signal  # noqa: F401
        import src.models.strategy_pair_metrics  # noqa: F401
        import src.models.user  # noqa: F401
        from sqlalchemy.exc import IntegrityError

        from src.core.enums import DataSource
        from src.models.base import Base
        from src.models.strategy import Strategy
        from src.models.strategy_pair_metrics import StrategyPairMetrics

        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)

        with Session(engine) as session:
            strategy = Strategy(
                name="strat_dup_test",
                description="d",
                strategy_type="t",
                pairs=["BTC/USDT"],
                config_params={},
            )
            session.add(strategy)
            session.flush()

            now = datetime.now(timezone.utc)
            m1 = StrategyPairMetrics(
                strategy_id=strategy.id,
                pair="BTC/USDT",
                timeframe="1h",
                data_source=DataSource.BACKTEST,
                last_updated_at=now,
            )
            m2 = StrategyPairMetrics(
                strategy_id=strategy.id,
                pair="BTC/USDT",
                timeframe="1h",
                data_source=DataSource.LIVE,
                last_updated_at=now,
            )
            session.add(m1)
            session.add(m2)
            with pytest.raises(IntegrityError):
                session.commit()

        Base.metadata.drop_all(engine)


# ============================================================
# Task 1.3 - Alembic 迁移文件结构测试
# ============================================================


def _load_pair_metrics_migration():
    """加载 add_strategy_pair_metrics 迁移模块。"""
    files = list(MIGRATIONS_DIR.glob(f"*{PAIR_METRICS_MIGRATION_SLUG}.py"))
    assert len(files) == 1, (
        f"找不到包含 '{PAIR_METRICS_MIGRATION_SLUG}' 的迁移文件"
    )
    module_name = f"migrations.versions.{files[0].stem}"
    return importlib.import_module(module_name)


class TestStrategyPairMetricsMigration:
    """验证 add_strategy_pair_metrics 迁移文件（需求 1.1–1.5）。"""

    def test_migration_file_exists(self) -> None:
        """add_strategy_pair_metrics 迁移文件应存在。"""
        files = list(MIGRATIONS_DIR.glob(f"*{PAIR_METRICS_MIGRATION_SLUG}.py"))
        assert len(files) == 1, (
            f"缺少包含 '{PAIR_METRICS_MIGRATION_SLUG}' 的迁移文件"
        )

    def test_migration_has_upgrade_function(self) -> None:
        """迁移文件应有 upgrade() 函数。"""
        module = _load_pair_metrics_migration()
        assert hasattr(module, "upgrade")
        assert callable(module.upgrade)

    def test_migration_has_downgrade_function(self) -> None:
        """迁移文件应有 downgrade() 函数。"""
        module = _load_pair_metrics_migration()
        assert hasattr(module, "downgrade")
        assert callable(module.downgrade)

    def test_migration_has_revision_id(self) -> None:
        """迁移文件应声明 revision 字符串。"""
        module = _load_pair_metrics_migration()
        assert hasattr(module, "revision")
        assert isinstance(module.revision, str)
        assert len(module.revision) > 0

    def test_migration_depends_on_latest_migration(self) -> None:
        """迁移文件的 down_revision 应指向 55d489f35f93（当前最新迁移）。"""
        module = _load_pair_metrics_migration()
        assert module.down_revision == "55d489f35f93"

    def test_migration_upgrade_creates_strategy_pair_metrics_table(self) -> None:
        """upgrade() 应创建 strategy_pair_metrics 表（通过源码检查）。"""
        files = list(MIGRATIONS_DIR.glob(f"*{PAIR_METRICS_MIGRATION_SLUG}.py"))
        assert len(files) == 1
        source = files[0].read_text()
        assert "strategy_pair_metrics" in source
        assert "create_table" in source

    def test_migration_upgrade_creates_datasource_enum(self) -> None:
        """upgrade() 应创建 datasource ENUM 类型（需求 1.3）。"""
        files = list(MIGRATIONS_DIR.glob(f"*{PAIR_METRICS_MIGRATION_SLUG}.py"))
        assert len(files) == 1
        source = files[0].read_text()
        assert "datasource" in source

    def test_migration_upgrade_includes_unique_constraint(self) -> None:
        """upgrade() 应包含 (strategy_id, pair, timeframe) 唯一约束（需求 1.2）。"""
        files = list(MIGRATIONS_DIR.glob(f"*{PAIR_METRICS_MIGRATION_SLUG}.py"))
        assert len(files) == 1
        source = files[0].read_text()
        assert "uq_spm_strategy_pair_tf" in source

    def test_migration_upgrade_includes_all_metric_columns(self) -> None:
        """upgrade() 应包含所有绩效指标字段（需求 1.1）。"""
        files = list(MIGRATIONS_DIR.glob(f"*{PAIR_METRICS_MIGRATION_SLUG}.py"))
        assert len(files) == 1
        source = files[0].read_text()
        for col in ["total_return", "profit_factor", "max_drawdown", "sharpe_ratio", "trade_count"]:
            assert col in source, f"迁移文件中缺少字段 {col}"

    def test_migration_upgrade_includes_last_updated_at(self) -> None:
        """upgrade() 应包含 last_updated_at 列（需求 1.4）。"""
        files = list(MIGRATIONS_DIR.glob(f"*{PAIR_METRICS_MIGRATION_SLUG}.py"))
        assert len(files) == 1
        source = files[0].read_text()
        assert "last_updated_at" in source

    def test_migration_upgrade_includes_indexes(self) -> None:
        """upgrade() 应创建三个索引（需求 1.2）。"""
        files = list(MIGRATIONS_DIR.glob(f"*{PAIR_METRICS_MIGRATION_SLUG}.py"))
        assert len(files) == 1
        source = files[0].read_text()
        assert "idx_spm_strategy_id" in source
        assert "idx_spm_strategy_pair_tf" in source
        assert "idx_spm_last_updated_at" in source

    def test_migration_downgrade_drops_table(self) -> None:
        """downgrade() 应删除 strategy_pair_metrics 表。"""
        files = list(MIGRATIONS_DIR.glob(f"*{PAIR_METRICS_MIGRATION_SLUG}.py"))
        assert len(files) == 1
        source = files[0].read_text()
        assert "drop_table" in source

    def test_migration_downgrade_drops_datasource_enum(self) -> None:
        """downgrade() 应删除 datasource ENUM 类型。"""
        files = list(MIGRATIONS_DIR.glob(f"*{PAIR_METRICS_MIGRATION_SLUG}.py"))
        assert len(files) == 1
        source = files[0].read_text()
        assert "datasource" in source
        assert "drop" in source.lower()


# ============================================================
# models/__init__.py 集成：StrategyPairMetrics 应被导出
# ============================================================


class TestStrategyPairMetricsInModelsInit:
    """验证 StrategyPairMetrics 在 src.models 包中正确导出。"""

    def test_strategy_pair_metrics_in_models_package(self) -> None:
        """src.models 应导出 StrategyPairMetrics。"""
        from src.models import StrategyPairMetrics

        assert StrategyPairMetrics is not None

    def test_strategy_pair_metrics_table_in_metadata(self) -> None:
        """导入 src.models 后，strategy_pair_metrics 表应注册到 Base.metadata。"""
        import src.models  # noqa: F401

        from src.models.base import Base

        assert "strategy_pair_metrics" in Base.metadata.tables
