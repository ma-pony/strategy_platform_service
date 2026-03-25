# 需求文档

## 简介

本功能旨在为量化策略科普展示平台接入真实数字货币行情数据，通过 freqtrade 引擎基于实时 OHLCV 行情定期运行各预设策略，产生真实的交易信号（Buy/Sell/Hold），并将信号持久化缓存至数据库，通过 REST API 展示给前端用户。平台仅做展示，不执行任何真实交易指令。

## 需求

### 需求 1: 真实行情数据接入（含风控与去重）

**Objective:** As a 平台运营方, I want 系统能从交易所安全稳定地获取 BTC、ETH 等主流数字货币的实时 OHLCV 行情数据, so that 信号生成有真实行情数据作为输入，同时不触发交易所风控。

#### Acceptance Criteria

1. The Signal Platform shall 采用**两阶段流水线架构**：第一阶段通过 `freqtrade download-data` 统一更新本地行情文件，第二阶段各策略从同一份本地文件加载数据进行信号计算。行情拉取按（交易对 + 时间周期）维度天然去重，因为同一（pair + timeframe）对应磁盘上同一个文件（如 `data/binance/BTC_USDT-1h-futures.json`）。
2. **增量更新而非全量拉取：** The Signal Platform shall 在拉取前检查本地 `datadir` 中对应（pair + timeframe）的数据文件是否存在且最后一根 K 线时间戳在当前周期内（如 1h 周期则在 1 小时内）。若数据文件足够新鲜，则跳过该组合的拉取，直接进入信号计算阶段。仅对缺失或过期的数据文件调用 `freqtrade download-data` 增量更新。
3. When 需要拉取时, the Signal Platform shall 调用 `freqtrade download-data --exchange binance --pairs <pairs> --timeframes 1h --days 30 --datadir <datadir>` 从 Binance 公开 API 增量更新。freqtrade 内部基于 ccxt，会自动合并已有数据，本地已有的历史部分不会重复下载。
4. The Signal Platform shall 仅使用公开行情接口（无需 API Key），禁止传入任何账户交易凭据。freqtrade `download-data` 对公开 K 线数据不要求认证。
5. **风控规避 — 请求限速：** The Signal Platform shall 在调用 `download-data` 时控制请求间隔（默认 200ms），确保不超过 Binance 公开 API 限频阈值（1200 权重/分钟）。对于 10 交易对 × 3 周期 = 30 次请求，以 200ms 间隔顺序执行约需 6 秒。
6. **风控规避 — 错误处理：** If 交易所 API 返回 429（Too Many Requests）或 418（IP Ban Warning）, freqtrade 内置的 ccxt 层会自动进行退避重试。The Signal Platform shall 在 `download-data` 子进程失败时记录告警日志，并降级使用本地已有的历史数据文件继续生成信号。
7. **数据目录持久化：** The Signal Platform shall 将 `freqtrade_datadir` 从默认的 `/tmp/freqtrade_data`（重启即丢失）迁移到持久化路径（如 `/opt/freqtrade_data`），通过环境变量 `FREQTRADE_DATADIR` 配置。Docker 部署时应将该路径挂载为 volume，确保数据跨容器/重启保留。回测任务和信号生成任务共享同一个 `datadir`，避免重复下载。
8. **本地文件保护：** The Signal Platform shall **禁止在任何流程中删除或清空 `datadir` 下的 OHLCV 数据文件**，仅允许追加/更新操作。任务结束后的临时目录清理（`/tmp/freqtrade_jobs/{task_id}/`）不得影响 `datadir`。
9. If `download-data` 执行失败且本地文件存在, the Signal Platform shall 降级使用本地已有数据继续生成信号，并在日志中标记 `data_source=local_fallback`。即使数据不是最新的，基于稍旧数据生成的信号仍有参考价值。
10. While 行情拉取任务正在运行, the Signal Platform shall 在独立的 Worker 进程（Celery）中以子进程方式执行 `download-data`，禁止阻塞 FastAPI 主事件循环。

---

### 需求 2: 实时信号生成（数据复用）

**Objective:** As a 平台运营方, I want 系统基于真实行情定期运行所有预设策略并生成信号, so that 用户看到的是基于真实市场数据产生的有参考价值的信号。

#### Acceptance Criteria

1. When 定时调度周期到达（默认每小时一次）, the Signal Platform shall 先执行**行情拉取阶段**（需求 1），再执行**信号计算阶段**，两阶段严格串行。
2. **信号计算阶段** shall 遍历所有（策略 × 交易对 × 时间周期）组合，对每个组合使用 freqtrade 的数据加载工具从本地 `datadir` 文件读取 OHLCV DataFrame（已在行情拉取阶段由 `download-data` 更新），传入策略的 `populate_indicators` → `populate_entry_trend` → `populate_exit_trend` 方法链，提取最后一根 K 线的信号结果。同一（pair + timeframe）的 DataFrame 在内存中仅加载一次，供所有策略复用。
3. The Signal Platform shall 通过 freqtrade 模块导入方式（`IStrategy` 子类实例化）在子进程中执行信号计算，不启动真实 freqtrade bot 实例，不提交任何订单。
4. When 信号计算完成, the Signal Platform shall 将信号结果（策略、交易对、时间周期、信号类型、信号强度/置信度、K 线时间戳、生成时间）写入数据库 `trading_signals` 表。
5. If 某策略的信号计算失败（异常或超时）, the Signal Platform shall 记录错误日志，将该条记录状态标记为 `ERROR`，并继续处理其余策略，不中断整体调度流程。
6. The Signal Platform shall 对每个（策略 + 交易对 + 时间周期）组合仅保留最新一条信号记录（upsert 语义），避免信号表无限增长。
7. While 信号生成任务正在执行, the Signal Platform shall 维护任务幂等性，若上次任务尚未完成则跳过本次触发（通过 Redis 分布式锁实现，锁 TTL = 任务超时时间），防止并发重复计算。
8. **统一使用 1h 时间周期：** 由于当前所有 10 个策略的 `timeframe` 均为 `1h`，The Signal Platform shall 在信号生成和回测中统一使用 `1h` 作为默认时间周期。行情拉取阶段仅需下载 `1h` K 线数据（无需 4h、1d），减少 API 请求量（10 交易对 × 1 周期 = 10 次请求）。未来新增其他周期策略时，通过配置扩展支持的 timeframe 列表。

