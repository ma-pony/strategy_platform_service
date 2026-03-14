# 需求文档

## 简介

本文档定义量化策略展示平台中 freqtrade 集成与对接功能的完整需求。该功能将 freqtrade 量化引擎与 FastAPI 后端服务进行深度集成，涵盖管理员专属回测任务调度（API 触发与后台自动运行）、持久化交易信号生成、配置隔离、任务生命周期管理及字段级权限控制等核心能力。平台不向普通用户开放回测功能，回测完全由系统后台管理，用户仅负责查看展示结果。freqtrade 所有交互封装在 `src/freqtrade_bridge/` 层，通过 Celery Worker 与 FastAPI 主进程完全解耦，确保 Web 事件循环不被阻塞。

---

## 需求

### 需求 1：freqtrade 回测任务提交与异步执行（仅管理员）

**目标：** 作为平台后台运营管理员，我希望能够通过管理员专属 API 手动触发或由后台定时任务自动触发 freqtrade 回测，以便在不阻塞 Web 服务的情况下获取策略历史表现数据，并将回测结果更新到数据库中的策略指标字段。

#### 验收标准

1. When 管理员通过管理员 API 提交回测请求，the Backtest Service shall 校验请求方是否持有管理员权限（`is_admin=True`），非管理员请求返回 `code: 1002`，HTTP 状态码 403。
2. When 管理员 API 或后台定时任务触发回测，the Backtest Service shall 创建 BacktestTask 记录（状态为 PENDING），返回 `task_id`，HTTP 响应在 500ms 内返回。
3. When 回测任务被提交到队列，the Celery Worker shall 在独立 Worker 进程中调用 `FreqtradeBridge` 执行 freqtrade 回测子进程，不在 FastAPI 事件循环中执行。
4. While 回测任务正在执行，the Backtest Service shall 将 BacktestTask 状态更新为 RUNNING，并记录任务开始时间。
5. When freqtrade 回测子进程执行成功，the Backtest Service shall 将回测结果（收益率、年化收益率、夏普比率、最大回撤、交易次数、胜率等指标）序列化写入 BacktestTask.result_json，并将状态更新为 DONE。
6. When BacktestTask 状态变为 DONE，the Backtest Service shall 检查策略表中对应指标字段（收益率、年化收益率、夏普比率、最大回撤、交易次数、胜率）是否为 NULL，若为 NULL 则将回测结果更新至策略表对应字段，若字段已有值则跳过该字段不覆盖。
7. If freqtrade 子进程执行失败或返回非零退出码，the Backtest Service shall 将任务状态更新为 FAILED，记录 error_message，并向调用方返回 `code: 5001`，不暴露原始 traceback。
8. The Backtest Service shall 使用串行队列机制调度回测任务：同一时间最多只有 1 个回测任务处于 RUNNING 状态，其余任务在队列中以 PENDING 状态排队等待；Celery Worker 须以 `concurrency=1` 配置启动，确保回测任务串行执行，避免多个回测并发运行导致 API 限额耗尽或系统资源超限。
9. When 管理员重复提交同一策略的回测请求，the Backtest Service shall 将新任务以 PENDING 状态加入队列排队等待，不拒绝该请求，不返回 `code: 3002`。

---

### 需求 2：freqtrade 交易信号生成与持久化

**目标：** 作为平台后台调度程序，我希望 freqtrade 进程持久化运行或通过定时任务定期启动，对不同的币种和策略及时生成交易信号（Buy/Sell/Hold），并将信号以追加方式持久化至数据库时序信号表，以便 API 直接读取最新信号展示给用户，同时完整保留所有历史信号记录，保障信号的及时性、可追溯性和可用性。

#### 验收标准

