"""backtester._trades_to_signals 单元测试。

验证：
  - 做多/做空 trade 映射为正确的 direction
  - confidence_score 固定为 0.60（不使用事后利润，无前瞻偏差）
  - signal_strength 固定为 0.75（入场信号）
  - indicator_values 不包含 profit_abs（避免前瞻偏差）
  - 空 trades 列表返回空信号列表
  - 各字段正确映射 freqtrade trade 结构
"""


from src.freqtrade_bridge.backtester import _trades_to_signals


def _make_trade(
    pair: str = "BTC/USDT",
    is_short: bool = False,
    profit_ratio: float = 0.05,
    open_rate: float = 30000.0,
    close_rate: float = 31500.0,
    stop_loss_abs: float = 29100.0,
    stake_amount: float = 500.0,
    open_date: str = "2024-06-01T12:00:00",
    exit_reason: str = "roi",
    trade_duration: int = 120,
    profit_abs: float = 25.0,
) -> dict:
    """构建一条模拟 freqtrade trade 记录。"""
    return {
        "pair": pair,
        "is_short": is_short,
        "profit_ratio": profit_ratio,
        "open_rate": open_rate,
        "close_rate": close_rate,
        "stop_loss_abs": stop_loss_abs,
        "stake_amount": stake_amount,
        "open_date": open_date,
        "exit_reason": exit_reason,
        "trade_duration": trade_duration,
        "profit_abs": profit_abs,
    }


class TestTradesToSignalsDirection:
    """trade 方向映射测试。"""

    def test_long_trade_produces_buy_direction(self) -> None:
        signals = _trades_to_signals([_make_trade(is_short=False)])
        assert signals[0]["direction"] == "buy"

    def test_short_trade_produces_sell_direction(self) -> None:
        signals = _trades_to_signals([_make_trade(is_short=True)])
        assert signals[0]["direction"] == "sell"


class TestTradesToSignalsNoLookAheadBias:
    """确保 confidence_score 和 signal_strength 无前瞻偏差。"""

    def test_confidence_fixed_060(self) -> None:
        """不管利润正负，confidence_score 固定 0.60。"""
        profitable = _trades_to_signals([_make_trade(profit_ratio=0.10)])
        losing = _trades_to_signals([_make_trade(profit_ratio=-0.10)])

        assert profitable[0]["confidence_score"] == 0.60
        assert losing[0]["confidence_score"] == 0.60

    def test_signal_strength_fixed_075(self) -> None:
        """不管利润正负，signal_strength 固定 0.75。"""
        profitable = _trades_to_signals([_make_trade(profit_ratio=0.10)])
        losing = _trades_to_signals([_make_trade(profit_ratio=-0.05)])

        assert profitable[0]["signal_strength"] == 0.75
        assert losing[0]["signal_strength"] == 0.75

    def test_indicator_values_no_profit_abs(self) -> None:
        """indicator_values 不应包含 profit_abs（事后数据）。"""
        signals = _trades_to_signals([_make_trade(profit_abs=100.0)])
        assert "profit_abs" not in signals[0]["indicator_values"]


class TestTradesToSignalsFieldMapping:
    """字段正确映射测试。"""

    def test_entry_price_maps_from_open_rate(self) -> None:
        signals = _trades_to_signals([_make_trade(open_rate=42000.0)])
        assert signals[0]["entry_price"] == 42000.0

    def test_stop_loss_maps_from_stop_loss_abs(self) -> None:
        signals = _trades_to_signals([_make_trade(stop_loss_abs=28000.0)])
        assert signals[0]["stop_loss"] == 28000.0

    def test_take_profit_maps_from_close_rate(self) -> None:
        signals = _trades_to_signals([_make_trade(close_rate=35000.0)])
        assert signals[0]["take_profit"] == 35000.0

    def test_volume_maps_from_stake_amount(self) -> None:
        signals = _trades_to_signals([_make_trade(stake_amount=1000.0)])
        assert signals[0]["volume"] == 1000.0

    def test_signal_at_maps_from_open_date(self) -> None:
        signals = _trades_to_signals([_make_trade(open_date="2025-03-01T08:00:00")])
        assert signals[0]["signal_at"] == "2025-03-01T08:00:00"

    def test_pair_maps_from_trade(self) -> None:
        signals = _trades_to_signals([_make_trade(pair="ETH/USDT")])
        assert signals[0]["pair"] == "ETH/USDT"

    def test_indicator_values_contains_exit_reason_and_duration(self) -> None:
        signals = _trades_to_signals([_make_trade(exit_reason="stop_loss", trade_duration=300)])
        iv = signals[0]["indicator_values"]
        assert iv["exit_reason"] == "stop_loss"
        assert iv["trade_duration"] == 300


class TestTradesToSignalsEdgeCases:
    """边界情况测试。"""

    def test_empty_trades_returns_empty_list(self) -> None:
        assert _trades_to_signals([]) == []

    def test_multiple_trades_produce_multiple_signals(self) -> None:
        trades = [_make_trade(pair="BTC/USDT"), _make_trade(pair="ETH/USDT")]
        signals = _trades_to_signals(trades)
        assert len(signals) == 2
        assert signals[0]["pair"] == "BTC/USDT"
        assert signals[1]["pair"] == "ETH/USDT"
