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
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
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
    async def test_anonymous_can_access_reports_list(self, client: AsyncClient, app) -> None:
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
    async def test_reports_list_returns_paginated_response(self, client: AsyncClient, app) -> None:
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
    async def test_reports_list_contains_summary_fields(self, client: AsyncClient, app) -> None:
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
    async def test_reports_list_related_coins_in_response(self, client: AsyncClient, app) -> None:
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
    async def test_reports_list_default_page_size_is_20(self, client: AsyncClient, app) -> None:
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
    async def test_anonymous_can_access_report_detail(self, client: AsyncClient, app) -> None:
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
    async def test_report_detail_contains_full_content(self, client: AsyncClient, app) -> None:
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
    async def test_report_not_found_returns_404_with_code_3001(self, client: AsyncClient, app) -> None:
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
    async def test_report_detail_related_coins_in_response(self, client: AsyncClient, app) -> None:
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


# ─────────────────────────────────────────────────────────────────────────────
# 任务 8.1：新增研报 API 集成测试（需求 5.1, 5.2, 5.3, 5.4, 5.5）
# ─────────────────────────────────────────────────────────────────────────────


class TestReportTask8:
    """任务 8.1：补充研报接口统一信封格式与分页结构显式验证用例。"""

    @pytest.mark.asyncio
    async def test_anonymous_list_access_returns_200_with_code_0(self, client: AsyncClient, app) -> None:
        """匿名用户（无 Authorization header）访问研报列表 → HTTP 200 + code:0。

        需求 5.1：匿名用户可访问研报列表，无需认证。
        """
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
                # 不携带 Authorization header
                response = await client.get("/api/v1/reports")
            finally:
                app.dependency_overrides.clear()

        assert response.status_code == 200
        body = response.json()
        assert body["code"] == 0

    @pytest.mark.asyncio
    async def test_anonymous_detail_access_returns_full_content(self, client: AsyncClient, app) -> None:
        """匿名用户访问研报详情 → 返回完整内容（含 content 字段），无需登录。

        需求 5.2：研报详情接口无需认证，返回完整研报内容。
        """
        from src.core.deps import get_db

        report = _make_mock_report(id=5, content="完整市场分析：详细数据与趋势预测。")
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
                response = await client.get("/api/v1/reports/5")
            finally:
                app.dependency_overrides.clear()

        assert response.status_code == 200
        body = response.json()
        assert body["code"] == 0
        # 返回完整内容（content 字段存在）
        assert "content" in body["data"]
        assert body["data"]["content"] == "完整市场分析：详细数据与趋势预测。"

    @pytest.mark.asyncio
    async def test_nonexistent_report_id_returns_404_not_500(self, client: AsyncClient, app) -> None:
        """请求不存在的研报 ID → HTTP 404 + 业务错误码，而非 HTTP 500。

        需求 5.3：不存在的研报 ID 返回适当错误码（非 500），HTTP 状态码为 404。
        """
        from src.core.deps import get_db
        from src.core.exceptions import NotFoundError

        mock_db = _make_mock_db()

        async def override_get_db():
            yield mock_db

        with patch(
            "src.api.reports._report_service.get_report",
            new_callable=AsyncMock,
            side_effect=NotFoundError("研报 99999 不存在"),
        ):
            app.dependency_overrides[get_db] = override_get_db
            try:
                response = await client.get("/api/v1/reports/99999")
            finally:
                app.dependency_overrides.clear()

        # 必须是 404，不能是 500
        assert response.status_code == 404
        assert response.status_code != 500
        body = response.json()
        assert body["code"] == 3001

    @pytest.mark.asyncio
    async def test_pagination_structure_has_required_fields(self, client: AsyncClient, app) -> None:
        """研报列表响应 data 包含 items、total、page、page_size 四个字段。

        需求 5.4：研报列表接口返回标准分页结构，与其他列表接口保持一致。
        """
        from src.core.deps import get_db

        reports = [_make_mock_report(id=i) for i in range(1, 4)]
        mock_db = _make_mock_db()

        async def override_get_db():
            yield mock_db

        with patch(
            "src.api.reports._report_service.list_reports",
            new_callable=AsyncMock,
            return_value=(reports, 3),
        ):
            app.dependency_overrides[get_db] = override_get_db
            try:
                response = await client.get("/api/v1/reports?page=1&page_size=10")
            finally:
                app.dependency_overrides.clear()

        assert response.status_code == 200
        data = response.json()["data"]
        # 四个必须字段
        assert "items" in data
        assert "total" in data
        assert "page" in data
        assert "page_size" in data
        # 验证值
        assert data["total"] == 3
        assert data["page"] == 1
        assert data["page_size"] == 10
        assert len(data["items"]) == 3

    @pytest.mark.asyncio
    async def test_envelope_format_has_code_message_data_fields(self, client: AsyncClient, app) -> None:
        """研报接口响应体包含 code、message、data 三个字段。

        需求 5.5：研报接口响应符合统一信封格式（code、message、data 三字段齐全）。
        """
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
        # 三字段齐全
        assert "code" in body
        assert "message" in body
        assert "data" in body
        assert body["code"] == 0
        assert body["message"] is not None


