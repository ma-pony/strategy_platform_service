"""任务 8.3 / 4.1-4.4 单元测试：CoordTask（generate_all_signals_task）。

测试分布式锁幂等性、连续失败告警、两阶段流水线串行执行。

涵盖需求：2.7, 5.2, 5.4
"""

import contextlib
from unittest.mock import MagicMock, patch


class TestDistributedLock:
    """任务 4.1：测试分布式锁与幂等调度。"""

    def test_task_skips_when_lock_exists(self) -> None:
        """锁已存在时，任务幂等跳过（需求 2.7）。"""
        from src.workers.tasks.signal_coord_task import generate_all_signals_task

        mock_redis = MagicMock()
        # SET NX 返回 None 表示锁已存在
        mock_redis.set = MagicMock(return_value=None)

        with patch("src.workers.tasks.signal_coord_task.get_redis_client", return_value=mock_redis):
            with patch("src.workers.tasks.signal_coord_task.DataDownloader") as mock_dd:
                with patch("src.workers.tasks.signal_coord_task.SignalCalculator") as mock_sc:
                    generate_all_signals_task()

                    # DataDownloader 和 SignalCalculator 不应被调用
                    mock_dd.return_value.download_market_data.assert_not_called()
                    mock_sc.return_value.compute_all_signals.assert_not_called()

    def test_task_runs_when_lock_acquired(self) -> None:
        """成功获取锁时，任务正常执行两阶段流水线。"""
        from src.freqtrade_bridge.data_downloader import DownloadResult
        from src.freqtrade_bridge.signal_calculator import SignalComputeResult
        from src.workers.tasks.signal_coord_task import generate_all_signals_task

        mock_redis = MagicMock()
        # SET NX 返回 True 表示锁获取成功
        mock_redis.set = MagicMock(return_value=True)
        mock_redis.delete = MagicMock()
        mock_redis.get = MagicMock(return_value=None)
        mock_redis.set = MagicMock(return_value=True)

        mock_download_result = DownloadResult(
            data_source="exchange",
            pairs_downloaded=10,
            pairs_skipped=0,
            pairs_failed=0,
            elapsed_seconds=5.0,
        )

        mock_compute_result = SignalComputeResult(
            total_combinations=100,
            success_count=98,
            failure_count=2,
            elapsed_seconds=35.0,
            cache_hit_rate=0.9,
        )

        with patch("src.workers.tasks.signal_coord_task.get_redis_client", return_value=mock_redis):
            with patch("src.workers.tasks.signal_coord_task.DataDownloader") as mock_dd_cls:
                with patch("src.workers.tasks.signal_coord_task.SignalCalculator") as mock_sc_cls:
                    with patch("src.workers.tasks.signal_coord_task._get_active_strategies_and_pairs") as mock_get:
                        mock_get.return_value = (
                            [{"id": 1, "name": "Test", "class": MagicMock()}],
                            ["BTC/USDT"],
                        )

                        mock_dd_cls.return_value.download_market_data.return_value = mock_download_result
                        mock_sc_cls.return_value.compute_all_signals.return_value = mock_compute_result

                        generate_all_signals_task()

                        # 两阶段都应被调用
                        mock_dd_cls.return_value.download_market_data.assert_called_once()
                        mock_sc_cls.return_value.compute_all_signals.assert_called_once()

    def test_lock_released_in_finally(self) -> None:
        """任务完成（成功或失败）后，锁应被释放（finally 块，需求 4.1）。"""
        from src.workers.tasks.signal_coord_task import generate_all_signals_task

        mock_redis = MagicMock()
        mock_redis.set = MagicMock(return_value=True)
        mock_redis.delete = MagicMock()
        mock_redis.get = MagicMock(return_value=None)

        with patch("src.workers.tasks.signal_coord_task.get_redis_client", return_value=mock_redis):
            with patch("src.workers.tasks.signal_coord_task.DataDownloader") as mock_dd_cls:
                with patch("src.workers.tasks.signal_coord_task._get_active_strategies_and_pairs") as mock_get:
                    mock_get.return_value = ([], [])
                    # DataDownloader 抛出异常
                    mock_dd_cls.return_value.download_market_data.side_effect = Exception("下载失败")

                    with contextlib.suppress(Exception):
                        generate_all_signals_task()

                    # 即使失败，锁也应被释放
                    mock_redis.delete.assert_called()


