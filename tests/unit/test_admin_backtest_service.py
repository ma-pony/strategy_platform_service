"""AdminBacktestService 单元测试（任务 10.2）。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.exceptions import NotFoundError, UnsupportedStrategyError


class TestAdminBacktestService:
    """管理员回测服务测试。"""

    @pytest.mark.asyncio
    async def test_submit_backtest_valid_strategy(self) -> None:
        """合法策略应直接入队，不检查 RUNNING 数。"""
        from src.services.admin_backtest_service import AdminBacktestService

        service = AdminBacktestService()
        mock_db = AsyncMock()

        # Mock strategy 查询
        mock_strategy = SimpleNamespace(id=1, name="TurtleTradingStrategy")
        mock_db.get = AsyncMock(return_value=mock_strategy)
        mock_db.flush = AsyncMock()
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()

        with (
            patch("src.services.admin_backtest_service.lookup") as mock_lookup,
            patch("src.workers.celery_app.celery_app") as mock_celery,
        ):
            mock_lookup.return_value = {
                "class_name": "TurtleTradingStrategy",
                "file_path": MagicMock(exists=MagicMock(return_value=True)),
            }

            await service.submit_backtest(mock_db, strategy_id=1, timerange="20240101-20240301")

            # 验证 Celery 入队被调用
            mock_celery.send_task.assert_called_once()
            mock_db.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_submit_backtest_strategy_not_found(self) -> None:
        """策略不存在应抛 NotFoundError。"""
        from src.services.admin_backtest_service import AdminBacktestService

        service = AdminBacktestService()
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=None)

        with pytest.raises(NotFoundError):
            await service.submit_backtest(mock_db, strategy_id=999, timerange="20240101-20240301")

    @pytest.mark.asyncio
    async def test_submit_backtest_unsupported_strategy(self) -> None:
        """策略不在注册表应抛 UnsupportedStrategyError(3003)。"""
        from src.services.admin_backtest_service import AdminBacktestService

        service = AdminBacktestService()
        mock_db = AsyncMock()

        mock_strategy = SimpleNamespace(id=1, name="FakeStrategy")
        mock_db.get = AsyncMock(return_value=mock_strategy)

        with patch(
            "src.services.admin_backtest_service.lookup",
            side_effect=UnsupportedStrategyError("不支持"),
        ):
            with pytest.raises(UnsupportedStrategyError) as exc_info:
                await service.submit_backtest(mock_db, strategy_id=1, timerange="20240101-20240301")
            assert exc_info.value.code == 3003

    @pytest.mark.asyncio
    async def test_get_task_not_found(self) -> None:
        """task_id 不存在应抛 NotFoundError(3001)。"""
        from src.services.admin_backtest_service import AdminBacktestService

        service = AdminBacktestService()
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=None)

        with pytest.raises(NotFoundError) as exc_info:
            await service.get_task(mock_db, task_id=999)
        assert exc_info.value.code == 3001
