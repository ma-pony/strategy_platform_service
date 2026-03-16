"""管理员信号 API 路由层（任务 6.1）。

提供管理员专属信号操作端点：
  - POST /admin/signals/refresh：手动触发信号全量刷新

所有端点通过 Depends(require_admin) 强制管理员鉴权。
非管理员请求返回 1002/403。
"""

from typing import Any

from fastapi import APIRouter, Depends

from src.core.deps import require_admin
from src.core.response import ApiResponse, ok

router = APIRouter(prefix="/admin/signals", tags=["admin-signals"])


@router.post("/refresh", response_model=ApiResponse[Any])
async def trigger_signal_refresh(
    current_user: Any = Depends(require_admin),
) -> ApiResponse[Any]:
    """手动触发信号全量刷新任务。

    调用 generate_all_signals_task.delay() 将任务异步入队。

    响应结构：
      {
        "code": 0,
        "data": {
          "task_id": "...",
          "message": "信号刷新任务已入队"
        }
      }

    非管理员请求返回 code:1002 HTTP 403。
    """
    from src.workers.tasks.signal_coord_task import generate_all_signals_task

    result = generate_all_signals_task.delay()

    return ok(
        data={
            "task_id": result.id,
            "message": "信号刷新任务已入队",
        }
    )
