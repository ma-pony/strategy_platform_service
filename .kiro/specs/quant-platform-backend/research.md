# 研究与设计决策

---
**功能**: `quant-platform-backend`
**探索范围**: 复杂新功能（Complex New Feature — Greenfield）
**关键发现**:
- Pydantic v2 的 `model_serializer` + 序列化上下文（`SerializationInfo`）是实现字段级权限过滤的最优方案，避免在业务层硬编码字段可见性
- freqtrade 回测必须通过 Celery Worker 子进程执行，任务状态需持久化至 PostgreSQL 供 API 轮询
- sqladmin 与 FastAPI 的集成需要两套独立的 SQLAlchemy engine（异步 engine 用于 Web 层，同步 engine 用于 sqladmin）

---

## 研究日志

### 主题：FastAPI + Celery + Redis 集成模式

- **背景**: 需要为 freqtrade 回测和信号生成提供异步任务队列，避免阻塞 FastAPI 事件循环
- **参考来源**:
  - [Production-Ready Background Task Processing: Celery, Redis, and FastAPI Integration Guide 2024](https://python.elitedev.in/python/production-ready-background-task-processing-celery-redis-and-fastapi-integration-guide-2024-80ddc2f9/)
  - [Celery + Redis + FastAPI: The Ultimate 2025 Production Guide](https://medium.com/@dewasheesh.rana/celery-redis-fastapi-the-ultimate-2025-production-guide-broker-vs-backend-explained-5b84ef508fa7)
- **发现**:
  - Celery 使用 Redis 作为 Broker（接收任务）和 Result Backend（存储任务状态）
  - FastAPI 端点应立即返回 `task_id`，客户端轮询状态；禁止同步等待任务完成
  - Celery Beat 配合 Redis broker 可实现周期性调度（定时回测、定时信号生成）
  - 长耗时任务与短耗时任务应分配至不同队列和 Worker，提升吞吐量
  - `sqlalchemy-celery-beat` 可将周期任务调度存储在 PostgreSQL，支持动态调整
- **影响**: 回测任务使用 Celery 队列（`backtest` 专用队列），信号生成任务使用独立队列（`signal` 队列），Worker 隔离互不影响

---

### 主题：sqladmin 与 FastAPI 的同步/异步 engine 集成

- **背景**: sqladmin 的 `Admin` 类要求传入 SQLAlchemy engine，且其内部使用同步 session；而 FastAPI Web 层使用异步 engine
- **参考来源**:
  - [sqladmin 官方仓库](https://github.com/aminalaee/sqladmin)
  - [SQLAlchemy Admin for Starlette/FastAPI 文档](https://aminalaee.github.io/sqladmin/)
- **发现**:
  - sqladmin 支持传入同步或异步 engine，但在生产实践中，为避免意外，推荐 sqladmin 使用独立的同步 engine（`psycopg2` 驱动），Web 层保持异步 engine（`asyncpg` 驱动）
  - `AuthenticationBackend` 可实现独立于 JWT 体系的管理员认证（Session cookie 方式）
  - `can_delete = False` 可禁用特定模型的后台删除操作
- **影响**: 在 `src/admin/__init__.py` 中创建独立的同步 engine 实例，不与 `src/core/deps.py` 的异步 engine 共享

---

### 主题：Pydantic v2 字段级权限控制

- **背景**: 需要根据用户会员等级（匿名 / Free / VIP1/VIP2）动态过滤响应字段，要求在序列化层而非业务层实现
- **参考来源**:
  - [Pydantic v2 Serialization 文档](https://docs.pydantic.dev/latest/concepts/serialization/)
  - [Pydantic Issues: Dynamically include/exclude fields](https://github.com/pydantic/pydantic/issues/9528)
- **发现**:
  - Pydantic v2 的 `@model_serializer(mode='wrap')` 结合 `SerializationInfo.context` 可在序列化时获取上下文参数（如会员等级），动态决定字段是否出现在输出中
  - 另一种方案是使用 FastAPI 的 `response_model_include/exclude` 参数，但该方案需在每个路由硬编码，维护性差
  - 推荐方案：在 Pydantic Schema 中定义字段的可见等级元数据（通过 `Field` 的 `json_schema_extra` 或自定义注解），再通过 `@model_serializer` 根据 `context["membership"]` 动态过滤
- **影响**: `StrategyRead`、`BacktestResultRead`、`SignalRead` 等响应 Schema 需实现 `@model_serializer`，路由层在调用 `.model_dump(context={"membership": user.membership})` 时传入会员等级上下文

---

### 主题：freqtrade 回测子进程隔离

- **背景**: freqtrade 回测是 CPU 密集型长耗时任务，必须在 FastAPI 事件循环外执行
- **参考来源**:
  - [freqtrade Backtesting 文档](https://www.freqtrade.io/en/stable/backtesting/)
  - [Celery Task Isolation Best Practices](https://deepnote.com/blog/ultimate-guide-to-celery-library-in-python)
- **发现**:
  - 推荐通过 `subprocess.run(["freqtrade", "backtesting", ...])` 在独立进程运行，进程隔离保证主 Worker 不受 freqtrade 崩溃影响
  - 每次回测需在隔离目录生成 freqtrade 配置文件，任务完成后清理
  - 超时设置（600 秒）防止单次回测无限阻塞 Worker
  - Celery 任务的幂等性：回测任务以 `strategy_id + 时间窗口` 作为唯一键，避免重复提交
- **影响**: `BacktestTask` 模型记录任务状态（PENDING → RUNNING → DONE | FAILED），`freqtrade_bridge/backtester.py` 封装子进程调用逻辑

---

## 架构模式评估

| 选项 | 描述 | 优势 | 风险/限制 | 备注 |
|------|------|------|-----------|------|
| 分层架构（当前方案） | API → Service → Model，freqtrade 封装在 bridge 层 | 清晰单向依赖，可独立测试各层 | 层间接口需明确定义 | 与 steering.structure.md 完全对齐 |
| 六边形架构 | 端口/适配器，核心域与外部系统解耦 | 可测试性极佳 | 额外的适配器层增加复杂度 | 当前项目规模不需要此复杂度 |
| 微服务 | 将 Auth/Strategy/Backtest 拆分为独立服务 | 独立部署和扩缩容 | 运维复杂度大幅上升，不适合当前阶段 | 未来扩展时可考虑 |

**选定方案**: 分层架构（与 steering 完全一致）

---

## 设计决策

### 决策：Pydantic Schema 字段级权限实现方式

- **背景**: 需求 2.3–2.5、2.9 要求根据会员等级动态过滤响应字段，且不在业务层硬编码
- **备选方案**:
  1. 每个会员等级定义独立 Schema 类（`StrategyReadAnonymous`, `StrategyReadFree`, `StrategyReadVIP`）
  2. 使用 Pydantic v2 `@model_serializer` + 序列化上下文动态过滤字段
  3. 路由层使用 `response_model_include` 参数按等级传入字段集
- **选定方案**: 方案 2（`@model_serializer` + 序列化上下文）
- **理由**: 字段过滤逻辑集中在 Schema 层，路由层只需传入 `context={"membership": tier}`，无需在路由或服务层维护字段列表；符合需求 2.9 要求
- **权衡**: 需要在 Schema 中定义每个字段的最低可见等级（通过 `Field` 元数据），初始实现稍复杂，但后续新增字段时只需修改 Schema 声明
- **后续**: 实现时验证 `@model_serializer(mode='wrap')` 的序列化上下文传递是否兼容 FastAPI 的 `response_model` 机制

---

### 决策：Celery vs ProcessPoolExecutor 用于 freqtrade 任务

- **背景**: 需求 4.1–4.2 要求系统级定时回测，禁止在 Web 线程执行
- **备选方案**:
  1. Celery + Redis Broker（分布式，支持 Beat 调度，任务状态持久化）
  2. `asyncio.ProcessPoolExecutor`（轻量，无额外中间件）
  3. APScheduler（纯 Python 调度库，不依赖 Redis）
- **选定方案**: Celery + Redis（与 steering.tech.md 的技术选型一致）
- **理由**: 项目已将 Redis 列为必选组件，Celery Beat 提供开箱即用的周期调度，任务状态和重试机制成熟；`ProcessPoolExecutor` 无法跨节点水平扩展
- **权衡**: 需要运行独立的 Celery Worker 和 Celery Beat 进程，增加部署复杂度，但与团队已有认知一致

---

### 决策：sqladmin 双 engine 策略

- **背景**: 需求 8.8 明确要求 sqladmin 使用同步 engine
- **备选方案**:
  1. sqladmin 复用 Web 层异步 engine（可能存在兼容性问题）
  2. sqladmin 使用独立同步 engine（`psycopg2` 驱动）
- **选定方案**: 方案 2（独立同步 engine）
- **理由**: sqladmin 内部对 session 的使用以同步为主，使用异步 engine 可能引发意外行为；独立 engine 避免连接池污染
- **权衡**: 需维护两套 engine 配置（`DATABASE_URL` 用于异步，`DATABASE_SYNC_URL` 用于同步），但逻辑清晰

---

## 风险与缓解措施

- **freqtrade 配置文件安全性** — 每个任务使用隔离目录，任务结束后立即清理，目录权限设为仅 Worker 可读写
- **Redis 信号缓存失效** — 若 Redis 不可用，信号接口回退至直接读取 PostgreSQL 最近一条历史记录，并在响应中标注 `last_updated_at`（需求 5.4）
- **Celery Worker 崩溃** — 配置 `acks_late=True` 和 `max_retries=3`，任务被 ack 前 Worker 崩溃时自动重新入队
- **会员等级 JWT 过期** — access_token 有效期 30 分钟，会员等级变更后旧 token 在过期前仍有效；可接受（平台科普展示场景，非金融实时交易）
- **sqladmin 暴露管理员入口** — `AuthenticationBackend` 使用强密码 + 独立会话 cookie，建议生产环境通过 IP 白名单或 VPN 限制 `/admin` 路径访问

---

## 参考资料

- [FastAPI 官方文档](https://fastapi.tiangolo.com/) — Web 框架核心参考
- [SQLAlchemy 2.x 文档](https://docs.sqlalchemy.org/en/20/) — ORM 和 engine 配置
- [sqladmin 文档](https://aminalaee.github.io/sqladmin/) — Admin UI 集成
- [Celery 5.x 文档](https://docs.celeryq.dev/en/stable/) — 任务队列和 Beat 调度
- [Pydantic v2 Serialization](https://docs.pydantic.dev/latest/concepts/serialization/) — 字段级序列化控制
- [freqtrade Backtesting](https://www.freqtrade.io/en/stable/backtesting/) — 回测引擎参数和输出格式
- [python-jose 文档](https://python-jose.readthedocs.io/) — JWT 签发与校验
- [passlib 文档](https://passlib.readthedocs.io/) — bcrypt 密码哈希
