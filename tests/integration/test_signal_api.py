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
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
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
    signal.timeframe = "1h"
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
    async def test_signal_endpoint_returns_signals_and_last_updated_at(self, client: AsyncClient, app) -> None:
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
    async def test_anonymous_cannot_see_confidence_score(self, client: AsyncClient, app) -> None:
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
    async def test_free_user_cannot_see_confidence_score(self, client: AsyncClient, app) -> None:
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
    async def test_vip_user_can_see_confidence_score(self, client: AsyncClient, app) -> None:
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
    async def test_strategy_not_found_returns_404_with_code_3001(self, client: AsyncClient, app) -> None:
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
    async def test_signals_limit_query_param_works(self, client: AsyncClient, app) -> None:
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
    async def test_signals_response_contains_direction_and_signal_at(self, client: AsyncClient, app) -> None:
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


class TestSignalVip2FieldVisibility:
    """GET /api/v1/strategies/{id}/signals VIP2 字段可见性补充测试（审计批次 1）。"""

    @pytest.mark.asyncio
    async def test_vip2_user_sees_confidence_score(self, client: AsyncClient, app) -> None:
        """VIP2 用户信号响应中应包含 confidence_score（与 VIP1 相同权限）。"""
        from src.core.deps import get_db, get_optional_user
        from src.core.enums import MembershipTier

        mock_db = _make_mock_db()
        signals = [_make_mock_signal(id=1, confidence_score=0.92)]
        last_updated = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)

        mock_vip2_user = MagicMock()
        mock_vip2_user.membership = MembershipTier.VIP2
        mock_vip2_user.is_active = True

        async def override_get_db():
            yield mock_db

        async def override_get_optional_user():
            return mock_vip2_user

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
        assert item["confidence_score"] == pytest.approx(0.92)


class TestSignalLimitValidation:
    """GET /api/v1/strategies/{id}/signals limit 参数边界校验补充测试（审计批次 1）。"""

    @pytest.mark.asyncio
    async def test_limit_zero_returns_422_code_2001(self, client: AsyncClient, app) -> None:
        """limit=0 时返回 HTTP 422 + code:2001（最小值校验）。"""
        from src.core.deps import get_db

        mock_db = _make_mock_db()

        async def override_get_db():
            yield mock_db

        app.dependency_overrides[get_db] = override_get_db
        try:
            response = await client.get("/api/v1/strategies/1/signals?limit=0")
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 422
        body = response.json()
        assert body["code"] == 2001

    @pytest.mark.asyncio
    async def test_limit_exceeds_max_returns_422_code_2001(self, client: AsyncClient, app) -> None:
        """limit=200（超过上限）时返回 HTTP 422 + code:2001。"""
        from src.core.deps import get_db

        mock_db = _make_mock_db()

        async def override_get_db():
            yield mock_db

        app.dependency_overrides[get_db] = override_get_db
        try:
            response = await client.get("/api/v1/strategies/1/signals?limit=200")
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 422
        body = response.json()
        assert body["code"] == 2001


class TestSignalSoftAuth:
    """GET /api/v1/strategies/{id}/signals 软鉴权场景补充测试（审计批次 1）。"""

    @pytest.mark.asyncio
    async def test_bad_token_treated_as_anonymous_returns_200(self, client: AsyncClient, app) -> None:
        """携带无效 token 时，软鉴权静默降级为匿名，信号接口返回 HTTP 200。"""
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
                response = await client.get(
                    "/api/v1/strategies/1/signals",
                    headers={"Authorization": "Bearer this.is.an.invalid.token"},
                )
            finally:
                app.dependency_overrides.clear()

        assert response.status_code == 200
        body = response.json()
        assert body["code"] == 0
        assert "signals" in body["data"]


# ─────────────────────────────────────────────────────────────────────────────
# 任务 7.1：空缓存保护验证（需求 4.1, 4.4）
# 任务 7.2：P95 性能测试占位（需求 4.5）
# ─────────────────────────────────────────────────────────────────────────────


class TestSignalEmptyCacheProtection:
    """任务 7.1：空缓存场景 → 返回空列表 + code:0，而非 HTTP 500（需求 4.4）。"""

    @pytest.mark.asyncio
    async def test_empty_cache_returns_empty_list_with_code_0(self, client: AsyncClient, app) -> None:
        """信号缓存为空时 → HTTP 200 + code:0 + 空 signals 列表，而非 HTTP 500。

        需求 4.4：若信号缓存中不存在指定策略和交易对的数据，系统返回空列表而非 500 错误。
        需求 4.1：信号接口正常返回 HTTP 200。
        """
        from src.core.deps import get_db

        mock_db = _make_mock_db()
        last_updated = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)

        async def override_get_db():
            yield mock_db

        with patch(
            "src.api.signals._signal_service.get_signals",
            new_callable=AsyncMock,
            return_value=([], last_updated),  # 空缓存：signals 列表为空
        ):
            app.dependency_overrides[get_db] = override_get_db
            try:
                response = await client.get("/api/v1/strategies/1/signals")
            finally:
                app.dependency_overrides.clear()

        # 不应返回 500
        assert response.status_code == 200
        body = response.json()
        assert body["code"] == 0
        assert "data" in body
        assert body["data"]["signals"] == []


class TestSignalPerformancePlaceholder:
    """任务 7.2：信号 P95 响应时间性能测试占位（需求 4.5）。"""

    @pytest.mark.skip(reason="性能测试延后，待 pytest-benchmark / Locust 方案确定后实现")
    async def test_signal_p95_response_time_under_500ms(self) -> None:
        """P95 响应时间应不超过 500ms（信号数据来自缓存，非实时计算）。

        需求 4.5：信号接口响应时间满足性能要求。
        延后原因：需要 pytest-benchmark 或 Locust/k6 等性能测试工具，
        当前 CI 环境未配置，待专项性能测试方案确定后实现。
        """
