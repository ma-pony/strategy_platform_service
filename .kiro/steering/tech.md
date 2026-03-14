# Technology Stack

## Architecture

FastAPI 异步 Web 服务，分层架构：路由层（FastAPI routers）→ 服务层（业务逻辑）→ 数据层（SQLAlchemy ORM）。freqtrade 集成在独立的 Worker 层，通过任务队列或子进程与主线程解耦，避免阻塞 Web 事件循环。sqladmin 挂载在同一 FastAPI 应用上，与 SQLAlchemy 模型直接绑定。

## Core Technologies

- **Language**: Python 3.10+（目前脚手架使用 3.11，业务代码最低兼容 3.10）
- **Web Framework**: FastAPI（异步，自动生成 OpenAPI 文档）
- **ORM**: SQLAlchemy 2.x（声明式模型，异步 session 或同步 session 按场景选择）
- **Admin UI**: sqladmin（基于 SQLAlchemy 模型，挂载至 FastAPI）
- **Quantitative Engine**: freqtrade（作为底层引擎，不直接暴露于 Web 层）
- **Database**: PostgreSQL（主存储，通过 SQLAlchemy 2.x 异步/同步驱动访问）
- **Cache/Queue**: Redis（信号缓存、Celery broker、会话等临时数据）
- **Package Manager**: uv 0.5+（依赖锁定通过 `uv.lock`）

## Key Libraries

- **pydantic / pydantic-settings** (`>=2.0`): 请求/响应 Schema 校验、多环境配置
- **asyncpg**: PostgreSQL 异步驱动（配合 SQLAlchemy async engine）
- **psycopg2-binary**: PostgreSQL 同步驱动（配合 sqladmin / Alembic）
- **redis / redis[hiredis]**: Redis 客户端（信号缓存读写）
- **python-jose 或 PyJWT**: JWT 令牌签发与校验
- **passlib + bcrypt**: 密码哈希
- **structlog** (`>=24.0`): 结构化日志，开发彩色 / 生产 JSON
- **alembic**: 数据库迁移，与 SQLAlchemy + PostgreSQL 配合使用
- **celery**: freqtrade 回测/信号任务的异步调度，以 Redis 为 broker

## Development Standards

### Type Safety
mypy strict 模式，所有函数须有完整类型注解。FastAPI 的 Depends 注入函数同样需要标注返回类型。

### Code Quality
Ruff（E/F/I 规则集，line-length 88）负责 lint 和格式化，pre-commit 在提交时自动执行。`make check` = lint + typecheck。

### Testing
pytest，`tests/unit/` 对应单元测试，`tests/integration/` 对应集成测试（含数据库）。FastAPI 路由测试使用 `httpx.AsyncClient` + `ASGITransport`。

## Development Environment

### Common Commands
```bash
# Install: make install        (uv sync)
# Run:     make run            (uvicorn src.main:app --reload)
# Test:    make test           (uv run pytest)
# Lint:    make lint           (uv run ruff check src/ tests/)
# Format:  make format         (uv run ruff format src/ tests/)
# Types:   make typecheck      (uv run mypy src/)
# All QA:  make check          (lint + typecheck)
# Migrate: make migrate        (alembic upgrade head)
```

## Key Technical Decisions

- **FastAPI over Flask/Django**: 原生异步支持、自动 OpenAPI、Pydantic 集成是量化 API 场景的首选
- **SQLAlchemy 2.x 声明式**: 与 sqladmin 兼容性最佳，迁移由 alembic 管理
- **freqtrade 非阻塞集成**: 回测等长耗时任务必须在 Web 事件循环之外执行（子进程或 Celery worker），结果异步写回数据库
- **JWT 无状态鉴权**: 后端无需维护 Session，适合 API-first 架构，VIP 等级编码在 token claims 中
- **uv 而非 pip/poetry**: 统一依赖管理，`uv.lock` 锁定版本

---
_updated_at: 2026-03-14 — 引入 FastAPI / SQLAlchemy / sqladmin / freqtrade / JWT 技术栈，替换无框架脚手架描述_
