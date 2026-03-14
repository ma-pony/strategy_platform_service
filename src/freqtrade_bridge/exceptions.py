"""freqtrade 集成专用异常类。

这些异常在 freqtrade bridge 层内部使用，
对外（服务层）的 AppError 体系转换在 Celery 任务中处理。
"""


class FreqtradeExecutionError(Exception):
    """freqtrade 执行失败。

    包含对用户友好的错误描述，不暴露原始 stderr 或内部路径。
    """

    def __init__(self, message: str = "量化引擎执行失败") -> None:
        self.message = message
        super().__init__(self.message)


class FreqtradeTimeoutError(Exception):
    """freqtrade 任务超时。

    任务执行超过配置的最大等待时间。
    """

    def __init__(self, message: str = "量化引擎执行超时") -> None:
        self.message = message
        super().__init__(self.message)
