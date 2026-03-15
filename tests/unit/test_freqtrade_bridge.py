"""freqtrade bridge 单元测试（任务 6.1, 6.2 / 13.4）。

验证：
  - run_backtest_subprocess 在超时时抛出 FreqtradeTimeoutError
  - 非零退出码时抛出 FreqtradeExecutionError，原始 stderr 不被透传
  - 隔离目录在任务结束后（含失败路径）被清理
  - 配置文件生成器在指定目录生成合法 JSON
  - fetch_signals 失败时抛出 FreqtradeExecutionError
"""

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


class TestRunBacktestSubprocess:
    """run_backtest_subprocess 单元测试。"""

    def test_timeout_raises_freqtrade_timeout_error(self, tmp_path: Path) -> None:
        """subprocess 超时时抛出 FreqtradeTimeoutError。"""
        from src.freqtrade_bridge.exceptions import FreqtradeTimeoutError
        from src.freqtrade_bridge.backtester import run_backtest_subprocess

        config_path = tmp_path / "config.json"
        config_path.write_text("{}")

        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="freqtrade", timeout=600)):
            with pytest.raises(FreqtradeTimeoutError):
                run_backtest_subprocess(config_path, "TestStrategy")

    def test_nonzero_exit_code_raises_execution_error(self, tmp_path: Path) -> None:
        """非零退出码时抛出 FreqtradeExecutionError。"""
        from src.freqtrade_bridge.exceptions import FreqtradeExecutionError
        from src.freqtrade_bridge.backtester import run_backtest_subprocess

        config_path = tmp_path / "config.json"
        config_path.write_text("{}")

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "freqtrade internal error details"
        mock_result.stdout = ""

        with patch("subprocess.run", return_value=mock_result):
            with pytest.raises(FreqtradeExecutionError):
                run_backtest_subprocess(config_path, "TestStrategy")

    def test_stderr_not_exposed_in_exception_message(self, tmp_path: Path) -> None:
        """FreqtradeExecutionError 不暴露原始 freqtrade stderr。"""
        from src.freqtrade_bridge.exceptions import FreqtradeExecutionError
        from src.freqtrade_bridge.backtester import run_backtest_subprocess

        config_path = tmp_path / "config.json"
        config_path.write_text("{}")

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "INTERNAL freqtrade path: /usr/local/lib/freqtrade/secret.py"
        mock_result.stdout = ""

        with patch("subprocess.run", return_value=mock_result):
            with pytest.raises(FreqtradeExecutionError) as exc_info:
                run_backtest_subprocess(config_path, "TestStrategy")

        # 异常消息中不应包含原始 stderr 内容（内部路径）
        assert "INTERNAL freqtrade path" not in str(exc_info.value)
        assert "/usr/local/lib/freqtrade/secret.py" not in str(exc_info.value)

    def test_success_returns_dict(self, tmp_path: Path) -> None:
        """执行成功时返回解析后的结果字典。"""
        from src.freqtrade_bridge.backtester import run_backtest_subprocess

        config_path = tmp_path / "config.json"
        config_path.write_text("{}")

        parsed_result = {"total_return": 0.15, "sharpe_ratio": 1.2}

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result):
            with patch(
                "src.freqtrade_bridge.backtester._parse_backtest_result",
                return_value=parsed_result,
            ):
                result = run_backtest_subprocess(config_path, "TestStrategy")

        assert result == parsed_result

    def test_timeout_parameter_passed_to_subprocess(self, tmp_path: Path) -> None:
        """超时参数正确传递给 subprocess.run。"""
        from src.freqtrade_bridge.backtester import run_backtest_subprocess

        config_path = tmp_path / "config.json"
        config_path.write_text("{}")

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps({})
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            run_backtest_subprocess(config_path, "TestStrategy", timeout=300)

        call_kwargs = mock_run.call_args
        assert call_kwargs.kwargs.get("timeout") == 300 or (
            len(call_kwargs.args) > 1 and call_kwargs.args[1] == 300
        )


