# 设计文档：quality-test-suite

---

## 概述

本特性为 `strategy_platform_service` 构建完整的质量测试套件，系统性覆盖认证鉴权、策略展示、回测任务（管理员接口）、交易信号、AI 研报、参数校验与 freqtrade 集成边界等核心模块。

**目标用户**：质量保障工程师与后端开发工程师，用于在 CI 环境中持续验证平台各层（API 路由层、业务逻辑层、数据访问层、freqtrade 集成层）的正确性。

**系统影响**：不修改现有业务代码，仅向 `tests/` 目录添加新测试文件、共享 conftest fixtures 和真实数据库集成测试层，现有 454 个测试全部保留且继续可运行。

### 目标

- 为需求 1–8 的所有验收标准提供可执行的测试用例映射（约 15–20 个新测试函数）
- 引入真实 PostgreSQL 集成测试层（Docker + Alembic），解决当前所有 DB 均被 mock 的覆盖盲区
- 建立共享 conftest fixtures（用户令牌工厂、应用工厂、真实 DB session），消除各测试文件重复的 `env_setup` / `_make_mock_db` 模式
- 明确回测提交接口为 Admin-Only（`POST /api/v1/admin/backtests`），补充缺失的权限与冲突检测用例
- 将性能测试（需求 4.5）标记为可选/延后，不纳入本次实现范围

### 非目标

- 不修改任何 `src/` 下业务源码
- 不引入 E2E 浏览器测试或真实 freqtrade 进程调用
- 需求 4.5（信号 P95 响应时间）：延后处理，标记为 `@pytest.mark.skip(reason="性能测试延后")`
- 不为 sqladmin UI 页面编写测试

---

## 架构

### 现有架构分析

当前测试套件具备以下基础设施：

- **测试模式**：`httpx.AsyncClient` + `ASGITransport`，无需真实网络端口
- **DB 隔离方式**：100% mock（`AsyncMock` + `dependency_overrides[get_db]`），无真实 DB 路径
- **pytest 配置**：`asyncio_mode = "auto"`（pytest-asyncio），测试目录 `tests/unit/` 和 `tests/integration/`
- **问题**：每个测试文件各自定义 `env_setup`、`app`、`client` fixture，存在大量重复；无共享 conftest；无真实数据库路径验证

**需要解决的关键差距**：

1. `tests/conftest.py` 仅提供 `clear_settings_cache`，缺少用户令牌工厂和应用工厂 fixtures
2. 回测创建（需求 3.1）缺少针对 `POST /api/v1/admin/backtests` 的 Admin 权限验证测试
3. `page_size` 超限应返回 `code: 2001`（需求 2.5），现有测试未覆盖此分支
4. 真实 DB 持久化验证（需求 3.8、8.1）无任何测试覆盖
5. freqtrade 超时与临时目录清理（需求 7.1、7.3）仅在单元层有部分覆盖，集成层缺失

### 架构模式与边界图

```mermaid
graph TB
    subgraph TestLayer
        UnitTests[tests/unit 单元测试]
        IntegTests[tests/integration 集成测试]
        Conftest[tests/conftest.py 共享 fixtures]
        DBConftest[tests/integration/conftest.py 真实 DB fixtures]
    end

    subgraph AppLayer
        FastAPI[FastAPI App ASGITransport]
        Services[src/services 业务逻辑]
        Models[src/models SQLAlchemy 模型]
    end

    subgraph InfraLayer
        MockDB[AsyncMock AsyncSession]
        RealDB[真实 PostgreSQL Docker]
        AlembicMigration[Alembic upgrade head]
    end

    Conftest --> UnitTests
    Conftest --> IntegTests
    DBConftest --> IntegTests
    IntegTests --> FastAPI
    UnitTests --> Services
    FastAPI --> Services
    Services --> Models
    DBConftest --> RealDB
    DBConftest --> AlembicMigration
    IntegTests --> MockDB
    RealDB --> Models
```

**架构决策**：

- **双轨 DB 策略**：保留 mock DB 路径（快速、无依赖），同时新增真实 DB 路径（`pytest.mark.integration_db`），两者并行共存。真实 DB 测试在无 Docker PostgreSQL 时自动 skip（需求 8.5）
- **共享 conftest 层级**：`tests/conftest.py` 提供无状态 fixtures（应用工厂、令牌工厂），`tests/integration/conftest.py` 提供真实 DB session（仅集成层可见）
- **Admin 接口边界**：回测提交测试目标 `POST /api/v1/admin/backtests`，通过 `require_admin` 依赖覆盖控制权限

