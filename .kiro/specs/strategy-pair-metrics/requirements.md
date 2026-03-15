# 需求文档

## 简介

本功能为量化策略科普展示平台的每一个"策略 × 币种 × 周期"组合（简称"策略对"）引入独立的绩效指标记录体系。具体指标包括：累计收益率（`total_return`）、盈利因子（`profit_factor`）、最大回撤、夏普比率和交易次数。这些指标在系统执行回测时初始化写入，并在实盘信号运行期间持续更新，从而使前端和管理后台能够准确呈现每个策略对的历史表现与实时状态。

## 需求

### 需求 1：策略对绩效指标数据模型

**目标：** 作为系统，我希望为每个策略 × 币种 × 周期组合持久化存储绩效指标，以便各模块能够统一读写。

#### 验收标准

1. The Strategy Platform Service shall 为每个策略对（strategy + pair + timeframe）维护唯一一条绩效指标记录，包含字段：`total_return`（累计收益率，百分比浮点数）、`profit_factor`（盈利因子/盈亏比，浮点数）、`max_drawdown`（最大回撤，百分比浮点数）、`sharpe_ratio`（夏普比率，浮点数）、`trade_count`（总交易次数，非负整数）。
2. The Strategy Platform Service shall 在 `strategy_pair_metrics` 表中以 `(strategy_id, pair, timeframe)` 三元组作为唯一约束，防止重复记录。
3. The Strategy Platform Service shall 在每条绩效指标记录中记录 `data_source` 字段（枚举值：`backtest` / `live`），标识当前指标最后一次来源。
4. The Strategy Platform Service shall 在每条绩效指标记录中记录 `last_updated_at` 时间戳（含时区，UTC 存储），反映最近一次指标更新时间。
5. If 某策略对的指标记录尚不存在，the Strategy Platform Service shall 在首次写入时自动创建该记录，而非返回错误。

---

### 需求 2：回测完成后初始化/更新绩效指标

**目标：** 作为系统，我希望在 freqtrade 回测任务完成后，自动将回测结果中的绩效指标写入对应策略对的记录，以便前端展示历史回测表现。

#### 验收标准

1. When 回测任务状态变更为 `DONE`，the Strategy Platform Service shall 从回测结果中提取 `total_return`、`profit_factor`、`max_drawdown`、`sharpe_ratio`、`trade_count` 并写入或更新对应策略对的绩效指标记录。
2. When 回测结果写入绩效指标，the Strategy Platform Service shall 将 `data_source` 设置为 `backtest`，并更新 `last_updated_at` 为当前 UTC 时间。
3. If 回测结果中某项指标字段缺失或为 `null`，the Strategy Platform Service shall 保留数据库中该字段的现有值，不覆盖为 null。
4. If 同一策略对的绩效指标记录已存在（来源为 `live`），the Strategy Platform Service shall 仍使用最新回测数据覆盖全部指标字段，并将 `data_source` 更新为 `backtest`。
5. While 回测结果写入数据库，the Strategy Platform Service shall 在单一数据库事务中完成回测任务状态更新与绩效指标写入，确保两者原子性一致。

---

### 需求 3：实盘信号运行期间持续更新绩效指标

**目标：** 作为系统，我希望在实盘信号生成过程中，将最新的实盘绩效数据增量更新到策略对的绩效指标记录，以便反映真实运行状态。

#### 验收标准

1. When 实盘信号任务完成并产生新的绩效快照，the Strategy Platform Service shall 将最新的 `total_return`、`profit_factor`、`max_drawdown`、`sharpe_ratio`、`trade_count` 更新到对应策略对的绩效指标记录。
2. When 实盘指标更新写入，the Strategy Platform Service shall 将 `data_source` 设置为 `live`，并更新 `last_updated_at` 为当前 UTC 时间。
3. If 对应策略对的绩效指标记录不存在，the Strategy Platform Service shall 自动创建新记录（upsert 语义），避免因记录缺失导致更新失败。
4. While 实盘信号任务运行期间，the Strategy Platform Service shall 保证绩效指标写入操作不阻塞信号生成主流程，写入失败时记录错误日志但不中断信号任务。
5. The Strategy Platform Service shall 支持对同一策略对的绩效指标进行幂等更新：相同时间戳的数据重复写入时，结果与单次写入相同。

