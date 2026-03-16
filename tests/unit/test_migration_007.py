"""任务 1.2 单元测试：trading_signals 约束迁移文件。

验证迁移文件 007_add_trading_signals_constraints.py 的结构：
- 文件存在且可导入
- revision/down_revision 正确
- upgrade/downgrade 函数存在
- upgrade 中包含唯一索引和 created_at 索引的创建语句
"""

import importlib
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).parent.parent.parent / "migrations" / "versions"


def _load_migration_007():
    """加载 007 迁移模块。"""
    files = list(MIGRATIONS_DIR.glob("007_*.py"))
    assert len(files) == 1, "找不到 007_*.py 迁移文件，请先创建"
    module_name = f"migrations.versions.{files[0].stem}"
    return importlib.import_module(module_name)


class TestMigration007Exists:
    """验证迁移文件 007 存在。"""

    def test_migration_007_file_exists(self) -> None:
        """007_add_trading_signals_constraints.py 应存在。"""
        files = list(MIGRATIONS_DIR.glob("007_*.py"))
        assert len(files) == 1, "缺少 007_add_trading_signals_constraints.py"

    def test_migration_007_importable(self) -> None:
        """007 迁移文件应可成功导入。"""
        mod = _load_migration_007()
        assert mod is not None


class TestMigration007Structure:
    """验证 007 迁移文件结构。"""

    def test_has_revision_id(self) -> None:
        """应有 revision 字段。"""
        mod = _load_migration_007()
        assert hasattr(mod, "revision")
        assert mod.revision == "007"

    def test_has_down_revision(self) -> None:
        """down_revision 应指向 006。"""
        mod = _load_migration_007()
        assert hasattr(mod, "down_revision")
        assert mod.down_revision == "006"

    def test_has_upgrade_function(self) -> None:
        """应有 upgrade 函数。"""
        mod = _load_migration_007()
        assert callable(getattr(mod, "upgrade", None))

    def test_has_downgrade_function(self) -> None:
        """应有 downgrade 函数（向下迁移回滚支持）。"""
        mod = _load_migration_007()
        assert callable(getattr(mod, "downgrade", None))


class TestMigration007Content:
    """验证迁移文件内容中包含必要的索引创建语句。"""

    def _get_source(self) -> str:
        files = list(MIGRATIONS_DIR.glob("007_*.py"))
        return files[0].read_text()

    def test_unique_constraint_in_upgrade(self) -> None:
        """upgrade 应包含 (strategy_id, pair, timeframe) 唯一索引创建。"""
        src = self._get_source()
        assert "uq_trading_signals_strategy_pair_tf" in src

    def test_created_at_index_in_upgrade(self) -> None:
        """upgrade 应包含 created_at 降序索引。"""
        src = self._get_source()
        assert "idx_signal_created_at" in src

    def test_downgrade_drops_indexes(self) -> None:
        """downgrade 应包含删除索引的操作（回滚支持）。"""
        src = self._get_source()
        assert "drop_index" in src

    def test_dry_run_safety_note(self) -> None:
        """迁移文件应包含必要注释（重复记录清理说明）。"""
        src = self._get_source()
        # 文件注释中应提及清理重复记录或唯一约束
        assert "unique" in src.lower() or "UNIQUE" in src
