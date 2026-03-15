# 实施计划

- [x] 1. 数据模型与数据库迁移
- [x] 1.1 在核心枚举层新增 DataSource 枚举
  - 在现有枚举文件中添加 `DataSource`（`backtest` / `live`），与 `MembershipTier`、`TaskStatus` 等枚举保持命名风格一致
  - 枚举值为字符串类型，便于 SQLAlchemy Enum 列和 Pydantic Schema 直接引用
  - _Requirements: 1.3_

- [x] 1.2 创建 StrategyPairMetrics ORM 模型
  - 在数据模型层新建策略对绩效指标模型，表名 `strategy_pair_metrics`
  - 字段包含：`id`（主键）、`strategy_id`（外键，ON DELETE CASCADE）、`pair`（VARCHAR 32）、`timeframe`（VARCHAR 16）、`total_return`、`profit_factor`、`max_drawdown`、`sharpe_ratio`（均为可空浮点）、`trade_count`（可空非负整数）、`data_source`（枚举，NOT NULL）、`last_updated_at`（TIMESTAMPTZ，由写入方显式传入）、`created_at`（服务端默认 now()）
  - 声明 `(strategy_id, pair, timeframe)` 唯一约束，命名 `uq_spm_strategy_pair_tf`
  - 声明三个索引：`idx_spm_strategy_id`、`idx_spm_strategy_pair_tf`、`idx_spm_last_updated_at`
  - `last_updated_at` 不使用 `onupdate`，由调用方显式控制以支持幂等判断
  - _Requirements: 1.1, 1.2, 1.3, 1.4_

- [x] 1.3 编写 Alembic 数据库迁移文件
  - 新建迁移文件，在 `upgrade()` 中先创建 `datasource` ENUM 类型，再创建 `strategy_pair_metrics` 表及全部约束和索引
  - 在 `downgrade()` 中按相反顺序删除表和枚举类型
  - 迁移文件命名遵循 `{seq}_add_strategy_pair_metrics.py` 规范
  - 验证迁移可反复执行 `upgrade head` / `downgrade base` 不报错
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5_

- [x] 2. 指标校验与核心 upsert 工具
- [x] 2.1 实现指标值域校验工具
  - 实现纯函数 `validate_metrics`，接收五个指标参数（均可为 None）
  - 浮点类指标（`total_return`、`profit_factor`、`max_drawdown`、`sharpe_ratio`）须在 `[-10000, 10000]` 范围内，否则抛出 `ValueError`，含字段名和实际值信息
  - `trade_count` 若为负数则抛出 `ValueError`，None 值直接通过
  - 无副作用，不依赖数据库，可独立测试
  - _Requirements: 6.2, 6.3_

- [x] 2.2 实现策略对绩效指标 upsert 核心函数
  - 实现 `upsert_pair_metrics` 函数，使用 PostgreSQL `INSERT ... ON CONFLICT(strategy_id, pair, timeframe) DO UPDATE SET ...` 语句
  - 回测来源（`DataSource.BACKTEST`）：无条件覆盖所有非 None 指标字段；None 字段使用 `COALESCE(excluded.field, existing.field)` 保留现有值
  - 实盘来源（`DataSource.LIVE`）：统一使用 `COALESCE` 避免覆盖已有高质量字段
  - upsert 条件加 `WHERE last_updated_at < excluded.last_updated_at`，防止旧数据覆盖新数据（幂等保障）
  - 函数不执行 `session.commit()`，由调用方统一控制事务边界
  - 成功后通过 structlog 记录 INFO 日志，字段含 `strategy_id`、`pair`、`timeframe`、`data_source`、`trade_count`
  - 数据库连接异常时指数退避重试最多 3 次（等待间隔 1s、2s、4s），耗尽后记录结构化 ERROR 日志并向上抛出
  - 调用前须先通过 `validate_metrics` 校验；校验失败时记录 WARNING 日志并保留原有值，不调用 upsert
  - _Requirements: 1.5, 2.2, 2.3, 2.4, 3.2, 3.3, 3.5, 6.1, 6.4, 6.5_

- [x] 3. (P) 回测 Worker 指标原子写入
  - 在回测任务状态变更为 DONE 的处理逻辑中，提取 `total_return`（映射自 `profit_total`）、`profit_factor`、`max_drawdown`、`sharpe_ratio`、`trade_count`，在 `session.commit()` 前调用 `upsert_pair_metrics`
  - 指标 upsert 与 `BacktestResult` 写入在同一事务内，保证原子性
  - 将 `data_source` 设置为 `DataSource.BACKTEST`，`last_updated_at` 设置为当前 UTC 时间
  - 若某字段在回测结果中为 null，不覆盖现有值（由 upsert 的 COALESCE 逻辑保证）
  - 即使目标策略对已有 `live` 来源记录，也使用最新回测数据全量覆盖，`data_source` 更新为 `backtest`
  - 注意：此任务依赖任务 2 的 `upsert_pair_metrics` 实现，与任务 4 无共享文件冲突，可并行执行
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5_