### 技术栈

| 层 | 技术 / 版本 | 在本特性中的职责 | 备注 |
|---|---|---|---|
| 测试框架 | pytest 8.x + pytest-asyncio 1.3.x | 异步测试驱动、fixtures 管理 | `asyncio_mode=auto` 已配置 |
| HTTP 测试客户端 | httpx 0.27.x + ASGITransport | 对 FastAPI 路由层发起异步 HTTP 请求 | 无需真实端口，现有模式 |
| 数据库（mock） | unittest.mock.AsyncMock | 单元/集成测试 DB 隔离 | 现有模式，继续使用 |
| 数据库（真实） | PostgreSQL 16 via Docker | 真实持久化路径集成测试 | 新增，需 `TEST_DATABASE_URL` 环境变量 |
| Schema 迁移 | alembic 1.13.x | 真实 DB 测试前初始化 Schema | 复用 `alembic.ini`，测试后 `downgrade base` |
| 异步 DB 驱动 | asyncpg 0.31.x | 真实 DB 集成测试 async session | 已有依赖 |
| JWT 工具 | python-jose 3.3.x | 测试令牌生成 | 复用 `SecurityUtils` |
| 进程 mock | unittest.mock.patch + MagicMock | freqtrade 子进程隔离 | 现有模式 |

---

## 系统流程

### 真实 DB 集成测试初始化流程

```mermaid
sequenceDiagram
    participant CI as CI / pytest
    participant Conftest as integration/conftest.py
    participant Docker as Docker PostgreSQL
    participant Alembic as alembic upgrade head
    participant Test as 集成测试用例

    CI->>Conftest: pytest session 启动
    Conftest->>Docker: 检查 TEST_DATABASE_URL 可达性
    alt 不可达
        Conftest-->>CI: pytest.skip 跳过全部 integration_db 测试
    else 可达
        Conftest->>Alembic: alembic upgrade head（建表）
        Alembic-->>Conftest: Schema 就绪
        Conftest->>Test: 提供 async_db_session fixture
        Test->>Docker: 执行 SQL / 验证持久化
        Test-->>Conftest: 测试完成
        Conftest->>Docker: TRUNCATE 各表（测试间隔离）
        Conftest->>Alembic: alembic downgrade base（teardown）
    end
```

### 管理员回测提交权限验证流程

```mermaid
sequenceDiagram
    participant TestCase as 测试用例
    participant Client as AsyncClient
    participant Router as admin_backtests router
    participant RequireAdmin as require_admin Depends
    participant Service as AdminBacktestService

    TestCase->>Client: POST /api/v1/admin/backtests
    Client->>Router: HTTP 请求
    Router->>RequireAdmin: 检查 is_admin
    alt 非管理员
        RequireAdmin-->>Router: PermissionError code=1002
        Router-->>Client: 403 + code:1002
        Client-->>TestCase: assert 403
    else 管理员
        RequireAdmin-->>Router: admin_user
        Router->>Service: submit_backtest(strategy_id, timerange)
        alt 策略不存在
            Service-->>Router: NotFoundError code=3001
            Router-->>Client: 404 + code:3001
        else RUNNING 冲突
            Service-->>Router: ConflictError code=3002
            Router-->>Client: 409 + code:3002
        else 成功
            Service-->>Router: BacktestTask(PENDING)
            Router-->>Client: 202 + task_id
            Client-->>TestCase: assert 202
        end
    end
```

---

## 需求追溯

