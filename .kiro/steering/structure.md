# Project Structure

## Organization Philosophy

**分层架构（Layered）**：`src/` 内部按技术职责分层，各层单向依赖（上层可依赖下层，禁止反向）。freqtrade 集成封装在独立的 `src/freqtrade_bridge/` 层，不向上泄漏引擎细节。sqladmin 注册逻辑集中在 `src/admin/`，与业务路由隔离。

```
src/
├── api/          # FastAPI routers（路由层，仅处理 HTTP 协议转换）
├── services/     # 业务逻辑层（无 HTTP 依赖，可独立测试）
├── models/       # SQLAlchemy 声明式模型（数据层）
├── schemas/      # Pydantic 请求/响应 Schema（与 ORM 模型分离）
├── core/         # 跨层共享：异常定义、依赖注入、安全工具
├── admin/        # sqladmin ModelView 注册
├── freqtrade_bridge/  # freqtrade 集成（子进程/RPC 封装）
└── utils/        # 无业务依赖的基础工具（日志等）
config/           # pydantic-settings 多环境配置
tests/
├── unit/         # 纯单元测试（mock 外部依赖）
└── integration/  # 集成测试（真实数据库、HTTP 客户端）
```

## Directory Patterns

### 路由层
**Location**: `src/api/`
**Purpose**: FastAPI `APIRouter` 定义，仅负责参数校验、调用 service、构造统一响应
**Pattern**: 按资源分文件（`users.py`, `strategies.py`, `backtests.py`），统一在 `src/api/__init__.py` 中 `include_router`

### 业务逻辑层
**Location**: `src/services/`
**Purpose**: 核心业务规则，不依赖 FastAPI 或 HTTP，接收 schema 对象，返回 ORM 对象或纯数据
**Pattern**: `{resource}_service.py`，类或函数式均可，但同一资源保持一致

### 数据模型层
**Location**: `src/models/`
**Purpose**: SQLAlchemy `DeclarativeBase` 子类，定义表结构与关系
**Pattern**: `{resource}.py`，模型类名 `PascalCase`（`User`, `Strategy`, `BacktestResult`）

### Schema 层
**Location**: `src/schemas/`
**Purpose**: Pydantic 请求/响应 Schema，与 ORM 模型解耦
**Pattern**: `{resource}.py`，命名后缀区分用途（`UserCreate`, `UserRead`, `UserUpdate`）

### 核心共享层
**Location**: `src/core/`
**Purpose**: 全局异常类、FastAPI `Depends` 注入函数（`get_db`, `get_current_user`）、JWT 工具
**Pattern**: `exceptions.py`, `deps.py`, `security.py`

### Admin 层
**Location**: `src/admin/`
**Purpose**: sqladmin `ModelView` 子类注册，挂载至 FastAPI app
**Pattern**: 每个 SQLAlchemy 模型对应一个 `ModelView`，统一在 `src/admin/__init__.py` 注册

### freqtrade 集成层
**Location**: `src/freqtrade_bridge/`
**Purpose**: 封装所有 freqtrade 交互，对上层服务暴露简单接口，内部处理子进程/RPC/模块导入
**Pattern**: `backtester.py`（回测任务），`signal_fetcher.py`（信号），`runner.py`（进程管理）

## Naming Conventions

- **Files**: `snake_case`
- **Classes**: `PascalCase`（`UserService`, `StrategyModel`, `BacktestView`）
- **Functions/Variables**: `snake_case`
- **Router prefix**: `/{resource}s`（复数），路由函数名 `{action}_{resource}`
- **Test files**: `test_<module>.py`，测试函数 `test_<scenario>`

## Import Organization

```python
# 标准库
import asyncio
from pathlib import Path

# 第三方库
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

# 项目内部（绝对路径，不使用相对导入）
from src.core.deps import get_db, get_current_user
from src.services.strategy_service import StrategyService
from src.schemas.strategy import StrategyCreate, StrategyRead
```

## Code Organization Principles

- `src/models/` 不依赖 `src/services/` 或 `src/api/`
- `src/services/` 不依赖 `src/api/`（无 `Request`/`Response` 引用）
- `src/freqtrade_bridge/` 不依赖 `src/api/`，服务层通过接口调用它
- `src/core/` 可被所有层引用，自身不引用业务层

---
_updated_at: 2026-03-14 — 重构为 FastAPI 分层架构，新增 schemas/admin/freqtrade_bridge 层描述_
