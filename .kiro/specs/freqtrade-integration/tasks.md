# 实施计划

- [x] 1. 数据库模型扩展与迁移
- [x] 1.1 (P) 为 User 模型新增管理员标记字段
  - 在 `User` 模型中添加 `is_admin` 布尔字段，`server_default='false'`，存量用户默认非管理员
  - 编写 Alembic 迁移文件，实现 `upgrade()` 和 `downgrade()`，确保存量数据不受影响
  - 在 `src/core/deps.py` 中新增 `require_admin` 鉴权 Depends，校验 `user.is_admin`，不符则抛 `PermissionError(1002)`
  - _Requirements: 1.1, 4.2_

- [x] 1.2 (P) 扩展交易信号表至 11 个字段
  - 在 `TradingSignal` 模型中新增 `signal_source`（`server_default='realtime'`）及 8 个扩展字段：`entry_price`、`stop_loss`、`take_profit`、`indicator_values`（JSONB）、`timeframe`、`signal_strength`、`volume`、`volatility`，所有扩展字段允许 NULL
  - 编写 Alembic 迁移文件，合并 `signal_source` 和 8 个扩展列到同一迁移，实现 `upgrade()` 和 `downgrade()`
  - 为 `trading_signals` 表新增 `idx_signal_strategy_source(strategy_id, signal_source)` 索引
  - 确认现有 `generate_signals_task` 写入路径不受新增可 NULL 字段影响（向后兼容）
  - _Requirements: 2.3, 2.4, 2.5_

- [x] 2. freqtrade 桥接层基础设施
- [x] 2.1 (P) 新增 UnsupportedStrategyError 异常类
  - 在 `src/core/exceptions.py` 中添加 `UnsupportedStrategyError(AppError, code=3003)`，默认消息为"策略不受支持，请联系管理员"
  - 在全局异常处理器中为 `code=3003` 映射 HTTP 422 状态码
  - _Requirements: 3.7, 5.1_

- [x] 2.2 (P) 实现 STRATEGY_REGISTRY 策略注册表
  - 在 `src/freqtrade_bridge/strategy_registry.py` 中定义 `StrategyRegistryEntry` TypedDict（含 `class_name` 和 `file_path`）
  - 创建 `STRATEGY_REGISTRY` 全局常量字典，建立数据库 `Strategy.name` ↔ freqtrade 类名 ↔ 策略文件绝对路径的三元映射，覆盖全部十个策略：`TurtleTrading`、`BollingerMeanReversion`、`RsiMeanReversion`、`MacdTrend`、`IchimokuTrend`、`ParabolicSarTrend`、`KeltnerBreakout`、`AroonTrend`、`Nr7Breakout`、`StochasticReversal`
  - 实现 `lookup(strategy_name)` 辅助函数，策略不存在时抛 `UnsupportedStrategyError`；在 `lookup()` 内验证 `file_path` 实际存在并记录告警日志
  - `file_path` 在模块加载时基于 `__file__` 解析为绝对路径，进程生命周期内不可变
  - _Requirements: 3.5, 3.7, 7.3, 7.4_

- [x] 3. 十个经典策略文件预置
- [x] 3.1 (P) 实现趋势跟随策略文件（4 个）
  - 在 `src/freqtrade_bridge/strategies/` 下创建 `turtle_trading.py`（`TurtleTrading`）、`macd_trend.py`（`MacdTrend`）、`ichimoku_trend.py`（`IchimokuTrend`）、`parabolic_sar_trend.py`（`ParabolicSarTrend`）四个文件
  - 每个文件声明 `INTERFACE_VERSION = 3`，实现 `populate_indicators`、`populate_entry_trend`、`populate_exit_trend` 三个方法；信号列使用 `enter_long` / `exit_long`
  - `populate_indicators` 计算并返回策略所需全部技术指标列，确保不出现 `KeyError` 或 `AttributeError`；仅使用 freqtrade 内置的 `pandas-ta`
  - 每个文件可独立通过 `freqtrade backtesting --strategy <ClassName>` 执行而不报错
  - _Requirements: 7.1, 7.2, 7.8, 7.9_

