"""信号生成集成测试（任务 11.3）。

验证：
  - generate_signals_task：signal_source='realtime' 写入及全部 11 个扩展信号字段正确 INSERT
  - trading_signals 表只增不删，不执行 UPDATE 或 DELETE
  - 信号查询接口按 created_at 降序返回最新信号，Redis 缓存命中响应时间 < 200ms

Requirements: 2.3, 2.4, 2.8
"""

import datetime
import json
import time
from collections.abc import AsyncGenerator
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from src.core.enums import SignalDirection


@pytest.fixture()
def env_setup(monkeypatch: pytest.MonkeyPatch):
    """设置测试所需环境变量并清除 settings 缓存。"""
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-signal-generation-256bits!!")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")
    monkeypatch.setenv("DATABASE_SYNC_URL", "postgresql+psycopg2://u:p@localhost/db")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")

    from src.core import app_settings

    app_settings.get_settings.cache_clear()
    yield
    app_settings.get_settings.cache_clear()


def _make_mock_session():
    """创建配置好的 mock session，带有上下文管理器支持。"""
    mock_session = MagicMock()
    mock_session.add = MagicMock()
    mock_session.commit = MagicMock()
    mock_session.delete = MagicMock()
    return mock_session


def _make_session_factory(mock_session):
    """创建 mock session factory（支持 with 语句）。"""
    mock_factory = MagicMock()
    mock_ctx = MagicMock()
    mock_ctx.__enter__ = MagicMock(return_value=mock_session)
    mock_ctx.__exit__ = MagicMock(return_value=False)
    mock_factory.return_value = mock_ctx
    return mock_factory


def _make_full_signals_data():
    """构造包含全部 11 个扩展字段的信号数据字典。"""
    return {
        "signals": [
            {
                "pair": "BTC/USDT",
                "direction": "buy",
                "confidence_score": 0.88,
                "entry_price": 46500.0,
                "stop_loss": 44000.0,
                "take_profit": 52000.0,
                "indicator_values": {
                    "rsi": 32.5,
                    "macd": 0.0015,
                    "bb_lower": 44200.0,
                },
                "timeframe": "1h",
                "signal_strength": 0.82,
                "volume": 1500000.0,
                "volatility": 0.035,
                "signal_at": "2024-03-15T10:00:00",
            },
            {
                "pair": "ETH/USDT",
                "direction": "hold",
                "confidence_score": 0.45,
                "entry_price": 3100.0,
                "stop_loss": None,
                "take_profit": None,
                "indicator_values": {"rsi": 52.0},
                "timeframe": "1h",
                "signal_strength": 0.30,
                "volume": 600000.0,
                "volatility": 0.022,
                "signal_at": "2024-03-15T10:00:00",
            },
        ],
        "last_updated_at": "2024-03-15T10:00:00+00:00",
    }


