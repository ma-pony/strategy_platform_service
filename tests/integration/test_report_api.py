"""研报 API 集成测试（任务 10.2 / 13.6）。

验证：
  - GET /api/v1/reports 分页列表，允许匿名访问
  - GET /api/v1/reports/{id} 研报详情，允许匿名访问
  - 研报不存在时返回 code:3001 HTTP 404
  - 列表含 id, title, summary, generated_at, related_coins 字段
  - 详情额外含 content 字段
"""

from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

TEST_SECRET = "test-secret-key-for-report-api-tests-256bits-long!!"


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


def _make_mock_report(
    id: int = 1,
    title: str = "BTC 市场研报",
    summary: str = "本报告分析 BTC 近期走势。",
    content: str = "详细内容包含对 BTC 的深度分析...",
    coins: list[str] | None = None,
) -> MagicMock:
    """创建 mock ResearchReport 对象。"""
    report = MagicMock()
    report.id = id
    report.title = title
    report.summary = summary
    report.content = content
    report.generated_at = datetime(2024, 3, 14, tzinfo=timezone.utc)
    report.created_at = datetime(2024, 3, 14, tzinfo=timezone.utc)
    report.updated_at = datetime(2024, 3, 14, tzinfo=timezone.utc)

    if coins is None:
        coins = ["BTC", "ETH"]
    coin_mocks = []
    for symbol in coins:
        coin_mock = MagicMock()
        coin_mock.coin_symbol = symbol
        coin_mocks.append(coin_mock)
    report.coins = coin_mocks

    return report


def _make_mock_db() -> AsyncMock:
    """创建通用 mock AsyncSession。"""
    return AsyncMock()


class TestReportListEndpoint:
    """GET /api/v1/reports 接口测试。"""

    @pytest.mark.asyncio
    async def test_anonymous_can_access_reports_list(
        self, client: AsyncClient, app
    ) -> None:
        """匿名用户可以访问研报列表（无需 Authorization header）。"""
        from src.core.deps import get_db

        mock_db = _make_mock_db()

        async def override_get_db():
            yield mock_db

        with patch(
            "src.api.reports._report_service.list_reports",
            new_callable=AsyncMock,
            return_value=([], 0),
        ):
            app.dependency_overrides[get_db] = override_get_db
            try:
                response = await client.get("/api/v1/reports")
            finally:
                app.dependency_overrides.clear()

        assert response.status_code == 200
        body = response.json()
        assert body["code"] == 0
        assert "data" in body
        assert "items" in body["data"]

    @pytest.mark.asyncio
    async def test_reports_list_returns_paginated_response(
        self, client: AsyncClient, app
    ) -> None:
        """研报列表接口返回正确分页结构。"""
        from src.core.deps import get_db

        reports = [
            _make_mock_report(id=1),
            _make_mock_report(id=2),
        ]
        mock_db = _make_mock_db()

        async def override_get_db():
            yield mock_db

        with patch(
            "src.api.reports._report_service.list_reports",
            new_callable=AsyncMock,
            return_value=(reports, 2),
        ):
            app.dependency_overrides[get_db] = override_get_db
            try:
                response = await client.get("/api/v1/reports?page=1&page_size=20")
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
    async def test_reports_list_contains_summary_fields(
        self, client: AsyncClient, app
    ) -> None:
        """研报列表包含 id, title, summary, generated_at, related_coins 字段。"""
        from src.core.deps import get_db

        report = _make_mock_report(id=1, coins=["BTC", "ETH"])
        mock_db = _make_mock_db()

        async def override_get_db():
            yield mock_db

        with patch(
            "src.api.reports._report_service.list_reports",
            new_callable=AsyncMock,
            return_value=([report], 1),
        ):
            app.dependency_overrides[get_db] = override_get_db
            try:
                response = await client.get("/api/v1/reports")
            finally:
                app.dependency_overrides.clear()

        assert response.status_code == 200
        item = response.json()["data"]["items"][0]
        assert item["id"] == 1
        assert item["title"] == "BTC 市场研报"
        assert "summary" in item
        assert "generated_at" in item
        assert "related_coins" in item
        # 列表接口不应包含 content 字段（摘要只）
        assert "content" not in item

    @pytest.mark.asyncio
    async def test_reports_list_related_coins_in_response(
        self, client: AsyncClient, app
    ) -> None:
        """研报列表响应包含关联币种列表。"""
        from src.core.deps import get_db

        report = _make_mock_report(id=1, coins=["BTC", "ETH", "SOL"])
        mock_db = _make_mock_db()

        async def override_get_db():
            yield mock_db

        with patch(
            "src.api.reports._report_service.list_reports",
            new_callable=AsyncMock,
            return_value=([report], 1),
        ):
            app.dependency_overrides[get_db] = override_get_db
            try:
                response = await client.get("/api/v1/reports")
            finally:
                app.dependency_overrides.clear()

        assert response.status_code == 200
        item = response.json()["data"]["items"][0]
        assert set(item["related_coins"]) == {"BTC", "ETH", "SOL"}

    @pytest.mark.asyncio
    async def test_reports_list_default_page_size_is_20(
        self, client: AsyncClient, app
    ) -> None:
        """研报列表接口默认 page_size=20。"""
        from src.core.deps import get_db

        mock_db = _make_mock_db()

        async def override_get_db():
            yield mock_db

        with patch(
            "src.api.reports._report_service.list_reports",
            new_callable=AsyncMock,
            return_value=([], 0),
        ):
            app.dependency_overrides[get_db] = override_get_db
            try:
                response = await client.get("/api/v1/reports")
            finally:
                app.dependency_overrides.clear()

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["page_size"] == 20


