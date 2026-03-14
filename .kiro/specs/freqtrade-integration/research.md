# 调研与设计决策记录

---
**用途**：记录 freqtrade-integration 功能的技术调研结果、架构权衡和关键设计决策，供 `design.md` 引用。

---

## 摘要

- **功能**：freqtrade-integration
- **发现范围**：Complex Integration（既涉及外部量化引擎的子进程封装，又涉及现有 FastAPI 分层架构的扩展）
- **关键发现**：
  1. 项目代码库已完成基础脚手架（`FreqtradeBridge`、`Celery Worker`、`BacktestTask/BacktestResult/TradingSignal` 模型），但尚缺少：管理员专属 API 路由、`STRATEGY_REGISTRY` 机制、信号扩展字段（11 字段）、种子数据脚本及十个策略文件。
  2. freqtrade IStrategy 接口（`INTERFACE_VERSION = 3`）已稳定，三个核心方法签名不变，策略文件可独立通过 CLI 执行，适合静态预置。
  3. 串行队列执行（`concurrency=1`）由 Celery Worker 层保证，服务层不设置 RUNNING 上限守卫；任务提交永不拒绝，消除 `code:3002` 场景。

---

## 调研日志

### 话题一：freqtrade IStrategy 接口稳定性

- **背景**：需要为十个经典策略预置 `.py` 文件，确认方法签名是否发生变更。
- **参考来源**：[Strategy Customization - Freqtrade](https://www.freqtrade.io/en/stable/strategy-customization/)
- **发现**：
  - `INTERFACE_VERSION = 3` 为当前稳定版本
  - 三个核心方法签名：`populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame`，`populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame`，`populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame`
  - 旧版 `populate_buy_trend` / `populate_sell_trend` 已于 2022 年重命名，当前版本使用 `enter_long` / `exit_long` 信号列
  - 策略必须在 `populate_entry_trend` 中向 DataFrame 写入 `enter_long` 列（1/0），在 `populate_exit_trend` 中写入 `exit_long` 列
- **影响**：十个策略文件均需声明 `INTERFACE_VERSION = 3`，信号列使用 `enter_long` / `exit_long`，不能使用旧版 `buy` / `sell`。

### 话题二：现有代码库差距分析

- **背景**：需要确定哪些组件已存在、哪些需要新增。
- **分析内容**：通过 Glob 和 Read 工具遍历 `src/` 全目录
- **已存在的组件**：
  - `src/freqtrade_bridge/`：`exceptions.py`（`FreqtradeExecutionError`、`FreqtradeTimeoutError`）、`runner.py`（`generate_config`、`cleanup_task_dir`）、`backtester.py`（`run_backtest_subprocess`）、`signal_fetcher.py`（`fetch_signals_sync` 占位实现）
  - `src/models/backtest.py`：`BacktestTask`（`strategy_id`、`scheduled_date`、`status`、`error_message`）、`BacktestResult`（六项核心指标）
  - `src/models/signal.py`：`TradingSignal`（`strategy_id`、`pair`、`direction`、`confidence_score`、`signal_at`）——缺少 `signal_source` 及扩展的 8 个信号字段
  - `src/workers/celery_app.py`：Celery 应用、`backtest` / `signal` 双队列、Beat 计划（每日 02:00 回测、每 15 分钟信号）——`backtest` 队列 Worker 须改为 `concurrency=1`
  - `src/workers/tasks/backtest_tasks.py`：`run_backtest_task` Celery 任务（幂等检查、RUNNING → DONE/FAILED 状态流转、目录清理）——含超时参数需移除
  - `src/workers/tasks/signal_tasks.py`：`generate_signals_task`（Redis 写入 + PostgreSQL 持久化）
  - `src/services/backtest_service.py`：`BacktestService`（只读查询，无管理员写入方法）
  - `src/api/backtests.py`：普通用户回测结果查询路由（不含管理员提交接口）
  - `src/core/exceptions.py`：`ConflictError(3002)`、`NotFoundError(3001)`、`FreqtradeError(5001)`、`PermissionError(1002)`
  - `src/core/deps.py`：`get_current_user`、`get_optional_user`、`require_membership`
- **缺少的组件**：
  - `src/freqtrade_bridge/strategy_registry.py`：`STRATEGY_REGISTRY` 字典（三元映射）
  - `src/freqtrade_bridge/strategies/`：十个策略 `.py` 文件
  - `src/freqtrade_bridge/config_template.json`：带占位符的默认配置模板
  - `src/freqtrade_bridge/seeds/`：种子数据脚本（幂等批量插入十条策略记录）
  - 管理员专属 API：`POST /api/v1/admin/backtests`（手动触发）、`GET /api/v1/admin/backtests/{task_id}`（查询任务）、`GET /api/v1/admin/backtests`（列表）
  - `src/services/admin_backtest_service.py`：管理员回测服务（仅注册表校验，无 RUNNING 计数守卫）
  - `src/models/signal.py` 的扩展字段：`signal_source`、`entry_price`、`stop_loss`、`take_profit`、`indicator_values`、`timeframe`、`signal_strength`、`volume`、`volatility`
  - `User.is_admin` 字段或通过 `membership` 等级的管理员鉴权 `Depends`
  - 回测完成后将回测信号追加写入 `trading_signals` 表的逻辑

### 话题三：管理员权限设计

- **背景**：需求要求非管理员请求返回 `code: 1002`，但现有 `User` 模型只有 `MembershipTier` 枚举，无 `is_admin` 布尔字段。
- **分析**：
  - 方案 A：在 `User` 模型新增 `is_admin: bool` 字段，`deps.py` 新增 `require_admin` Depends
  - 方案 B：复用 `sqladmin` 独立管理员体系，API 调用使用独立 token
  - 方案 C：将 VIP2 等级视为管理员（简化）
- **选定方案**：方案 A（`is_admin` 布尔字段）。理由：语义清晰、与 JWT 体系正交、无需独立 session 体系、Admin API 需要纳入 OpenAPI 文档供测试。

### 话题四：回测信号来源标记

- **背景**：需求 2.5 要求回测完成后产生的信号标记为 `backtest` 来源，与实时信号区分。
- **分析**：现有 `TradingSignal` 模型无 `signal_source` 字段，需通过 Alembic 迁移新增 `String(16)` 字段，可选值 `realtime` / `backtest`，`server_default='realtime'`。

### 话题五：策略不支持错误码（3003）

- **背景**：需求 3.7 要求策略不在 `STRATEGY_REGISTRY` 时返回 `code: 3003`，但 `src/core/exceptions.py` 中无此错误类。
- **决策**：新增 `UnsupportedStrategyError(AppError, code=3003)`，挂载到现有异常体系。

### 话题六：TradingSignal 扩展字段设计

- **背景**：需求 2.3 将信号表扩展至 11 个字段，现有模型仅有 `pair`、`direction`、`confidence_score` 三个信号字段（不含 `id`、`strategy_id`、`signal_at`、`created_at` 等元数据字段）。
- **新增字段**：`entry_price`（Float）、`stop_loss`（Float）、`take_profit`（Float）、`indicator_values`（JSONB）、`timeframe`（String(8)）、`signal_strength`（Float）、`volume`（Float）、`volatility`（Float），共 8 个，与已有 3 个信号字段合计 11 个。
- **决策**：所有新增字段允许 NULL，以保证向后兼容（旧写入路径不会因缺少字段而报错）；新路径显式传入全部 11 个字段。
- **迁移方案**：合并到单一 Alembic 迁移文件 `xxx_extend_trading_signals.py`，同时添加 `signal_source` 和 8 个扩展字段，减少迁移文件数量。

### 话题七：并发回测控制策略

- **背景**：需求 1.8 要求同一时间只有 1 个回测任务处于 RUNNING 状态，其余以 PENDING 排队；需求 1.9 和 5.5 明确不因队列积压拒绝任务提交。
- **原有方案**（已废弃）：
  - 服务层双守卫：① 策略级 RUNNING 计数（> 0 则 `ConflictError(3002)`）；② 全局 RUNNING 计数（≥ 5 则 `ConflictError(3002)`）
  - `run_backtest_subprocess` 添加 `timeout=600` 强制终止
- **分析**：
  - 服务层守卫方案与需求 1.9（"不拒绝"、"不返回 3002"）直接冲突
  - `timeout=600` 与需求 1.8（"任务运行至完成"）直接冲突
  - Celery `concurrency=1` 在 Worker 层已天然实现串行：队列中的任务一次只被 1 个 Worker 取出并执行，无法并发
- **选定方案**：
  - Celery `backtest` 队列 Worker 以 `concurrency=1` 启动，由 Celery 自身保证串行，不在服务层做 RUNNING 计数守卫
  - `run_backtest_subprocess` 移除 `timeout` 参数，任务运行至自然结束
  - 移除 `ConflictError(3002)` 在回测提交路径中的使用（保留类定义，其他场景可用）
  - 移除 `RUNNING_BACKTEST_LIMIT` 环境变量配置项
- **权衡**：
  - 优势：语义更清晰，投诉队列积压时管理员可通过任务列表接口查看排队状态而非被拒绝
  - 风险：长时间运行的回测任务无超时防护，若 freqtrade 子进程挂起（如网络 I/O 阻塞），需依赖操作系统或 Celery 进程管理手动介入
  - 缓解：structlog 记录 `duration_ms`，可通过监控系统（Prometheus/Grafana）设置外部告警阈值

---

## 架构模式评估

| 方案 | 描述 | 优势 | 风险/局限 | 备注 |
|------|------|------|-----------|------|
| 子进程（subprocess） | freqtrade CLI 作为独立进程调用 | 进程隔离、崩溃不影响主服务 | 序列化开销、无法共享内存 | 已选定用于回测，符合 steering 约束 |
| ProcessPoolExecutor | 进程池复用，适合轻量信号生成 | 进程复用降低启动开销 | 复杂度稍高，Worker 中无需使用（Celery 本身已是独立进程） | 用于异步信号生成场景 |
| freqtrade RPC API | 通过 HTTP 调用 freqtrade 内置 REST | 无需子进程管理 | 需要持久化 bot 实例、增加运维复杂度 | 未选用——MVP 阶段过重 |
| Celery concurrency=1（串行队列） | Worker 单并发消费 backtest 队列 | 天然串行，无服务层守卫逻辑 | 长任务阻塞后续队列 | 已选定，符合需求 1.8/1.9/5.5 |
| 服务层 RUNNING 计数守卫（弃用） | 提交时检查 RUNNING 数量，超限拒绝 | 细粒度控制 | 与"永不拒绝"需求冲突，引入 3002 错误码 | 已废弃 |

---

## 设计决策

### 决策一：User.is_admin 管理员字段

- **背景**：管理员专属 API 需要区分普通用户与管理员
- **备选方案**：
  1. 新增 `is_admin` 布尔字段（选定）
  2. 通过 VIP2 等级隐式代表管理员（混用语义）
- **选定方案**：在 `User` 模型新增 `is_admin: bool = False`，`deps.py` 新增 `require_admin` Depends，非管理员抛 `PermissionError(1002)`
- **理由**：权限语义清晰，不污染会员等级枚举，Alembic 迁移成本低
- **权衡**：增加一个迁移文件和测试用例，但安全性更可审计
- **后续**：验证 sqladmin 是否需要同步更新 `UserAdmin` 视图

### 决策二：signal_source 字段设计

- **背景**：回测信号和实时信号共存同一张表，需要区分来源
- **备选方案**：
  1. 新增 `signal_source: Literal["realtime", "backtest"]` 字段（选定）
  2. 建立独立的 `backtest_signals` 表（过度设计）
- **选定方案**：`TradingSignal` 新增 `signal_source: str`，`server_default='realtime'`，通过 Alembic 迁移添加
- **理由**：符合需求 2.3/2.4/2.5 的只增不删约束，现有查询逻辑仅需过滤条件微调
- **权衡**：迁移历史数据均标记为 `realtime`，语义准确

### 决策三：STRATEGY_REGISTRY 静态映射

- **背景**：需求 3.5/7.3 要求三元映射（数据库策略名 ↔ freqtrade 类名 ↔ 文件路径）
- **选定方案**：`StrategyRegistryEntry` TypedDict，`STRATEGY_REGISTRY: dict[str, StrategyRegistryEntry]` 全局常量，键为数据库 `Strategy.name` 字段值
- **理由**：纯 Python 常量，无外部依赖，类型安全，可测试

### 决策四：并发回测控制——Celery concurrency=1 替代服务层守卫

- **背景**：需求 1.8 要求串行回测（同时 1 个 RUNNING），需求 1.9 和 5.5 明确不拒绝任务提交
- **原方案**（已废弃）：服务层双守卫（策略级 + 全局 RUNNING 计数），超限返回 `code:3002`；`timeout=600` 强制终止子进程
- **选定方案**：
  - Celery `backtest` 队列 Worker 以 `concurrency=1` 启动，由消息队列机制保证串行
  - `run_backtest_subprocess` 不传入 `timeout` 参数，任务运行至自然结束
  - 服务层 `submit_backtest` 仅做注册表查找，不检查 RUNNING 状态
- **理由**：
  - `concurrency=1` 是 Celery 原生特性，天然串行，无竞争条件
  - 去除服务层守卫消除了高并发下查询竞争（两次 SELECT 与 INSERT 之间的 TOCTOU 问题）
  - 任务永不拒绝，管理员提交体验更佳，可通过任务列表监控队列深度
- **权衡**：
  - 移除超时防护后，长时间运行的 freqtrade 任务无内部强制终止机制
  - 需依赖外部监控（structlog `duration_ms` + Prometheus 告警）检测异常挂起任务
  - `ConflictError(3002)` 类定义保留（其他场景可能复用），但在回测提交路径中不再触发

### 决策五：TradingSignal 扩展至 11 字段

- **背景**：需求 2.3 要求信号记录包含完整的 11 个字段（pair、direction、confidence_score 已有；entry_price、stop_loss、take_profit、indicator_values、timeframe、signal_strength、volume、volatility 需新增）
- **备选方案**：
  1. 直接在 `trading_signals` 表新增 8 列（选定）
  2. 新建 `signal_details` 关联表存储扩展字段（规范化过度）
  3. 将扩展字段合并到已有 `indicator_values` JSON 列（缺少类型安全）
- **选定方案**：直接新增 8 个独立列，所有列允许 NULL（向后兼容），合并到单一 Alembic 迁移
- **理由**：查询效率高（无 JOIN），字段语义清晰，可按列建立索引，符合时序表扁平化设计原则

---

## 风险与缓解措施

- **风险**：`run_backtest_task` 未集成 `STRATEGY_REGISTRY` 查找和目录结构（`strategy/`、`results/` 子目录），现有实现仅生成 `config.json` — **缓解**：在任务实现中补充策略文件复制逻辑，通过 `STRATEGY_REGISTRY` 查找策略文件路径
- **风险**：十个策略文件使用 `ta-lib` 或 `pandas-ta` 等不同技术指标库，依赖未锁定 — **缓解**：统一使用 freqtrade 内置的 `pandas-ta`（已随 freqtrade 安装），避免额外依赖
- **风险**：`User.is_admin` 迁移影响现有测试 fixtures — **缓解**：迁移文件添加 `server_default='false'`，存量数据默认非管理员，无需数据补丁
- **风险**：`TradingSignal` 扩展字段影响现有 `generate_signals_task` 写入 — **缓解**：所有新增字段设为可 NULL，旧写入路径无需修改；新路径显式传入全部 11 个字段
- **风险**：移除超时后回测子进程可能因 freqtrade 异常挂起（如数据下载阻塞）— **缓解**：structlog 记录 `duration_ms`，通过外部监控系统设置超时告警；运维层面可通过 `celery inspect` 命令查看长时间 RUNNING 任务并手动终止

---

## 参考资料

- [freqtrade Strategy Customization](https://www.freqtrade.io/en/stable/strategy-customization/) — IStrategy 接口方法签名与 INTERFACE_VERSION
- [freqtrade Strategy Quickstart](https://www.freqtrade.io/en/stable/strategy-101/) — enter_long / exit_long 信号列约定
- 项目 steering 文档 `freqtrade-integration.md` — 子进程调用模式与配置隔离约定
- 项目 steering 文档 `api-standards.md` — 统一响应信封与错误码约定
- [Celery Workers Guide - Concurrency](https://docs.celeryq.dev/en/stable/userguide/workers.html#concurrency) — concurrency=1 串行队列配置
