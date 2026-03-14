"""Alembic 迁移文件单元测试。

验证所有迁移文件语法正确，upgrade/downgrade 函数存在，
以及迁移链依赖关系符合规范。
"""

import importlib
from pathlib import Path

import pytest

MIGRATIONS_DIR = (
    Path(__file__).parent.parent.parent / "migrations" / "versions"
)

EXPECTED_MIGRATIONS = {
    "001": "create_users",
    "002": "create_strategies",
    "003": "create_backtest_tables",
    "004": "create_trading_signals",
    "005": "create_research_reports",
}


def _load_migration(rev_id: str):
    """加载指定 revision 的迁移模块。"""
    files = list(MIGRATIONS_DIR.glob(f"{rev_id}_*.py"))
    assert len(files) == 1, f"找不到 revision {rev_id} 的迁移文件"
    module_name = f"migrations.versions.{files[0].stem}"
    return importlib.import_module(module_name)


class TestMigrationFilesExist:
    """验证所有迁移文件存在。"""

    def test_migration_directory_exists(self) -> None:
        """migrations/versions 目录应存在。"""
        assert MIGRATIONS_DIR.exists()
        assert MIGRATIONS_DIR.is_dir()

    @pytest.mark.parametrize("rev_id,slug", EXPECTED_MIGRATIONS.items())
    def test_migration_file_exists(self, rev_id: str, slug: str) -> None:
        """每个迁移文件应存在。"""
        files = list(MIGRATIONS_DIR.glob(f"{rev_id}_*.py"))
        assert len(files) == 1, f"缺少 {rev_id}_{slug}.py 迁移文件"


class TestMigrationStructure:
    """验证迁移文件结构（revision、up/down 函数）。"""

    @pytest.mark.parametrize("rev_id", EXPECTED_MIGRATIONS.keys())
    def test_migration_has_revision_id(self, rev_id: str) -> None:
        """迁移文件应有正确的 revision ID。"""
        module = _load_migration(rev_id)
        assert hasattr(module, "revision")
        assert module.revision == rev_id

    @pytest.mark.parametrize("rev_id", EXPECTED_MIGRATIONS.keys())
    def test_migration_has_upgrade_function(self, rev_id: str) -> None:
        """迁移文件应有 upgrade() 函数。"""
        module = _load_migration(rev_id)
        assert hasattr(module, "upgrade")
        assert callable(module.upgrade)

    @pytest.mark.parametrize("rev_id", EXPECTED_MIGRATIONS.keys())
    def test_migration_has_downgrade_function(self, rev_id: str) -> None:
        """迁移文件应有 downgrade() 函数。"""
        module = _load_migration(rev_id)
        assert hasattr(module, "downgrade")
        assert callable(module.downgrade)

    @pytest.mark.parametrize("rev_id", EXPECTED_MIGRATIONS.keys())
    def test_migration_has_down_revision(self, rev_id: str) -> None:
        """迁移文件应声明 down_revision。"""
        module = _load_migration(rev_id)
        assert hasattr(module, "down_revision")


class TestMigrationChain:
    """验证迁移链依赖关系。"""

    def test_001_has_no_predecessor(self) -> None:
        """001 迁移应无前置迁移（首次迁移）。"""
        module = _load_migration("001")
        assert module.down_revision is None

    def test_002_depends_on_001(self) -> None:
        """002 迁移应依赖 001。"""
        module = _load_migration("002")
        assert module.down_revision == "001"

    def test_003_depends_on_002(self) -> None:
        """003 迁移应依赖 002。"""
        module = _load_migration("003")
        assert module.down_revision == "002"

    def test_004_depends_on_003(self) -> None:
        """004 迁移应依赖 003。"""
        module = _load_migration("004")
        assert module.down_revision == "003"

    def test_005_depends_on_004(self) -> None:
        """005 迁移应依赖 004。"""
        module = _load_migration("005")
        assert module.down_revision == "004"
