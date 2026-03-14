# 实施计划

- [x] 1. 项目基础设施与核心共享层
- [x] 1.1 建立枚举类型与基础配置
  - 在核心层定义 `MembershipTier`（FREE / VIP1 / VIP2）、`TaskStatus`（PENDING / RUNNING / DONE / FAILED）、`SignalDirection`（BUY / SELL / HOLD）三组枚举
  - 配置 `pydantic-settings` 读取环境变量（`SECRET_KEY`、`DATABASE_URL`、`DATABASE_SYNC_URL`、`REDIS_URL` 等），所有敏感配置禁止硬编码
  - 建立 structlog 结构化日志初始化逻辑，开发环境输出彩色日志，生产环境输出 JSON 格式
  - _Requirements: 2.1_

- [x] 1.2 实现统一响应信封与错误码体系
  - 实现 `ApiResponse` 泛型模型（含 `code`、`message`、`data` 字段）和 `PaginatedData` 分页结构
  - 实现 `ok()`、`fail()`、`paginated()` 响应构造工具函数
  - 定义 `AppError` 基类及子类：`AuthenticationError(1001)`、`PermissionError(1002/1003)`、`ValidationError(2001)`、`NotFoundError(3001)`、`ConflictError(3002)`、`FreqtradeError(5001)`
  - 注册全局异常处理器：将 Pydantic `RequestValidationError(422)` 转换为 `code:2001` 信封格式，将 `AppError` 转换为对应 HTTP 状态码的信封格式，兜底处理未捕获异常为 `code:5000`
  - _Requirements: 9.1, 9.2, 9.3, 9.6_

- [x] 1.3 实现 JWT 安全工具
  - 实现 `create_access_token`（有效期 30 分钟）和 `create_refresh_token`（有效期 7 天）
  - JWT claims 必须包含 `sub`（用户 ID）、`membership`、`exp`、`iat`、`type` 五个字段
  - 实现 `decode_token`：校验签名、过期时间和 `type` 字段（防止 refresh token 被用于接口调用），失败时抛出 `AuthenticationError(1001)`
  - 实现 `hash_password` 和 `verify_password`（bcrypt），禁止在任何日志中记录明文密码
  - _Requirements: 1.7, 1.8_

- [x] 1.4 实现 FastAPI 依赖注入函数
  - 实现 `get_db`：异步 session 生命周期管理，基于 `asyncpg` 的异步 engine（`pool_size=10, max_overflow=20`）
  - 实现 `get_current_user`：从 Bearer token 解析用户 ID，**从数据库实时查询**用户的 `membership` 和 `is_active`（不信任 JWT claims 中的 membership），`is_active=False` 时抛出 `AuthenticationError(1001)`
  - 实现 `get_optional_user`：宽松鉴权，无 token 或 token 无效时返回 `None`，不拦截请求；携带有效 token 时同样从数据库实时读取用户状态
  - 实现 `require_membership(min_tier)` 工厂函数，以数据库用户对象的 `membership` 字段为准执行等级校验，不足时抛出 `PermissionError(1003)`
  - _Requirements: 1.8, 2.6, 2.7, 2.8_

- [x] 2. 数据模型层与数据库迁移
- [x] 2.1 (P) 建立 SQLAlchemy 基础模型与公共 Mixin
  - 定义 `DeclarativeBase` 子类 `Base` 作为所有模型的基类
  - 实现 `TimestampMixin`：自动维护 `created_at` 和 `updated_at` 字段，所有时间列使用 `DateTime(timezone=True)`（UTC 存储）
  - 配置 Alembic `env.py` 指向 `Base.metadata`，使用同步 engine（psycopg2）执行迁移
  - _Requirements: 6.2, 6.4_

- [x] 2.2 (P) 实现用户与策略数据模型
  - 实现 `User` 模型：`id`（主键）、`username`（唯一约束 + 索引）、`hashed_password`、`membership`（枚举默认 FREE）、`is_active`（默认 True）+ `TimestampMixin`
  - 实现 `Strategy` 模型：`id`、`name`（唯一）、`description`、`strategy_type`、`pairs`（JSON 列）、`config_params`（JSON 列）、`is_active`（默认 True，索引）+ `TimestampMixin`
  - 创建 Alembic 迁移 `001_create_users` 和 `002_create_strategies`，各含 `upgrade()` 和 `downgrade()`
  - _Requirements: 1.1, 2.1, 3.3_