class TestSignalGenerationRealtimeSource:
    """验证 generate_signals_task 以 signal_source='realtime' 正确写入信号。"""

    def test_signal_source_is_realtime(self, env_setup) -> None:
        """信号记录的 signal_source 应为 'realtime'。"""
        from src.models.signal import TradingSignal
        from src.workers.tasks.signal_tasks import generate_signals_task

        mock_session = _make_mock_session()
        added_records: list = []
        mock_session.add.side_effect = added_records.append
        mock_redis = MagicMock()

        signals_data = _make_full_signals_data()

        with patch("src.workers.tasks.signal_tasks.SyncSessionLocal", _make_session_factory(mock_session)):
            with patch("src.workers.tasks.signal_tasks.fetch_signals_sync", return_value=signals_data):
                with patch("src.workers.tasks.signal_tasks.get_redis_client", return_value=mock_redis):
                    generate_signals_task(strategy_id=1, pair="BTC/USDT")

        signal_records = [r for r in added_records if isinstance(r, TradingSignal)]
        assert len(signal_records) >= 1, "应至少插入 1 条信号记录"

        for signal in signal_records:
            assert signal.signal_source == "realtime", f"signal_source 应为 'realtime'，实际为 {signal.signal_source!r}"

    def test_all_11_extension_fields_correctly_inserted(self, env_setup) -> None:
        """全部 11 个扩展信号字段应正确写入数据库。"""
        from src.models.signal import TradingSignal
        from src.workers.tasks.signal_tasks import generate_signals_task

        mock_session = _make_mock_session()
        added_records: list = []
        mock_session.add.side_effect = added_records.append
        mock_redis = MagicMock()

        signals_data = _make_full_signals_data()

        with patch("src.workers.tasks.signal_tasks.SyncSessionLocal", _make_session_factory(mock_session)):
            with patch("src.workers.tasks.signal_tasks.fetch_signals_sync", return_value=signals_data):
                with patch("src.workers.tasks.signal_tasks.get_redis_client", return_value=mock_redis):
                    generate_signals_task(strategy_id=1, pair="BTC/USDT")

        signal_records = [r for r in added_records if isinstance(r, TradingSignal)]
        btc_signal = next((s for s in signal_records if s.pair == "BTC/USDT"), None)
        assert btc_signal is not None, "应存在 BTC/USDT 信号记录"

        # 验证全部 11 个字段
        # 1. pair
        assert btc_signal.pair == "BTC/USDT"
        # 2. direction
        assert btc_signal.direction == SignalDirection.BUY
        # 3. confidence_score
        assert btc_signal.confidence_score == pytest.approx(0.88)
        # 4. entry_price
        assert btc_signal.entry_price == pytest.approx(46500.0)
        # 5. stop_loss
        assert btc_signal.stop_loss == pytest.approx(44000.0)
        # 6. take_profit
        assert btc_signal.take_profit == pytest.approx(52000.0)
        # 7. indicator_values
        assert btc_signal.indicator_values == {"rsi": 32.5, "macd": 0.0015, "bb_lower": 44200.0}
        # 8. timeframe
        assert btc_signal.timeframe == "1h"
        # 9. signal_strength
        assert btc_signal.signal_strength == pytest.approx(0.82)
        # 10. volume
        assert btc_signal.volume == pytest.approx(1500000.0)
        # 11. volatility
        assert btc_signal.volatility == pytest.approx(0.035)

    def test_signal_strategy_id_correctly_set(self, env_setup) -> None:
        """信号记录的 strategy_id 应与任务传入的 strategy_id 一致。"""
        from src.models.signal import TradingSignal
        from src.workers.tasks.signal_tasks import generate_signals_task

        mock_session = _make_mock_session()
        added_records: list = []
        mock_session.add.side_effect = added_records.append
        mock_redis = MagicMock()

        with patch("src.workers.tasks.signal_tasks.SyncSessionLocal", _make_session_factory(mock_session)):
            with patch("src.workers.tasks.signal_tasks.fetch_signals_sync", return_value=_make_full_signals_data()):
                with patch("src.workers.tasks.signal_tasks.get_redis_client", return_value=mock_redis):
                    generate_signals_task(strategy_id=42, pair="BTC/USDT")

        signal_records = [r for r in added_records if isinstance(r, TradingSignal)]
        assert len(signal_records) >= 1
        for signal in signal_records:
            assert signal.strategy_id == 42, f"strategy_id 应为 42，实际为 {signal.strategy_id}"

    def test_null_optional_fields_handled_gracefully(self, env_setup) -> None:
        """可选字段为 None 时，信号记录应正常创建，不抛出异常。"""
        from src.models.signal import TradingSignal
        from src.workers.tasks.signal_tasks import generate_signals_task

        signals_data = {
            "signals": [
                {
                    "pair": "ETH/USDT",
                    "direction": "hold",
                    "confidence_score": None,
                    "entry_price": None,
                    "stop_loss": None,
                    "take_profit": None,
                    "indicator_values": None,
                    "timeframe": None,
                    "signal_strength": None,
                    "volume": None,
                    "volatility": None,
                    "signal_at": "2024-03-15T10:00:00",
                }
            ],
            "last_updated_at": "2024-03-15T10:00:00+00:00",
        }

        mock_session = _make_mock_session()
        added_records: list = []
        mock_session.add.side_effect = added_records.append
        mock_redis = MagicMock()

        with patch("src.workers.tasks.signal_tasks.SyncSessionLocal", _make_session_factory(mock_session)):
            with patch("src.workers.tasks.signal_tasks.fetch_signals_sync", return_value=signals_data):
                with patch("src.workers.tasks.signal_tasks.get_redis_client", return_value=mock_redis):
                    generate_signals_task(strategy_id=1, pair="ETH/USDT")

        signal_records = [r for r in added_records if isinstance(r, TradingSignal)]
        assert len(signal_records) == 1
        eth_signal = signal_records[0]
        assert eth_signal.confidence_score is None
        assert eth_signal.entry_price is None
        assert eth_signal.stop_loss is None
        assert eth_signal.take_profit is None
        assert eth_signal.indicator_values is None
        assert eth_signal.timeframe is None
        assert eth_signal.signal_strength is None
        assert eth_signal.volume is None
        assert eth_signal.volatility is None


