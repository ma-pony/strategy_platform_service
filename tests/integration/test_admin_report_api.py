"""管理员研报 CRUD API 集成测试。

验证：
  - POST /api/v1/admin/reports：管理员创建研报
  - PUT /api/v1/admin/reports/{id}：管理员更新研报
  - DELETE /api/v1/admin/reports/{id}：管理员删除研报
  - 非管理员访问返回 403
  - 研报不存在时返回 404
"""

import datetime
from collections.abc import AsyncGenerator
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from src.core.deps import get_db, require_admin_or_api_key

TEST_SECRET = "test-secret-key-for-admin-report-api-256bits-long!!"  # pragma: allowlist secret


@pytest.fixture()
def env_setup(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SECRET_KEY", TEST_SECRET)
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")
    monkeypatch.setenv("DATABASE_SYNC_URL", "postgresql+psycopg2://u:p@localhost/db")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")

    from src.core import app_settings

    app_settings.get_settings.cache_clear()
    yield
    app_settings.get_settings.cache_clear()


def _make_admin_user():
    return SimpleNamespace(
        id=1,
        email="admin@example.com",
        membership="free",
        is_active=True,
        is_admin=True,
    )


def _make_mock_report(
    id: int = 1,
    title: str = "测试研报",
    summary: str = "测试摘要",
    content: str = "测试内容",
    coins: list[str] | None = None,
):
    """创建 mock ResearchReport 对象。"""
    report = MagicMock()
    report.id = id
    report.title = title
    report.summary = summary
    report.content = content
    report.generated_at = datetime.datetime(2024, 3, 14, tzinfo=datetime.timezone.utc)
    report.created_at = datetime.datetime(2024, 3, 14, tzinfo=datetime.timezone.utc)
    report.updated_at = datetime.datetime(2024, 3, 14, tzinfo=datetime.timezone.utc)

    if coins is None:
        coins = ["BTC", "ETH"]
    coin_mocks = []
    for symbol in coins:
        coin_mock = MagicMock()
        coin_mock.coin_symbol = symbol
        coin_mocks.append(coin_mock)
    report.coins = coin_mocks
    return report


@pytest.fixture()
def app(env_setup):
    from src.api.main_router import create_app

    return create_app()


@pytest.fixture()
async def client(app) -> AsyncGenerator[AsyncClient, None]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest.fixture()
def admin_app(app):
    """配置管理员鉴权的应用。"""
    admin_user = _make_admin_user()
    app.dependency_overrides[require_admin_or_api_key] = lambda: admin_user
    yield app
    app.dependency_overrides.clear()


@pytest.fixture()
def normal_user_app(app):
    """配置普通用户鉴权的应用。"""
    from src.core.exceptions import PermissionError as AppPermissionError

    app.dependency_overrides[require_admin_or_api_key] = lambda: (_ for _ in ()).throw(AppPermissionError("权限不足"))
    yield app
    app.dependency_overrides.clear()


@pytest.fixture()
async def admin_client(admin_app) -> AsyncGenerator[AsyncClient, None]:
    async with AsyncClient(transport=ASGITransport(app=admin_app), base_url="http://test") as ac:
        yield ac


@pytest.fixture()
async def normal_client(normal_user_app) -> AsyncGenerator[AsyncClient, None]:
    async with AsyncClient(transport=ASGITransport(app=normal_user_app), base_url="http://test") as ac:
        yield ac


# ─────────────────────────────────────────────
# POST /api/v1/admin/reports
# ─────────────────────────────────────────────


class TestCreateReport:
    """POST /api/v1/admin/reports 创建研报测试。"""

    @pytest.mark.asyncio
    async def test_admin_can_create_report(self, admin_app, admin_client: AsyncClient) -> None:
        """管理员可以创建研报。"""
        mock_db = AsyncMock()

        # Mock flush 给 report 分配 id
        async def mock_flush():
            pass

        mock_db.flush = mock_flush
        mock_db.add = MagicMock()
        mock_db.commit = AsyncMock()

        report = _make_mock_report(id=1, title="新研报", summary="新摘要", content="新内容", coins=["BTC"])
        mock_db.refresh = AsyncMock(return_value=None)

        async def override_get_db():
            yield mock_db

        admin_app.dependency_overrides[get_db] = override_get_db

        with (
            patch("src.api.admin_reports.ResearchReport") as mock_report_cls,
            patch("src.api.admin_reports.ReportCoin"),
        ):
            mock_instance = report
            mock_report_cls.return_value = mock_instance
            mock_instance.id = 1

            response = await admin_client.post(
                "/api/v1/admin/reports",
                json={
                    "title": "新研报",
                    "summary": "新摘要",
                    "content": "新内容",
                    "related_coins": ["BTC"],
                },
            )

        assert response.status_code == 200
        body = response.json()
        assert body["code"] == 0

    @pytest.mark.asyncio
    async def test_normal_user_cannot_create_report(self, normal_client: AsyncClient) -> None:
        """普通用户创建研报返回 403。"""
        response = await normal_client.post(
            "/api/v1/admin/reports",
            json={
                "title": "测试",
                "summary": "测试",
                "content": "测试",
                "related_coins": [],
            },
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_anonymous_cannot_create_report(self, client: AsyncClient) -> None:
        """未登录用户创建研报返回 401。"""
        response = await client.post(
            "/api/v1/admin/reports",
            json={
                "title": "测试",
                "summary": "测试",
                "content": "测试",
                "related_coins": [],
            },
        )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_create_report_missing_title_returns_422(self, admin_client: AsyncClient) -> None:
        """缺少 title 字段返回 422。"""
        response = await admin_client.post(
            "/api/v1/admin/reports",
            json={
                "summary": "测试",
                "content": "测试",
            },
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_create_report_missing_content_returns_422(self, admin_client: AsyncClient) -> None:
        """缺少 content 字段返回 422。"""
        response = await admin_client.post(
            "/api/v1/admin/reports",
            json={
                "title": "测试",
                "summary": "测试",
            },
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_create_report_with_empty_coins(self, admin_app, admin_client: AsyncClient) -> None:
        """创建研报时 related_coins 为空列表是合法的。"""
        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        mock_db.commit = AsyncMock()

        report = _make_mock_report(id=2, coins=[])
        mock_db.refresh = AsyncMock(return_value=None)

        async def override_get_db():
            yield mock_db

        admin_app.dependency_overrides[get_db] = override_get_db

        with (
            patch("src.api.admin_reports.ResearchReport") as mock_report_cls,
            patch("src.api.admin_reports.ReportCoin"),
        ):
            mock_report_cls.return_value = report
            report.id = 2

            response = await admin_client.post(
                "/api/v1/admin/reports",
                json={
                    "title": "无币种研报",
                    "summary": "摘要",
                    "content": "内容",
                    "related_coins": [],
                },
            )

        assert response.status_code == 200


# ─────────────────────────────────────────────
# PUT /api/v1/admin/reports/{id}
# ─────────────────────────────────────────────


class TestUpdateReport:
    """PUT /api/v1/admin/reports/{id} 更新研报测试。"""

    @pytest.mark.asyncio
    async def test_admin_can_update_report(self, admin_app, admin_client: AsyncClient) -> None:
        """管理员可以更新研报。"""
        mock_db = AsyncMock()
        report = _make_mock_report(id=1)

        # Mock execute 返回查询结果
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = report
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock(return_value=None)

        async def override_get_db():
            yield mock_db

        admin_app.dependency_overrides[get_db] = override_get_db

        response = await admin_client.put(
            "/api/v1/admin/reports/1",
            json={"title": "更新后的标题"},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["code"] == 0

    @pytest.mark.asyncio
    async def test_update_nonexistent_report_returns_404(self, admin_app, admin_client: AsyncClient) -> None:
        """更新不存在的研报返回 404。"""
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        async def override_get_db():
            yield mock_db

        admin_app.dependency_overrides[get_db] = override_get_db

        response = await admin_client.put(
            "/api/v1/admin/reports/999",
            json={"title": "不存在"},
        )

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_normal_user_cannot_update_report(self, normal_client: AsyncClient) -> None:
        """普通用户更新研报返回 403。"""
        response = await normal_client.put(
            "/api/v1/admin/reports/1",
            json={"title": "更新"},
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_update_partial_fields(self, admin_app, admin_client: AsyncClient) -> None:
        """只更新部分字段，其余保持不变。"""
        mock_db = AsyncMock()
        report = _make_mock_report(id=1, title="原标题", summary="原摘要")

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = report
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock(return_value=None)

        async def override_get_db():
            yield mock_db

        admin_app.dependency_overrides[get_db] = override_get_db

        response = await admin_client.put(
            "/api/v1/admin/reports/1",
            json={"summary": "新摘要"},
        )

        assert response.status_code == 200
        # title 应该保持不变
        assert report.title == "原标题"


# ─────────────────────────────────────────────
# DELETE /api/v1/admin/reports/{id}
# ─────────────────────────────────────────────


class TestDeleteReport:
    """DELETE /api/v1/admin/reports/{id} 删除研报测试。"""

    @pytest.mark.asyncio
    async def test_admin_can_delete_report(self, admin_app, admin_client: AsyncClient) -> None:
        """管理员可以删除研报。"""
        mock_db = AsyncMock()
        report = _make_mock_report(id=1)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = report
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.delete = AsyncMock()
        mock_db.commit = AsyncMock()

        async def override_get_db():
            yield mock_db

        admin_app.dependency_overrides[get_db] = override_get_db

        response = await admin_client.delete("/api/v1/admin/reports/1")

        assert response.status_code == 200
        body = response.json()
        assert body["code"] == 0
        assert body["data"]["id"] == 1
        assert body["data"]["deleted"] is True

    @pytest.mark.asyncio
    async def test_delete_nonexistent_report_returns_404(self, admin_app, admin_client: AsyncClient) -> None:
        """删除不存在的研报返回 404。"""
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        async def override_get_db():
            yield mock_db

        admin_app.dependency_overrides[get_db] = override_get_db

        response = await admin_client.delete("/api/v1/admin/reports/999")

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_normal_user_cannot_delete_report(self, normal_client: AsyncClient) -> None:
        """普通用户删除研报返回 403。"""
        response = await normal_client.delete("/api/v1/admin/reports/1")
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_anonymous_cannot_delete_report(self, client: AsyncClient) -> None:
        """未登录用户删除研报返回 401。"""
        response = await client.delete("/api/v1/admin/reports/1")
        assert response.status_code == 401
