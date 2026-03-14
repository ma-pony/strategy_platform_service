"""研报服务单元测试（任务 10.1）。

验证：
  - list_reports 分页查询，按 generated_at 降序，含关联 ReportCoin 信息
  - get_report 单条查询，不存在时抛出 NotFoundError(code=3001)
  - 不提供任何写入方法
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest


def _make_mock_report(
    id: int = 1,
    title: str = "BTC 市场研报",
    summary: str = "本报告分析 BTC 近期走势。",
    content: str = "详细内容...",
    coins: list[str] | None = None,
) -> MagicMock:
    """创建 mock ResearchReport 对象。"""
    report = MagicMock()
    report.id = id
    report.title = title
    report.summary = summary
    report.content = content
    report.generated_at = datetime(2024, 3, 14, tzinfo=timezone.utc)
    report.created_at = datetime(2024, 3, 14, tzinfo=timezone.utc)
    report.updated_at = datetime(2024, 3, 14, tzinfo=timezone.utc)

    # 关联币种
    if coins is None:
        coins = ["BTC", "ETH"]
    coin_mocks = []
    for symbol in coins:
        coin_mock = MagicMock()
        coin_mock.coin_symbol = symbol
        coin_mocks.append(coin_mock)
    report.coins = coin_mocks

    return report


class TestReportServiceListReports:
    """ReportService.list_reports 测试。"""

    @pytest.mark.asyncio
    async def test_list_reports_returns_tuple_of_list_and_count(self) -> None:
        """list_reports 应返回 (reports, total) 元组。"""
        from src.services.report_service import ReportService

        service = ReportService()
        mock_db = AsyncMock()

        count_result = MagicMock()
        count_result.scalar_one.return_value = 2

        reports = [_make_mock_report(id=1), _make_mock_report(id=2)]
        data_result = MagicMock()
        data_result.scalars.return_value.all.return_value = reports

        mock_db.execute = AsyncMock(side_effect=[count_result, data_result])

        report_list, total = await service.list_reports(mock_db, page=1, page_size=20)

        assert total == 2
        assert len(report_list) == 2

    @pytest.mark.asyncio
    async def test_list_reports_uses_pagination(self) -> None:
        """list_reports 应支持分页（page/page_size）。"""
        from src.services.report_service import ReportService

        service = ReportService()
        mock_db = AsyncMock()

        count_result = MagicMock()
        count_result.scalar_one.return_value = 50

        single_report = [_make_mock_report(id=5)]
        data_result = MagicMock()
        data_result.scalars.return_value.all.return_value = single_report

        mock_db.execute = AsyncMock(side_effect=[count_result, data_result])

        report_list, total = await service.list_reports(mock_db, page=3, page_size=5)

        assert total == 50
        assert len(report_list) == 1

    @pytest.mark.asyncio
    async def test_list_reports_returns_empty_when_no_reports(self) -> None:
        """无研报时返回 ([], 0)。"""
        from src.services.report_service import ReportService

        service = ReportService()
        mock_db = AsyncMock()

        count_result = MagicMock()
        count_result.scalar_one.return_value = 0

        data_result = MagicMock()
        data_result.scalars.return_value.all.return_value = []

        mock_db.execute = AsyncMock(side_effect=[count_result, data_result])

        report_list, total = await service.list_reports(mock_db, page=1, page_size=20)

        assert report_list == []
        assert total == 0


class TestReportServiceGetReport:
    """ReportService.get_report 测试。"""

    @pytest.mark.asyncio
    async def test_get_report_returns_report_when_found(self) -> None:
        """get_report 在找到记录时应返回 ResearchReport 对象。"""
        from src.services.report_service import ReportService

        service = ReportService()
        mock_db = AsyncMock()

        mock_report = _make_mock_report(id=1)
        execute_result = MagicMock()
        execute_result.scalar_one_or_none.return_value = mock_report

        mock_db.execute = AsyncMock(return_value=execute_result)

        report = await service.get_report(mock_db, report_id=1)

        assert report.id == 1

    @pytest.mark.asyncio
    async def test_get_report_raises_not_found_when_missing(self) -> None:
        """get_report 在记录不存在时应抛出 NotFoundError(code=3001)。"""
        from src.core.exceptions import NotFoundError
        from src.services.report_service import ReportService

        service = ReportService()
        mock_db = AsyncMock()

        execute_result = MagicMock()
        execute_result.scalar_one_or_none.return_value = None

        mock_db.execute = AsyncMock(return_value=execute_result)

        with pytest.raises(NotFoundError) as exc_info:
            await service.get_report(mock_db, report_id=999)

        assert exc_info.value.code == 3001

    @pytest.mark.asyncio
    async def test_report_service_has_no_write_methods(self) -> None:
        """ReportService 不暴露任何写入方法（无 create/update/delete）。"""
        from src.services.report_service import ReportService

        service = ReportService()
        assert not hasattr(service, "create_report")
        assert not hasattr(service, "update_report")
        assert not hasattr(service, "delete_report")
