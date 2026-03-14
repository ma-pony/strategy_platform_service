"""平台应用异常体系。

所有业务异常继承 AppError 基类，携带 code 和 message。
全局异常处理器统一将其转换为 JSON 信封格式。

错误码约定：
  1000–1999  认证/授权错误
  2000–2999  请求参数错误
  3000–3999  业务逻辑错误
  5000–5999  服务端内部错误
"""


class AppError(Exception):
    """应用业务异常基类。

    所有自定义异常继承此类，全局异常处理器统一拦截。
    """

    code: int = 5000
    default_message: str = "服务内部错误"

    def __init__(self, message: str | None = None) -> None:
        self.message = message or self.default_message
        super().__init__(self.message)


# ──────────────────────────────────────────────
# 1000–1999  认证/授权错误
# ──────────────────────────────────────────────


class AuthenticationError(AppError):
    """未登录、token 过期或签名无效（code=1001）。"""

    code = 1001
    default_message = "未登录或 token 无效"


class PermissionError(AppError):
    """权限不足（code=1002）。"""

    code = 1002
    default_message = "权限不足"


class MembershipError(AppError):
    """会员等级不足（code=1003）。"""

    code = 1003
    default_message = "会员等级不足"


# ──────────────────────────────────────────────
# 2000–2999  请求参数错误
# ──────────────────────────────────────────────


class ValidationError(AppError):
    """请求参数校验失败（code=2001），含用户名重复等业务校验。"""

    code = 2001
    default_message = "请求参数校验失败"


# ──────────────────────────────────────────────
# 3000–3999  业务逻辑错误
# ──────────────────────────────────────────────


class NotFoundError(AppError):
    """资源不存在（code=3001）。"""

    code = 3001
    default_message = "资源不存在"


class ConflictError(AppError):
    """资源冲突（code=3002），如回测任务重复。"""

    code = 3002
    default_message = "资源冲突"


class UnsupportedStrategyError(AppError):
    """策略不受支持（code=3003）。"""

    code = 3003
    default_message = "策略不受支持，请联系管理员"


# ──────────────────────────────────────────────
# 5000–5999  服务端内部错误
# ──────────────────────────────────────────────


class FreqtradeError(AppError):
    """freqtrade 调用失败（code=5001）。

    对外仅返回友好描述，禁止暴露原始 traceback 或内部路径。
    """

    code = 5001
    default_message = "量化引擎调用失败，请稍后重试"
