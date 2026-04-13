# 从外部服务调用研报 API 指南

## 线上环境信息

| 项目 | 值 |
|------|-----|
| API 地址 | `http://8.209.238.108` (80 端口，OpenResty 反代至内部 8000) |
| 鉴权方式 | `X-API-Key` Header |
| API Key | 通过服务器 `.env` 文件中的 `INTERNAL_API_KEY` 配置 |

## API 端点

### 管理接口（需鉴权）

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/v1/admin/reports` | 创建研报 |
| `PUT` | `/api/v1/admin/reports/{id}` | 更新研报（部分更新） |
| `DELETE` | `/api/v1/admin/reports/{id}` | 删除研报 |

### 公开接口（无需鉴权）

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/v1/reports?page=1&page_size=20` | 研报列表（不含 content） |
| `GET` | `/api/v1/reports/{id}` | 研报详情（含 content） |

## 鉴权方式

支持两种鉴权，任选其一：

1. **X-API-Key**（推荐，适合服务间调用）：在 Header 中传入 `X-API-Key: {your_key}`
2. **Bearer JWT**（适合前端用户操作）：管理员登录后带 `Authorization: Bearer {token}`

---

## 字段说明

### 创建请求（POST）

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `title` | string | 是 | 研报标题（≤256 字符） |
| `summary` | string | 是 | 摘要，展示在列表页 |
| `content` | string | 是 | Markdown 正文，展示在详情页 |
| `related_coins` | string[] | 否 | 关联币种，如 `["BTC", "ETH"]`，自动转大写 |

`generated_at` 自动设为创建时间（UTC），无需传入。

### 更新请求（PUT）

所有字段均为可选，仅传入需要修改的字段。`related_coins` 传入时会**全量替换**现有关联。

### 响应格式

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "id": 1,
    "title": "研报标题",
    "summary": "摘要",
    "content": "# Markdown 正文",
    "generated_at": "2026-04-11T05:42:36.411819Z",
    "related_coins": ["BTC", "ETH"]
  }
}
```

---

## 调用示例

### cURL

```bash
# 创建研报
curl -X POST http://8.209.238.108/api/v1/admin/reports \
  -H "Content-Type: application/json" \
  -H "X-API-Key: ${INTERNAL_API_KEY}" \
  -d '{
    "title": "海龟交易策略深度解析",
    "summary": "本报告深入分析海龟交易策略在加密市场的表现...",
    "content": "# 海龟交易策略\n\n## 一、策略概述\n...",
    "related_coins": ["BTC", "ETH"]
  }'

# 更新研报
curl -X PUT http://8.209.238.108/api/v1/admin/reports/1 \
  -H "Content-Type: application/json" \
  -H "X-API-Key: ${INTERNAL_API_KEY}" \
  -d '{
    "title": "更新后的标题"
  }'

# 删除研报
curl -X DELETE http://8.209.238.108/api/v1/admin/reports/1 \
  -H "X-API-Key: ${INTERNAL_API_KEY}"

# 查询列表（公开，无需鉴权）
curl http://8.209.238.108/api/v1/reports?page=1&page_size=20

# 查询详情（公开，无需鉴权）
curl http://8.209.238.108/api/v1/reports/1
```

### Python

```python
import requests

API_BASE = "http://8.209.238.108/api/v1"
API_KEY = "your_internal_api_key"  # 从 .env INTERNAL_API_KEY 获取  # pragma: allowlist secret

headers = {
    "X-API-Key": API_KEY,
    "Content-Type": "application/json",
}


def create_report(title: str, summary: str, content: str, coins: list[str] | None = None) -> dict:
    """创建一篇研报。"""
    resp = requests.post(
        f"{API_BASE}/admin/reports",
        headers=headers,
        json={
            "title": title,
            "summary": summary,
            "content": content,
            "related_coins": coins or [],
        },
    )
    resp.raise_for_status()
    return resp.json()["data"]


def update_report(report_id: int, **fields) -> dict:
    """更新研报，仅传入需要修改的字段。"""
    resp = requests.put(
        f"{API_BASE}/admin/reports/{report_id}",
        headers=headers,
        json=fields,
    )
    resp.raise_for_status()
    return resp.json()["data"]


def delete_report(report_id: int) -> dict:
    """删除研报。"""
    resp = requests.delete(
        f"{API_BASE}/admin/reports/{report_id}",
        headers=headers,
    )
    resp.raise_for_status()
    return resp.json()["data"]


def list_reports(page: int = 1, page_size: int = 20) -> dict:
    """查询研报列表（公开接口）。"""
    resp = requests.get(f"{API_BASE}/reports", params={"page": page, "page_size": page_size})
    resp.raise_for_status()
    return resp.json()["data"]


# 使用示例
if __name__ == "__main__":
    # 创建
    report = create_report(
        title="MACD 趋势跟随策略分析",
        summary="深入分析 MACD 指标在加密货币市场的趋势跟随效果",
        content="# MACD 趋势跟随策略\n\n## 一、策略原理\n...",
        coins=["BTC", "ETH"],
    )
    print(f"创建成功: id={report['id']}")

    # 更新
    updated = update_report(report["id"], title="更新后的标题")
    print(f"更新成功: {updated['title']}")

    # 列表
    data = list_reports()
    print(f"共 {data['total']} 篇研报")
```

---

## 错误码

| code | HTTP 状态码 | 说明 |
|------|-----------|------|
| 0 | 200 | 成功 |
| 1001 | 401 | 鉴权失败（API Key 错误或缺失） |
| 1002 | 403 | 权限不足（JWT 模式下非管理员） |
| 3001 | 404 | 研报不存在 |

## 注意事项

- `content` 字段支持 Markdown 格式，前端会渲染为 HTML
- `related_coins` 中的币种符号会自动转为大写存储
- 列表接口 `GET /api/v1/reports` 不返回 `content` 字段（减少传输量），详情接口才返回
- API Key 无过期时间，如需轮换请修改服务器 `.env` 中的 `INTERNAL_API_KEY` 并重启 web 容器
