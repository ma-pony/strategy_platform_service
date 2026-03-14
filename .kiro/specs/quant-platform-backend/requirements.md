# 需求文档

## 引言

本文档定义量化平台后端服务（strategy_platform_service）的功能需求。系统定位为**面向数字货币量化交易入门用户的策略科普展示平台**，基于 FastAPI 构建，专注于加密货币（BTC、ETH 等主流币种及其交易对）领域，展示经典量化策略的回测结果、实时交易信号和核心指标（收益率、夏普比率、胜率、可信度等）。策略由后台预设，系统基于 freqtrade 引擎自动执行回测，用户仅浏览查看。所有接口遵循统一 JSON 信封响应格式，鉴权采用 JWT 无状态方案，未注册用户可浏览基础内容，会员等级（Free / VIP1 / VIP2）控制高级指标字段的可见性。

---

## 需求

### 需求 1：用户注册与登录

**目标：** 作为平台访客，我希望能够注册账户并登录，以便解锁更多策略指标和高级内容。

#### 验收标准

1. When 用户向 `POST /api/v1/auth/register` 提交合法的用户名和密码，the Auth Service shall 创建新用户记录（密码以 bcrypt 哈希存储），初始会员等级设为 Free，并返回 `code: 0` 及用户基本信息。
2. If 注册时用户名已存在，then the Auth Service shall 返回 `code: 2001` 及提示"用户名已被使用"，HTTP 状态码 400。
3. When 用户向 `POST /api/v1/auth/login` 提交正确的用户名和密码，the Auth Service shall 返回有效的 `access_token`（有效期 30 分钟）和 `refresh_token`（有效期 7 天），响应 `code: 0`。
4. If 登录时密码错误或用户不存在，then the Auth Service shall 返回 `code: 1001` 及"用户名或密码错误"，HTTP 状态码 401。
5. When 用户向 `POST /api/v1/auth/refresh` 提交有效的 `refresh_token`，the Auth Service shall 签发新的 `access_token` 并返回 `code: 0`。
6. If `refresh_token` 已过期或格式非法，then the Auth Service shall 返回 `code: 1001`，HTTP 状态码 401。
7. The Auth Service shall 在 JWT claims 中携带 `sub`（用户 ID）、`membership`（会员等级枚举）、`exp`、`iat` 和 `type` 字段。
8. If 请求携带的 `access_token` 已过期或签名无效，then the Auth Service shall 拦截请求并返回 `code: 1001`，HTTP 状态码 401。

---

### 需求 2：会员等级与字段级权限控制

**目标：** 作为平台运营方，我希望通过会员等级（Free / VIP1 / VIP2）差异化控制用户可查看的策略指标字段，实现分级展示以支持商业化运营。

#### 验收标准

1. The Auth Service shall 支持三种会员等级：Free、VIP1、VIP2，等级枚举存储于用户模型和 JWT claims 中。
2. The Platform shall 支持三种访问身份：匿名用户（未登录）、Free 用户（已注册未付费）、VIP1/VIP2 用户（付费会员），各身份可见的策略指标字段不同。
3. While 用户为匿名访客（未携带 JWT），the Strategy Service shall 返回策略基础信息（名称、描述、交易对）和有限的回测摘要（如总收益率），隐藏高级指标字段（夏普比率、最大回撤、胜率、可信度评分等）。
4. While 用户会员等级为 Free，the Strategy Service shall 在匿名可见字段基础上额外展示部分中级指标（如交易次数、最大回撤），但仍隐藏高级指标（夏普比率、胜率、可信度评分等）。
5. While 用户会员等级为 VIP1 或 VIP2，the Strategy Service shall 返回策略的全部指标字段，包括夏普比率、胜率、可信度评分、信号详情等。
6. The Auth Service shall 提供 `get_optional_user` 依赖注入函数，在请求携带有效 JWT 时返回用户对象，未携带或无效时返回 `None`（不拦截请求），供展示类接口使用。
7. The Auth Service shall 通过 FastAPI `Depends` 注入的 `require_membership(min_tier)` 工厂函数统一执行等级校验，用于需要强制鉴权的接口。
8. If 用户账户被标记为 `is_active=False`，then the Auth Service shall 拒绝所有请求并返回 `code: 1001`（"用户已禁用"），HTTP 状态码 401。
9. The Strategy Service shall 通过响应序列化层（Pydantic Schema 的动态字段过滤）实现字段级权限控制，不在业务逻辑层硬编码字段可见性判断。

---

### 需求 3：策略展示（只读）

