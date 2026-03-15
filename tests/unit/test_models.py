"""数据模型层单元测试。

测试覆盖任务 2.1-2.4：
- Base 和 TimestampMixin
- User 和 Strategy 模型
- BacktestTask 和 BacktestResult 模型
- TradingSignal、ResearchReport、ReportCoin 模型
"""

from sqlalchemy import DateTime, UniqueConstraint, create_engine, inspect
from sqlalchemy.orm import Session

from src.core.enums import MembershipTier, SignalDirection, TaskStatus
from src.models.base import Base, TimestampMixin

# ============================================================
# 2.1 - Base 与 TimestampMixin 测试
# ============================================================


class TestBase:
    """测试 DeclarativeBase 子类 Base。"""

    def test_base_is_declarative_base(self) -> None:
        """Base 应是 DeclarativeBase 的子类。"""
        from sqlalchemy.orm import DeclarativeBase

        assert issubclass(Base, DeclarativeBase)

    def test_base_has_metadata(self) -> None:
        """Base 应有 metadata 属性，供 Alembic 迁移使用。"""
        from sqlalchemy import MetaData

        assert hasattr(Base, "metadata")
        assert isinstance(Base.metadata, MetaData)


class TestTimestampMixin:
    """测试 TimestampMixin。"""

    def test_mixin_declares_created_at(self) -> None:
        """TimestampMixin 应声明 created_at 字段。"""
        assert hasattr(TimestampMixin, "created_at")

    def test_mixin_declares_updated_at(self) -> None:
        """TimestampMixin 应声明 updated_at 字段。"""
        assert hasattr(TimestampMixin, "updated_at")

    def test_created_at_uses_timezone(self) -> None:
        """created_at 应使用 DateTime(timezone=True)。"""
        from sqlalchemy.orm import class_mapper

        from src.models.user import User

        mapper = class_mapper(User)
        col = mapper.columns["created_at"]
        assert isinstance(col.type, DateTime)
        assert col.type.timezone is True

    def test_updated_at_uses_timezone(self) -> None:
        """updated_at 应使用 DateTime(timezone=True)。"""
        from sqlalchemy.orm import class_mapper

        from src.models.user import User

        mapper = class_mapper(User)
        col = mapper.columns["updated_at"]
        assert isinstance(col.type, DateTime)
        assert col.type.timezone is True


# ============================================================
# 2.2 - User 与 Strategy 模型测试
# ============================================================


