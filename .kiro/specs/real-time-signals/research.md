# 研究与设计决策记录

---
**Purpose**: 记录发现阶段的研究成果、架构探索和设计权衡，为 design.md 提供支撑。

---

## 摘要

- **Feature**: `real-time-signals`
- **发现范围**: Complex Integration（复杂集成）
- **关键发现**:
  - freqtrade `download-data` CLI 原生支持增量更新，无需业务层手动对比文件时间戳；当本地数据存在时自动补充缺失区间至当前时刻
  - `freqtrade.data.history.load_pair_history` 可从本地 datadir 加载 OHLCV DataFrame，配合 `IStrategy.populate_indicators / populate_entry_trend / populate_exit_trend` 方法链实现离线信号计算，无需启动真实 bot
  - 当前 `signal_tasks.py` 的 `generate_signals_task` 采用"按单个 (strategy_id, pair) 分发独立 Celery 任务"模式，缺乏全局协调；实时信号需要改为"单次全量协调任务 + 两阶段流水线"模式，并通过 Redis `SET NX` 实现幂等锁
  - 现有 `trading_signals` 表结构（含 `timeframe` 字段）已能支撑 upsert 语义，需增加 `(strategy_id, pair, timeframe)` 唯一约束和 `bar_timestamp` / `signal_source` 字段对齐需求规格

---

## 研究日志

### 话题：freqtrade download-data 增量机制

