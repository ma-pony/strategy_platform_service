"""策略对绩效指标 API 集成测试（Task 5.3, Task 7.7）。

验证：
  - GET /api/v1/strategies/{strategy_id}/pair-metrics：分页列表
  - GET /api/v1/strategies/{strategy_id}/pair-metrics/{pair}/{timeframe}：单条详情
  - 匿名 / Free / VIP1 字段可见性
  - strategy_id 不存在返回 HTTP 404，code=3001
  - pair/timeframe 过滤有效
  - 分页参数正确返回子集

需求可追溯：4.1, 4.2, 4.3, 4.4, 4.5, 4.6
"""

from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

TEST_SECRET = "test-secret-key-for-pair-metrics-api-256bits"


@pytest.fixture()
def env_setup(monkeypatch: pytest.MonkeyPatch):
    """注入测试环境变量并清除 settings 缓存。"""
    monkeypatch.setenv("SECRET_KEY", TEST_SECRET)
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")
    monkeypatch.setenv("DATABASE_SYNC_URL", "postgresql+psycopg2://u:p@localhost/db")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")

    from src.core import app_settings
    app_settings.get_settings.cache_clear()
    yield
    app_settings.get_settings.cache_clear()


@pytest.fixture()
def app(env_setup):
    """创建测试用 FastAPI 应用实例。"""
    from src.api.main_router import create_app
    return create_app()


@pytest.fixture()
async def client(app) -> AsyncGenerator[AsyncClient, None]:
    """提供绑定测试应用的异步 HTTP 客户端。"""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac


def _make_mock_metric(
    pair: str = "BTC/USDT",
    timeframe: str = "1h",
    total_return: float = 0.15,
    trade_count: int = 42,
    profit_factor: float = 1.5,
    data_source: str = "backtest",
    max_drawdown: float = 0.08,
    sharpe_ratio: float = 1.2,
    last_updated_at: datetime | None = None,
) -> MagicMock:
    """创建 StrategyPairMetrics mock 对象。"""
    from src.core.enums import DataSource

    metric = MagicMock()
    metric.pair = pair
    metric.timeframe = timeframe
    metric.total_return = total_return
    metric.trade_count = trade_count
    metric.profit_factor = profit_factor
    metric.data_source = DataSource(data_source)
    metric.max_drawdown = max_drawdown
    metric.sharpe_ratio = sharpe_ratio
    metric.last_updated_at = last_updated_at or datetime(2024, 1, 1, tzinfo=timezone.utc)
    return metric


class TestPairMetricsListEndpoint:
    """GET /api/v1/strategies/{strategy_id}/pair-metrics 分页列表端点测试。"""

    @pytest.mark.anyio
    async def test_returns_200_with_valid_strategy(
        self, client: AsyncClient, env_setup: None
    ) -> None:
        """有效 strategy_id 应返回 HTTP 200。"""
        mock_metrics = [_make_mock_metric()]

        with patch(
            "src.services.pair_metrics_service.PairMetricsService.list_pair_metrics",
            new_callable=AsyncMock,
            return_value=(mock_metrics, 1),
        ):
            response = await client.get("/api/v1/strategies/1/pair-metrics")

        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0

    @pytest.mark.anyio
    async def test_anonymous_response_hides_profit_factor(
        self, client: AsyncClient, env_setup: None
    ) -> None:
        """匿名请求时，profit_factor 应为 None（需求 4.2）。"""
        mock_metrics = [_make_mock_metric(profit_factor=1.75)]

        with patch(
            "src.services.pair_metrics_service.PairMetricsService.list_pair_metrics",
            new_callable=AsyncMock,
            return_value=(mock_metrics, 1),
        ):
            response = await client.get("/api/v1/strategies/1/pair-metrics")

        assert response.status_code == 200
        items = response.json()["data"]["items"]
        assert len(items) == 1
        assert items[0]["profit_factor"] is None

    @pytest.mark.anyio
    async def test_anonymous_response_shows_basic_fields(
        self, client: AsyncClient, env_setup: None
    ) -> None:
        """匿名请求应返回 pair、timeframe、total_return、trade_count（需求 4.2）。"""
        mock_metrics = [_make_mock_metric()]

        with patch(
            "src.services.pair_metrics_service.PairMetricsService.list_pair_metrics",
            new_callable=AsyncMock,
            return_value=(mock_metrics, 1),
        ):
            response = await client.get("/api/v1/strategies/1/pair-metrics")

        item = response.json()["data"]["items"][0]
        assert item["pair"] == "BTC/USDT"
        assert item["timeframe"] == "1h"
        assert item["total_return"] is not None
        assert item["trade_count"] is not None

    @pytest.mark.anyio
    async def test_strategy_not_found_returns_404(
        self, client: AsyncClient, env_setup: None
    ) -> None:
        """strategy_id 不存在时应返回 HTTP 404，code=3001（需求 4.4）。"""
        from src.core.exceptions import NotFoundError

        with patch(
            "src.services.pair_metrics_service.PairMetricsService.list_pair_metrics",
            new_callable=AsyncMock,
            side_effect=NotFoundError("策略 999 不存在"),
        ):
            response = await client.get("/api/v1/strategies/999/pair-metrics")

        assert response.status_code == 404
        assert response.json()["code"] == 3001

    @pytest.mark.anyio
    async def test_pagination_params_passed_correctly(
        self, client: AsyncClient, env_setup: None
    ) -> None:
        """page 和 page_size 参数应正确传递给 service（需求 4.5）。"""
        mock_metrics = [_make_mock_metric()]

        with patch(
            "src.services.pair_metrics_service.PairMetricsService.list_pair_metrics",
            new_callable=AsyncMock,
            return_value=(mock_metrics, 10),
        ) as mock_service:
            response = await client.get(
                "/api/v1/strategies/1/pair-metrics?page=2&page_size=5"
            )

        assert response.status_code == 200
        # 验证 service 被以正确参数调用
        call_kwargs = mock_service.call_args.kwargs
        assert call_kwargs.get("page") == 2
        assert call_kwargs.get("page_size") == 5

    @pytest.mark.anyio
    async def test_response_contains_pagination_metadata(
        self, client: AsyncClient, env_setup: None
    ) -> None:
        """响应应包含分页元数据（total、page、page_size）。"""
        mock_metrics = [_make_mock_metric()]

        with patch(
            "src.services.pair_metrics_service.PairMetricsService.list_pair_metrics",
            new_callable=AsyncMock,
            return_value=(mock_metrics, 5),
        ):
            response = await client.get("/api/v1/strategies/1/pair-metrics?page=1&page_size=3")

        data = response.json()["data"]
        assert "total" in data
        assert "page" in data
        assert "page_size" in data
        assert data["total"] == 5

    @pytest.mark.anyio
    async def test_pair_filter_passed_to_service(
        self, client: AsyncClient, env_setup: None
    ) -> None:
        """?pair 过滤参数应传递给 service（需求 4.5）。"""
        mock_metrics = [_make_mock_metric()]

        with patch(
            "src.services.pair_metrics_service.PairMetricsService.list_pair_metrics",
            new_callable=AsyncMock,
            return_value=(mock_metrics, 1),
        ) as mock_service:
            response = await client.get(
                "/api/v1/strategies/1/pair-metrics?pair=BTC/USDT"
            )

        assert response.status_code == 200
        call_kwargs = mock_service.call_args.kwargs
        assert call_kwargs.get("pair_filter") == "BTC/USDT"

    @pytest.mark.anyio
    async def test_timeframe_filter_passed_to_service(
        self, client: AsyncClient, env_setup: None
    ) -> None:
        """?timeframe 过滤参数应传递给 service（需求 4.5）。"""
        mock_metrics = [_make_mock_metric()]

        with patch(
            "src.services.pair_metrics_service.PairMetricsService.list_pair_metrics",
            new_callable=AsyncMock,
            return_value=(mock_metrics, 1),
        ) as mock_service:
            response = await client.get(
                "/api/v1/strategies/1/pair-metrics?timeframe=4h"
            )

        assert response.status_code == 200
        call_kwargs = mock_service.call_args.kwargs
        assert call_kwargs.get("timeframe_filter") == "4h"


