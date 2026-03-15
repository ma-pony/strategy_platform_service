"""真实数据库 API 集成测试。

使用真实 PostgreSQL 数据库（TEST_DATABASE_URL），无 mock，全栈测试：
  HTTP 请求 → FastAPI → Service → SQLAlchemy → PostgreSQL → Response

覆盖：
  - 认证流程：注册 → 登录 → token 刷新 → 被禁用用户
  - 策略 API：列表分页、详情、不存在 404
  - 信号 API：策略不存在 404、真实信号数据返回、VIP 权限过滤
  - 回测 API：策略不存在返回空列表、回测不存在 404
  - 参数校验：密码过短 422、page 参数边界
"""

import datetime
import os

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from src.core.enums import MembershipTier, SignalDirection, TaskStatus
from src.models.backtest import BacktestResult, BacktestTask
from src.models.signal import TradingSignal
from src.models.strategy import Strategy
from src.models.user import User

# 测试结束后 TRUNCATE 的业务表
_TABLES_TO_TRUNCATE = (
    "backtest_results",
    "backtest_tasks",
    "trading_signals",
    "report_coins",
    "research_reports",
    "strategies",
    "users",
)


# ─── Fixtures ──────────────────────────────────────────────────────────────────


_DEFAULT_TEST_DB_URL = "postgresql+asyncpg://postgres:123456@localhost:5432/strategy_platform_test"


def _get_test_db_url() -> str:
    return os.environ.get("TEST_DATABASE_URL", "").strip() or _DEFAULT_TEST_DB_URL


@pytest.fixture()
def env_setup(monkeypatch: pytest.MonkeyPatch):
    """设置测试所需环境变量并清除 settings 缓存。"""
    test_url = _get_test_db_url()
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-real-db-integration-256b!!")
    monkeypatch.setenv("DATABASE_URL", test_url)
    sync_url = test_url.replace("postgresql+asyncpg://", "postgresql+psycopg2://", 1)
    monkeypatch.setenv("DATABASE_SYNC_URL", sync_url)
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")

    from src.core import app_settings

    app_settings.get_settings.cache_clear()
    yield
    app_settings.get_settings.cache_clear()


def _run_alembic(direction: str = "upgrade") -> None:
    """同步执行 Alembic 迁移。"""
    from pathlib import Path

    from alembic import command
    from alembic.config import Config

    project_root = Path(__file__).parent.parent.parent
    alembic_cfg = Config(str(project_root / "alembic.ini"))

    async_url = _get_test_db_url()
    sync_url = async_url.replace("postgresql+asyncpg://", "postgresql+psycopg2://", 1)
    alembic_cfg.set_main_option("sqlalchemy.url", sync_url)
    alembic_cfg.set_main_option("script_location", str(project_root / "migrations"))

    if direction == "upgrade":
        command.upgrade(alembic_cfg, "head")
    else:
        command.downgrade(alembic_cfg, "base")


@pytest.fixture()
async def db_engine() -> AsyncEngine:
    """Function 作用域的异步引擎，在当前 event loop 中创建。"""
    url = _get_test_db_url()

    # 确保 Schema 存在（同步 Alembic）
    try:
        _run_alembic("upgrade")
    except Exception as exc:
        pytest.skip(f"Alembic 迁移失败: {exc}")

    engine = create_async_engine(url, echo=False, pool_pre_ping=True, pool_size=5)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as exc:
        await engine.dispose()
        pytest.skip(f"无法连接测试数据库: {exc}")

    yield engine
    await engine.dispose()


@pytest.fixture()
async def db_session(db_engine: AsyncEngine) -> AsyncSession:
    """Function 作用域的 async session，测试结束后 TRUNCATE。"""
    factory = async_sessionmaker(db_engine, expire_on_commit=False, autoflush=False)
    async with factory() as session:
        yield session

    # TRUNCATE 所有业务表
    async with factory() as cleanup:
        async with cleanup.begin():
            for table in _TABLES_TO_TRUNCATE:
                await cleanup.execute(text(f"TRUNCATE TABLE {table} RESTART IDENTITY CASCADE"))


@pytest.fixture()
def app(env_setup):
    """创建 FastAPI 应用实例。"""
    from src.api.main_router import create_app

    return create_app()


