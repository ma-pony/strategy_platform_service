"""freqtrade 隔离集成测试（任务 9.2）。

验证 Web 服务在 freqtrade Worker 不可用时的降级隔离行为：
  - 策略列表接口在 Worker 不可用时仍返回 HTTP 200 + code:0
  - 研报列表接口在 Worker 不可用时仍返回 HTTP 200

通过 mock Celery worker inspect 返回 None 模拟 Worker 不可用场景，
确保非回测功能（策略查询、研报读取）不受 freqtrade Worker 状态影响。

对应需求：7.4
"""

from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

TEST_SECRET = "test-secret-key-for-freqtrade-isolation-tests-256bits"


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

    return create_app()


@pytest.fixture()
async def client(app) -> AsyncGenerator[AsyncClient, None]:
    """提供绑定测试应用的异步 HTTP 客户端。"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


def _make_mock_strategy(
    id: int = 1,
    name: str = "Isolation Test Strategy",
) -> MagicMock:
    """创建 mock Strategy 对象，提供策略接口所需字段。"""
    strategy = MagicMock()
    strategy.id = id
    strategy.name = name
    strategy.description = "隔离测试用策略"
    strategy.strategy_type = "mean_reversion"
    strategy.pairs = ["BTC/USDT"]
    strategy.config_params = {}
    strategy.is_active = True
    strategy.trade_count = None
    strategy.max_drawdown = None
    strategy.sharpe_ratio = None
    strategy.win_rate = None
    strategy.created_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
    strategy.updated_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
    return strategy


def _make_mock_report(
    id: int = 1,
    title: str = "BTC 市场研报",
    summary: str = "本报告分析 BTC 近期走势。",
    content: str = "详细内容包含对 BTC 的深度分析...",
) -> MagicMock:
    """创建 mock Report 对象，提供研报接口所需字段。"""
    report = MagicMock()
    report.id = id
    report.title = title
    report.summary = summary
    report.content = content
    report.generated_at = datetime(2024, 6, 1, tzinfo=timezone.utc)
    report.report_coins = []
    return report


class TestFreqtradeWorkerIsolation:
    """验证 Web 服务与 freqtrade Worker 的故障隔离（需求 7.4）。

    当 Celery Worker 不可用（inspect 返回 None）时，
    非回测接口（策略查询、研报读取）应继续正常服务。
    """

    async def test_strategy_endpoint_returns_200_when_worker_unavailable(self, client: AsyncClient, app) -> None:
        """策略列表接口在 Worker 不可用时仍返回 HTTP 200 + code:0。

        patch Celery worker inspect 返回 None 模拟 Worker 不可用，
        验证策略接口不依赖 freqtrade Worker 状态。
        """
        from src.core.deps import get_db

        mock_strategy = _make_mock_strategy()
        mock_db_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_strategy]
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        # 模拟 Worker 不可用：Celery inspect 返回 None
        with patch(
            "celery.app.control.Inspect.active",
            return_value=None,
        ):
            with patch(
                "celery.app.control.Inspect.ping",
                return_value=None,
            ):
                app.dependency_overrides[get_db] = lambda: mock_db_session

                try:
                    response = await client.get("/api/v1/strategies")
                finally:
                    app.dependency_overrides.clear()

        assert response.status_code == 200
        body = response.json()
        assert body["code"] == 0

    async def test_report_endpoint_returns_200_when_worker_unavailable(self, client: AsyncClient, app) -> None:
        """研报列表接口在 Worker 不可用时仍返回 HTTP 200。

        patch Celery worker inspect 返回 None 模拟 Worker 不可用，
        验证研报接口不依赖 freqtrade Worker 状态。
        """
        from src.core.deps import get_db

        mock_report = _make_mock_report()
        mock_db_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_report]
        mock_result.scalar_one_or_none.return_value = None

        # 为列表查询和 count 查询分别配置返回值
        count_result = MagicMock()
        count_result.scalar_one.return_value = 1
        mock_db_session.execute = AsyncMock(side_effect=[count_result, mock_result])

        # 模拟 Worker 不可用：Celery inspect 返回 None
        with patch(
            "celery.app.control.Inspect.active",
            return_value=None,
        ):
            with patch(
                "celery.app.control.Inspect.ping",
                return_value=None,
            ):
                app.dependency_overrides[get_db] = lambda: mock_db_session

                try:
                    response = await client.get("/api/v1/reports")
                finally:
                    app.dependency_overrides.clear()

        assert response.status_code == 200

    async def test_strategy_endpoint_independent_of_freqtrade_subprocess(self, client: AsyncClient, app) -> None:
        """验证策略接口不依赖 freqtrade 子进程，即使 subprocess.run 被 patch 为失败。

        当 freqtrade 子进程调用失败时，策略读取接口不应受影响。
        """
        from src.core.deps import get_db

        mock_strategy = _make_mock_strategy(id=2, name="AnotherStrategy")
        mock_db_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_strategy]
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        # 模拟 freqtrade 子进程不可用
        with patch(
            "subprocess.run",
            side_effect=FileNotFoundError("freqtrade: command not found"),
        ):
            app.dependency_overrides[get_db] = lambda: mock_db_session

            try:
                response = await client.get("/api/v1/strategies")
            finally:
                app.dependency_overrides.clear()

        # 策略列表接口应正常返回，不受 freqtrade 进程影响
        assert response.status_code == 200
        body = response.json()
        assert body["code"] == 0