| 需求 | 摘要 | 组件 | 接口 | 流程 |
|---|---|---|---|---|
| 1.1 | 正确凭证登录返回双 token + code:0 | SharedConftest, AuthIntegTest | POST /api/v1/auth/login | — |
| 1.2 | 错误密码返回 code:1001 + 401 | AuthIntegTest | POST /api/v1/auth/login | — |
| 1.3 | 有效 token 访问受保护接口 | SharedConftest token_factory | GET /api/v1/strategies | — |
| 1.4 | 过期/无效 token 返回 code:1001 | AuthIntegTest | 任意受保护接口 | — |
| 1.5 | 无认证头部返回 code:1001 | AuthIntegTest | 任意受保护接口 | — |
| 1.6 | free 会员调用 VIP1 接口返回 code:1003 | SharedConftest membership_fixtures | 需 VIP1 的接口 | — |
| 1.7 | refresh_token 换发新 access_token | AuthIntegTest | POST /api/v1/auth/refresh | — |
| 1.8 | refresh_token 不可用于普通业务接口 | AuthIntegTest | GET /api/v1/strategies | — |
| 2.1 | 匿名用户策略列表仅含基础字段 | StrategyIntegTest | GET /api/v1/strategies | — |
| 2.2 | Free 用户策略详情含中级字段 | StrategyIntegTest | GET /api/v1/strategies/{id} | — |
| 2.3 | VIP 用户策略详情含所有高级字段 | StrategyIntegTest | GET /api/v1/strategies/{id} | — |
| 2.4 | 默认分页 page=1, page_size=20 | StrategyIntegTest | GET /api/v1/strategies | — |
| 2.5 | page_size 超限返回 code:2001 | StrategyIntegTest | GET /api/v1/strategies?page_size=200 | — |
| 2.6 | 策略 ID 不存在返回 code:3001 + 404 | StrategyIntegTest | GET /api/v1/strategies/9999 | — |
| 2.7 | 响应符合统一信封格式 | SharedConftest envelope_assert | 所有策略接口 | — |
| 3.1 | 管理员提交回测返回 task_id + PENDING + 202 | AdminBacktestIntegTest | POST /api/v1/admin/backtests | 管理员权限流程 |
| 3.2 | RUNNING 状态查询不含结果数据 | AdminBacktestIntegTest | GET /api/v1/admin/backtests/{id} | — |
| 3.3 | DONE 后包含六项核心指标 | BacktestStatusFlowTest | GET /api/v1/admin/backtests/{id} | — |
| 3.4 | freqtrade 失败状态为 FAILED + code:5001 | FreqtradeIntegTest | GET /api/v1/admin/backtests/{id} | — |
| 3.5 | 重复提交 RUNNING 任务返回 code:3002 | AdminBacktestIntegTest | POST /api/v1/admin/backtests | 管理员权限流程 |
| 3.6 | 匿名用户调用回测接口返回 code:1001 | AdminBacktestIntegTest | POST /api/v1/admin/backtests | — |
| 3.7 | Free 用户超配额返回相应错误码 | AdminBacktestIntegTest | POST /api/v1/admin/backtests | — |
| 3.8 | 回测结果正确持久化到 DB | RealDBIntegTest | DB 查询验证 | 真实 DB 流程 |
| 4.1 | 信号接口返回 200 + 缓存信号 | SignalIntegTest | GET /api/v1/signals | — |
| 4.2 | 匿名用户信号仅基础字段 | SignalIntegTest | GET /api/v1/signals | — |
| 4.3 | VIP 用户信号含 confidence_score | SignalIntegTest | GET /api/v1/signals | — |
| 4.4 | 无缓存数据返回空列表非 500 | SignalIntegTest | GET /api/v1/signals | — |
| 4.5 | P95 响应时间不超 500ms | （延后，标记 skip） | — | — |
| 5.1 | 匿名访问研报列表返回 200 | ReportIntegTest | GET /api/v1/reports | — |
| 5.2 | 匿名访问研报详情返回完整内容 | ReportIntegTest | GET /api/v1/reports/{id} | — |
| 5.3 | 研报 ID 不存在返回 404 非 500 | ReportIntegTest | GET /api/v1/reports/9999 | — |
| 5.4 | 研报列表含标准分页结构 | ReportIntegTest | GET /api/v1/reports | — |
| 5.5 | 研报响应符合统一信封格式 | ReportIntegTest | GET /api/v1/reports | — |
| 6.1 | 缺少必填字段返回 code:2001 + 字段详情 | ValidationIntegTest | POST /api/v1/auth/login | — |
| 6.2 | 类型错误字段返回 code:2001 + 422 | ValidationIntegTest | 各资源 POST 接口 | — |
| 6.3 | RequestValidationError 被转换为信封格式 | ValidationIntegTest | 全局异常处理器验证 | — |
| 6.4 | 路径参数非数字返回参数校验错误非 500 | ValidationIntegTest | GET /api/v1/strategies/abc | — |
| 6.5 | 所有错误响应符合信封格式不暴露堆栈 | ValidationIntegTest | 4xx/5xx 响应 | — |
| 7.1 | freqtrade 超时任务标记 FAILED + code:5001 | FreqtradeUnitTest | BacktestTask 状态机 | — |
| 7.2 | 非零退出码捕获为业务错误 | FreqtradeUnitTest | FreqtradeBridge | — |
| 7.3 | 任务结束后清理临时目录 | FreqtradeUnitTest | BacktestTask teardown | — |
| 7.4 | freqtrade Worker 不可用时 Web 接口正常 | FreqtradeIntegTest | GET /api/v1/strategies | — |
| 7.5 | 用户间 freqtrade 配置目录隔离 | FreqtradeUnitTest | 配置路径生成逻辑 | — |
| 8.1 | 真实 PostgreSQL + Alembic 初始化/清理 | RealDBFixture | DB session fixture | 真实 DB 流程 |
| 8.2 | httpx.AsyncClient + ASGITransport | SharedConftest | async_client fixture | — |
| 8.3 | 单元测试 mock 外部依赖 | SharedConftest mock_db | AsyncMock fixture | — |
| 8.4 | 用户令牌工厂 fixtures | SharedConftest token_factory | JWT 签发 | — |
| 8.5 | DB 不可用时 skip 而非报错 | RealDBFixture | pytest.skip 逻辑 | 真实 DB 流程 |
| 8.6 | make test 5 分钟内完成 | CI 配置 | Makefile test target | — |
| 8.7 | unit/integration 目录结构 | 测试文件组织 | 目录对应 src 层次 | — |
| 8.8 | 未预期异常输出诊断报告 | pytest 配置 | --tb=short/long | — |