**目标：** 作为量化小白用户，我希望能浏览平台预设的经典策略列表和详情，以便学习和了解不同量化策略的原理与表现。

#### 验收标准

1. When 任何用户（含匿名）向 `GET /api/v1/strategies` 发起请求，the Strategy Service shall 返回平台预设策略的分页列表，包含策略名称、描述、适用交易对和策略类型等基础字段。
2. When 任何用户（含匿名）向 `GET /api/v1/strategies/{id}` 发起请求，the Strategy Service shall 返回策略详情，根据用户身份（匿名/Free/VIP）动态过滤可见的指标字段（参见需求 2 的字段级权限）。
3. The Strategy Service shall 不提供任何创建、更新、删除策略的公开 API 接口，所有策略数据仅通过后台管理或数据库 seed 方式维护。
4. If 请求的策略 ID 不存在，then the Strategy Service shall 返回 `code: 3001`（"策略不存在"），HTTP 状态码 404。
5. The Strategy Service shall 在策略详情中包含该策略最近一次回测结果的摘要数据（如总收益率、交易次数等，按权限过滤字段）。

---

### 需求 4：系统自动回测与结果展示

**目标：** 作为平台用户，我希望能查看系统自动执行的策略回测结果和历史表现数据，以便评估经典策略的有效性。

#### 验收标准

1. The Backtest Service shall 提供系统级定时回测机制（如 Celery Beat 定时任务或管理命令），按预设周期自动对所有启用策略执行回测，用户不可触发回测。
2. The Backtest Service shall 将回测执行提交至独立 Worker 进程（Celery 或 ProcessPoolExecutor），禁止在 FastAPI 事件循环中同步调用 freqtrade 回测。
3. When 回测任务执行完成，the Backtest Service shall 将结果数据（总收益率、年化收益率、夏普比率、最大回撤、交易次数、胜率等核心指标）持久化至数据库，并将任务状态更新为 `DONE`。
4. If freqtrade 回测执行失败或超时，then the Backtest Service shall 将任务状态更新为 `FAILED`，记录 `error_message`，不影响其他策略的回测调度。
5. When 任何用户（含匿名）向 `GET /api/v1/strategies/{id}/backtests` 发起请求，the Backtest Service shall 返回该策略的回测结果列表（分页），根据用户身份动态过滤可见的指标字段。
6. When 任何用户（含匿名）向 `GET /api/v1/backtests/{id}` 发起请求，the Backtest Service shall 返回单次回测的完整结果详情，根据用户身份动态过滤可见的指标字段。
7. The Backtest Service shall 为每个回测任务在隔离目录下生成 freqtrade 配置文件，任务结束后清理该目录。
8. The Backtest Service shall 不暴露任何触发回测的公开 API 接口，回测仅通过系统内部调度执行。

---

### 需求 5：交易信号展示

**目标：** 作为平台用户，我希望能查看经典策略产生的实时交易信号和可信度评分，以便学习策略如何判断买卖时机。

#### 验收标准

1. When 任何用户（含匿名）向 `GET /api/v1/strategies/{id}/signals` 发起请求，the Signal Service shall 返回该策略最近的交易信号列表，包含信号方向（Buy / Sell / Hold）和信号时间戳。
2. While 用户会员等级为 VIP1 或 VIP2，the Signal Service shall 在信号响应中额外包含可信度/胜率评分字段（`confidence_score`，范围 0.0–1.0）；匿名和 Free 用户该字段不返回或返回 `null`。
3. The Signal Service shall 定期（由系统内部调度）通过独立进程调用 freqtrade 信号生成逻辑，将结果缓存至 Redis（热数据）并持久化至 PostgreSQL（历史数据），API 优先读取 Redis 缓存结果而非实时计算。
4. If freqtrade 信号生成失败，then the Signal Service shall 返回最近一次成功缓存的信号数据，并在响应中标注数据时效（`last_updated_at` 字段）。
5. The Signal Service shall 禁止在 FastAPI 请求处理路径中同步调用 freqtrade，所有信号生成通过后台任务异步完成。
6. If 请求的策略 ID 不存在，then the Signal Service shall 返回 `code: 3001`（"策略不存在"），HTTP 状态码 404。

---

### 需求 6：AI 市场研报数据模型

**目标：** 作为平台运营方，我希望有结构化的研报数据库模型，以便存储和管理 AI 生成的市场研报内容。

#### 验收标准

