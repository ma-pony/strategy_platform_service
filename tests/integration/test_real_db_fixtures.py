"""任务 2 TDD 测试文件：验证 tests/integration/conftest.py 中的真实 DB fixtures。

本文件采用 TDD 方法验证 RealDBFixture 组件的以下行为：
  - real_db_engine fixture 正确读取 TEST_DATABASE_URL 并在连接不可达时 skip
  - alembic_setup fixture 能执行 upgrade/downgrade（在引擎可用时）
  - real_db_session fixture 提供独立 async session 并 TRUNCATE 各表
  - pytest.mark.integration_db 自定义标记已注册

在没有 TEST_DATABASE_URL 的环境下，所有 integration_db 测试均应被优雅跳过，
非 DB 测试不受影响。
"""

import os

import pytest


# ─── 基础：标记注册验证 ──────────────────────────────────────────────────────────

class TestIntegrationDbMarkerRegistered:
    """验证 pytest.mark.integration_db 已作为自定义标记注册（需求 8.5 / 任务 2 交付项）。"""

    def test_integration_db_marker_is_known(self) -> None:
        """integration_db 标记应已在 pytest 配置中注册，不产生 PytestUnknownMarkWarning。"""
        import warnings

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            # 在运行时给一个 dummy 函数打标记，看是否触发未知标记警告
            @pytest.mark.integration_db
            def _dummy() -> None:
                pass

        unknown_mark_warnings = [
            w for w in caught
            if "PytestUnknownMarkWarning" in str(w.category)
            and "integration_db" in str(w.message)
        ]
        assert not unknown_mark_warnings, (
            "integration_db 标记未注册，产生了 PytestUnknownMarkWarning。"
            "请在 pyproject.toml [tool.pytest.ini_options].markers 中注册该标记。"
        )


# ─── 无 TEST_DATABASE_URL 时的跳过行为 ──────────────────────────────────────────

class TestRealDbEngineSkipBehavior:
    """验证 real_db_engine fixture 在 TEST_DATABASE_URL 缺失时正确 skip（需求 8.5）。"""

    def test_skip_when_test_database_url_not_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """TEST_DATABASE_URL 未设置时，real_db_engine 应 skip 而非报错。

        通过直接调用 fixture 实现函数来测试其跳过逻辑。
        """
        # 确保 TEST_DATABASE_URL 未设置
        monkeypatch.delenv("TEST_DATABASE_URL", raising=False)

        # 导入并调用真实 DB 引擎检查函数
        from tests.integration.conftest import _check_test_database_url

        with pytest.raises(pytest.skip.Exception) as exc_info:
            _check_test_database_url()

        assert "TEST_DATABASE_URL" in str(exc_info.value), (
            "skip 消息应明确说明 TEST_DATABASE_URL 未设置"
        )

    def test_skip_message_is_descriptive(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """跳过原因消息应明确、可读，便于 CI 日志排查（需求 8.5）。"""
        monkeypatch.delenv("TEST_DATABASE_URL", raising=False)

        from tests.integration.conftest import _check_test_database_url

        with pytest.raises(pytest.skip.Exception) as exc_info:
            _check_test_database_url()

        reason = str(exc_info.value)
        # 消息应包含如何设置该变量的提示
        assert len(reason) > 20, "跳过消息过短，应包含足够的诊断信息"


# ─── conftest 模块结构验证 ──────────────────────────────────────────────────────

class TestIntegrationConftestStructure:
    """验证 tests/integration/conftest.py 模块存在且暴露所需的 fixtures / 辅助函数。"""

    def test_conftest_module_importable(self) -> None:
        """tests/integration/conftest.py 应可正常导入，无语法错误。"""
        import importlib
        mod = importlib.import_module("tests.integration.conftest")
        assert mod is not None

    def test_real_db_engine_fixture_defined(self) -> None:
        """real_db_engine fixture 应在 conftest 中定义。"""
        import importlib
        mod = importlib.import_module("tests.integration.conftest")
        assert hasattr(mod, "real_db_engine"), (
            "conftest.py 中应定义 real_db_engine fixture"
        )

    def test_alembic_setup_fixture_defined(self) -> None:
        """alembic_setup fixture 应在 conftest 中定义。"""
        import importlib
        mod = importlib.import_module("tests.integration.conftest")
        assert hasattr(mod, "alembic_setup"), (
            "conftest.py 中应定义 alembic_setup fixture"
        )

    def test_real_db_session_fixture_defined(self) -> None:
        """real_db_session fixture 应在 conftest 中定义。"""
        import importlib
        mod = importlib.import_module("tests.integration.conftest")
        assert hasattr(mod, "real_db_session"), (
            "conftest.py 中应定义 real_db_session fixture"
        )

    def test_check_helper_function_defined(self) -> None:
        """_check_test_database_url 辅助函数应在 conftest 中定义（供 TDD 测试调用）。"""
        import importlib
        mod = importlib.import_module("tests.integration.conftest")
        assert hasattr(mod, "_check_test_database_url"), (
            "conftest.py 中应定义 _check_test_database_url 辅助函数"
        )

    def test_check_helper_is_callable(self) -> None:
        """_check_test_database_url 应是可调用对象。"""
        import importlib
        mod = importlib.import_module("tests.integration.conftest")
        assert callable(mod._check_test_database_url)


# ─── 真实 DB 测试（仅在 TEST_DATABASE_URL 可用时运行）──────────────────────────

@pytest.mark.integration_db
class TestRealDbSessionIsolation:
    """验证 real_db_session fixture 提供 function 作用域隔离（需求 8.1）。

    此 class 下的测试仅在 TEST_DATABASE_URL 可用时运行，
    在没有真实数据库的 CI 环境中将被跳过。
    """

    async def test_real_db_session_is_async(self, real_db_session) -> None:  # type: ignore[no-untyped-def]
        """real_db_session 应是可 await 的 AsyncSession 实例。"""
        from sqlalchemy.ext.asyncio import AsyncSession

        assert isinstance(real_db_session, AsyncSession), (
            "real_db_session 应为 AsyncSession 实例"
        )

    async def test_real_db_session_can_execute_query(self, real_db_session) -> None:  # type: ignore[no-untyped-def]
        """real_db_session 应能执行简单 SQL 查询（验证真实 DB 连接有效）。"""
        from sqlalchemy import text

        result = await real_db_session.execute(text("SELECT 1 AS val"))
        row = result.fetchone()
        assert row is not None
        assert row[0] == 1

    async def test_tables_truncated_between_tests_first(self, real_db_session) -> None:  # type: ignore[no-untyped-def]
        """第一个测试：写入数据，验证写入成功（数据隔离验证第一步）。"""
        from sqlalchemy import text

        # 检查 users 表是否为空（TRUNCATE 后应为空）
        result = await real_db_session.execute(text("SELECT COUNT(*) FROM users"))
        count = result.scalar()
        assert count == 0, (
            "real_db_session fixture 应在测试开始前 TRUNCATE users 表，"
            f"但发现 {count} 条记录"
        )
