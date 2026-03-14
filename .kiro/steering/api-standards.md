# API Standards

量化平台所有 HTTP 接口遵循统一的 RESTful 规范，所有响应使用同一 JSON 信封格式。

## Unified Response Envelope

**所有接口（包括错误）必须返回此结构**，HTTP 状态码同时设置：

```json
{
  "code": 0,
  "message": "success",
  "data": { ... }
}
```

- `code`: 业务状态码，`0` 表示成功，非 `0` 表示各类错误（见错误码约定）
- `message`: 人类可读的状态描述
- `data`: 成功时为业务数据，失败时可为 `null` 或包含错误详情

FastAPI 中通过统一的响应工具函数生成：

```python
# src/core/response.py
from typing import Any
from pydantic import BaseModel

class ApiResponse(BaseModel):
    code: int = 0
    message: str = "success"
    data: Any = None

def ok(data: Any = None, message: str = "success") -> ApiResponse:
    return ApiResponse(code=0, message=message, data=data)

def fail(code: int, message: str, data: Any = None) -> ApiResponse:
    return ApiResponse(code=code, message=message, data=data)
```

## Error Code Convention

| 范围 | 含义 |
|------|------|
| 0 | 成功 |
| 1000–1999 | 认证/授权错误（1001=未登录，1002=权限不足，1003=会员等级不够） |
| 2000–2999 | 请求参数错误（2001=字段校验失败） |
| 3000–3999 | 业务逻辑错误（3001=策略不存在，3002=回测任务冲突） |
| 5000–5999 | 服务端内部错误（5001=freqtrade 调用失败） |

HTTP 状态码与业务 code 并行使用（4xx/5xx 对应客户端/服务端问题）。

## Endpoint Pattern

```
/api/v1/{resource}[/{id}][/{sub-resource}]
```

示例：
- `GET  /api/v1/strategies` — 列出当前用户策略
- `POST /api/v1/strategies` — 创建策略
- `GET  /api/v1/strategies/{id}/backtests` — 查询某策略的回测列表
- `POST /api/v1/backtests/{id}/run` — 触发回测（动词 action 作为子资源）

HTTP 动词语义：GET（幂等读取）、POST（创建/触发）、PUT（全量更新）、PATCH（部分更新）、DELETE（删除，幂等）。

## Versioning

- URL 路径版本（`/api/v1/`）
- Breaking change → 新版本号 `/api/v2/`
- 旧版本在文档中标记 deprecated，提供至少一个迁移周期

## Pagination

列表接口统一返回分页结构：

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "items": [...],
    "total": 100,
    "page": 1,
    "page_size": 20
  }
}
```

查询参数：`?page=1&page_size=20`，默认 `page_size=20`，最大 `100`。

## Request Validation

- 所有请求体通过 Pydantic Schema 校验，校验失败自动返回 `code: 2001`
- FastAPI 的 422 Unprocessable Entity 需被全局异常处理器拦截，转换为统一信封格式

```python
# src/core/exception_handlers.py
from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={"code": 2001, "message": "请求参数校验失败", "data": exc.errors()},
    )
```

---
_Focus on envelope contract and patterns, not endpoint catalogs._