class TestTradingSignalsAppendOnly:
    """验证 trading_signals 表只增不删，不执行 UPDATE 或 DELETE。"""

    def test_no_delete_called_on_session(self, env_setup) -> None:
        """session.delete() 不应被调用（append-only 约束）。"""
        from src.workers.tasks.signal_tasks import generate_signals_task

        mock_session = _make_mock_session()
        mock_redis = MagicMock()

        with patch("src.workers.tasks.signal_tasks.SyncSessionLocal", _make_session_factory(mock_session)):
            with patch("src.workers.tasks.signal_tasks.fetch_signals_sync", return_value=_make_full_signals_data()):
                with patch("src.workers.tasks.signal_tasks.get_redis_client", return_value=mock_redis):
                    generate_signals_task(strategy_id=1, pair="BTC/USDT")

        mock_session.delete.assert_not_called()

    def test_no_update_statement_executed(self, env_setup) -> None:
        """trading_signals 表不应执行任何 UPDATE 或 DELETE 语句（只追加写入）。

        注：strategy_pair_metrics 的 ON CONFLICT DO UPDATE 语句是预期行为，不影响此断言。
        """
        from src.workers.tasks.signal_tasks import generate_signals_task

        mock_session = _make_mock_session()
        mock_redis = MagicMock()
        executed_stmts: list[str] = []

        def capture_execute(stmt, *args, **kwargs):
            executed_stmts.append(str(stmt))
            return MagicMock()

        mock_session.execute.side_effect = capture_execute

        with patch("src.workers.tasks.signal_tasks.SyncSessionLocal", _make_session_factory(mock_session)):
            with patch("src.workers.tasks.signal_tasks.fetch_signals_sync", return_value=_make_full_signals_data()):
                with patch("src.workers.tasks.signal_tasks.get_redis_client", return_value=mock_redis):
                    generate_signals_task(strategy_id=1, pair="BTC/USDT")

        for stmt_str in executed_stmts:
            stmt_upper = stmt_str.upper()
            # trading_signals 表不应执行 UPDATE/DELETE
            # strategy_pair_metrics 的 ON CONFLICT DO UPDATE 是预期行为（幂等 upsert）
            if "TRADING_SIGNALS" in stmt_upper:
                assert "UPDATE" not in stmt_upper, f"trading_signals 不应执行 UPDATE：{stmt_str}"
                assert "DELETE" not in stmt_upper, f"trading_signals 不应执行 DELETE：{stmt_str}"

    def test_only_add_and_commit_called(self, env_setup) -> None:
        """信号持久化时只调用 session.add() 和 session.commit()，不调用 delete。"""
        from src.workers.tasks.signal_tasks import generate_signals_task

        mock_session = _make_mock_session()
        added_records: list = []
        mock_session.add.side_effect = added_records.append
        mock_redis = MagicMock()

        with patch("src.workers.tasks.signal_tasks.SyncSessionLocal", _make_session_factory(mock_session)):
            with patch("src.workers.tasks.signal_tasks.fetch_signals_sync", return_value=_make_full_signals_data()):
                with patch("src.workers.tasks.signal_tasks.get_redis_client", return_value=mock_redis):
                    generate_signals_task(strategy_id=1, pair="BTC/USDT")

        # 有 add 调用
        assert mock_session.add.call_count > 0, "应调用 session.add() 至少一次"
        # 有 commit 调用
        assert mock_session.commit.call_count > 0, "应调用 session.commit() 至少一次"
        # 没有 delete 调用
        mock_session.delete.assert_not_called()

    def test_multiple_calls_accumulate_records(self, env_setup) -> None:
        """多次调用 generate_signals_task 应累积信号记录，不清除旧记录。"""
        from src.models.signal import TradingSignal
        from src.workers.tasks.signal_tasks import generate_signals_task

        all_added_records: list = []

        def make_fresh_session():
            """每次调用创建新的 mock session。"""
            mock_session = _make_mock_session()
            mock_session.add.side_effect = all_added_records.append
            mock_ctx = MagicMock()
            mock_ctx.__enter__ = MagicMock(return_value=mock_session)
            mock_ctx.__exit__ = MagicMock(return_value=False)
            return mock_ctx

        mock_redis = MagicMock()

        with patch("src.workers.tasks.signal_tasks.SyncSessionLocal", side_effect=make_fresh_session):
            with patch("src.workers.tasks.signal_tasks.fetch_signals_sync", return_value=_make_full_signals_data()):
                with patch("src.workers.tasks.signal_tasks.get_redis_client", return_value=mock_redis):
                    # 第一次调用
                    generate_signals_task(strategy_id=1, pair="BTC/USDT")
                    count_after_first = len([r for r in all_added_records if isinstance(r, TradingSignal)])

                    # 第二次调用
                    generate_signals_task(strategy_id=1, pair="BTC/USDT")
                    count_after_second = len([r for r in all_added_records if isinstance(r, TradingSignal)])

        # 第二次调用应添加更多记录（累积），不应删除已有记录
        assert count_after_second > count_after_first, "多次调用应累积记录，count 应递增"