1. The Signal Fetcher shall 支持 freqtrade 进程持久化运行模式或定时启动模式，确保各策略和币种能及时产生信号，信号生成间隔不超过系统配置的刷新周期（默认 5 分钟）。
2. When 后台定时任务触发信号生成，the Signal Fetcher shall 在 `ProcessPoolExecutor` 独立进程中调用 freqtrade 信号逻辑，不占用 Web 事件循环线程。
3. When 信号生成成功，the Signal Fetcher shall 以 INSERT 方式将信号结果追加写入 `trading_signals` 表，每条记录须包含以下字段：`pair`（交易对，如 BTC/USDT）、`direction`（信号方向 Buy/Sell/Hold）、`confidence_score`（可信度评分）、`entry_price`（建议入场价格）、`stop_loss`（建议止损价格）、`take_profit`（建议止盈价格）、`indicator_values`（策略所用技术指标快照，JSON 格式，如 RSI 值、MACD 值、布林带宽等）、`timeframe`（信号时间周期，如 1h）、`signal_strength`（信号强度，归一化数值）、`volume`（对应 K 线成交量）、`volatility`（波动率指标）；不执行 UPDATE 或 DELETE，不覆盖同一策略和交易对的历史信号记录。
4. The trading_signals 表 shall 作为只增不删的时序数据表，每次信号生成均产生新记录，系统不对任何已存在的信号行执行 UPDATE 或 DELETE 操作（禁止 upsert/覆盖）。
5. When 回测任务（BacktestTask）状态变为 DONE，the Backtest Service shall 将回测过程中产生的交易信号以 INSERT 方式追加写入 `trading_signals` 表，并标记信号来源为 `backtest`，历史回测信号与实时信号共同保留在同一时序表中。
6. The Signal Fetcher shall 支持对多个交易对（如 BTC/USDT、ETH/USDT 等主流币种）并发生成信号，最大并发进程数通过配置项控制，默认不超过 2。
7. If 信号生成过程中 freqtrade 模块调用失败，the Signal Fetcher shall 记录结构化错误日志（含策略名、交易对、错误信息、时间戳），跳过本次信号写入，保留 `trading_signals` 表中上一次有效信号记录，不影响 API 正常响应。
8. When API 请求读取策略信号，the Strategy Service shall 直接从 `trading_signals` 表中按策略和交易对查询最新一条记录（按 `created_at` 降序取第一条），不实时调用 freqtrade，确保信号查询接口响应时间在 200ms 以内。
9. The Signal Fetcher shall 对每次信号生成任务记录结构化日志，包含策略名、交易对、信号类型、信号来源（realtime/backtest）、执行耗时，日志格式遵循 structlog JSON 格式。

---

### 需求 3：freqtrade 配置隔离与环境管理

**目标：** 作为平台系统，我希望每个回测任务拥有独立隔离的 freqtrade 配置目录，信号生成进程拥有独立的运行配置，以便防止多个任务之间的配置文件相互覆盖或污染，同时通过静态策略文件与映射注册机制确保策略的可追溯性，确保 freqtrade 特有的策略代码与主服务代码完全隔离。

#### 验收标准

1. When 回测任务被创建，the Backtest Service shall 在 `/tmp/freqtrade_jobs/{task_id}/` 路径下生成独立的 `config.json`、`strategy/` 策略文件目录和 `results/` 输出目录。
2. The Backtest Service shall 生成的 `config.json` 中不包含任何敏感 API Key 或交易所凭证，所有敏感配置从环境变量注入；`config.json` 的可变参数仅为交易对、时间周期和回测日期范围，策略代码本身不随任务变化。
3. When 回测任务结束（DONE 或 FAILED），the Backtest Service shall 自动清理 `/tmp/freqtrade_jobs/{task_id}/` 临时目录，释放磁盘空间。
4. If 临时目录创建失败（如磁盘空间不足），the Backtest Service shall 拒绝回测任务提交，返回 `code: 5001`，并记录错误日志。
5. The FreqtradeBridge shall 维护一个 `STRATEGY_REGISTRY` 映射字典，建立数据库 `Strategy.id` / `Strategy.name` ↔ freqtrade 策略类名 ↔ 策略文件路径（`src/freqtrade_bridge/strategies/`）的三元对应关系；平台仅支持预置在该注册表中的经典策略（如 SMA Crossover、RSI、MACD、Bollinger Bands 等排名前十的公认大策略），不支持用户或管理员动态提交新策略。
6. When 回测任务被创建，the Backtest Service shall 通过 `STRATEGY_REGISTRY` 查找对应策略文件的静态路径，将该文件以复制或符号链接方式放置到任务临时目录的 `strategy/` 子目录，不从数据库读取策略代码内容，不动态生成策略文件。
7. If 回测请求中指定的策略 ID 或名称在 `STRATEGY_REGISTRY` 中不存在，the Backtest Service shall 拒绝任务提交，返回 `code: 3003`（策略不支持），HTTP 状态码 422。
8. The FreqtradeBridge shall 将 freqtrade 特有的逻辑（策略执行代码、回测参数配置、信号提取逻辑）封装在 `src/freqtrade_bridge/` 模块内，策略文件统一存放于 `src/freqtrade_bridge/strategies/` 目录并随代码仓库一同版本管理，不在主服务代码中直接引用 freqtrade 内部模块。
9. Where 系统部署环境包含多个 Celery Worker 实例，the Backtest Service shall 确保不同 Worker 实例的临时目录路径互不冲突，通过唯一 `task_id` 命名隔离。

