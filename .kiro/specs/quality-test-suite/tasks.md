# 实现计划

- [x] 1. 建立共享测试基础设施（SharedConftest）
- [x] 1.1 在根级 conftest 中实现全局无状态 fixtures
  - 实现环境变量注入 fixture，通过 monkeypatch 注入 SECRET_KEY、DATABASE_URL、REDIS_URL 测试值，退出时清除 settings lru_cache
  - 实现应用工厂 fixture，每次测试函数作用域调用 create_app() 返回隔离的 FastAPI 实例
  - 实现异步 HTTP 客户端 fixture，通过 ASGITransport 绑定 httpx.AsyncClient，使用 async with 确保连接正确关闭
  - 实现令牌工厂 fixture，封装 SecurityUtils 按 MembershipTier 枚举（匿名、Free、VIP1、VIP2）签发有效 JWT，固定 user_id 映射
  - 实现 mock DB fixture，返回预配置 AsyncMock async session，并作为 app.dependency_overrides[get_db] 的覆盖项
  - 所有 fixture 遵循不依赖全局状态原则，确保现有 454 个测试全部继续通过
  - _Requirements: 8.2, 8.3, 8.4_

- [x] 2. 建立真实数据库集成测试 fixtures（RealDBFixture）
- [x] 2.1 在集成测试目录 conftest 中实现真实 PostgreSQL 测试 fixtures
  - 实现 session 作用域真实 DB 引擎 fixture，读取 TEST_DATABASE_URL 环境变量；连接不可达时调用 pytest.skip() 跳过整个 session 并输出明确原因
  - 实现 session 作用域 Alembic 初始化 fixture，在真实 DB 引擎就绪后执行 alembic upgrade head 建表，session teardown 时执行 alembic downgrade base
  - 实现 function 作用域真实 DB 会话 fixture，每个测试函数分配独立 async session，测试后 TRUNCATE users、strategies、backtest_tasks、backtest_results、trading_signals、reports 表
  - 注册 pytest.mark.integration_db 自定义标记，非 DB 测试不依赖此 fixture
  - _Requirements: 8.1, 8.5_

- [x] 3. 补充认证鉴权集成测试（缺失用例）
- [x] 3.1 向认证 API 测试文件追加缺失的认证边界测试用例
  - 追加 Free 用户携带合法 token 调用 VIP1 专属接口，验证响应 HTTP 403 + code:1003
  - 追加使用 refresh_token 调用刷新端点，验证系统签发新 access_token 且响应 code:0
  - 追加使用 type 为 refresh 的令牌调用普通业务接口，验证响应 HTTP 401 + code:1001
  - 复用任务 1 中的令牌工厂和异步客户端 fixtures，不再各自重复定义
  - _Requirements: 1.6, 1.7, 1.8_

- [x] 4. 补充策略展示集成测试（缺失用例）
- [x] 4.1 向策略 API 测试文件追加 page_size 超限验证用例
  - 追加请求 page_size=200 的策略列表，验证响应 HTTP 422 + code:2001，行为为返回错误而非截断
  - 复用共享异步客户端 fixture
  - _Requirements: 2.5_

- [x] 5. 新建管理员回测接口集成测试
- [x] 5.1 (P) 在管理员回测 API 测试文件中新增权限与状态测试用例
  - 实现管理员提交回测成功场景，mock submit_backtest 返回 PENDING 状态任务，验证 HTTP 202 + 响应体包含 task_id 和 status:PENDING
  - 实现匿名用户提交回测场景，无 Authorization header 调用提交接口，验证 HTTP 401 + code:1001
  - 实现重复提交 RUNNING 任务冲突场景，mock submit_backtest 抛出 ConflictError，验证 HTTP 409 + code:3002
  - 实现策略不存在场景，mock submit_backtest 抛出 NotFoundError，验证 HTTP 404 + code:3001
  - 实现 Free 用户超配额场景，mock 配额超限异常，验证返回对应配额错误码
  - 实现 RUNNING 状态查询场景，mock 任务状态为 RUNNING，验证查询响应不含结果数据
  - 全程使用 mock DB，不依赖真实 DB，与任务 6、7、8 无资源竞争可并行执行
  - _Requirements: 3.1, 3.2, 3.5, 3.6, 3.7_

- [x] 6. 新建参数校验与错误响应集成测试
- [x] 6.1 (P) 新建参数校验集成测试文件，覆盖全局异常处理器转换行为
  - 实现缺少必填字段场景，登录接口省略 password 字段，验证 HTTP 422 + code:2001 + data 包含字段级校验详情（非空列表）
  - 实现类型错误字段场景，登录接口 password 传入整型，验证 HTTP 422 + code:2001
  - 实现 RequestValidationError 信封转换验证，确认响应体格式为统一信封（code/message/data 三字段），而非 FastAPI 默认 422 格式
  - 实现路径参数非数字场景，请求策略详情传入字母路径参数，验证 HTTP 422 + code:2001，而非 HTTP 500
  - 实现错误响应信封格式验证，构造 401、403、404 响应，断言均含 code、message、data 三字段且不含 Python traceback 信息
  - 全程使用 mock DB，与任务 5、7、8 独立可并行执行
  - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5_

- [x] 7. 新建交易信号集成测试
- [x] 7.1 (P) 新建交易信号 API 测试文件，覆盖信号读取与权限控制场景
  - 实现信号接口基础可用性测试，mock 信号数据后调用信号列表接口和策略信号子接口，验证 HTTP 200 + code:0
  - 实现匿名用户字段裁剪验证，匿名请求信号接口，验证响应不含 confidence_score 等高级字段
  - 实现 VIP 用户字段完整性验证，VIP token 请求信号接口，验证响应包含 confidence_score
  - 实现空缓存保护验证，mock 信号查询返回空结果，验证响应为空列表加 code:0 而非 HTTP 500
  - 使用共享令牌工厂和 mock DB，与其他新建测试文件无资源竞争可并行执行
  - _Requirements: 4.1, 4.2, 4.3, 4.4_