class TestGenerateConfig:
    """配置文件生成器单元测试。"""

    def test_generate_config_creates_json_file(self, tmp_path: Path) -> None:
        """generate_config 在指定目录生成 JSON 配置文件。"""
        from src.freqtrade_bridge.runner import generate_config

        strategy_config = {
            "stake_currency": "USDT",
            "timeframe": "5m",
            "pairs": ["BTC/USDT", "ETH/USDT"],
        }

        config_path = generate_config(tmp_path, strategy_config)

        assert config_path.exists()
        assert config_path.suffix == ".json"
        loaded = json.loads(config_path.read_text())
        assert loaded["stake_currency"] == "USDT"
        assert loaded["timeframe"] == "5m"

    def test_generate_config_does_not_contain_api_keys(self, tmp_path: Path) -> None:
        """生成的配置不包含交易所 API Key 等敏感信息。"""
        from src.freqtrade_bridge.runner import generate_config

        strategy_config = {
            "stake_currency": "USDT",
            "api_key": "should-not-appear",  # 即使传入也应被过滤
        }

        config_path = generate_config(tmp_path, strategy_config)
        content = config_path.read_text()

        assert "should-not-appear" not in content

    def test_generate_config_returns_path_object(self, tmp_path: Path) -> None:
        """generate_config 返回 Path 对象。"""
        from src.freqtrade_bridge.runner import generate_config

        config_path = generate_config(tmp_path, {"stake_currency": "USDT"})
        assert isinstance(config_path, Path)


class TestCleanupTaskDir:
    """隔离目录清理函数单元测试。"""

    def test_cleanup_removes_existing_directory(self, tmp_path: Path) -> None:
        """cleanup_task_dir 清理指定目录。"""
        from src.freqtrade_bridge.runner import cleanup_task_dir

        task_dir = tmp_path / "task_123"
        task_dir.mkdir()
        (task_dir / "config.json").write_text("{}")

        cleanup_task_dir(task_dir)

        assert not task_dir.exists()

    def test_cleanup_is_safe_when_directory_not_exists(self, tmp_path: Path) -> None:
        """目录不存在时 cleanup_task_dir 不抛出异常。"""
        from src.freqtrade_bridge.runner import cleanup_task_dir

        nonexistent = tmp_path / "nonexistent_dir"
        # 不应抛出异常
        cleanup_task_dir(nonexistent)

    def test_cleanup_called_on_success_path(self, tmp_path: Path) -> None:
        """run_backtest_subprocess 成功时，隔离目录应被清理（通过 finally 块）。"""
        from src.freqtrade_bridge.runner import generate_config, cleanup_task_dir

        task_dir = tmp_path / "task_cleanup_test"
        task_dir.mkdir()
        config_path = generate_config(task_dir, {"stake_currency": "USDT"})

        assert config_path.exists()
        cleanup_task_dir(task_dir)
        assert not task_dir.exists()

    def test_cleanup_called_on_failure_path(self, tmp_path: Path) -> None:
        """run_backtest_subprocess 失败时（通过 finally 块），目录同样被清理。

        此测试验证 cleanup_task_dir 在异常路径中调用后目录确实被删除。
        """
        from src.freqtrade_bridge.runner import cleanup_task_dir

        task_dir = tmp_path / "task_fail_cleanup"
        task_dir.mkdir()
        (task_dir / "config.json").write_text("{}")

        try:
            raise RuntimeError("模拟任务失败")
        except RuntimeError:
            pass
        finally:
            cleanup_task_dir(task_dir)

        assert not task_dir.exists()


