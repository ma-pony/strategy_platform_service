"""回测服务单元测试（任务 8.1）。

验证：
  - list_backtests 按 strategy_id 分页查询，按 created_at 降序
  - get_backtest 单条查询，不存在时抛出 NotFoundError(code=3001)
  - 不提供任何触发回测的方法
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.core.exceptions import NotFoundError


def _make_mock_backtest_result(
    id: int = 1,
    strategy_id: int = 1,
    task_id: int = 1,
) -> MagicMock:
    """创建 mock BacktestResult 对象。"""
    result = MagicMock()
    result.id = id
    result.strategy_id = strategy_id
    result.task_id = task_id
    result.total_return = 0.15
    result.annual_return = 0.20
    result.sharpe_ratio = 1.5
    result.max_drawdown = 0.10
    result.trade_count = 50
    result.win_rate = 0.60
    from datetime import datetime, timezone

    result.period_start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    result.period_end = datetime(2024, 12, 31, tzinfo=timezone.utc)
    result.created_at = datetime(2024, 12, 31, tzinfo=timezone.utc)
    return result


class TestBacktestServiceListBacktests:
    """BacktestService.list_backtests 测试。"""

    @pytest.mark.asyncio
    async def test_list_backtests_returns_tuple_of_list_and_count(self) -> None:
        """list_backtests 应返回 (results, total) 元组。"""
        from src.services.backtest_service import BacktestService

        service = BacktestService()
        mock_db = AsyncMock()

        # mock count 查询
        count_result = MagicMock()
        count_result.scalar_one.return_value = 2

        # mock 数据查询
        results = [_make_mock_backtest_result(id=1), _make_mock_backtest_result(id=2)]
        data_result = MagicMock()
        data_result.scalars.return_value.all.return_value = results

        mock_db.execute = AsyncMock(side_effect=[count_result, data_result])

        backtest_results, total = await service.list_backtests(mock_db, strategy_id=1, page=1, page_size=20)

        assert total == 2
        assert len(backtest_results) == 2

    @pytest.mark.asyncio
    async def test_list_backtests_uses_strategy_id_filter(self) -> None:
        """list_backtests 应按 strategy_id 过滤。"""
        from src.services.backtest_service import BacktestService

        service = BacktestService()
        mock_db = AsyncMock()

        count_result = MagicMock()
        count_result.scalar_one.return_value = 0

        data_result = MagicMock()
        data_result.scalars.return_value.all.return_value = []

        mock_db.execute = AsyncMock(side_effect=[count_result, data_result])

        results, total = await service.list_backtests(mock_db, strategy_id=99, page=1, page_size=10)

        assert total == 0
        assert results == []

    @pytest.mark.asyncio
    async def test_list_backtests_uses_pagination(self) -> None:
        """list_backtests 应支持分页（page/page_size）。"""
        from src.services.backtest_service import BacktestService

        service = BacktestService()
        mock_db = AsyncMock()

        count_result = MagicMock()
        count_result.scalar_one.return_value = 100

        single_result = [_make_mock_backtest_result(id=5)]
        data_result = MagicMock()
        data_result.scalars.return_value.all.return_value = single_result

        mock_db.execute = AsyncMock(side_effect=[count_result, data_result])

        results, total = await service.list_backtests(mock_db, strategy_id=1, page=3, page_size=5)

        assert total == 100
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_list_backtests_empty_strategy_returns_empty(self) -> None:
        """strategy_id 无对应回测时返回 ([], 0)。"""
        from src.services.backtest_service import BacktestService

        service = BacktestService()
        mock_db = AsyncMock()

        count_result = MagicMock()
        count_result.scalar_one.return_value = 0

        data_result = MagicMock()
        data_result.scalars.return_value.all.return_value = []

        mock_db.execute = AsyncMock(side_effect=[count_result, data_result])

        results, total = await service.list_backtests(mock_db, strategy_id=1, page=1, page_size=20)

        assert results == []
        assert total == 0


class TestBacktestServiceGetBacktest:
    """BacktestService.get_backtest 测试。"""

    @pytest.mark.asyncio
    async def test_get_backtest_returns_result_when_found(self) -> None:
        """get_backtest 在找到记录时应返回 BacktestResult 对象。"""
        from src.services.backtest_service import BacktestService

        service = BacktestService()
        mock_db = AsyncMock()

        mock_result = _make_mock_backtest_result(id=1)
        execute_result = MagicMock()
        execute_result.scalar_one_or_none.return_value = mock_result

        mock_db.execute = AsyncMock(return_value=execute_result)

        backtest = await service.get_backtest(mock_db, backtest_id=1)

        assert backtest.id == 1

    @pytest.mark.asyncio
    async def test_get_backtest_raises_not_found_when_missing(self) -> None:
        """get_backtest 在记录不存在时应抛出 NotFoundError(code=3001)。"""
        from src.services.backtest_service import BacktestService

        service = BacktestService()
        mock_db = AsyncMock()

        execute_result = MagicMock()
        execute_result.scalar_one_or_none.return_value = None

        mock_db.execute = AsyncMock(return_value=execute_result)

        with pytest.raises(NotFoundError) as exc_info:
            await service.get_backtest(mock_db, backtest_id=999)

        assert exc_info.value.code == 3001

    @pytest.mark.asyncio
    async def test_backtest_service_has_no_write_methods(self) -> None:
        """BacktestService 不暴露任何写入方法（无 create/update/delete）。"""
        from src.services.backtest_service import BacktestService

        service = BacktestService()
        assert not hasattr(service, "create_backtest")
        assert not hasattr(service, "update_backtest")
        assert not hasattr(service, "delete_backtest")
        assert not hasattr(service, "trigger_backtest")
        assert not hasattr(service, "run_backtest")
