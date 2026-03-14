"""全局异常处理器。

将 Pydantic RequestValidationError 和 AppError 统一转换为 JSON 信封格式响应。

错误码约定：
  - RequestValidationError(422) → code:2001 信封格式
  - AppError 子类 → 对应 HTTP 状态码和 code 字段
  - 未捕获异常 → code:5000 HTTP 500
"""

import structlog
from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from src.core.exceptions import (
    AppError,
    AuthenticationError,
    ConflictError,
    FreqtradeError,
    MembershipError,
    NotFoundError,
    PermissionError,
    UnsupportedStrategyError,
    ValidationError,
)

logger = structlog.get_logger(__name__)

# AppError 子类 → HTTP 状态码映射
_ERROR_HTTP_STATUS: dict[type[AppError], int] = {
    AuthenticationError: 401,
    PermissionError: 403,
    MembershipError: 403,
    ValidationError: 400,
    NotFoundError: 404,
    ConflictError: 409,
    UnsupportedStrategyError: 422,
    FreqtradeError: 500,
}


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """将 Pydantic 422 校验错误转换为统一信封格式。

    返回 code:2001，HTTP 状态码保持 422。
    """
    return JSONResponse(
        status_code=422,
        content={
            "code": 2001,
            "message": "请求参数校验失败",
            "data": exc.errors(),
        },
    )


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    """将业务异常（AppError 子类）转换为统一信封格式。"""
    http_status = _ERROR_HTTP_STATUS.get(type(exc), 500)
    logger.warning(
        "app error",
        code=exc.code,
        message=exc.message,
        path=str(request.url),
    )
    return JSONResponse(
        status_code=http_status,
        content={
            "code": exc.code,
            "message": exc.message,
            "data": None,
        },
    )


async def generic_exception_handler(
    request: Request, exc: Exception
) -> JSONResponse:
    """兜底处理未捕获异常，返回 code:5000 HTTP 500。

    不向客户端暴露原始 traceback 或内部路径信息。
    """
    logger.error(
        "unhandled exception",
        path=str(request.url),
        exc_info=exc,
    )
    return JSONResponse(
        status_code=500,
        content={
            "code": 5000,
            "message": "服务内部错误，请稍后重试",
            "data": None,
        },
    )
