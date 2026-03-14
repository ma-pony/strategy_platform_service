"""LoggingModule 单元测试。"""

from src.utils.logging import configure_logging, get_logger


class TestConfigureLogging:
    """测试 configure_logging 函数。"""

    def test_configure_logging_no_exception(self) -> None:
        """configure_logging() 调用不抛出异常。"""
        configure_logging()

    def test_configure_logging_with_debug_level(self) -> None:
        """configure_logging(level='DEBUG') 调用不抛出异常。"""
        configure_logging(level="DEBUG")

    def test_configure_logging_with_error_level(self) -> None:
        """configure_logging(level='ERROR') 调用不抛出异常。"""
        configure_logging(level="ERROR")

    def test_configure_logging_is_production_true(self) -> None:
        """configure_logging(is_production=True) 调用不抛出异常（JSON 渲染器）。"""
        configure_logging(is_production=True)

    def test_configure_logging_is_production_false(self) -> None:
        """configure_logging(is_production=False) 调用不抛出异常（Console 渲染器）。"""
        configure_logging(is_production=False)

    def test_configure_logging_idempotent(self) -> None:
        """configure_logging() 多次调用不产生副作用（幂等性）。"""
        configure_logging(level="INFO", is_production=True)
        configure_logging(level="INFO", is_production=True)
        configure_logging(level="DEBUG", is_production=False)

    def test_configure_logging_default_level_is_info(self) -> None:
        """configure_logging() 默认 level 为 INFO，不传参数调用不抛出异常。"""
        configure_logging()


class TestGetLogger:
    """测试 get_logger 工具函数。"""

    def test_get_logger_returns_bound_logger(self) -> None:
        """get_logger() 返回 structlog BoundLogger 实例。"""
        configure_logging()
        logger = get_logger("test_module")
        assert logger is not None

    def test_get_logger_can_log_info(self) -> None:
        """get_logger() 返回的 logger 可以调用 .info() 不抛出异常。"""
        configure_logging(is_production=True)
        logger = get_logger("test_module")
        logger.info("test message", key="value")

    def test_get_logger_can_log_debug(self) -> None:
        """get_logger() 返回的 logger 可以调用 .debug() 不抛出异常。"""
        configure_logging(is_production=True)
        logger = get_logger("test_module")
        logger.debug("debug message")

    def test_get_logger_can_log_error(self) -> None:
        """get_logger() 返回的 logger 可以调用 .error() 不抛出异常。"""
        configure_logging(is_production=True)
        logger = get_logger("test_module")
        logger.error("error message")


class TestLoggingModuleExport:
    """测试 src.utils 包的导出接口。"""

    def test_import_configure_logging(self) -> None:
        """src.utils 包应导出 configure_logging。"""
        from src.utils import configure_logging as cl

        assert callable(cl)

    def test_import_get_logger(self) -> None:
        """src.utils 包应导出 get_logger。"""
        from src.utils import get_logger as gl

        assert callable(gl)
