"""freqtrade 任务目录管理与配置生成工具。

职责：
  - generate_config：基于模板在隔离目录生成 freqtrade 配置 JSON
  - cleanup_task_dir：任务结束后清理隔离目录（通过 finally 块调用）

安全约束：
  - 生成的配置不含交易所 API Key 等敏感信息
  - 每个任务使用独立隔离目录，防止配置互相覆盖
"""

import json
import shutil
from pathlib import Path
from typing import Any

_TEMPLATE_PATH = Path(__file__).parent / "config_template.json"

# 不允许出现在配置文件中的敏感字段
_SENSITIVE_KEYS: frozenset[str] = frozenset(
    {
        "api_key",
        "api_secret",
        "secret",
        "password",
        "token",
        "exchange_key",
        "exchange_secret",
    }
)


def generate_config(
    task_dir: Path,
    strategy_config: dict[str, Any],
    timerange: str = "20240101-20240601",
) -> Path:
    """基于模板在隔离目录下生成 freqtrade 配置 JSON 文件。

    使用 config_template.json 模板，替换占位符后与 strategy_config 合并。
    过滤敏感字段（API Key 等），确保配置仅含回测参数。

    Args:
        task_dir: 任务隔离目录（如 /tmp/freqtrade_jobs/{task_id}/）
        strategy_config: 策略配置参数字典（可覆盖模板默认值）
        timerange: 回测时间范围，格式 YYYYMMDD-YYYYMMDD

    Returns:
        生成的配置文件路径
    """
    from src.core.app_settings import get_settings

    settings = get_settings()

    task_dir.mkdir(parents=True, exist_ok=True)

    strategy_path = str(task_dir / "strategy")
    results_dir = task_dir / "results"
    results_dir.mkdir(parents=True, exist_ok=True)

    # 加载模板
    template = json.loads(_TEMPLATE_PATH.read_text())

    # 替换模板占位符（数据目录使用全局共享路径）
    template["timerange"] = timerange
    template["datadir"] = settings.freqtrade_datadir
    template["strategy_path"] = strategy_path

    # 合并策略自定义配置（过滤敏感字段）
    for key, value in strategy_config.items():
        if key.lower() not in _SENSITIVE_KEYS:
            template[key] = value

    config_path = task_dir / "config.json"
    config_path.write_text(json.dumps(template, indent=2, ensure_ascii=False))
    return config_path


def cleanup_task_dir(task_dir: Path) -> None:
    """清理任务隔离目录。

    应在任务完成或失败后通过 finally 块调用，防止临时文件堆积。
    目录不存在时静默返回，不抛出异常。

    Args:
        task_dir: 需要清理的任务目录
    """
    if task_dir.exists():
        shutil.rmtree(task_dir, ignore_errors=True)
