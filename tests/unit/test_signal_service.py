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
    signal.timeframe = "1h"
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
            signals, last_updated_at = await service.get_signals(mock_db, strategy_id=1, limit=20)

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
            signals, last_updated_at = await service.get_signals(mock_db, strategy_id=1, limit=20)

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
            signals, _last_updated_at = await service.get_signals(mock_db, strategy_id=1, limit=20)

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

        from src.core.exceptions import NotFoundError

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
            _signals, last_updated_at = await service.get_signals(mock_db, strategy_id=1, limit=20)

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
            signals, last_updated_at = await service.get_signals(mock_db, strategy_id=1, limit=20)

        assert signals == []
        assert isinstance(last_updated_at, datetime)


class TestListSignals:
    """任务 8.4：测试 SignalService.list_signals 方法（需求 4.1, 4.5, 4.6, 4.7）。"""

    @pytest.mark.asyncio
    async def test_raises_not_found_when_strategy_missing(self) -> None:
        """strategy_id 不存在时抛出 NotFoundError(code=3001)（需求 4.5）。"""
        from src.services.signal_service import SignalService

        service = SignalService()

        mock_db = AsyncMock()
        strategy_result = MagicMock()
        strategy_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=strategy_result)

        from src.core.exceptions import NotFoundError

        with pytest.raises(NotFoundError):
            await service.list_signals(db=mock_db, strategy_id=9999)

    @pytest.mark.asyncio
    async def test_filter_by_pair_from_redis(self) -> None:
        """pair 过滤从 Redis 缓存中正确过滤（需求 4.1）。"""
        import json

        from src.services.signal_service import SignalService

        service = SignalService()
        now_iso = datetime.now(timezone.utc).isoformat()
        cache_data = {
            "signals": [
                {
                    "id": 1,
                    "strategy_id": 1,
                    "pair": "BTC/USDT",
                    "timeframe": "1h",
                    "direction": "buy",
                    "confidence_score": 0.8,
                    "signal_at": now_iso,
                    "created_at": now_iso,
                },
                {
                    "id": 2,
                    "strategy_id": 1,
                    "pair": "ETH/USDT",
                    "timeframe": "1h",
                    "direction": "hold",
                    "confidence_score": 0.0,
                    "signal_at": now_iso,
                    "created_at": now_iso,
                },
            ],
            "last_updated_at": now_iso,
        }

        mock_db = AsyncMock()
        strategy_result = MagicMock()
        strategy_result.scalar_one_or_none.return_value = MagicMock(id=1)
        mock_db.execute = AsyncMock(return_value=strategy_result)

        mock_redis = MagicMock()
        mock_redis.get = MagicMock(return_value=json.dumps(cache_data))

        with patch("src.services.signal_service.get_redis_client", return_value=mock_redis):
            signals, total, _last_updated_at = await service.list_signals(
                db=mock_db,
                strategy_id=1,
                pair="BTC/USDT",
            )

        # 过滤后只包含 BTC/USDT
        for s in signals:
            assert getattr(s, "pair", None) == "BTC/USDT"
        assert total == len(signals)

    @pytest.mark.asyncio
    async def test_filter_by_timeframe_from_redis(self) -> None:
        """timeframe 过滤从 Redis 缓存中正确过滤。"""
        import json

        from src.services.signal_service import SignalService

        service = SignalService()
        now_iso = datetime.now(timezone.utc).isoformat()
        cache_data = {
            "signals": [
                {
                    "id": 1,
                    "strategy_id": 1,
                    "pair": "BTC/USDT",
                    "timeframe": "1h",
                    "direction": "buy",
                    "confidence_score": 0.7,
                    "signal_at": now_iso,
                    "created_at": now_iso,
                },
                {
                    "id": 2,
                    "strategy_id": 1,
                    "pair": "BTC/USDT",
                    "timeframe": "4h",
                    "direction": "hold",
                    "confidence_score": 0.0,
                    "signal_at": now_iso,
                    "created_at": now_iso,
                },
            ],
            "last_updated_at": now_iso,
        }

        mock_db = AsyncMock()
        strategy_result = MagicMock()
        strategy_result.scalar_one_or_none.return_value = MagicMock(id=1)
        mock_db.execute = AsyncMock(return_value=strategy_result)

        mock_redis = MagicMock()
        mock_redis.get = MagicMock(return_value=json.dumps(cache_data))

        with patch("src.services.signal_service.get_redis_client", return_value=mock_redis):
            signals, _total, _last_updated_at = await service.list_signals(
                db=mock_db,
                strategy_id=1,
                timeframe="1h",
            )

        for s in signals:
            assert getattr(s, "timeframe", None) == "1h"

    @pytest.mark.asyncio
    async def test_pagination_page_size(self) -> None:
        """分页：page_size 限制返回数量（需求 4.6）。"""
        import json

        from src.services.signal_service import SignalService

        service = SignalService()
        now_iso = datetime.now(timezone.utc).isoformat()

        # 5 条信号，但 page_size=2
        signals_data = [
            {
                "id": i,
                "strategy_id": 1,
                "pair": "BTC/USDT",
                "timeframe": "1h",
                "direction": "buy",
                "confidence_score": 0.7,
                "signal_at": now_iso,
                "created_at": now_iso,
            }
            for i in range(1, 6)
        ]
        cache_data = {"signals": signals_data, "last_updated_at": now_iso}

        mock_db = AsyncMock()
        strategy_result = MagicMock()
        strategy_result.scalar_one_or_none.return_value = MagicMock(id=1)
        mock_db.execute = AsyncMock(return_value=strategy_result)

        mock_redis = MagicMock()
        mock_redis.get = MagicMock(return_value=json.dumps(cache_data))

        with patch("src.services.signal_service.get_redis_client", return_value=mock_redis):
            signals, total, _last_updated_at = await service.list_signals(
                db=mock_db,
                strategy_id=1,
                page=1,
                page_size=2,
            )

        assert len(signals) == 2
        assert total == 5  # 总数仍为 5

    @pytest.mark.asyncio
    async def test_redis_unavailable_falls_back_to_db(self) -> None:
        """Redis 不可用时降级回 DB 查询，不抛出异常（需求 4.7）。"""
        from src.services.signal_service import SignalService

        service = SignalService()

        mock_db = AsyncMock()
        strategy_result = MagicMock()
        strategy_result.scalar_one_or_none.return_value = MagicMock(id=1)

        count_result = MagicMock()
        count_result.scalar = MagicMock(return_value=0)

        signals_result = MagicMock()
        signals_result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))

        mock_db.execute = AsyncMock(side_effect=[strategy_result, count_result, signals_result])

        mock_redis = MagicMock()
        mock_redis.get = MagicMock(side_effect=Exception("Redis down"))

        with patch("src.services.signal_service.get_redis_client", return_value=mock_redis):
            signals, total, last_updated_at = await service.list_signals(
                db=mock_db,
                strategy_id=1,
            )

        assert isinstance(signals, list)
        assert isinstance(total, int)
        assert isinstance(last_updated_at, datetime)