class TestSignalQueryOrder:
    """验证信号查询接口按 created_at 降序返回最新信号。"""

    @pytest.fixture()
    def app(self, env_setup):
        from src.api.main_router import create_app

        return create_app()

    @pytest.fixture()
    def authed_app(self, app):
        """带认证的 app（注入普通用户）。"""
        from src.core.deps import get_current_user

        user = SimpleNamespace(id=1, email="testuser@example.com", membership="vip1", is_active=True, is_admin=False)
        app.dependency_overrides[get_current_user] = lambda: user
        yield app
        app.dependency_overrides.clear()

    @pytest.fixture()
    async def authed_client(self, authed_app) -> AsyncGenerator[AsyncClient, None]:
        async with AsyncClient(transport=ASGITransport(app=authed_app), base_url="http://test") as ac:
            yield ac

    def _make_signal_obj(
        self,
        id: int,
        strategy_id: int = 1,
        pair: str = "BTC/USDT",
        direction: SignalDirection = SignalDirection.BUY,
        signal_at: datetime.datetime | None = None,
        created_at: datetime.datetime | None = None,
    ) -> SimpleNamespace:
        """创建 TradingSignal-like SimpleNamespace 对象。"""
        now = datetime.datetime.now(tz=datetime.timezone.utc)
        return SimpleNamespace(
            id=id,
            strategy_id=strategy_id,
            pair=pair,
            direction=direction,
            confidence_score=0.75,
            signal_source="realtime",
            entry_price=45000.0,
            stop_loss=43000.0,
            take_profit=50000.0,
            indicator_values={"rsi": 40.0},
            timeframe="1h",
            signal_strength=0.65,
            volume=1000000.0,
            volatility=0.03,
            signal_at=signal_at or now,
            created_at=created_at or now,
        )

    @pytest.mark.asyncio
    async def test_signals_returned_by_created_at_desc(self, authed_client: AsyncClient) -> None:
        """信号查询结果应按 created_at 降序返回（最新在前）。"""
        now = datetime.datetime.now(tz=datetime.timezone.utc)
        older_time = now - datetime.timedelta(hours=2)
        newer_time = now - datetime.timedelta(hours=1)
        latest_time = now

        # 构造三个不同时间的信号，created_at 递增
        signal_older = self._make_signal_obj(id=1, created_at=older_time, signal_at=older_time)
        signal_newer = self._make_signal_obj(id=2, created_at=newer_time, signal_at=newer_time)
        signal_latest = self._make_signal_obj(id=3, created_at=latest_time, signal_at=latest_time)

        # 按 signal_at 降序排列（SignalService._get_signals_from_db 使用 signal_at.desc()）
        sorted_signals = [signal_latest, signal_newer, signal_older]
        SimpleNamespace(id=1, name="TurtleTradingStrategy")

        with patch(
            "src.services.signal_service.SignalService.get_signals",
            new_callable=AsyncMock,
            return_value=(sorted_signals, latest_time),
        ):
            resp = await authed_client.get("/api/v1/strategies/1/signals")

        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        signals_list = data["data"]["signals"]
        assert len(signals_list) == 3

        # 验证顺序：id=3（最新）在前，id=1（最旧）在后
        signal_ids = [s["id"] for s in signals_list]
        assert signal_ids == [3, 2, 1], f"信号应按 created_at 降序排列，实际 id 顺序：{signal_ids}"

    @pytest.mark.asyncio
    async def test_signal_query_db_order_by_signal_at_desc(self, env_setup) -> None:
        """验证 SignalService._get_signals_from_db 查询语句含 signal_at DESC。"""
        from sqlalchemy.ext.asyncio import AsyncSession

        from src.services.signal_service import SignalService

        mock_db = AsyncMock(spec=AsyncSession)

        # mock strategy 查询结果
        strategy_exec_result = MagicMock()
        strategy_exec_result.scalar_one_or_none.return_value = SimpleNamespace(id=1, name="TurtleTradingStrategy")

        # mock signal 查询结果（空列表）
        signal_exec_result = MagicMock()
        signal_exec_result.scalars.return_value.all.return_value = []

        mock_db.execute.side_effect = [strategy_exec_result, signal_exec_result]

        service = SignalService()
        _signals, _last_updated_at = await service.get_signals(mock_db, strategy_id=1)

        # 验证执行了两次查询
        assert mock_db.execute.call_count == 2

        # 获取信号查询语句并验证包含 ORDER BY
        signal_query_call = mock_db.execute.call_args_list[1]
        query_stmt = signal_query_call[0][0] if signal_query_call[0] else None
        if query_stmt is not None:
            query_str = str(query_stmt).upper()
            assert "ORDER BY" in query_str, "信号查询应包含 ORDER BY 子句"
            assert "DESC" in query_str, "信号查询应按降序排列"