---

### 需求 4：回测任务状态查询 API（仅管理员）

**目标：** 作为平台后台运营管理员，我希望能够通过管理员专属接口查询回测任务的当前状态和结果，以便监控回测进度并在完成后获取详细指标数据。

#### 验收标准

1. The Backtest Service shall 提供 `GET /api/v1/admin/backtests/{task_id}` 接口，返回任务状态（PENDING/RUNNING/DONE/FAILED）、创建时间、完成时间及结果摘要；该接口仅管理员可访问，非管理员请求返回 `code: 1002`，HTTP 状态码 403。
2. When 管理员查询 task_id 对应的回测任务，the Backtest Service shall 校验当前登录用户是否具有管理员权限，若不是则返回 `code: 1002`（权限不足）。
3. If 查询的 task_id 不存在，the Backtest Service shall 返回 `code: 3001`（任务不存在），HTTP 状态码 404。
4. The Backtest Service shall 提供 `GET /api/v1/admin/backtests` 列表接口，支持分页（`page`、`page_size`），仅管理员可访问，可按策略名和任务状态筛选。
5. When 回测任务状态为 DONE，the Backtest Service shall 在查询响应中包含完整回测指标（收益率、年化收益率、夏普比率、最大回撤、交易次数、胜率），不做字段裁剪（管理员查看完整数据）。

---

### 需求 5：freqtrade 调用错误处理与监控

**目标：** 作为平台运维人员，我希望 freqtrade 集成层的所有错误都能被统一捕获、分类记录，以便快速定位问题并对调用方返回友好的错误信息。

#### 验收标准

1. The FreqtradeBridge shall 将所有 freqtrade 执行错误封装为 `FreqtradeExecutionError` 或 `FreqtradeTimeoutError`，不向上层泄漏 freqtrade 内部异常类型。
2. When FreqtradeBridge 抛出 `FreqtradeExecutionError`，the Backtest Service shall 捕获后将任务状态更新为 FAILED，并通过统一信封格式返回 `{"code": 5001, "message": "freqtrade 调用失败"}`。
3. If freqtrade 子进程输出 stderr 包含错误信息，the FreqtradeBridge shall 将 stderr 内容写入 BacktestTask.error_message（长度截断至 2000 字符），不在 HTTP 响应中直接输出。
4. The FreqtradeBridge shall 对每次 freqtrade 调用记录结构化日志，包含 task_id、strategy、执行耗时、退出码，日志格式遵循 structlog JSON 格式。
5. While 新的回测任务被提交，the Backtest Service shall 将任务以 PENDING 状态加入 Celery 队列排队等待，由 concurrency=1 的 Worker 串行取出执行；系统不因队列积压而拒绝任务提交，不返回 `code: 3002`，任务始终可入队。

---

### 需求 6：freqtrade 集成层与 Web 层解耦约束

**目标：** 作为平台架构师，我希望 freqtrade 集成层严格遵守分层架构约束，确保 Web 事件循环不被阻塞，系统在高并发场景下保持稳定。

#### 验收标准

1. The FreqtradeBridge shall 不依赖 `src/api/` 层的任何模块（无 `Request`、`Response`、`APIRouter` 引用），保持单向依赖。
2. The Celery Worker shall 作为独立进程运行，与 FastAPI 主进程通过 Redis broker 通信，不共享内存状态。
3. When FastAPI 路由层收到回测请求，the Backtest Service shall 仅执行任务入队操作，不等待 freqtrade 执行结果，立即返回 `task_id`。
4. The FreqtradeBridge shall 所有 CPU 密集型操作（回测子进程、信号生成）均在独立进程中执行，不在 FastAPI 异步事件循环中直接调用同步阻塞函数。
5. Where 系统部署环境包含 Celery Worker，the Celery Worker shall 支持通过环境变量配置 Redis broker 地址，与 FastAPI 主服务使用同一 Redis 实例。

---

### 需求 7：MVP 初始化十大经典策略文件与配置预置

