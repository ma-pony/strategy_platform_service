"""统一响应信封与错误码体系单元测试。

测试 ApiResponse、PaginatedData 模型和 ok/fail/paginated 工具函数，
以及 AppError 异常体系。
"""



class TestApiResponse:
    """ApiResponse 泛型模型测试。"""

    def test_ok_response_has_code_zero(self) -> None:
        from src.core.response import ok

        resp = ok(data={"id": 1})
        assert resp.code == 0

    def test_ok_response_default_message(self) -> None:
        from src.core.response import ok

        resp = ok(data={"id": 1})
        assert resp.message == "success"

    def test_ok_response_carries_data(self) -> None:
        from src.core.response import ok

        resp = ok(data={"id": 42, "name": "test"})
        assert resp.data == {"id": 42, "name": "test"}

    def test_ok_response_custom_message(self) -> None:
        from src.core.response import ok

        resp = ok(data=None, message="操作成功")
        assert resp.message == "操作成功"

    def test_ok_response_none_data(self) -> None:
        from src.core.response import ok

        resp = ok()
        assert resp.data is None
        assert resp.code == 0

    def test_fail_response_has_error_code(self) -> None:
        from src.core.response import fail

        resp = fail(code=1001, message="未登录")
        assert resp.code == 1001

    def test_fail_response_has_message(self) -> None:
        from src.core.response import fail

        resp = fail(code=2001, message="参数错误")
        assert resp.message == "参数错误"

    def test_fail_response_data_defaults_none(self) -> None:
        from src.core.response import fail

        resp = fail(code=3001, message="不存在")
        assert resp.data is None

    def test_fail_response_can_carry_data(self) -> None:
        from src.core.response import fail

        resp = fail(code=2001, message="校验失败", data={"field": "errors"})
        assert resp.data == {"field": "errors"}


class TestPaginatedData:
    """PaginatedData 分页结构测试。"""

    def test_paginated_response_fields(self) -> None:
        from src.core.response import paginated

        resp = paginated(items=[1, 2, 3], total=100, page=1, page_size=20)
        assert resp.code == 0
        assert resp.data is not None
        assert resp.data.items == [1, 2, 3]
        assert resp.data.total == 100
        assert resp.data.page == 1
        assert resp.data.page_size == 20

    def test_paginated_data_model_fields(self) -> None:
        from src.core.response import PaginatedData

        data: PaginatedData[str] = PaginatedData(items=["a", "b"], total=2, page=1, page_size=20)
        assert data.items == ["a", "b"]
        assert data.total == 2


class TestAppErrors:
    """AppError 及子类异常测试。"""

    def test_authentication_error_code(self) -> None:
        from src.core.exceptions import AuthenticationError

        err = AuthenticationError("未登录")
        assert err.code == 1001

    def test_permission_error_code(self) -> None:
        from src.core.exceptions import PermissionError as AppPermissionError

        err = AppPermissionError("权限不足")
        assert err.code == 1002

    def test_membership_error_code(self) -> None:
        from src.core.exceptions import MembershipError

        err = MembershipError("会员等级不足")
        assert err.code == 1003

    def test_validation_error_code(self) -> None:
        from src.core.exceptions import ValidationError as AppValidationError

        err = AppValidationError("参数错误")
        assert err.code == 2001

    def test_not_found_error_code(self) -> None:
        from src.core.exceptions import NotFoundError

        err = NotFoundError("资源不存在")
        assert err.code == 3001

    def test_conflict_error_code(self) -> None:
        from src.core.exceptions import ConflictError

        err = ConflictError("任务冲突")
        assert err.code == 3002

    def test_freqtrade_error_code(self) -> None:
        from src.core.exceptions import FreqtradeError

        err = FreqtradeError("freqtrade 调用失败")
        assert err.code == 5001

    def test_app_error_is_base_class(self) -> None:
        from src.core.exceptions import AppError, AuthenticationError, NotFoundError

        assert issubclass(AuthenticationError, AppError)
        assert issubclass(NotFoundError, AppError)

    def test_error_message_stored(self) -> None:
        from src.core.exceptions import NotFoundError

        err = NotFoundError("策略不存在")
        assert err.message == "策略不存在"

    def test_app_error_is_exception(self) -> None:
        from src.core.exceptions import AppError

        assert issubclass(AppError, Exception)
