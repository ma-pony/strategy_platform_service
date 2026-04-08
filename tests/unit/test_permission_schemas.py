"""字段级权限序列化单元测试（任务 4.1 / 4.2）。

验证 StrategyRead、BacktestResultRead、SignalRead 在不同会员等级下的字段可见性：
  - 匿名 (None)：仅返回基础公开字段
  - Free：额外返回中级指标字段
  - VIP1/VIP2：返回全部高级字段（含 sharpe_ratio、win_rate、confidence_score）
"""

import pytest

from src.core.enums import MembershipTier
from src.schemas.strategy import BacktestResultRead, SignalRead, StrategyRead


class TestStrategyReadAnonymous:
    """匿名用户访问 StrategyRead 时仅返回基础可见字段。"""

    def test_anonymous_sees_base_fields(self) -> None:
        schema = StrategyRead(
            id=1,
            name="RSI Strategy",
            description="RSI 均值回归",
            pairs=["BTC/USDT"],
            strategy_type="mean_reversion",
            trade_count=100,
            max_drawdown=0.15,
            sharpe_ratio=1.5,
            win_rate=0.6,
        )
        result = schema.model_dump(context={"membership": None})
        assert result["id"] == 1
        assert result["name"] == "RSI Strategy"
        assert result["description"] == "RSI 均值回归"
        assert result["pairs"] == ["BTC/USDT"]
        assert result["strategy_type"] == "mean_reversion"

    def test_anonymous_sees_ranking_metrics(self) -> None:
        """首页榜单的 4 个核心指标对匿名用户可见（付费墙下移到 BacktestResultRead）。"""
        schema = StrategyRead(
            id=1,
            name="RSI Strategy",
            description="RSI 均值回归",
            pairs=["BTC/USDT"],
            strategy_type="mean_reversion",
            trade_count=100,
            max_drawdown=0.15,
            sharpe_ratio=1.5,
            win_rate=0.6,
        )
        result = schema.model_dump(context={"membership": None})
        assert result["trade_count"] == 100
        assert result["max_drawdown"] == pytest.approx(0.15)
        assert result["sharpe_ratio"] == pytest.approx(1.5)
        assert result["win_rate"] == pytest.approx(0.6)

    def test_no_context_treated_as_anonymous(self) -> None:
        """未提供 context 时以匿名等级处理，但榜单字段仍可见。"""
        schema = StrategyRead(
            id=1,
            name="RSI Strategy",
            description="desc",
            pairs=[],
            strategy_type="type",
            sharpe_ratio=2.0,
            win_rate=0.7,
        )
        result = schema.model_dump()
        assert result["sharpe_ratio"] == pytest.approx(2.0)
        assert result["win_rate"] == pytest.approx(0.7)


class TestStrategyReadFree:
    """Free 用户访问 StrategyRead 时的字段可见性（现已与匿名一致，榜单字段全可见）。"""

    def test_free_user_sees_trade_count_and_max_drawdown(self) -> None:
        schema = StrategyRead(
            id=2,
            name="MACD Strategy",
            description="MACD 趋势跟随",
            pairs=["ETH/USDT"],
            strategy_type="trend_following",
            trade_count=200,
            max_drawdown=0.20,
            sharpe_ratio=2.0,
            win_rate=0.55,
        )
        result = schema.model_dump(context={"membership": MembershipTier.FREE})
        assert result["trade_count"] == 200
        assert result["max_drawdown"] == pytest.approx(0.20)

    def test_free_user_sees_all_ranking_fields(self) -> None:
        """Free 用户同样能看到 sharpe_ratio/win_rate（首页榜单核心指标已对全量访客开放）。"""
        schema = StrategyRead(
            id=2,
            name="MACD Strategy",
            description="MACD 趋势跟随",
            pairs=["ETH/USDT"],
            strategy_type="trend_following",
            sharpe_ratio=2.0,
            win_rate=0.55,
        )
        result = schema.model_dump(context={"membership": MembershipTier.FREE})
        assert result["sharpe_ratio"] == pytest.approx(2.0)
        assert result["win_rate"] == pytest.approx(0.55)