@pytest.fixture()
async def client(app, db_session: AsyncSession) -> AsyncClient:
    """使用真实数据库 session 的 HTTP 测试客户端。"""
    from src.core.deps import get_db

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


# ─── Helpers ───────────────────────────────────────────────────────────────────


async def _create_user(
    db: AsyncSession,
    email: str = "test@example.com",
    password: str = "testpass123",
    membership: MembershipTier = MembershipTier.FREE,
    is_active: bool = True,
) -> User:
    """在真实数据库中创建用户。"""
    from src.core.security import SecurityUtils

    security = SecurityUtils()
    user = User(
        email=email,
        hashed_password=security.hash_password(password),
        membership=membership,
        is_active=is_active,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def _create_strategy(
    db: AsyncSession,
    name: str = "TestStrategy",
    strategy_type: str = "technical",
    pairs: list | None = None,
) -> Strategy:
    """在真实数据库中创建策略。"""
    strategy = Strategy(
        name=name,
        description=f"Test strategy {name}",
        strategy_type=strategy_type,
        pairs=pairs or ["BTC/USDT"],
    )
    db.add(strategy)
    await db.commit()
    await db.refresh(strategy)
    return strategy


async def _create_signal(
    db: AsyncSession,
    strategy_id: int,
    pair: str = "BTC/USDT",
    direction: SignalDirection = SignalDirection.BUY,
    confidence_score: float = 0.85,
    signal_at: datetime.datetime | None = None,
) -> TradingSignal:
    """在真实数据库中创建交易信号。"""
    signal = TradingSignal(
        strategy_id=strategy_id,
        pair=pair,
        direction=direction,
        confidence_score=confidence_score,
        signal_source="realtime",
        entry_price=30000.0,
        stop_loss=29000.0,
        take_profit=32000.0,
        signal_strength=0.75,
        volume=1000.0,
        volatility=0.03,
        timeframe="1h",
        indicator_values={"rsi": 45.0},
        signal_at=signal_at or datetime.datetime.now(tz=datetime.timezone.utc),
    )
    db.add(signal)
    await db.commit()
    await db.refresh(signal)
    return signal


async def _login_and_get_token(client: AsyncClient, email: str, password: str) -> str:
    """登录并返回 access_token。"""
    resp = await client.post(
        "/api/v1/auth/login",
        json={
            "email": email,
            "password": password,
        },
    )
    assert resp.status_code == 200, f"login failed: {resp.json()}"
    return resp.json()["data"]["access_token"]


# ─── Auth API Tests ────────────────────────────────────────────────────────────


class TestAuthRegisterRealDB:
    """注册 API 真实数据库集成测试。"""

    @pytest.mark.asyncio
    async def test_register_success(self, client: AsyncClient, db_session: AsyncSession) -> None:
        """注册成功返回用户信息，membership 默认 FREE。"""
        resp = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "newuser@example.com",
                "password": "strongpass123",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        assert data["data"]["email"] == "newuser@example.com"
        assert data["data"]["membership"] == "free"

    @pytest.mark.asyncio
    async def test_register_duplicate_email(self, client: AsyncClient, db_session: AsyncSession) -> None:
        """重复邮箱返回 code:3010 HTTP 409。"""
        await _create_user(db_session, email="existing@example.com")
        resp = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "existing@example.com",
                "password": "strongpass123",
            },
        )
        assert resp.status_code == 409
        assert resp.json()["code"] == 3010

    @pytest.mark.asyncio
    async def test_register_short_password_422(self, client: AsyncClient) -> None:
        """密码过短返回 422 参数校验错误。"""
        resp = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "shortpw@example.com",
                "password": "1234567",  # min_length=8
            },
        )
        assert resp.status_code == 422
        assert resp.json()["code"] == 2001