class TestReportDetailEndpoint:
    """GET /api/v1/reports/{id} 详情接口测试。"""

    @pytest.mark.asyncio
    async def test_anonymous_can_access_report_detail(
        self, client: AsyncClient, app
    ) -> None:
        """匿名用户可以访问研报详情（无需 Authorization header）。"""
        from src.core.deps import get_db

        report = _make_mock_report(id=1)
        mock_db = _make_mock_db()

        async def override_get_db():
            yield mock_db

        with patch(
            "src.api.reports._report_service.get_report",
            new_callable=AsyncMock,
            return_value=report,
        ):
            app.dependency_overrides[get_db] = override_get_db
            try:
                response = await client.get("/api/v1/reports/1")
            finally:
                app.dependency_overrides.clear()

        assert response.status_code == 200
        body = response.json()
        assert body["code"] == 0

    @pytest.mark.asyncio
    async def test_report_detail_contains_full_content(
        self, client: AsyncClient, app
    ) -> None:
        """研报详情包含完整 content 字段。"""
        from src.core.deps import get_db

        report = _make_mock_report(id=1, content="这是完整的市场分析内容，包含深度数据...")
        mock_db = _make_mock_db()

        async def override_get_db():
            yield mock_db

        with patch(
            "src.api.reports._report_service.get_report",
            new_callable=AsyncMock,
            return_value=report,
        ):
            app.dependency_overrides[get_db] = override_get_db
            try:
                response = await client.get("/api/v1/reports/1")
            finally:
                app.dependency_overrides.clear()

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["id"] == 1
        assert data["title"] == "BTC 市场研报"
        assert "content" in data
        assert data["content"] == "这是完整的市场分析内容，包含深度数据..."
        assert "summary" in data
        assert "generated_at" in data
        assert "related_coins" in data

    @pytest.mark.asyncio
    async def test_report_not_found_returns_404_with_code_3001(
        self, client: AsyncClient, app
    ) -> None:
        """研报不存在时返回 HTTP 404，code=3001。"""
        from src.core.deps import get_db
        from src.core.exceptions import NotFoundError

        mock_db = _make_mock_db()

        async def override_get_db():
            yield mock_db

        with patch(
            "src.api.reports._report_service.get_report",
            new_callable=AsyncMock,
            side_effect=NotFoundError("研报 999 不存在"),
        ):
            app.dependency_overrides[get_db] = override_get_db
            try:
                response = await client.get("/api/v1/reports/999")
            finally:
                app.dependency_overrides.clear()

        assert response.status_code == 404
        body = response.json()
        assert body["code"] == 3001

    @pytest.mark.asyncio
    async def test_report_detail_related_coins_in_response(
        self, client: AsyncClient, app
    ) -> None:
        """研报详情包含关联币种列表。"""
        from src.core.deps import get_db

        report = _make_mock_report(id=1, coins=["BTC", "ETH"])
        mock_db = _make_mock_db()

        async def override_get_db():
            yield mock_db

        with patch(
            "src.api.reports._report_service.get_report",
            new_callable=AsyncMock,
            return_value=report,
        ):
            app.dependency_overrides[get_db] = override_get_db
            try:
                response = await client.get("/api/v1/reports/1")
            finally:
                app.dependency_overrides.clear()

        assert response.status_code == 200
        data = response.json()["data"]
        assert set(data["related_coins"]) == {"BTC", "ETH"}