class TestPairMetricDetailEndpoint:
    """GET /api/v1/strategies/{strategy_id}/pair-metrics/{pair}/{timeframe} 单条端点测试。"""

    @pytest.mark.anyio
    async def test_returns_200_for_existing_metric(
        self, client: AsyncClient, env_setup: None
    ) -> None:
        """存在的策略对记录应返回 HTTP 200。"""
        mock_metric = _make_mock_metric()

        with patch(
            "src.services.pair_metrics_service.PairMetricsService.get_pair_metric",
            new_callable=AsyncMock,
            return_value=mock_metric,
        ):
            response = await client.get(
                "/api/v1/strategies/1/pair-metrics/BTC%2FUSDT/1h"
            )

        assert response.status_code == 200
        assert response.json()["code"] == 0

    @pytest.mark.anyio
    async def test_strategy_not_found_returns_404_code_3001(
        self, client: AsyncClient, env_setup: None
    ) -> None:
        """strategy_id 不存在时返回 HTTP 404，code=3001（需求 4.4）。"""
        from src.core.exceptions import NotFoundError

        with patch(
            "src.services.pair_metrics_service.PairMetricsService.get_pair_metric",
            new_callable=AsyncMock,
            side_effect=NotFoundError("策略不存在"),
        ):
            response = await client.get(
                "/api/v1/strategies/999/pair-metrics/BTC%2FUSDT/1h"
            )

        assert response.status_code == 404
        assert response.json()["code"] == 3001

    @pytest.mark.anyio
    async def test_metric_not_found_returns_404(
        self, client: AsyncClient, env_setup: None
    ) -> None:
        """记录不存在时返回 HTTP 404，code=3001（需求 4.6）。"""
        from src.core.exceptions import NotFoundError

        with patch(
            "src.services.pair_metrics_service.PairMetricsService.get_pair_metric",
            new_callable=AsyncMock,
            side_effect=NotFoundError("记录不存在"),
        ):
            response = await client.get(
                "/api/v1/strategies/1/pair-metrics/BTC%2FUSDT/4h"
            )

        assert response.status_code == 404

    @pytest.mark.anyio
    async def test_pair_url_decoded_correctly(
        self, client: AsyncClient, env_setup: None
    ) -> None:
        """URL 编码的 pair 参数（BTC%2FUSDT）应正确解码为 BTC/USDT 传递给 service。"""
        mock_metric = _make_mock_metric()

        with patch(
            "src.services.pair_metrics_service.PairMetricsService.get_pair_metric",
            new_callable=AsyncMock,
            return_value=mock_metric,
        ) as mock_service:
            response = await client.get(
                "/api/v1/strategies/1/pair-metrics/BTC%2FUSDT/1h"
            )

        assert response.status_code == 200
        call_kwargs = mock_service.call_args.kwargs
        assert call_kwargs.get("pair") == "BTC/USDT"
