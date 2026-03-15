"""策略对绩效指标 API 路由层（Task 5.3）。

提供策略对绩效指标只读端点：
  - GET /strategies/{strategy_id}/pair-metrics：分页列表，支持 pair/timeframe 过滤
  - GET /strategies/{strategy_id}/pair-metrics/{pair}/{timeframe}：单条详情

字段按会员等级过滤：
  - 匿名：pair、timeframe、total_return、trade_count
  - Free：额外 profit_factor、data_source
  - VIP1+：全部字段含 max_drawdown、sharpe_ratio、last_updated_at

认证使用 get_optional_user（匿名时 membership=None）。

需求可追溯：4.1, 4.4, 4.5, 4.6
"""

from typing import Any
from urllib.parse import unquote

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.deps import get_db, get_optional_user
from src.core.response import ApiResponse, PaginatedData, ok, paginated
from src.schemas.pair_metrics import PairMetricsRead
from src.services.pair_metrics_service import PairMetricsService

router = APIRouter(prefix="/strategies", tags=["pair-metrics"])

_pair_metrics_service = PairMetricsService()


@router.get(
    "/{strategy_id}/pair-metrics",
    response_model=ApiResponse[PaginatedData[Any]],
    summary="获取策略对绩效指标分页列表",
)
async def list_pair_metrics(
    strategy_id: int = Path(..., description="策略 ID"),
    pair: str | None = Query(default=None, description="交易对过滤（精确匹配，如 BTC/USDT）"),
    timeframe: str | None = Query(default=None, description="时间周期过滤（如 1h）"),
    page: int = Query(default=1, ge=1, description="页码（从 1 开始）"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页数量（最大 100）"),
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(get_optional_user),
) -> ApiResponse[PaginatedData[Any]]:
    """获取指定策略下所有策略对的绩效指标分页列表。

    按 total_return 降序排列（NULLS LAST）。
    支持 ?pair=BTC/USDT、?timeframe=1h、?page=1、?page_size=20 过滤和分页。

    匿名用户仅返回基础字段，Free 用户额外返回 profit_factor/data_source，
    VIP1+ 用户返回全部字段。

    Args:
        strategy_id: 策略 ID（不存在时返回 404, code=3001）
        pair: 可选交易对过滤（精确匹配）
        timeframe: 可选时间周期过滤（精确匹配）
        page: 页码（默认 1）
        page_size: 每页数量（默认 20，最大 100）
        db: 异步数据库 session
        current_user: 可选认证用户（匿名时为 None）

    Returns:
        ApiResponse[PaginatedData[PairMetricsRead]]
    """
    metrics_list, total = await _pair_metrics_service.list_pair_metrics(
        db=db,
        strategy_id=strategy_id,
        pair_filter=pair,
        timeframe_filter=timeframe,
        page=page,
        page_size=page_size,
    )

    membership = current_user.membership if current_user is not None else None

    items: list[Any] = []
    for metric in metrics_list:
        schema = PairMetricsRead.model_validate(metric)
        items.append(schema.model_dump(context={"membership": membership}))

    return paginated(items=items, total=total, page=page, page_size=page_size)


@router.get(
    "/{strategy_id}/pair-metrics/{pair:path}/{timeframe}",
    response_model=ApiResponse[Any],
    summary="获取单个策略对绩效指标详情",
)
async def get_pair_metric(
    strategy_id: int = Path(..., description="策略 ID"),
    pair: str = Path(..., description="交易对（/ 须 URL 编码为 %2F，如 BTC%2FUSDT）"),
    timeframe: str = Path(..., description="时间周期（如 1h）"),
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(get_optional_user),
) -> ApiResponse[Any]:
    """获取指定策略对的绩效指标详情。

    pair 路径参数中 / 须 URL 编码为 %2F（如 BTC%2FUSDT）。
    策略或记录不存在时返回 HTTP 404，code=3001。

    Args:
        strategy_id: 策略 ID
        pair: 交易对（URL 解码后传入 service）
        timeframe: 时间周期
        db: 异步数据库 session
        current_user: 可选认证用户（匿名时为 None）

    Returns:
        ApiResponse[PairMetricsRead]
    """
    # URL 解码 pair 参数（如 BTC%2FUSDT → BTC/USDT）
    decoded_pair = unquote(pair)

    metric = await _pair_metrics_service.get_pair_metric(
        db=db,
        strategy_id=strategy_id,
        pair=decoded_pair,
        timeframe=timeframe,
    )

    membership = current_user.membership if current_user is not None else None
    schema = PairMetricsRead.model_validate(metric)
    filtered_data = schema.model_dump(context={"membership": membership})

    return ok(data=filtered_data)