- [x] 3.2 (P) 实现均值回归策略文件（3 个）
  - 在 `src/freqtrade_bridge/strategies/` 下创建 `bollinger_mean_reversion.py`（`BollingerMeanReversion`）、`rsi_mean_reversion.py`（`RsiMeanReversion`）、`stochastic_reversal.py`（`StochasticReversal`）三个文件
  - 每个文件遵循与 3.1 相同的接口约束（`INTERFACE_VERSION = 3`、三个核心方法、`enter_long`/`exit_long`、`pandas-ta`）
  - `populate_indicators` 包含各策略所有必需指标（布林带、RSI、随机指标），确保回测可完整执行
  - _Requirements: 7.1, 7.2, 7.8, 7.9_

- [x] 3.3 (P) 实现突破策略文件（2 个）
  - 在 `src/freqtrade_bridge/strategies/` 下创建 `keltner_breakout.py`（`KeltnerBreakout`）、`nr7_breakout.py`（`Nr7Breakout`）两个文件
  - 每个文件遵循与 3.1 相同的接口约束；`KeltnerBreakout` 计算凯尔特纳通道宽度，`Nr7Breakout` 计算 NR7 窄幅区间
  - _Requirements: 7.1, 7.2, 7.8, 7.9_

- [x] 3.4 (P) 实现趋势识别策略文件（1 个）并提供配置模板
  - 在 `src/freqtrade_bridge/strategies/` 下创建 `aroon_trend.py`（`AroonTrend`）；遵循相同接口约束
  - 在 `src/freqtrade_bridge/config_template.json` 中提供默认 freqtrade 配置模板：包含 `BTC/USDT`、`ETH/USDT`、`BNB/USDT`、`SOL/USDT` 四个交易对，时间周期 `1h`，回测日期范围以 `"timerange": "{{TIMERANGE}}"` 占位符表示，不包含任何 API Key 或交易所凭证
  - 将上述十个策略文件和配置模板纳入 Git 追踪（确认 `.gitignore` 不排除 `*.py` 和 `*.json`）
  - _Requirements: 7.1, 7.2, 7.5, 7.8, 7.9_

- [x] 4. 种子数据脚本
- [x] 4.1 实现幂等策略种子数据脚本
  - 在 `src/freqtrade_bridge/seeds/seed_strategies.py` 中实现批量 INSERT 脚本，内嵌十条策略记录（`name`、`description`、`category` 字段），`name` 值与 `STRATEGY_REGISTRY` 键名完全一致
  - 以幂等方式写入：若同名策略记录已存在则跳过（使用 `INSERT ... ON CONFLICT DO NOTHING` 或先 SELECT 再按需 INSERT），不破坏已有数据
  - 同时在 `tests/fixtures/strategy_fixtures.py` 中提供等效的 pytest fixture 形式供测试环境使用
  - 脚本使用 SQLAlchemy 同步 session（`psycopg2` 驱动），兼容迁移脚本和 CLI 调用场景
  - _Requirements: 7.6, 7.7, 7.9_

- [x] 5. Celery Worker 与回测任务逻辑扩展
  - 注：本任务依赖任务 2（STRATEGY_REGISTRY）和任务 1（数据模型迁移），须在二者完成后进行

- [x] 5.1 调整 Celery backtest 队列并发配置
  - 将 `celery_app.py` 中 `backtest` 队列对应的 Worker 并发数配置为 `concurrency=1`，确保任意时刻最多 1 个回测任务处于 RUNNING 状态
  - 确认 Redis broker 地址通过环境变量配置，与 FastAPI 主服务共用同一 Redis 实例
  - 移除旧版 `RUNNING_BACKTEST_LIMIT` 环境变量引用（若存在）
  - _Requirements: 1.8, 6.2, 6.5_