---

## 组件与接口

### 组件概览

| 组件 | 层 | 职责 | 需求覆盖 | 关键依赖 | 契约 |
|---|---|---|---|---|---|
| SharedConftest | tests/conftest.py | 全局 fixtures：env/app/client/token 工厂 | 1.1–1.8, 8.2–8.4 | SecurityUtils, create_app | Service |
| RealDBFixture | tests/integration/conftest.py | Docker PG + Alembic setup/teardown | 3.8, 8.1, 8.5 | asyncpg, alembic | State |
| AuthMissingTests | tests/integration/test_auth_api.py | 补充 1.6、1.7、1.8 缺失用例 | 1.6, 1.7, 1.8 | SharedConftest | API |
| AdminBacktestIntegTest | tests/integration/test_admin_backtest_api.py | 补充 3.1、3.5、3.6 用例 | 3.1, 3.5, 3.6, 3.7 | SharedConftest | API |
| StrategyMissingTests | tests/integration/test_strategy_api.py | 补充 2.5（page_size 超限）用例 | 2.5 | SharedConftest | API |
| ValidationIntegTest | tests/integration/test_validation.py | 需求 6 全部参数校验场景（新文件） | 6.1–6.5 | SharedConftest | API |
| RealDBIntegTest | tests/integration/test_real_db_persistence.py | 真实 DB 持久化验证（新文件） | 3.8, 8.1 | RealDBFixture | State |
| FreqtradeIntegTest | tests/integration/test_freqtrade_isolation.py | 7.4 Worker 不可用隔离验证（新文件） | 7.4 | SharedConftest | API |

---

### 测试基础设施层

#### SharedConftest

| 字段 | 详情 |
|---|---|
| 意图 | 为全体测试提供可复用的无状态 fixtures，消除各文件重复的 env_setup / app / client 定义 |
| 需求 | 1.3, 1.6, 8.2, 8.3, 8.4 |

**职责与约束**

- 提供 `env_setup` fixture（session/module/function 可选作用域），注入 `SECRET_KEY`、`DATABASE_URL`、`REDIS_URL` 测试值并在退出时清除 settings 缓存
- 提供 `app_factory` fixture，返回调用 `create_app()` 创建的 FastAPI 实例（`function` 作用域，确保测试间隔离）
- 提供 `async_client` fixture，绑定 `ASGITransport(app=app_factory)` 的 `httpx.AsyncClient`
- 提供 `token_factory` fixture，封装 `SecurityUtils` 签发方法，按 `MembershipTier` 枚举生成有效 JWT
- 提供 `mock_db` fixture，返回配置好基本方法的 `AsyncMock` session
- 所有 fixture 均通过 `monkeypatch` 和 `lru_cache` 清除实现测试间隔离，不依赖全局状态

**依赖**

- 入站：各测试文件通过 pytest fixture 注入机制使用
- 出站：`src.api.main_router.create_app`（P0），`src.core.security.SecurityUtils`（P0），`src.core.app_settings.get_settings`（P0）