class TestUserModel:
    """测试 User 数据模型（任务 2.1：username → email）。"""

    def test_user_tablename(self) -> None:
        """User 模型表名应为 users。"""
        from src.models.user import User

        assert User.__tablename__ == "users"

    def test_user_has_required_columns(self) -> None:
        """User 模型应包含所有必需字段（email 替换 username）。"""
        from sqlalchemy.orm import class_mapper

        from src.models.user import User

        mapper = class_mapper(User)
        column_names = {c.key for c in mapper.columns}
        assert "id" in column_names
        assert "email" in column_names
        assert "username" not in column_names
        assert "hashed_password" in column_names
        assert "membership" in column_names
        assert "is_active" in column_names
        # TimestampMixin 字段
        assert "created_at" in column_names
        assert "updated_at" in column_names

    def test_user_email_unique(self) -> None:
        """email 字段应有唯一约束（需求 3.3）。"""
        from sqlalchemy.orm import class_mapper

        from src.models.user import User

        mapper = class_mapper(User)
        col = mapper.columns["email"]
        assert col.unique is True

    def test_user_email_max_length_254(self) -> None:
        """email 字段最大长度应为 254（遵循 RFC 5321）。"""
        from sqlalchemy import String
        from sqlalchemy.orm import class_mapper

        from src.models.user import User

        mapper = class_mapper(User)
        col = mapper.columns["email"]
        assert isinstance(col.type, String)
        assert col.type.length == 254

    def test_user_email_not_nullable(self) -> None:
        """email 字段不可为空（需求 3.1）。"""
        from sqlalchemy.orm import class_mapper

        from src.models.user import User

        mapper = class_mapper(User)
        col = mapper.columns["email"]
        assert col.nullable is False

    def test_user_has_idx_users_email_index(self) -> None:
        """User 模型应有 idx_users_email 索引，不应有 idx_users_username（需求 3.3）。"""
        from src.models.user import User

        index_names = {idx.name for idx in User.__table__.indexes}
        assert "idx_users_email" in index_names
        assert "idx_users_username" not in index_names

    def test_user_no_username_field(self) -> None:
        """User 模型不应有 username 字段（需求 3.1）。"""
        from sqlalchemy.orm import class_mapper

        from src.models.user import User

        mapper = class_mapper(User)
        column_names = {c.key for c in mapper.columns}
        assert "username" not in column_names

    def test_user_inherits_timestamp_mixin(self) -> None:
        """User 应继承 TimestampMixin。"""
        from src.models.user import User

        assert issubclass(User, TimestampMixin)

    def test_user_membership_default_free_via_db(self) -> None:
        """User 会员等级数据库默认值应为 FREE（通过 SQLite 验证 server_default）。"""
        import src.models.strategy  # noqa: F401 - 触发所有关联模型注册
        from src.models.user import User

        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        with Session(engine) as session:
            user = User(email="test@example.com", hashed_password="hashed")
            session.add(user)
            session.commit()
            session.refresh(user)
            assert user.membership == MembershipTier.FREE
        Base.metadata.drop_all(engine)

    def test_user_is_active_default_true_via_db(self) -> None:
        """User is_active 数据库默认值应为 True（通过 SQLite 验证 server_default）。"""
        import src.models.strategy  # noqa: F401
        from src.models.user import User

        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        with Session(engine) as session:
            user = User(email="test@example.com", hashed_password="hashed")
            session.add(user)
            session.commit()
            session.refresh(user)
            assert user.is_active is True
        Base.metadata.drop_all(engine)


class TestStrategyModel:
    """测试 Strategy 数据模型（任务 2.2）。"""

    def test_strategy_tablename(self) -> None:
        """Strategy 模型表名应为 strategies。"""
        from src.models.strategy import Strategy

        assert Strategy.__tablename__ == "strategies"

    def test_strategy_has_required_columns(self) -> None:
        """Strategy 模型应包含所有必需字段。"""
        from sqlalchemy.orm import class_mapper

        from src.models.strategy import Strategy

        mapper = class_mapper(Strategy)
        column_names = {c.key for c in mapper.columns}
        assert "id" in column_names
        assert "name" in column_names
        assert "description" in column_names
        assert "strategy_type" in column_names
        assert "pairs" in column_names
        assert "config_params" in column_names
        assert "is_active" in column_names
        assert "created_at" in column_names
        assert "updated_at" in column_names

    def test_strategy_name_unique(self) -> None:
        """strategy name 字段应有唯一约束。"""
        from sqlalchemy.orm import class_mapper

        from src.models.strategy import Strategy

        mapper = class_mapper(Strategy)
        col = mapper.columns["name"]
        assert col.unique is True

    def test_strategy_is_active_default_true_via_db(self) -> None:
        """Strategy is_active 数据库默认值应为 True（通过 SQLite 验证）。"""
        import src.models.backtest  # noqa: F401
        import src.models.report  # noqa: F401
        import src.models.signal  # noqa: F401
        import src.models.user  # noqa: F401
        from src.models.strategy import Strategy

        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        with Session(engine) as session:
            s = Strategy(
                name="test_strat",
                description="desc",
                strategy_type="trend",
                pairs=["BTC/USDT"],
                config_params={},
            )
            session.add(s)
            session.commit()
            session.refresh(s)
            assert s.is_active is True
        Base.metadata.drop_all(engine)

    def test_strategy_inherits_timestamp_mixin(self) -> None:
        """Strategy 应继承 TimestampMixin。"""
        from src.models.strategy import Strategy

        assert issubclass(Strategy, TimestampMixin)

    def test_strategy_pairs_is_json_column(self) -> None:
        """pairs 字段应使用 JSON 类型。"""
        from sqlalchemy import JSON
        from sqlalchemy.orm import class_mapper

        from src.models.strategy import Strategy

        mapper = class_mapper(Strategy)
        col = mapper.columns["pairs"]
        assert isinstance(col.type, JSON)

    def test_strategy_config_params_is_json_column(self) -> None:
        """config_params 字段应使用 JSON 类型。"""
        from sqlalchemy import JSON
        from sqlalchemy.orm import class_mapper

        from src.models.strategy import Strategy

        mapper = class_mapper(Strategy)
        col = mapper.columns["config_params"]
        assert isinstance(col.type, JSON)

    def test_strategy_has_is_active_index(self) -> None:
        """Strategy 应在 is_active 字段上建立索引。"""
        from src.models.strategy import Strategy

        table = Strategy.__table__
        # 检查是否有包含 is_active 的索引
        has_is_active_index = any(
            "is_active" in idx.name
            or any(col.name == "is_active" for col in idx.columns)
            for idx in table.indexes
        )
        assert has_is_active_index


