"""参数校验与错误响应集成测试（任务 6.1）。

验证：
  - 缺少必填字段 → HTTP 422 + code:2001 + data 包含字段级校验详情
  - 类型错误字段 → HTTP 422 + code:2001
  - RequestValidationError 被转换为统一信封格式（非 FastAPI 默认 422 格式）
  - 路径参数非数字 → HTTP 422 + code:2001（非 HTTP 500）
  - 所有错误响应（401、403、404）含 code、message、data 三字段，不含 Python traceback

需求覆盖：6.1, 6.2, 6.3, 6.4, 6.5
"""

from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

TEST_SECRET = "test-secret-key-for-validation-tests-256bits-long!!"


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


class TestMissingRequiredField:
    """需求 6.1：缺少必填字段时返回 code:2001 + 字段级校验详情。"""

    @pytest.mark.asyncio
    async def test_login_missing_password_returns_422_with_code_2001(self, client: AsyncClient) -> None:
        """登录接口省略 password 字段 → HTTP 422 + code:2001 + data 为非空列表。

        验证：
          1. HTTP 状态码为 422
          2. 响应体 code 字段为 2001（统一信封格式，非 FastAPI 默认 422）
          3. data 字段为非空列表，包含字段级校验失败详情（需求 6.1）
        """
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": "testuser@example.com"},  # 缺少 password 字段
        )

        assert resp.status_code == 422
        body = resp.json()
        # 验证统一信封格式（需求 6.3）
        assert "code" in body
        assert "message" in body
        assert "data" in body
        assert body["code"] == 2001
        # data 包含字段级校验详情（非空列表）
        assert isinstance(body["data"], list)
        assert len(body["data"]) > 0


class TestWrongTypeField:
    """需求 6.2：字段类型错误时返回 code:2001 + HTTP 422。"""

    @pytest.mark.asyncio
    async def test_login_password_as_integer_returns_422_with_code_2001(self, client: AsyncClient) -> None:
        """登录接口 password 传入整型 → HTTP 422 + code:2001。

        验证：
          1. HTTP 状态码为 422
          2. code 字段为 2001（需求 6.2）
        """
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": "testuser@example.com", "password": 12345},  # password 应为字符串
        )

        assert resp.status_code == 422
        body = resp.json()
        assert body["code"] == 2001


class TestRequestValidationErrorEnvelope:
    """需求 6.3：RequestValidationError 被转换为统一信封格式（非 FastAPI 默认 422 格式）。"""

    @pytest.mark.asyncio
    async def test_validation_error_returns_unified_envelope_not_fastapi_default(self, client: AsyncClient) -> None:
        """验证 RequestValidationError 响应体为统一信封格式，而非 FastAPI 原始格式。

        FastAPI 默认 422 响应格式为 {"detail": [...]}, 本测试确认响应格式为
        {"code": 2001, "message": ..., "data": [...]}（全局异常处理器转换）。
        """
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": "testuser@example.com"},  # 缺少 password，触发 RequestValidationError
        )

        assert resp.status_code == 422
        body = resp.json()
        # 统一信封格式：必须包含 code、message、data，不含 FastAPI 默认的 "detail"
        assert "code" in body
        assert "message" in body
        assert "data" in body
        assert "detail" not in body  # 不使用 FastAPI 原始格式
        assert body["code"] == 2001


class TestNonNumericPathParam:
    """需求 6.4：路径参数包含非数字字符时返回 422（非 500）。"""

    @pytest.mark.asyncio
    async def test_non_numeric_strategy_id_returns_422_not_500(self, client: AsyncClient) -> None:
        """GET /api/v1/strategies/abc → HTTP 422 + code:2001（非 HTTP 500）。

        需求 6.4：路径参数非数字时，系统返回参数校验错误而非服务端错误。
        """
        resp = await client.get("/api/v1/strategies/abc")

        assert resp.status_code == 422
        body = resp.json()
        assert body["code"] == 2001
        # 确认不是 500 服务端错误
        assert resp.status_code != 500


class TestErrorResponseEnvelopeFormat:
    """需求 6.5：所有错误响应（4xx、5xx）符合统一信封格式，不暴露 Python traceback。"""

    @pytest.mark.asyncio
    async def test_401_response_has_unified_envelope(self, client: AsyncClient) -> None:
        """调用需要认证的接口（无 token）→ HTTP 401，响应含 code、message、data。

        需求 6.5：401 响应符合统一信封格式。
        """
        # 调用需要认证的端点（策略详情或受保护接口），不携带 token
        resp = await client.get("/api/v1/admin/backtests/1")

        assert resp.status_code == 401
        body = resp.json()
        assert "code" in body
        assert "message" in body
        assert "data" in body
        assert body["code"] == 1001
        # 确认不含 Python traceback 关键词
        body_str = str(body)
        assert "Traceback" not in body_str
        assert 'File "' not in body_str

    @pytest.mark.asyncio
    async def test_404_response_has_unified_envelope(self, client: AsyncClient, app) -> None:
        """请求不存在的策略 ID → HTTP 404，响应含 code、message、data，不含 traceback。

        需求 6.5：404 响应符合统一信封格式。
        """
        from src.core.deps import get_db
        from src.core.exceptions import NotFoundError

        mock_db = AsyncMock()

        async def override_get_db():
            yield mock_db

        with patch(
            "src.api.strategies._strategy_service.get_strategy",
            new_callable=AsyncMock,
            side_effect=NotFoundError("策略 99999 不存在"),
        ):
            app.dependency_overrides[get_db] = override_get_db
            try:
                resp = await client.get("/api/v1/strategies/99999")
            finally:
                app.dependency_overrides.clear()

        assert resp.status_code == 404
        body = resp.json()
        assert "code" in body
        assert "message" in body
        assert "data" in body
        assert body["code"] == 3001
        # 确认不含 Python traceback 关键词
        body_str = str(body)
        assert "Traceback" not in body_str
        assert 'File "' not in body_str

    @pytest.mark.asyncio
    async def test_403_response_has_unified_envelope(self, client: AsyncClient, app) -> None:
        """非管理员访问 admin 接口 → HTTP 403，响应含 code、message、data。

        需求 6.5：403 响应符合统一信封格式。
        """
        from types import SimpleNamespace

        from src.core.deps import get_current_user

        normal_user = SimpleNamespace(id=2, email="user@example.com", membership="free", is_active=True, is_admin=False)
        app.dependency_overrides[get_current_user] = lambda: normal_user
        try:
            resp = await client.post(
                "/api/v1/admin/backtests",
                json={"strategy_id": 1, "timerange": "20240101-20240301"},
            )
        finally:
            app.dependency_overrides.clear()

        assert resp.status_code == 403
        body = resp.json()
        assert "code" in body
        assert "message" in body
        assert "data" in body
        # 确认不含 Python traceback 关键词
        body_str = str(body)
        assert "Traceback" not in body_str
        assert 'File "' not in body_str
