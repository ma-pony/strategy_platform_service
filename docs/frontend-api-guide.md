# 量化策略平台 — 前端对接文档

> **Base URL:** `http://localhost:8000/api/v1`
> **交互式文档:** `http://localhost:8000/docs` (Swagger UI) / `http://localhost:8000/redoc`
> **版本:** 1.0.0
> **最后更新:** 2026-03-24

---

## 目录

1. [全局约定](#1-全局约定)
2. [认证机制](#2-认证机制)
3. [会员等级与字段权限](#3-会员等级与字段权限)
4. [错误码一览](#4-错误码一览)
5. [接口详细说明](#5-接口详细说明)
   - 5.1 [健康检查](#51-健康检查)
   - 5.2 [认证模块](#52-认证模块)
   - 5.3 [策略模块](#53-策略模块)
   - 5.4 [回测模块](#54-回测模块)
   - 5.5 [信号模块](#55-信号模块)
   - 5.6 [研报模块](#56-研报模块)
   - 5.7 [交易对指标模块](#57-交易对指标模块)
   - 5.8 [管理后台接口](#58-管理后台接口)
6. [接口总索引](#6-接口总索引)
7. [前端对接指南](#7-前端对接指南)

---

## 1. 全局约定

### 1.1 统一响应结构

所有接口返回统一的 JSON 结构：

```jsonc
// 成功
{
  "code": 0,
  "message": "success",
  "data": { /* 业务数据 */ }
}

// 失败
{
  "code": 1001,         // 业务错误码，见第4节
  "message": "认证失败",  // 人类可读错误信息
  "data": null
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `code` | `int` | `0` 表示成功，非零为业务错误码 |
| `message` | `string` | 状态描述 |
| `data` | `T \| null` | 业务数据；失败时为 `null` |

### 1.2 分页结构

分页接口的 `data` 字段使用统一结构：

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "items": [],
    "total": 100,
    "page": 1,
    "page_size": 20
  }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `items` | `T[]` | 当前页数据列表 |
| `total` | `int` | 符合条件的总记录数 |
| `page` | `int` | 当前页码 |
| `page_size` | `int` | 每页条数 |

**通用分页参数：**

| 参数 | 类型 | 默认值 | 约束 | 说明 |
|------|------|--------|------|------|
| `page` | `int` | `1` | >= 1 | 页码 |
| `page_size` | `int` | `20` | 1 ~ 100 | 每页条数 |

### 1.3 时间格式

所有时间字段使用 **ISO 8601** 格式，UTC 时区：`2026-03-15T10:30:00Z`

### 1.4 CORS 配置

| 配置项 | 值 |
|--------|-----|
| 允许的来源 | `http://localhost:5173`、`http://127.0.0.1:5173` |
| 允许凭证 | `true` |
| 允许的方法 | `*`（全部） |
| 允许的请求头 | `*`（全部） |

> 生产环境需要更新来源白名单。

---

## 2. 认证机制

### 2.1 JWT Token

采用 **JWT Bearer Token**（HS256 签名）认证方式。

```http
Authorization: Bearer <access_token>
```

| Token 类型 | 有效期 | 用途 |
|-----------|--------|------|
| Access Token | 30 分钟 | 访问受保护的接口 |
| Refresh Token | 7 天 | 刷新 Access Token |

**Token 载荷（Claims）：**

| 字段 | 说明 |
|------|------|
| `sub` | 用户 ID（字符串） |
| `membership` | 会员等级 |
| `exp` | 过期时间戳 |
| `iat` | 签发时间戳 |
| `type` | `"access"` 或 `"refresh"` |

### 2.2 三种鉴权模式

接口使用以下三种鉴权模式之一：

| 模式 | 行为 | 适用场景 |
|------|------|----------|
| **无需认证** | 不检查 Token | 健康检查、研报列表 |
| **可选认证** | 有 Token → 解析用户和会员等级；无 Token → 匿名访问（部分字段为 null） | 策略、回测、信号等公开接口 |
| **必须认证** | 无有效 Token → 返回 `1001` 错误 | — |
| **管理员** | 必须认证 + `is_admin=true`，否则返回 `1002` 错误 | 后台管理接口 |

### 2.3 前端 Token 管理建议

```
1. 登录 → 存储 access_token 和 refresh_token
2. 每次请求 → 在 Header 带上 access_token
3. 收到 401 响应 → 用 refresh_token 调用刷新接口
4. 刷新成功 → 更新 access_token，重试原请求
5. 刷新失败 → 跳转登录页
```

---

## 3. 会员等级与字段权限

### 3.1 等级体系

等级从低到高：`anonymous`（未登录）< `free` < `vip1` < `vip2`

新注册用户默认为 `free`。

### 3.2 字段权限规则

**重要：权限不足时，受限字段返回 `null`，而非省略字段。** 前端需要根据 `null` 值展示占位或升级提示。

各业务模块的字段权限详见具体接口说明。以下是汇总视图：

| 字段 | anonymous | free | vip1 | vip2 |
|------|:---------:|:----:|:----:|:----:|
| 基础信息（名称、时间等） | ✅ | ✅ | ✅ | ✅ |
| `trade_count` / `total_return` | ❌ | ✅ | ✅ | ✅ |
| `max_drawdown` | ❌ | ✅ | ✅ | ✅ |
| `profit_factor` / `data_source` | ❌ | ✅ | ✅ | ✅ |
| `sharpe_ratio` / `win_rate` | ❌ | ❌ | ✅ | ✅ |
| `annual_return` | ❌ | ❌ | ✅ | ✅ |
| `confidence_score` | ❌ | ❌ | ✅ | ✅ |
| `last_updated_at`（指标） | ❌ | ❌ | ✅ | ✅ |

---

## 4. 错误码一览

| 错误码 | HTTP 状态码 | 说明 |
|--------|------------|------|
| `0` | 200 | 成功 |
| `1001` | 401 | 认证失败：Token 缺失 / 无效 / 过期 |
| `1002` | 403 | 权限不足：非管理员访问管理接口 |
| `1003` | 403 | 会员等级不足 |
| `1004` | 401 | 登录失败：邮箱或密码错误 |
| `1005` | 403 | 账号已被禁用 |
| `2001` | 400 / 422 | 参数校验失败 |
| `3001` | 404 | 资源不存在 |
| `3002` | 409 | 资源冲突（如重复的回测任务） |
| `3003` | 422 | 不支持的策略类型 |
| `3010` | 409 | 邮箱已注册 |
| `5000` | 500 | 服务器内部错误 |
| `5001` | 500 | Freqtrade 引擎调用失败 |

**前端建议处理方式：**

| 场景 | 处理 |
|------|------|
| `code === 0` | 正常处理 `data` |
| `code === 1001` | 尝试刷新 Token；失败则跳转登录 |
| `code === 1002` / `1003` / `1005` | 提示权限不足或账号被禁用 |
| `code === 2001` | 显示表单校验错误 |
| `code === 3001` | 资源不存在，404 页面或提示 |
| `code === 3010` | 提示邮箱已注册 |
| `code >= 5000` | 显示通用错误提示 |

---

## 5. 接口详细说明

### 5.1 健康检查

#### `GET /api/v1/health`

**认证：** 无需

**响应示例：**
```json
{
  "code": 0,
  "message": "success",
  "data": {
    "status": "healthy"
  }
}
```

---

### 5.2 认证模块

#### 5.2.1 用户注册

`POST /api/v1/auth/register`

**认证：** 无需

**请求体：**

| 字段 | 类型 | 必填 | 约束 | 说明 |
|------|------|:----:|------|------|
| `email` | `string` | ✅ | 合法邮箱格式，最长 254 字符 | 注册邮箱 |
| `password` | `string` | ✅ | 8 ~ 128 字符 | 密码 |

**请求示例：**
```json
{
  "email": "user@example.com",
  "password": "mypassword123"  // pragma: allowlist secret
}
```

**响应 `data`：**

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | `int` | 用户 ID |
| `email` | `string` | 注册邮箱 |
| `membership` | `string` | 初始值 `"free"` |
| `created_at` | `datetime \| null` | 创建时间 |

**响应示例：**
```json
{
  "code": 0,
  "message": "success",
  "data": {
    "id": 1,
    "email": "user@example.com",
    "membership": "free",
    "created_at": "2026-03-24T08:00:00Z"
  }
}
```

**可能的错误：** `3010`（邮箱已注册）、`2001`（参数校验失败）

---

#### 5.2.2 用户登录

`POST /api/v1/auth/login`

**认证：** 无需

**请求体：**

| 字段 | 类型 | 必填 | 说明 |
|------|------|:----:|------|
| `email` | `string` | ✅ | 邮箱 |
| `password` | `string` | ✅ | 密码 |

**响应 `data`：**

| 字段 | 类型 | 说明 |
|------|------|------|
| `access_token` | `string` | JWT 访问令牌（30 分钟有效） |
| `refresh_token` | `string` | JWT 刷新令牌（7 天有效） |
| `token_type` | `string` | 固定值 `"bearer"` |

**响应示例：**
```json
{
  "code": 0,
  "message": "success",
  "data": {
    "access_token": "eyJhbGciOiJIUzI1NiIs...",
    "refresh_token": "eyJhbGciOiJIUzI1NiIs...",
    "token_type": "bearer"
  }
}
```

**可能的错误：** `1001`（邮箱或密码错误）

---

#### 5.2.3 刷新 Token

`POST /api/v1/auth/refresh`

**认证：** 无需（在请求体中传入 refresh_token）

**请求体：**

| 字段 | 类型 | 必填 | 说明 |
|------|------|:----:|------|
| `refresh_token` | `string` | ✅ | 有效的刷新令牌 |

**响应 `data`：**

| 字段 | 类型 | 说明 |
|------|------|------|
| `access_token` | `string` | 新的访问令牌 |
| `token_type` | `string` | 固定值 `"bearer"` |

**可能的错误：** `1001`（刷新令牌无效或过期）

---

### 5.3 策略模块

#### 5.3.1 策略列表

`GET /api/v1/strategies`

**认证：** 可选（匿名可访问，登录用户可看到更多字段）

**查询参数：** 通用分页参数（`page`、`page_size`）

**响应 `data`：** `PaginatedData<StrategyRead>`

**`StrategyRead` 字段：**

| 字段 | 类型 | 最低等级 | 说明 |
|------|------|:--------:|------|
| `id` | `int` | anonymous | 策略 ID |
| `name` | `string` | anonymous | 策略名称 |
| `description` | `string` | anonymous | 策略描述 |
| `pairs` | `string[]` | anonymous | 交易对列表，如 `["BTC/USDT", "ETH/USDT"]` |
| `strategy_type` | `string` | anonymous | 策略类型标识 |
| `trade_count` | `int \| null` | free | 交易次数 |
| `max_drawdown` | `float \| null` | free | 最大回撤 |
| `sharpe_ratio` | `float \| null` | vip1 | 夏普比率 |
| `win_rate` | `float \| null` | vip1 | 胜率 |

**响应示例：**
```json
{
  "code": 0,
  "message": "success",
  "data": {
    "items": [
      {
        "id": 1,
        "name": "BollingerBand RSI",
        "description": "基于布林带和RSI的趋势策略",
        "pairs": ["BTC/USDT", "ETH/USDT"],
        "strategy_type": "bollinger_rsi",
        "trade_count": 156,
        "max_drawdown": -0.12,
        "sharpe_ratio": null,
        "win_rate": null
      }
    ],
    "total": 5,
    "page": 1,
    "page_size": 20
  }
}
```

> 上例为 `free` 用户视角，`sharpe_ratio` 和 `win_rate` 因等级不足显示为 `null`。

---

#### 5.3.2 策略详情

`GET /api/v1/strategies/{strategy_id}`

**认证：** 可选

**路径参数：**

| 参数 | 类型 | 说明 |
|------|------|------|
| `strategy_id` | `int` | 策略 ID |

**响应 `data`：** `StrategyRead`（字段同 5.3.1）

**可能的错误：** `3001`（策略不存在）

---

### 5.4 回测模块

#### 5.4.1 策略回测列表

`GET /api/v1/strategies/{strategy_id}/backtests`

**认证：** 可选

**路径参数：**

| 参数 | 类型 | 说明 |
|------|------|------|
| `strategy_id` | `int` | 策略 ID |

**查询参数：** 通用分页参数

**响应 `data`：** `PaginatedData<BacktestResultRead>`

**`BacktestResultRead` 字段：**

| 字段 | 类型 | 最低等级 | 说明 |
|------|------|:--------:|------|
| `id` | `int` | anonymous | 回测结果 ID |
| `strategy_id` | `int` | anonymous | 策略 ID |
| `task_id` | `int` | anonymous | 关联任务 ID |
| `period_start` | `datetime` | anonymous | 回测开始时间 |
| `period_end` | `datetime` | anonymous | 回测结束时间 |
| `created_at` | `datetime` | anonymous | 记录创建时间 |
| `total_return` | `float \| null` | free | 总收益率 |
| `trade_count` | `int \| null` | free | 交易次数 |
| `max_drawdown` | `float \| null` | free | 最大回撤 |
| `sharpe_ratio` | `float \| null` | vip1 | 夏普比率 |
| `win_rate` | `float \| null` | vip1 | 胜率 |
| `annual_return` | `float \| null` | vip1 | 年化收益率 |

**可能的错误：** `3001`（策略不存在）

---

#### 5.4.2 回测详情

`GET /api/v1/backtests/{backtest_id}`

**认证：** 可选

**路径参数：**

| 参数 | 类型 | 说明 |
|------|------|------|
| `backtest_id` | `int` | 回测结果 ID |

**响应 `data`：** `BacktestResultRead`（字段同 5.4.1）

**可能的错误：** `3001`（回测不存在）

---

### 5.5 信号模块

#### 5.5.1 策略最新信号

`GET /api/v1/strategies/{strategy_id}/signals`

**认证：** 可选

**路径参数：**

| 参数 | 类型 | 说明 |
|------|------|------|
| `strategy_id` | `int` | 策略 ID |

**查询参数：**

| 参数 | 类型 | 默认值 | 约束 | 说明 |
|------|------|--------|------|------|
| `limit` | `int` | `20` | 1 ~ 100 | 返回最新 N 条信号 |

> ⚠️ **注意：** 此接口不是分页接口，使用 `limit` 参数而非 `page`/`page_size`。

**响应 `data`：**

```json
{
  "signals": [ /* SignalRead[] */ ],
  "last_updated_at": "2026-03-15T10:30:00Z"
}
```

**`SignalRead` 字段：**

| 字段 | 类型 | 最低等级 | 说明 |
|------|------|:--------:|------|
| `id` | `int` | anonymous | 信号 ID |
| `strategy_id` | `int` | anonymous | 策略 ID |
| `pair` | `string` | anonymous | 交易对，如 `"BTC/USDT"` |
| `timeframe` | `string \| null` | anonymous | 时间周期，如 `"1h"` |
| `direction` | `string` | anonymous | 信号方向：`"buy"` / `"sell"` / `"hold"` |
| `signal_at` | `datetime` | anonymous | 信号产生时间 |
| `created_at` | `datetime` | anonymous | 记录入库时间 |
| `confidence_score` | `float \| null` | vip1 | 信号置信度 |

**响应示例：**
```json
{
  "code": 0,
  "message": "success",
  "data": {
    "signals": [
      {
        "id": 42,
        "strategy_id": 1,
        "pair": "BTC/USDT",
        "timeframe": "1h",
        "direction": "buy",
        "signal_at": "2026-03-24T08:00:00Z",
        "created_at": "2026-03-24T08:01:30Z",
        "confidence_score": null
      }
    ],
    "last_updated_at": "2026-03-24T08:01:30Z"
  }
}
```

**可能的错误：** `3001`（策略不存在）

---

### 5.6 研报模块

#### 5.6.1 研报列表

`GET /api/v1/reports`

**认证：** 无需（完全公开）

**查询参数：** 通用分页参数

**响应 `data`：** `PaginatedData<ReportRead>`

**`ReportRead` 字段（列表摘要，不含正文）：**

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | `int` | 研报 ID |
| `title` | `string` | 标题 |
| `summary` | `string` | 摘要 |
| `generated_at` | `datetime` | AI 生成时间 |
| `related_coins` | `string[]` | 相关币种，如 `["BTC", "ETH"]` |

**响应示例：**
```json
{
  "code": 0,
  "message": "success",
  "data": {
    "items": [
      {
        "id": 1,
        "title": "BTC 周度市场分析",
        "summary": "本周比特币在关键支撑位获得支撑...",
        "generated_at": "2026-03-24T00:00:00Z",
        "related_coins": ["BTC"]
      }
    ],
    "total": 10,
    "page": 1,
    "page_size": 20
  }
}
```

---

#### 5.6.2 研报详情

`GET /api/v1/reports/{report_id}`

**认证：** 无需

**路径参数：**

| 参数 | 类型 | 说明 |
|------|------|------|
| `report_id` | `int` | 研报 ID |

**响应 `data`：** `ReportDetailRead`

**`ReportDetailRead` 字段（含完整正文）：**

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | `int` | 研报 ID |
| `title` | `string` | 标题 |
| `summary` | `string` | 摘要 |
| `content` | `string` | 完整正文（Markdown 格式） |
| `generated_at` | `datetime` | AI 生成时间 |
| `related_coins` | `string[]` | 相关币种 |

**可能的错误：** `3001`（研报不存在）

---

### 5.7 交易对指标模块

#### 5.7.1 交易对指标列表

`GET /api/v1/strategies/{strategy_id}/pair-metrics`

**认证：** 可选

**路径参数：**

| 参数 | 类型 | 说明 |
|------|------|------|
| `strategy_id` | `int` | 策略 ID |

**查询参数：**

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `pair` | `string \| null` | `null` | 精确筛选交易对，如 `BTC/USDT` |
| `timeframe` | `string \| null` | `null` | 精确筛选时间周期，如 `1h` |
| `page` | `int` | `1` | 页码 |
| `page_size` | `int` | `20` | 每页条数 |

> 返回结果按 `total_return` 降序排列。

**响应 `data`：** `PaginatedData<PairMetricsRead>`

**`PairMetricsRead` 字段：**

| 字段 | 类型 | 最低等级 | 说明 |
|------|------|:--------:|------|
| `pair` | `string` | anonymous | 交易对 |
| `timeframe` | `string` | anonymous | 时间周期 |
| `total_return` | `float \| null` | anonymous | 总收益率 |
| `trade_count` | `int \| null` | anonymous | 交易次数 |
| `profit_factor` | `float \| null` | free | 盈利因子 |
| `data_source` | `string \| null` | free | 数据来源：`"backtest"` 或 `"live"` |
| `max_drawdown` | `float \| null` | vip1 | 最大回撤 |
| `sharpe_ratio` | `float \| null` | vip1 | 夏普比率 |
| `last_updated_at` | `datetime \| null` | vip1 | 最后更新时间 |

**可能的错误：** `3001`（策略不存在）

---

#### 5.7.2 单个交易对指标

`GET /api/v1/strategies/{strategy_id}/pair-metrics/{pair}/{timeframe}`

**认证：** 可选

**路径参数：**

| 参数 | 类型 | 说明 |
|------|------|------|
| `strategy_id` | `int` | 策略 ID |
| `pair` | `string` | 交易对 |
| `timeframe` | `string` | 时间周期 |

> ⚠️ **重要：** 交易对中的 `/` 需要进行 URL 编码。例如 `BTC/USDT` 应编码为 `BTC%2FUSDT`。
>
> 完整 URL 示例：`/api/v1/strategies/1/pair-metrics/BTC%2FUSDT/1h`

**响应 `data`：** `PairMetricsRead`（字段同 5.7.1）

**可能的错误：** `3001`（策略或指标不存在）

---

### 5.8 管理后台接口

> ⚠️ 以下所有接口均需要 **管理员权限**。请求必须携带管理员用户的 Access Token，否则返回 `1002` 错误。

#### 5.8.1 提交回测任务

`POST /api/v1/admin/backtests`

**请求体：**

| 字段 | 类型 | 必填 | 约束 | 说明 |
|------|------|:----:|------|------|
| `strategy_id` | `int` | ✅ | — | 策略 ID |
| `timerange` | `string` | ✅ | 正则 `^\d{8}-\d{8}$` | 日期范围，格式 `YYYYMMDD-YYYYMMDD` |

**请求示例：**
```json
{
  "strategy_id": 1,
  "timerange": "20250101-20251231"
}
```

**响应 `data`：** `BacktestTaskRead`

**`BacktestTaskRead` 字段：**

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | `int` | 任务 ID |
| `strategy_id` | `int` | 策略 ID |
| `status` | `string` | 任务状态：`"pending"` / `"running"` / `"done"` / `"failed"` |
| `timerange` | `string \| null` | 请求的日期范围 |
| `error_message` | `string \| null` | 错误信息（仅失败时有值） |
| `result_summary` | `object \| null` | 回测结果摘要（仅完成时有值） |
| `created_at` | `datetime` | 创建时间 |
| `updated_at` | `datetime` | 最后更新时间 |

**`result_summary` 嵌套对象：**

| 字段 | 类型 | 说明 |
|------|------|------|
| `total_return` | `float \| null` | 总收益率 |
| `annual_return` | `float \| null` | 年化收益率 |
| `sharpe_ratio` | `float \| null` | 夏普比率 |
| `max_drawdown` | `float \| null` | 最大回撤 |
| `trade_count` | `int \| null` | 交易次数 |
| `win_rate` | `float \| null` | 胜率 |

---

#### 5.8.2 回测任务列表

`GET /api/v1/admin/backtests`

**查询参数：**

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `page` | `int` | `1` | 页码 |
| `page_size` | `int` | `20` | 每页条数 |
| `strategy_name` | `string \| null` | `null` | 按策略名称筛选 |
| `status` | `string \| null` | `null` | 按状态筛选 |

**响应 `data`：** `PaginatedData<BacktestTaskRead>`

---

#### 5.8.3 回测任务详情

`GET /api/v1/admin/backtests/{task_id}`

**路径参数：**

| 参数 | 类型 | 说明 |
|------|------|------|
| `task_id` | `int` | 任务 ID |

**响应 `data`：** `BacktestTaskRead`

---

#### 5.8.4 创建研报

`POST /api/v1/admin/reports`

**请求体：**

| 字段 | 类型 | 必填 | 约束 | 说明 |
|------|------|:----:|------|------|
| `title` | `string` | ✅ | 最长 256 字符 | 研报标题 |
| `summary` | `string` | ✅ | — | 研报摘要 |
| `content` | `string` | ✅ | — | 研报正文 |
| `related_coins` | `string[]` | ❌ | 默认 `[]` | 相关币种，存储时自动转大写 |

**响应 `data`：** `ReportResponse`

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | `int` | 研报 ID |
| `title` | `string` | 标题 |
| `summary` | `string` | 摘要 |
| `content` | `string` | 正文 |
| `generated_at` | `datetime` | 创建时间（自动设为当前 UTC 时间） |
| `related_coins` | `string[]` | 相关币种（大写） |

---

#### 5.8.5 更新研报

`PUT /api/v1/admin/reports/{report_id}`

**路径参数：**

| 参数 | 类型 | 说明 |
|------|------|------|
| `report_id` | `int` | 研报 ID |

**请求体（所有字段可选，部分更新）：**

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `title` | `string \| null` | 最长 256 字符 | 新标题 |
| `summary` | `string \| null` | — | 新摘要 |
| `content` | `string \| null` | — | 新正文 |
| `related_coins` | `string[] \| null` | — | 全量替换币种列表 |

**响应 `data`：** `ReportResponse`

**可能的错误：** `3001`（研报不存在）

---

#### 5.8.6 删除研报

`DELETE /api/v1/admin/reports/{report_id}`

**路径参数：**

| 参数 | 类型 | 说明 |
|------|------|------|
| `report_id` | `int` | 研报 ID |

**响应示例：**
```json
{
  "code": 0,
  "message": "success",
  "data": {
    "id": 42,
    "deleted": true
  }
}
```

**可能的错误：** `3001`（研报不存在）

---

#### 5.8.7 触发信号刷新

`POST /api/v1/admin/signals/refresh`

**请求体：** 无

**响应示例：**
```json
{
  "code": 0,
  "message": "success",
  "data": {
    "task_id": "celery-task-uuid-xxxx",
    "message": "信号刷新任务已入队"
  }
}
```

> 此接口异步执行，返回 Celery 任务 ID。信号刷新在后台完成。

---

## 6. 接口总索引

| 方法 | 路径 | 认证 | 说明 |
|------|------|------|------|
| `GET` | `/api/v1/health` | 无需 | 健康检查 |
| `POST` | `/api/v1/auth/register` | 无需 | 用户注册 |
| `POST` | `/api/v1/auth/login` | 无需 | 用户登录 |
| `POST` | `/api/v1/auth/refresh` | 无需 | 刷新 Token |
| `GET` | `/api/v1/strategies` | 可选 | 策略列表 |
| `GET` | `/api/v1/strategies/{strategy_id}` | 可选 | 策略详情 |
| `GET` | `/api/v1/strategies/{strategy_id}/backtests` | 可选 | 策略回测列表 |
| `GET` | `/api/v1/backtests/{backtest_id}` | 可选 | 回测详情 |
| `GET` | `/api/v1/strategies/{strategy_id}/signals` | 可选 | 策略最新信号 |
| `GET` | `/api/v1/reports` | 无需 | 研报列表 |
| `GET` | `/api/v1/reports/{report_id}` | 无需 | 研报详情 |
| `GET` | `/api/v1/strategies/{strategy_id}/pair-metrics` | 可选 | 交易对指标列表 |
| `GET` | `/api/v1/strategies/{sid}/pair-metrics/{pair}/{tf}` | 可选 | 单个交易对指标 |
| `POST` | `/api/v1/admin/backtests` | 管理员 | 提交回测任务 |
| `GET` | `/api/v1/admin/backtests` | 管理员 | 回测任务列表 |
| `GET` | `/api/v1/admin/backtests/{task_id}` | 管理员 | 回测任务详情 |
| `POST` | `/api/v1/admin/reports` | 管理员 | 创建研报 |
| `PUT` | `/api/v1/admin/reports/{report_id}` | 管理员 | 更新研报 |
| `DELETE` | `/api/v1/admin/reports/{report_id}` | 管理员 | 删除研报 |
| `POST` | `/api/v1/admin/signals/refresh` | 管理员 | 触发信号刷新 |

**共 20 个接口**

---

## 7. 前端对接指南

### 7.1 Axios 请求封装示例

```typescript
import axios from 'axios'

const api = axios.create({
  baseURL: 'http://localhost:8000/api/v1',
  timeout: 10000,
})

// 请求拦截器：自动携带 Token
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('access_token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// 响应拦截器：统一处理错误
api.interceptors.response.use(
  (response) => {
    const { code, message, data } = response.data
    if (code !== 0) {
      return Promise.reject({ code, message, data })
    }
    return data  // 直接返回 data 层
  },
  async (error) => {
    if (error.response?.status === 401) {
      // 尝试刷新 Token
      const refreshToken = localStorage.getItem('refresh_token')
      if (refreshToken) {
        try {
          const { data } = await axios.post(
            'http://localhost:8000/api/v1/auth/refresh',
            { refresh_token: refreshToken }
          )
          localStorage.setItem('access_token', data.data.access_token)
          // 重试原请求
          error.config.headers.Authorization = `Bearer ${data.data.access_token}`
          return api(error.config)
        } catch {
          // 刷新也失败，跳转登录
          localStorage.clear()
          window.location.href = '/login'
        }
      }
    }
    return Promise.reject(error)
  }
)

export default api
```

### 7.2 TypeScript 类型定义

```typescript
// ---- 通用 ----
interface ApiResponse<T> {
  code: number
  message: string
  data: T | null
}

interface PaginatedData<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

// ---- 认证 ----
interface TokenPair {
  access_token: string
  refresh_token: string
  token_type: 'bearer'
}

interface UserRead {
  id: number
  email: string
  membership: 'free' | 'vip1' | 'vip2'
  created_at: string | null
}

// ---- 策略 ----
interface StrategyRead {
  id: number
  name: string
  description: string
  pairs: string[]
  strategy_type: string
  trade_count: number | null
  max_drawdown: number | null
  sharpe_ratio: number | null
  win_rate: number | null
}

// ---- 回测 ----
interface BacktestResultRead {
  id: number
  strategy_id: number
  task_id: number
  period_start: string
  period_end: string
  created_at: string
  total_return: number | null
  trade_count: number | null
  max_drawdown: number | null
  sharpe_ratio: number | null
  win_rate: number | null
  annual_return: number | null
}

// ---- 信号 ----
interface SignalRead {
  id: number
  strategy_id: number
  pair: string
  timeframe: string | null
  direction: 'buy' | 'sell' | 'hold'
  signal_at: string
  created_at: string
  confidence_score: number | null
}

interface SignalsWithTimestamp {
  signals: SignalRead[]
  last_updated_at: string
}

// ---- 研报 ----
interface ReportRead {
  id: number
  title: string
  summary: string
  generated_at: string
  related_coins: string[]
}

interface ReportDetailRead extends ReportRead {
  content: string
}

// ---- 交易对指标 ----
interface PairMetricsRead {
  pair: string
  timeframe: string
  total_return: number | null
  trade_count: number | null
  profit_factor: number | null
  data_source: 'backtest' | 'live' | null
  max_drawdown: number | null
  sharpe_ratio: number | null
  last_updated_at: string | null
}

// ---- 管理后台 ----
interface BacktestTaskRead {
  id: number
  strategy_id: number
  status: 'pending' | 'running' | 'done' | 'failed'
  timerange: string | null
  error_message: string | null
  result_summary: BacktestResultSummary | null
  created_at: string
  updated_at: string
}

interface BacktestResultSummary {
  total_return: number | null
  annual_return: number | null
  sharpe_ratio: number | null
  max_drawdown: number | null
  trade_count: number | null
  win_rate: number | null
}
```

### 7.3 注意事项

1. **`null` 字段处理：** 会员权限不足时字段值为 `null`，前端应显示锁定图标或升级提示，而非空值
2. **交易对 URL 编码：** 在路径参数中传交易对时，`/` 必须编码为 `%2F`（如 `BTC%2FUSDT`）
4. **时间处理：** 所有时间均为 UTC，前端需自行转换为本地时区显示
5. **分页边界：** `page_size` 最大 100，超出会被截断
6. **管理后台：** 后端另有 SQLAdmin 管理界面挂载在 `/admin` 路径下，非 API 接口
