"""sqladmin 管理后台单元测试（任务 11）。

验证：
  - AdminAuth 实现 AuthenticationBackend 接口
  - AdminAuth.login 使用正确凭证时返回 True
  - AdminAuth.login 使用错误凭证时返回 False
  - AdminAuth.authenticate 返回包含 token 的会话状态
  - AdminAuth.logout 清除会话数据
  - UserAdmin can_delete=False（禁止后台删除用户）
  - UserAdmin 展示必要字段（username, membership, is_active, created_at）
  - StrategyAdmin 支持创建和编辑
  - ReportAdmin 支持列表、创建、编辑
  - setup_admin 函数可正常调用并注册视图
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestAdminAuth:
    """AdminAuth 认证后端测试。"""

    def test_admin_auth_is_authentication_backend(self) -> None:
        """AdminAuth 应该是 AuthenticationBackend 的实例。"""
        from sqladmin.authentication import AuthenticationBackend

        from src.admin.auth import AdminAuth

        auth = AdminAuth(secret_key="test-secret")
        assert isinstance(auth, AuthenticationBackend)

    @pytest.mark.asyncio
    async def test_login_returns_true_with_correct_credentials(self) -> None:
        """使用正确管理员凭证时 login 返回 True。"""
        from src.admin.auth import AdminAuth

        auth = AdminAuth(
            secret_key="test-secret",
            admin_username="admin",
            admin_password="adminpass",
        )

        mock_request = MagicMock()
        mock_request.form = AsyncMock(return_value={"username": "admin", "password": "adminpass"})
        mock_request.session = {}

        result = await auth.login(mock_request)
        assert result is True

    @pytest.mark.asyncio
    async def test_login_returns_false_with_wrong_password(self) -> None:
        """使用错误密码时 login 返回 False。"""
        from src.admin.auth import AdminAuth

        auth = AdminAuth(
            secret_key="test-secret",
            admin_username="admin",
            admin_password="adminpass",
        )

        mock_request = MagicMock()
        mock_request.form = AsyncMock(return_value={"username": "admin", "password": "wrongpassword"})
        mock_request.session = {}

        result = await auth.login(mock_request)
        assert result is False

    @pytest.mark.asyncio
    async def test_login_returns_false_with_wrong_username(self) -> None:
        """使用错误用户名时 login 返回 False。"""
        from src.admin.auth import AdminAuth

        auth = AdminAuth(
            secret_key="test-secret",
            admin_username="admin",
            admin_password="adminpass",
        )

        mock_request = MagicMock()
        mock_request.form = AsyncMock(return_value={"username": "wrongadmin", "password": "adminpass"})
        mock_request.session = {}

        result = await auth.login(mock_request)
        assert result is False

    @pytest.mark.asyncio
    async def test_login_stores_token_in_session(self) -> None:
        """login 成功时在 session 中存储 token。"""
        from src.admin.auth import AdminAuth

        auth = AdminAuth(
            secret_key="test-secret",
            admin_username="admin",
            admin_password="adminpass",
        )

        mock_request = MagicMock()
        mock_request.form = AsyncMock(return_value={"username": "admin", "password": "adminpass"})
        mock_request.session = {}

        await auth.login(mock_request)
        # 成功登录后 session 应包含认证 token
        assert "admin_token" in mock_request.session

    @pytest.mark.asyncio
    async def test_logout_clears_session_token(self) -> None:
        """logout 应清除 session 中的 token。"""
        from src.admin.auth import AdminAuth

        auth = AdminAuth(secret_key="test-secret")

        mock_request = MagicMock()
        mock_request.session = {"admin_token": "some-token"}

        result = await auth.logout(mock_request)
        assert result is True
        assert "admin_token" not in mock_request.session

    @pytest.mark.asyncio
    async def test_authenticate_returns_true_with_valid_token(self) -> None:
        """session 中有有效 token 时 authenticate 返回 True。"""
        from src.admin.auth import AdminAuth

        auth = AdminAuth(secret_key="test-secret")

        mock_request = MagicMock()
        mock_request.session = {"admin_token": "valid-token"}

        result = await auth.authenticate(mock_request)
        assert result is True

    @pytest.mark.asyncio
    async def test_authenticate_returns_false_without_token(self) -> None:
        """session 中没有 token 时 authenticate 返回 False。"""
        from src.admin.auth import AdminAuth

        auth = AdminAuth(secret_key="test-secret")

        mock_request = MagicMock()
        mock_request.session = {}

        result = await auth.authenticate(mock_request)
        assert result is False


class TestUserAdmin:
    """UserAdmin ModelView 测试。"""

    def test_user_admin_cannot_delete(self) -> None:
        """UserAdmin.can_delete 应为 False，禁止后台删除用户。"""
        from src.admin.views import UserAdmin

        assert UserAdmin.can_delete is False

    def test_user_admin_column_list_includes_required_fields(self) -> None:
        """UserAdmin.column_list 应包含 email, membership, is_active, created_at（需求 3.5）。"""
        from src.admin.views import UserAdmin

        column_list = UserAdmin.column_list
        # 检查字段名称（通过字符串或属性判断）
        column_names = []
        for col in column_list:
            if hasattr(col, "key"):
                column_names.append(col.key)
            elif isinstance(col, str):
                column_names.append(col)

        assert "email" in column_names
        assert "username" not in column_names
        assert "membership" in column_names
        assert "is_active" in column_names
        assert "created_at" in column_names

    def test_user_admin_search_includes_email(self) -> None:
        """UserAdmin.column_searchable_list 应包含 email（需求 3.5）。"""
        from src.admin.views import UserAdmin

        searchable = UserAdmin.column_searchable_list
        search_names = []
        for col in searchable:
            if hasattr(col, "key"):
                search_names.append(col.key)
            elif isinstance(col, str):
                search_names.append(col)

        assert "email" in search_names
        assert "username" not in search_names

    def test_user_admin_sortable_includes_created_at(self) -> None:
        """UserAdmin.column_sortable_list 应包含 created_at。"""
        from src.admin.views import UserAdmin

        sortable = UserAdmin.column_sortable_list
        sort_names = []
        for col in sortable:
            if hasattr(col, "key"):
                sort_names.append(col.key)
            elif isinstance(col, str):
                sort_names.append(col)

        assert "created_at" in sort_names


class TestStrategyAdmin:
    """StrategyAdmin ModelView 测试。"""

    def test_strategy_admin_can_create(self) -> None:
        """StrategyAdmin.can_create 应为 True（支持创建策略）。"""
        from src.admin.views import StrategyAdmin

        assert StrategyAdmin.can_create is True

    def test_strategy_admin_can_edit(self) -> None:
        """StrategyAdmin.can_edit 应为 True（支持编辑策略）。"""
        from src.admin.views import StrategyAdmin

        assert StrategyAdmin.can_edit is True


class TestReportAdmin:
    """ReportAdmin ModelView 测试。"""

    def test_report_admin_can_create(self) -> None:
        """ReportAdmin.can_create 应为 True（支持创建研报）。"""
        from src.admin.views import ReportAdmin

        assert ReportAdmin.can_create is True

    def test_report_admin_can_edit(self) -> None:
        """ReportAdmin.can_edit 应为 True（支持编辑研报）。"""
        from src.admin.views import ReportAdmin

        assert ReportAdmin.can_edit is True

    def test_report_admin_search_includes_title(self) -> None:
        """ReportAdmin.column_searchable_list 应包含 title。"""
        from src.admin.views import ReportAdmin

        searchable = ReportAdmin.column_searchable_list
        search_names = []
        for col in searchable:
            if hasattr(col, "key"):
                search_names.append(col.key)
            elif isinstance(col, str):
                search_names.append(col)

        assert "title" in search_names

    def test_report_admin_sortable_includes_generated_at(self) -> None:
        """ReportAdmin.column_sortable_list 应包含 generated_at。"""
        from src.admin.views import ReportAdmin

        sortable = ReportAdmin.column_sortable_list
        sort_names = []
        for col in sortable:
            if hasattr(col, "key"):
                sort_names.append(col.key)
            elif isinstance(col, str):
                sort_names.append(col)

        assert "generated_at" in sort_names


class TestSetupAdmin:
    """setup_admin 函数测试。"""

    def test_setup_admin_registers_views_and_returns_none(self) -> None:
        """setup_admin 应成功注册视图，不抛出异常。"""
        from unittest.mock import MagicMock

        from fastapi import FastAPI

        app = FastAPI()
        mock_engine = MagicMock()

        mock_settings = MagicMock()
        mock_settings.secret_key = "test-secret-key"

        with (
            patch("src.admin.AdminAuth") as mock_auth_cls,
            patch("src.admin.Admin") as mock_admin_cls,
            patch("src.core.app_settings.get_settings", return_value=mock_settings),
        ):
            mock_auth_instance = MagicMock()
            mock_auth_cls.return_value = mock_auth_instance

            mock_admin_instance = MagicMock()
            mock_admin_cls.return_value = mock_admin_instance

            from src.admin import setup_admin

            setup_admin(app, mock_engine)

            # 验证 Admin 实例被创建
            assert mock_admin_cls.called
            # 验证 add_view 被调用七次
            # （User、Strategy、Report、TradingSignal、BacktestTask、BacktestResult、StrategyPairMetrics）
            assert mock_admin_instance.add_view.call_count == 7
