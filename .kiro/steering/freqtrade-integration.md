# Freqtrade Integration

freqtrade 作为量化引擎底层，所有调用封装在 `src/freqtrade_bridge/` 中，通过异步机制与 FastAPI 主进程完全解耦。

## Core Principle: Never Block the Web Thread

freqtrade 的回测和策略运行属于 CPU 密集型或长耗时操作，**禁止**在 FastAPI 请求处理路径中同步调用。违反此原则会导致整个事件循环阻塞，所有并发请求挂起。

## Integration Architecture

```
FastAPI Request
    │
    ▼
StrategyService / BacktestService
    │  提交任务（返回 task_id）
    ▼
Task Queue (Celery / asyncio ProcessPoolExecutor)
    │  独立 Worker 进程
    ▼
FreqtradeBridge（子进程或模块调用）
    │
    ▼
freqtrade Engine
    │  结果写回 DB
    ▼
BacktestResult（SQLAlchemy 模型）
```

## Calling Methods（按复杂度选型）

### 方案 A：子进程（推荐用于回测）
适合长耗时、有可能崩溃的任务，进程隔离保证主服务稳定：

```python
# src/freqtrade_bridge/backtester.py
import subprocess
import json
from pathlib import Path

def run_backtest_subprocess(config_path: Path, strategy: str) -> dict:
    """在独立子进程中执行 freqtrade 回测，阻塞等待结果。
    应在 Worker 进程中调用，不可在 Web 线程中直接调用。
    """
    result = subprocess.run(
        ["freqtrade", "backtesting", "--config", str(config_path),
         "--strategy", strategy, "--export", "json"],
        capture_output=True,
        text=True,
        timeout=600,  # 10 分钟超时
    )
    if result.returncode != 0:
        raise FreqtradeExecutionError(result.stderr)
    return json.loads(result.stdout)
```

### 方案 B：模块导入（推荐用于信号查询）
适合轻量、快速的信号生成，在 ProcessPoolExecutor 中运行避免 GIL：

```python
# src/freqtrade_bridge/signal_fetcher.py
from concurrent.futures import ProcessPoolExecutor

_executor = ProcessPoolExecutor(max_workers=2)

async def fetch_signals(strategy: str, pair: str) -> dict:
    """在独立进程中调用 freqtrade 信号逻辑，返回 asyncio Future。"""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_executor, _fetch_signals_sync, strategy, pair)

def _fetch_signals_sync(strategy: str, pair: str) -> dict:
    # 在子进程中 import freqtrade 模块并执行信号逻辑
    from freqtrade.strategy.interface import IStrategy
    ...
```

### 方案 C：freqtrade RPC API
若 freqtrade 实例以 `--rpc` 模式运行，可通过 HTTP 调用其内置 REST API，适合管理已运行的 bot 实例。

## Task Lifecycle

回测等异步任务必须持久化状态，供客户端轮询：

```python
# src/models/backtest_task.py
class BacktestTask(Base, TimestampMixin):
    __tablename__ = "backtest_tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    strategy: Mapped[str] = mapped_column(String(128))
    status: Mapped[TaskStatus] = mapped_column(default=TaskStatus.PENDING)
    # PENDING → RUNNING → DONE | FAILED
    result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
```

客户端通过 `GET /api/v1/backtests/{task_id}` 轮询状态，无需 WebSocket。

## Error Handling

freqtrade 调用失败应捕获为业务错误，不暴露原始 traceback：

```python
# src/freqtrade_bridge/exceptions.py
class FreqtradeExecutionError(Exception):
    """freqtrade 执行失败，包含原始错误信息。"""

class FreqtradeTimeoutError(Exception):
    """freqtrade 任务超时。"""
```

服务层捕获后将任务状态更新为 `FAILED`，返回 `code: 5001` 给客户端。

## Configuration Isolation

每个用户/策略的 freqtrade 配置文件生成在隔离目录，禁止用户配置互相覆盖：

```
/tmp/freqtrade_jobs/{user_id}/{task_id}/
├── config.json        # 动态生成，不含敏感 API key
├── strategy/          # 策略文件（从数据库写入）
└── results/           # 回测输出
```

任务结束后清理临时目录。

---
_Focus on integration patterns and isolation. No API keys or exchange credentials._
