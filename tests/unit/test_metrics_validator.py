"""MetricsValidator 单元测试（Task 2.1）。

测试覆盖范围：
- 浮点指标边界值：±10000 临界值（应通过）、超出范围（应抛出）
- trade_count 负数拒绝、零通过、正数通过
- 所有字段均为 None 时通过（不写入场景）

需求可追溯：6.2, 6.3
"""

import pytest

from src.services.metrics_validator import validate_metrics


class TestValidateMetricsAllNone:
    """所有字段为 None 时应通过校验（不写入场景，需求 6.2）。"""

    def test_all_none_passes(self) -> None:
        """全为 None 时不应抛出任何异常。"""
        validate_metrics(
            total_return=None,
            profit_factor=None,
            max_drawdown=None,
            sharpe_ratio=None,
            trade_count=None,
        )


class TestValidateMetricsBoundaryValues:
    """浮点指标边界值测试（±10000 临界值，需求 6.2）。"""

    def test_total_return_at_positive_boundary_passes(self) -> None:
        """total_return = 10000.0 临界值应通过。"""
        validate_metrics(
            total_return=10000.0,
            profit_factor=None,
            max_drawdown=None,
            sharpe_ratio=None,
            trade_count=None,
        )

    def test_total_return_at_negative_boundary_passes(self) -> None:
        """total_return = -10000.0 临界值应通过。"""
        validate_metrics(
            total_return=-10000.0,
            profit_factor=None,
            max_drawdown=None,
            sharpe_ratio=None,
            trade_count=None,
        )

    def test_total_return_exceeds_positive_boundary_raises(self) -> None:
        """total_return > 10000.0 应抛出 ValueError。"""
        with pytest.raises(ValueError, match="total_return"):
            validate_metrics(
                total_return=10000.1,
                profit_factor=None,
                max_drawdown=None,
                sharpe_ratio=None,
                trade_count=None,
            )

    def test_total_return_exceeds_negative_boundary_raises(self) -> None:
        """total_return < -10000.0 应抛出 ValueError。"""
        with pytest.raises(ValueError, match="total_return"):
            validate_metrics(
                total_return=-10000.1,
                profit_factor=None,
                max_drawdown=None,
                sharpe_ratio=None,
                trade_count=None,
            )

    def test_profit_factor_at_positive_boundary_passes(self) -> None:
        """profit_factor = 10000.0 临界值应通过。"""
        validate_metrics(
            total_return=None,
            profit_factor=10000.0,
            max_drawdown=None,
            sharpe_ratio=None,
            trade_count=None,
        )

    def test_profit_factor_at_negative_boundary_passes(self) -> None:
        """profit_factor = -10000.0 临界值应通过。"""
        validate_metrics(
            total_return=None,
            profit_factor=-10000.0,
            max_drawdown=None,
            sharpe_ratio=None,
            trade_count=None,
        )

    def test_profit_factor_exceeds_positive_boundary_raises(self) -> None:
        """profit_factor > 10000.0 应抛出 ValueError。"""
        with pytest.raises(ValueError, match="profit_factor"):
            validate_metrics(
                total_return=None,
                profit_factor=10001.0,
                max_drawdown=None,
                sharpe_ratio=None,
                trade_count=None,
            )

    def test_profit_factor_exceeds_negative_boundary_raises(self) -> None:
        """profit_factor < -10000.0 应抛出 ValueError。"""
        with pytest.raises(ValueError, match="profit_factor"):
            validate_metrics(
                total_return=None,
                profit_factor=-10001.0,
                max_drawdown=None,
                sharpe_ratio=None,
                trade_count=None,
            )

    def test_max_drawdown_at_positive_boundary_passes(self) -> None:
        """max_drawdown = 10000.0 临界值应通过。"""
        validate_metrics(
            total_return=None,
            profit_factor=None,
            max_drawdown=10000.0,
            sharpe_ratio=None,
            trade_count=None,
        )

    def test_max_drawdown_at_negative_boundary_passes(self) -> None:
        """max_drawdown = -10000.0 临界值应通过。"""
        validate_metrics(
            total_return=None,
            profit_factor=None,
            max_drawdown=-10000.0,
            sharpe_ratio=None,
            trade_count=None,
        )

    def test_max_drawdown_exceeds_positive_boundary_raises(self) -> None:
        """max_drawdown > 10000.0 应抛出 ValueError。"""
        with pytest.raises(ValueError, match="max_drawdown"):
            validate_metrics(
                total_return=None,
                profit_factor=None,
                max_drawdown=99999.0,
                sharpe_ratio=None,
                trade_count=None,
            )

    def test_max_drawdown_exceeds_negative_boundary_raises(self) -> None:
        """max_drawdown < -10000.0 应抛出 ValueError。"""
        with pytest.raises(ValueError, match="max_drawdown"):
            validate_metrics(
                total_return=None,
                profit_factor=None,
                max_drawdown=-99999.0,
                sharpe_ratio=None,
                trade_count=None,
            )

    def test_sharpe_ratio_at_positive_boundary_passes(self) -> None:
        """sharpe_ratio = 10000.0 临界值应通过。"""
        validate_metrics(
            total_return=None,
            profit_factor=None,
            max_drawdown=None,
            sharpe_ratio=10000.0,
            trade_count=None,
        )

    def test_sharpe_ratio_at_negative_boundary_passes(self) -> None:
        """sharpe_ratio = -10000.0 临界值应通过。"""
        validate_metrics(
            total_return=None,
            profit_factor=None,
            max_drawdown=None,
            sharpe_ratio=-10000.0,
            trade_count=None,
        )

    def test_sharpe_ratio_exceeds_positive_boundary_raises(self) -> None:
        """sharpe_ratio > 10000.0 应抛出 ValueError。"""
        with pytest.raises(ValueError, match="sharpe_ratio"):
            validate_metrics(
                total_return=None,
                profit_factor=None,
                max_drawdown=None,
                sharpe_ratio=10000.01,
                trade_count=None,
            )

    def test_sharpe_ratio_exceeds_negative_boundary_raises(self) -> None:
        """sharpe_ratio < -10000.0 应抛出 ValueError。"""
        with pytest.raises(ValueError, match="sharpe_ratio"):
            validate_metrics(
                total_return=None,
                profit_factor=None,
                max_drawdown=None,
                sharpe_ratio=-10001.0,
                trade_count=None,
            )


