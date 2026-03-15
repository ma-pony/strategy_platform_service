"""策略、回测、信号和研报的 Pydantic 响应 Schema。

包含字段级权限控制逻辑：
  - StrategyRead、BacktestResultRead、SignalRead 通过 @model_serializer
    按会员等级动态过滤字段
  - 字段的最低可见等级通过 Field(json_schema_extra={"min_tier": "..."}) 声明
  - 未提供 context 时以匿名等级（None）处理，仅返回匿名可见字段

等级层次顺序（低 → 高）：None（匿名） < FREE < VIP1 < VIP2
"""

from datetime import datetime
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field, SerializationInfo, model_serializer

from src.core.enums import MembershipTier, SignalDirection

# 字段等级层次（低 → 高），None 代表匿名
TIER_ORDER: list[MembershipTier | None] = [
    None,
    MembershipTier.FREE,
    MembershipTier.VIP1,
    MembershipTier.VIP2,
]

T = TypeVar("T")


def _tier_index(tier: MembershipTier | None) -> int:
    """返回会员等级在 TIER_ORDER 中的索引，未知等级视为匿名（索引 0）。"""
    try:
        return TIER_ORDER.index(tier)
    except ValueError:
        return 0


# ─────────────────────────────────────────────────────────────────
# 通用泛型分页 Schema
# ─────────────────────────────────────────────────────────────────


class PaginatedResponse(BaseModel, Generic[T]):
    """泛型分页响应 Schema。

    page_size 默认 20，最大 100（由路由层校验）。
    """

    items: list[T]
    total: int
    page: int
    page_size: int = 20


# ─────────────────────────────────────────────────────────────────
# 用户 Schema
# ─────────────────────────────────────────────────────────────────


class UserRead(BaseModel):
    """用户信息响应 Schema。

    用于注册成功响应，不含密码字段。
    """

    id: int
    username: str
    membership: MembershipTier
    created_at: datetime | None = None

    model_config = {"from_attributes": True}


# ─────────────────────────────────────────────────────────────────
# 策略 Schema（含字段级权限控制）
# ─────────────────────────────────────────────────────────────────


class StrategyRead(BaseModel):
    """策略详情响应 Schema，支持按会员等级过滤字段。

    字段等级：
      - 匿名可见：id, name, description, pairs, strategy_type
      - Free 可见（min_tier="free"）：trade_count, max_drawdown
      - VIP 专属（min_tier="vip1"）：sharpe_ratio, win_rate

    使用 model_dump(context={"membership": tier}) 触发字段过滤。
    未提供 context 时以匿名等级处理。
    """

    # 匿名可见字段（无 min_tier 约束）
    id: int
    name: str
    description: str
    pairs: list[str]
    strategy_type: str

    # Free 可见字段
    trade_count: int | None = Field(
        default=None,
        json_schema_extra={"min_tier": "free"},
    )
    max_drawdown: float | None = Field(
        default=None,
        json_schema_extra={"min_tier": "free"},
    )

    # VIP 专属字段
    sharpe_ratio: float | None = Field(
        default=None,
        json_schema_extra={"min_tier": "vip1"},
    )
    win_rate: float | None = Field(
        default=None,
        json_schema_extra={"min_tier": "vip1"},
    )

    model_config = {"from_attributes": True}

    @model_serializer(mode="wrap")
    def filter_by_tier(self, handler: Any, info: SerializationInfo) -> dict[str, Any]:
        """按会员等级过滤响应字段。

        从 info.context 中获取 membership，将低于该等级的字段置为 None
        或从输出 dict 中移除。
        """
        result: dict[str, Any] = handler(self)

        # 确定当前用户等级
        context = info.context if info else None
        membership: MembershipTier | None = context.get("membership") if isinstance(context, dict) else None
        user_tier_idx = _tier_index(membership)

        # 遍历模型字段，过滤高于用户等级的字段（从类访问以避免 Pydantic v2.11 警告）
        for field_name, field_info in self.__class__.model_fields.items():
            extra = field_info.json_schema_extra
            if not isinstance(extra, dict):
                continue
            min_tier_str: str | None = extra.get("min_tier")
            if min_tier_str is None:
                continue

            # 将 min_tier 字符串映射为枚举
            try:
                min_tier = MembershipTier(min_tier_str)
            except ValueError:
                continue

            required_idx = _tier_index(min_tier)
            if user_tier_idx < required_idx:
                result[field_name] = None

        return result


