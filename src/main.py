"""应用程序主入口。

提供：
  - FastAPI 应用实例 `app`（供 uvicorn 使用：uvicorn src.main:app）
  - ApplicationRunner 类和 main() 入口函数（供脚本模式调用）

FastAPI app 包含完整的 lifespan 管理（sqladmin 挂载、数据库连接池）。

可通过以下方式启动：
  - uvicorn src.main:app --reload
  - python -m src.main（脚本模式，旧占位实现）
"""

import signal
import sys
import types

from config import settings_factory
from src.api.app import create_app_with_lifespan
from src.utils.logging import configure_logging, get_logger

# FastAPI 应用实例，供 uvicorn 启动使用
# uvicorn src.main:app --host 0.0.0.0 --port 8000
app = create_app_with_lifespan()


class ApplicationRunner:
    """应用程序运行器，管理启动序列、信号处理和优雅退出。"""

    def __init__(self) -> None:
        self._shutdown_event: bool = False

    def _handle_signal(self, signum: int, frame: types.FrameType | None) -> None:
        """设置关闭标志，触发优雅退出。"""
        self._shutdown_event = True

    def _run_service(self) -> None:
        """服务主循环（当前为占位实现）。"""
        logger = get_logger(__name__)
        logger.info("service started, running placeholder main loop")

    def start(self) -> None:
        """加载配置、初始化日志、注册信号处理器并启动服务主循环。"""
        try:
            # 1. 加载配置（校验失败立即退出）
            settings = settings_factory()

            # 2. 初始化日志
            is_production = settings.app_env == "production"
            configure_logging(
                level=settings.log_level,
                is_production=is_production,
            )

            logger = get_logger(__name__)
            logger.info(
                "application starting",
                app_name=settings.app_name,
                app_env=settings.app_env,
                log_level=settings.log_level,
            )

            # 3. 注册信号处理器
            signal.signal(signal.SIGTERM, self._handle_signal)
            signal.signal(signal.SIGINT, self._handle_signal)

            # 4. 启动服务主循环
            self._run_service()

        except SystemExit:
            raise
        except Exception as exc:
            # 未捕获异常：记录 CRITICAL 日志后以非零退出码退出
            try:
                logger = get_logger(__name__)
                logger.critical("unhandled exception during startup", exc_info=exc)
            except Exception:
                pass
            sys.exit(1)

    def shutdown(self) -> None:
        """执行清理逻辑后退出进程。"""
        try:
            logger = get_logger(__name__)
            logger.info("application shutting down gracefully")
        except Exception:
            pass
        sys.exit(0)


def main() -> None:
    """模块入口点，创建 ApplicationRunner 并调用 start()。"""
    runner = ApplicationRunner()
    runner.start()


if __name__ == "__main__":
    main()
