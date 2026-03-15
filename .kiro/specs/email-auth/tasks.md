# 实施计划

- [x] 1. 安装邮箱校验依赖并创建工具类
  - 在 `pyproject.toml` 中添加 `email-validator` 依赖（`pydantic[email]` 方式引入）
  - 实现邮箱校验工具：主路径调用 `email_validator.validate_email()`，返回归一化邮箱字符串
  - 在模块加载时通过 `try/except ImportError` 检测库可用性，失败时设置降级标志
  - 降级路径使用基础正则 `^[^@]+@[^@]+\.[^@]+$` 执行校验，并通过 structlog 记录 WARNING 日志
  - 校验失败时抛出 `ValueError`，不抛出 HTTP 异常
  - _Requirements: 4.1, 4.2, 4.3, 4.4_

- [x] 2. 更新用户数据模型与 Alembic 迁移脚本
- [x] 2.1 将 User 模型中的 username 字段替换为 email
  - 在 `User` 模型中移除 `username` 字段，新增 `email` 字段（`String(254)`，唯一约束，不可为空）
  - 将模型级唯一索引从 `idx_users_username` 更新为 `idx_users_email`
  - 同时设置 `unique=True` 和数据库层唯一索引双重保障
  - _Requirements: 3.1, 3.3_

- [x] 2.2 编写 Alembic 数据库迁移脚本
  - 创建新的迁移文件，命名遵循 `{seq}_replace_username_with_email_in_users.py` 规范
  - `upgrade()`：删除旧索引 `idx_users_username` 和 `username` 列，新增 `email VARCHAR(254) UNIQUE NOT NULL` 列和 `idx_users_email` 索引
  - `downgrade()`：逆向还原 `username VARCHAR(64) UNIQUE NOT NULL` 列和原索引
  - _Requirements: 3.2_

- [x] 3. 新增业务异常类并更新异常处理映射
  - 在核心异常定义文件中新增 `EmailConflictError`（code=3010，HTTP 409）、`LoginNotFoundError`（code=1004，HTTP 401）和 `AccountDisabledError`（code=1005，HTTP 403）三个异常类
  - 在全局异常处理器的 HTTP 状态码映射表中注册三个新异常类与对应状态码的关联
  - _Requirements: 1.3, 2.2, 2.3, 2.4_

- [x] 4. 更新 Pydantic Schema 以支持邮箱字段
- [x] 4.1 (P) 更新注册请求 Schema
  - 将 `RegisterRequest` 中的 `username` 字段替换为 `email` 字段（`String`，最大长度 254）
  - 通过 `@field_validator` 调用邮箱校验工具，使校验在请求解析阶段自动触发
  - 将 `password` 字段的最低长度从 6 改为 8
  - _Requirements: 1.1, 1.2, 1.6, 1.7, 3.4, 4.3_

- [x] 4.2 (P) 更新登录和响应 Schema
  - 将 `LoginRequest` 中的 `username` 字段替换为 `email` 字段，并添加 `@field_validator` 调用邮箱校验工具
  - 将 `UserRead` 中的 `username` 字段替换为 `email` 字段
  - 依赖任务 1（邮箱校验工具）完成后方可执行；4.1 和 4.2 修改不同 Schema 类，可并行
  - _Requirements: 1.5, 2.1, 3.4_

- [x] 5. 更新认证业务逻辑层
  - 将 `AuthService.register` 中的用户查重逻辑从按 `username` 查询改为按 `email` 查询，重复时抛出 `EmailConflictError`（code=3010）
  - 将 `AuthService.login` 中的用户查询从按 `username` 改为按 `email`，邮箱不存在或密码不匹配时抛出 `LoginNotFoundError`（code=1004），账号禁用时抛出 `AccountDisabledError`（code=1005）
  - 确保登录对邮箱不存在和密码错误返回同一错误码，防止用户枚举
  - `refresh_access_token` 逻辑保持不变，继续使用现有 `AuthenticationError`（code=1001）
  - 依赖任务 2.1（User 模型）和任务 3（新异常类）完成后方可执行
  - _Requirements: 1.3, 1.4, 1.5, 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 5.1, 5.2, 5.3, 5.4, 5.5_

