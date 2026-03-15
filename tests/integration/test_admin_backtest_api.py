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


# ─────────────────────────────────────────────────────────────────────────────
# 任务 5.1：新增权限与状态测试用例（需求 3.1, 3.2, 3.5, 3.6, 3.7）
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture()
async def bare_client(app) -> AsyncGenerator[AsyncClient, None]:
    """未覆盖任何认证依赖的原始客户端（用于测试匿名访问）。"""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac


class TestAdminBacktestTask5:
    """任务 5.1 新增测试用例：权限控制、冲突、Not Found 及状态查询。"""

    @pytest.mark.asyncio
    async def test_admin_submit_returns_task_id_and_pending_status(
        self, admin_client: AsyncClient
    ) -> None:
        """管理员提交回测 → mock 返回 PENDING 任务 → 响应包含 task_id 和 status:pending。

        注：当前路由返回 HTTP 200（非 202），此为已知行为差异，记录于设计文档。
        需求 3.1 要求 task_id 和初始状态 PENDING，均通过此用例验证。
        """
        mock_task = _make_mock_task(id=42, status=TaskStatus.PENDING)

        with patch(
            "src.services.admin_backtest_service.AdminBacktestService.submit_backtest",
            new_callable=AsyncMock,
            return_value=mock_task,
        ):
            resp = await admin_client.post(
                "/api/v1/admin/backtests",
                json={"strategy_id": 1, "timerange": "20240101-20240301"},
            )

        assert resp.status_code == 200  # 当前路由实际返回 200
        body = resp.json()
        assert body["code"] == 0
        assert body["data"]["id"] == 42
        assert body["data"]["status"] == "pending"

    @pytest.mark.asyncio
    async def test_anonymous_user_returns_401_on_backtest_submit(
        self, bare_client: AsyncClient
    ) -> None:
        """匿名用户（无 Authorization header）提交回测 → HTTP 401 + code:1001。

        需求 3.6：匿名用户调用回测接口，系统返回业务错误码 1001，拒绝创建任务。
        """
        resp = await bare_client.post(
            "/api/v1/admin/backtests",
            json={"strategy_id": 1, "timerange": "20240101-20240301"},
        )

        assert resp.status_code == 401
        body = resp.json()
        assert body["code"] == 1001

    @pytest.mark.asyncio
    async def test_running_task_conflict_returns_409_with_code_3002(
        self, admin_client: AsyncClient
    ) -> None:
        """重复提交 RUNNING 任务 → mock 抛出 ConflictError → HTTP 409 + code:3002。

        需求 3.5：已有任务处于 RUNNING 状态时，返回业务错误码 3002（回测任务冲突）。
        """
        from src.core.exceptions import ConflictError

        with patch(
            "src.services.admin_backtest_service.AdminBacktestService.submit_backtest",
            new_callable=AsyncMock,
            side_effect=ConflictError("已有 RUNNING 任务，禁止重复提交"),
        ):
            resp = await admin_client.post(
                "/api/v1/admin/backtests",
                json={"strategy_id": 1, "timerange": "20240101-20240301"},
            )

        assert resp.status_code == 409
        body = resp.json()
        assert body["code"] == 3002

    @pytest.mark.asyncio
    async def test_strategy_not_found_returns_404_with_code_3001(
        self, admin_client: AsyncClient
    ) -> None:
        """策略不存在 → mock 抛出 NotFoundError → HTTP 404 + code:3001。

        需求 3.1 错误路径：提交指向不存在策略的回测时，返回 3001。
        """
        from src.core.exceptions import NotFoundError

        with patch(
            "src.services.admin_backtest_service.AdminBacktestService.submit_backtest",
            new_callable=AsyncMock,
            side_effect=NotFoundError("策略 9999 不存在"),
        ):
            resp = await admin_client.post(
                "/api/v1/admin/backtests",
                json={"strategy_id": 9999, "timerange": "20240101-20240301"},
            )

        assert resp.status_code == 404
        body = resp.json()
        assert body["code"] == 3001

    @pytest.mark.asyncio
    async def test_running_status_query_returns_no_result_data(
        self, admin_client: AsyncClient
    ) -> None:
        """RUNNING 状态任务查询 → 响应不含结果数据（result_summary 为 None）。

        需求 3.2：任务处于 RUNNING 状态时，查询接口返回当前状态且不包含结果数据。
        """
        mock_task = _make_mock_task(id=10, status=TaskStatus.RUNNING)
        # 确保 result_json 为 None（无结果数据）
        mock_task.result_json = None

        with patch(
            "src.services.admin_backtest_service.AdminBacktestService.get_task",
            new_callable=AsyncMock,
            return_value=mock_task,
        ):
            resp = await admin_client.get("/api/v1/admin/backtests/10")

        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["data"]["status"] == "running"
        assert body["data"]["result_summary"] is None
