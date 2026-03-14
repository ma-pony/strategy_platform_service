"""管理员回测 API 集成测试（任务 11.1）。

验证：
  - POST /api/v1/admin/backtests：管理员提交，非管理员403，策略不存在422
  - GET /api/v1/admin/backtests/{task_id}：正常返回，404
  - GET /api/v1/admin/backtests：分页和筛选
"""

import datetime
from collections.abc import AsyncGenerator
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from src.core.deps import get_current_user, require_admin
from src.core.enums import TaskStatus

TEST_SECRET = "test-secret-key-for-admin-backtest-api-256bits-long!!"


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
        id=1, username="admin", membership="free", is_active=True, is_admin=True,
    )


def _make_normal_user():
    return SimpleNamespace(
        id=2, username="user", membership="free", is_active=True, is_admin=False,
    )


def _make_mock_task(
    id: int = 1,
    strategy_id: int = 1,
    status: TaskStatus = TaskStatus.PENDING,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=id,
        strategy_id=strategy_id,
        scheduled_date=datetime.date.today(),
        status=status,
        timerange="20240101-20240301",
        result_json=None,
        error_message=None,
        created_at=datetime.datetime.now(tz=datetime.timezone.utc),
        updated_at=datetime.datetime.now(tz=datetime.timezone.utc),
    )


@pytest.fixture()
def app(env_setup):
    from src.api.main_router import create_app
    return create_app()


@pytest.fixture()
def admin_app(app):
    """App with admin user dependency override."""
    admin_user = _make_admin_user()
    app.dependency_overrides[get_current_user] = lambda: admin_user
    app.dependency_overrides[require_admin] = lambda: admin_user
    yield app
    app.dependency_overrides.clear()


@pytest.fixture()
def non_admin_app(app):
    """App with non-admin user dependency override."""
    normal_user = _make_normal_user()
    app.dependency_overrides[get_current_user] = lambda: normal_user
    yield app
    app.dependency_overrides.clear()


@pytest.fixture()
async def admin_client(admin_app) -> AsyncGenerator[AsyncClient, None]:
    async with AsyncClient(
        transport=ASGITransport(app=admin_app), base_url="http://test"
    ) as ac:
        yield ac


@pytest.fixture()
async def non_admin_client(non_admin_app) -> AsyncGenerator[AsyncClient, None]:
    async with AsyncClient(
        transport=ASGITransport(app=non_admin_app), base_url="http://test"
    ) as ac:
        yield ac


class TestAdminBacktestSubmit:
    """POST /api/v1/admin/backtests 测试。"""

    @pytest.mark.asyncio
    async def test_non_admin_returns_403(self, non_admin_client: AsyncClient) -> None:
        """非管理员用户应返回 403 + code:1002。"""
        resp = await non_admin_client.post(
            "/api/v1/admin/backtests",
            json={"strategy_id": 1, "timerange": "20240101-20240301"},
        )
        assert resp.status_code == 403
        assert resp.json()["code"] == 1002

    @pytest.mark.asyncio
    async def test_admin_submit_success(self, admin_client: AsyncClient) -> None:
        """管理员提交有效请求应返回 200 + task_id。"""
        mock_task = _make_mock_task()

        with patch(
            "src.services.admin_backtest_service.AdminBacktestService.submit_backtest",
            new_callable=AsyncMock,
            return_value=mock_task,
        ):
            resp = await admin_client.post(
                "/api/v1/admin/backtests",
                json={"strategy_id": 1, "timerange": "20240101-20240301"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        assert data["data"]["id"] == 1
        assert data["data"]["status"] == "pending"

    @pytest.mark.asyncio
    async def test_unsupported_strategy_returns_422(self, admin_client: AsyncClient) -> None:
        """策略不在注册表应返回 422 + code:3003。"""
        from src.core.exceptions import UnsupportedStrategyError

        with patch(
            "src.services.admin_backtest_service.AdminBacktestService.submit_backtest",
            new_callable=AsyncMock,
            side_effect=UnsupportedStrategyError("不支持"),
        ):
            resp = await admin_client.post(
                "/api/v1/admin/backtests",
                json={"strategy_id": 999, "timerange": "20240101-20240301"},
            )

        assert resp.status_code == 422
        assert resp.json()["code"] == 3003

    @pytest.mark.asyncio
    async def test_duplicate_submit_returns_200(self, admin_client: AsyncClient) -> None:
        """同策略重复提交应返回 200（不返回 409）。"""
        mock_task = _make_mock_task(id=2)

        with patch(
            "src.services.admin_backtest_service.AdminBacktestService.submit_backtest",
            new_callable=AsyncMock,
            return_value=mock_task,
        ):
            resp = await admin_client.post(
                "/api/v1/admin/backtests",
                json={"strategy_id": 1, "timerange": "20240101-20240301"},
            )

        assert resp.status_code == 200
        assert resp.json()["code"] == 0


class TestAdminBacktestGet:
    """GET /api/v1/admin/backtests/{task_id} 测试。"""

    @pytest.mark.asyncio
    async def test_get_task_success(self, admin_client: AsyncClient) -> None:
        """正常返回任务详情。"""
        mock_task = _make_mock_task()

        with patch(
            "src.services.admin_backtest_service.AdminBacktestService.get_task",
            new_callable=AsyncMock,
            return_value=mock_task,
        ):
            resp = await admin_client.get("/api/v1/admin/backtests/1")

        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        assert data["data"]["id"] == 1

    @pytest.mark.asyncio
    async def test_get_task_not_found(self, admin_client: AsyncClient) -> None:
        """task_id 不存在应返回 404 + code:3001。"""
        from src.core.exceptions import NotFoundError

        with patch(
            "src.services.admin_backtest_service.AdminBacktestService.get_task",
            new_callable=AsyncMock,
            side_effect=NotFoundError("不存在"),
        ):
            resp = await admin_client.get("/api/v1/admin/backtests/999")

        assert resp.status_code == 404
        assert resp.json()["code"] == 3001


class TestAdminBacktestList:
    """GET /api/v1/admin/backtests 测试。"""

    @pytest.mark.asyncio
    async def test_list_tasks_with_pagination(self, admin_client: AsyncClient) -> None:
        """分页查询应正常返回。"""
        mock_tasks = [_make_mock_task(id=i) for i in range(1, 4)]

        with patch(
            "src.services.admin_backtest_service.AdminBacktestService.list_tasks",
            new_callable=AsyncMock,
            return_value=(mock_tasks, 3),
        ):
            resp = await admin_client.get(
                "/api/v1/admin/backtests",
                params={"page": 1, "page_size": 10},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        assert data["data"]["total"] == 3
        assert len(data["data"]["items"]) == 3
