# 需求文档

## 介绍

本文档定义了 `strategy_platform_service` 质量测试套件的完整需求。该测试套件旨在通过功能测试和集成测试，系统性地保障平台各核心模块（认证鉴权、策略展示、回测任务、交易信号、AI研报、字段级权限控制）的正确性与可用性。测试覆盖范围对应平台的分层架构：API 路由层、业务逻辑层（服务层）、数据访问层，以及 freqtrade 集成层的外部边界。

---

## 需求

### 需求 1: 认证与鉴权测试

**目标：** 作为质量保障工程师，我希望覆盖所有登录、令牌校验、权限拦截场景，以便确保平台的身份认证体系安全可靠。

#### 验收标准

1. When 用户携带正确的用户名和密码调用登录接口，the Test Suite shall 验证响应包含有效的 `access_token` 和 `refresh_token`，且 HTTP 状态码为 200，响应体符合统一信封格式（`code: 0`）。
2. When 用户携带错误密码调用登录接口，the Test Suite shall 验证响应返回业务错误码 `1001`，HTTP 状态码为 401，且响应体中不包含令牌字段。
3. When 客户端携带有效 `access_token` 调用受保护接口，the Test Suite shall 验证接口正常返回数据且不触发 401 错误。
4. When 客户端携带过期或签名无效的 `access_token` 调用受保护接口，the Test Suite shall 验证系统返回业务错误码 `1001`，HTTP 状态码为 401。
5. When 客户端不携带任何认证头部调用受保护接口，the Test Suite shall 验证系统拒绝请求并返回业务错误码 `1001`。
6. When 用户携带 `membership: "free"` 的令牌调用 VIP1 专属接口，the Test Suite shall 验证系统返回业务错误码 `1003`，HTTP 状态码为 403。
7. When 用户使用 `refresh_token` 调用刷新接口，the Test Suite shall 验证系统签发新的 `access_token` 且原令牌不再有效。
8. If `refresh_token` 被用于调用普通业务接口（非刷新端点），the Test Suite shall 验证系统拒绝该请求并返回认证错误。

---

### 需求 2: 策略展示接口测试

**目标：** 作为质量保障工程师，我希望验证策略列表与详情接口在不同权限等级下的数据可见性，以便确保字段级权限控制符合业务规则。

#### 验收标准

1. When 匿名用户调用 `GET /api/v1/strategies`，the Test Suite shall 验证响应仅包含基础字段（策略名称、描述、所属币种等），不包含高级指标字段（如夏普比率、胜率、可信度评分）。
2. When 已登录的 Free 用户调用 `GET /api/v1/strategies/{id}`，the Test Suite shall 验证响应包含中级指标字段，且不包含 VIP 专属字段。
3. When VIP1 或 VIP2 用户调用 `GET /api/v1/strategies/{id}`，the Test Suite shall 验证响应包含所有高级指标字段（夏普比率、胜率、可信度评分等）。
4. When 客户端调用策略列表接口且未传分页参数，the Test Suite shall 验证响应默认返回第 1 页、每页 20 条，且分页结构包含 `items`、`total`、`page`、`page_size` 字段。
5. When 客户端传入超过最大值（100）的 `page_size` 参数，the Test Suite shall 验证系统返回业务错误码 `2001` 或自动截断至最大值 100。
6. When 请求的策略 ID 不存在，the Test Suite shall 验证系统返回业务错误码 `3001`，HTTP 状态码为 404。
7. The Test Suite shall 验证所有策略接口响应体均符合统一 JSON 信封格式（`code`、`message`、`data` 字段齐全）。

---

### 需求 3: 回测任务接口测试

**目标：** 作为质量保障工程师，我希望覆盖回测任务的创建、状态轮询、结果读取及错误处理，以便确保异步回测流程的完整性和数据一致性。

#### 验收标准

1. When 已登录用户提交回测请求，the Test Suite shall 验证系统立即返回 `task_id` 和初始状态 `PENDING`，HTTP 状态码为 202。
2. While 回测任务处于 `RUNNING` 状态，the Test Suite shall 验证 `GET /api/v1/backtests/{task_id}` 返回当前状态为 `RUNNING` 且不包含结果数据。
3. When 回测任务成功完成，the Test Suite shall 验证任务状态更新为 `DONE`，且响应数据包含收益率、年化收益率、夏普比率、最大回撤、交易次数、胜率等核心指标。
4. When freqtrade 执行失败（模拟 freqtrade 异常），the Test Suite shall 验证任务状态更新为 `FAILED`，响应包含业务错误码 `5001`，且错误信息不暴露原始 traceback。
5. When 用户尝试对同一策略触发重复回测且已有任务处于 `RUNNING` 状态，the Test Suite shall 验证系统返回业务错误码 `3002`（回测任务冲突）。
6. When 匿名用户或未登录用户调用回测接口，the Test Suite shall 验证系统返回业务错误码 `1001`，拒绝创建任务。
7. Where VIP 配额限制特性已启用，the Test Suite shall 验证 Free 用户提交超出配额的回测请求时系统返回相应错误码。
8. The Test Suite shall 验证回测结果数据在数据库中正确持久化，且后续查询可读取相同数据。

---

### 需求 4: 交易信号接口测试

**目标：** 作为质量保障工程师，我希望验证交易信号的读取接口和权限控制，以便确保信号数据展示符合会员等级规则。

#### 验收标准