class TestStrategyReadVIP:
    """VIP 用户访问 StrategyRead 时返回全部字段。"""

    def test_vip1_sees_all_fields(self) -> None:
        schema = StrategyRead(
            id=3,
            name="Bollinger Strategy",
            description="布林带策略",
            pairs=["BTC/USDT", "ETH/USDT"],
            strategy_type="volatility",
            trade_count=50,
            max_drawdown=0.10,
            sharpe_ratio=3.0,
            win_rate=0.65,
        )
        result = schema.model_dump(context={"membership": MembershipTier.VIP1})
        assert result["sharpe_ratio"] == pytest.approx(3.0)
        assert result["win_rate"] == pytest.approx(0.65)
        assert result["trade_count"] == 50
        assert result["max_drawdown"] == pytest.approx(0.10)

    def test_vip2_sees_all_fields(self) -> None:
        schema = StrategyRead(
            id=3,
            name="Bollinger Strategy",
            description="布林带策略",
            pairs=["BTC/USDT"],
            strategy_type="volatility",
            trade_count=50,
            max_drawdown=0.10,
            sharpe_ratio=3.0,
            win_rate=0.65,
        )
        result = schema.model_dump(context={"membership": MembershipTier.VIP2})
        assert result["sharpe_ratio"] == pytest.approx(3.0)
        assert result["win_rate"] == pytest.approx(0.65)


class TestBacktestResultReadPermissions:
    """BacktestResultRead 字段权限测试。"""

    def test_anonymous_sees_base_fields_only(self) -> None:
        from datetime import datetime, timezone

        schema = BacktestResultRead(
            id=1,
            strategy_id=1,
            task_id=1,
            total_return=0.25,
            annual_return=0.30,
            sharpe_ratio=2.0,
            max_drawdown=0.12,
            trade_count=150,
            win_rate=0.58,
            period_start=datetime(2024, 1, 1, tzinfo=timezone.utc),
            period_end=datetime(2024, 12, 31, tzinfo=timezone.utc),
            created_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        )
        result = schema.model_dump(context={"membership": None})
        # 匿名用户不可见的字段
        assert result.get("total_return") is None
        assert result.get("trade_count") is None
        assert result.get("max_drawdown") is None
        assert result.get("sharpe_ratio") is None
        assert result.get("win_rate") is None
        assert result.get("annual_return") is None

    def test_free_user_sees_total_return_trade_count_max_drawdown(self) -> None:
        from datetime import datetime, timezone

        schema = BacktestResultRead(
            id=1,
            strategy_id=1,
            task_id=1,
            total_return=0.25,
            annual_return=0.30,
            sharpe_ratio=2.0,
            max_drawdown=0.12,
            trade_count=150,
            win_rate=0.58,
            period_start=datetime(2024, 1, 1, tzinfo=timezone.utc),
            period_end=datetime(2024, 12, 31, tzinfo=timezone.utc),
            created_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        )
        result = schema.model_dump(context={"membership": MembershipTier.FREE})
        assert result["total_return"] == pytest.approx(0.25)
        assert result["trade_count"] == 150
        assert result["max_drawdown"] == pytest.approx(0.12)
        # VIP 字段不可见
        assert result.get("sharpe_ratio") is None
        assert result.get("win_rate") is None
        assert result.get("annual_return") is None

    def test_vip_user_sees_all_fields(self) -> None:
        from datetime import datetime, timezone

        schema = BacktestResultRead(
            id=1,
            strategy_id=1,
            task_id=1,
            total_return=0.25,
            annual_return=0.30,
            sharpe_ratio=2.0,
            max_drawdown=0.12,
            trade_count=150,
            win_rate=0.58,
            period_start=datetime(2024, 1, 1, tzinfo=timezone.utc),
            period_end=datetime(2024, 12, 31, tzinfo=timezone.utc),
            created_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        )
        result = schema.model_dump(context={"membership": MembershipTier.VIP1})
        assert result["sharpe_ratio"] == pytest.approx(2.0)
        assert result["win_rate"] == pytest.approx(0.58)
        assert result["annual_return"] == pytest.approx(0.30)


