# 实施计划

## 任务列表

- [x] 1. 配置与数据层扩展
- [x] 1.1 (P) 新增持久化行情目录配置项
  - 在应用配置中新增 `FREQTRADE_DATADIR` 环境变量支持，默认值为 `/opt/freqtrade_data`
  - 同步新增 `SIGNAL_REFRESH_INTERVAL` 配置项（crontab 表达式，默认 `"0 * * * *"`）和 `SIGNAL_PAIRS`、`SIGNAL_TIMEFRAMES` 列表配置项
  - 确保配置读取失败时有合理的启动告警
  - _Requirements: 1.7, 2.8_

- [x] 1.2 (P) 创建数据库迁移添加唯一约束和索引
  - 在 `trading_signals` 表上添加 `UNIQUE(strategy_id, pair, timeframe)` 唯一索引，迁移前先清理同一组合的重复记录（保留最新一条）
  - 在 `created_at` 列上添加普通降序索引以加速时间范围查询
  - 确认并补充 `timeframe` 列的 `NOT NULL` 约束（如当前为 NULLABLE 则修改），以及 `signal_source` 列的默认值 `'realtime'`
  - 迁移文件命名为 `007_add_trading_signals_constraints.py`，包含向下迁移（回滚）逻辑
  - _Requirements: 3.2, 3.3_

- [x] 2. DataDownloader：行情拉取组件
- [x] 2.1 实现新鲜度检查逻辑
  - 实现读取本地 datadir 中 (pair + timeframe) 对应数据文件、解析最后一根 K 线时间戳的能力
  - 判断最后一根 K 线是否在当前时间周期内（如 1h 周期：距当前不超过 1 小时），结果返回布尔值
  - 处理文件不存在或解析失败的情况（返回 False，触发下载）
  - _Requirements: 1.2_

- [x] 2.2 实现 download-data 子进程调用
  - 在 Celery Worker 中通过 `subprocess.run` 调用 `freqtrade download-data` CLI，生成隔离配置文件（无账户凭据、`dry_run: true`、禁用 Telegram/RPC）
  - 配置文件写入 `/tmp/freqtrade_signals/{task_id}/config.json`，子进程超时设置为 300 秒（超时后强制终止进程）
  - 非零退出码时抛出 `FreqtradeExecutionError`；超时时抛出 `FreqtradeTimeoutError`
  - 禁止在子进程调用前后删除或清空 `datadir` 下任何 OHLCV 文件
  - _Requirements: 1.3, 1.4, 1.5, 1.8, 1.10, 6.1, 6.2, 6.3_

- [x] 2.3 实现降级与汇总结果
  - 当 download-data 失败但本地文件存在时，降级使用本地数据并在日志中标记 `data_source=local_fallback`
  - 当 download-data 失败且无本地文件时，抛出异常终止当前流程
  - `download_market_data` 方法汇总各交易对的下载状态（已下载数/已跳过数/失败数），以 `DownloadResult` 数据对象返回
  - 任务结束后清理 `/tmp/freqtrade_signals/{task_id}/` 临时配置文件（不影响 datadir）
  - _Requirements: 1.1, 1.6, 1.9, 6.4, 6.5_

- [x] 3. SignalCalculator：信号计算组件
- [x] 3.1 实现从本地 datadir 加载 OHLCV 数据
  - 使用 `freqtrade.data.history.load_pair_history` 从持久化 datadir 加载指定 (pair, timeframe) 的 OHLCV DataFrame
  - 在内存中按 (pair, timeframe) 对 DataFrame 做一次性缓存，同一组合内所有策略复用同一份数据，避免重复文件 I/O
  - 文件不存在或加载失败时抛出 `FreqtradeExecutionError`
  - _Requirements: 2.2_

- [x] 3.2 实现策略方法链信号提取
  - 从策略注册表获取所有激活策略，通过 `IStrategy` 子类实例化（`strategy_class(config={})`）在进程内执行，不启动真实 bot
  - 对每个 (strategy, pair, timeframe) 组合依次调用 `populate_indicators` → `populate_entry_trend` → `populate_exit_trend` 方法链，提取 DataFrame 最后一行的信号类型和置信度
  - 单个组合执行失败时捕获异常、记录 ERROR 日志，继续处理下一组合，不中断整体流程
  - _Requirements: 2.3, 2.5_

