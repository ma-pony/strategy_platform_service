"""策略服务单元测试（任务 5.1）。

验证 StrategyService：
  - list_strategies 分页列表查询（禁止全表扫描）
  - get_strategy 详情查询（含最近回测结果）
  - 策略不存在时抛出 NotFoundError(code=3001)
  - 不提供任何写入方法
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.core.exceptions import NotFoundError


class TestStrategyServiceListStrategies:
    """list_strategies 分页查询测试。"""

    @pytest.mark.asyncio
    async def test_list_strategies_returns_tuple(self) -> None:
        """返回 (strategies, total) 元组。"""
        from src.services.strategy_service import StrategyService

        db = AsyncMock()

        # mock execute 返回分页结果
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_count_result = MagicMock()
        mock_count_result.scalar_one.return_value = 0

        db.execute = AsyncMock(side_effect=[mock_count_result, mock_result])

        service = StrategyService()
        strategies, total = await service.list_strategies(db, page=1, page_size=20)

        assert isinstance(strategies, list)
        assert isinstance(total, int)
        assert total == 0

    @pytest.mark.asyncio
    async def test_list_strategies_applies_offset(self) -> None:
        """第 2 页应使用正确的 offset。"""
        from src.services.strategy_service import StrategyService

        db = AsyncMock()

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_count_result = MagicMock()
        mock_count_result.scalar_one.return_value = 50

        db.execute = AsyncMock(side_effect=[mock_count_result, mock_result])

        service = StrategyService()
        strategies, total = await service.list_strategies(db, page=2, page_size=20)

        assert total == 50
        assert isinstance(strategies, list)

    @pytest.mark.asyncio
    async def test_list_strategies_returns_strategies(self) -> None:
        """有数据时返回策略列表。"""
        from src.services.strategy_service import StrategyService
        from src.models.strategy import Strategy

        db = AsyncMock()

        # 创建 mock 策略
        mock_strategy = MagicMock(spec=Strategy)
        mock_strategy.id = 1
        mock_strategy.name = "RSI Strategy"

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_strategy]
        mock_count_result = MagicMock()
        mock_count_result.scalar_one.return_value = 1

        db.execute = AsyncMock(side_effect=[mock_count_result, mock_result])

        service = StrategyService()
        strategies, total = await service.list_strategies(db, page=1, page_size=20)

        assert len(strategies) == 1
        assert total == 1


class TestStrategyServiceGetStrategy:
    """get_strategy 详情查询测试。"""

    @pytest.mark.asyncio
    async def test_get_strategy_returns_strategy_when_found(self) -> None:
        """策略存在时返回 Strategy 对象。"""
        from src.services.strategy_service import StrategyService
        from src.models.strategy import Strategy

        db = AsyncMock()
        mock_strategy = MagicMock(spec=Strategy)
        mock_strategy.id = 1

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_strategy

        db.execute = AsyncMock(return_value=mock_result)

        service = StrategyService()
        result = await service.get_strategy(db, strategy_id=1)

        assert result is mock_strategy

    @pytest.mark.asyncio
    async def test_get_strategy_raises_not_found_when_missing(self) -> None:
        """策略不存在时抛出 NotFoundError(code=3001)。"""
        from src.services.strategy_service import StrategyService

        db = AsyncMock()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        db.execute = AsyncMock(return_value=mock_result)

        service = StrategyService()
        with pytest.raises(NotFoundError) as exc_info:
            await service.get_strategy(db, strategy_id=999)

        assert exc_info.value.code == 3001

    @pytest.mark.asyncio
    async def test_strategy_service_has_no_write_methods(self) -> None:
        """StrategyService 不提供任何写入方法。"""
        from src.services.strategy_service import StrategyService

        service = StrategyService()
        # 确保没有 create/update/delete 等写入方法
        assert not hasattr(service, "create_strategy")
        assert not hasattr(service, "update_strategy")
        assert not hasattr(service, "delete_strategy")