- [x] 4. (P) 实盘信号 Worker 指标非阻塞更新
- [x] 4.1 实现实盘滚动指标计算逻辑
  - 实现 `compute_live_metrics` 函数，从 `trading_signals` 历史表查询指定策略对最近 200 条信号记录（按 `signal_at` 降序）
  - 计算五个估算指标：`trade_count`（非 hold 方向信号数）、`total_return`（buy 方向信号置信度加权简化估算）、`profit_factor`（buy 信号置信度总和 / sell 信号置信度总和）、`sharpe_ratio`（置信度序列均值/标准差近似）、`max_drawdown`（累计方向序列最大连续负序列归一化估算）
  - 历史数据不足 5 条时所有指标返回 None
  - 注意：实盘指标为估算值，非精确交易绩效，仅供科普展示参考
  - 注意：此子任务依赖任务 2 完成，与任务 3 无共享文件冲突，可并行执行
  - _Requirements: 3.1_

- [x] 4.2 实现非阻塞实盘指标更新封装
  - 实现 `try_upsert_live_metrics` 函数，在 `_persist_signals_to_db()` 完成后调用
  - 使用独立的 `SyncSessionLocal()` session，避免污染信号写入事务
  - 全部逻辑包裹在 `try/except Exception`，失败时记录 structlog ERROR（含 `strategy_id`、`pair`、`timeframe`、`error_message`），不向上抛出，保证不阻塞信号生成主流程
  - 成功时自行 `session.commit()`，将 `data_source` 设置为 `DataSource.LIVE`
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_

- [x] 5. (P) 策略对绩效指标 API 层
- [x] 5.1 实现 PairMetricsRead 响应 Schema
  - 创建 Pydantic v2 响应 Schema，配置 `from_attributes = True` 支持 ORM 对象直接转换
  - 复用现有 `TIER_ORDER`、`_tier_index`、`filter_by_tier` 的 `@model_serializer(mode="wrap")` 模式实现字段级权限过滤
  - 匿名可见字段：`pair`、`timeframe`、`total_return`、`trade_count`
  - Free 可见字段（`min_tier="free"`）：`profit_factor`、`data_source`
  - VIP1 可见字段（`min_tier="vip1"`）：`max_drawdown`、`sharpe_ratio`、`last_updated_at`
  - _Requirements: 4.1, 4.2, 4.3_

- [x] 5.2 实现 PairMetricsService 查询服务
  - 实现异步服务类，提供 `list_pair_metrics` 和 `get_pair_metric` 两个方法
  - 查询前先验证 `strategy_id` 对应策略存在，不存在时抛出 `NotFoundError(code=3001)`
  - `list_pair_metrics` 按 `total_return DESC NULLS LAST` 排序，支持 `pair`、`timeframe` 过滤参数，实现 `LIMIT/OFFSET` 分页（默认 page=1, page_size=20，最大 100），同时执行 COUNT 查询返回总记录数
  - `get_pair_metric` 按 `(strategy_id, pair, timeframe)` 三元组查询单条记录，不存在时抛出 `NotFoundError`
  - 不含任何写入逻辑，严格只读
  - _Requirements: 4.4, 4.5, 4.6_

- [x] 5.3 实现 PairMetricsRouter 路由层
  - 在 API 层新建路由文件，声明两个端点：
    - `GET /api/v1/strategies/{strategy_id}/pair-metrics`：接收 `?pair`、`?timeframe`、`?page`、`?page_size` 查询参数，返回 `ApiResponse[PaginatedData[PairMetricsRead]]`
    - `GET /api/v1/strategies/{strategy_id}/pair-metrics/{pair}/{timeframe}`：`pair` 路径参数中 `/` 需 URL 编码为 `%2F`，返回 `ApiResponse[PairMetricsRead]`
  - 认证使用 `Depends(get_optional_user)`，匿名时 `membership=None`
  - 通过 `PairMetricsRead.model_dump(context={"membership": membership})` 序列化响应，实现字段级权限过滤
  - 在 `main_router.py` 的路由注册函数中追加注册此路由器（`prefix="/strategies"`）
  - _Requirements: 4.1, 4.4, 4.5, 4.6_