**目标：** 作为平台开发团队，我希望在代码仓库中预置十大公认经典量化策略的 freqtrade IStrategy 实现文件、STRATEGY_REGISTRY 映射字典、默认配置模板及数据库种子数据，以便 MVP 阶段能直接运行端到端回测验证，无需手动创建策略文件或初始化数据库记录。

#### 验收标准

1. The FreqtradeBridge shall 在 `src/freqtrade_bridge/strategies/` 目录下包含以下十个策略文件，每个文件对应一个独立的 freqtrade IStrategy 子类：

   | # | 策略名称 | 类名 | 策略创始人 | 类别 |
   |---|---------|------|-----------|------|
   | 1 | 海龟交易（唐奇安突破趋势跟随） | `TurtleTrading` | Richard Dennis / William Eckhardt | trend_following |
   | 2 | 布林带均值回归 | `BollingerMeanReversion` | John Bollinger | mean_reversion |
   | 3 | RSI 超买超卖均值回归 | `RsiMeanReversion` | J. Welles Wilder | mean_reversion |
   | 4 | MACD 趋势跟随 | `MacdTrend` | Gerald Appel | trend_following |
   | 5 | 一目均衡表趋势策略 | `IchimokuTrend` | Goichi Hosoda | trend_following |
   | 6 | 抛物线转向（SAR）趋势跟随 | `ParabolicSarTrend` | J. Welles Wilder | trend_following |
   | 7 | 凯尔特纳通道突破 | `KeltnerBreakout` | Chester W. Keltner | breakout |
   | 8 | Aroon 趋势识别与跟随 | `AroonTrend` | Tushar Chande | trend_following |
   | 9 | NR7 窄幅波动收缩—突破 | `Nr7Breakout` | Toby Crabel | breakout |
   | 10 | 随机指标反转/背离策略 | `StochasticReversal` | George Lane | mean_reversion |

2. The FreqtradeBridge shall 确保每个策略文件均实现 `populate_indicators`、`populate_entry_trend`、`populate_exit_trend` 三个方法，且每个文件可独立通过 `freqtrade backtesting --strategy <ClassName>` 命令执行而不报错。
3. The FreqtradeBridge shall 在 `src/freqtrade_bridge/strategy_registry.py` 中提供 `STRATEGY_REGISTRY` 映射字典，建立策略名称（数据库 `Strategy.name` 字段）↔ freqtrade 策略类名 ↔ 策略文件路径的三元对应关系，覆盖上述全部十个策略：`TurtleTrading`、`BollingerMeanReversion`、`RsiMeanReversion`、`MacdTrend`、`IchimokuTrend`、`ParabolicSarTrend`、`KeltnerBreakout`、`AroonTrend`、`Nr7Breakout`、`StochasticReversal`。
4. When 系统通过 `STRATEGY_REGISTRY` 查找任意上述十个策略，the FreqtradeBridge shall 能正确解析出对应的策略类名和文件绝对路径，且路径指向的文件实际存在。
5. The FreqtradeBridge shall 在 `src/freqtrade_bridge/config_template.json` 中提供默认的 freqtrade 配置模板，模板中包含 `BTC/USDT`、`ETH/USDT`、`BNB/USDT`、`SOL/USDT` 四个主流数字货币交易对，时间周期默认为 `1h`，回测日期范围参数以占位符形式表示（如 `"timerange": "{{TIMERANGE}}"`），模板中不包含任何真实交易所 API Key 或账户凭证。
6. The FreqtradeBridge shall 提供数据库种子数据脚本或 pytest fixture（位于 `src/freqtrade_bridge/seeds/` 或 `tests/fixtures/`），用于向 `strategies` 表批量插入上述十条策略记录，每条记录包含 `name`、`description`、`category` 字段，且 `name` 字段值与 `STRATEGY_REGISTRY` 键名完全一致。
7. When 种子数据脚本被执行，the FreqtradeBridge shall 以幂等方式写入策略记录（若同名策略记录已存在则跳过插入），不重复创建记录，不破坏已有数据库状态。
8. If 任意一个策略文件在回测时缺少必要的依赖指标或参数配置，the FreqtradeBridge shall 在该文件的 `populate_indicators` 方法中计算并返回所有所需技术指标列，确保回测可完整执行至生成信号阶段而不中途抛出 `KeyError` 或 `AttributeError`。
9. The FreqtradeBridge shall 确保十个策略文件及 `STRATEGY_REGISTRY`、`config_template.json`、种子数据脚本均随代码仓库版本管理（纳入 Git 追踪），不依赖外部下载或运行时动态生成。