# ============================================================
# 2.3 - BacktestTask 与 BacktestResult 模型测试
# ============================================================


class TestBacktestTaskModel:
    """测试 BacktestTask 数据模型（任务 2.3）。"""

    def test_backtest_task_tablename(self) -> None:
        """BacktestTask 表名应为 backtest_tasks。"""
        from src.models.backtest import BacktestTask

        assert BacktestTask.__tablename__ == "backtest_tasks"

    def test_backtest_task_has_required_columns(self) -> None:
        """BacktestTask 应包含所有必需字段。"""
        from sqlalchemy.orm import class_mapper

        from src.models.backtest import BacktestTask

        mapper = class_mapper(BacktestTask)
        column_names = {c.key for c in mapper.columns}
        assert "id" in column_names
        assert "strategy_id" in column_names
        assert "scheduled_date" in column_names
        assert "status" in column_names
        assert "error_message" in column_names

    def test_backtest_task_has_unique_constraint_on_strategy_date(self) -> None:
        """BacktestTask 应有 (strategy_id, scheduled_date) 的联合唯一约束。"""
        from src.models.backtest import BacktestTask

        table = BacktestTask.__table__
        # 查找唯一约束
        unique_constraints = [
            c for c in table.constraints
            if isinstance(c, UniqueConstraint)
        ]
        col_sets = [
            frozenset(col.name for col in uc.columns)
            for uc in unique_constraints
        ]
        assert frozenset({"strategy_id", "scheduled_date"}) in col_sets

    def test_backtest_task_status_default_pending_via_db(self) -> None:
        """BacktestTask status 数据库默认值应为 PENDING（通过 SQLite 验证）。"""
        import datetime

        import src.models.report  # noqa: F401
        import src.models.signal  # noqa: F401
        import src.models.user  # noqa: F401
        from src.models.backtest import BacktestTask
        from src.models.strategy import Strategy

        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        with Session(engine) as session:
            strategy = Strategy(
                name="strat1",
                description="d",
                strategy_type="t",
                pairs=["BTC/USDT"],
                config_params={},
            )
            session.add(strategy)
            session.flush()
            task = BacktestTask(
                strategy_id=strategy.id,
                scheduled_date=datetime.date(2026, 3, 14),
            )
            session.add(task)
            session.commit()
            session.refresh(task)
            assert task.status == TaskStatus.PENDING
        Base.metadata.drop_all(engine)

    def test_backtest_task_has_strategy_status_index(self) -> None:
        """BacktestTask 应有 idx_btask_strategy_status 索引。"""
        from src.models.backtest import BacktestTask

        table = BacktestTask.__table__
        index_names = {idx.name for idx in table.indexes}
        assert "idx_btask_strategy_status" in index_names

    def test_backtest_task_strategy_id_is_foreign_key(self) -> None:
        """strategy_id 应为外键，指向 strategies.id。"""
        from sqlalchemy.orm import class_mapper

        from src.models.backtest import BacktestTask

        mapper = class_mapper(BacktestTask)
        col = mapper.columns["strategy_id"]
        fks = list(col.foreign_keys)
        assert len(fks) > 0
        fk_target = list(fks)[0].target_fullname
        assert "strategies.id" in fk_target