**契约**：Service [x] / API [ ] / Event [ ] / Batch [ ] / State [ ]

##### Service 接口

```python
# tests/conftest.py 中的 fixture 签名（伪接口，供实现参考）

# env_setup: 注入测试环境变量，作用域 function
@pytest.fixture()
def env_setup(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]: ...

# app_factory: 返回隔离的 FastAPI 实例
@pytest.fixture()
def app(env_setup: None) -> FastAPI: ...

# async_client: 绑定 ASGITransport 的异步 HTTP 客户端
@pytest.fixture()
async def async_client(app: FastAPI) -> AsyncGenerator[AsyncClient, None]: ...

# token_factory: 按会员等级签发 JWT
@pytest.fixture()
def token_factory(env_setup: None) -> Callable[[MembershipTier], str]: ...

# mock_db: 预配置的 AsyncMock 数据库 session
@pytest.fixture()
def mock_db() -> AsyncMock: ...
```

**实现说明**

- `token_factory` 内部调用 `SecurityUtils().create_access_token(sub=str(user_id), membership=tier)`，`user_id` 默认按等级分配固定值（匿名=None，Free=1，VIP1=2，VIP2=3），便于依赖覆盖
- `async_client` 必须通过 `async with` 上下文管理确保连接正确关闭
- 现有各集成测试文件内的局部 `env_setup` / `app` / `client` fixture 可逐步迁移至共享 conftest，但迁移不破坏现有测试

---

#### RealDBFixture

| 字段 | 详情 |
|---|---|
| 意图 | 为真实 DB 集成测试提供 PostgreSQL session，包含 Alembic 迁移初始化和测试间数据清理 |
| 需求 | 3.8, 8.1, 8.5 |

**职责与约束**

- `session` 作用域 fixture `real_db_engine`：读取 `TEST_DATABASE_URL` 环境变量，若不可达则调用 `pytest.skip()` 跳过整个 session
- `function` 作用域 fixture `real_db_session`：每个测试函数分配独立 async session，测试后 TRUNCATE 业务表（`users`, `strategies`, `backtest_tasks`, `backtest_results`, `trading_signals`, `reports`）以实现数据隔离
- `session` 作用域 fixture `alembic_setup`：在 `real_db_engine` 就绪后执行 `alembic upgrade head`，测试 session 结束后执行 `alembic downgrade base`
- 真实 DB 测试用 `@pytest.mark.integration_db` 标记，非 DB 测试不依赖此 fixture

**依赖**

- 入站：`RealDBIntegTest` 测试文件
- 出站：`asyncpg`（P0），`alembic`（P0），`TEST_DATABASE_URL` 环境变量（P0），`src.models.base.Base`（P1）
- 外部：Docker PostgreSQL 16 容器，CI 中通过 `docker-compose` 或 `services` 提供

**契约**：Service [ ] / API [ ] / Event [ ] / Batch [ ] / State [x]

##### State Management

- **状态模型**：每个测试函数对应一个 PostgreSQL 事务或显式 TRUNCATE，保证测试间数据隔离
- **持久化与一致性**：`alembic upgrade head` 确保测试 Schema 与生产代码一致；`downgrade base` 在 session teardown 时清理所有表
- **并发策略**：测试默认串行执行（`pytest-asyncio` auto 模式），无并发隔离需求

**实现说明**

- `TEST_DATABASE_URL` 格式：`postgresql+asyncpg://user:password@localhost:5432/test_db`，CI 中通过环境变量注入
- Alembic 调用通过 `subprocess.run(["alembic", "upgrade", "head"], ...)` 或 `alembic.config.Config` API 执行，确保迁移文件路径正确（项目根 `alembic.ini`）
- 风险：若 Alembic 迁移文件尚未创建，测试 session 将失败并输出明确错误信息，提示运行 `make migrate`

---

### 集成测试层（新增测试）

#### ValidationIntegTest

| 字段 | 详情 |
|---|---|
| 意图 | 验证全局异常处理器将 FastAPI RequestValidationError 转换为统一信封格式，以及各类参数校验边界 |
| 需求 | 6.1, 6.2, 6.3, 6.4, 6.5 |

**职责与约束**