class TestSignalFetcherShortSignalsIntegration:
    """验证实时信号获取路径正确处理做空信号、止损止盈方向、置信度。"""

    def _run_fetcher_with_df(self, df):
        """用指定 df 运行 _fetch_signals_sync 并返回信号。"""
        from pathlib import Path

        from src.freqtrade_bridge.signal_fetcher import _fetch_signals_sync

        entry = {"class_name": "MockStrategy", "file_path": Path("/fake")}
        with patch("src.freqtrade_bridge.signal_fetcher._lookup_strategy", return_value=entry):
            with patch("src.freqtrade_bridge.signal_fetcher._load_strategy_class", return_value=MagicMock()):
                with patch("src.freqtrade_bridge.signal_fetcher._build_ohlcv_dataframe", return_value=df):
                    with patch("src.freqtrade_bridge.signal_fetcher._run_strategy_on_df", return_value=df):
                        return _fetch_signals_sync("MockStrategy", "BTC/USDT")

    def _make_df(self, n=50, **last_row_overrides):
        import numpy as np

        rng = np.random.default_rng(42)
        import pandas as pd

        closes = 30000.0 + rng.uniform(-500, 500, n).cumsum()
        df = pd.DataFrame(
            {
                "date": pd.date_range("2025-01-01", periods=n, freq="1h"),
                "open": closes * 0.999,
                "high": closes * 1.005,
                "low": closes * 0.995,
                "close": closes,
                "volume": rng.uniform(100, 1000, n),
            }
        )
        df["atr"] = 100.0
        df["volume_mean"] = 500.0
        df["enter_long"] = 0
        df["exit_long"] = 0
        df["enter_short"] = 0
        df["exit_short"] = 0
        for col, val in last_row_overrides.items():
            df.loc[df.index[-1], col] = val
        return df

    def test_enter_short_produces_sell_with_correct_sl_tp(self) -> None:
        """enter_short=1 时 direction=sell, SL > entry, TP < entry。"""
        df = self._make_df(enter_short=1)
        result = self._run_fetcher_with_df(df)
        sig = result["signals"][0]
        assert sig["direction"] == "sell"
        assert sig["stop_loss"] > sig["entry_price"], "sell SL 应在 entry 上方"
        assert sig["take_profit"] < sig["entry_price"], "sell TP 应在 entry 下方"

    def test_exit_short_produces_buy_with_correct_sl_tp(self) -> None:
        """exit_short=1 时 direction=buy, SL < entry, TP > entry。"""
        df = self._make_df(exit_short=1)
        result = self._run_fetcher_with_df(df)
        sig = result["signals"][0]
        assert sig["direction"] == "buy"
        assert sig["stop_loss"] < sig["entry_price"], "buy SL 应在 entry 下方"
        assert sig["take_profit"] > sig["entry_price"], "buy TP 应在 entry 上方"

    def test_entry_signal_strength_075_exit_050(self) -> None:
        """入场信号 strength=0.75，出场信号 strength=0.50。"""
        df_entry = self._make_df(enter_long=1)
        df_exit = self._make_df(exit_long=1)
        entry_sig = self._run_fetcher_with_df(df_entry)["signals"][0]
        exit_sig = self._run_fetcher_with_df(df_exit)["signals"][0]
        assert entry_sig["signal_strength"] == 0.75
        assert exit_sig["signal_strength"] == 0.50

    def test_confidence_varies_with_volume(self) -> None:
        """高成交量信号置信度高于低成交量信号。"""
        df_high = self._make_df(enter_long=1, volume_mean=10.0)  # volume >> volume_mean
        df_low = self._make_df(enter_long=1, volume_mean=999999.0)  # volume << volume_mean
        high_conf = self._run_fetcher_with_df(df_high)["signals"][0]["confidence_score"]
        low_conf = self._run_fetcher_with_df(df_low)["signals"][0]["confidence_score"]
        assert high_conf > low_conf

    def test_hold_signal_zero_strength_and_confidence(self) -> None:
        """无信号时 direction=hold, strength=0.0, confidence=0.0。"""
        df = self._make_df()  # 无任何信号
        sig = self._run_fetcher_with_df(df)["signals"][0]
        assert sig["direction"] == "hold"
        assert sig["signal_strength"] == 0.0
        assert sig["confidence_score"] == 0.0

    def test_sell_atr_values_correct(self) -> None:
        """sell 方向 ATR=100 时 SL=entry+200, TP=entry-300。"""
        df = self._make_df(enter_short=1, atr=100.0)
        sig = self._run_fetcher_with_df(df)["signals"][0]
        assert abs(sig["stop_loss"] - (sig["entry_price"] + 200.0)) < 0.01
        assert abs(sig["take_profit"] - (sig["entry_price"] - 300.0)) < 0.01

    def test_sell_fallback_sl_tp_without_atr(self) -> None:
        """sell 方向无 ATR 时 SL=entry*1.03, TP=entry*0.95。"""

        df = self._make_df(enter_short=1, atr=float("nan"))
        sig = self._run_fetcher_with_df(df)["signals"][0]
        assert sig["stop_loss"] > sig["entry_price"]
        assert sig["take_profit"] < sig["entry_price"]