- [x] 5.2 扩展 run_backtest_task 策略文件复制逻辑
  - 在 `run_backtest_task` 中调用 `StrategyRegistry.lookup(strategy.name)` 获取策略文件路径；策略查找失败时将任务置 FAILED 并记录错误
  - 在任务临时目录 `/tmp/freqtrade_jobs/{task_id}/` 下创建 `strategy/` 和 `results/` 子目录，将策略文件以复制方式放置到 `strategy/` 子目录
  - 移除 `run_backtest_subprocess` 的 `timeout` 参数，任务运行至自然结束（成功或失败）
  - 确保 `concurrency=1` 串行机制而非服务层 RUNNING 计数守卫实现串行约束
  - _Requirements: 1.3, 1.4, 1.8, 3.1, 3.6, 6.4_

- [x] 5.3 扩展 run_backtest_task DONE 后置逻辑
  - 回测子进程成功后将 `total_return`、`annual_return`、`sharpe_ratio`、`max_drawdown`、`trade_count`、`win_rate` 六项指标序列化写入 `BacktestTask.result_json`，状态更新为 DONE
  - DONE 后检查 `Strategy` 表对应指标字段是否为 NULL，若为 NULL 则更新为回测结果值，若字段已有值则跳过
  - DONE 后将回测过程中产生的交易信号从 `backtest_output["signals"]` 以 INSERT 方式追加写入 `trading_signals`，`signal_source='backtest'`，并填充可用的 11 个扩展字段
  - 通过 structlog 记录结构化日志，包含 `task_id`、`strategy`、`exit_code`、`duration_ms`；stderr 截断至 2000 字符写入 `error_message`
  - _Requirements: 1.5, 1.6, 2.5, 5.3, 5.4_

- [x] 5.4 完善 run_backtest_task 失败处理
  - 子进程非零退出码或异常时将任务置 FAILED，将 stderr 截断至 2000 字符写入 `error_message`，不在 HTTP 响应中透传原始 traceback
  - 所有 freqtrade 执行错误封装为 `FreqtradeExecutionError`，不向上层泄漏 freqtrade 内部异常类型
  - 任务无论 DONE 或 FAILED 均清理 `/tmp/freqtrade_jobs/{task_id}/` 临时目录
  - _Requirements: 1.7, 3.3, 5.1, 5.2_

- [x] 6. 信号生成逻辑完善
  - 注：本任务依赖任务 1.2（TradingSignal 模型扩展）和任务 3（策略文件），须在二者完成后进行

- [x] 6.1 实现 _fetch_signals_sync 信号生成核心逻辑
  - 完成 `src/freqtrade_bridge/signal_fetcher.py` 中 `_fetch_signals_sync(strategy, pair)` 占位方法的实际实现，调用 freqtrade IStrategy 生成信号
  - 输出包含 11 个字段的信号数据：`pair`、`direction`（Buy/Sell/Hold）、`confidence_score`、`entry_price`、`stop_loss`、`take_profit`、`indicator_values`（技术指标快照 JSON）、`timeframe`、`signal_strength`、`volume`、`volatility`
  - 通过 `ProcessPoolExecutor(max_workers=2)` 在独立进程中执行，最大并发进程数通过环境变量 `SIGNAL_MAX_WORKERS` 可配置（默认 2）
  - 支持多交易对并发信号生成（BTC/USDT、ETH/USDT 等主流币种）
  - _Requirements: 2.1, 2.2, 2.3, 2.6_

- [x] 6.2 完善 generate_signals_task 信号写入与日志
  - 更新 `generate_signals_task` 将信号以 INSERT 方式追加写入 `trading_signals`，显式传入 `signal_source='realtime'` 及全部 11 个扩展字段，禁止 UPDATE 或 DELETE 已有记录
  - 信号生成失败时记录结构化错误日志（含策略名、交易对、错误信息、时间戳），跳过本次写入，不影响 API 正常响应
  - 每次信号生成记录结构化日志：策略名、交易对、信号类型、信号来源（realtime）、执行耗时，遵循 structlog JSON 格式
  - 确认 Celery Beat 信号生成计划（每 15 分钟触发 `generate_signals_task`）中刷新周期通过配置项 `SIGNAL_REFRESH_INTERVAL` 控制，默认不超过 5 分钟
  - _Requirements: 2.1, 2.3, 2.4, 2.7, 2.9_

