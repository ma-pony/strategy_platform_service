"""PairMetricsRead Schema 单元测试（Task 5.1, Task 7.4）。

验证按会员等级的字段可见性：
  - 匿名用户（membership=None）：仅返回 pair、timeframe、total_return、trade_count
  - Free 用户：额外返回 profit_factor、data_source
  - VIP1 及以上：全部字段含 max_drawdown、sharpe_ratio、last_updated_at

需求可追溯：4.1, 4.2, 4.3
"""

from datetime import datetime, timezone

import pytest

from src.core.enums import DataSource, MembershipTier


def _make_orm_like_obj() -> object:
    """构造模拟 ORM 对象，含全部指标字段。"""

    class FakeMetrics:
        pair = "BTC/USDT"
        timeframe = "1h"
        total_return = 0.15
        trade_count = 42
        profit_factor = 1.5
        data_source = DataSource.BACKTEST
        max_drawdown = 0.08
        sharpe_ratio = 1.2
        last_updated_at = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

    return FakeMetrics()


class TestPairMetricsReadAnonymous:
    """匿名用户仅返回基础字段（需求 4.2）。"""

    def test_anonymous_user_sees_pair_and_timeframe(self) -> None:
        """匿名用户应能看到 pair 和 timeframe 字段。"""
        from src.schemas.pair_metrics import PairMetricsRead

        obj = _make_orm_like_obj()
        schema = PairMetricsRead.model_validate(obj)
        result = schema.model_dump(context={"membership": None})

        assert result["pair"] == "BTC/USDT"
        assert result["timeframe"] == "1h"

    def test_anonymous_user_sees_total_return(self) -> None:
        """匿名用户应能看到 total_return 字段。"""
        from src.schemas.pair_metrics import PairMetricsRead

        obj = _make_orm_like_obj()
        schema = PairMetricsRead.model_validate(obj)
        result = schema.model_dump(context={"membership": None})

        assert result["total_return"] == 0.15

    def test_anonymous_user_sees_trade_count(self) -> None:
        """匿名用户应能看到 trade_count 字段。"""
        from src.schemas.pair_metrics import PairMetricsRead

        obj = _make_orm_like_obj()
        schema = PairMetricsRead.model_validate(obj)
        result = schema.model_dump(context={"membership": None})

        assert result["trade_count"] == 42

    def test_anonymous_user_cannot_see_profit_factor(self) -> None:
        """匿名用户的 profit_factor 应为 None（隐藏，需求 4.2）。"""
        from src.schemas.pair_metrics import PairMetricsRead

        obj = _make_orm_like_obj()
        schema = PairMetricsRead.model_validate(obj)
        result = schema.model_dump(context={"membership": None})

        assert result.get("profit_factor") is None

    def test_anonymous_user_cannot_see_data_source(self) -> None:
        """匿名用户的 data_source 应为 None（需求 4.2）。"""
        from src.schemas.pair_metrics import PairMetricsRead

        obj = _make_orm_like_obj()
        schema = PairMetricsRead.model_validate(obj)
        result = schema.model_dump(context={"membership": None})

        assert result.get("data_source") is None

    def test_anonymous_user_cannot_see_max_drawdown(self) -> None:
        """匿名用户的 max_drawdown 应为 None（需求 4.2）。"""
        from src.schemas.pair_metrics import PairMetricsRead

        obj = _make_orm_like_obj()
        schema = PairMetricsRead.model_validate(obj)
        result = schema.model_dump(context={"membership": None})

        assert result.get("max_drawdown") is None

    def test_anonymous_user_cannot_see_sharpe_ratio(self) -> None:
        """匿名用户的 sharpe_ratio 应为 None（需求 4.2）。"""
        from src.schemas.pair_metrics import PairMetricsRead

        obj = _make_orm_like_obj()
        schema = PairMetricsRead.model_validate(obj)
        result = schema.model_dump(context={"membership": None})

        assert result.get("sharpe_ratio") is None

    def test_no_context_treated_as_anonymous(self) -> None:
        """未提供 context 时应以匿名等级处理。"""
        from src.schemas.pair_metrics import PairMetricsRead

        obj = _make_orm_like_obj()
        schema = PairMetricsRead.model_validate(obj)
        result = schema.model_dump()

        assert result.get("profit_factor") is None
        assert result.get("max_drawdown") is None


