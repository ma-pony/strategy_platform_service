"""策略 API 集成测试（任务 5.2 / 13.5）。

验证：
  - GET /api/v1/strategies 分页列表（匿名和已登录用户均可访问）
  - GET /api/v1/strategies/{id} 详情（字段按会员等级过滤）
  - 匿名 / Free / VIP 三种身份字段可见性差异
  - 策略不存在时返回 code:3001 HTTP 404
"""

from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

TEST_SECRET = "test-secret-key-for-strategy-api-tests-256bits"


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


def _make_mock_strategy(
    id: int = 1,
    name: str = "RSI Strategy",
    description: str = "RSI 均值回归",
    strategy_type: str = "mean_reversion",
    pairs: list | None = None,
) -> MagicMock:
    """创建一个具有真实字段值的 mock Strategy 对象。"""
    strategy = MagicMock()
    strategy.id = id
    strategy.name = name
    strategy.description = description
    strategy.strategy_type = strategy_type
    strategy.pairs = pairs or ["BTC/USDT"]
    strategy.is_active = True
    strategy.trade_count = None
    strategy.max_drawdown = None
    strategy.sharpe_ratio = None
    strategy.win_rate = None
    return strategy


def _make_mock_db() -> AsyncMock:
    """创建通用 mock AsyncSession（后续通过 side_effect 或 return_value 配置具体行为）。"""
    db = AsyncMock()
    return db


class TestStrategiesListEndpoint:
    """GET /api/v1/strategies 列表接口测试。"""

    @pytest.mark.asyncio
    async def test_anonymous_can_access_strategies_list(
        self, client: AsyncClient, app
    ) -> None:
        """匿名用户可以访问策略列表（无需 Authorization header）。"""
        from src.core.deps import get_db

        mock_db = _make_mock_db()

        async def override_get_db():
            yield mock_db

        with patch(
            "src.api.strategies._strategy_service.list_strategies",
            new_callable=AsyncMock,
            return_value=([], 0),
        ):
            app.dependency_overrides[get_db] = override_get_db
            try:
                response = await client.get("/api/v1/strategies")
            finally:
                app.dependency_overrides.clear()

        assert response.status_code == 200
        body = response.json()
        assert body["code"] == 0
        assert "data" in body
        assert "items" in body["data"]
        assert "total" in body["data"]

    @pytest.mark.asyncio
    async def test_strategies_list_returns_paginated_response(
        self, client: AsyncClient, app
    ) -> None:
        """列表接口返回分页结构。"""
        from src.core.deps import get_db

        strategies = [_make_mock_strategy(id=i, name=f"Strategy {i}") for i in range(1, 4)]
        mock_db = _make_mock_db()

        async def override_get_db():
            yield mock_db

        with patch(
            "src.api.strategies._strategy_service.list_strategies",
            new_callable=AsyncMock,
            return_value=(strategies, 3),
        ):
            app.dependency_overrides[get_db] = override_get_db
            try:
                response = await client.get("/api/v1/strategies?page=1&page_size=20")
            finally:
                app.dependency_overrides.clear()

        assert response.status_code == 200
        body = response.json()
        assert body["code"] == 0
        data = body["data"]
        assert data["total"] == 3
        assert data["page"] == 1
        assert data["page_size"] == 20
        assert len(data["items"]) == 3

    @pytest.mark.asyncio
    async def test_strategy_list_item_anonymous_sees_base_fields(
        self, client: AsyncClient, app
    ) -> None:
        """匿名用户访问策略列表时，item 仅含基础字段（无 sharpe_ratio 等 VIP 字段）。"""
        from src.core.deps import get_db

        strategy = _make_mock_strategy()
        mock_db = _make_mock_db()

        async def override_get_db():
            yield mock_db

        with patch(
            "src.api.strategies._strategy_service.list_strategies",
            new_callable=AsyncMock,
            return_value=([strategy], 1),
        ):
            app.dependency_overrides[get_db] = override_get_db
            try:
                response = await client.get("/api/v1/strategies")
            finally:
                app.dependency_overrides.clear()

        assert response.status_code == 200
        item = response.json()["data"]["items"][0]
        assert "id" in item
        assert "name" in item
        assert item.get("sharpe_ratio") is None
        assert item.get("win_rate") is None