# ─────────────────────────────────────────────────────────────────────────────
# Batch 2：补齐研报接口级别测试用例
# ─────────────────────────────────────────────────────────────────────────────


class TestReportListValidation:
    """GET /api/v1/reports 输入验证测试。"""

    @pytest.mark.asyncio
    async def test_page_size_exceeds_limit_returns_422(self, client: AsyncClient) -> None:
        """page_size=200（超过 100 上限）→ HTTP 422。"""
        resp = await client.get("/api/v1/reports", params={"page_size": 200})
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_page_zero_returns_422(self, client: AsyncClient) -> None:
        """page=0（小于最小值 1）→ HTTP 422。"""
        resp = await client.get("/api/v1/reports", params={"page": 0})
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_page_size_zero_returns_422(self, client: AsyncClient) -> None:
        """page_size=0（小于最小值 1）→ HTTP 422。"""
        resp = await client.get("/api/v1/reports", params={"page_size": 0})
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_negative_page_returns_422(self, client: AsyncClient) -> None:
        """page=-1（负数）→ HTTP 422。"""
        resp = await client.get("/api/v1/reports", params={"page": -1})
        assert resp.status_code == 422


class TestReportDetailValidation:
    """GET /api/v1/reports/{id} 输入验证测试。"""

    @pytest.mark.asyncio
    async def test_non_integer_report_id_returns_422(self, client: AsyncClient) -> None:
        """非整数 report_id（如 "abc"）→ HTTP 422。"""
        resp = await client.get("/api/v1/reports/abc")
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_float_report_id_returns_422(self, client: AsyncClient) -> None:
        """浮点数 report_id（如 "1.5"）→ HTTP 422。"""
        resp = await client.get("/api/v1/reports/1.5")
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_logged_in_user_can_access_report_detail(self, client: AsyncClient, app) -> None:
        """已登录用户访问研报详情 → 正常返回 200（不因多余的 token 报错）。"""
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
                # 携带 Authorization header（模拟已登录用户）
                response = await client.get(
                    "/api/v1/reports/1",
                    headers={"Authorization": "Bearer some-token"},
                )
            finally:
                app.dependency_overrides.clear()

        # 研报接口不做鉴权，即使携带 token 也应正常返回
        assert response.status_code == 200
        assert response.json()["code"] == 0

    @pytest.mark.asyncio
    async def test_logged_in_user_can_access_report_list(self, client: AsyncClient, app) -> None:
        """已登录用户访问研报列表 → 正常返回 200。"""
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
                response = await client.get(
                    "/api/v1/reports",
                    headers={"Authorization": "Bearer some-token"},
                )
            finally:
                app.dependency_overrides.clear()

        assert response.status_code == 200
        assert response.json()["code"] == 0
