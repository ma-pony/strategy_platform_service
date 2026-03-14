"""结构化日志模块。

提供 configure_logging() 和 get_logger() 两个核心接口。
"""

import logging
import sys
from typing import Literal

import structlog
from structlog.processors import CallsiteParameter

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]


def configure_logging(
    level: LogLevel = "INFO",
    is_production: bool = False,
) -> None:
    """配置全局 structlog 处理器链。

    - is_production=True：JSON 输出
    - is_production=False：ConsoleRenderer 彩色输出（或根据 isatty 自动判断）
    调用一次后即生效，应在 main.py 启动序列的最早阶段调用。
    为幂等操作，多次调用不产生副作用。
    """
    # 设置标准库 logging 级别
    logging.basicConfig(level=getattr(logging, level), format="%(message)s", force=True)

    # 根据 is_production 或终端类型选择渲染器
    use_json = is_production or not sys.stderr.isatty()

    if use_json:
        renderer: structlog.types.Processor = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer()

    processors: list[structlog.types.Processor] = [
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.stdlib.add_log_level,
        structlog.processors.CallsiteParameterAdder([CallsiteParameter.MODULE]),
        renderer,
    ]

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=False,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """返回绑定模块名的 logger 实例。"""
    logger: structlog.stdlib.BoundLogger = structlog.get_logger(name)
    return logger
