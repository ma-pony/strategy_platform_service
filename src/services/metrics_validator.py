"""指标值域校验工具（Task 2.1）。

提供纯函数 validate_metrics，在写入数据库前校验绩效指标值域，
拒绝超出合理范围的异常值。

校验规则：
  - 浮点类指标（total_return, profit_factor, max_drawdown, sharpe_ratio）
    须在 [-10000, 10000] 范围内，None 值直接通过
  - trade_count 须为非负整数（>= 0），None 值直接通过

特性：
  - 纯函数，无副作用，不依赖数据库，可独立测试
  - 校验失败时立即抛出 ValueError（快速失败语义），含字段名和实际值
  - 校验通过时返回 None

需求可追溯：6.2, 6.3
"""

_FLOAT_MIN = -10000.0
_FLOAT_MAX = 10000.0


def validate_metrics(
    total_return: float | None,
    profit_factor: float | None,
    max_drawdown: float | None,
    sharpe_ratio: float | None,
    trade_count: int | None,
) -> None:
    """校验指标值域。校验失败时立即抛出 ValueError（含字段名和实际值）。

    浮点类指标（total_return, profit_factor, max_drawdown, sharpe_ratio）须在
    [-10000, 10000] 范围内。trade_count 须为非负整数。None 值直接通过。

    Args:
        total_return: 累计收益率，映射自 freqtrade profit_total
        profit_factor: 盈利因子，freqtrade 回测独立字段
        max_drawdown: 最大回撤（正数表示）
        sharpe_ratio: 夏普比率
        trade_count: 总交易次数（非负整数）

    Returns:
        None（所有字段通过校验）

    Raises:
        ValueError: 任一字段校验失败，错误信息含字段名和实际值
    """
    _validate_float_field("total_return", total_return)
    _validate_float_field("profit_factor", profit_factor)
    _validate_float_field("max_drawdown", max_drawdown)
    _validate_float_field("sharpe_ratio", sharpe_ratio)
    _validate_trade_count(trade_count)


def _validate_float_field(field_name: str, value: float | None) -> None:
    """校验浮点指标字段值域（[-10000, 10000]）。

    Args:
        field_name: 字段名（用于错误信息）
        value: 字段值，None 直接通过

    Raises:
        ValueError: 值超出 [-10000, 10000] 范围
    """
    if value is None:
        return
    if value < _FLOAT_MIN or value > _FLOAT_MAX:
        raise ValueError(
            f"指标字段 {field_name} 值 {value} 超出合理范围 "
            f"[{_FLOAT_MIN}, {_FLOAT_MAX}]，拒绝写入。"
        )


def _validate_trade_count(value: int | None) -> None:
    """校验 trade_count 为非负整数。

    Args:
        value: trade_count 值，None 直接通过

    Raises:
        ValueError: 值为负数
    """
    if value is None:
        return
    if value < 0:
        raise ValueError(
            f"指标字段 trade_count 值 {value} 为负数，非法，拒绝写入。"
        )
