"""信号服务单元测试（任务 9.1）。

验证：
  - get_signals 优先读取 Redis，缓存未命中时回退至 DB
  - Redis 不可用时静默回退至 DB，记录 WARNING 日志
  - 响应必须包含 last_updated_at 字段
  - strategy_id 不存在时抛出 NotFoundError(code=3001)
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.exceptions import NotFoundError


def _make_mock_signal(
    id: int = 1,
    strategy_id: int = 1,
    pair: str = "BTC/USDT",
    direction: str = "buy",
    confidence_score: float | None = 0.85,
) -> MagicMock:
    """创建 mock TradingSignal 对象。"""
    from src.core.enums import SignalDirection

    signal = MagicMock()
    signal.id = id
    signal.strategy_id = strategy_id
    signal.pair = pair
    signal.direction = SignalDirection(direction)
    signal.confidence_score = confidence_score
    signal.signal_at = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
    signal.created_at = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
    return signal


class TestSignalServiceGetSignals:
    """SignalService.get_signals 测试。"""

    @pytest.mark.asyncio
    async def test_get_signals_returns_from_redis_cache_when_hit(self) -> None:
        """Redis 命中时，应从缓存返回信号数据和 last_updated_at。"""
        from src.services.signal_service import SignalService

        service = SignalService()
        mock_db = AsyncMock()

        # Redis 缓存数据
        import json

        cached_data = {
            "signals": [
                {
                    "id": 1,
                    "strategy_id": 1,
                    "pair": "BTC/USDT",
                    "direction": "buy",
                    "confidence_score": 0.85,
                    "signal_at": "2024-01-01T12:00:00+00:00",
                    "created_at": "2024-01-01T12:00:00+00:00",
                }
            ],
            "last_updated_at": "2024-01-01T12:00:00+00:00",
        }
        mock_redis = MagicMock()
        mock_redis.get.return_value = json.dumps(cached_data)

        # 策略存在
        strategy_result = MagicMock()
        strategy_result.scalar_one_or_none.return_value = MagicMock(id=1)
        mock_db.execute = AsyncMock(return_value=strategy_result)

        with patch("src.services.signal_service.get_redis_client", return_value=mock_redis):
            signals, last_updated_at = await service.get_signals(
                mock_db, strategy_id=1, limit=20
            )

        # 从缓存中读取
        assert len(signals) == 1
        assert isinstance(last_updated_at, datetime)
        mock_redis.get.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_signals_falls_back_to_db_when_cache_miss(self) -> None:
        """Redis 缓存未命中时，应回退至数据库查询。"""
        from src.services.signal_service import SignalService

        service = SignalService()
        mock_db = AsyncMock()

        mock_redis = MagicMock()
        mock_redis.get.return_value = None  # 缓存未命中

        # 策略存在
        strategy_result = MagicMock()
        strategy_result.scalar_one_or_none.return_value = MagicMock(id=1)

        # DB 信号
        db_signals = [_make_mock_signal(id=1)]
        signals_result = MagicMock()
        signals_result.scalars.return_value.all.return_value = db_signals

        mock_db.execute = AsyncMock(side_effect=[strategy_result, signals_result])

        with patch("src.services.signal_service.get_redis_client", return_value=mock_redis):
            signals, last_updated_at = await service.get_signals(
                mock_db, strategy_id=1, limit=20
            )

        assert len(signals) == 1
        assert isinstance(last_updated_at, datetime)

    @pytest.mark.asyncio
    async def test_get_signals_falls_back_to_db_when_redis_unavailable(self) -> None:
        """Redis 不可用时应静默回退至数据库，不暴露错误给调用方。"""
        from src.services.signal_service import SignalService

        service = SignalService()
        mock_db = AsyncMock()

        mock_redis = MagicMock()
        mock_redis.get.side_effect = Exception("Redis connection refused")

        # 策略存在
        strategy_result = MagicMock()
        strategy_result.scalar_one_or_none.return_value = MagicMock(id=1)

        # DB 信号
        db_signals = [_make_mock_signal(id=1)]
        signals_result = MagicMock()
        signals_result.scalars.return_value.all.return_value = db_signals

        mock_db.execute = AsyncMock(side_effect=[strategy_result, signals_result])

        with patch("src.services.signal_service.get_redis_client", return_value=mock_redis):
            # 不应抛出异常
            signals, last_updated_at = await service.get_signals(
                mock_db, strategy_id=1, limit=20
            )

        assert len(signals) == 1

    @pytest.mark.asyncio
    async def test_get_signals_raises_not_found_when_strategy_missing(self) -> None:
        """strategy_id 不存在时应抛出 NotFoundError(code=3001)。"""
        from src.services.signal_service import SignalService

        service = SignalService()
        mock_db = AsyncMock()

        mock_redis = MagicMock()
        mock_redis.get.return_value = None

        # 策略不存在
        strategy_result = MagicMock()
        strategy_result.scalar_one_or_none.return_value = None

        mock_db.execute = AsyncMock(return_value=strategy_result)

        with patch("src.services.signal_service.get_redis_client", return_value=mock_redis):
            with pytest.raises(NotFoundError) as exc_info:
                await service.get_signals(mock_db, strategy_id=999, limit=20)

        assert exc_info.value.code == 3001

    @pytest.mark.asyncio
    async def test_get_signals_returns_last_updated_at_from_db(self) -> None:
        """DB 回退时，last_updated_at 应来自最新信号的 signal_at 字段。"""
        from src.services.signal_service import SignalService

        service = SignalService()
        mock_db = AsyncMock()

        mock_redis = MagicMock()
        mock_redis.get.return_value = None

        strategy_result = MagicMock()
        strategy_result.scalar_one_or_none.return_value = MagicMock(id=1)

        signal_time = datetime(2024, 6, 15, 10, 30, tzinfo=timezone.utc)
        db_signal = _make_mock_signal(id=1)
        db_signal.signal_at = signal_time

        signals_result = MagicMock()
        signals_result.scalars.return_value.all.return_value = [db_signal]

        mock_db.execute = AsyncMock(side_effect=[strategy_result, signals_result])

        with patch("src.services.signal_service.get_redis_client", return_value=mock_redis):
            signals, last_updated_at = await service.get_signals(
                mock_db, strategy_id=1, limit=20
            )

        assert last_updated_at == signal_time

    @pytest.mark.asyncio
    async def test_get_signals_empty_db_returns_empty_list(self) -> None:
        """DB 无信号时返回空列表和当前时间。"""
        from src.services.signal_service import SignalService

        service = SignalService()
        mock_db = AsyncMock()

        mock_redis = MagicMock()
        mock_redis.get.return_value = None

        strategy_result = MagicMock()
        strategy_result.scalar_one_or_none.return_value = MagicMock(id=1)

        signals_result = MagicMock()
        signals_result.scalars.return_value.all.return_value = []

        mock_db.execute = AsyncMock(side_effect=[strategy_result, signals_result])

        with patch("src.services.signal_service.get_redis_client", return_value=mock_redis):
            signals, last_updated_at = await service.get_signals(
                mock_db, strategy_id=1, limit=20
            )

        assert signals == []
        assert isinstance(last_updated_at, datetime)