class TestBacktestResultModel:
    """测试 BacktestResult 数据模型（任务 2.3）。"""

    def test_backtest_result_tablename(self) -> None:
        """BacktestResult 表名应为 backtest_results。"""
        from src.models.backtest import BacktestResult

        assert BacktestResult.__tablename__ == "backtest_results"

    def test_backtest_result_has_required_columns(self) -> None:
        """BacktestResult 应包含所有必需字段。"""
        from sqlalchemy.orm import class_mapper

        from src.models.backtest import BacktestResult

        mapper = class_mapper(BacktestResult)
        column_names = {c.key for c in mapper.columns}
        required = {
            "id", "strategy_id", "task_id",
            "total_return", "annual_return", "sharpe_ratio",
            "max_drawdown", "trade_count", "win_rate",
            "period_start", "period_end", "created_at",
        }
        for col in required:
            assert col in column_names, f"缺少字段: {col}"

    def test_backtest_result_has_strategy_id_index(self) -> None:
        """BacktestResult 应有 idx_bresult_strategy_id 索引。"""
        from src.models.backtest import BacktestResult

        table = BacktestResult.__table__
        index_names = {idx.name for idx in table.indexes}
        assert "idx_bresult_strategy_id" in index_names

    def test_backtest_result_has_created_at_index(self) -> None:
        """BacktestResult 应有 idx_bresult_created_at 索引。"""
        from src.models.backtest import BacktestResult

        table = BacktestResult.__table__
        index_names = {idx.name for idx in table.indexes}
        assert "idx_bresult_created_at" in index_names

    def test_backtest_result_created_at_timezone(self) -> None:
        """BacktestResult.created_at 应使用 timezone=True。"""
        from sqlalchemy.orm import class_mapper

        from src.models.backtest import BacktestResult

        mapper = class_mapper(BacktestResult)
        col = mapper.columns["created_at"]
        assert isinstance(col.type, DateTime)
        assert col.type.timezone is True

    def test_backtest_result_strategy_id_foreign_key(self) -> None:
        """strategy_id 应为外键。"""
        from sqlalchemy.orm import class_mapper

        from src.models.backtest import BacktestResult

        mapper = class_mapper(BacktestResult)
        col = mapper.columns["strategy_id"]
        fks = list(col.foreign_keys)
        assert len(fks) > 0

    def test_backtest_result_task_id_foreign_key(self) -> None:
        """task_id 应为外键。"""
        from sqlalchemy.orm import class_mapper

        from src.models.backtest import BacktestResult

        mapper = class_mapper(BacktestResult)
        col = mapper.columns["task_id"]
        fks = list(col.foreign_keys)
        assert len(fks) > 0


# ============================================================
# 2.4 - TradingSignal、ResearchReport、ReportCoin 模型测试
# ============================================================