- [x] 3.3 实现信号 upsert 持久化和缓存更新
  - 使用 PostgreSQL `INSERT ... ON CONFLICT (strategy_id, pair, timeframe) DO UPDATE` 语句，将信号结果（策略 ID、交易对、时间周期、信号类型、置信度、K 线时间戳、数据来源）以 upsert 方式写入 `trading_signals` 表
  - 写入成功后将该策略的最新信号以 JSON 形式更新至 Redis（key: `signal:{strategy_id}`，TTL: 3600 秒）
  - 数据库写入失败时记录 ERROR 日志并将异常上报，Redis 写入失败时静默降级并记录 WARNING
  - 计算所有组合处理完成后的汇总指标（总组合数、成功数、失败数、内存 DataFrame 复用率），以 `SignalComputeResult` 返回
  - _Requirements: 2.4, 2.6, 3.1, 3.4_

- [x] 4. CoordTask：全局协调任务
- [x] 4.1 实现分布式锁与幂等调度
  - 在 Celery 任务入口处通过 Redis `SET lock:signal_refresh NX EX 600` 获取分布式锁；锁已存在时记录日志后直接返回，不执行任何操作
  - 任务结束（成功或失败）时通过 `finally` 块释放锁并清理临时目录
  - _Requirements: 2.7_

- [x] 4.2 实现两阶段流水线串行执行
  - 新建 `generate_all_signals_task` Celery 任务，从数据库读取所有激活策略和对应交易对，先串行执行阶段一（调用 DataDownloader），再串行执行阶段二（调用 SignalCalculator），两阶段严格顺序执行
  - 从旧版 `generate_signals_task` 的 Celery Beat 调度配置中移除旧任务，保留函数定义供调试使用
  - _Requirements: 2.1_

- [x] 4.3 实现结构化汇总日志与连续失败告警
  - 任务完成（成功或失败）后，以结构化 JSON 格式记录汇总日志，包含总耗时、阶段一耗时、拉取交易对数、缓存命中率、组合成功/失败数、数据来源标记
  - 维护 Redis 计数器 `signal:consecutive_failures`：任务成功时重置为 0，失败时 INCR；计数达到 3 时记录 ERROR 级别告警日志
  - _Requirements: 5.2, 5.4_

- [x] 4.4 配置 Celery Beat 定时调度
  - 将 `generate_all_signals_task` 注册到 Celery Beat，默认调度规则为 `crontab(minute=0, hour="*")`（每小时整点触发）
  - 调度间隔从环境变量 `SIGNAL_REFRESH_INTERVAL` 读取（支持 crontab 表达式格式）
  - _Requirements: 5.1_

- [x] 5. 信号查询 API 扩展
- [x] 5.1 (P) 扩展 SignalService 以支持过滤和分页
  - 新增 `list_signals` 方法，支持 `strategy_id`、`pair`、`timeframe` 可选过滤参数和 `page`/`page_size` 标准分页（默认 20，上限 100）
  - 查询优先从 Redis 缓存读取并在内存中过滤分页，缓存未命中时回退到 PostgreSQL 查询
  - `strategy_id` 指定但策略不存在时抛出 `NotFoundError(code=3001)`
  - 保留现有 `get_signals` 方法不变（向后兼容）
  - _Requirements: 4.1, 4.5, 4.6, 4.7_

- [x] 5.2 (P) 扩展 SignalRead Schema 字段别名和会员权限控制
  - 在 `SignalRead` Schema 中确认 `signal_type`（对应 ORM `direction` 字段）和 `bar_timestamp`（对应 ORM `signal_at` 字段）别名映射
  - 通过现有 `filter_by_tier` 机制：匿名和 Free 用户 `confidence` 字段返回 `null`，VIP1 及以上用户返回实际数值
  - 确保 `generated_at` 字段映射至 ORM `created_at`，保持 API 字段命名与需求规格一致
  - _Requirements: 4.2, 4.3_

- [x] 5.3 新增顶级信号查询路由
  - 在 `src/api/` 新建顶级信号路由模块，注册以下两个端点：`GET /api/v1/signals`（支持 `strategy_id`、`pair`、`timeframe`、`page`、`page_size` 查询参数）和 `GET /api/v1/signals/{strategy_id}`（返回该策略在所有激活交易对上的最新信号）
  - 两个端点均通过 `get_optional_user` 依赖注入获取当前用户信息（允许匿名），并将会员等级传入 Schema 过滤逻辑
  - 响应使用统一信封格式 `ApiResponse[PaginatedResponse[SignalRead]]`；策略不存在时返回 3001/404
  - 在 `src/api/main_router.py` 中注册该路由，前缀 `/api/v1`
  - _Requirements: 4.1, 4.4, 4.5, 4.6_