class TestSignalReadPermissions:
    """SignalRead 字段权限测试 —— confidence_score VIP 专属。"""

    def test_anonymous_cannot_see_confidence_score(self) -> None:
        from datetime import datetime, timezone

        from src.core.enums import SignalDirection

        schema = SignalRead(
            id=1,
            strategy_id=1,
            pair="BTC/USDT",
            direction=SignalDirection.BUY,
            confidence_score=0.85,
            signal_at=datetime(2025, 3, 1, tzinfo=timezone.utc),
            created_at=datetime(2025, 3, 1, tzinfo=timezone.utc),
        )
        result = schema.model_dump(context={"membership": None})
        assert result.get("confidence_score") is None

    def test_free_user_cannot_see_confidence_score(self) -> None:
        from datetime import datetime, timezone

        from src.core.enums import SignalDirection

        schema = SignalRead(
            id=1,
            strategy_id=1,
            pair="BTC/USDT",
            direction=SignalDirection.SELL,
            confidence_score=0.72,
            signal_at=datetime(2025, 3, 1, tzinfo=timezone.utc),
            created_at=datetime(2025, 3, 1, tzinfo=timezone.utc),
        )
        result = schema.model_dump(context={"membership": MembershipTier.FREE})
        assert result.get("confidence_score") is None

    def test_vip1_can_see_confidence_score(self) -> None:
        from datetime import datetime, timezone

        from src.core.enums import SignalDirection

        schema = SignalRead(
            id=1,
            strategy_id=1,
            pair="BTC/USDT",
            direction=SignalDirection.BUY,
            confidence_score=0.91,
            signal_at=datetime(2025, 3, 1, tzinfo=timezone.utc),
            created_at=datetime(2025, 3, 1, tzinfo=timezone.utc),
        )
        result = schema.model_dump(context={"membership": MembershipTier.VIP1})
        assert result["confidence_score"] == pytest.approx(0.91)

    def test_all_users_see_direction_and_signal_at(self) -> None:
        from datetime import datetime, timezone

        from src.core.enums import SignalDirection

        signal_time = datetime(2025, 3, 1, tzinfo=timezone.utc)
        schema = SignalRead(
            id=1,
            strategy_id=1,
            pair="ETH/USDT",
            direction=SignalDirection.HOLD,
            signal_at=signal_time,
            created_at=signal_time,
        )
        for membership in [None, MembershipTier.FREE, MembershipTier.VIP1]:
            result = schema.model_dump(context={"membership": membership})
            assert result["direction"] is not None
            assert result["signal_at"] is not None


class TestUserReadSchema:
    """UserRead Schema 基础验证（任务 4.2）。"""

    def test_user_read_contains_required_fields(self) -> None:
        from datetime import datetime, timezone

        from src.schemas.strategy import UserRead

        schema = UserRead(
            id=1,
            username="testuser",
            membership=MembershipTier.FREE,
            created_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        )
        result = schema.model_dump()
        assert result["id"] == 1
        assert result["username"] == "testuser"
        assert result["membership"] == MembershipTier.FREE
        assert result["created_at"] is not None


class TestReportSchemas:
    """ReportRead / ReportDetailRead Schema 验证（任务 4.2）。"""

    def test_report_read_contains_list_fields(self) -> None:
        from datetime import datetime, timezone

        from src.schemas.strategy import ReportRead

        schema = ReportRead(
            id=1,
            title="BTC 市场研报",
            summary="本周比特币整体偏强。",
            generated_at=datetime(2025, 3, 1, tzinfo=timezone.utc),
            related_coins=["BTC", "ETH"],
        )
        result = schema.model_dump()
        assert result["id"] == 1
        assert result["title"] == "BTC 市场研报"
        assert result["related_coins"] == ["BTC", "ETH"]

    def test_report_detail_read_contains_content(self) -> None:
        from datetime import datetime, timezone

        from src.schemas.strategy import ReportDetailRead

        schema = ReportDetailRead(
            id=2,
            title="ETH 分析",
            summary="以太坊本月走势分析。",
            content="详细内容……",
            generated_at=datetime(2025, 3, 1, tzinfo=timezone.utc),
            related_coins=["ETH"],
        )
        result = schema.model_dump()
        assert result["content"] == "详细内容……"


class TestPaginatedResponseSchema:
    """PaginatedResponse 泛型 Schema 验证（任务 4.2）。"""

    def test_paginated_response_fields(self) -> None:
        from src.schemas.strategy import PaginatedResponse

        schema: PaginatedResponse[int] = PaginatedResponse(
            items=[1, 2, 3],
            total=100,
            page=1,
            page_size=20,
        )
        result = schema.model_dump()
        assert result["items"] == [1, 2, 3]
        assert result["total"] == 100
        assert result["page"] == 1
        assert result["page_size"] == 20

    def test_paginated_response_default_page_size(self) -> None:
        from src.schemas.strategy import PaginatedResponse

        schema: PaginatedResponse[str] = PaginatedResponse(
            items=["a"],
            total=1,
            page=1,
        )
        assert schema.page_size == 20
