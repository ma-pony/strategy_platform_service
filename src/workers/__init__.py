"""Celery Worker 层。

包含 Celery 应用初始化（celery_app.py）和异步任务定义（tasks/）。
Worker 层不依赖 FastAPI，使用同步 SQLAlchemy session（Celery Worker 不适合 async）。
"""