- [x] 2.3 (P) 实现回测相关数据模型
  - 实现 `BacktestTask` 模型：`id`、`strategy_id`（外键）、`scheduled_date`、`status`（TaskStatus 枚举）、`error_message`；联合唯一约束 `(strategy_id, scheduled_date)` 防止同日重复；建立 `idx_btask_strategy_status` 索引
  - 实现 `BacktestResult` 模型：`id`、`strategy_id`（外键）、`task_id`（外键）、`total_return`、`annual_return`、`sharpe_ratio`、`max_drawdown`、`trade_count`、`win_rate`、`period_start`、`period_end`、`created_at`；建立 `idx_bresult_strategy_id` 和 `idx_bresult_created_at` 索引
  - 创建 Alembic 迁移 `003_create_backtest_tables`
  - _Requirements: 4.3, 4.4_

- [x] 2.4 (P) 实现交易信号与研报数据模型
  - 实现 `TradingSignal` 模型：`id`、`strategy_id`（外键）、`pair`、`direction`（SignalDirection 枚举）、`confidence_score`、`signal_at`（timezone=True）、`created_at`；建立 `idx_signal_strategy_at DESC` 索引
  - 实现 `ResearchReport` 模型：`id`、`title`、`summary`（Text）、`content`（Text）、`generated_at`（timezone=True）+ `TimestampMixin`；建立 `idx_report_generated_at DESC` 索引
  - 实现 `ReportCoin` 关联表：`id`、`report_id`（外键）、`coin_symbol`；建立 `idx_reportcoin_report_id` 索引
  - 创建 Alembic 迁移 `004_create_trading_signals` 和 `005_create_research_reports`
  - _Requirements: 5.1, 6.1, 6.3, 6.4_

- [x] 3. 用户认证体系
- [x] 3.1 实现用户注册与登录业务逻辑
  - 实现注册逻辑：查询用户名是否已存在，存在时抛出 `ValidationError(code=2001)`；密码以 bcrypt 哈希存储；新用户会员等级初始化为 FREE
  - 实现登录逻辑：查询用户、校验 bcrypt 哈希，凭证错误时抛出 `AuthenticationError(code=1001)`；校验通过后签发 access_token + refresh_token
  - 实现 token 刷新逻辑：校验 refresh_token 的类型（`type == "refresh"`）和有效性，失败时抛出 `AuthenticationError(code=1001)`，成功后签发新 access_token
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6_

- [x] 3.2 实现认证 API 路由
  - 实现 `POST /api/v1/auth/register`：接受 `{username, password}`，成功返回 `code:0` 及 `{id, username, membership, created_at}`，用户名重复返回 `code:2001` HTTP 400
  - 实现 `POST /api/v1/auth/login`：接受 `{username, password}`，成功返回 `code:0` 及 `{access_token, refresh_token, token_type}`，凭证错误返回 `code:1001` HTTP 401
  - 实现 `POST /api/v1/auth/refresh`：接受 `{refresh_token}`，成功返回 `code:0` 及 `{access_token, token_type}`，token 无效或过期返回 `code:1001` HTTP 401
  - 所有路由响应符合统一信封格式，URL 前缀为 `/api/v1`
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 9.1, 9.5_

- [x] 4. Pydantic Schema 字段级权限控制
- [x] 4.1 实现带权限过滤的响应 Schema
  - 定义字段等级层次顺序：`[None（匿名）, FREE, VIP1, VIP2]`
  - 实现 `StrategyRead` Schema：匿名可见字段（`id`、`name`、`description`、`pairs`、`strategy_type`）、Free 可见字段（`trade_count`、`max_drawdown`）、VIP 专属字段（`sharpe_ratio`、`win_rate`、`confidence_score`）；通过 `Field(json_schema_extra={"min_tier": "..."})` 声明各字段最低可见等级
  - 实现 `BacktestResultRead` Schema：同等级划分逻辑，Free 字段含 `total_return`、`trade_count`、`max_drawdown`，VIP 字段含 `sharpe_ratio`、`win_rate`、`annual_return`
  - 实现 `SignalRead` Schema：所有用户可见 `direction`、`signal_at`，VIP 专属 `confidence_score`（匿名/Free 不返回或返回 `null`）
  - 在各 Schema 上通过 `@model_serializer(mode='wrap')` 读取 `SerializationInfo.context["membership"]` 动态过滤字段；未提供 context 时以匿名等级处理
  - _Requirements: 2.3, 2.4, 2.5, 2.9_

