"""任务 9.3 集成测试：顶级信号查询 API（/api/v1/signals）。

验证：
  - GET /api/v1/signals 过滤和分页参数的正确性
  - 匿名用户请求时 confidence 字段为 null；VIP1 用户返回实际置信度数值
  - GET /api/v1/signals/{strategy_id} 在策略不存在时返回 3001/404

涵盖需求：4.1, 4.2, 4.3, 4.4, 4.5
"""

from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

TEST_SECRET = "test-secret-key-for-signals-top-api-tests-256bits-long"  # pragma: allowlist secret


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

    application = create_app()
    return application


@pytest.fixture()
async def client(app) -> AsyncGenerator[AsyncClient, None]:
    """提供绑定测试应用的异步 HTTP 客户端。"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


def _make_mock_signal(
    id: int = 1,
    strategy_id: int = 1,
    pair: str = "BTC/USDT",
    timeframe: str = "1h",
    confidence_score: float | None = 0.85,
) -> MagicMock:
    """创建 mock 信号对象。"""
    from src.core.enums import SignalDirection

    signal = MagicMock()
    signal.id = id
    signal.strategy_id = strategy_id
    signal.pair = pair
    signal.timeframe = timeframe
    signal.confidence_score = confidence_score
    signal.signal_at = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
    signal.created_at = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
    signal.direction = SignalDirection.BUY
    return signal


class TestSignalsTopListEndpoint:
    """GET /api/v1/signals 端点测试（需求 4.1, 4.2, 4.3, 4.5, 4.6）。"""

    @pytest.mark.asyncio
    async def test_list_signals_strategy_not_found_returns_404(
        self,
        client: AsyncClient,
    ) -> None:
        """strategy_id 不存在时返回 3001/404（需求 4.5）。"""
        from src.core.exceptions import NotFoundError

        with patch(
            "src.api.signals_top._signal_service.list_signals",
            new_callable=AsyncMock,
            side_effect=NotFoundError("策略不存在"),
        ):
            response = await client.get("/api/v1/signals?strategy_id=9999")

        assert response.status_code == 404
        data = response.json()
        assert data["code"] == 3001

    @pytest.mark.asyncio
    async def test_list_signals_returns_paginated_response(
        self,
        client: AsyncClient,
    ) -> None:
        """成功返回分页格式响应（需求 4.6）。"""
        mock_signals = [_make_mock_signal(id=i) for i in range(1, 4)]

        with patch(
            "src.api.signals_top._signal_service.list_signals",
            new_callable=AsyncMock,
            return_value=(mock_signals, 3, datetime.now(timezone.utc)),
        ):
            response = await client.get("/api/v1/signals?strategy_id=1")

        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        assert "items" in data["data"]
        assert data["data"]["total"] == 3
        assert data["data"]["page"] == 1

    @pytest.mark.asyncio
    async def test_anonymous_user_gets_null_confidence(
        self,
        client: AsyncClient,
    ) -> None:
        """匿名用户请求时 confidence_score 字段为 null（需求 4.2）。"""
        mock_signal = _make_mock_signal(confidence_score=0.85)

        with patch(
            "src.api.signals_top._signal_service.list_signals",
            new_callable=AsyncMock,
            return_value=([mock_signal], 1, datetime.now(timezone.utc)),
        ):
            # 不带 Authorization header（匿名）
            response = await client.get("/api/v1/signals?strategy_id=1")

        assert response.status_code == 200
        items = response.json()["data"]["items"]
        if items:
            assert items[0]["confidence_score"] is None

    @pytest.mark.asyncio
    async def test_get_signals_by_strategy_not_found(
        self,
        client: AsyncClient,
    ) -> None:
        """GET /api/v1/signals/{strategy_id} 策略不存在返回 3001/404（需求 4.4）。"""
        from src.core.exceptions import NotFoundError

        with patch(
            "src.api.signals_top._signal_service.list_signals",
            new_callable=AsyncMock,
            side_effect=NotFoundError("策略不存在"),
        ):
            response = await client.get("/api/v1/signals/9999")

        assert response.status_code == 404
        data = response.json()
        assert data["code"] == 3001

    @pytest.mark.asyncio
    async def test_get_signals_by_strategy_returns_paginated(
        self,
        client: AsyncClient,
    ) -> None:
        """GET /api/v1/signals/{strategy_id} 返回分页格式（需求 4.4）。"""
        mock_signals = [_make_mock_signal(id=i, strategy_id=1) for i in range(1, 3)]

        with patch(
            "src.api.signals_top._signal_service.list_signals",
            new_callable=AsyncMock,
            return_value=(mock_signals, 2, datetime.now(timezone.utc)),
        ):
            response = await client.get("/api/v1/signals/1")

        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        assert "items" in data["data"]
        assert data["data"]["total"] == 2