1. When 任意用户调用 `GET /api/v1/strategies/{id}/signals`，the Test Suite shall 验证响应返回最新缓存的交易信号（buy/sell/hold），且 HTTP 状态码为 200。
2. When 匿名用户请求信号数据，the Test Suite shall 验证响应仅包含基础信号字段，不包含高级字段（如可信度评分）。
3. When VIP 用户请求信号数据，the Test Suite shall 验证响应包含完整信号字段，包括可信度评分等高级指标。
4. If 信号缓存中不存在指定策略和交易对的数据，the Test Suite shall 验证系统返回空列表或适当提示，而非 500 错误。
5. The Test Suite shall 验证信号接口响应时间满足性能要求（P95 响应时间不超过 500ms），因为信号数据来自缓存（数据库/Redis）而非实时计算。

---

### 需求 5: AI 市场研报接口测试

**目标：** 作为质量保障工程师，我希望验证研报的列表与详情接口支持匿名访问，以便确保科普内容对所有用户可用。

#### 验收标准

1. When 匿名用户调用 `GET /api/v1/reports`，the Test Suite shall 验证系统正常返回研报列表，HTTP 状态码为 200，无需认证头部。
2. When 匿名用户调用 `GET /api/v1/reports/{id}` 获取研报详情，the Test Suite shall 验证返回完整研报内容且不要求登录。
3. When 请求不存在的研报 ID，the Test Suite shall 验证系统返回适当错误码（非 500），HTTP 状态码为 404。
4. When 研报列表接口被调用，the Test Suite shall 验证响应包含标准分页结构，与其他列表接口保持一致。
5. The Test Suite shall 验证研报接口响应符合统一信封格式。

---

### 需求 6: 请求参数校验与错误响应测试

**目标：** 作为质量保障工程师，我希望验证所有接口的参数校验逻辑和错误响应格式，以便确保系统对非法输入的健壮性。

#### 验收标准

1. When 请求体包含缺失的必填字段，the Test Suite shall 验证系统返回业务错误码 `2001`，且响应体中包含具体的字段校验失败信息。
2. When 请求体包含类型错误的字段（如字符串传入整型字段），the Test Suite shall 验证系统返回 `2001` 错误码，HTTP 状态码为 422。
3. If FastAPI 触发 `RequestValidationError`，the Test Suite shall 验证全局异常处理器将其转换为统一信封格式（`code: 2001`），而非 FastAPI 默认的 422 响应格式。
4. When 路径参数包含非数字字符（如 `GET /api/v1/strategies/abc`），the Test Suite shall 验证系统返回参数校验错误而非 500 服务端错误。
5. The Test Suite shall 验证所有错误响应（4xx、5xx）均符合统一 JSON 信封格式（`code`、`message`、`data` 字段），不暴露 Python 堆栈跟踪信息。

---

### 需求 7: freqtrade 集成边界测试

**目标：** 作为质量保障工程师，我希望验证 freqtrade 集成层的异常隔离和超时处理，以便确保 freqtrade 故障不影响主服务稳定性。

#### 验收标准

1. If freqtrade 子进程执行超时（超过 600 秒），the Test Suite shall 验证系统将任务标记为 `FAILED`，返回 `code: 5001`，且主进程不被阻塞。
2. If freqtrade 执行返回非零退出码，the Test Suite shall 验证系统捕获 `FreqtradeExecutionError` 并转化为业务错误，不向客户端暴露原始错误信息。
3. When 回测任务完成后，the Test Suite shall 验证系统自动清理临时工作目录（`/tmp/freqtrade_jobs/{user_id}/{task_id}/`）。
4. While freqtrade Worker 不可用，the Test Suite shall 验证 Web 服务接口仍可正常响应（策略查询、研报读取等非回测功能不受影响）。
5. The Test Suite shall 验证不同用户的 freqtrade 配置文件存储在各自独立的目录中，不存在路径冲突或配置互相覆盖的风险。

---

### 需求 8: 测试基础设施与测试数据管理

**目标：** 作为质量保障工程师，我希望建立稳定、可重复运行的测试环境和测试数据管理机制，以便确保测试结果可靠且不污染生产数据。

#### 验收标准

1. The Test Suite shall 使用独立的测试数据库（PostgreSQL），每次集成测试运行前通过 Alembic 迁移初始化 Schema，测试结束后完整清理数据。
2. The Test Suite shall 使用 `httpx.AsyncClient` 配合 `ASGITransport` 对 FastAPI 路由进行异步 HTTP 测试，不依赖真实网络端口。
3. When 单元测试需要调用外部依赖（数据库、Redis、freqtrade），the Test Suite shall 使用 mock/patch 机制隔离外部依赖，确保单元测试在无外部服务环境下可运行。
4. The Test Suite shall 提供 Fixtures 用于创建测试用户（匿名、Free、VIP1、VIP2），并生成对应的有效 JWT 令牌，供各测试用例复用。
5. When 测试数据库连接不可用，the Test Suite shall 将集成测试标记为跳过（skip），并输出明确的跳过原因，而非触发断言失败。
6. The Test Suite shall 支持通过 `make test` 命令在 CI 环境中运行，所有测试应在合理时间（单次全量运行不超过 5 分钟）内完成。
7. The Test Suite shall 在 `tests/unit/` 目录下组织纯单元测试，在 `tests/integration/` 目录下组织集成测试，目录结构与 `src/` 层次对应。
8. If 测试运行期间出现未预期的异常，the Test Suite shall 输出包含足够诊断信息的错误报告，便于定位问题根源。