- [x] 7. 管理员回测服务层
  - 注：本任务依赖任务 1.1（User.is_admin 及 require_admin）、任务 2.1（UnsupportedStrategyError）、任务 2.2（STRATEGY_REGISTRY）

- [x] 7.1 实现 AdminBacktestService
  - 创建 `src/services/admin_backtest_service.py`，实现 `submit_backtest(db, strategy_id, timerange)`：通过 `StrategyRegistry.lookup()` 校验策略在注册表中存在，不存在则抛 `UnsupportedStrategyError(3003)`；通过 `AdminBacktestService` 预检临时目录可用性，失败则抛 `FreqtradeError(5001)`
  - 校验通过后创建 `BacktestTask(PENDING)` 写入数据库，通过 `celery_app.send_task` 异步入队后立即返回 `task_id`，不等待回测执行结果；不检查 RUNNING 任务数，任务始终可入队，不返回 `code:3002`
  - 实现 `get_task(db, task_id)`：task_id 不存在时抛 `NotFoundError(3001)`
  - 实现 `list_tasks(db, page, page_size, strategy_name, status)`：支持按 `strategy_name` 和 `status` 筛选，按 `created_at` 降序分页返回
  - DONE 状态的查询响应中包含完整的六项回测指标，无字段裁剪
  - _Requirements: 1.1, 1.2, 1.7, 1.9, 4.1, 4.3, 4.4, 4.5, 5.5_

- [x] 8. 管理员回测 API 路由层
  - 注：本任务依赖任务 7（AdminBacktestService）和任务 1.1（require_admin）

- [x] 8.1 实现管理员专属回测 HTTP 端点
  - 创建 `src/api/admin_backtests.py`，定义三个端点：
    - `POST /api/v1/admin/backtests`：接收 `BacktestSubmitRequest`（`strategy_id: int`，`timerange: str` 格式 `YYYYMMDD-YYYYMMDD`），调用 `AdminBacktestService.submit_backtest`，返回 `ApiResponse[BacktestTaskRead]`（status=PENDING），HTTP 响应在 500ms 内返回
    - `GET /api/v1/admin/backtests/{task_id}`：调用 `AdminBacktestService.get_task`，返回任务状态、创建时间、完成时间及结果摘要
    - `GET /api/v1/admin/backtests`：调用 `AdminBacktestService.list_tasks`，支持 `page`、`page_size`、`strategy_name`、`status` 查询参数，返回分页数据
  - 所有端点通过 `Depends(require_admin)` 强制管理员鉴权，非管理员请求返回 `code:1002`，HTTP 403
  - 在 `src/api/__init__.py`（或 `main_router.py`）中以 `/api/v1` 前缀注册该路由
  - 确认路由层仅执行入队操作，不等待 freqtrade 执行结果（满足解耦约束）
  - 定义 `BacktestSubmitRequest`、`BacktestTaskRead`、`BacktestResultSummary` Pydantic Schema
  - _Requirements: 1.1, 1.2, 1.9, 4.1, 4.2, 4.3, 4.4, 4.5, 6.3_