- [x] 4.2 实现用户与研报的普通响应 Schema
  - 实现 `UserRead` Schema（`id`、`username`、`membership`、`created_at`），用于注册响应
  - 实现 `ReportRead`（列表摘要：`id`、`title`、`summary`、`generated_at`、`related_coins`）和 `ReportDetailRead`（含完整 `content` 字段）Schema
  - 实现 `PaginatedResponse` 泛型 Schema（`items`、`total`、`page`、`page_size`），`page_size` 默认 20，最大 100
  - _Requirements: 9.4, 7.1, 7.2_

- [x] 5. 策略服务与 API
- [x] 5.1 实现策略只读业务逻辑
  - 实现策略分页列表查询（`limit + offset` 分页，禁止全表扫描）
  - 实现策略详情查询，使用 `selectinload` 同时加载最近一次成功回测结果，避免 N+1 查询
  - 策略 ID 不存在时抛出 `NotFoundError(code=3001)`；不提供任何写入方法
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_

- [x] 5.2 实现策略 API 路由（含字段权限过滤）
  - 实现 `GET /api/v1/strategies`：接受 `?page=1&page_size=20`，匿名和已登录用户均可访问，通过 `get_optional_user` 注入可选用户，返回 `PaginatedData[StrategyRead]` 信封响应
  - 实现 `GET /api/v1/strategies/{id}`：同上注入可选用户，调用 `.model_dump(context={"membership": user.membership if user else None})` 实现字段级权限过滤，策略不存在返回 `code:3001` HTTP 404
  - _Requirements: 3.1, 3.2, 3.4, 3.5, 2.3, 2.4, 2.5, 9.1, 9.4, 9.5_

- [x] 6. freqtrade 集成层
- [x] 6.1 实现回测子进程封装
  - 实现配置文件生成器：在 `/tmp/freqtrade_jobs/{task_id}/` 隔离目录下生成 freqtrade 配置 JSON，包含策略配置参数，不含交易所 API Key
  - 实现 `run_backtest_subprocess`：通过 `subprocess.run` 执行 freqtrade CLI，超时 600 秒，非零退出码时抛出 `FreqtradeExecutionError`，超时时抛出 `FreqtradeTimeoutError`
  - 实现隔离目录清理函数，在任务完成或失败后通过 `finally` 块清理，防止临时文件堆积
  - 所有 freqtrade 原始 stderr 记录至结构化日志，对外只抛出封装后的异常，不暴露原始 traceback
  - _Requirements: 4.2, 4.7_

- [x] 6.2 实现信号获取进程池封装
  - 实现 `fetch_signals`：通过 `ProcessPoolExecutor(max_workers=2)` 在独立进程中调用 freqtrade 信号逻辑，返回信号字典
  - 在独立进程中导入 freqtrade 模块，避免污染主进程的事件循环
  - 失败时抛出 `FreqtradeExecutionError`，不向调用方暴露 freqtrade 内部错误细节
  - _Requirements: 5.5_

- [x] 7. Celery 异步任务体系
- [x] 7.1 初始化 Celery 应用与队列配置
  - 初始化 Celery 应用，以 Redis 同时作为 broker 和 result backend
  - 配置两条独立队列：`backtest` 队列（处理回测任务，`concurrency=2`）和 `signal` 队列（处理信号生成任务），避免长耗时回测阻塞信号更新
  - 配置 Celery Beat 定时计划：回测任务（`0 2 * * *`，每日 UTC 02:00）、信号生成任务（`*/15 * * * *`，每 15 分钟）
  - _Requirements: 4.1, 4.8, 5.5_

- [x] 7.2 实现回测 Celery 任务
  - 实现 `run_backtest_task(strategy_id)` Celery 任务：配置 `acks_late=True`、`max_retries=3`、超时 600 秒
  - 任务启动时查询当日是否已有 RUNNING/DONE 状态记录（基于 `uq_btask_strategy_date` 唯一约束），存在则跳过（幂等设计）
  - 任务状态流转：创建 `BacktestTask(status=PENDING)` → 更新为 RUNNING → 调用 `FreqtradeBridge.run_backtest_subprocess` → 成功时创建 `BacktestResult` 并更新 Task 为 DONE，失败时写入 `error_message` 并更新 Task 为 FAILED
  - 回测失败不影响其他策略的调度，使用同步 SQLAlchemy session（Celery Worker 不使用异步 session）
  - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.7, 4.8_

- [x] 7.3 实现信号生成 Celery 任务
  - 实现 `generate_signals_task(strategy_id, pair)` Celery 任务，定期触发
  - 调用 `FreqtradeBridge.fetch_signals` 获取信号数据，将结果以 JSON 格式写入 Redis key `signal:{strategy_id}`（TTL 3600 秒），同时持久化新 `TradingSignal` 历史记录至 PostgreSQL
  - 信号生成失败时记录 WARNING 日志，不影响历史缓存数据的可用性
  - _Requirements: 5.3, 5.5_