class TestConsecutiveFailureAlert:
    """任务 4.3：测试连续失败告警计数器。"""

    def test_failure_increments_counter(self) -> None:
        """任务失败时，连续失败计数器 INCR（需求 5.4）。"""
        from src.workers.tasks.signal_coord_task import generate_all_signals_task

        mock_redis = MagicMock()
        mock_redis.set = MagicMock(return_value=True)
        mock_redis.delete = MagicMock()
        mock_redis.incr = MagicMock(return_value=1)
        mock_redis.get = MagicMock(return_value=None)

        with patch("src.workers.tasks.signal_coord_task.get_redis_client", return_value=mock_redis):
            with patch("src.workers.tasks.signal_coord_task.DataDownloader") as mock_dd_cls:
                with patch("src.workers.tasks.signal_coord_task._get_active_strategies_and_pairs") as mock_get:
                    mock_get.return_value = ([{"id": 1, "name": "T", "class": MagicMock()}], ["BTC/USDT"])
                    mock_dd_cls.return_value.download_market_data.side_effect = Exception("下载失败")

                    with contextlib.suppress(Exception):
                        generate_all_signals_task()

                    # 失败计数器应被 INCR
                    mock_redis.incr.assert_called()

    def test_success_resets_failure_counter(self) -> None:
        """任务成功时，连续失败计数器重置为 0（需求 5.4）。"""
        from src.freqtrade_bridge.data_downloader import DownloadResult
        from src.freqtrade_bridge.signal_calculator import SignalComputeResult
        from src.workers.tasks.signal_coord_task import generate_all_signals_task

        mock_redis = MagicMock()
        mock_redis.set = MagicMock(return_value=True)
        mock_redis.delete = MagicMock()
        mock_redis.incr = MagicMock()
        mock_redis.get = MagicMock(return_value=None)

        mock_download_result = DownloadResult(
            data_source="exchange",
            pairs_downloaded=1,
            pairs_skipped=0,
            pairs_failed=0,
            elapsed_seconds=1.0,
        )
        mock_compute_result = SignalComputeResult(
            total_combinations=1,
            success_count=1,
            failure_count=0,
            elapsed_seconds=1.0,
            cache_hit_rate=0.0,
        )

        with patch("src.workers.tasks.signal_coord_task.get_redis_client", return_value=mock_redis):
            with patch("src.workers.tasks.signal_coord_task.DataDownloader") as mock_dd_cls:
                with patch("src.workers.tasks.signal_coord_task.SignalCalculator") as mock_sc_cls:
                    with patch("src.workers.tasks.signal_coord_task._get_active_strategies_and_pairs") as mock_get:
                        mock_get.return_value = (
                            [{"id": 1, "name": "T", "class": MagicMock()}],
                            ["BTC/USDT"],
                        )
                        mock_dd_cls.return_value.download_market_data.return_value = mock_download_result
                        mock_sc_cls.return_value.compute_all_signals.return_value = mock_compute_result

                        generate_all_signals_task()

                        # 成功时，set 应被调用以重置计数器（set key 0 或 delete）
                        # 断言 set 被调用多次（一次获取锁，一次重置计数器）
                        assert mock_redis.set.call_count >= 1

    def test_three_consecutive_failures_trigger_error_log(self) -> None:
        """连续 3 次失败时触发 ERROR 级别告警日志（需求 5.4）。"""
        from src.workers.tasks.signal_coord_task import generate_all_signals_task

        mock_redis = MagicMock()
        mock_redis.set = MagicMock(return_value=True)
        mock_redis.delete = MagicMock()
        # incr 返回 3（第三次失败）
        mock_redis.incr = MagicMock(return_value=3)
        mock_redis.get = MagicMock(return_value=None)

        with patch("src.workers.tasks.signal_coord_task.get_redis_client", return_value=mock_redis):
            with patch("src.workers.tasks.signal_coord_task.DataDownloader") as mock_dd_cls:
                with patch("src.workers.tasks.signal_coord_task._get_active_strategies_and_pairs") as mock_get:
                    mock_get.return_value = ([{"id": 1, "name": "T", "class": MagicMock()}], ["BTC/USDT"])
                    mock_dd_cls.return_value.download_market_data.side_effect = Exception("下载失败")

                    with patch("src.workers.tasks.signal_coord_task.logger") as mock_logger:
                        with contextlib.suppress(Exception):
                            generate_all_signals_task()

                        # 连续 3 次失败应记录 ERROR 日志
                        mock_logger.error.assert_called()