- [x] 6. 管理员接口与后台视图
- [x] 6.1 (P) 新增管理员手动刷新信号接口
  - 实现 `POST /api/v1/admin/signals/refresh` 端点，通过 `require_admin` 依赖验证管理员权限（`current_user.is_admin == True`）
  - 调用 `generate_all_signals_task.delay()` 将任务异步入队，返回 Celery `task_id` 和提示消息
  - 非管理员请求返回 1002/403
  - _Requirements: 5.5_

- [x] 6.2 (P) 扩展 sqladmin 信号只读视图
  - 扩展现有 `TradingSignalAdmin` ModelView，设置 `can_create=False`、`can_edit=False`、`can_delete=False`，确保只读
  - 在列表视图中启用按策略 ID、信号类型（BUY/SELL/HOLD）、时间范围筛选的过滤功能
  - _Requirements: 5.3_

- [x] 7. 安全隔离验证
- [x] 7.1 确保 freqtrade 配置安全隔离
  - 验证生成的每份 freqtrade 配置文件均包含 `"dry_run": true`，不含任何 `exchange.key` / `exchange.secret` 字段
  - 验证 freqtrade 配置中禁用了 `telegram` 和 `api_server`（RPC 接口）节
  - 确认日志输出中不含 datadir 的完整绝对路径；API 响应中不含内部路径或账户信息
  - _Requirements: 6.1, 6.2, 6.4_

- [x] 8. 单元测试
- [x] 8.1 (P) DataDownloader 单元测试
  - 测试新鲜度检查：数据在当前周期内（跳过）、数据过期（触发下载）、文件不存在（触发下载）三种路径
  - Mock `subprocess.run`，测试超时抛出 `FreqtradeTimeoutError`、非零退出码抛出 `FreqtradeExecutionError`、成功执行三种分支
  - 测试降级逻辑：download-data 失败但本地文件存在时正确标记 `data_source=local_fallback`
  - _Requirements: 1.2, 1.3, 1.6, 1.9_

- [x] 8.2 (P) SignalCalculator 单元测试
  - Mock `load_pair_history`，测试文件不存在时的 `FreqtradeExecutionError` 抛出
  - 测试 upsert 路径：INSERT（首次写入）和 UPDATE（唯一冲突时覆盖已有记录）两种分支
  - 测试单个组合异常时不中断其余组合的处理（容错循环逻辑）
  - _Requirements: 2.2, 2.5, 2.6, 3.4_

- [x] 8.3 (P) CoordTask 单元测试
  - Mock Redis，测试锁已存在时任务幂等跳过、锁获取成功时正常执行
  - 测试连续失败计数器：失败时 INCR、成功时重置为 0、连续 3 次失败时触发 ERROR 告警日志
  - _Requirements: 2.7, 5.4_

- [x] 8.4 (P) SignalService 单元测试
  - 测试 `list_signals` 各过滤参数组合（仅 strategy_id、仅 pair、组合过滤）
  - 测试分页偏移计算（page=2, page_size=10 → offset=10）
  - 测试 Redis 不可用时降级回 DB 查询
  - 测试 strategy_id 不存在时抛出 `NotFoundError`
  - _Requirements: 4.1, 4.5, 4.6, 4.7_

- [x] 9. 集成测试
- [x] 9.1 (P) DataDownloader + 本地文件集成测试
  - 使用测试 fixtures 的本地 OHLCV 文件（非真实 Binance 请求），验证新鲜度检查正确跳过已有新鲜数据
  - 验证降级逻辑：模拟 download-data 子进程失败时，现有本地文件被正确使用
  - _Requirements: 1.2, 1.9_

- [x] 9.2 (P) 信号计算端到端集成测试
  - 给定测试用本地 OHLCV 文件，执行 `compute_all_signals`，验证数据库中每个 (strategy_id, pair, timeframe) 组合仅存在一条最新记录（upsert 语义验证）
  - _Requirements: 2.6, 3.2_

- [x] 9.3 (P) 信号查询 API 集成测试
  - 测试 `GET /api/v1/signals` 过滤和分页参数的正确性
  - 测试匿名用户请求时 `confidence` 字段为 `null`；VIP1 用户请求时返回实际置信度数值
  - 测试 `GET /api/v1/signals/{strategy_id}` 在策略不存在时返回 3001/404
  - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5_

- [x] 9.4 (P) 管理员接口集成测试
  - 测试 `POST /api/v1/admin/signals/refresh` 需要管理员权限：非管理员返回 1002/403
  - 测试管理员请求时任务成功入队并返回 `task_id`
  - _Requirements: 5.5_
