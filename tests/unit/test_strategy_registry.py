"""StrategyRegistry 单元测试（任务 10.1）。"""

import pytest

from src.core.exceptions import UnsupportedStrategyError
from src.freqtrade_bridge.strategy_registry import STRATEGY_REGISTRY, lookup


class TestStrategyRegistry:
    """策略注册表测试。"""

    # 全部十个有效策略名
    VALID_STRATEGIES = [
        "TurtleTrading",
        "BollingerMeanReversion",
        "RsiMeanReversion",
        "MacdTrend",
        "IchimokuTrend",
        "ParabolicSarTrend",
        "KeltnerBreakout",
        "AroonTrend",
        "Nr7Breakout",
        "StochasticReversal",
    ]

    def test_registry_contains_ten_strategies(self) -> None:
        """注册表应包含恰好十个策略。"""
        assert len(STRATEGY_REGISTRY) == 10

    @pytest.mark.parametrize("name", VALID_STRATEGIES)
    def test_lookup_valid_strategy(self, name: str) -> None:
        """有效策略名应返回正确的 class_name 和存在的 file_path。"""
        entry = lookup(name)
        assert entry["class_name"] == name
        assert entry["file_path"].exists(), f"策略文件不存在: {entry['file_path']}"
        assert entry["file_path"].suffix == ".py"

    def test_lookup_invalid_strategy_raises(self) -> None:
        """无效策略名应抛 UnsupportedStrategyError。"""
        with pytest.raises(UnsupportedStrategyError) as exc_info:
            lookup("NonExistentStrategy")
        assert exc_info.value.code == 3003

    def test_lookup_empty_string_raises(self) -> None:
        """空字符串应抛 UnsupportedStrategyError。"""
        with pytest.raises(UnsupportedStrategyError):
            lookup("")

    @pytest.mark.parametrize("name", VALID_STRATEGIES)
    def test_registry_entry_file_path_is_absolute(self, name: str) -> None:
        """每个策略的 file_path 应为绝对路径。"""
        entry = STRATEGY_REGISTRY[name]
        assert entry["file_path"].is_absolute()
