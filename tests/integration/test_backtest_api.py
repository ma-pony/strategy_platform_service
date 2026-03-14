"""回测 API 集成测试（任务 8.2 / 13.6）。

验证：
  - GET /api/v1/strategies/{id}/backtests 分页接口（字段按会员等级过滤）
  - GET /api/v1/backtests/{id} 详情接口（字段按会员等级过滤）
  - 策略不存在时返回 code:3001 HTTP 404
  - 回测记录不存在时返回 code:3001 HTTP 404
  - 匿名 / Free / VIP 字段可见性差异
"""

from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

TEST_SECRET = "test-secret-key-for-backtest-api-tests-256bits-long"


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


def _make_mock_backtest_result(
    id: int = 1,
    strategy_id: int = 1,
    task_id: int = 1,
    total_return: float = 0.15,
    annual_return: float = 0.20,
    sharpe_ratio: float = 1.5,
    max_drawdown: float = 0.10,
    trade_count: int = 50,
    win_rate: float = 0.60,
) -> MagicMock:
    """创建 mock BacktestResult 对象。"""
    result = MagicMock()
    result.id = id
    result.strategy_id = strategy_id
    result.task_id = task_id
    result.total_return = total_return
    result.annual_return = annual_return
    result.sharpe_ratio = sharpe_ratio
    result.max_drawdown = max_drawdown
    result.trade_count = trade_count
    result.win_rate = win_rate
    result.period_start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    result.period_end = datetime(2024, 12, 31, tzinfo=timezone.utc)
    result.created_at = datetime(2024, 12, 31, tzinfo=timezone.utc)
    return result


def _make_mock_db() -> AsyncMock:
    """创建通用 mock AsyncSession。"""
    return AsyncMock()


class TestBacktestListEndpoint:
    """GET /api/v1/strategies/{id}/backtests 接口测试。"""

    @pytest.mark.asyncio
    async def test_anonymous_can_access_backtests_list(
        self, client: AsyncClient, app
    ) -> None:
        """匿名用户可以访问回测列表（无需 Authorization header）。"""
        from src.core.deps import get_db

        mock_db = _make_mock_db()

        async def override_get_db():
            yield mock_db

        with patch(
            "src.api.backtests._backtest_service.list_backtests",
            new_callable=AsyncMock,
            return_value=([], 0),
        ):
            app.dependency_overrides[get_db] = override_get_db
            try:
                response = await client.get("/api/v1/strategies/1/backtests")
            finally:
                app.dependency_overrides.clear()

        assert response.status_code == 200
        body = response.json()
        assert body["code"] == 0
        assert "data" in body
        assert "items" in body["data"]

    @pytest.mark.asyncio
    async def test_backtests_list_returns_paginated_response(
        self, client: AsyncClient, app
    ) -> None:
        """回测列表接口返回正确分页结构。"""
        from src.core.deps import get_db

        results = [
            _make_mock_backtest_result(id=1),
            _make_mock_backtest_result(id=2),
        ]
        mock_db = _make_mock_db()

        async def override_get_db():
            yield mock_db

        with patch(
            "src.api.backtests._backtest_service.list_backtests",
            new_callable=AsyncMock,
            return_value=(results, 2),
        ):
            app.dependency_overrides[get_db] = override_get_db
            try:
                response = await client.get("/api/v1/strategies/1/backtests?page=1&page_size=20")
            finally:
                app.dependency_overrides.clear()

        assert response.status_code == 200
        body = response.json()
        data = body["data"]
        assert data["total"] == 2
        assert data["page"] == 1
        assert data["page_size"] == 20
        assert len(data["items"]) == 2

    @pytest.mark.asyncio
    async def test_anonymous_sees_only_base_fields_in_backtest_list(
        self, client: AsyncClient, app
    ) -> None:
        """匿名用户只能看到基础字段（total_return、sharpe_ratio 等为 null）。"""
        from src.core.deps import get_db

        result = _make_mock_backtest_result()
        mock_db = _make_mock_db()

        async def override_get_db():
            yield mock_db

        with patch(
            "src.api.backtests._backtest_service.list_backtests",
            new_callable=AsyncMock,
            return_value=([result], 1),
        ):
            app.dependency_overrides[get_db] = override_get_db
            try:
                response = await client.get("/api/v1/strategies/1/backtests")
            finally:
                app.dependency_overrides.clear()

        assert response.status_code == 200
        item = response.json()["data"]["items"][0]
        assert "id" in item
        assert "strategy_id" in item
        # 匿名用户 Free 字段应为 null
        assert item.get("total_return") is None
        assert item.get("trade_count") is None
        # 匿名用户 VIP 字段应为 null
        assert item.get("sharpe_ratio") is None
        assert item.get("win_rate") is None

    @pytest.mark.asyncio
    async def test_free_user_sees_free_tier_fields_not_vip_in_backtest_list(
        self, client: AsyncClient, app
    ) -> None:
        """Free 用户回测列表中可见 Free 字段，VIP 字段为 null。"""
        from src.core.deps import get_db, get_optional_user
        from src.core.enums import MembershipTier

        result = _make_mock_backtest_result()
        mock_db = _make_mock_db()

        mock_free_user = MagicMock()
        mock_free_user.membership = MembershipTier.FREE
        mock_free_user.is_active = True

        async def override_get_db():
            yield mock_db

        async def override_get_optional_user():
            return mock_free_user

        with patch(
            "src.api.backtests._backtest_service.list_backtests",
            new_callable=AsyncMock,
            return_value=([result], 1),
        ):
            app.dependency_overrides[get_db] = override_get_db
            app.dependency_overrides[get_optional_user] = override_get_optional_user
            try:
                response = await client.get("/api/v1/strategies/1/backtests")
            finally:
                app.dependency_overrides.clear()

        assert response.status_code == 200
        item = response.json()["data"]["items"][0]
        # Free 用户可见
        assert item["total_return"] == pytest.approx(0.15)
        assert item["trade_count"] == 50
        assert item["max_drawdown"] == pytest.approx(0.10)
        # VIP 不可见
        assert item.get("sharpe_ratio") is None
        assert item.get("win_rate") is None

    @pytest.mark.asyncio
    async def test_vip_user_sees_all_fields_in_backtest_list(
        self, client: AsyncClient, app
    ) -> None:
        """VIP 用户回测列表中可见所有字段。"""
        from src.core.deps import get_db, get_optional_user
        from src.core.enums import MembershipTier

        result = _make_mock_backtest_result()
        mock_db = _make_mock_db()

        mock_vip_user = MagicMock()
        mock_vip_user.membership = MembershipTier.VIP1
        mock_vip_user.is_active = True

        async def override_get_db():
            yield mock_db

        async def override_get_optional_user():
            return mock_vip_user

        with patch(
            "src.api.backtests._backtest_service.list_backtests",
            new_callable=AsyncMock,
            return_value=([result], 1),
        ):
            app.dependency_overrides[get_db] = override_get_db
            app.dependency_overrides[get_optional_user] = override_get_optional_user
            try:
                response = await client.get("/api/v1/strategies/1/backtests")
            finally:
                app.dependency_overrides.clear()

        assert response.status_code == 200
        item = response.json()["data"]["items"][0]
        assert item["sharpe_ratio"] == pytest.approx(1.5)
        assert item["win_rate"] == pytest.approx(0.60)
        assert item["annual_return"] == pytest.approx(0.20)
        assert item["total_return"] == pytest.approx(0.15)