- [x] 9. 架构边界与解耦验证
- [x] 9.1 验证 freqtrade_bridge 层单向依赖约束
  - 确认 `src/freqtrade_bridge/` 下所有文件不引用 `src/api/` 层的任何 `Request`、`Response`、`APIRouter` 对象
  - 确认信号查询接口（`SignalService`）直接从 `trading_signals` 表按 `created_at` 降序取最新一条，不实时调用 freqtrade
  - 确认 Celery Worker 作为独立进程运行，与 FastAPI 主进程通过 Redis broker 通信，不共享内存状态
  - 确认配置生成的 `config.json` 中不包含任何敏感 API Key 或交易所凭证，所有敏感配置从环境变量注入
  - 不同 Worker 实例的临时目录通过唯一 `task_id` 命名，路径互不冲突
  - _Requirements: 3.2, 3.8, 3.9, 6.1, 6.2, 6.4_

- [x] 10. 单元测试
- [x] 10.1 (P) StrategyRegistry 与种子数据单元测试
  - 测试 `StrategyRegistry.lookup()` 对十个有效策略名各返回正确 `class_name` 和实际存在的 `file_path`
  - 测试无效策略名抛 `UnsupportedStrategyError`
  - 测试 `SeedData` 脚本幂等性：同名记录不重复插入，多次执行不破坏已有数据
  - _Requirements: 3.5, 3.7, 7.3, 7.4, 7.6, 7.7_

- [x] 10.2 (P) AdminBacktestService 与 require_admin 单元测试
  - 测试 `require_admin` Depends：`is_admin=True` 通过，`is_admin=False` 抛 `PermissionError(1002)`
  - 测试 `AdminBacktestService.submit_backtest`：Mock `StrategyRegistry.lookup`、`BacktestTask` 插入、`celery.send_task`；验证合法策略直接入队（不检查 RUNNING 数）；验证不支持策略返回 3003
  - 测试 `run_backtest_task`：验证调用 `run_backtest_subprocess` 时无 `timeout` 参数传入
  - _Requirements: 1.1, 1.8, 1.9, 3.7, 4.2_

- [x] 11. 集成测试
- [x] 11.1 (P) 管理员回测 API 集成测试
  - 测试 `POST /api/v1/admin/backtests`：非管理员用户返回 403 + `code:1002`；管理员提交有效请求返回 200 + `task_id`；策略不在注册表返回 422 + `code:3003`；同策略重复提交返回 200（不返回 409 或 `code:3002`）
  - 测试 `GET /api/v1/admin/backtests/{task_id}`：正常返回任务详情；task_id 不存在返回 404 + `code:3001`
  - 测试 `GET /api/v1/admin/backtests`：验证分页和筛选功能
  - _Requirements: 1.1, 1.2, 1.7, 1.9, 4.1, 4.2, 4.3, 4.4_

- [x] 11.2 (P) 回测任务状态流转集成测试
  - 测试 `run_backtest_task`（使用 Mock freqtrade）：验证 PENDING → RUNNING → DONE 状态流转
  - 验证 `BacktestResult` 六项指标正确写入，`trading_signals` 扩展 11 字段以 `signal_source='backtest'` 正确 INSERT
  - 验证 Strategy NULL 字段在 DONE 后被回测结果填充，非 NULL 字段不被覆盖
  - 验证任务结束后临时目录自动清理
  - _Requirements: 1.4, 1.5, 1.6, 2.5, 3.3_

- [x] 11.3 (P) 信号生成集成测试
  - 测试 `generate_signals_task`：验证 `signal_source='realtime'` 写入及全部 11 个扩展信号字段正确 INSERT
  - 验证 `trading_signals` 表只增不删，不执行 UPDATE 或 DELETE
  - 验证信号查询接口按 `created_at` 降序取最新一条，Redis 缓存命中响应时间 < 200ms
  - _Requirements: 2.3, 2.4, 2.8_

- [ ]* 11.4 管理员回测性能验收测试（可选）
  - 验证管理员提交回测请求 HTTP 响应时间 < 500ms（任务入队后立即返回，p99）
  - 验证 Celery `backtest` 队列 `concurrency=1`：同时只有 1 个 RUNNING 任务，其余为 PENDING 状态排队
  - 确认此测试覆盖需求 1.2 和 1.8 中的性能与串行验收标准
  - _Requirements: 1.2, 1.8_
