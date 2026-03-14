"""平台核心枚举类型定义。

定义会员等级、任务状态和信号方向三组枚举，
供业务逻辑层和数据模型层共用。
"""

from enum import Enum


class MembershipTier(str, Enum):
    """会员等级枚举。

    层次顺序（低 → 高）：FREE < VIP1 < VIP2。
    """

    FREE = "free"
    VIP1 = "vip1"
    VIP2 = "vip2"


class TaskStatus(str, Enum):
    """回测任务状态枚举。

    状态只能单向流转：PENDING → RUNNING → DONE | FAILED。
    """

    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class SignalDirection(str, Enum):
    """交易信号方向枚举。"""

    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"