class TestTradingSignalModel:
    """测试 TradingSignal 数据模型（任务 2.4）。"""

    def test_trading_signal_tablename(self) -> None:
        """TradingSignal 表名应为 trading_signals。"""
        from src.models.signal import TradingSignal

        assert TradingSignal.__tablename__ == "trading_signals"

    def test_trading_signal_has_required_columns(self) -> None:
        """TradingSignal 应包含所有必需字段。"""
        from sqlalchemy.orm import class_mapper

        from src.models.signal import TradingSignal

        mapper = class_mapper(TradingSignal)
        column_names = {c.key for c in mapper.columns}
        required = {
            "id", "strategy_id", "pair", "direction",
            "confidence_score", "signal_at", "created_at",
        }
        for col in required:
            assert col in column_names, f"缺少字段: {col}"

    def test_trading_signal_has_strategy_at_index(self) -> None:
        """TradingSignal 应有 idx_signal_strategy_at 索引。"""
        from src.models.signal import TradingSignal

        table = TradingSignal.__table__
        index_names = {idx.name for idx in table.indexes}
        assert "idx_signal_strategy_at" in index_names

    def test_trading_signal_direction_uses_enum(self) -> None:
        """direction 字段值应为 SignalDirection 枚举。"""
        from src.models.signal import TradingSignal

        signal = TradingSignal(
            strategy_id=1,
            pair="BTC/USDT",
            direction=SignalDirection.BUY,
            confidence_score=0.85,
            signal_at=None,
        )
        assert signal.direction == SignalDirection.BUY

    def test_trading_signal_signal_at_timezone(self) -> None:
        """signal_at 应使用 timezone=True。"""
        from sqlalchemy.orm import class_mapper

        from src.models.signal import TradingSignal

        mapper = class_mapper(TradingSignal)
        col = mapper.columns["signal_at"]
        assert isinstance(col.type, DateTime)
        assert col.type.timezone is True

    def test_trading_signal_created_at_timezone(self) -> None:
        """created_at 应使用 timezone=True。"""
        from sqlalchemy.orm import class_mapper

        from src.models.signal import TradingSignal

        mapper = class_mapper(TradingSignal)
        col = mapper.columns["created_at"]
        assert isinstance(col.type, DateTime)
        assert col.type.timezone is True

    def test_trading_signal_strategy_id_foreign_key(self) -> None:
        """strategy_id 应为外键，指向 strategies.id。"""
        from sqlalchemy.orm import class_mapper

        from src.models.signal import TradingSignal

        mapper = class_mapper(TradingSignal)
        col = mapper.columns["strategy_id"]
        fks = list(col.foreign_keys)
        assert len(fks) > 0
        fk_target = list(fks)[0].target_fullname
        assert "strategies.id" in fk_target


class TestResearchReportModel:
    """测试 ResearchReport 数据模型（任务 2.4）。"""

    def test_research_report_tablename(self) -> None:
        """ResearchReport 表名应为 research_reports。"""
        from src.models.report import ResearchReport

        assert ResearchReport.__tablename__ == "research_reports"

    def test_research_report_has_required_columns(self) -> None:
        """ResearchReport 应包含所有必需字段。"""
        from sqlalchemy.orm import class_mapper

        from src.models.report import ResearchReport

        mapper = class_mapper(ResearchReport)
        column_names = {c.key for c in mapper.columns}
        required = {
            "id", "title", "summary", "content",
            "generated_at", "created_at", "updated_at",
        }
        for col in required:
            assert col in column_names, f"缺少字段: {col}"

    def test_research_report_has_generated_at_index(self) -> None:
        """ResearchReport 应有 idx_report_generated_at 索引。"""
        from src.models.report import ResearchReport

        table = ResearchReport.__table__
        index_names = {idx.name for idx in table.indexes}
        assert "idx_report_generated_at" in index_names

    def test_research_report_summary_is_text(self) -> None:
        """summary 字段应为 Text 类型。"""
        from sqlalchemy import Text
        from sqlalchemy.orm import class_mapper

        from src.models.report import ResearchReport

        mapper = class_mapper(ResearchReport)
        col = mapper.columns["summary"]
        assert isinstance(col.type, Text)

    def test_research_report_content_is_text(self) -> None:
        """content 字段应为 Text 类型。"""
        from sqlalchemy import Text
        from sqlalchemy.orm import class_mapper

        from src.models.report import ResearchReport

        mapper = class_mapper(ResearchReport)
        col = mapper.columns["content"]
        assert isinstance(col.type, Text)

    def test_research_report_generated_at_timezone(self) -> None:
        """generated_at 应使用 timezone=True。"""
        from sqlalchemy.orm import class_mapper

        from src.models.report import ResearchReport

        mapper = class_mapper(ResearchReport)
        col = mapper.columns["generated_at"]
        assert isinstance(col.type, DateTime)
        assert col.type.timezone is True

    def test_research_report_inherits_timestamp_mixin(self) -> None:
        """ResearchReport 应继承 TimestampMixin。"""
        from src.models.report import ResearchReport

        assert issubclass(ResearchReport, TimestampMixin)