- 文件路径：`tests/integration/test_validation.py`（新文件）
- 验证 `POST /api/v1/auth/login` 缺少 `password` 字段时，响应为 HTTP 422，body `{"code": 2001, "message": ..., "data": [...]}`，`data` 包含字段级校验详情
- 验证 `POST /api/v1/auth/login` 中 `password` 传入整型时，响应为 HTTP 422，`code: 2001`
- 验证 `GET /api/v1/strategies/abc` 路径参数非整数，响应为 HTTP 422，`code: 2001`，非 HTTP 500
- 验证 HTTP 404、401、403 响应体均包含 `code`、`message`、`data` 三字段，不含 Python traceback 信息

**依赖**

- 入站：pytest runner
- 出站：`SharedConftest.app`（P0），`src.core.exception_handlers`（P0）

**契约**：Service [ ] / API [x] / Event [ ] / Batch [ ] / State [ ]

##### API 契约

| Method | Endpoint | 请求 | 期望响应 | 错误验证 |
|---|---|---|---|---|
| POST | /api/v1/auth/login | 缺少 password 字段 | 422 + `code: 2001` + 字段详情 | 6.1, 6.3 |
| POST | /api/v1/auth/login | password 为整型 | 422 + `code: 2001` | 6.2, 6.3 |
| GET | /api/v1/strategies/abc | 路径参数非数字 | 422 + `code: 2001` | 6.4 |
| GET | /api/v1/strategies/99999 | 策略不存在 | 404 + `code: 3001` + 无 traceback | 6.5 |

**实现说明**

- 所有用例通过 mock DB 运行，不依赖真实 DB
- `data` 字段中的校验详情格式来自 FastAPI `RequestValidationError.errors()` 列表，测试仅断言列表非空，不校验具体内容（避免与 Pydantic 版本耦合）

---

#### AdminBacktestIntegTest（补充用例）

| 字段 | 详情 |
|---|---|
| 意图 | 补充管理员回测接口中缺失的冲突检测、匿名访问拒绝和 free 用户超配额场景 |
| 需求 | 3.1, 3.5, 3.6, 3.7 |

**职责与约束**

- 文件路径：`tests/integration/test_admin_backtest_api.py`（现有文件，追加用例）
- 补充 `test_anonymous_user_returns_401_on_backtest_submit`：无 Authorization header 调用 `POST /api/v1/admin/backtests`，响应 401 + `code: 1001`
- 补充 `test_running_task_conflict_returns_code_3002`：mock `submit_backtest` 抛出 `ConflictError`，响应 409 + `code: 3002`
- 补充 `test_strategy_not_found_returns_code_3001`：mock `submit_backtest` 抛出 `NotFoundError`，响应 404 + `code: 3001`
- 补充 `test_admin_submit_returns_202_with_task_id`：验证成功路径响应 HTTP 202（非 200），body 包含 `task_id` 和 `status: PENDING`（需确认 API 实际状态码，若当前为 200 则需记录差异）

**依赖**

- 入站：pytest runner
- 出站：`SharedConftest`（P0），`src.services.admin_backtest_service.AdminBacktestService`（P0），`src.core.exceptions.ConflictError`（P0）

**契约**：Service [ ] / API [x] / Event [ ] / Batch [ ] / State [ ]

##### API 契约

| Method | Endpoint | 请求方 | 期望响应 | 需求 |
|---|---|---|---|---|
| POST | /api/v1/admin/backtests | 匿名（无 token） | 401 + `code: 1001` | 3.6 |
| POST | /api/v1/admin/backtests | 管理员 + RUNNING 冲突 | 409 + `code: 3002` | 3.5 |
| POST | /api/v1/admin/backtests | 管理员 + 策略不存在 | 404 + `code: 3001` | 3.1 |
| POST | /api/v1/admin/backtests | Free 用户超配额 | 对应配额错误码 | 3.7 |

---

#### StrategyMissingTests（补充用例）

| 字段 | 详情 |
|---|---|
| 意图 | 补充 page_size 超限返回 code:2001 的验证场景 |
| 需求 | 2.5 |

**职责与约束**

- 文件路径：`tests/integration/test_strategy_api.py`（现有文件，追加用例）
- 补充 `test_page_size_exceeds_max_returns_code_2001`：`GET /api/v1/strategies?page_size=200`，期望响应 HTTP 422，body `code: 2001`，不发生截断行为

**依赖**

- 出站：`SharedConftest.app`（P0），策略列表路由 Pydantic schema 的 `le=100` 校验器（P0）

**契约**：Service [ ] / API [x] / Event [ ] / Batch [ ] / State [ ]

---