class TestAuthLoginRealDB:
    """登录 API 真实数据库集成测试。"""

    @pytest.mark.asyncio
    async def test_login_success(self, client: AsyncClient, db_session: AsyncSession) -> None:
        """正确凭证登录成功，返回 token 对。"""
        await _create_user(db_session, email="loginuser@example.com", password="testpass123")
        resp = await client.post(
            "/api/v1/auth/login",
            json={
                "email": "loginuser@example.com",
                "password": "testpass123",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        assert "access_token" in data["data"]
        assert "refresh_token" in data["data"]
        assert data["data"]["token_type"] == "bearer"

    @pytest.mark.asyncio
    async def test_login_wrong_password(self, client: AsyncClient, db_session: AsyncSession) -> None:
        """密码错误返回 code:1004 HTTP 401。"""
        await _create_user(db_session, email="wrongpw@example.com", password="correctpass")
        resp = await client.post(
            "/api/v1/auth/login",
            json={
                "email": "wrongpw@example.com",
                "password": "wrongpass",
            },
        )
        assert resp.status_code == 401
        assert resp.json()["code"] == 1004

    @pytest.mark.asyncio
    async def test_login_nonexistent_user(self, client: AsyncClient) -> None:
        """用户不存在返回 code:1004（不泄露是否存在）。"""
        resp = await client.post(
            "/api/v1/auth/login",
            json={
                "email": "ghost@example.com",
                "password": "anypass12345",
            },
        )
        assert resp.status_code == 401
        assert resp.json()["code"] == 1004

    @pytest.mark.asyncio
    async def test_login_inactive_user(self, client: AsyncClient, db_session: AsyncSession) -> None:
        """被禁用用户登录返回 code:1005 HTTP 403。"""
        await _create_user(db_session, email="banned@example.com", password="testpass123", is_active=False)
        resp = await client.post(
            "/api/v1/auth/login",
            json={
                "email": "banned@example.com",
                "password": "testpass123",
            },
        )
        assert resp.status_code == 403
        assert resp.json()["code"] == 1005


class TestAuthRefreshRealDB:
    """Token 刷新 API 真实数据库集成测试。"""

    @pytest.mark.asyncio
    async def test_refresh_success(self, client: AsyncClient, db_session: AsyncSession) -> None:
        """有效 refresh_token 返回新 access_token。"""
        await _create_user(db_session, email="refreshuser@example.com", password="testpass123")
        login_resp = await client.post(
            "/api/v1/auth/login",
            json={
                "email": "refreshuser@example.com",
                "password": "testpass123",
            },
        )
        refresh_token = login_resp.json()["data"]["refresh_token"]

        resp = await client.post(
            "/api/v1/auth/refresh",
            json={
                "refresh_token": refresh_token,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        assert "access_token" in data["data"]

    @pytest.mark.asyncio
    async def test_refresh_invalid_token(self, client: AsyncClient) -> None:
        """无效 token 返回 code:1001。"""
        resp = await client.post(
            "/api/v1/auth/refresh",
            json={
                "refresh_token": "invalid.token.here",
            },
        )
        assert resp.status_code == 401
        assert resp.json()["code"] == 1001

    @pytest.mark.asyncio
    async def test_refresh_with_access_token_fails(self, client: AsyncClient, db_session: AsyncSession) -> None:
        """用 access_token 做 refresh 应失败（type 不匹配）。"""
        await _create_user(db_session, email="typecheck@example.com", password="testpass123")
        login_resp = await client.post(
            "/api/v1/auth/login",
            json={
                "email": "typecheck@example.com",
                "password": "testpass123",
            },
        )
        access_token = login_resp.json()["data"]["access_token"]

        resp = await client.post(
            "/api/v1/auth/refresh",
            json={
                "refresh_token": access_token,
            },
        )
        assert resp.status_code == 401
        assert resp.json()["code"] == 1001

    @pytest.mark.asyncio
    async def test_refresh_inactive_user(self, client: AsyncClient, db_session: AsyncSession) -> None:
        """用户登录后被禁用，refresh 应失败。"""
        user = await _create_user(db_session, email="willban@example.com", password="testpass123")
        login_resp = await client.post(
            "/api/v1/auth/login",
            json={
                "email": "willban@example.com",
                "password": "testpass123",
            },
        )
        refresh_token = login_resp.json()["data"]["refresh_token"]

        # 禁用用户
        user.is_active = False
        await db_session.commit()

        resp = await client.post(
            "/api/v1/auth/refresh",
            json={
                "refresh_token": refresh_token,
            },
        )
        assert resp.status_code == 401
        assert resp.json()["code"] == 1001


# ─── Strategy API Tests ───────────────────────────────────────────────────────


class TestStrategyListRealDB:
    """策略列表 API 真实数据库集成测试。"""

    @pytest.mark.asyncio
    async def test_list_empty(self, client: AsyncClient) -> None:
        """无策略时返回空列表和 total=0。"""
        resp = await client.get("/api/v1/strategies")
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        assert data["data"]["items"] == []
        assert data["data"]["total"] == 0

    @pytest.mark.asyncio
    async def test_list_with_strategies(self, client: AsyncClient, db_session: AsyncSession) -> None:
        """有策略时正确返回列表和 total。"""
        await _create_strategy(db_session, name="StratA")
        await _create_strategy(db_session, name="StratB")

        resp = await client.get("/api/v1/strategies")
        assert resp.status_code == 200
        data = resp.json()
        assert data["data"]["total"] == 2
        assert len(data["data"]["items"]) == 2

    @pytest.mark.asyncio
    async def test_list_pagination(self, client: AsyncClient, db_session: AsyncSession) -> None:
        """分页参数正确裁剪结果。"""
        for i in range(5):
            await _create_strategy(db_session, name=f"PagStrat{i}")

        resp = await client.get("/api/v1/strategies?page=1&page_size=2")
        data = resp.json()["data"]
        assert data["total"] == 5
        assert len(data["items"]) == 2
        assert data["page"] == 1
        assert data["page_size"] == 2

        resp2 = await client.get("/api/v1/strategies?page=3&page_size=2")
        data2 = resp2.json()["data"]
        assert len(data2["items"]) == 1  # 第 3 页只有 1 条

    @pytest.mark.asyncio
    async def test_list_anonymous_hides_vip_fields(self, client: AsyncClient, db_session: AsyncSession) -> None:
        """匿名用户看不到 VIP 字段（sharpe_ratio, win_rate 为 null）。"""
        strategy = await _create_strategy(db_session, name="VipStrat")
        strategy.sharpe_ratio = 1.5
        strategy.win_rate = 0.65
        strategy.trade_count = 100
        await db_session.commit()

        resp = await client.get("/api/v1/strategies")
        item = resp.json()["data"]["items"][0]
        assert item["sharpe_ratio"] is None
        assert item["win_rate"] is None
        # 匿名也看不到 Free 字段
        assert item["trade_count"] is None

    @pytest.mark.asyncio
    async def test_list_free_user_sees_free_fields(self, client: AsyncClient, db_session: AsyncSession) -> None:
        """Free 用户可见 trade_count, max_drawdown；不可见 sharpe_ratio, win_rate。"""
        await _create_user(
            db_session,
            email="freeuser@example.com",
            password="testpass123",
            membership=MembershipTier.FREE,
        )
        strategy = await _create_strategy(db_session, name="FreeStrat")
        strategy.trade_count = 50
        strategy.max_drawdown = 0.1
        strategy.sharpe_ratio = 2.0
        strategy.win_rate = 0.7
        await db_session.commit()

        token = await _login_and_get_token(client, "freeuser@example.com", "testpass123")
        resp = await client.get(
            "/api/v1/strategies",
            headers={"Authorization": f"Bearer {token}"},
        )
        item = resp.json()["data"]["items"][0]
        assert item["trade_count"] == 50
        assert item["max_drawdown"] == pytest.approx(0.1)
        assert item["sharpe_ratio"] is None
        assert item["win_rate"] is None

    @pytest.mark.asyncio
    async def test_list_vip1_user_sees_all_fields(self, client: AsyncClient, db_session: AsyncSession) -> None:
        """VIP1 用户可见全部字段。"""
        await _create_user(
            db_session,
            email="vip1user@example.com",
            password="testpass123",
            membership=MembershipTier.VIP1,
        )
        strategy = await _create_strategy(db_session, name="VipAllStrat")
        strategy.trade_count = 200
        strategy.sharpe_ratio = 1.8
        strategy.win_rate = 0.72
        await db_session.commit()

        token = await _login_and_get_token(client, "vip1user@example.com", "testpass123")
        resp = await client.get(
            "/api/v1/strategies",
            headers={"Authorization": f"Bearer {token}"},
        )
        item = resp.json()["data"]["items"][0]
        assert item["trade_count"] == 200
        assert item["sharpe_ratio"] == pytest.approx(1.8)
        assert item["win_rate"] == pytest.approx(0.72)


class TestStrategyDetailRealDB:
    """策略详情 API 真实数据库集成测试。"""

    @pytest.mark.asyncio
    async def test_get_existing_strategy(self, client: AsyncClient, db_session: AsyncSession) -> None:
        """存在的策略返回正确详情。"""
        strategy = await _create_strategy(db_session, name="DetailStrat")
        resp = await client.get(f"/api/v1/strategies/{strategy.id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        assert data["data"]["name"] == "DetailStrat"

    @pytest.mark.asyncio
    async def test_get_nonexistent_strategy_404(self, client: AsyncClient) -> None:
        """策略不存在返回 code:3001 HTTP 404。"""
        resp = await client.get("/api/v1/strategies/99999")
        assert resp.status_code == 404
        assert resp.json()["code"] == 3001


# ─── Signal API Tests ─────────────────────────────────────────────────────────


class TestSignalApiRealDB:
    """信号 API 真实数据库集成测试。"""

    @pytest.mark.asyncio
    async def test_signals_strategy_not_found(self, client: AsyncClient) -> None:
        """策略不存在返回 code:3001 HTTP 404。"""
        resp = await client.get("/api/v1/strategies/99999/signals")
        assert resp.status_code == 404
        assert resp.json()["code"] == 3001

    @pytest.mark.asyncio
    async def test_signals_empty_for_strategy(self, client: AsyncClient, db_session: AsyncSession) -> None:
        """策略存在但无信号时返回空 signals 列表。"""
        strategy = await _create_strategy(db_session, name="EmptySigStrat")
        resp = await client.get(f"/api/v1/strategies/{strategy.id}/signals")
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        assert data["data"]["signals"] == []

    @pytest.mark.asyncio
    async def test_signals_returns_real_data(self, client: AsyncClient, db_session: AsyncSession) -> None:
        """真实信号数据正确返回，字段完整。"""
        strategy = await _create_strategy(db_session, name="SigStrat")
        await _create_signal(
            db_session,
            strategy.id,
            pair="ETH/USDT",
            direction=SignalDirection.SELL,
            confidence_score=0.92,
        )

        resp = await client.get(f"/api/v1/strategies/{strategy.id}/signals")
        assert resp.status_code == 200
        signals = resp.json()["data"]["signals"]
        assert len(signals) == 1
        assert signals[0]["pair"] == "ETH/USDT"
        assert signals[0]["direction"] == "sell"
        # 匿名用户 confidence_score 被过滤
        assert signals[0]["confidence_score"] is None

    @pytest.mark.asyncio
    async def test_signals_vip_sees_confidence(self, client: AsyncClient, db_session: AsyncSession) -> None:
        """VIP 用户可见 confidence_score 字段。"""
        await _create_user(
            db_session,
            email="sigvip@example.com",
            password="testpass123",
            membership=MembershipTier.VIP1,
        )
        strategy = await _create_strategy(db_session, name="SigVipStrat")
        await _create_signal(db_session, strategy.id, confidence_score=0.88)

        token = await _login_and_get_token(client, "sigvip@example.com", "testpass123")
        resp = await client.get(
            f"/api/v1/strategies/{strategy.id}/signals",
            headers={"Authorization": f"Bearer {token}"},
        )
        signals = resp.json()["data"]["signals"]
        assert signals[0]["confidence_score"] == pytest.approx(0.88)

    @pytest.mark.asyncio
    async def test_signals_order_desc(self, client: AsyncClient, db_session: AsyncSession) -> None:
        """信号按 signal_at 降序返回。"""
        strategy = await _create_strategy(db_session, name="SigOrderStrat")
        now = datetime.datetime.now(tz=datetime.timezone.utc)
        await _create_signal(
            db_session,
            strategy.id,
            pair="BTC/USDT",
            signal_at=now - datetime.timedelta(hours=2),
        )
        await _create_signal(
            db_session,
            strategy.id,
            pair="ETH/USDT",
            signal_at=now,
        )

        resp = await client.get(f"/api/v1/strategies/{strategy.id}/signals")
        signals = resp.json()["data"]["signals"]
        assert len(signals) == 2
        # 最新在前
        assert signals[0]["pair"] == "ETH/USDT"
        assert signals[1]["pair"] == "BTC/USDT"

    @pytest.mark.asyncio
    async def test_signals_limit_param(self, client: AsyncClient, db_session: AsyncSession) -> None:
        """limit 参数正确限制返回数量。"""
        strategy = await _create_strategy(db_session, name="SigLimitStrat")
        now = datetime.datetime.now(tz=datetime.timezone.utc)
        for i in range(5):
            await _create_signal(
                db_session,
                strategy.id,
                signal_at=now - datetime.timedelta(hours=i),
            )

        resp = await client.get(f"/api/v1/strategies/{strategy.id}/signals?limit=2")
        signals = resp.json()["data"]["signals"]
        assert len(signals) == 2


# ─── Backtest API Tests ───────────────────────────────────────────────────────


class TestBacktestListRealDB:
    """回测列表 API 真实数据库集成测试。"""

    @pytest.mark.asyncio
    async def test_backtests_empty_for_strategy(self, client: AsyncClient, db_session: AsyncSession) -> None:
        """策略存在但无回测时返回空列表。"""
        strategy = await _create_strategy(db_session, name="NoBacktestStrat")
        resp = await client.get(f"/api/v1/strategies/{strategy.id}/backtests")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["items"] == []
        assert data["total"] == 0

    @pytest.mark.asyncio
    async def test_backtests_with_data(self, client: AsyncClient, db_session: AsyncSession) -> None:
        """回测结果正确返回，匿名用户 VIP 字段过滤。"""
        strategy = await _create_strategy(db_session, name="BacktestStrat")
        task = BacktestTask(
            strategy_id=strategy.id,
            scheduled_date=datetime.date(2025, 1, 1),
            status=TaskStatus.DONE,
        )
        db_session.add(task)
        await db_session.commit()
        await db_session.refresh(task)

        now = datetime.datetime.now(tz=datetime.timezone.utc)
        result = BacktestResult(
            strategy_id=strategy.id,
            task_id=task.id,
            total_return=0.15,
            annual_return=0.30,
            sharpe_ratio=1.8,
            max_drawdown=0.05,
            trade_count=120,
            win_rate=0.65,
            period_start=now - datetime.timedelta(days=90),
            period_end=now,
        )
        db_session.add(result)
        await db_session.commit()

        resp = await client.get(f"/api/v1/strategies/{strategy.id}/backtests")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["total"] == 1
        item = data["items"][0]
        # 匿名：VIP 字段被过滤
        assert item["sharpe_ratio"] is None
        assert item["win_rate"] is None
        assert item["annual_return"] is None
        # 匿名：Free 字段也被过滤
        assert item["total_return"] is None


class TestBacktestDetailRealDB:
    """回测详情 API 真实数据库集成测试。"""

    @pytest.mark.asyncio
    async def test_backtest_not_found(self, client: AsyncClient) -> None:
        """回测不存在返回 code:3001 HTTP 404。"""
        resp = await client.get("/api/v1/backtests/99999")
        assert resp.status_code == 404
        assert resp.json()["code"] == 3001

    @pytest.mark.asyncio
    async def test_backtest_detail_vip_sees_all(self, client: AsyncClient, db_session: AsyncSession) -> None:
        """VIP 用户可见回测全部字段。"""
        await _create_user(
            db_session,
            email="btvip@example.com",
            password="testpass123",
            membership=MembershipTier.VIP1,
        )
        strategy = await _create_strategy(db_session, name="BTDetailStrat")
        task = BacktestTask(
            strategy_id=strategy.id,
            scheduled_date=datetime.date(2025, 2, 1),
            status=TaskStatus.DONE,
        )
        db_session.add(task)
        await db_session.commit()
        await db_session.refresh(task)

        now = datetime.datetime.now(tz=datetime.timezone.utc)
        result = BacktestResult(
            strategy_id=strategy.id,
            task_id=task.id,
            total_return=0.25,
            annual_return=0.50,
            sharpe_ratio=2.1,
            max_drawdown=0.03,
            trade_count=200,
            win_rate=0.71,
            period_start=now - datetime.timedelta(days=60),
            period_end=now,
        )
        db_session.add(result)
        await db_session.commit()
        await db_session.refresh(result)

        token = await _login_and_get_token(client, "btvip@example.com", "testpass123")
        resp = await client.get(
            f"/api/v1/backtests/{result.id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["sharpe_ratio"] == pytest.approx(2.1)
        assert data["win_rate"] == pytest.approx(0.71)
        assert data["annual_return"] == pytest.approx(0.50)
        assert data["total_return"] == pytest.approx(0.25)


# ─── Auth Token on Protected Endpoints ─────────────────────────────────────────


class TestProtectedEndpointsRealDB:
    """需要认证的端点真实数据库测试。"""

    @pytest.mark.asyncio
    async def test_access_with_valid_token(self, client: AsyncClient, db_session: AsyncSession) -> None:
        """有效 token 正常访问受保护端点。"""
        await _create_user(
            db_session,
            email="authed@example.com",
            password="testpass123",
            membership=MembershipTier.VIP1,
        )
        strategy = await _create_strategy(db_session, name="AuthStrat")
        await _create_signal(db_session, strategy.id, confidence_score=0.9)

        token = await _login_and_get_token(client, "authed@example.com", "testpass123")
        resp = await client.get(
            f"/api/v1/strategies/{strategy.id}/signals",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        # VIP1 看到 confidence_score
        signals = resp.json()["data"]["signals"]
        assert signals[0]["confidence_score"] is not None

    @pytest.mark.asyncio
    async def test_disabled_user_token_rejected(self, client: AsyncClient, db_session: AsyncSession) -> None:
        """用户登录后被禁用，旧 token 在宽松鉴权接口降级为匿名。"""
        user = await _create_user(
            db_session,
            email="disabling@example.com",
            password="testpass123",
            membership=MembershipTier.VIP1,
        )
        strategy = await _create_strategy(db_session, name="DisableStrat")
        await _create_signal(db_session, strategy.id, confidence_score=0.9)

        token = await _login_and_get_token(client, "disabling@example.com", "testpass123")

        # 禁用用户
        user.is_active = False
        await db_session.commit()

        # get_optional_user 遇到 inactive 返回 None → 匿名，confidence 被过滤
        resp = await client.get(
            f"/api/v1/strategies/{strategy.id}/signals",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        signals = resp.json()["data"]["signals"]
        assert signals[0]["confidence_score"] is None  # 降级为匿名


# ─── Full Auth Flow ────────────────────────────────────────────────────────────


class TestFullAuthFlowRealDB:
    """注册 → 登录 → 访问 → 刷新 完整流程集成测试。"""

    @pytest.mark.asyncio
    async def test_full_flow(self, client: AsyncClient, db_session: AsyncSession) -> None:
        """完整认证流程：注册 → 登录 → 用 token 获取策略 → 刷新 token → 再次获取。"""
        # 1. 注册
        reg_resp = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "flowuser@example.com",
                "password": "testpass123",
            },
        )
        assert reg_resp.status_code == 200
        assert reg_resp.json()["data"]["email"] == "flowuser@example.com"

        # 2. 登录
        login_resp = await client.post(
            "/api/v1/auth/login",
            json={
                "email": "flowuser@example.com",
                "password": "testpass123",
            },
        )
        assert login_resp.status_code == 200
        tokens = login_resp.json()["data"]
        access_token = tokens["access_token"]
        refresh_token = tokens["refresh_token"]

        # 3. 用 access_token 查策略列表
        await _create_strategy(db_session, name="FlowStrat")
        list_resp = await client.get(
            "/api/v1/strategies",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert list_resp.status_code == 200
        assert list_resp.json()["data"]["total"] >= 1

        # 4. 刷新 token
        refresh_resp = await client.post(
            "/api/v1/auth/refresh",
            json={
                "refresh_token": refresh_token,
            },
        )
        assert refresh_resp.status_code == 200
        new_access = refresh_resp.json()["data"]["access_token"]

        # 5. 用新 token 访问策略详情
        items = list_resp.json()["data"]["items"]
        strat_id = items[0]["id"]
        detail_resp = await client.get(
            f"/api/v1/strategies/{strat_id}",
            headers={"Authorization": f"Bearer {new_access}"},
        )
        assert detail_resp.status_code == 200
        assert detail_resp.json()["data"]["name"] == "FlowStrat"