- **背景**: 需求 1.2 要求增量更新而非全量拉取，避免重复下载历史数据。
- **来源**:
  - [Freqtrade Data Download 官方文档](https://www.freqtrade.io/en/stable/data-download/)
  - [freqtrade-original GitHub docs](https://github.com/abhi-murari/freqtrade-original/blob/develop/docs/data-download.md)
- **发现**:
  - 若本地 datadir 已存在对应 (pair + timeframe) 数据文件，freqtrade 自动计算缺失时间段并仅下载差量部分，无需 `--timerange` 参数
  - `--days 30` 配合已有本地文件时，仅补充最近 30 天内缺失的 K 线
  - `--new-pairs-days` 参数可对新加入交易对单独控制初始下载天数
  - 数据文件按 exchange/pair/timeframe 命名，如 `BTC_USDT-1h.json`（spot）或 `BTC_USDT-1h-futures.json`（futures）
  - 需求规格要求使用 futures 模式：`--trading-mode futures` 会自动同时下载 mark 和 funding_rate candle types
- **影响**: 需求 1.2 中"检查本地文件时间戳"的逻辑可大幅简化：只需检查文件是否存在，调用 `download-data` 即可（freqtrade 内部自动增量）；但需求 1.2 中"当前周期内"的新鲜度判断仍需业务层实现，以决定是否跳过本次拉取调用（避免每次信号周期都产生子进程开销）

### 话题：freqtrade Python API 用于信号计算

- **背景**: 需求 2.2 要求通过 freqtrade 方法链计算信号，复用本地 OHLCV 数据。
- **来源**:
  - [Freqtrade Strategy Analysis Example](https://www.freqtrade.io/en/stable/strategy_analysis_example/)
  - [Strategy Customization 官方文档](https://www.freqtrade.io/en/stable/strategy-customization/)
- **发现**:
  - `load_pair_history(datadir, timeframe, pair, data_format="json", candle_type=CandleType.SPOT)` 可直接从本地文件返回 pandas DataFrame
  - 通过 `IStrategy` 实例的 `populate_indicators` → `populate_entry_trend` → `populate_exit_trend` 方法链即可离线计算信号，无需 bot 上下文
  - 现有 `_fetch_signals_sync` 中的 `_build_ohlcv_dataframe`（合成数据）需替换为 `load_pair_history` 调用
  - `candle_type=CandleType.FUTURES` 对应 futures 数据文件格式
- **影响**: `signal_fetcher.py` 的 `_build_ohlcv_dataframe` 需被替换为新的 `_load_ohlcv_from_datadir` 函数，接受 `datadir: Path` 参数

### 话题：Celery 任务幂等锁（分布式锁）

- **背景**: 需求 2.7 要求任务幂等性，通过 Redis 分布式锁防止并发重复执行。
- **来源**:
  - [celery-singleton GitHub](https://github.com/steinitzu/celery-singleton)
  - [celery-once PyPI](https://pypi.org/project/celery_once/)
  - [Distributed Task Locking in Celery](http://loose-bits.com/2010/10/distributed-task-locking-in-celery.html)
- **发现**:
  - 最简方案：任务开始时执行 Redis `SET lock:signal_refresh NX EX <ttl>`，返回 None 表示已有锁（跳过），返回 OK 表示获锁成功；任务结束时 DEL 锁
  - `celery-once` / `celery-singleton` 提供更完整的封装，但引入额外依赖
  - 既有项目已使用 `redis-py`，直接使用其 `SET NX EX` 原语即可，无需引入新依赖
  - 锁 TTL 应等于任务预期最大执行时间（需求 2.7：= 任务超时时间，本设计取 600 秒）
- **影响**: 新增 `acquire_signal_refresh_lock` / `release_signal_refresh_lock` 工具函数，在新建的 `generate_all_signals_task` 中使用

### 话题：数据目录持久化与 Docker Volume

- **背景**: 需求 1.7 要求将 `datadir` 迁移到持久化路径，防止重启后数据丢失。
- **来源**: 需求规格 + 现有 `backtester.py` 中的 `/tmp/freqtrade_jobs/{task_id}/` 隔离目录模式
- **发现**:
  - 现有回测任务使用 `/tmp/freqtrade_jobs/` 作为临时隔离目录，任务结束后清理
  - 行情数据目录与任务隔离目录不同：行情数据需要跨任务持久化复用，不能清理
  - 通过环境变量 `FREQTRADE_DATADIR` 配置持久化路径（默认 `/opt/freqtrade_data`）
  - Docker 部署时需在 `docker-compose.yml` 中挂载该路径为 named volume
- **影响**: `app_settings.py` 需新增 `freqtrade_datadir: Path` 配置项；回测任务与信号任务共享同一 `datadir`

### 话题：现有 trading_signals 表与需求规格差距分析

- **背景**: 需求 3.1 定义了 `trading_signals` 表字段，包含 `bar_timestamp`、`signal_source` 等字段；需核查现有表结构。
- **来源**: `src/models/signal.py`，`migrations/versions/004_create_trading_signals.py`
- **发现**:
  - 现有表缺少 `bar_timestamp` 字段（需求 3.1 中为 K 线 UTC 时间，与 `signal_at` 语义相近但不同）
  - `signal_source` 字段已存在（`server_default="realtime"`）
  - `timeframe` 字段已存在
  - 缺少 `(strategy_id, pair, timeframe)` 唯一约束（需求 3.2, 3.3 要求 upsert 语义）
  - 设计决策：将现有 `signal_at` 字段复用为 `bar_timestamp` 语义（信号对应的 K 线时间），增加 `(strategy_id, pair, timeframe)` 唯一约束以支持 upsert
- **影响**: 需新增 Alembic 迁移：(1) 添加 `(strategy_id, pair, timeframe)` 唯一约束，(2) 在 `signal_at` 上添加普通索引（如果尚不存在），(3) 调整 `signal_source` 列使其具有明确的 "realtime" 默认值

### 话题：API 扩展（需求 4）

- **背景**: 需求 4 定义了两个新 API 端点和分页要求；需核查现有 `signals.py` 路由结构。
- **来源**: `src/api/signals.py`
- **发现**:
  - 现有仅有 `GET /strategies/{strategy_id}/signals` 接口，路径嵌套在 strategies 资源下
  - 需求 4.1 要求 `GET /api/v1/signals`（顶级，按 strategy_id/pair/timeframe 过滤）
  - 需求 4.4 要求 `GET /api/v1/signals/{strategy_id}`（按策略 ID 查询）
  - 需求 4.2/4.3 中的字段权限控制（隐藏 confidence_score）与现有 `SignalRead` Schema 已有机制一致
  - 需求 4.6 要求分页，现有接口仅有 `limit` 参数，无标准分页 schema
- **影响**: 新增 `src/api/signals_v2.py`（或扩展现有），添加两个顶级路由；扩展 `SignalService` 增加过滤和分页支持

---

## 架构模式评估

| 方案 | 描述 | 优势 | 风险/局限 | 备注 |
|------|------|------|-----------|------|
| 方案 A：单协调任务 + 两阶段流水线 | 新建 `generate_all_signals_task` 作为全局协调者，先执行 download-data 子进程（阶段一），再串行调用各 (strategy, pair, timeframe) 信号计算（阶段二） | 清晰的两阶段边界；Redis 分布式锁易实现；符合需求 2.1 串行要求 | 单任务执行时间较长；阶段一失败需降级逻辑 | **选定方案** |
| 方案 B：保留现有分散任务 + 前置 download-data beat | 新增一个独立 Beat 任务专门执行 download-data，signal_tasks 保持现状 | 改动最小 | 两个 Beat 任务之间无协调机制；download-data 完成前 signal 任务可能已触发；难以保证串行 | 不选 |
| 方案 C：Celery Chain | 使用 Celery `chain()` 将 download 任务和信号计算任务串联 | Celery 原生支持 | 需要将信号计算分解为多个子任务并协调；复杂度高 | 不选 |

---

## 设计决策

### 决策：复用 `signal_at` 字段语义为 K 线时间戳

- **背景**: 需求 3.1 定义 `bar_timestamp`（K 线 UTC 时间），现有表有 `signal_at` 字段
- **备选**:
  1. 新增 `bar_timestamp` 列，保留 `signal_at` 作为生成时间
  2. 复用 `signal_at` 承载 K 线时间戳语义，新增 `generated_at` 列（或直接用 `created_at`）
- **选定方案**: 方案 2 + 将 `created_at` 视为 `generated_at`，不引入新列；在代码注释中明确 `signal_at` = K 线时间戳
- **理由**: 避免迁移复杂度；`created_at` 已由 `server_default=func.now()` 自动填充，等效于 `generated_at`
- **权衡**: 字段命名略有歧义，但通过注释和文档对齐

### 决策：使用 Redis SET NX EX 原语实现分布式锁

- **背景**: 需求 2.7 要求幂等性分布式锁
- **备选**:
  1. 引入 `celery-once` 或 `celery-singleton` 第三方库
  2. 直接使用 `redis-py` 的 `SET NX EX` 原语
- **选定方案**: 方案 2
- **理由**: 项目已依赖 `redis-py`；无需引入额外库；实现简单透明，TTL 可精确控制
- **权衡**: 需要手动处理锁释放（try/finally），方案 1 更自动化

### 决策：`_build_ohlcv_dataframe` 替换为 `load_pair_history`

- **背景**: 现有信号获取使用合成数据，需替换为真实 Binance 数据
- **备选**:
  1. 在 `signal_fetcher.py` 中替换数据加载逻辑
  2. 新建独立的 `realtime_signal_fetcher.py` 文件，保留旧文件
- **选定方案**: 方案 1（原地替换 `_build_ohlcv_dataframe`，新增 `_load_ohlcv_from_datadir`）
- **理由**: 保持模块组织一致性；旧合成数据函数不再需要；降低并行维护负担
- **权衡**: 若需要回滚到合成数据，需要 git revert

### 决策：`generate_signals_task` 重构为 `generate_all_signals_task`

- **背景**: 现有 `generate_signals_task` 接受单个 (strategy_id, pair) 参数；需求要求全局协调两阶段流水线
- **备选**:
  1. 保留现有任务接口，在 Beat 调度中扩展
  2. 新建 `generate_all_signals_task`，保留旧任务兼容性
- **选定方案**: 方案 2（新建 `generate_all_signals_task` 作为主协调任务，旧任务可保留但从 Beat 中移除）
- **理由**: 避免破坏现有单元测试；新任务接口清晰；旧任务可用于单策略调试
- **权衡**: 同时维护两个任务函数，需要注意 Beat 调度中仅启用新任务

---

## 风险与缓解措施

- **Binance API 限速风险** — freqtrade 内置 ccxt 层自动退避重试（429/418 处理），业务层添加 download-data 失败时的降级逻辑（使用本地已有数据）；满足需求 1.5, 1.6
- **子进程泄漏风险** — `subprocess.run` 设置 `timeout=300`，超时后抛出 `subprocess.TimeoutExpired`；满足需求 6.3
- **datadir 文件并发写入风险** — download-data 作为全局单一进程执行（受分布式锁保护），不存在并发写入问题；满足需求 1.8
- **trading_signals 表无限增长风险** — 通过 `(strategy_id, pair, timeframe)` 唯一约束 + upsert 语义每组合仅保留一条最新记录；满足需求 2.6
- **信号计算失败不中断整体流程** — 对每个 (strategy, pair, timeframe) 组合独立 try/except，记录 ERROR 后继续；满足需求 2.5
- **连续失败告警** — 在协调任务中维护连续失败计数器（Redis key: `signal:consecutive_failures`），达到 3 次时记录 ERROR 告警；满足需求 5.4

---

## 参考资料

- [Freqtrade Data Download 官方文档](https://www.freqtrade.io/en/stable/data-download/)
- [Freqtrade Strategy Analysis Example](https://www.freqtrade.io/en/stable/strategy_analysis_example/)
- [Freqtrade Strategy Customization](https://www.freqtrade.io/en/stable/strategy-customization/)
- [celery-singleton GitHub](https://github.com/steinitzu/celery-singleton)
- [celery-once PyPI](https://pypi.org/project/celery_once/)
- [Redis SET NX EX 分布式锁模式](http://loose-bits.com/2010/10/distributed-task-locking-in-celery.html)
- [RedBeat Scheduler](https://github.com/sibson/redbeat)