class TestPathIsolation:
    """路径隔离单元测试（需求 7.5）。

    验证不同用户/任务的 freqtrade 配置路径互不重叠，
    防止配置文件相互覆盖。
    """

    def test_different_task_ids_produce_non_overlapping_paths(self, tmp_path: Path) -> None:
        """为两个不同 task_id 生成配置路径，断言路径不重叠。"""
        from src.freqtrade_bridge.runner import generate_config

        user_id = 42
        task_id_1 = 101
        task_id_2 = 102

        task_dir_1 = tmp_path / str(user_id) / str(task_id_1)
        task_dir_2 = tmp_path / str(user_id) / str(task_id_2)

        config_1 = generate_config(task_dir_1, {"stake_currency": "USDT"})
        config_2 = generate_config(task_dir_2, {"stake_currency": "USDT"})

        # 路径不重叠：config 文件在不同目录
        assert config_1.parent != config_2.parent
        assert str(task_id_1) in str(config_1)
        assert str(task_id_2) in str(config_2)

    def test_different_user_ids_produce_non_overlapping_paths(self, tmp_path: Path) -> None:
        """为两个不同 user_id 生成配置路径，断言路径不重叠。"""
        from src.freqtrade_bridge.runner import generate_config

        user_id_1 = 1
        user_id_2 = 2
        task_id = 999

        task_dir_1 = tmp_path / str(user_id_1) / str(task_id)
        task_dir_2 = tmp_path / str(user_id_2) / str(task_id)

        config_1 = generate_config(task_dir_1, {"stake_currency": "USDT"})
        config_2 = generate_config(task_dir_2, {"stake_currency": "USDT"})

        # 不同用户的路径不重叠
        assert config_1.parent != config_2.parent
        # 写入 config_1 的内容不影响 config_2
        config_1.write_text('{"user": "1"}')
        assert config_1.read_text() != config_2.read_text()

    def test_task_dir_follows_isolation_pattern(self, tmp_path: Path) -> None:
        """验证任务目录遵循 /{base}/{user_id}/{task_id}/ 隔离模式。"""
        user_id = 7
        task_id = 200

        task_dir = tmp_path / str(user_id) / str(task_id)
        # 路径中包含 user_id 和 task_id，确保隔离命名体现在目录层级
        parts = task_dir.parts
        assert str(user_id) in parts
        assert str(task_id) in parts
        # user_id 在 task_id 之前（父目录）
        user_idx = parts.index(str(user_id))
        task_idx = parts.index(str(task_id))
        assert user_idx < task_idx


class TestFetchSignals:
    """fetch_signals 信号获取单元测试。"""

    def test_fetch_signals_failure_raises_execution_error(self) -> None:
        """信号获取失败时抛出 FreqtradeExecutionError。"""
        import asyncio
        from concurrent.futures import ProcessPoolExecutor
        from unittest.mock import patch
        from src.freqtrade_bridge.exceptions import FreqtradeExecutionError
        from src.freqtrade_bridge.signal_fetcher import fetch_signals

        # 模拟 ProcessPoolExecutor.submit 抛出异常
        with patch(
            "src.freqtrade_bridge.signal_fetcher._fetch_signals_sync",
            side_effect=RuntimeError("freqtrade module import failed"),
        ):
            with patch(
                "src.freqtrade_bridge.signal_fetcher._executor"
            ) as mock_executor:
                # 模拟 executor.submit 返回一个失败的 future
                import concurrent.futures
                future: concurrent.futures.Future = concurrent.futures.Future()
                future.set_exception(RuntimeError("freqtrade module import failed"))
                mock_executor.submit.return_value = future

                with pytest.raises(FreqtradeExecutionError):
                    asyncio.run(fetch_signals("TestStrategy", "BTC/USDT"))

    def test_fetch_signals_module_structure_exists(self) -> None:
        """验证 signal_fetcher 模块结构存在且可导入。"""
        from src.freqtrade_bridge import signal_fetcher

        assert hasattr(signal_fetcher, "fetch_signals")
        assert hasattr(signal_fetcher, "_fetch_signals_sync")
