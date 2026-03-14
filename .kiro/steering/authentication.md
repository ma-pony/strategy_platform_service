# Authentication & Authorization

平台使用 JWT 无状态鉴权，区分匿名、普通用户与多等级 VIP 会员，鉴权逻辑集中在 `src/core/` 层。

## Authentication Flow

```
1) POST /api/v1/auth/login  {username, password}
2) 服务端验证密码（bcrypt），签发 access_token（短期）+ refresh_token（长期）
3) 客户端每次请求携带 Authorization: Bearer {access_token}
4) FastAPI Depends 注入 get_current_user，校验 token 后返回 User 对象
5) 业务逻辑通过 User 对象判断权限和会员等级
```

## JWT Token Structure

Access token claims（`python-jose` 或 `PyJWT` 签发）：

```json
{
  "sub": "user_id_here",
  "membership": "vip2",
  "exp": 1712000000,
  "iat": 1711996400,
  "type": "access"
}
```

- `sub`: 用户 ID（字符串）
- `membership`: 会员等级，枚举值（见下方）
- `type`: `"access"` 或 `"refresh"`，防止 refresh token 被用于接口调用
- Access token 有效期建议 30 分钟，Refresh token 7 天

## Membership Tiers

会员等级定义为枚举，存储于 User 模型和 JWT claims：

```python
# src/core/enums.py
from enum import Enum

class MembershipTier(str, Enum):
    FREE = "free"       # 免费用户：有限策略数量，有限回测周期
    VIP1 = "vip1"       # VIP1：更多策略，更长回测
    VIP2 = "vip2"       # VIP2：最高配额，优先任务队列
```

权限检查通过 FastAPI `Depends` 实现，不在业务逻辑中散落：

```python
# src/core/deps.py
from fastapi import Depends, HTTPException, status
from src.core.enums import MembershipTier
from src.core.security import decode_token

def require_membership(min_tier: MembershipTier):
    """工厂函数，返回 Depends 可用的校验函数。"""
    def checker(current_user: User = Depends(get_current_user)) -> User:
        tier_order = [MembershipTier.FREE, MembershipTier.VIP1, MembershipTier.VIP2]
        if tier_order.index(current_user.membership) < tier_order.index(min_tier):
            raise HTTPException(status_code=403, detail={"code": 1003, "message": "会员等级不足"})
        return current_user
    return checker

# 路由用法：
# @router.post("/backtests/long-range")
# async def create_long_backtest(user: User = Depends(require_membership(MembershipTier.VIP1))):
```

## Security Patterns

- 密码使用 `passlib[bcrypt]` 哈希，禁止明文存储或日志输出
- Token 签名使用 HS256（对称）或 RS256（非对称，多服务场景），密钥从环境变量注入（`SECRET_KEY`）
- 未认证请求在路由层拦截，返回统一信封 `{"code": 1001, "message": "未登录"}`
- 权限不足返回 `{"code": 1002, "message": "权限不足"}` 或 `{"code": 1003, "message": "会员等级不足"}`

## get_current_user Pattern

```python
# src/core/deps.py
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from src.models.user import User

bearer_scheme = HTTPBearer()

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    token = credentials.credentials
    payload = decode_token(token)           # 校验签名和过期，失败抛 HTTPException
    user = await db.get(User, payload["sub"])
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail={"code": 1001, "message": "用户不存在或已禁用"})
    return user
```

## sqladmin Authentication

sqladmin 后台必须单独设置认证，与用户 JWT 体系隔离，使用 `AuthenticationBackend` 实现独立的管理员会话：

```python
# src/admin/auth.py
from sqladmin.authentication import AuthenticationBackend
# 实现 authenticate / logout，使用独立的管理员账号（不共用普通用户表）
```

---
_No secrets or credentials in steering. Focus on patterns and decisions._