- [x] 8. 回测服务与 API
- [x] 8.1 实现回测结果只读业务逻辑
  - 实现按 `strategy_id` 过滤的回测结果分页查询，按 `created_at` 降序排列
  - 实现单条回测结果查询，不存在时抛出 `NotFoundError(code=3001)`
  - 不提供任何触发回测的方法；业务层不直接调用 freqtrade
  - _Requirements: 4.3, 4.5, 4.6, 4.8_

- [x] 8.2 实现回测 API 路由（含字段权限过滤）
  - 实现 `GET /api/v1/strategies/{id}/backtests`：接受 `?page&page_size`，通过 `get_optional_user` 注入可选用户，返回 `PaginatedData[BacktestResultRead]`（字段按会员等级过滤），策略不存在返回 `code:3001` HTTP 404
  - 实现 `GET /api/v1/backtests/{id}`：通过 `get_optional_user` 注入可选用户，返回完整回测详情（字段按会员等级过滤），不存在返回 `code:3001` HTTP 404
  - _Requirements: 4.5, 4.6, 2.3, 2.4, 2.5, 9.1, 9.4, 9.5_

- [x] 9. 交易信号服务与 API
- [x] 9.1 实现信号查询业务逻辑
  - 实现信号查询：优先读取 Redis key `signal:{strategy_id}`，缓存未命中时回退至 PostgreSQL 最近信号记录
  - Redis 不可用时静默回退至数据库，记录 WARNING 日志，不向客户端暴露缓存错误；响应中必须携带 `last_updated_at` 字段标注数据时效
  - 策略不存在时抛出 `NotFoundError(code=3001)`
  - _Requirements: 5.1, 5.4, 5.6_

- [x] 9.2 实现信号 API 路由（含字段权限过滤）
  - 实现 `GET /api/v1/strategies/{id}/signals`：接受 `?limit=20`，通过 `get_optional_user` 注入可选用户，VIP 用户响应含 `confidence_score`，匿名和 Free 用户该字段不返回或返回 `null`
  - 响应结构含 `signals` 列表和 `last_updated_at` 时效字段；策略不存在返回 `code:3001` HTTP 404
  - _Requirements: 5.1, 5.2, 5.4, 5.6, 9.1, 9.5_

- [x] 10. AI 市场研报服务与 API
- [x] 10.1 实现研报只读业务逻辑
  - 实现研报分页列表查询（`limit + offset`，按 `generated_at` 降序）；查询结果包含关联 `ReportCoin` 的币种信息（使用 `selectinload` 避免 N+1）
  - 实现单条研报详情查询（含完整 `content` 字段），研报不存在时抛出 `NotFoundError(code=3001)`
  - 所有方法均不执行任何写入操作
  - _Requirements: 6.1, 6.2, 6.3, 7.1, 7.2, 7.3, 7.4_

- [x] 10.2 实现研报 API 路由
  - 实现 `GET /api/v1/reports`：接受 `?page=1&page_size=20`，允许匿名访问（路由不使用 `get_current_user`），返回 `PaginatedData[ReportRead]`（含 `id`、`title`、`summary`、`generated_at`、`related_coins`）
  - 实现 `GET /api/v1/reports/{id}`：允许匿名访问，返回 `ReportDetailRead`（含完整 `content`），研报不存在返回 `code:3001` HTTP 404
  - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 9.1, 9.4, 9.5_

- [x] 11. sqladmin 管理后台
- [x] 11.1 实现管理员认证机制
  - 实现独立的 `AdminAuth` 认证后端（`AuthenticationBackend`），管理员账户完全独立于普通用户表
  - 实现管理员登录、登出逻辑，使用 Session cookie 机制，与普通用户 JWT 体系完全隔离
  - 未认证请求访问 `/admin` 路径时自动重定向至 `/admin/login`
  - _Requirements: 8.6, 8.7_

- [x] 11.2 实现各模型管理视图
  - 实现 `UserAdmin`（ModelView for User）：展示列包含 `username`、`membership`、`is_active`、`created_at`，支持按 `username` 搜索、按 `created_at` 排序，允许编辑 `membership` 和 `is_active` 字段，设置 `can_delete=False` 禁止后台删除用户
  - 实现 `StrategyAdmin`（ModelView for Strategy）：支持创建、编辑（名称、描述、配置参数、启用状态），作为维护策略数据的唯一入口
  - 实现 `ReportAdmin`（ModelView for ResearchReport）：支持列表展示、创建、编辑，支持按标题搜索、按生成时间排序
  - _Requirements: 8.2, 8.3, 8.4, 8.5, 8.9_

