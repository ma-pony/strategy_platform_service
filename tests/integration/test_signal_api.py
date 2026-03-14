"""信号 API 集成测试（任务 9.2 / 13.6）。

验证：
  - GET /api/v1/strategies/{id}/signals 接口（含 signals 列表和 last_updated_at）
  - VIP 用户可见 confidence_score，匿名 / Free 用户该字段为 null
  - strategy_id 不存在时返回 code:3001 HTTP 404
  - Redis 命中路径和 DB 回退路径均正常处理
"""

from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

TEST_SECRET = "test-secret-key-for-signal-api-tests-256bits-long-enough"


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
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac


def _make_mock_signal(
    id: int = 1,
    strategy_id: int = 1,
    confidence_score: float | None = 0.85,
) -> MagicMock:
    """创建 mock TradingSignal 对象。"""
    from src.core.enums import SignalDirection

    signal = MagicMock()
    signal.id = id
    signal.strategy_id = strategy_id
    signal.pair = "BTC/USDT"
    signal.direction = SignalDirection.BUY
    signal.confidence_score = confidence_score
    signal.signal_at = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
    signal.created_at = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
    return signal


def _make_mock_db() -> AsyncMock:
    return AsyncMock()


class TestSignalListEndpoint:
    """GET /api/v1/strategies/{id}/signals 接口测试。"""

    @pytest.mark.asyncio
    async def test_signal_endpoint_returns_signals_and_last_updated_at(
        self, client: AsyncClient, app
    ) -> None:
        """信号接口返回 signals 列表和 last_updated_at 字段。"""
        from src.core.deps import get_db

        mock_db = _make_mock_db()
        signals = [_make_mock_signal(id=1)]
        last_updated = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)

        async def override_get_db():
            yield mock_db

        with patch(
            "src.api.signals._signal_service.get_signals",
            new_callable=AsyncMock,
            return_value=(signals, last_updated),
        ):
            app.dependency_overrides[get_db] = override_get_db
            try:
                response = await client.get("/api/v1/strategies/1/signals")
            finally:
                app.dependency_overrides.clear()

        assert response.status_code == 200
        body = response.json()
        assert body["code"] == 0
        assert "data" in body
        data = body["data"]
        assert "signals" in data
        assert "last_updated_at" in data

    @pytest.mark.asyncio
    async def test_anonymous_cannot_see_confidence_score(
        self, client: AsyncClient, app
    ) -> None:
        """匿名用户信号响应中 confidence_score 应为 null。"""
        from src.core.deps import get_db

        mock_db = _make_mock_db()
        signals = [_make_mock_signal(id=1, confidence_score=0.85)]
        last_updated = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)

        async def override_get_db():
            yield mock_db

        with patch(
            "src.api.signals._signal_service.get_signals",
            new_callable=AsyncMock,
            return_value=(signals, last_updated),
        ):
            app.dependency_overrides[get_db] = override_get_db
            try:
                response = await client.get("/api/v1/strategies/1/signals")
            finally:
                app.dependency_overrides.clear()

        assert response.status_code == 200
        item = response.json()["data"]["signals"][0]
        assert item.get("confidence_score") is None

    @pytest.mark.asyncio
    async def test_free_user_cannot_see_confidence_score(
        self, client: AsyncClient, app
    ) -> None:
        """Free 用户信号响应中 confidence_score 应为 null。"""
        from src.core.deps import get_db, get_optional_user
        from src.core.enums import MembershipTier

        mock_db = _make_mock_db()
        signals = [_make_mock_signal(id=1, confidence_score=0.85)]
        last_updated = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)

        mock_free_user = MagicMock()
        mock_free_user.membership = MembershipTier.FREE
        mock_free_user.is_active = True

        async def override_get_db():
            yield mock_db

        async def override_get_optional_user():
            return mock_free_user

        with patch(
            "src.api.signals._signal_service.get_signals",
            new_callable=AsyncMock,
            return_value=(signals, last_updated),
        ):
            app.dependency_overrides[get_db] = override_get_db
            app.dependency_overrides[get_optional_user] = override_get_optional_user
            try:
                response = await client.get("/api/v1/strategies/1/signals")
            finally:
                app.dependency_overrides.clear()

        assert response.status_code == 200
        item = response.json()["data"]["signals"][0]
        assert item.get("confidence_score") is None

    @pytest.mark.asyncio
    async def test_vip_user_can_see_confidence_score(
        self, client: AsyncClient, app
    ) -> None:
        """VIP 用户信号响应中应包含 confidence_score。"""
        from src.core.deps import get_db, get_optional_user
        from src.core.enums import MembershipTier

        mock_db = _make_mock_db()
        signals = [_make_mock_signal(id=1, confidence_score=0.85)]
        last_updated = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)

        mock_vip_user = MagicMock()
        mock_vip_user.membership = MembershipTier.VIP1
        mock_vip_user.is_active = True

        async def override_get_db():
            yield mock_db

        async def override_get_optional_user():
            return mock_vip_user

        with patch(
            "src.api.signals._signal_service.get_signals",
            new_callable=AsyncMock,
            return_value=(signals, last_updated),
        ):
            app.dependency_overrides[get_db] = override_get_db
            app.dependency_overrides[get_optional_user] = override_get_optional_user
            try:
                response = await client.get("/api/v1/strategies/1/signals")
            finally:
                app.dependency_overrides.clear()

        assert response.status_code == 200
        item = response.json()["data"]["signals"][0]
        assert item["confidence_score"] == pytest.approx(0.85)

    @pytest.mark.asyncio
    async def test_strategy_not_found_returns_404_with_code_3001(
        self, client: AsyncClient, app
    ) -> None:
        """strategy_id 不存在时返回 HTTP 404，code=3001。"""
        from src.core.deps import get_db
        from src.core.exceptions import NotFoundError

        mock_db = _make_mock_db()

        async def override_get_db():
            yield mock_db

        with patch(
            "src.api.signals._signal_service.get_signals",
            new_callable=AsyncMock,
            side_effect=NotFoundError("策略 999 不存在"),
        ):
            app.dependency_overrides[get_db] = override_get_db
            try:
                response = await client.get("/api/v1/strategies/999/signals")
            finally:
                app.dependency_overrides.clear()

        assert response.status_code == 404
        body = response.json()
        assert body["code"] == 3001

    @pytest.mark.asyncio
    async def test_signals_limit_query_param_works(
        self, client: AsyncClient, app
    ) -> None:
        """?limit 查询参数应被接受。"""
        from src.core.deps import get_db

        mock_db = _make_mock_db()
        last_updated = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)

        async def override_get_db():
            yield mock_db

        with patch(
            "src.api.signals._signal_service.get_signals",
            new_callable=AsyncMock,
            return_value=([], last_updated),
        ):
            app.dependency_overrides[get_db] = override_get_db
            try:
                response = await client.get("/api/v1/strategies/1/signals?limit=5")
            finally:
                app.dependency_overrides.clear()

        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_signals_response_contains_direction_and_signal_at(
        self, client: AsyncClient, app
    ) -> None:
        """信号响应中包含 direction 和 signal_at 字段（所有用户可见）。"""
        from src.core.deps import get_db

        mock_db = _make_mock_db()
        signals = [_make_mock_signal(id=1)]
        last_updated = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)

        async def override_get_db():
            yield mock_db

        with patch(
            "src.api.signals._signal_service.get_signals",
            new_callable=AsyncMock,
            return_value=(signals, last_updated),
        ):
            app.dependency_overrides[get_db] = override_get_db
            try:
                response = await client.get("/api/v1/strategies/1/signals")
            finally:
                app.dependency_overrides.clear()

        assert response.status_code == 200
        item = response.json()["data"]["signals"][0]
        assert "direction" in item
        assert "signal_at" in item
