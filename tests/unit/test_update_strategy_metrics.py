"""backtest_tasks._update_strategy_metrics 单元测试。

锁死"总是覆盖"语义：真实回测成功后应当刷新 Strategy 表的 6 个指标字段，
不管目标字段是不是 NULL。这样首页榜单才会随新回测更新。

防御要点：
  - 非 NULL 字段也必须被覆盖（反面：旧的"只填 NULL"行为）
  - result_data 缺 key 时跳过，保留既有值（避免把有值写成 None）
  - 目标字段不存在时跳过（防御 model 缺字段的情况）
"""

from types import SimpleNamespace

from src.workers.tasks.backtest_tasks import _update_strategy_metrics


def _make_strategy(**fields) -> SimpleNamespace:
    """构造一个带 6 个指标字段的简单策略对象（不需要 ORM）。"""
    defaults = {
        "total_return": None,
        "annual_return": None,
        "trade_count": None,
        "max_drawdown": None,
        "sharpe_ratio": None,
        "win_rate": None,
    }
    defaults.update(fields)
    return SimpleNamespace(**defaults)


def test_overwrites_all_null_fields() -> None:
    """全 NULL 初始状态 → 全部字段写入新值。"""
    strategy = _make_strategy()
    result = {
        "total_return": 0.35,
        "annual_return": 0.12,
        "trade_count": 100,
        "max_drawdown": 0.22,
        "sharpe_ratio": 1.8,
        "win_rate": 0.55,
    }
    _update_strategy_metrics(strategy, result)
    assert strategy.total_return == 0.35
    assert strategy.annual_return == 0.12
    assert strategy.trade_count == 100
    assert strategy.max_drawdown == 0.22
    assert strategy.sharpe_ratio == 1.8
    assert strategy.win_rate == 0.55


def test_overwrites_existing_non_null_values() -> None:
    """核心防回退：非 NULL 字段必须被新值覆盖（原"只填 NULL"的反面）。"""
    strategy = _make_strategy(
        total_return=15.66,  # 旧 seed 值
        annual_return=0.58,  # 旧 seed 值
        trade_count=1225,
        max_drawdown=0.80,
        sharpe_ratio=1.86,
        win_rate=0.36,
    )
    result = {
        "total_return": 0.25,  # 真实回测的新值
        "annual_return": 0.08,
        "trade_count": 50,
        "max_drawdown": 0.15,
        "sharpe_ratio": 1.2,
        "win_rate": 0.62,
    }
    _update_strategy_metrics(strategy, result)
    assert strategy.total_return == 0.25
    assert strategy.annual_return == 0.08
    assert strategy.trade_count == 50
    assert strategy.max_drawdown == 0.15
    assert strategy.sharpe_ratio == 1.2
    assert strategy.win_rate == 0.62


def test_missing_key_preserves_existing_value() -> None:
    """result_data 缺 key 时不写入 None，保留既有值。"""
    strategy = _make_strategy(
        total_return=0.5,
        annual_return=0.1,
        trade_count=10,
    )
    # result 缺 annual_return 和 win_rate
    result = {
        "total_return": 0.6,
        "trade_count": 20,
        "max_drawdown": 0.1,
        "sharpe_ratio": 1.0,
    }
    _update_strategy_metrics(strategy, result)
    assert strategy.total_return == 0.6
    assert strategy.annual_return == 0.1  # 保留旧值
    assert strategy.trade_count == 20
    assert strategy.win_rate is None  # 保留旧值（原本就是 None）


def test_skips_unknown_attribute() -> None:
    """目标对象没有某字段时静默跳过，不抛 AttributeError。"""
    strategy = SimpleNamespace(total_return=None, trade_count=None)
    result = {
        "total_return": 0.3,
        "annual_return": 0.1,  # strategy 对象没这个字段
        "trade_count": 5,
        "max_drawdown": 0.2,  # strategy 对象没这个字段
    }
    _update_strategy_metrics(strategy, result)
    assert strategy.total_return == 0.3
    assert strategy.trade_count == 5
    assert not hasattr(strategy, "annual_return")
    assert not hasattr(strategy, "max_drawdown")
