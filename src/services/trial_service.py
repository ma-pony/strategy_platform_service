"""体验期（Trial）服务 — 基于 Redis 存储。

KEY: trial:{visitor_id}
VALUE: JSON { visitor_id, created_at, expires_at, ip }
TTL: 259200s（3 天）

反滥用：同一 IP 24h 内最多创建 5 个 trial，超出时拒绝创建。
原子性：使用 SET NX 保证幂等，避免并发竞争。
"""

import json
import time
from datetime import datetime, timezone

import redis as redis_lib

TRIAL_TTL = 259200  # 3 天（秒）
IP_WINDOW = 86400  # 24h（秒）
IP_MAX = 5  # 同 IP 最多 5 个 trial


def _trial_key(visitor_id: str) -> str:
    return f"trial:{visitor_id}"


def _ip_key(ip: str) -> str:
    return f"trial_ip:{ip}"


def _ts_to_iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def init_trial(redis: redis_lib.Redis, visitor_id: str, ip: str) -> dict:
    """幂等创建 trial。已存在则直接返回现有状态，不重置计时。

    使用 SET NX 保证原子性，避免并发竞争。
    同一 IP 24h 内超过 IP_MAX 个 trial 时拒绝创建，返回 None。
    """
    key = _trial_key(visitor_id)
    existing = redis.get(key)
    if existing:
        data = json.loads(existing)
        data["created_at"] = _ts_to_iso(data["created_at"])
        data["expires_at"] = _ts_to_iso(data["expires_at"])
        return data

    # 反滥用：检查同 IP 24h 内创建数量
    ip_key = _ip_key(ip)
    ip_count = redis.get(ip_key)
    if ip_count and int(ip_count) >= IP_MAX:
        return {"error": "rate_limited", "visitor_id": visitor_id}

    now = time.time()
    data = {
        "visitor_id": visitor_id,
        "created_at": now,
        "expires_at": now + TRIAL_TTL,
        "ip": ip,
    }
    # SET NX：仅在 key 不存在时写入（原子操作，防并发重复创建）
    created = redis.set(key, json.dumps(data), ex=TRIAL_TTL, nx=True)
    if not created:
        # 并发情况下另一个请求已创建，读取并返回
        existing = redis.get(key)
        if existing:
            data = json.loads(existing)
            data["created_at"] = _ts_to_iso(data["created_at"])
            data["expires_at"] = _ts_to_iso(data["expires_at"])
            return data

    # 增加 IP 计数
    pipe = redis.pipeline()
    pipe.incr(ip_key)
    pipe.expire(ip_key, IP_WINDOW)
    pipe.execute()

    data["created_at"] = _ts_to_iso(data["created_at"])
    data["expires_at"] = _ts_to_iso(data["expires_at"])
    return data


def get_trial(redis: redis_lib.Redis, visitor_id: str) -> dict | None:
    """获取 trial 状态，不存在返回 None。"""
    raw = redis.get(_trial_key(visitor_id))
    if raw is None:
        return None
    data = json.loads(raw)
    # 兼容旧格式（float timestamp）和新格式（ISO string）
    created_at = data["created_at"]
    expires_at = data["expires_at"]
    if isinstance(created_at, float):
        created_at = _ts_to_iso(created_at)
        expires_at_ts = data["expires_at"]
    else:
        expires_at_ts = datetime.fromisoformat(expires_at).timestamp()

    remaining = max(0, int(expires_at_ts - time.time()))
    return {
        "visitor_id": data["visitor_id"],
        "created_at": created_at,
        "expires_at": expires_at if isinstance(expires_at, str) else _ts_to_iso(expires_at),
        "remaining_seconds": remaining,
        "expired": remaining == 0,
    }


def is_trial_active(redis: redis_lib.Redis, visitor_id: str) -> bool:
    """visitor_id 是否有有效（未过期）的 trial。"""
    trial = get_trial(redis, visitor_id)
    return trial is not None and not trial["expired"]