- [x] 11.3 初始化 sqladmin 并挂载至 FastAPI
  - 创建独立同步 SQLAlchemy engine（`psycopg2` 驱动，`pool_size=5`），不复用 Web 层的异步 engine
  - 初始化 `Admin` 实例，注册 `UserAdmin`、`StrategyAdmin`、`ReportAdmin` 三个视图，挂载至 FastAPI app 的 `/admin` 路径
  - _Requirements: 8.1, 8.8_

- [x] 12. FastAPI 应用组装与路由集成
- [x] 12.1 组装 FastAPI 主应用
  - 在 `main.py` 中创建 FastAPI 应用实例，配置 `lifespan` 函数管理启动/关闭钩子（数据库连接池初始化、Celery 应用初始化）
  - 注册全局异常处理器（`RequestValidationError`、`AppError`、通用 `Exception`）
  - 挂载所有 API 路由器（auth、strategies、backtests、signals、reports），统一路由前缀 `/api/v1`
  - 挂载 sqladmin 管理后台至 `/admin`
  - _Requirements: 9.1, 9.2, 9.3, 9.5, 9.6_

- [x] 12.2 验证端到端路由与权限链路
  - 手动验证匿名用户访问策略列表和研报接口可正常返回基础字段
  - 手动验证 Free 用户登录后访问策略详情可见中级指标，VIP 用户可见全部高级指标
  - 手动验证禁用用户（`is_active=False`）请求被拦截并返回 `code:1001`
  - 验证所有错误场景（资源不存在、token 过期、参数校验失败）返回正确的信封格式和错误码
  - _Requirements: 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 9.1, 9.2, 9.3_

- [x] 13. 测试
- [x] 13.1 核心安全工具单元测试
  - 验证 `create_access_token` 生成的 JWT claims 包含 `sub`、`membership`、`exp`、`iat`、`type` 五个字段
  - 验证 `decode_token` 在 token 过期、签名无效、`type` 字段不匹配时均抛出 `AuthenticationError`
  - 验证 `hash_password` 和 `verify_password` 的一致性；验证错误密码校验返回 False
  - _Requirements: 1.7, 1.8_

- [x] 13.2 字段级权限序列化单元测试
  - 验证 `StrategyRead.model_dump(context={"membership": None})` 仅返回匿名可见字段，高级字段不出现在输出中
  - 验证 `context={"membership": FREE}` 时额外返回 Free 等级字段
  - 验证 `context={"membership": VIP1}` 时返回全部字段（含 `sharpe_ratio`、`win_rate`、`confidence_score`）
  - 对 `SignalRead` 验证 `confidence_score` 字段在 VIP 时返回、非 VIP 时不返回或为 `null`
  - _Requirements: 2.3, 2.4, 2.5, 2.9_

- [x] 13.3 认证服务单元测试
  - 验证注册逻辑：用户名重复时抛出 `ValidationError(code=2001)`，成功时新用户 membership 为 FREE
  - 验证登录逻辑：密码错误时抛出 `AuthenticationError(code=1001)`
  - 验证 token 刷新：传入 access_token（type 不匹配）时抛出 `AuthenticationError`
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6_

- [x] 13.4 freqtrade bridge 单元测试
  - 使用 mock `subprocess.run` 验证 `run_backtest_subprocess` 在超时时抛出 `FreqtradeTimeoutError`
  - 验证非零退出码时抛出 `FreqtradeExecutionError`，原始 stderr 不被透传给调用方
  - 验证隔离目录在任务结束后（含失败路径）被清理
  - _Requirements: 4.2, 4.7_

- [x] 13.5 认证与策略 API 集成测试
  - 使用 `httpx.AsyncClient + ASGITransport` 对注册、登录、刷新完整 HTTP 流程进行端到端测试
  - 验证匿名 / Free / VIP 三种身份访问策略详情时返回字段的差异（字段可见性差异验证）
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 2.3, 2.4, 2.5_

- [x]* 13.6 回测、信号与研报接口集成测试
  - 验证回测列表和详情接口使用 DB fixture 返回正确分页数据
  - 验证信号接口 Redis 命中路径和回退至 DB 路径均正确处理
  - 验证研报列表和详情接口匿名访问正常，研报不存在时返回 `code:3001`
  - _Requirements: 4.5, 4.6, 5.1, 5.4, 7.1, 7.2, 7.3_