class TestStrategyDetailEndpoint:
    """GET /api/v1/strategies/{id} 详情接口测试。"""

    @pytest.mark.asyncio
    async def test_strategy_not_found_returns_404_with_code_3001(
        self, client: AsyncClient, app
    ) -> None:
        """策略不存在时返回 HTTP 404，code=3001。"""
        from src.core.deps import get_db
        from src.core.exceptions import NotFoundError

        mock_db = _make_mock_db()

        async def override_get_db():
            yield mock_db

        with patch(
            "src.api.strategies._strategy_service.get_strategy",
            new_callable=AsyncMock,
            side_effect=NotFoundError("策略 999 不存在"),
        ):
            app.dependency_overrides[get_db] = override_get_db
            try:
                response = await client.get("/api/v1/strategies/999")
            finally:
                app.dependency_overrides.clear()

        assert response.status_code == 404
        body = response.json()
        assert body["code"] == 3001

    @pytest.mark.asyncio
    async def test_anonymous_gets_base_fields_only(
        self, client: AsyncClient, app
    ) -> None:
        """匿名用户访问策略详情，仅返回基础字段（sharpe_ratio、win_rate 为 null）。"""
        from src.core.deps import get_db

        strategy = _make_mock_strategy()
        mock_db = _make_mock_db()

        async def override_get_db():
            yield mock_db

        with patch(
            "src.api.strategies._strategy_service.get_strategy",
            new_callable=AsyncMock,
            return_value=strategy,
        ):
            app.dependency_overrides[get_db] = override_get_db
            try:
                response = await client.get("/api/v1/strategies/1")
            finally:
                app.dependency_overrides.clear()

        assert response.status_code == 200
        item = response.json()["data"]
        assert item["id"] == 1
        assert item["name"] == "RSI Strategy"
        assert item.get("sharpe_ratio") is None
        assert item.get("win_rate") is None
        assert item.get("trade_count") is None

    @pytest.mark.asyncio
    async def test_free_user_sees_free_tier_fields_not_vip(
        self, client: AsyncClient, app
    ) -> None:
        """Free 用户访问策略详情：Free 字段可见，VIP 字段不可见。"""
        from src.core.deps import get_db, get_optional_user
        from src.core.enums import MembershipTier

        strategy = _make_mock_strategy()
        strategy.trade_count = 100
        strategy.max_drawdown = 0.12
        strategy.sharpe_ratio = 2.5
        strategy.win_rate = 0.65

        mock_free_user = MagicMock()
        mock_free_user.membership = MembershipTier.FREE
        mock_free_user.is_active = True

        mock_db = _make_mock_db()

        async def override_get_db():
            yield mock_db

        async def override_get_optional_user():
            return mock_free_user

        with patch(
            "src.api.strategies._strategy_service.get_strategy",
            new_callable=AsyncMock,
            return_value=strategy,
        ):
            app.dependency_overrides[get_db] = override_get_db
            app.dependency_overrides[get_optional_user] = override_get_optional_user
            try:
                response = await client.get("/api/v1/strategies/1")
            finally:
                app.dependency_overrides.clear()

        assert response.status_code == 200
        item = response.json()["data"]
        # Free 用户可见 trade_count 和 max_drawdown
        assert item["trade_count"] == 100
        assert item["max_drawdown"] == pytest.approx(0.12)
        # VIP 字段不可见
        assert item.get("sharpe_ratio") is None
        assert item.get("win_rate") is None

    @pytest.mark.asyncio
    async def test_page_size_over_limit_returns_422_code_2001(
        self, client: AsyncClient, app
    ) -> None:
        """传入 page_size=200（超过最大值 100）时，验证 HTTP 422 + code:2001（需求 2.5）。

        行为为返回校验错误，而非静默截断至最大值 100。
        """
        from src.core.deps import get_db

        mock_db = _make_mock_db()

        async def override_get_db():
            yield mock_db

        app.dependency_overrides[get_db] = override_get_db
        try:
            response = await client.get("/api/v1/strategies?page_size=200")
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 422
        body = response.json()
        assert body["code"] == 2001

    @pytest.mark.asyncio
    async def test_vip_user_sees_all_fields(
        self, client: AsyncClient, app
    ) -> None:
        """VIP 用户访问策略详情，所有字段均可见。"""
        from src.core.deps import get_db, get_optional_user
        from src.core.enums import MembershipTier

        strategy = _make_mock_strategy()
        strategy.sharpe_ratio = 2.5
        strategy.win_rate = 0.65
        strategy.trade_count = 100
        strategy.max_drawdown = 0.12

        mock_vip_user = MagicMock()
        mock_vip_user.membership = MembershipTier.VIP1
        mock_vip_user.is_active = True

        mock_db = _make_mock_db()

        async def override_get_db():
            yield mock_db

        async def override_get_optional_user():
            return mock_vip_user

        with patch(
            "src.api.strategies._strategy_service.get_strategy",
            new_callable=AsyncMock,
            return_value=strategy,
        ):
            app.dependency_overrides[get_db] = override_get_db
            app.dependency_overrides[get_optional_user] = override_get_optional_user
            try:
                response = await client.get("/api/v1/strategies/1")
            finally:
                app.dependency_overrides.clear()

        assert response.status_code == 200
        item = response.json()["data"]
        assert item["sharpe_ratio"] == pytest.approx(2.5)
        assert item["win_rate"] == pytest.approx(0.65)
        assert item["trade_count"] == 100
        assert item["max_drawdown"] == pytest.approx(0.12)

    @pytest.mark.asyncio
    async def test_vip2_user_sees_all_advanced_fields(
        self, client: AsyncClient, app
    ) -> None:
        """VIP2 用户访问策略详情，所有高级指标字段均可见（需求 2.3）。"""
        from src.core.deps import get_db, get_optional_user
        from src.core.enums import MembershipTier

        strategy = _make_mock_strategy()
        strategy.sharpe_ratio = 3.1
        strategy.win_rate = 0.70
        strategy.trade_count = 200
        strategy.max_drawdown = 0.08

        mock_vip2_user = MagicMock()
        mock_vip2_user.membership = MembershipTier.VIP2
        mock_vip2_user.is_active = True

        mock_db = _make_mock_db()

        async def override_get_db():
            yield mock_db

        async def override_get_optional_user():
            return mock_vip2_user

        with patch(
            "src.api.strategies._strategy_service.get_strategy",
            new_callable=AsyncMock,
            return_value=strategy,
        ):
            app.dependency_overrides[get_db] = override_get_db
            app.dependency_overrides[get_optional_user] = override_get_optional_user
            try:
                response = await client.get("/api/v1/strategies/1")
            finally:
                app.dependency_overrides.clear()

        assert response.status_code == 200
        item = response.json()["data"]
        assert item["sharpe_ratio"] == pytest.approx(3.1)
        assert item["win_rate"] == pytest.approx(0.70)
        assert item["trade_count"] == 200
        assert item["max_drawdown"] == pytest.approx(0.08)