1. The Research Report Service shall 使用包含以下字段的 SQLAlchemy 模型存储研报：`id`（主键）、`title`（标题）、`summary`（摘要）、`content`（正文）、`generated_at`（生成时间，时区感知）、`related_coins`（关联币种，支持多个）、`created_at`、`updated_at`。
2. The Research Report Service shall 通过 `TimestampMixin` 自动维护 `created_at` 和 `updated_at` 字段，时间列使用 `timezone=True` 存储 UTC 时间。
3. The Research Report Service shall 支持研报与多个关联币种的映射关系（如通过独立的关联表或 JSON 字段存储币种列表）。
4. The Research Report Service shall 通过 Alembic 迁移管理研报表结构变更，每次迁移须包含 `upgrade()` 和 `downgrade()`。

---

### 需求 7：AI 市场研报只读接口

**目标：** 作为前端开发者，我希望通过只读 API 拉取研报列表和详情，以便在用户界面展示市场分析内容。

#### 验收标准

1. When 任何用户（含匿名）向 `GET /api/v1/reports` 发起请求，the Research Report Service shall 返回研报列表（含 `id`、`title`、`summary`、`generated_at`、`related_coins` 等摘要字段）的分页数据，默认 `page_size=20`。
2. When 任何用户（含匿名）向 `GET /api/v1/reports/{id}` 发起请求，the Research Report Service shall 返回研报完整内容，含 `title`、`summary`、`content`、`generated_at`、`related_coins` 全部字段。
3. If 请求的研报 ID 不存在，then the Research Report Service shall 返回 `code: 3001`（"研报不存在"），HTTP 状态码 404。
4. The Research Report Service shall 对研报列表和详情接口提供只读访问，不暴露任何创建、更新、删除研报的公开接口。
5. The Research Report Service shall 允许匿名访问研报接口，无需 JWT 鉴权。

---

### 需求 8：后台管理系统

**目标：** 作为运营人员，我希望通过可视化管理面板直接管理用户数据、策略配置、研报内容和会员状态，以便高效执行运营操作。

#### 验收标准

1. The Admin Service shall 基于 sqladmin 构建管理面板，并无缝挂载至 FastAPI 应用路由（路径如 `/admin`），无需独立部署。
2. The Admin Service shall 为 `User` 模型提供 `ModelView`，支持列表展示（含 `username`、`membership`、`is_active`、`created_at`）、搜索（按 `username`）和排序（按 `created_at`）。
3. The Admin Service shall 为策略（`Strategy`）模型提供 `ModelView`，支持创建、编辑策略（名称、描述、配置参数、启用状态），这是维护策略数据的唯一入口。
4. The Admin Service shall 为研报（`ResearchReport`）模型提供 `ModelView`，支持列表展示、创建、编辑、按标题搜索和按生成时间排序。
5. The Admin Service shall 允许运营人员在后台直接修改用户的 `membership` 字段和 `is_active` 状态。
6. The Admin Service shall 使用独立的管理员认证机制（`AuthenticationBackend`），与普通用户 JWT 体系完全隔离，管理员账户不共用用户表。
7. If 未认证的请求访问 `/admin` 路径，then the Admin Service shall 重定向至管理员登录页面。
8. The Admin Service shall 使用同步 SQLAlchemy engine（非异步 engine）与 sqladmin 集成，与 Web 层的异步 engine 实例分开创建。
9. Where sqladmin 提供 CRUD 操作，the Admin Service shall 根据业务需要限制特定模型（如 `User`）的后台删除操作（`can_delete = False`）。

---

### 需求 9：统一 API 响应与错误处理

**目标：** 作为 API 消费方（前端/客户端），我希望所有接口返回一致的 JSON 结构，以便统一处理成功响应和错误。

#### 验收标准

1. The API Gateway shall 对所有接口响应使用统一信封格式：`{"code": 0, "message": "success", "data": {...}}`，HTTP 状态码同时正确设置。
2. If 请求体校验失败（Pydantic 422），then the API Gateway shall 通过全局异常处理器将其转换为信封格式，返回 `code: 2001`（"请求参数校验失败"）及错误详情，HTTP 状态码 422。
3. The API Gateway shall 遵循错误码约定：1000–1999 为认证/授权错误，2000–2999 为参数错误，3000–3999 为业务逻辑错误，5000–5999 为服务端内部错误。
4. The API Gateway shall 对所有列表接口使用分页信封结构，包含 `items`、`total`、`page`、`page_size` 字段；`page_size` 默认 20，最大 100。
5. The API Gateway shall 使用 URL 路径版本（`/api/v1/`），Breaking change 时升级至新版本号，旧版本标记 deprecated。
6. If freqtrade 调用失败，then the API Gateway shall 返回 `code: 5001` 并包含对用户友好的错误描述，禁止暴露原始 traceback 或内部路径信息。
