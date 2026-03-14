"""sqladmin ModelView 视图定义（任务 11.2）。

提供三个管理视图：
  - UserAdmin：用户管理（列表展示、搜索、排序，禁止删除）
  - StrategyAdmin：策略管理（列表、创建、编辑）
  - ReportAdmin：研报管理（列表、创建、编辑、搜索、排序）

关键约束：
  - UserAdmin.can_delete = False：禁止后台删除用户
  - 所有 ModelView 使用 SQLAlchemy 模型与 sqladmin 集成
"""

from sqladmin import ModelView

from src.models.report import ResearchReport
from src.models.strategy import Strategy
from src.models.user import User


class UserAdmin(ModelView, model=User):
    """用户管理视图。

    支持列表展示、按 username 搜索、按 created_at 排序。
    允许编辑 membership 和 is_active 字段。
    禁止后台删除用户（can_delete=False）。
    """

    name = "用户"
    name_plural = "用户列表"

    # 展示列
    column_list = [
        User.id,
        User.username,
        User.membership,
        User.is_active,
        User.is_admin,
        User.created_at,
    ]

    # 可搜索字段
    column_searchable_list = [User.username]

    # 可排序字段
    column_sortable_list = [User.created_at]

    # 可编辑字段（membership 和 is_active）
    form_columns = [User.membership, User.is_active, User.is_admin]

    # 禁止删除
    can_delete = False

    # 允许列表展示和编辑
    can_view_details = True
    can_create = False  # 用户通过注册接口创建，不在后台创建
    can_edit = True


class StrategyAdmin(ModelView, model=Strategy):
    """策略管理视图。

    作为维护策略数据的唯一入口，支持创建、编辑策略配置。
    """

    name = "策略"
    name_plural = "策略列表"

    # 展示列
    column_list = [
        Strategy.id,
        Strategy.name,
        Strategy.strategy_type,
        Strategy.is_active,
        Strategy.created_at,
    ]

    # 可搜索字段
    column_searchable_list = [Strategy.name]

    # 可排序字段
    column_sortable_list = [Strategy.created_at]

    # 允许创建和编辑
    can_create = True
    can_edit = True
    can_delete = True
    can_view_details = True


class ReportAdmin(ModelView, model=ResearchReport):
    """研报管理视图。

    支持列表展示、创建、编辑研报。
    按标题搜索、按生成时间排序。
    """

    name = "研报"
    name_plural = "研报列表"

    # 展示列
    column_list = [
        ResearchReport.id,
        ResearchReport.title,
        ResearchReport.generated_at,
        ResearchReport.created_at,
    ]

    # 可搜索字段
    column_searchable_list = [ResearchReport.title]

    # 可排序字段
    column_sortable_list = [ResearchReport.generated_at]

    # 允许创建和编辑
    can_create = True
    can_edit = True
    can_delete = True
    can_view_details = True