class TestValidateMetricsTradeCount:
    """trade_count 校验测试（需求 6.3）。"""

    def test_trade_count_zero_passes(self) -> None:
        """trade_count = 0 应通过校验（非负整数）。"""
        validate_metrics(
            total_return=None,
            profit_factor=None,
            max_drawdown=None,
            sharpe_ratio=None,
            trade_count=0,
        )

    def test_trade_count_positive_passes(self) -> None:
        """trade_count > 0 应通过校验。"""
        validate_metrics(
            total_return=None,
            profit_factor=None,
            max_drawdown=None,
            sharpe_ratio=None,
            trade_count=100,
        )

    def test_trade_count_negative_raises(self) -> None:
        """trade_count < 0 应抛出 ValueError（需求 6.3）。"""
        with pytest.raises(ValueError, match="trade_count"):
            validate_metrics(
                total_return=None,
                profit_factor=None,
                max_drawdown=None,
                sharpe_ratio=None,
                trade_count=-1,
            )

    def test_trade_count_large_negative_raises(self) -> None:
        """trade_count = -999 应抛出 ValueError。"""
        with pytest.raises(ValueError, match="trade_count"):
            validate_metrics(
                total_return=None,
                profit_factor=None,
                max_drawdown=None,
                sharpe_ratio=None,
                trade_count=-999,
            )

    def test_trade_count_none_passes(self) -> None:
        """trade_count = None 应通过校验（可选字段）。"""
        validate_metrics(
            total_return=None,
            profit_factor=None,
            max_drawdown=None,
            sharpe_ratio=None,
            trade_count=None,
        )


class TestValidateMetricsNormalValues:
    """正常范围内的指标值应通过校验。"""

    def test_normal_backtest_metrics_pass(self) -> None:
        """典型回测指标数值应全部通过。"""
        validate_metrics(
            total_return=0.1523,
            profit_factor=1.5,
            max_drawdown=0.08,
            sharpe_ratio=1.2,
            trade_count=42,
        )

    def test_zero_returns_pass(self) -> None:
        """零值指标应通过校验。"""
        validate_metrics(
            total_return=0.0,
            profit_factor=0.0,
            max_drawdown=0.0,
            sharpe_ratio=0.0,
            trade_count=0,
        )

    def test_negative_returns_within_range_pass(self) -> None:
        """负收益率在 [-10000, 10000] 范围内应通过。"""
        validate_metrics(
            total_return=-0.5,
            profit_factor=0.3,
            max_drawdown=0.25,
            sharpe_ratio=-1.5,
            trade_count=10,
        )

    def test_error_message_contains_field_name_and_value(self) -> None:
        """ValueError 错误信息应包含字段名和实际值。"""
        with pytest.raises(ValueError) as exc_info:
            validate_metrics(
                total_return=99999.0,
                profit_factor=None,
                max_drawdown=None,
                sharpe_ratio=None,
                trade_count=None,
            )
        error_msg = str(exc_info.value)
        # 错误信息应包含字段名
        assert "total_return" in error_msg
        # 错误信息应包含实际值
        assert "99999" in error_msg

    def test_trade_count_error_message_contains_field_name_and_value(self) -> None:
        """trade_count 校验失败的 ValueError 应包含字段名和实际值。"""
        with pytest.raises(ValueError) as exc_info:
            validate_metrics(
                total_return=None,
                profit_factor=None,
                max_drawdown=None,
                sharpe_ratio=None,
                trade_count=-5,
            )
        error_msg = str(exc_info.value)
        assert "trade_count" in error_msg
        assert "-5" in error_msg

    def test_first_invalid_field_raises_immediately(self) -> None:
        """校验失败时应立即抛出（快速失败语义）。"""
        # 第一个字段就非法，不应继续校验后续字段
        with pytest.raises(ValueError, match="total_return"):
            validate_metrics(
                total_return=99999.0,
                profit_factor=-99999.0,  # 也非法，但不应报这个
                max_drawdown=None,
                sharpe_ratio=None,
                trade_count=-1,  # 也非法，但不应报这个
            )