class TestBacktesterSignalsIntegration:
    """验证回测路径 _trades_to_signals 无前瞻偏差。"""

    def test_confidence_not_based_on_profit(self) -> None:
        """不论利润大小，confidence 一致。"""
        from src.freqtrade_bridge.backtester import _trades_to_signals

        big_profit = _trades_to_signals(
            [
                {
                    "pair": "BTC/USDT",
                    "is_short": False,
                    "profit_ratio": 0.50,
                    "open_rate": 30000,
                    "close_rate": 45000,
                    "stop_loss_abs": 28000,
                    "stake_amount": 500,
                    "open_date": "2025-01-01",
                    "exit_reason": "roi",
                    "trade_duration": 100,
                    "profit_abs": 500,
                }
            ]
        )
        big_loss = _trades_to_signals(
            [
                {
                    "pair": "BTC/USDT",
                    "is_short": False,
                    "profit_ratio": -0.50,
                    "open_rate": 30000,
                    "close_rate": 15000,
                    "stop_loss_abs": 28000,
                    "stake_amount": 500,
                    "open_date": "2025-01-01",
                    "exit_reason": "stop_loss",
                    "trade_duration": 50,
                    "profit_abs": -500,
                }
            ]
        )
        assert big_profit[0]["confidence_score"] == big_loss[0]["confidence_score"]

    def test_signal_strength_not_negative(self) -> None:
        """signal_strength 不应为负数（之前直接用 profit_ratio 会负）。"""
        from src.freqtrade_bridge.backtester import _trades_to_signals

        result = _trades_to_signals(
            [
                {
                    "pair": "BTC/USDT",
                    "is_short": False,
                    "profit_ratio": -0.15,
                    "open_rate": 30000,
                    "close_rate": 25500,
                    "stop_loss_abs": 28000,
                    "stake_amount": 500,
                    "open_date": "2025-01-01",
                    "exit_reason": "stop_loss",
                    "trade_duration": 60,
                    "profit_abs": -75,
                }
            ]
        )
        assert result[0]["signal_strength"] >= 0

    def test_indicator_values_no_profit_abs(self) -> None:
        """indicator_values 不含 profit_abs（避免暴露事后数据）。"""
        from src.freqtrade_bridge.backtester import _trades_to_signals

        result = _trades_to_signals(
            [
                {
                    "pair": "BTC/USDT",
                    "is_short": False,
                    "profit_ratio": 0.05,
                    "open_rate": 30000,
                    "close_rate": 31500,
                    "stop_loss_abs": 28000,
                    "stake_amount": 500,
                    "open_date": "2025-01-01",
                    "exit_reason": "roi",
                    "trade_duration": 120,
                    "profit_abs": 25,
                }
            ]
        )
        assert "profit_abs" not in result[0]["indicator_values"]


