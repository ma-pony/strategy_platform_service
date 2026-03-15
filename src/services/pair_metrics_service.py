"""策略对绩效指标服务层（Task 2.2, 5.2）。

提供：
  - upsert_pair_metrics：策略对绩效指标 PostgreSQL upsert 核心函数
    （含指标校验、指数退避重试、结构化日志）
  - PairMetricsService：异步查询服务（API 层使用）

设计约束：
  - upsert_pair_metrics 不执行 session.commit()，由调用方统一控制事务边界
  - 回测来源（DataSource.BACKTEST）：无条件覆盖所有非 None 指标字段；
    None 字段使用 COALESCE 保留现有值（需求 2.3）
  - 实盘来源（DataSource.LIVE）：统一使用 COALESCE 避免覆盖高质量回测数据
  - last_updated_at 防旧数据覆盖新数据（幂等保障，需求 3.5）
  - DB 连接错误：指数退避重试最多 3 次（1s, 2s, 4s），耗尽后记录 ERROR 并上抛

需求可追溯：1.5, 2.2, 2.3, 2.4, 3.2, 3.3, 3.5, 4.4, 4.5, 4.6, 6.1, 6.4, 6.5
"""

import time
from datetime import datetime

import structlog
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from src.core.enums import DataSource
from src.core.exceptions import NotFoundError
from src.models.strategy import Strategy
from src.models.strategy_pair_metrics import StrategyPairMetrics
from src.services.metrics_validator import validate_metrics

logger = structlog.get_logger(__name__)

# 重试配置（需求 6.1）
_MAX_RETRIES = 3
_RETRY_BASE_DELAY_SECONDS = 1.0


def upsert_pair_metrics(
    session: Session,
    strategy_id: int,
    pair: str,
    timeframe: str,
    total_return: float | None,
    profit_factor: float | None,
    max_drawdown: float | None,
    sharpe_ratio: float | None,
    trade_count: int | None,
    data_source: DataSource,
    last_updated_at: datetime,
) -> None:
    """执行 strategy_pair_metrics upsert，含指标校验、重试和结构化日志。

    使用 PostgreSQL INSERT ... ON CONFLICT(strategy_id, pair, timeframe) DO UPDATE SET ...
    实现幂等 upsert，保证并发安全（需求 6.4）。

    - 回测来源（DataSource.BACKTEST）：无条件覆盖非 None 字段；None 字段保留现有值（COALESCE）
    - 实盘来源（DataSource.LIVE）：所有字段均使用 COALESCE，避免覆盖高质量回测数据
    - last_updated_at 时序保护：仅在新时间戳 > 当前时间戳时更新（防旧数据覆盖，需求 3.5）
    - 调用前自动执行 validate_metrics 校验；校验失败则记录 WARNING 并返回，不执行 upsert

    Args:
        session: 同步 SQLAlchemy Session，由调用方提供，不自行 commit
        strategy_id: 策略 ID
        pair: 交易对（如 "BTC/USDT"）
        timeframe: 时间周期（如 "1h"）
        total_return: 累计收益率（映射自 freqtrade profit_total）
        profit_factor: 盈利因子（freqtrade 回测独立字段）
        max_drawdown: 最大回撤
        sharpe_ratio: 夏普比率
        trade_count: 总交易次数（非负整数）
        data_source: 数据来源（BACKTEST 或 LIVE）
        last_updated_at: 指标最后更新时间（UTC），由调用方显式传入

    Returns:
        None（成功或校验失败均无返回值）

    Raises:
        OperationalError: DB 连接错误重试 3 次耗尽后向上传播
    """
    # Step 1: 指标值域校验（需求 6.2, 6.3）
    try:
        validate_metrics(
            total_return=total_return,
            profit_factor=profit_factor,
            max_drawdown=max_drawdown,
            sharpe_ratio=sharpe_ratio,
            trade_count=trade_count,
        )
    except ValueError as exc:
        logger.warning(
            "指标值域校验失败，跳过 upsert，保留原有值",
            strategy_id=strategy_id,
            pair=pair,
            timeframe=timeframe,
            error_message=str(exc),
        )
        return

    # Step 2: 构建 upsert 语句（需求 6.4：PostgreSQL ON CONFLICT 保证幂等）
    stmt = _build_upsert_stmt(
        strategy_id=strategy_id,
        pair=pair,
        timeframe=timeframe,
        total_return=total_return,
        profit_factor=profit_factor,
        max_drawdown=max_drawdown,
        sharpe_ratio=sharpe_ratio,
        trade_count=trade_count,
        data_source=data_source,
        last_updated_at=last_updated_at,
    )

    # Step 3: 执行 upsert，含指数退避重试（需求 6.1）
    _execute_with_retry(
        session=session,
        stmt=stmt,
        strategy_id=strategy_id,
        pair=pair,
        timeframe=timeframe,
        data_source=data_source,
        trade_count=trade_count,
    )