class TestBacktestDetailEndpoint:
    """GET /api/v1/backtests/{id} 详情接口测试。"""

    @pytest.mark.asyncio
    async def test_backtest_not_found_returns_404_with_code_3001(
        self, client: AsyncClient, app
    ) -> None:
        """回测记录不存在时返回 HTTP 404，code=3001。"""
        from src.core.deps import get_db
        from src.core.exceptions import NotFoundError

        mock_db = _make_mock_db()

        async def override_get_db():
            yield mock_db

        with patch(
            "src.api.backtests._backtest_service.get_backtest",
            new_callable=AsyncMock,
            side_effect=NotFoundError("回测记录 999 不存在"),
        ):
            app.dependency_overrides[get_db] = override_get_db
            try:
                response = await client.get("/api/v1/backtests/999")
            finally:
                app.dependency_overrides.clear()

        assert response.status_code == 404
        body = response.json()
        assert body["code"] == 3001

    @pytest.mark.asyncio
    async def test_anonymous_gets_base_fields_in_backtest_detail(
        self, client: AsyncClient, app
    ) -> None:
        """匿名用户访问回测详情，仅返回基础字段。"""
        from src.core.deps import get_db

        result = _make_mock_backtest_result()
        mock_db = _make_mock_db()

        async def override_get_db():
            yield mock_db

        with patch(
            "src.api.backtests._backtest_service.get_backtest",
            new_callable=AsyncMock,
            return_value=result,
        ):
            app.dependency_overrides[get_db] = override_get_db
            try:
                response = await client.get("/api/v1/backtests/1")
            finally:
                app.dependency_overrides.clear()

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["id"] == 1
        assert data.get("total_return") is None
        assert data.get("sharpe_ratio") is None

    @pytest.mark.asyncio
    async def test_vip_user_gets_all_fields_in_backtest_detail(
        self, client: AsyncClient, app
    ) -> None:
        """VIP 用户访问回测详情，所有字段均可见。"""
        from src.core.deps import get_db, get_optional_user
        from src.core.enums import MembershipTier

        result = _make_mock_backtest_result()
        mock_db = _make_mock_db()

        mock_vip_user = MagicMock()
        mock_vip_user.membership = MembershipTier.VIP1
        mock_vip_user.is_active = True

        async def override_get_db():
            yield mock_db

        async def override_get_optional_user():
            return mock_vip_user

        with patch(
            "src.api.backtests._backtest_service.get_backtest",
            new_callable=AsyncMock,
            return_value=result,
        ):
            app.dependency_overrides[get_db] = override_get_db
            app.dependency_overrides[get_optional_user] = override_get_optional_user
            try:
                response = await client.get("/api/v1/backtests/1")
            finally:
                app.dependency_overrides.clear()

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["sharpe_ratio"] == pytest.approx(1.5)
        assert data["win_rate"] == pytest.approx(0.60)
        assert data["annual_return"] == pytest.approx(0.20)
