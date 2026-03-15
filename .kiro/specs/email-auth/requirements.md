# 需求文档

## 项目描述（输入）

增加邮箱注册登录功能，放弃原本的用户名登录注册，找一些第三方库来校验邮箱的有效性

## 需求

### 需求 1：邮箱注册

**目标：** 作为新用户，我希望使用邮箱地址和密码完成注册，以便获得平台账号并访问分级会员功能。

#### 验收标准

1. When 用户提交包含邮箱地址和密码的注册请求，the Auth Service shall 使用第三方邮箱校验库（如 `email-validator`）验证邮箱格式的合法性。
2. If 邮箱格式不合法，the Auth Service shall 返回业务错误码 `2001`，并在 `data` 中描述具体的格式错误原因。
3. If 该邮箱地址已被注册，the Auth Service shall 返回业务错误码 `3010`，HTTP 状态码 409，消息为"邮箱已被注册"。
4. When 邮箱格式合法且未被占用，the Auth Service shall 使用 `passlib[bcrypt]` 对密码进行哈希后存入数据库，并将该用户默认会员等级设置为 `free`。
5. The Auth Service shall 在注册成功后返回统一信封响应（`code: 0`），`data` 中包含用户 ID 和邮箱地址，不返回密码哈希或原始密码。
6. The Auth Service shall 对注册密码执行最低强度校验：长度不少于 8 个字符。
7. If 密码长度不满足要求，the Auth Service shall 返回业务错误码 `2001`，并在 `data` 中说明密码规则。

---

### 需求 2：邮箱登录

**目标：** 作为已注册用户，我希望使用邮箱和密码登录，以便获取 JWT 令牌并访问受保护的平台功能。

#### 验收标准

1. When 用户提交邮箱和密码登录请求，the Auth Service shall 通过邮箱在数据库中查找对应用户记录。
2. If 邮箱不存在于数据库，the Auth Service shall 返回业务错误码 `1004`，HTTP 状态码 401，消息为"邮箱或密码错误"（不区分具体原因，防止用户枚举）。
3. If 密码与存储的 bcrypt 哈希不匹配，the Auth Service shall 返回业务错误码 `1004`，HTTP 状态码 401，消息为"邮箱或密码错误"。
4. If 用户账号处于禁用状态（`is_active = false`），the Auth Service shall 返回业务错误码 `1005`，HTTP 状态码 403，消息为"账号已被禁用"。
5. When 邮箱和密码验证通过且账号处于激活状态，the Auth Service shall 签发 access token（有效期 30 分钟）和 refresh token（有效期 7 天），token claims 中包含 `sub`（用户 ID）、`membership`（会员等级）和 `type` 字段。
6. The Auth Service shall 在登录成功响应的 `data` 中同时返回 `access_token`、`refresh_token` 和 `token_type: "bearer"`。

---

### 需求 3：用户数据模型迁移（用户名 → 邮箱）

**目标：** 作为系统，我需要将用户身份标识从用户名字段迁移为邮箱字段，以支持邮箱认证体系并保持数据一致性。

#### 验收标准

1. The Auth Service shall 在用户数据模型中新增 `email` 字段（字符串类型，唯一约束，不可为空），并移除 `username` 字段。
2. The Auth Service shall 在数据库迁移脚本中同时实现 `upgrade()`（添加 `email` 列，删除 `username` 列）和 `downgrade()`（还原操作），符合 Alembic 规范。
3. The Auth Service shall 对 `email` 字段建立唯一索引，以保证查询性能和唯一性约束在数据库层双重生效。
4. The Auth Service shall 更新所有引用 `username` 字段的 Pydantic Schema（`UserCreate`、`UserRead`、`UserUpdate`）以使用 `email` 字段。
5. The Auth Service shall 更新 sqladmin `UserAdmin` 视图，将搜索和展示列从 `username` 替换为 `email`。

---

### 需求 4：邮箱格式校验

**目标：** 作为系统，我需要通过第三方库对邮箱有效性进行可靠校验，以防止无效邮箱地址进入系统。

#### 验收标准

1. The Auth Service shall 使用符合 RFC 5321/5322 标准的第三方邮箱校验库（推荐 `email-validator`）对所有用户提交的邮箱执行格式校验。
2. When 邮箱校验库检测到格式无效（包括缺失 `@`、域名不合法、本地部分违规等），the Auth Service shall 拒绝请求并返回错误码 `2001`。
3. The Auth Service shall 在 Pydantic Schema 层集成邮箱校验逻辑，使校验在请求解析阶段自动触发，无需在业务层重复校验。
4. If 邮箱校验库运行时出现异常（如导入失败），the Auth Service shall 降级为基础正则校验并记录警告日志，不中断服务。

---

### 需求 5：Token 刷新

**目标：** 作为已登录用户，我希望在 access token 过期后使用 refresh token 换取新的 access token，以保持登录状态而无需重新输入密码。

#### 验收标准

1. When 用户携带有效的 refresh token 请求刷新接口，the Auth Service shall 验证该 token 的签名、有效期及 `type` 字段是否为 `"refresh"`。
2. If refresh token 已过期或签名无效，the Auth Service shall 返回业务错误码 `1001`，HTTP 状态码 401，消息为"refresh token 无效或已过期"。
3. If refresh token 中的 `type` 字段不为 `"refresh"`（即传入了 access token），the Auth Service shall 返回业务错误码 `1001`，HTTP 状态码 401，消息为"token 类型错误"。
4. When refresh token 校验通过，the Auth Service shall 签发新的 access token（有效期 30 分钟），`data` 中仅返回新的 `access_token` 和 `token_type: "bearer"`（不重新签发 refresh token）。
5. While refresh token 仍在有效期内，the Auth Service shall 允许无限次刷新 access token，不强制要求重新登录。

---

### 需求 6：API 接口规范合规

**目标：** 作为系统，我需要确保所有认证相关接口遵循平台统一的 API 规范，以保持接口风格一致性。

#### 验收标准

1. The Auth Service shall 将所有认证接口挂载于 `/api/v1/auth/` 路径前缀下，提供 `POST /api/v1/auth/register`、`POST /api/v1/auth/login`、`POST /api/v1/auth/refresh` 三个端点。
2. The Auth Service shall 对所有认证接口的成功和失败响应统一使用平台信封格式 `{"code": ..., "message": ..., "data": ...}`。
3. If 认证接口的请求体 Pydantic 校验失败，the Auth Service shall 通过全局异常处理器将 FastAPI 422 错误转换为 `code: 2001` 的统一信封响应。
4. The Auth Service shall 在任何错误响应中不暴露密码哈希、原始密码或内部堆栈信息。