#### RealDBIntegTest

| 字段 | 详情 |
|---|---|
| 意图 | 验证回测结果在真实 PostgreSQL 中正确持久化，后续查询可读取相同数据 |
| 需求 | 3.8, 8.1 |

**职责与约束**

- 文件路径：`tests/integration/test_real_db_persistence.py`（新文件）
- 标记 `@pytest.mark.integration_db`，依赖 `RealDBFixture.real_db_session`
- `test_backtest_result_persisted_to_real_db`：通过真实 async session 直接插入 `BacktestTask` 和 `BacktestResult` ORM 对象，commit 后重新查询，断言六项核心指标值不变
- `test_user_created_with_correct_membership`：插入用户对象，查询验证 `membership` 字段正确持久化

**依赖**

- 入站：pytest runner（仅 `TEST_DATABASE_URL` 可用时）
- 出站：`RealDBFixture`（P0），`src.models.backtest_result.BacktestResult`（P0），`src.models.user.User`（P0）

**契约**：Service [ ] / API [ ] / Event [ ] / Batch [ ] / State [x]

---

#### FreqtradeIntegTest

| 字段 | 详情 |
|---|---|
| 意图 | 验证 freqtrade Worker 不可用时，非回测 Web 接口仍正常响应（服务降级隔离） |
| 需求 | 7.4 |

**职责与约束**

- 文件路径：`tests/integration/test_freqtrade_isolation.py`（新文件）
- `test_strategies_accessible_when_worker_unavailable`：patch `celery.app.control.inspect` 返回 None（模拟 Worker 不可用），调用 `GET /api/v1/strategies`，断言响应 200 + `code: 0`
- `test_reports_accessible_when_worker_unavailable`：同上，调用 `GET /api/v1/reports`，断言 200

**依赖**

- 出站：`SharedConftest.app`（P0），`unittest.mock.patch`（P0）

**契约**：Service [ ] / API [x] / Event [ ] / Batch [ ] / State [ ]

---

### 单元测试层（补充用例）

#### AuthMissingUnitTests（补充用例）

| 字段 | 详情 |
|---|---|
| 意图 | 补充 refresh_token 被用于普通接口被拒绝的验证（需求 1.8） |
| 需求 | 1.8 |

**职责与约束**

- 文件路径：`tests/integration/test_auth_api.py`（现有文件，追加用例）
- 补充 `test_refresh_token_rejected_on_protected_api`：生成 `refresh_token`，携带其调用 `GET /api/v1/strategies`，断言 401 + `code: 1001`（`get_current_user` 会拒绝 `type != "access"` 的 token）

---

## 数据模型

### 域模型

本特性不新增业务数据模型，复用现有 SQLAlchemy 声明式模型：

- `User`（`src/models/user.py`）：`id`、`username`、`hashed_password`、`membership`（MembershipTier）、`is_active`、`is_admin`
- `BacktestTask`（`src/models/backtest_task.py`）：`id`、`strategy_id`、`status`（TaskStatus）、`result_json`、`error_message`
- `BacktestResult`（`src/models/backtest_result.py`）：`id`、`task_id`、`strategy_id`、六项核心指标
- `TradingSignal`：`id`、`strategy_id`、`direction`、`confidence_score`

### 测试数据契约

真实 DB 测试中通过 ORM 直接构造数据，不依赖 fixture 文件或 SQL dump：

```
BacktestResult {
  total_return: float      # 核心指标 1
  annual_return: float     # 核心指标 2
  sharpe_ratio: float      # 核心指标 3（VIP）
  max_drawdown: float      # 核心指标 4
  trade_count: int         # 核心指标 5
  win_rate: float          # 核心指标 6（VIP）
}
```

测试数据生命周期：每个 `function` 作用域测试后，通过 TRUNCATE 清除，不跨测试共享。

---

## 错误处理

### 错误策略

测试套件本身不引入新的错误处理逻辑，但需要验证以下应用层错误处理模式正确工作：

### 错误分类与响应验证

**应用层用户错误（4xx）**：