def _build_upsert_stmt(
    strategy_id: int,
    pair: str,
    timeframe: str,
    total_return: float | None,
    profit_factor: float | None,
    max_drawdown: float | None,
    sharpe_ratio: float | None,
    trade_count: int | None,
    data_source: DataSource,
    last_updated_at: datetime,
):  # type: ignore[no-untyped-def]
    """构建 PostgreSQL INSERT ... ON CONFLICT DO UPDATE 语句。

    回测来源：非 None 字段无条件覆盖，None 字段使用 COALESCE 保留现有值（需求 2.3, 2.4）。
    实盘来源：所有字段使用 COALESCE，不覆盖已有高质量数据（需求 3.2）。
    last_updated_at 使用时序保护：仅当新时间戳更新时才更新（需求 3.5）。
    """
    insert_values = {
        "strategy_id": strategy_id,
        "pair": pair,
        "timeframe": timeframe,
        "total_return": total_return,
        "profit_factor": profit_factor,
        "max_drawdown": max_drawdown,
        "sharpe_ratio": sharpe_ratio,
        "trade_count": trade_count,
        "data_source": data_source,
        "last_updated_at": last_updated_at,
    }

    insert_stmt = insert(StrategyPairMetrics).values(**insert_values)

    # 构建 ON CONFLICT DO UPDATE 的 set_ 参数
    table = StrategyPairMetrics.__table__
    excluded = insert_stmt.excluded

    if data_source == DataSource.BACKTEST:
        # 回测来源：非 None 字段直接用 excluded（新值），None 字段 COALESCE 保留现有
        set_dict = {
            "data_source": excluded.data_source,
            "last_updated_at": excluded.last_updated_at,
            # 非 None 字段直接覆盖；None 字段回退到现有值
            "total_return": (
                excluded.total_return
                if total_return is not None
                else func.coalesce(excluded.total_return, table.c.total_return)
            ),
            "profit_factor": (
                excluded.profit_factor
                if profit_factor is not None
                else func.coalesce(excluded.profit_factor, table.c.profit_factor)
            ),
            "max_drawdown": (
                excluded.max_drawdown
                if max_drawdown is not None
                else func.coalesce(excluded.max_drawdown, table.c.max_drawdown)
            ),
            "sharpe_ratio": (
                excluded.sharpe_ratio
                if sharpe_ratio is not None
                else func.coalesce(excluded.sharpe_ratio, table.c.sharpe_ratio)
            ),
            "trade_count": (
                excluded.trade_count
                if trade_count is not None
                else func.coalesce(excluded.trade_count, table.c.trade_count)
            ),
        }
    else:
        # 实盘来源（DataSource.LIVE）：统一 COALESCE，不覆盖已有高质量回测数据
        set_dict = {
            "data_source": excluded.data_source,
            "last_updated_at": excluded.last_updated_at,
            "total_return": func.coalesce(excluded.total_return, table.c.total_return),
            "profit_factor": func.coalesce(excluded.profit_factor, table.c.profit_factor),
            "max_drawdown": func.coalesce(excluded.max_drawdown, table.c.max_drawdown),
            "sharpe_ratio": func.coalesce(excluded.sharpe_ratio, table.c.sharpe_ratio),
            "trade_count": func.coalesce(excluded.trade_count, table.c.trade_count),
        }

    upsert_stmt = insert_stmt.on_conflict_do_update(
        index_elements=["strategy_id", "pair", "timeframe"],
        set_=set_dict,
        # 时序保护：仅当新 last_updated_at > 现有时才更新（幂等，需求 3.5）
        where=table.c.last_updated_at < excluded.last_updated_at,
    )

    return upsert_stmt


def _execute_with_retry(
    session: Session,
    stmt: object,
    strategy_id: int,
    pair: str,
    timeframe: str,
    data_source: DataSource,
    trade_count: int | None,
) -> None:
    """执行 SQL 语句，DB 连接错误时指数退避重试最多 3 次。

    Args:
        session: 同步 Session
        stmt: 待执行的 SQL 语句
        strategy_id: 用于日志
        pair: 用于日志
        timeframe: 用于日志
        data_source: 用于日志
        trade_count: 用于日志

    Raises:
        OperationalError: 重试 3 次耗尽后向上传播
    """
    last_exc: Exception | None = None

    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            session.execute(stmt)  # type: ignore[arg-type]

            # 成功：记录 INFO 日志（需求 6.5）
            logger.info(
                "策略对绩效指标 upsert 成功",
                strategy_id=strategy_id,
                pair=pair,
                timeframe=timeframe,
                data_source=data_source.value,
                trade_count=trade_count,
            )
            return

        except OperationalError as exc:
            last_exc = exc
            delay = _RETRY_BASE_DELAY_SECONDS * (2 ** (attempt - 1))  # 1s, 2s, 4s

            logger.warning(
                "DB 连接错误，准备重试",
                strategy_id=strategy_id,
                pair=pair,
                timeframe=timeframe,
                attempt=attempt,
                max_retries=_MAX_RETRIES,
                delay_seconds=delay,
                error_message=str(exc),
            )

            if attempt < _MAX_RETRIES:
                time.sleep(delay)
            # 最后一次重试后不 sleep，直接落入 error 日志

    # 重试耗尽：记录 ERROR 日志并向上传播（需求 6.1）
    logger.error(
        "DB 写入全部重试耗尽，放弃 upsert",
        strategy_id=strategy_id,
        pair=pair,
        timeframe=timeframe,
        error_message=str(last_exc),
    )
    raise last_exc  # type: ignore[misc]


