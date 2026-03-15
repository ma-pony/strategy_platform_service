"""策略对绩效指标响应 Schema（Task 5.1）。

PairMetricsRead：Pydantic v2 响应 Schema，含 @model_serializer 字段级权限过滤。
复用现有 TIER_ORDER / _tier_index / filter_by_tier 模式（来自 src/schemas/strategy.py）。

字段等级设计：
  匿名可见字段（无 min_tier）：pair、timeframe、total_return、trade_count
  Free 可见字段（min_tier="free"）：profit_factor、data_source
  VIP1 可见字段（min_tier="vip1"）：max_drawdown、sharpe_ratio、last_updated_at

需求可追溯：4.1, 4.2, 4.3
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, SerializationInfo, model_serializer

from src.core.enums import DataSource, MembershipTier
from src.schemas.strategy import TIER_ORDER, _tier_index


class PairMetricsRead(BaseModel):
    """策略对绩效指标响应 Schema，支持按会员等级过滤字段。

    字段等级：
      - 匿名可见：pair、timeframe、total_return、trade_count
      - Free 可见（min_tier="free"）：profit_factor、data_source
      - VIP1 可见（min_tier="vip1"）：max_drawdown、sharpe_ratio、last_updated_at

    使用 model_dump(context={"membership": tier}) 触发字段过滤。
    未提供 context 时以匿名等级处理。
    """

    # 匿名可见字段（无 min_tier 约束）
    pair: str
    timeframe: str
    total_return: float | None = None
    trade_count: int | None = None

    # Free 可见字段（min_tier="free"）
    profit_factor: float | None = Field(
        default=None,
        json_schema_extra={"min_tier": "free"},
    )
    data_source: DataSource | None = Field(
        default=None,
        json_schema_extra={"min_tier": "free"},
    )

    # VIP1 可见字段（min_tier="vip1"）
    max_drawdown: float | None = Field(
        default=None,
        json_schema_extra={"min_tier": "vip1"},
    )
    sharpe_ratio: float | None = Field(
        default=None,
        json_schema_extra={"min_tier": "vip1"},
    )
    last_updated_at: datetime | None = Field(
        default=None,
        json_schema_extra={"min_tier": "vip1"},
    )

    model_config = {"from_attributes": True}

    @model_serializer(mode="wrap")
    def filter_by_tier(
        self, handler: Any, info: SerializationInfo
    ) -> dict[str, Any]:
        """按会员等级过滤响应字段。

        从 info.context 中获取 membership，将低于该等级的字段置为 None。
        """
        result: dict[str, Any] = handler(self)

        # 确定当前用户等级
        context = info.context if info else None
        membership: MembershipTier | None = (
            context.get("membership") if isinstance(context, dict) else None
        )
        user_tier_idx = _tier_index(membership)

        # 遍历模型字段，过滤高于用户等级的字段
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

            required_idx = _tier_index(min_tier)
            if user_tier_idx < required_idx:
                result[field_name] = None

        return result