class TestStrategyListFieldVisibility:
    """GET /api/v1/strategies 列表接口字段可见性补充测试（审计批次 1）。"""

    @pytest.mark.asyncio
    async def test_free_user_sees_free_fields_not_vip_in_list(
        self, client: AsyncClient, app
    ) -> None:
        """Free 用户访问策略列表：trade_count / max_drawdown 可见，sharpe_ratio / win_rate 为 null。"""
        from src.core.deps import get_db, get_optional_user
        from src.core.enums import MembershipTier

        strategy = _make_mock_strategy()
        strategy.trade_count = 80
        strategy.max_drawdown = 0.15
        strategy.sharpe_ratio = 1.8
        strategy.win_rate = 0.55
        mock_db = _make_mock_db()

        mock_free_user = MagicMock()
        mock_free_user.membership = MembershipTier.FREE
        mock_free_user.is_active = True

        async def override_get_db():
            yield mock_db

        async def override_get_optional_user():
            return mock_free_user

        with patch(
            "src.api.strategies._strategy_service.list_strategies",
            new_callable=AsyncMock,
            return_value=([strategy], 1),
        ):
            app.dependency_overrides[get_db] = override_get_db
            app.dependency_overrides[get_optional_user] = override_get_optional_user
            try:
                response = await client.get("/api/v1/strategies")
            finally:
                app.dependency_overrides.clear()

        assert response.status_code == 200
        item = response.json()["data"]["items"][0]
        assert item["trade_count"] == 80
        assert item["max_drawdown"] == pytest.approx(0.15)
        assert item.get("sharpe_ratio") is None
        assert item.get("win_rate") is None

    @pytest.mark.asyncio
    async def test_vip1_user_sees_all_fields_in_list(
        self, client: AsyncClient, app
    ) -> None:
        """VIP1 用户访问策略列表：所有字段均可见。"""
        from src.core.deps import get_db, get_optional_user
        from src.core.enums import MembershipTier

        strategy = _make_mock_strategy()
        strategy.trade_count = 120
        strategy.max_drawdown = 0.09
        strategy.sharpe_ratio = 2.1
        strategy.win_rate = 0.62
        mock_db = _make_mock_db()

        mock_vip1_user = MagicMock()
        mock_vip1_user.membership = MembershipTier.VIP1
        mock_vip1_user.is_active = True

        async def override_get_db():
            yield mock_db

        async def override_get_optional_user():
            return mock_vip1_user

        with patch(
            "src.api.strategies._strategy_service.list_strategies",
            new_callable=AsyncMock,
            return_value=([strategy], 1),
        ):
            app.dependency_overrides[get_db] = override_get_db
            app.dependency_overrides[get_optional_user] = override_get_optional_user
            try:
                response = await client.get("/api/v1/strategies")
            finally:
                app.dependency_overrides.clear()

        assert response.status_code == 200
        item = response.json()["data"]["items"][0]
        assert item["sharpe_ratio"] == pytest.approx(2.1)
        assert item["win_rate"] == pytest.approx(0.62)
        assert item["trade_count"] == 120
        assert item["max_drawdown"] == pytest.approx(0.09)