# ─────────────────────────────────────────────────────────────────
# API 查询服务（Task 5.2）
# ─────────────────────────────────────────────────────────────────


class PairMetricsService:
    """策略对绩效指标异步查询服务。

    提供 API 层使用的只读查询方法：
      - list_pair_metrics：分页列表查询，按 total_return 降序
      - get_pair_metric：单条记录查询

    约束：
      - 不含任何写入逻辑，严格只读
      - 查询前验证 strategy_id 存在，不存在时抛出 NotFoundError(code=3001)
      - 使用 AsyncSession，由路由层通过 Depends(get_db) 注入

    需求可追溯：4.1, 4.4, 4.5, 4.6
    """

    async def list_pair_metrics(
        self,
        db: AsyncSession,
        strategy_id: int,
        pair_filter: str | None = None,
        timeframe_filter: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[StrategyPairMetrics], int]:
        """按 total_return 降序返回策略对绩效分页列表和总记录数。

        Args:
            db: 异步数据库 session
            strategy_id: 策略 ID
            pair_filter: 可选交易对过滤（精确匹配）
            timeframe_filter: 可选时间周期过滤（精确匹配）
            page: 页码（从 1 开始）
            page_size: 每页数量（最大 100）

        Returns:
            (metrics_list, total_count) 元组

        Raises:
            NotFoundError: 策略不存在（code=3001）
        """
        await self._verify_strategy_exists(db, strategy_id)

        # 构建过滤条件
        filters = [StrategyPairMetrics.strategy_id == strategy_id]
        if pair_filter is not None:
            filters.append(StrategyPairMetrics.pair == pair_filter)
        if timeframe_filter is not None:
            filters.append(StrategyPairMetrics.timeframe == timeframe_filter)

        # 查询总数
        count_stmt = select(func.count()).select_from(StrategyPairMetrics).where(*filters)
        count_result = await db.execute(count_stmt)
        total: int = count_result.scalar_one()

        # 查询分页数据（按 total_return DESC NULLS LAST）
        offset = (page - 1) * page_size
        stmt = (
            select(StrategyPairMetrics)
            .where(*filters)
            .order_by(StrategyPairMetrics.total_return.desc().nullslast())
            .limit(page_size)
            .offset(offset)
        )
        result = await db.execute(stmt)
        metrics: list[StrategyPairMetrics] = list(result.scalars().all())

        return metrics, total

    async def get_pair_metric(
        self,
        db: AsyncSession,
        strategy_id: int,
        pair: str,
        timeframe: str,
    ) -> StrategyPairMetrics:
        """返回单个策略对详情。

        Args:
            db: 异步数据库 session
            strategy_id: 策略 ID
            pair: 交易对
            timeframe: 时间周期

        Returns:
            StrategyPairMetrics 对象

        Raises:
            NotFoundError: 策略不存在或记录不存在（code=3001）
        """
        await self._verify_strategy_exists(db, strategy_id)

        stmt = select(StrategyPairMetrics).where(
            StrategyPairMetrics.strategy_id == strategy_id,
            StrategyPairMetrics.pair == pair,
            StrategyPairMetrics.timeframe == timeframe,
        )
        result = await db.execute(stmt)
        metric = result.scalar_one_or_none()

        if metric is None:
            raise NotFoundError(f"策略对绩效记录不存在：strategy_id={strategy_id}, pair={pair}, timeframe={timeframe}")

        return metric

    async def _verify_strategy_exists(self, db: AsyncSession, strategy_id: int) -> None:
        """验证 strategy_id 对应策略是否存在。

        Raises:
            NotFoundError: 策略不存在（code=3001）
        """
        stmt = select(Strategy.id).where(Strategy.id == strategy_id)
        result = await db.execute(stmt)
        if result.scalar_one_or_none() is None:
            raise NotFoundError(f"策略 {strategy_id} 不存在")