---

### 需求 4：策略对绩效指标的 API 查询

**目标：** 作为前端消费方，我希望通过 API 查询特定策略的所有币种周期组合的绩效指标，以便在策略详情页展示各交易对的表现排行。

#### 验收标准

1. When 客户端发起 `GET /api/v1/strategies/{strategy_id}/pair-metrics` 请求，the Strategy Platform Service shall 返回该策略下所有策略对的绩效指标分页列表，字段包含 `pair`、`timeframe`、`total_return`、`profit_factor`、`max_drawdown`、`sharpe_ratio`、`trade_count`、`data_source`、`last_updated_at`。
2. When 匿名用户请求策略对绩效指标，the Strategy Platform Service shall 仅返回 `pair`、`timeframe`、`total_return`、`trade_count` 基础字段，隐藏 `profit_factor`、`sharpe_ratio` 等高级指标。
3. Where 用户会员等级为 VIP1 及以上，the Strategy Platform Service shall 在响应中包含 `max_drawdown` 和 `sharpe_ratio` 字段。
4. If 指定的 `strategy_id` 不存在，the Strategy Platform Service shall 返回 HTTP 404，响应体中 `code` 为 `3001`，`message` 为"策略不存在"。
5. The Strategy Platform Service shall 按 `total_return` 降序返回策略对列表，支持 `?pair=BTC/USDT`、`?timeframe=1h`、`?page=1`、`?page_size=20` 查询参数进行过滤和分页（默认 page=1, page_size=20, 最大 page_size=100）。
6. When 客户端发起 `GET /api/v1/strategies/{strategy_id}/pair-metrics/{pair}/{timeframe}` 请求，the Strategy Platform Service shall 返回单个策略对的完整绩效指标详情（权限规则同上）。

---

### 需求 5：管理后台对绩效指标的可见性

**目标：** 作为运营管理员，我希望在 sqladmin 后台查看和管理每个策略对的绩效指标，以便监控平台整体运行质量。

#### 验收标准

1. The Strategy Platform Service shall 在 sqladmin 后台注册 `StrategyPairMetricsAdmin` ModelView，展示字段包括 `strategy_id`、`pair`、`timeframe`、`total_return`、`profit_factor`、`max_drawdown`、`sharpe_ratio`、`trade_count`、`data_source`、`last_updated_at`。
2. The Strategy Platform Service shall 在 sqladmin 中支持按 `strategy_id`、`pair`、`timeframe`、`data_source` 筛选绩效指标记录。
3. The Strategy Platform Service shall 在 sqladmin 中支持按 `last_updated_at` 和 `total_return` 排序绩效指标记录。
4. Where sqladmin 后台启用，the Strategy Platform Service shall 禁止通过后台直接删除绩效指标记录（`can_delete = False`），保护历史数据完整性。
5. The Strategy Platform Service shall 允许管理员通过 sqladmin 手动编辑单条绩效指标记录的所有指标字段，以便修正异常数据。

---

### 需求 6：数据一致性与错误处理

**目标：** 作为系统，我希望在指标写入发生异常时进行妥善处理，以便不影响平台其他功能的稳定运行。

#### 验收标准

1. If 绩效指标写入数据库时发生数据库连接错误，the Strategy Platform Service shall 重试最多 3 次（指数退避），重试均失败后记录结构化错误日志（含 `strategy_id`、`pair`、`timeframe`、`error_message`）。
2. If `total_return`、`profit_factor`、`max_drawdown` 或 `sharpe_ratio` 接收到超出合理范围的异常值（如 `±10000` 以外），the Strategy Platform Service shall 拒绝写入并记录警告日志，保留原有值不变。
3. If `trade_count` 接收到负数，the Strategy Platform Service shall 拒绝写入并记录校验错误日志。
4. While 并发写入同一策略对绩效指标时，the Strategy Platform Service shall 通过数据库级别的 upsert（ON CONFLICT DO UPDATE）保证最终一致性，不产生重复记录。
5. The Strategy Platform Service shall 通过结构化日志（structlog）记录每次指标更新操作，字段包含 `strategy_id`、`pair`、`timeframe`、`data_source`、`trade_count`，日志级别为 `INFO`。
