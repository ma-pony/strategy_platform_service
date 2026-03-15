"""健康检查 API 路由。

提供：
  - GET /health：服务健康检查端点，供 Docker HEALTHCHECK 和负载均衡使用
"""

from fastapi import APIRouter

from src.core.response import ApiResponse, ok

router = APIRouter(tags=["health"])


@router.get("/health", response_model=ApiResponse[dict])
async def health_check() -> ApiResponse[dict]:
    """服务健康检查。

    返回 HTTP 200 表示服务正常运行。
    供 Docker HEALTHCHECK、Kubernetes liveness probe 和负载均衡使用。
    """
    return ok(data={"status": "healthy"})
