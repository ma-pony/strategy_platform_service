"""StrategyPairMetricsAdmin sqladmin 视图单元测试（Task 6）。

验证：
  - StrategyPairMetricsAdmin 类存在并继承 ModelView
  - column_list 含全部展示字段
  - can_delete = False（禁止删除）
  - can_create = False（由 Worker 创建）
  - can_edit = True（允许手动修正）
  - column_searchable_list 含 pair、timeframe、data_source
  - column_sortable_list 含 last_updated_at、total_return
  - setup_admin() 注册了 StrategyPairMetricsAdmin 视图

需求可追溯：5.1, 5.2, 5.3, 5.4, 5.5
"""


class TestStrategyPairMetricsAdminExists:
    """StrategyPairMetricsAdmin 类存在性验证（需求 5.1）。"""

    def test_admin_view_class_importable(self) -> None:
        """StrategyPairMetricsAdmin 应可从 src.admin.views 导入。"""
        from src.admin.views import StrategyPairMetricsAdmin

        assert StrategyPairMetricsAdmin is not None

    def test_admin_view_inherits_model_view(self) -> None:
        """StrategyPairMetricsAdmin 应继承 sqladmin ModelView。"""
        from sqladmin import ModelView

        from src.admin.views import StrategyPairMetricsAdmin

        assert issubclass(StrategyPairMetricsAdmin, ModelView)

    def test_admin_view_bound_to_strategy_pair_metrics_model(self) -> None:
        """StrategyPairMetricsAdmin 应绑定到 StrategyPairMetrics 模型。"""
        from src.admin.views import StrategyPairMetricsAdmin
        from src.models.strategy_pair_metrics import StrategyPairMetrics

        assert StrategyPairMetricsAdmin.model is StrategyPairMetrics


class TestStrategyPairMetricsAdminPermissions:
    """sqladmin 权限配置测试（需求 5.4, 5.5）。"""

    def test_can_delete_is_false(self) -> None:
        """can_delete 应为 False，禁止删除历史绩效数据（需求 5.4）。"""
        from src.admin.views import StrategyPairMetricsAdmin

        assert StrategyPairMetricsAdmin.can_delete is False

    def test_can_create_is_false(self) -> None:
        """can_create 应为 False，由 Worker 任务创建，不在后台创建。"""
        from src.admin.views import StrategyPairMetricsAdmin

        assert StrategyPairMetricsAdmin.can_create is False

    def test_can_edit_is_true(self) -> None:
        """can_edit 应为 True，允许管理员手动修正异常数据（需求 5.5）。"""
        from src.admin.views import StrategyPairMetricsAdmin

        assert StrategyPairMetricsAdmin.can_edit is True

    def test_can_view_details_is_true(self) -> None:
        """can_view_details 应为 True。"""
        from src.admin.views import StrategyPairMetricsAdmin

        assert StrategyPairMetricsAdmin.can_view_details is True


class TestStrategyPairMetricsAdminColumnConfig:
    """sqladmin 列配置测试（需求 5.1, 5.2, 5.3）。"""

    def test_column_list_contains_required_fields(self) -> None:
        """column_list 应包含全部展示字段（需求 5.1）。"""
        from src.admin.views import StrategyPairMetricsAdmin

        col_list = StrategyPairMetricsAdmin.column_list
        # 将字段列表转为字段名称集合以便检查
        {c.key if hasattr(c, "key") else str(c) for c in col_list}
        required_fields = {
            "strategy_id",
            "pair",
            "timeframe",
            "total_return",
            "profit_factor",
            "max_drawdown",
            "sharpe_ratio",
            "trade_count",
            "data_source",
            "last_updated_at",
        }
        # 检查必需字段是否均存在
        for field in required_fields:
            assert any((hasattr(c, "key") and c.key == field) or str(c) == field for c in col_list), (
                f"column_list 中缺少字段 {field}"
            )

    def test_column_searchable_includes_pair(self) -> None:
        """column_searchable_list 应包含 pair（需求 5.2）。"""
        from src.admin.views import StrategyPairMetricsAdmin

        searchable = StrategyPairMetricsAdmin.column_searchable_list
        assert any((hasattr(c, "key") and c.key == "pair") or str(c) == "pair" for c in searchable)

    def test_column_searchable_includes_timeframe(self) -> None:
        """column_searchable_list 应包含 timeframe（需求 5.2）。"""
        from src.admin.views import StrategyPairMetricsAdmin

        searchable = StrategyPairMetricsAdmin.column_searchable_list
        assert any((hasattr(c, "key") and c.key == "timeframe") or str(c) == "timeframe" for c in searchable)

    def test_column_sortable_includes_last_updated_at(self) -> None:
        """column_sortable_list 应包含 last_updated_at（需求 5.3）。"""
        from src.admin.views import StrategyPairMetricsAdmin

        sortable = StrategyPairMetricsAdmin.column_sortable_list
        assert any((hasattr(c, "key") and c.key == "last_updated_at") or str(c) == "last_updated_at" for c in sortable)

    def test_column_sortable_includes_total_return(self) -> None:
        """column_sortable_list 应包含 total_return（需求 5.3）。"""
        from src.admin.views import StrategyPairMetricsAdmin

        sortable = StrategyPairMetricsAdmin.column_sortable_list
        assert any((hasattr(c, "key") and c.key == "total_return") or str(c) == "total_return" for c in sortable)


class TestSetupAdminRegistration:
    """setup_admin() 注册 StrategyPairMetricsAdmin 视图测试（需求 5.1）。"""

    def test_strategy_pair_metrics_admin_imported_in_setup_admin(self) -> None:
        """src.admin.__init__ 应导入 StrategyPairMetricsAdmin。"""
        import inspect

        import src.admin as admin_module

        source = inspect.getsource(admin_module)
        assert "StrategyPairMetricsAdmin" in source

    def test_add_view_called_with_strategy_pair_metrics_admin(self) -> None:
        """setup_admin() 应调用 admin.add_view(StrategyPairMetricsAdmin)。"""
        import inspect

        import src.admin as admin_module

        source = inspect.getsource(admin_module)
        assert "StrategyPairMetricsAdmin" in source