class TestPairMetricsReadFreeUser:
    """Free 用户额外返回 profit_factor 和 data_source（需求 4.2）。"""

    def test_free_user_sees_profit_factor(self) -> None:
        """Free 用户应能看到 profit_factor 字段。"""
        from src.schemas.pair_metrics import PairMetricsRead

        obj = _make_orm_like_obj()
        schema = PairMetricsRead.model_validate(obj)
        result = schema.model_dump(context={"membership": MembershipTier.FREE})

        assert result["profit_factor"] == 1.5

    def test_free_user_sees_data_source(self) -> None:
        """Free 用户应能看到 data_source 字段。"""
        from src.schemas.pair_metrics import PairMetricsRead

        obj = _make_orm_like_obj()
        schema = PairMetricsRead.model_validate(obj)
        result = schema.model_dump(context={"membership": MembershipTier.FREE})

        assert result["data_source"] is not None

    def test_free_user_cannot_see_max_drawdown(self) -> None:
        """Free 用户的 max_drawdown 应为 None（VIP1 专属，需求 4.3）。"""
        from src.schemas.pair_metrics import PairMetricsRead

        obj = _make_orm_like_obj()
        schema = PairMetricsRead.model_validate(obj)
        result = schema.model_dump(context={"membership": MembershipTier.FREE})

        assert result.get("max_drawdown") is None

    def test_free_user_cannot_see_sharpe_ratio(self) -> None:
        """Free 用户的 sharpe_ratio 应为 None（VIP1 专属，需求 4.3）。"""
        from src.schemas.pair_metrics import PairMetricsRead

        obj = _make_orm_like_obj()
        schema = PairMetricsRead.model_validate(obj)
        result = schema.model_dump(context={"membership": MembershipTier.FREE})

        assert result.get("sharpe_ratio") is None

    def test_free_user_cannot_see_last_updated_at(self) -> None:
        """Free 用户的 last_updated_at 应为 None（VIP1 专属，需求 4.3）。"""
        from src.schemas.pair_metrics import PairMetricsRead

        obj = _make_orm_like_obj()
        schema = PairMetricsRead.model_validate(obj)
        result = schema.model_dump(context={"membership": MembershipTier.FREE})

        assert result.get("last_updated_at") is None


class TestPairMetricsReadVIP1:
    """VIP1 及以上用户返回全量字段（需求 4.3）。"""

    def test_vip1_user_sees_all_fields(self) -> None:
        """VIP1 用户应能看到全部字段。"""
        from src.schemas.pair_metrics import PairMetricsRead

        obj = _make_orm_like_obj()
        schema = PairMetricsRead.model_validate(obj)
        result = schema.model_dump(context={"membership": MembershipTier.VIP1})

        assert result["pair"] == "BTC/USDT"
        assert result["total_return"] == 0.15
        assert result["trade_count"] == 42
        assert result["profit_factor"] == 1.5
        assert result["data_source"] is not None
        assert result["max_drawdown"] == 0.08
        assert result["sharpe_ratio"] == 1.2
        assert result["last_updated_at"] is not None

    def test_vip2_user_sees_all_fields(self) -> None:
        """VIP2 用户（更高等级）应能看到全部字段。"""
        from src.schemas.pair_metrics import PairMetricsRead

        obj = _make_orm_like_obj()
        schema = PairMetricsRead.model_validate(obj)
        result = schema.model_dump(context={"membership": MembershipTier.VIP2})

        assert result["max_drawdown"] is not None
        assert result["sharpe_ratio"] is not None

    def test_from_attributes_enabled(self) -> None:
        """model_config 应启用 from_attributes=True 以支持 ORM 对象直接转换。"""
        from src.schemas.pair_metrics import PairMetricsRead

        # 如果 from_attributes=True，model_validate 不应抛出错误
        obj = _make_orm_like_obj()
        schema = PairMetricsRead.model_validate(obj)
        assert schema.pair == "BTC/USDT"