- [x] 6. 更新路由层与 Admin 视图
- [x] 6.1 更新 Auth 路由层
  - 将注册和登录端点的参数从 `username` 切换为 `email`，确保 `POST /api/v1/auth/register`、`POST /api/v1/auth/login`、`POST /api/v1/auth/refresh` 三个端点正常运行
  - 确认所有端点响应使用统一信封格式 `{"code": ..., "message": ..., "data": ...}`
  - 确认任何错误响应中不包含 `hashed_password` 或内部堆栈信息
  - _Requirements: 6.1, 6.2, 6.3, 6.4_

- [x] 6.2 更新 UserAdmin 视图
  - 将 sqladmin `UserAdmin` 的展示列和搜索列从 `username` 替换为 `email`
  - 可与 6.1 并行执行，两者修改不同文件无资源竞争
  - _Requirements: 3.5_

- [x] 7. 编写单元测试
- [x] 7.1 (P) 邮箱校验工具单元测试
  - 测试合法邮箱返回归一化字符串（如小写化处理）
  - 测试缺少 `@`、无效域名等格式返回 `ValueError`
  - 测试 `email_validator` 库不可用时降级为正则并触发 WARNING 日志
  - _Requirements: 4.1, 4.2, 4.4_

- [x] 7.2 (P) Schema 校验单元测试
  - 测试 `RegisterRequest` 在邮箱格式非法时抛出 `ValidationError`
  - 测试 `RegisterRequest` 在密码不足 8 位时抛出 `ValidationError`
  - _Requirements: 1.1, 1.2, 1.6, 1.7_

- [x] 7.3 (P) AuthService 业务逻辑单元测试
  - 测试 `register` 在邮箱重复时抛出 `EmailConflictError`（code=3010）
  - 测试 `register` 成功时返回 `User` 对象且 `membership=free`
  - 测试 `login` 在邮箱不存在时抛出 `LoginNotFoundError`（code=1004）
  - 测试 `login` 在密码错误时抛出 `LoginNotFoundError`（code=1004）
  - 测试 `login` 在 `is_active=false` 时抛出 `AccountDisabledError`（code=1005）
  - 测试 `login` 成功时返回包含 access token 和 refresh token 的元组
  - _Requirements: 1.3, 1.4, 2.1, 2.2, 2.3, 2.4, 2.5, 2.6_

- [x] 8. 编写集成测试
- [x] 8.1 注册接口集成测试
  - 测试合法请求返回 `code:0`，`data` 中包含 `id` 和 `email`，不含密码信息
  - 测试邮箱格式非法返回 `code:2001`，HTTP 422
  - 测试邮箱已注册返回 `code:3010`，HTTP 409
  - 测试密码不足 8 位返回 `code:2001`，HTTP 422
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 6.2, 6.3, 6.4_

- [x] 8.2 登录接口集成测试
  - 测试合法邮箱和密码登录返回 `code:0`，`data` 中包含 `access_token`、`refresh_token` 和 `token_type: "bearer"`
  - 测试邮箱不存在返回 `code:1004`，HTTP 401
  - 测试密码错误返回 `code:1004`，HTTP 401（与邮箱不存在相同响应，防枚举）
  - 测试账号禁用（`is_active=false`）返回 `code:1005`，HTTP 403
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 6.1, 6.2_

- [x] 8.3 Token 刷新接口集成测试
  - 测试有效 refresh token 返回新 `access_token`，不重新签发 refresh token
  - 测试过期或签名无效的 refresh token 返回 `code:1001`，HTTP 401
  - 测试传入 access token 作为 refresh token 时返回 `code:1001`，HTTP 401（type 字段校验）
  - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5_

- [ ]* 8.4 Alembic 迁移脚本往返测试
  - 执行 `alembic upgrade head` 后验证 `users` 表包含 `email` 列和 `idx_users_email` 索引
  - 执行 `alembic downgrade` 后验证表结构还原为 `username` 列和原索引
  - 验证迁移脚本在 CI 环境可独立重复执行
  - _Requirements: 3.2_