- [x] 7.2 (P) 在信号测试文件中添加性能测试占位用例
  - 添加信号 P95 响应时间测试函数，标记为 skip 并注明延后原因
  - _Requirements: 4.5_

- [x] 8. 新建 AI 研报集成测试
- [x] 8.1 (P) 新建研报 API 测试文件，覆盖匿名访问与分页场景
  - 实现匿名列表访问测试，无 Authorization header 调用研报列表接口，验证 HTTP 200 + code:0
  - 实现匿名详情访问测试，调用研报详情接口，验证返回完整内容且不要求登录
  - 实现研报不存在场景，请求不存在的研报 ID，验证 HTTP 404 + 业务错误码而非 HTTP 500
  - 实现分页结构验证，断言响应 data 包含 items、total、page、page_size 四个字段
  - 实现信封格式验证，断言响应 code、message、data 三字段齐全
  - 全程 mock DB，与任务 7 独立可并行执行
  - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5_

- [x] 9. 补充 freqtrade 单元测试与隔离集成测试
- [x] 9.1 (P) 向现有 freqtrade bridge 单元测试文件追加边界覆盖用例
  - 追加超时场景，mock subprocess.run 抛出 TimeoutExpired，验证任务状态更新为 FAILED + code:5001 且主进程不阻塞
  - 追加非零退出码场景，mock subprocess.run 返回非零 returncode，验证捕获为业务错误且响应不含原始 stderr 内容
  - 追加临时目录清理验证，mock 或断言文件系统调用，验证任务结束后工作目录被正确清理
  - 追加路径隔离验证，为两个不同 user_id 生成配置路径，断言路径不重叠
  - 本任务仅操作单元测试目录下已有文件，与任务 9.2 操作不同目录可并行执行
  - _Requirements: 7.1, 7.2, 7.3, 7.5_

- [x] 9.2 (P) 新建 freqtrade 隔离集成测试文件，验证服务降级隔离
  - 实现策略接口可用性降级验证，patch Celery worker inspect 返回 None 模拟 Worker 不可用，调用策略列表接口，断言 HTTP 200 + code:0
  - 实现研报接口可用性降级验证，同上配置，调用研报列表接口，断言 HTTP 200
  - 本任务新建独立文件，与任务 9.1 操作不同目录可并行执行
  - _Requirements: 7.4_

- [x] 10. 新建真实数据库持久化集成测试
- [x] 10.1 新建真实 DB 持久化测试文件，验证 ORM 写入与查询一致性
  - 标记 @pytest.mark.integration_db，依赖任务 2 提供的真实 DB 会话 fixture（须在任务 2 完成后方可运行，不可与任务 2 并行）
  - 实现回测结果持久化验证，通过真实 async session 插入 BacktestTask 和 BacktestResult ORM 对象（含六项核心指标：total_return、annual_return、sharpe_ratio、max_drawdown、trade_count、win_rate），commit 后重新查询，断言各指标值与写入值一致
  - 实现用户会员等级持久化验证，插入 User 对象后查询，验证 membership 字段正确持久化
  - _Requirements: 3.8, 8.1_

- [x] 11. 配置 CI 基础设施与 Makefile 支持
- [x] 11.1 确认并完善全量测试执行配置
  - 确认 Makefile 的 test target 包含 pytest 调用并配置 --tb=short，确保未预期异常输出紧凑诊断信息
  - 验证 pyproject.toml 中 asyncio_mode=auto 和 integration_db 自定义 mark 注册正确
  - 确认测试目录结构 tests/unit/ 对应单元测试、tests/integration/ 对应集成测试，层级与 src/ 一致
  - 验证全量测试（不含 integration_db 标记的 DB 依赖测试）可在 5 分钟内完成
  - _Requirements: 8.6, 8.7, 8.8_

- [x] 12. 补全策略展示接口测试的字段级权限与分页覆盖
- [x] 12.1 向策略 API 测试文件追加字段可见性与分页边界用例
  - 验证匿名用户策略列表响应仅含基础字段，不含夏普比率、胜率、可信度评分等高级指标
  - 验证 Free 用户策略详情响应包含中级指标字段且不含 VIP 专属字段
  - 验证 VIP1/VIP2 用户策略详情响应包含所有高级指标字段
  - 验证策略列表接口不传分页参数时默认返回第 1 页每页 20 条，且响应包含 items、total、page、page_size 字段
  - 验证请求不存在的策略 ID 时响应 HTTP 404 + code:3001
  - 验证所有策略接口响应符合统一 JSON 信封格式
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.6, 2.7_

- [x] 13. 补全回测任务接口状态流转与认证测试覆盖
- [x] 13.1 向回测相关测试文件追加状态流转与认证边界用例
  - 验证 DONE 状态回测任务响应包含六项核心指标（total_return、annual_return、sharpe_ratio、max_drawdown、trade_count、win_rate）
  - 验证认证成功场景：有效 access_token 调用受保护接口正常返回数据不触发 401
  - 验证认证失败场景：过期或签名无效的 access_token 返回 HTTP 401 + code:1001
  - 验证未携带认证头部调用受保护接口时系统拒绝请求并返回 code:1001
  - 验证正确凭证登录响应包含有效 access_token 和 refresh_token 且 HTTP 200 + code:0
  - 验证错误密码登录响应返回 code:1001 且响应体不含令牌字段
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 3.3, 3.4_
