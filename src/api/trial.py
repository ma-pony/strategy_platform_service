"""体验期 API。

- POST /trial/init：初始化体验期（幂等）
- GET  /trial/status：查询体验期状态
"""

import asyncio
import ipaddress
from typing import Any

from fastapi import APIRouter, Request

from src.core.app_settings import get_settings
from src.core.response import ApiResponse, ok
from src.workers.redis_client import get_redis_client

router = APIRouter(prefix="/trial", tags=["trial"])


def _get_visitor_id(request: Request) -> str | None:
    return request.headers.get("X-Visitor-ID", "").strip() or None


def _get_client_ip(request: Request) -> str:
    """返回真实客户端 IP，仅当直连 peer 在可信代理 CIDR 白名单内时才信任 X-Forwarded-For。

    否则回落到 request.client.host，防止未认证客户端通过伪造 header 绕过 IP rate-limit。
    """
    peer_host = request.client.host if request.client else None

    if peer_host and _is_trusted_proxy(peer_host):
        forwarded = request.headers.get("X-Forwarded-For", "")
        if forwarded:
            # XFF 最左侧是最初的客户端（不可信但代表真实 IP 源），不做进一步信任链遍历
            return forwarded.split(",")[0].strip()

    return peer_host or "unknown"


def _is_trusted_proxy(ip: str) -> bool:
    """判断 ip 是否落在可信代理 CIDR 白名单内。"""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    for cidr in get_settings().trusted_proxy_cidrs:
        try:
            if addr in ipaddress.ip_network(cidr, strict=False):
                return True
        except ValueError:
            continue
    return False


@router.post("/init", response_model=ApiResponse[Any])
async def init_trial(request: Request) -> ApiResponse[Any]:
    """初始化体验期（幂等）。需携带 X-Visitor-ID header。"""
    from src.services.trial_service import init_trial as _init

    visitor_id = _get_visitor_id(request)
    if not visitor_id:
        from src.core.exceptions import ValidationError

        raise ValidationError("缺少 X-Visitor-ID header")

    redis = get_redis_client()
    data = await asyncio.to_thread(_init, redis, visitor_id, _get_client_ip(request))
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
    trial = await asyncio.to_thread(get_trial, redis, visitor_id)
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