# ─────────────────────────────────────────────────────────────────
# 回测结果 Schema（含字段级权限控制）
# ─────────────────────────────────────────────────────────────────


class BacktestResultRead(BaseModel):
    """回测结果响应 Schema，支持按会员等级过滤字段。

    字段等级：
      - 匿名可见：id, strategy_id, task_id, period_start, period_end, created_at
      - Free 可见（min_tier="free"）：total_return, trade_count, max_drawdown
      - VIP 专属（min_tier="vip1"）：sharpe_ratio, win_rate, annual_return
    """

    # 匿名可见字段
    id: int
    strategy_id: int
    task_id: int
    period_start: datetime
    period_end: datetime
    created_at: datetime

    # Free 可见字段
    total_return: float | None = Field(
        default=None,
        json_schema_extra={"min_tier": "free"},
    )
    trade_count: int | None = Field(
        default=None,
        json_schema_extra={"min_tier": "free"},
    )
    max_drawdown: float | None = Field(
        default=None,
        json_schema_extra={"min_tier": "free"},
    )

    # VIP 专属字段
    sharpe_ratio: float | None = Field(
        default=None,
        json_schema_extra={"min_tier": "vip1"},
    )
    win_rate: float | None = Field(
        default=None,
        json_schema_extra={"min_tier": "vip1"},
    )
    annual_return: float | None = Field(
        default=None,
        json_schema_extra={"min_tier": "vip1"},
    )

    model_config = {"from_attributes": True}

    @model_serializer(mode="wrap")
    def filter_by_tier(self, handler: Any, info: SerializationInfo) -> dict[str, Any]:
        """按会员等级过滤响应字段。"""
        result: dict[str, Any] = handler(self)

        context = info.context if info else None
        membership: MembershipTier | None = context.get("membership") if isinstance(context, dict) else None
        user_tier_idx = _tier_index(membership)

        for field_name, field_info in self.__class__.model_fields.items():
            extra = field_info.json_schema_extra
            if not isinstance(extra, dict):
                continue
            min_tier_str: str | None = extra.get("min_tier")
            if min_tier_str is None:
                continue
            try:
                min_tier = MembershipTier(min_tier_str)
            except ValueError:
                continue
            if user_tier_idx < _tier_index(min_tier):
                result[field_name] = None

        return result


# ─────────────────────────────────────────────────────────────────
# 交易信号 Schema（含字段级权限控制）
# ─────────────────────────────────────────────────────────────────


class SignalRead(BaseModel):
    """交易信号响应 Schema，VIP 专属 confidence_score 字段。

    字段等级：
      - 所有用户可见：id, strategy_id, pair, direction, signal_at, created_at
      - VIP 专属（min_tier="vip1"）：confidence_score
    """

    # 所有用户可见
    id: int
    strategy_id: int
    pair: str
    direction: SignalDirection
    signal_at: datetime
    created_at: datetime

    # VIP 专属
    confidence_score: float | None = Field(
        default=None,
        json_schema_extra={"min_tier": "vip1"},
    )

    model_config = {"from_attributes": True}

    @model_serializer(mode="wrap")
    def filter_by_tier(self, handler: Any, info: SerializationInfo) -> dict[str, Any]:
        """按会员等级过滤 confidence_score 字段。"""
        result: dict[str, Any] = handler(self)

        context = info.context if info else None
        membership: MembershipTier | None = context.get("membership") if isinstance(context, dict) else None
        user_tier_idx = _tier_index(membership)

        for field_name, field_info in self.__class__.model_fields.items():
            extra = field_info.json_schema_extra
            if not isinstance(extra, dict):
                continue
            min_tier_str: str | None = extra.get("min_tier")
            if min_tier_str is None:
                continue
            try:
                min_tier = MembershipTier(min_tier_str)
            except ValueError:
                continue
            if user_tier_idx < _tier_index(min_tier):
                result[field_name] = None

        return result


# ─────────────────────────────────────────────────────────────────
# 研报 Schema（任务 4.2）
# ─────────────────────────────────────────────────────────────────


class ReportRead(BaseModel):
    """研报列表摘要响应 Schema（匿名可访问）。

    用于列表接口，不含完整 content 字段。
    """

    id: int
    title: str
    summary: str
    generated_at: datetime
    related_coins: list[str] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class ReportDetailRead(BaseModel):
    """研报详情响应 Schema（含完整 content 字段）。"""

    id: int
    title: str
    summary: str
    content: str
    generated_at: datetime
    related_coins: list[str] = Field(default_factory=list)

    model_config = {"from_attributes": True}