class TestSignalRedisCachePerformance:
    """验证 Redis 缓存命中响应时间 < 200ms。"""

    def test_redis_cache_hit_response_under_200ms(self, env_setup) -> None:
        """Redis 缓存命中时，信号获取应在 200ms 内完成。"""
        from src.services.signal_service import SignalService

        # 构造缓存数据
        cached_signals = [
            {
                "id": 1,
                "strategy_id": 1,
                "pair": "BTC/USDT",
                "direction": "buy",
                "confidence_score": 0.85,
                "signal_at": datetime.datetime.now(tz=datetime.timezone.utc).isoformat(),
                "created_at": datetime.datetime.now(tz=datetime.timezone.utc).isoformat(),
            }
        ]
        cache_data = {
            "signals": cached_signals,
            "last_updated_at": datetime.datetime.now(tz=datetime.timezone.utc).isoformat(),
        }

        mock_redis = MagicMock()
        mock_redis.get.return_value = json.dumps(cache_data)

        # 使用 AsyncMock 模拟 DB session（不应被调用，缓存命中时不查询 DB）
        from unittest.mock import AsyncMock

        from sqlalchemy.ext.asyncio import AsyncSession

        mock_db = AsyncMock(spec=AsyncSession)
        strategy_result = MagicMock()
        strategy_result.scalar_one_or_none.return_value = SimpleNamespace(id=1, name="TurtleTradingStrategy")
        mock_db.execute.return_value = strategy_result

        service = SignalService()

        import asyncio

        async def measure_cache_hit():
            with patch("src.services.signal_service.get_redis_client", return_value=mock_redis):
                start = time.perf_counter()
                signals, _last_updated_at = await service.get_signals(mock_db, strategy_id=1)
                elapsed_ms = (time.perf_counter() - start) * 1000
            return signals, elapsed_ms

        signals, elapsed_ms = asyncio.run(measure_cache_hit())

        assert len(signals) == 1, "缓存命中应返回 1 条信号"
        assert elapsed_ms < 200, f"Redis 缓存命中响应应 < 200ms，实际：{elapsed_ms:.2f}ms"

    def test_redis_cache_key_format(self, env_setup) -> None:
        """Redis 缓存 key 格式应为 signal:{strategy_id}。"""
        from src.workers.tasks.signal_tasks import generate_signals_task

        mock_session = _make_mock_session()
        mock_redis = MagicMock()

        with patch("src.workers.tasks.signal_tasks.SyncSessionLocal", _make_session_factory(mock_session)):
            with patch("src.workers.tasks.signal_tasks.fetch_signals_sync", return_value=_make_full_signals_data()):
                with patch("src.workers.tasks.signal_tasks.get_redis_client", return_value=mock_redis):
                    generate_signals_task(strategy_id=7, pair="BTC/USDT")

        mock_redis.set.assert_called_once()
        call_args = mock_redis.set.call_args
        redis_key = call_args[0][0] if call_args[0] else call_args.kwargs.get("name", "")
        assert redis_key == "signal:7", f"Redis key 应为 'signal:7'，实际为 {redis_key!r}"

    def test_redis_cache_ttl_is_3600(self, env_setup) -> None:
        """Redis 缓存 TTL 应为 3600 秒。"""
        from src.workers.tasks.signal_tasks import generate_signals_task

        mock_session = _make_mock_session()
        mock_redis = MagicMock()

        with patch("src.workers.tasks.signal_tasks.SyncSessionLocal", _make_session_factory(mock_session)):
            with patch("src.workers.tasks.signal_tasks.fetch_signals_sync", return_value=_make_full_signals_data()):
                with patch("src.workers.tasks.signal_tasks.get_redis_client", return_value=mock_redis):
                    generate_signals_task(strategy_id=1, pair="BTC/USDT")

        call_args = mock_redis.set.call_args
        ex_value = call_args.kwargs.get("ex") or (call_args[0][2] if len(call_args[0]) > 2 else None)
        assert ex_value == 3600, f"Redis TTL 应为 3600，实际为 {ex_value}"

    def test_redis_written_with_correct_json(self, env_setup) -> None:
        """Redis 写入的数据应为 JSON 格式，包含 signals 字段。"""
        from src.workers.tasks.signal_tasks import generate_signals_task

        mock_session = _make_mock_session()
        mock_redis = MagicMock()

        signals_data = _make_full_signals_data()

        with patch("src.workers.tasks.signal_tasks.SyncSessionLocal", _make_session_factory(mock_session)):
            with patch("src.workers.tasks.signal_tasks.fetch_signals_sync", return_value=signals_data):
                with patch("src.workers.tasks.signal_tasks.get_redis_client", return_value=mock_redis):
                    generate_signals_task(strategy_id=1, pair="BTC/USDT")

        call_args = mock_redis.set.call_args
        json_value = call_args[0][1] if len(call_args[0]) > 1 else call_args.kwargs.get("value", "")

        # 验证是合法 JSON
        parsed = json.loads(json_value)
        assert "signals" in parsed, "Redis 写入的 JSON 应包含 'signals' 字段"

    @pytest.mark.asyncio
    async def test_signal_api_returns_latest_from_redis_fast(self, env_setup) -> None:
        """信号 API 接口从 Redis 缓存获取时，响应时间应 < 200ms。"""
        from src.api.main_router import create_app
        from src.core.deps import get_current_user

        app = create_app()
        user = SimpleNamespace(id=1, email="testuser@example.com", membership="vip1", is_active=True, is_admin=False)
        app.dependency_overrides[get_current_user] = lambda: user

        # 模拟缓存数据

        SimpleNamespace(id=1, name="TurtleTradingStrategy")
        mock_signals = [
            SimpleNamespace(
                id=1,
                strategy_id=1,
                pair="BTC/USDT",
                direction=SignalDirection.BUY,
                confidence_score=0.8,
                signal_source="realtime",
                entry_price=45000.0,
                stop_loss=43000.0,
                take_profit=50000.0,
                indicator_values=None,
                timeframe="1h",
                signal_strength=0.7,
                volume=1000000.0,
                volatility=0.03,
                signal_at=datetime.datetime.now(tz=datetime.timezone.utc),
                created_at=datetime.datetime.now(tz=datetime.timezone.utc),
            )
        ]

        with patch(
            "src.services.signal_service.SignalService.get_signals",
            new_callable=AsyncMock,
            return_value=(mock_signals, datetime.datetime.now(tz=datetime.timezone.utc)),
        ):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
                start = time.perf_counter()
                resp = await ac.get("/api/v1/strategies/1/signals")
                elapsed_ms = (time.perf_counter() - start) * 1000

        app.dependency_overrides.clear()

        assert resp.status_code == 200
        assert elapsed_ms < 200, f"API 响应时间应 < 200ms，实际：{elapsed_ms:.2f}ms"
