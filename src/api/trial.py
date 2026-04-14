"""体验期 API。

- POST /trial/init：初始化体验期（幂等）
- GET  /trial/status：查询体验期状态
"""

from typing import Any

from fastapi import APIRouter, Request

from src.core.response import ApiResponse, ok
from src.workers.redis_client import get_redis_client

router = APIRouter(prefix="/trial", tags=["trial"])


def _get_visitor_id(request: Request) -> str | None:
    return request.headers.get("X-Visitor-ID", "").strip() or None


def _get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For", "")
    return forwarded.split(",")[0].strip() if forwarded else (request.client.host if request.client else "unknown")


@router.post("/init", response_model=ApiResponse[Any])
async def init_trial(request: Request) -> ApiResponse[Any]:
    """初始化体验期（幂等）。需携带 X-Visitor-ID header。"""
    from src.services.trial_service import init_trial as _init

    visitor_id = _get_visitor_id(request)
    if not visitor_id:
        from src.core.exceptions import ValidationError

        raise ValidationError("缺少 X-Visitor-ID header")

    redis = get_redis_client()
    data = _init(redis, visitor_id, _get_client_ip(request))
    return ok(
        data={
            "visitor_id": data["visitor_id"],
            "created_at": data["created_at"],
            "expires_at": data["expires_at"],
        }
    )


@router.get("/status", response_model=ApiResponse[Any])
async def trial_status(request: Request) -> ApiResponse[Any]:
    """查询体验期状态。需携带 X-Visitor-ID header。"""
    from src.services.trial_service import get_trial

    visitor_id = _get_visitor_id(request)
    if not visitor_id:
        from src.core.exceptions import ValidationError

        raise ValidationError("缺少 X-Visitor-ID header")

    redis = get_redis_client()
    trial = get_trial(redis, visitor_id)
    if trial is None:
        return ok(data={"active": False, "trial": None})

    return ok(
        data={
            "active": not trial["expired"],
            "trial": {
                "visitor_id": trial["visitor_id"],
                "created_at": trial["created_at"],
                "expires_at": trial["expires_at"],
                "remaining_seconds": trial["remaining_seconds"],
            },
        }
    )
