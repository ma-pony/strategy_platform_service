"""统一响应信封工具。

提供 ApiResponse 泛型模型和 ok / fail / paginated 构造函数，
所有 API 路由必须通过这些工具构造响应，确保信封格式一致。

信封格式：
    {"code": 0, "message": "success", "data": {...}}
"""

from typing import Any, Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    """统一 JSON 响应信封。

    code=0 表示成功，非 0 表示各类错误（见错误码约定）。
    """

    code: int = 0
    message: str = "success"
    data: T | None = None


class PaginatedData(BaseModel, Generic[T]):
    """分页数据结构，嵌套在 ApiResponse.data 中。

    page_size 默认 20，最大 100（由路由层校验）。
    """

    items: list[T]
    total: int
    page: int
    page_size: int


def ok(data: Any = None, message: str = "success") -> ApiResponse[Any]:
    """构造成功响应（code=0）。"""
    return ApiResponse(code=0, message=message, data=data)


def fail(code: int, message: str, data: Any = None) -> ApiResponse[Any]:
    """构造错误响应（code 为非 0 业务错误码）。"""
    return ApiResponse(code=code, message=message, data=data)


def paginated(
    items: list[Any],
    total: int,
    page: int,
    page_size: int,
) -> ApiResponse[PaginatedData[Any]]:
    """构造分页列表成功响应。"""
    page_data: PaginatedData[Any] = PaginatedData(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
    )
    return ok(data=page_data)