class TestStrategyListPaginationValidation:
    """GET /api/v1/strategies 分页参数边界校验补充测试（审计批次 1）。"""

    @pytest.mark.asyncio
    async def test_page_zero_returns_422_code_2001(
        self, client: AsyncClient, app
    ) -> None:
        """page=0 时返回 HTTP 422 + code:2001（页码最小值为 1）。"""
        from src.core.deps import get_db

        mock_db = _make_mock_db()

        async def override_get_db():
            yield mock_db

        app.dependency_overrides[get_db] = override_get_db
        try:
            response = await client.get("/api/v1/strategies?page=0")
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 422
        body = response.json()
        assert body["code"] == 2001

    @pytest.mark.asyncio
    async def test_page_size_zero_returns_422_code_2001(
        self, client: AsyncClient, app
    ) -> None:
        """page_size=0 时返回 HTTP 422 + code:2001（每页条数最小值为 1）。"""
        from src.core.deps import get_db

        mock_db = _make_mock_db()

        async def override_get_db():
            yield mock_db

        app.dependency_overrides[get_db] = override_get_db
        try:
            response = await client.get("/api/v1/strategies?page_size=0")
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 422
        body = response.json()
        assert body["code"] == 2001


class TestStrategyListSoftAuth:
    """GET /api/v1/strategies 软鉴权场景补充测试（审计批次 1）。"""

    @pytest.mark.asyncio
    async def test_invalid_token_treated_as_anonymous_returns_200(
        self, client: AsyncClient, app
    ) -> None:
        """携带签名无效 token 时，接口静默降级为匿名访问，返回 HTTP 200 + 基础字段。"""
        from src.core.deps import get_db

        mock_db = _make_mock_db()

        async def override_get_db():
            yield mock_db

        with patch(
            "src.api.strategies._strategy_service.list_strategies",
            new_callable=AsyncMock,
            return_value=([], 0),
        ):
            app.dependency_overrides[get_db] = override_get_db
            try:
                response = await client.get(
                    "/api/v1/strategies",
                    headers={"Authorization": "Bearer this.is.an.invalid.token"},
                )
            finally:
                app.dependency_overrides.clear()

        assert response.status_code == 200
        body = response.json()
        assert body["code"] == 0
        assert "items" in body["data"]