- [x] 6. (P) sqladmin 管理视图
  - 在 admin 视图文件末尾新增 `StrategyPairMetricsAdmin` ModelView 类
  - 列表展示字段：`strategy_id`、`pair`、`timeframe`、`total_return`、`profit_factor`、`max_drawdown`、`sharpe_ratio`、`trade_count`、`data_source`、`last_updated_at`
  - 搜索和筛选：`column_searchable_list` 含 `pair`、`timeframe`、`data_source`；`column_filters` 含 `strategy_id`、`pair`、`timeframe`、`data_source`
  - 排序：`column_sortable_list` 含 `last_updated_at`、`total_return`
  - 权限配置：`can_delete = False`（禁止删除）、`can_create = False`（由 Worker 创建）、`can_edit = True`（允许手动修正）、`can_view_details = True`
  - 编辑表单字段：`form_columns` 含全部指标字段及 `data_source`、`last_updated_at`
  - 在 `setup_admin()` 中追加 `admin.add_view(StrategyPairMetricsAdmin)` 注册视图
  - 注意：此任务依赖任务 1 的模型，与任务 3/4/5 无共享文件冲突，可并行执行
  - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5_

- [x] 7. 测试覆盖
- [x] 7.1 MetricsValidator 单元测试
  - 测试浮点指标边界值：`±10000` 临界值（应通过）、超出范围（应抛出）
  - 测试 `trade_count` 负数拒绝、零通过、正数通过
  - 测试所有字段均为 None 时通过（不写入场景）
  - _Requirements: 6.2, 6.3_

- [x] 7.2 (P) upsert 核心逻辑单元测试
  - 使用 mock session 验证 COALESCE 语义：None 字段不覆盖现有值
  - 验证 `last_updated_at` 时序保护：旧时间戳不覆盖新时间戳
  - 验证回测来源无条件覆盖非 None 字段
  - 验证重试逻辑：模拟 DB 连接错误，确认指数退避 3 次后向上抛出
  - 验证 structlog INFO 日志在成功 upsert 后被调用
  - _Requirements: 2.3, 2.4, 3.5, 6.1, 6.5_

- [x] 7.3 (P) 实盘指标计算单元测试
  - 测试空历史（0 条）：所有指标返回 None
  - 测试不足 5 条：所有指标返回 None
  - 测试正常数据集（≥5 条）：验证各指标计算结果在合理范围
  - 测试 `try_upsert_live_metrics`：模拟 `compute_live_metrics` 抛出异常，确认不向上传播
  - _Requirements: 3.1, 3.4_

- [x] 7.4 (P) PairMetricsRead Schema 单元测试
  - 测试匿名用户（membership=None）：仅返回 `pair`、`timeframe`、`total_return`、`trade_count`
  - 测试 Free 用户：额外返回 `profit_factor`、`data_source`
  - 测试 VIP1 及以上：返回全部字段含 `max_drawdown`、`sharpe_ratio`、`last_updated_at`
  - _Requirements: 4.2, 4.3_

- [x] 7.5 集成测试：回测 Worker 写入链路
  - 使用真实测试数据库，验证回测任务状态变更为 DONE 后 `strategy_pair_metrics` 记录被创建，`data_source=backtest`
  - 验证同一策略对重复回测后 upsert 幂等：记录数不增加，指标被更新
  - 验证 `BacktestResult` 写入与指标写入的原子性：模拟 upsert 异常时两者均回滚
  - _Requirements: 2.1, 2.2, 2.5_

- [x] 7.6 (P) 集成测试：实盘信号 Worker 写入链路
  - 验证信号任务完成后 `strategy_pair_metrics` 记录创建/更新，`data_source=live`
  - 验证写入失败（mock DB 错误）时信号任务主流程不中断
  - _Requirements: 3.1, 3.2, 3.4_

- [x] 7.7 (P) 集成测试：API 查询端点
  - 使用真实测试数据库，测试 `GET /api/v1/strategies/{strategy_id}/pair-metrics`：
    - 匿名请求：高级字段隐藏，基础字段可见
    - VIP1 请求：全量字段返回
    - `?pair=BTC%2FUSDT&timeframe=1h` 过滤有效
    - 分页参数 `?page=2&page_size=5` 返回正确子集，total 字段准确
    - 结果按 `total_return` 降序排列
  - 测试 `GET /api/v1/strategies/{strategy_id}/pair-metrics/{pair}/{timeframe}`：
    - 策略 ID 不存在返回 HTTP 404，`code=3001`
    - 记录不存在返回 HTTP 404，`code=3001`
  - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6_

- [ ]* 7.8 并发 upsert 一致性测试
  - 使用真实数据库，多线程并发写入同一策略对绩效指标，验证不产生重复记录（ON CONFLICT 行级锁保证）
  - 验证并发 20 个写入操作完成后记录数仍为 1
  - _Requirements: 6.4_