---

### 需求 3: 信号数据持久化与存储

**Objective:** As a 平台运营方, I want 信号以结构化方式持久化存储至 PostgreSQL, so that API 层可直接高效查询，无需每次请求实时计算。

#### Acceptance Criteria

1. The Signal Platform shall 复用现有 `trading_signals` 表结构，包含字段：`id`、`strategy_id`（外键 `strategies.id`）、`pair`（交易对，如 `BTC/USDT`）、`timeframe`（时间周期）、`direction`（枚举：`BUY` / `SELL` / `HOLD`）、`confidence_score`（小数，0–1）、`signal_at`（K 线 UTC 时间）、`created_at`（生成 UTC 时间）、`signal_source`（`realtime`）、`updated_at`。
2. When 信号生成完成, the Signal Platform shall 以 upsert 方式（基于 `strategy_id + pair + timeframe` 唯一约束）写入信号记录，确保幂等性。
3. The Signal Platform shall 确保 `trading_signals` 表在 `(strategy_id, pair, timeframe)` 列上有唯一索引，在 `created_at` 列上有普通索引以加速时间范围查询。如已存在则无需重复创建。
4. If 数据库写入失败, the Signal Platform shall 记录错误日志并将异常上报给调度框架，不丢失错误信息。

---

### 需求 4: 信号查询 API

**Objective:** As a 前端用户（匿名 / Free / VIP）, I want 通过 REST API 查询各策略的最新信号, so that 能在平台上看到基于真实行情的交易参考信号。

#### Acceptance Criteria

1. The Signal Platform shall 提供 `GET /api/v1/strategies/{strategy_id}/signals` 接口，返回该策略的最新信号列表，响应使用统一信封格式 `{"code": 0, "message": "success", "data": {...}}`。
2. When 匿名用户请求信号列表, the Signal Platform shall 返回基础字段（`strategy_id`、`pair`、`timeframe`、`direction`、`signal_at`），隐藏 `confidence_score`（置信度）字段。
3. Where VIP1 及以上会员已登录, the Signal Platform shall 在响应中额外返回 `confidence_score`（置信度）字段。
5. When 请求的 `strategy_id` 不存在, the Signal Platform shall 返回 `{"code": 3001, "message": "策略不存在", "data": null}` 及 HTTP 404。
6. The Signal Platform shall 对信号列表接口支持分页查询（`page` / `page_size`），`page_size` 默认 20，最大 100。
7. While 信号数据正常存在于数据库, the Signal Platform shall 在 100ms 内返回单次信号查询响应（不包含外部 I/O 超时）。

---

### 需求 5: 定时调度与运维管理

**Objective:** As a 平台运营方, I want 信号生成任务能够自动定时触发并可通过后台监控, so that 平台信号数据能保持实时更新而无需人工干预。

#### Acceptance Criteria

1. The Signal Platform shall 通过 Celery Beat 定时调度，默认每小时触发一次全量信号生成任务，调度间隔可通过环境变量 `SIGNAL_REFRESH_INTERVAL` 配置。
2. When 信号生成任务完成（成功或失败）, the Signal Platform shall 在结构化日志中记录：任务执行总耗时、行情拉取耗时、拉取的交易对数量、缓存命中率、信号计算的（策略 × 交易对）数量、成功数、失败数。
3. The Signal Platform shall 通过 sqladmin 后台提供对 `trading_signals` 表的只读查看视图，运营人员可按策略、信号类型、时间范围筛选信号记录。
4. If 连续 3 次信号生成任务均失败, the Signal Platform shall 将告警信息写入错误日志（告警级别 `ERROR`），便于运维人员通过日志监控系统发现问题。
5. The Signal Platform shall 支持通过管理接口（`POST /api/v1/admin/signals/refresh`，需管理员权限）手动触发一次全量信号生成，以便运营人员在需要时立即刷新信号。

---

### 需求 6: 安全性与数据隔离

**Objective:** As a 平台运营方, I want 信号生成过程严格隔离，不引入任何真实交易风险, so that 平台仅作为展示工具，不对用户资产造成任何影响。

#### Acceptance Criteria

1. The Signal Platform shall 在 freqtrade 配置中明确设置 `dry_run: true`，且不传入任何账户 API Key，确保信号计算过程中不发起任何真实订单。
2. The Signal Platform shall 在信号计算子进程的 freqtrade 配置中禁用 Telegram、RPC 通知及其他 bot 管理接口，防止误发交易指令。
3. If freqtrade 信号计算子进程执行超时（默认 300 秒）, the Signal Platform shall 强制终止该子进程并记录超时告警日志。
4. The Signal Platform shall 不在信号数据或 API 响应中暴露任何交易所账户信息、API Key 或内部进程路径。
5. The Signal Platform shall 对信号生成任务使用独立的临时目录（`/tmp/freqtrade_signals/{task_id}/`），任务完成后自动清理临时文件。