class TestReportCoinModel:
    """测试 ReportCoin 关联表模型（任务 2.4）。"""

    def test_report_coin_tablename(self) -> None:
        """ReportCoin 表名应为 report_coins。"""
        from src.models.report import ReportCoin

        assert ReportCoin.__tablename__ == "report_coins"

    def test_report_coin_has_required_columns(self) -> None:
        """ReportCoin 应包含所有必需字段。"""
        from sqlalchemy.orm import class_mapper

        from src.models.report import ReportCoin

        mapper = class_mapper(ReportCoin)
        column_names = {c.key for c in mapper.columns}
        assert "id" in column_names
        assert "report_id" in column_names
        assert "coin_symbol" in column_names

    def test_report_coin_has_report_id_index(self) -> None:
        """ReportCoin 应有 idx_reportcoin_report_id 索引。"""
        from src.models.report import ReportCoin

        table = ReportCoin.__table__
        index_names = {idx.name for idx in table.indexes}
        assert "idx_reportcoin_report_id" in index_names

    def test_report_coin_report_id_foreign_key(self) -> None:
        """report_id 应为外键，指向 research_reports.id。"""
        from sqlalchemy.orm import class_mapper

        from src.models.report import ReportCoin

        mapper = class_mapper(ReportCoin)
        col = mapper.columns["report_id"]
        fks = list(col.foreign_keys)
        assert len(fks) > 0
        fk_target = list(fks)[0].target_fullname
        assert "research_reports.id" in fk_target


# ============================================================
# 集成：所有模型注册到 Base.metadata 测试
# ============================================================


class TestModelsRegisteredInMetadata:
    """确保所有模型都注册到 Base.metadata。"""

    def test_all_tables_in_metadata(self) -> None:
        """所有业务表应注册到 Base.metadata。"""
        # 先导入所有模型触发注册
        import src.models.backtest  # noqa: F401
        import src.models.report  # noqa: F401
        import src.models.signal  # noqa: F401
        import src.models.strategy  # noqa: F401
        import src.models.user  # noqa: F401

        table_names = set(Base.metadata.tables.keys())
        expected = {
            "users",
            "strategies",
            "backtest_tasks",
            "backtest_results",
            "trading_signals",
            "research_reports",
            "report_coins",
        }
        for table in expected:
            assert table in table_names, f"表 {table} 未注册到 Base.metadata"

    def test_metadata_can_create_tables_in_memory(self) -> None:
        """使用 SQLite 内存数据库验证所有模型可成功建表。"""
        import src.models.backtest  # noqa: F401
        import src.models.report  # noqa: F401
        import src.models.signal  # noqa: F401
        import src.models.strategy  # noqa: F401
        import src.models.user  # noqa: F401

        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        insp = inspect(engine)
        table_names = set(insp.get_table_names())
        expected = {
            "users",
            "strategies",
            "backtest_tasks",
            "backtest_results",
            "trading_signals",
            "research_reports",
            "report_coins",
        }
        for table in expected:
            assert table in table_names, f"SQLite 中未找到表 {table}"
        Base.metadata.drop_all(engine)