class TestStrategyDetailSoftAuth:
    """GET /api/v1/strategies/{id} 软鉴权及路径参数校验补充测试（审计批次 1）。"""

    @pytest.mark.asyncio
    async def test_non_integer_path_param_returns_422(
        self, client: AsyncClient, app
    ) -> None:
        """非整数路径参数 /strategies/abc 返回 HTTP 422，不应触发 500。"""
        from src.core.deps import get_db

        mock_db = _make_mock_db()

        async def override_get_db():
            yield mock_db

        app.dependency_overrides[get_db] = override_get_db
        try:
            response = await client.get("/api/v1/strategies/abc")
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_bad_token_silently_treated_as_anonymous_in_detail(
        self, client: AsyncClient, app
    ) -> None:
        """携带无效 token 访问策略详情时，软鉴权静默降级为匿名，返回 HTTP 200。"""
        from src.core.deps import get_db

        strategy = _make_mock_strategy()
        mock_db = _make_mock_db()

        async def override_get_db():
            yield mock_db

        with patch(
            "src.api.strategies._strategy_service.get_strategy",
            new_callable=AsyncMock,
            return_value=strategy,
        ):
            app.dependency_overrides[get_db] = override_get_db
            try:
                response = await client.get(
                    "/api/v1/strategies/1",
                    headers={"Authorization": "Bearer bad.token.here"},
                )
            finally:
                app.dependency_overrides.clear()

        assert response.status_code == 200
        body = response.json()
        assert body["code"] == 0
        # 匿名用户看不到 VIP 字段
        item = body["data"]
        assert item.get("sharpe_ratio") is None
        assert item.get("win_rate") is None


class TestStrategyListDefaultPagination:
    """策略列表默认分页参数验证（需求 2.4）。"""

    @pytest.mark.asyncio
    async def test_no_pagination_params_defaults_to_page1_size20(
        self, client: AsyncClient, app
    ) -> None:
        """不传分页参数时，接口默认返回第 1 页每页 20 条，响应含 items/total/page/page_size（需求 2.4）。"""
        from src.core.deps import get_db

        strategies = [_make_mock_strategy(id=i, name=f"Strategy {i}") for i in range(1, 6)]
        mock_db = _make_mock_db()

        async def override_get_db():
            yield mock_db

        with patch(
            "src.api.strategies._strategy_service.list_strategies",
            new_callable=AsyncMock,
            return_value=(strategies, 5),
        ):
            app.dependency_overrides[get_db] = override_get_db
            try:
                # 不传任何分页参数
                response = await client.get("/api/v1/strategies")
            finally:
                app.dependency_overrides.clear()

        assert response.status_code == 200
        body = response.json()
        assert body["code"] == 0
        data = body["data"]
        # 响应体必须包含分页字段
        assert "items" in data
        assert "total" in data
        assert "page" in data
        assert "page_size" in data
        # 默认分页值
        assert data["page"] == 1
        assert data["page_size"] == 20
        assert data["total"] == 5
        assert len(data["items"]) == 5