| 场景 | 期望业务码 | 期望 HTTP 状态 | 测试文件 |
|---|---|---|---|
| 无效/过期 token | 1001 | 401 | test_auth_api.py |
| 无认证头部 | 1001 | 401 | test_auth_api.py |
| refresh_token 用于业务接口 | 1001 | 401 | test_auth_api.py |
| 会员等级不足 | 1003 | 403 | test_strategy_api.py |
| 非管理员访问 admin 接口 | 1002 | 403 | test_admin_backtest_api.py |
| 参数校验失败 | 2001 | 422 | test_validation.py |
| page_size 超限 | 2001 | 422 | test_strategy_api.py |
| 资源不存在 | 3001 | 404 | test_strategy_api.py |
| 回测任务冲突 | 3002 | 409 | test_admin_backtest_api.py |

**应用层系统错误（5xx）**：

| 场景 | 期望业务码 | 测试文件 |
|---|---|---|
| freqtrade 执行失败 | 5001 | test_freqtrade_bridge.py（现有） |
| freqtrade 超时 | 5001 | test_freqtrade_bridge.py（现有） |

**错误响应格式约束**：所有错误响应必须包含 `code`、`message`、`data` 三字段；`data` 为 `null` 或包含详情；不暴露 Python traceback 或内部路径。由 `test_validation.py` 的 6.5 用例统一验证此格式约束。

### 监控

- pytest 失败时通过 `--tb=short` 输出紧凑调用栈（需求 8.8）
- CI 执行结果通过 `--cov-report=term-missing` 展示覆盖率差距
- 真实 DB 测试 skip 时输出 `reason="TEST_DATABASE_URL not available"` 明确原因

---

## 测试策略

### 单元测试（现有，补充部分）

- `test_auth_api.py`：补充 1 个用例（需求 1.8，refresh_token 被拒）
- `test_freqtrade_bridge.py`：验证需求 7.1（超时）、7.2（非零退出码）、7.3（目录清理）、7.5（路径隔离）

### 集成测试（新增文件 + 补充用例）

- `test_admin_backtest_api.py`（追加）：3.1、3.5、3.6、3.7（匿名拒绝、冲突、不存在策略）
- `test_strategy_api.py`（追加）：2.5（page_size 超限返回 2001）
- `test_validation.py`（新文件）：6.1–6.5 全部参数校验场景
- `test_real_db_persistence.py`（新文件）：3.8、8.1 真实 DB 持久化
- `test_freqtrade_isolation.py`（新文件）：7.4 Worker 不可用服务降级

### 真实数据库集成测试

- 标记 `@pytest.mark.integration_db`，通过 `TEST_DATABASE_URL` 环境变量控制是否激活
- 本地开发：`docker compose up -d postgres` 后设置 `TEST_DATABASE_URL`，运行 `make test`
- CI：在 pipeline 中通过 `services.postgres` 提供 Docker PG，注入 `TEST_DATABASE_URL`

### 性能测试（延后）

- 需求 4.5（信号 P95 响应时间 ≤ 500ms）：标记 `@pytest.mark.skip(reason="性能测试延后，待 Locust/k6 方案确定后实现")`，不纳入本次范围

---

## 安全考量

- 测试用 JWT 令牌使用独立固定密钥（`TEST_SECRET_KEY`），与生产 `SECRET_KEY` 严格隔离
- `TEST_DATABASE_URL` 仅指向本地/CI 测试数据库，禁止指向生产数据库
- 测试代码不持久化任何明文密码；用户 fixture 通过 `SecurityUtils.hash_password()` 生成哈希值
- freqtrade mock 不调用真实 exchange API，不涉及真实账户或资金

---

## 支持参考

### 现有测试模式参考

当前集成测试的标准 mock DB 模式（`tests/integration/test_auth_api.py` 第 32–38 行）作为所有新测试的实现基线：使用 `AsyncMock` + `dependency_overrides[get_db]` + `app.dependency_overrides.clear()` 的三段式结构。

### pytest-asyncio 配置

`asyncio_mode = "auto"`（`pyproject.toml`）意味着所有 `async def test_*` 函数自动运行为协程，无需显式 `@pytest.mark.asyncio` 标注（现有代码中的 `@pytest.mark.asyncio` 为向前兼容，新代码可省略）。

### 真实 DB 所需新增开发依赖

当前 `pyproject.toml` 的 `dev` 依赖组中未包含真实 DB 测试所需的辅助库。需在 `[dependency-groups].dev` 中追加：

```
pytest-postgresql 或 testcontainers-python （二选一，用于 CI Docker PG 管理）
```

若使用纯环境变量控制（`TEST_DATABASE_URL`），则无需额外依赖，通过 `try/except` 连接测试即可实现 skip 逻辑。推荐使用环境变量方案以保持最小依赖原则。
