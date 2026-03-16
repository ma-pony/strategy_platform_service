"""sqladmin ModelView 视图定义（任务 11.2, Task 6）。

提供以下管理视图：
  - UserAdmin：用户管理（列表展示、搜索、排序，禁止删除）
  - StrategyAdmin：策略管理（列表、创建、编辑）
  - ReportAdmin：研报管理（列表、创建、编辑、搜索、排序）
  - StrategyPairMetricsAdmin：策略对绩效指标管理（只读监控，禁止删除，允许手动修正）

关键约束：
  - UserAdmin.can_delete = False：禁止后台删除用户
  - StrategyPairMetricsAdmin.can_delete = False：禁止删除历史绩效数据
  - 所有 ModelView 使用 SQLAlchemy 模型与 sqladmin 集成
"""

from sqladmin import ModelView

from src.models.backtest import BacktestResult, BacktestTask
from src.models.report import ResearchReport
from src.models.signal import TradingSignal
from src.models.strategy import Strategy
from src.models.strategy_pair_metrics import StrategyPairMetrics
from src.models.user import User


class UserAdmin(ModelView, model=User):
    """用户管理视图。

    支持列表展示、按 email 搜索、按 created_at 排序。
    允许编辑 membership 和 is_active 字段。
    禁止后台删除用户（can_delete=False）。
    """

    name = "用户"
    name_plural = "用户列表"

    # 展示列
    column_list = [
        User.id,
        User.email,
        User.membership,
        User.is_active,
        User.is_admin,
        User.created_at,
    ]

    # 可搜索字段
    column_searchable_list = [User.email]

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


class TradingSignalAdmin(ModelView, model=TradingSignal):
    """交易信号管理视图（只读）。

    设置为只读视图（需求 5.3）：
      - can_create=False：禁止新建
      - can_edit=False：禁止编辑
      - can_delete=False：禁止删除
    支持按策略 ID、信号类型、时间范围过滤。
    """

    name = "交易信号"
    name_plural = "交易信号列表"

    column_list = [
        TradingSignal.id,
        TradingSignal.strategy_id,
        TradingSignal.pair,
        TradingSignal.direction,
        TradingSignal.confidence_score,
        TradingSignal.signal_at,
        TradingSignal.entry_price,
        TradingSignal.stop_loss,
        TradingSignal.take_profit,
        TradingSignal.timeframe,
        TradingSignal.signal_strength,
        TradingSignal.signal_source,
    ]

    column_searchable_list = [TradingSignal.pair, TradingSignal.direction]
    column_sortable_list = [TradingSignal.signal_at, TradingSignal.confidence_score, TradingSignal.strategy_id]
    column_filters = [TradingSignal.strategy_id, TradingSignal.direction, TradingSignal.signal_at]

    # 只读模式（需求 5.3）
    can_create = False
    can_edit = False
    can_delete = False
    can_view_details = True


class BacktestTaskAdmin(ModelView, model=BacktestTask):
    """回测任务管理视图。"""

    name = "回测任务"
    name_plural = "回测任务列表"

    column_list = [
        BacktestTask.id,
        BacktestTask.strategy_id,
        BacktestTask.status,
        BacktestTask.timerange,
        BacktestTask.error_message,
        BacktestTask.created_at,
    ]

    column_searchable_list = [BacktestTask.status]
    column_sortable_list = [BacktestTask.created_at]

    can_create = True
    can_edit = True
    can_delete = True
    can_view_details = True


class BacktestResultAdmin(ModelView, model=BacktestResult):
    """回测结果管理视图。"""

    name = "回测结果"
    name_plural = "回测结果列表"

    column_list = [
        BacktestResult.id,
        BacktestResult.strategy_id,
        BacktestResult.task_id,
        BacktestResult.total_return,
        BacktestResult.annual_return,
        BacktestResult.sharpe_ratio,
        BacktestResult.max_drawdown,
        BacktestResult.trade_count,
        BacktestResult.win_rate,
    ]

    column_sortable_list = [BacktestResult.sharpe_ratio, BacktestResult.total_return]

    can_create = True
    can_edit = True
    can_delete = True
    can_view_details = True


class StrategyPairMetricsAdmin(ModelView, model=StrategyPairMetrics):
    """策略对绩效指标管理视图（Task 6）。

    提供策略对绩效指标的只读监控视图，支持手动修正异常数据。
    禁止通过后台删除历史绩效数据（can_delete=False，需求 5.4）。
    由 Worker 任务创建记录，后台不允许新建（can_create=False）。
    允许管理员手动编辑单条记录（can_edit=True，需求 5.5）。

    展示字段：strategy_id, pair, timeframe, total_return, profit_factor,
              max_drawdown, sharpe_ratio, trade_count, data_source, last_updated_at
    搜索：pair, timeframe, data_source（需求 5.2）
    筛选：strategy_id, pair, timeframe, data_source（需求 5.2）
    排序：last_updated_at, total_return（需求 5.3）
    """

    name = "策略对绩效"
    name_plural = "策略对绩效列表"

    # 展示列（需求 5.1）
    column_list = [
        StrategyPairMetrics.strategy_id,
        StrategyPairMetrics.pair,
        StrategyPairMetrics.timeframe,
        StrategyPairMetrics.total_return,
        StrategyPairMetrics.profit_factor,
        StrategyPairMetrics.max_drawdown,
        StrategyPairMetrics.sharpe_ratio,
        StrategyPairMetrics.trade_count,
        StrategyPairMetrics.data_source,
        StrategyPairMetrics.last_updated_at,
    ]

    # 可搜索字段（需求 5.2）
    column_searchable_list = [
        StrategyPairMetrics.pair,
        StrategyPairMetrics.timeframe,
        StrategyPairMetrics.data_source,
    ]

    # 可排序字段（需求 5.3）
    column_sortable_list = [
        StrategyPairMetrics.last_updated_at,
        StrategyPairMetrics.total_return,
    ]

    # 权限配置（需求 5.4, 5.5）
    can_delete = False  # 禁止删除，保护历史数据完整性（需求 5.4）
    can_create = False  # 由 Worker 任务创建，不在后台创建
    can_edit = True  # 允许管理员手动修正异常数据（需求 5.5）
    can_view_details = True

    # 可编辑字段（含全部指标字段及元数据，需求 5.5）
    form_columns = [
        StrategyPairMetrics.total_return,
        StrategyPairMetrics.profit_factor,
        StrategyPairMetrics.max_drawdown,
        StrategyPairMetrics.sharpe_ratio,
        StrategyPairMetrics.trade_count,
        StrategyPairMetrics.data_source,
        StrategyPairMetrics.last_updated_at,
    ]
