"""backtester._parse_backtest_result 字段映射单元测试。

防回退：确保 freqtrade 回测 JSON 的关键字段被映射到正确的业务字段，
特别是 annual_return 必须来自 `cagr`（复合年增长率），不能再错成
`profit_total_abs`（绝对利润金额）。
"""

import json
import zipfile
from pathlib import Path

import pytest

from src.freqtrade_bridge.backtester import _parse_backtest_result


@pytest.fixture
def fake_result_zip(tmp_path: Path) -> Path:
    """构造一个 freqtrade 回测结果 zip，内含覆盖字段映射的 strategy_data。"""
    strategy_name = "DemoStrategy"
    payload = {
        "strategy": {
            strategy_name: {
                "profit_total": 0.3456,  # 总收益 ratio
                "profit_total_abs": 3456.0,  # 绝对金额（故意填充以防误用为 annual_return）
                "cagr": 0.1278,  # 年化收益 ratio
                "sharpe": 1.9,
                # max_drawdown_account 是 ratio（本次应采用的字段）
                "max_drawdown_account": 0.22,
                # max_drawdown_abs 是绝对金额（故意填充以防误用为 max_drawdown）
                "max_drawdown_abs": 2200.0,
                "total_trades": 4,
                "backtest_start": "2024-01-01T00:00:00",
                "backtest_end": "2024-12-31T00:00:00",
                "trades": [
                    {"profit_ratio": 0.05, "pair": "BTC/USDT", "open_rate": 30000.0, "close_rate": 31500.0},
                    {"profit_ratio": 0.03, "pair": "BTC/USDT", "open_rate": 31000.0, "close_rate": 31930.0},
                    {"profit_ratio": -0.02, "pair": "ETH/USDT", "open_rate": 2000.0, "close_rate": 1960.0},
                    {"profit_ratio": 0.08, "pair": "ETH/USDT", "open_rate": 2100.0, "close_rate": 2268.0},
                ],
            }
        }
    }

    results_dir = tmp_path / "results"
    results_dir.mkdir()
    zip_path = results_dir / "backtest-result-2024.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("backtest-result.json", json.dumps(payload))
    return results_dir


def test_annual_return_maps_to_cagr(fake_result_zip: Path) -> None:
    """annual_return 必须来自 strategy_data['cagr']，不得退化为 profit_total_abs。"""
    result = _parse_backtest_result(fake_result_zip, "DemoStrategy")
    assert result["annual_return"] == pytest.approx(0.1278)
    # 回归防御：cagr 与 profit_total_abs 差 4 个数量级，绝不应混淆
    assert result["annual_return"] != pytest.approx(3456.0)


def test_total_return_maps_to_profit_total(fake_result_zip: Path) -> None:
    """total_return 继续使用 profit_total（总收益 ratio）。"""
    result = _parse_backtest_result(fake_result_zip, "DemoStrategy")
    assert result["total_return"] == pytest.approx(0.3456)


def test_max_drawdown_maps_to_account_ratio(fake_result_zip: Path) -> None:
    """max_drawdown 必须来自 max_drawdown_account（比率），不得退化为
    max_drawdown_abs（币种绝对金额），否则会与 seed 写入的 ratio 语义冲突。
    """
    result = _parse_backtest_result(fake_result_zip, "DemoStrategy")
    assert result["max_drawdown"] == pytest.approx(0.22)
    # 回归防御：两字段相差 4 个数量级，绝不应混淆
    assert result["max_drawdown"] != pytest.approx(2200.0)


def test_win_rate_and_trade_count(fake_result_zip: Path) -> None:
    """win_rate = winning / total_trades；trade_count 取 total_trades。"""
    result = _parse_backtest_result(fake_result_zip, "DemoStrategy")
    assert result["trade_count"] == 4
    assert result["win_rate"] == pytest.approx(3 / 4)


def test_missing_cagr_falls_back_to_zero(tmp_path: Path) -> None:
    """freqtrade 未输出 cagr / max_drawdown_account 时，兜底为 0.0 而非 KeyError。"""
    strategy_name = "DemoStrategy"
    payload = {
        "strategy": {
            strategy_name: {
                "profit_total": 0.1,
                "sharpe": 1.0,
                "total_trades": 1,
                "backtest_start": "2024-01-01T00:00:00",
                "backtest_end": "2024-06-01T00:00:00",
                "trades": [],
            }
        }
    }
    results_dir = tmp_path / "results"
    results_dir.mkdir()
    with zipfile.ZipFile(results_dir / "backtest-result.zip", "w") as zf:
        zf.writestr("backtest-result.json", json.dumps(payload))

    result = _parse_backtest_result(results_dir, strategy_name)
    assert result["annual_return"] == 0.0
    assert result["max_drawdown"] == 0.0
