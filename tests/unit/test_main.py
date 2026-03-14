"""ApplicationRunner 单元测试。"""

import os
import signal

import pytest

from src.main import ApplicationRunner, main


class TestApplicationRunner:
    """测试 ApplicationRunner 类。"""

    def test_runner_init(self) -> None:
        """ApplicationRunner 初始化后 _shutdown_event 为 False。"""
        runner = ApplicationRunner()
        assert runner._shutdown_event is False

    def test_handle_signal_sets_shutdown_event(self) -> None:
        """_handle_signal() 调用后设置 _shutdown_event=True。"""
        runner = ApplicationRunner()
        runner._handle_signal(signal.SIGINT, None)
        assert runner._shutdown_event is True

    def test_start_completes_with_valid_config(
        self, clear_settings_cache: None
    ) -> None:
        """有效配置下 ApplicationRunner.start() 完成初始化不抛出异常。"""
        os.environ.pop("APP_ENV", None)
        runner = ApplicationRunner()
        # start() 应正常完成（占位主循环立即返回）
        runner.start()

    def test_start_missing_config_calls_exit(
        self, clear_settings_cache: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """缺少必填配置时 start() 以非零退出码退出。"""
        from pydantic import ValidationError

        import src.main as main_module

        def mock_factory() -> None:
            raise ValidationError.from_exception_data(
                title="DevSettings",
                input_type="python",
                line_errors=[],
            )

        exit_calls: list[int] = []

        def mock_exit(code: int) -> None:
            exit_calls.append(code)
            raise SystemExit(code)

        monkeypatch.setattr("sys.exit", mock_exit)
        # mock src.main 模块中实际引用的 settings_factory
        monkeypatch.setattr(main_module, "settings_factory", mock_factory)

        runner = ApplicationRunner()
        with pytest.raises(SystemExit) as exc_info:
            runner.start()
        assert exc_info.value.code != 0

    def test_shutdown_calls_exit_zero(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """shutdown() 以 exit(0) 退出。"""
        exit_calls: list[int] = []

        def mock_exit(code: int) -> None:
            exit_calls.append(code)
            raise SystemExit(code)

        monkeypatch.setattr("sys.exit", mock_exit)
        runner = ApplicationRunner()
        with pytest.raises(SystemExit) as exc_info:
            runner.shutdown()
        assert exc_info.value.code == 0

    def test_uncaught_exception_exits_nonzero(
        self, clear_settings_cache: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """服务主循环中未捕获异常时以非零退出码退出。"""
        import src.main as main_module

        os.environ.pop("APP_ENV", None)
        exit_calls: list[int] = []

        def mock_exit(code: int) -> None:
            exit_calls.append(code)
            raise SystemExit(code)

        def mock_run_service(self: ApplicationRunner) -> None:
            raise RuntimeError("unexpected error")

        monkeypatch.setattr("sys.exit", mock_exit)
        monkeypatch.setattr(
            main_module.ApplicationRunner, "_run_service", mock_run_service
        )

        runner = ApplicationRunner()
        with pytest.raises(SystemExit) as exc_info:
            runner.start()
        assert exc_info.value.code != 0


class TestMainFunction:
    """测试 main() 入口函数。"""

    def test_main_is_callable(self) -> None:
        """main() 函数应可调用。"""
        assert callable(main)

    def test_main_creates_runner_and_starts(
        self, clear_settings_cache: None
    ) -> None:
        """main() 调用不抛出异常（有效环境）。"""
        os.environ.pop("APP_ENV", None)
        main()
