"""Celery 应用初始化与队列配置。

以 Redis 同时作为 broker 和 result backend。
配置两条独立队列：
  - backtest：处理回测任务（concurrency=1，串行执行），避免 API 限额和资源竞争
  - signal：处理信号生成任务（更高频率，独立调度）

Celery Beat 定时计划：
  - 回测任务：每日 UTC 02:00（cron: 0 2 * * *）
  - 信号生成：每 15 分钟（cron: */15 * * * *）
"""

from celery import Celery
from celery.schedules import crontab
from kombu import Queue

from src.core.app_settings import get_settings

settings = get_settings()

celery_app = Celery(
    "strategy_platform",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=[
        "src.workers.tasks.backtest_tasks",
        "src.workers.tasks.signal_tasks",
    ],
)

# ──────────────────────────────────────────────
# 序列化配置
# ──────────────────────────────────────────────
celery_app.conf.task_serializer = "json"
celery_app.conf.result_serializer = "json"
celery_app.conf.accept_content = ["json"]
celery_app.conf.timezone = "UTC"
celery_app.conf.enable_utc = True

# ──────────────────────────────────────────────
# 队列配置：backtest 和 signal 两条独立队列
# ──────────────────────────────────────────────
celery_app.conf.task_queues = (
    Queue("backtest"),
    Queue("signal"),
)
celery_app.conf.task_default_queue = "backtest"

# backtest Worker 并发配置提示：启动时使用 --concurrency=1
# celery -A src.workers.celery_app worker -Q backtest --concurrency=1
celery_app.conf.worker_prefetch_multiplier = 1  # 串行队列每次只预取 1 个任务

# ──────────────────────────────────────────────
# Celery Beat 定时计划
# ──────────────────────────────────────────────
celery_app.conf.beat_schedule = {
    "run-daily-backtest": {
        "task": "src.workers.tasks.backtest_tasks.run_backtest_task",
        "schedule": crontab(hour=2, minute=0),  # 每日 UTC 02:00
        "options": {"queue": "backtest"},
    },
    "generate-signals-every-15min": {
        "task": "src.workers.tasks.signal_tasks.generate_signals_task",
        "schedule": crontab(minute="*/15"),  # 每 15 分钟
        "options": {"queue": "signal"},
    },
}
