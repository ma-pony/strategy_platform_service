"""任务 3：新增业务异常类及异常处理映射测试（TDD 红阶段先行）。

验证：
  - EmailConflictError(code=3010, HTTP 409)
  - LoginNotFoundError(code=1004, HTTP 401)
  - AccountDisabledError(code=1005, HTTP 403)
  - 三个异常类在 exception_handlers._ERROR_HTTP_STATUS 中注册了正确的 HTTP 状态码
"""

import pytest


class TestEmailConflictError:
    """EmailConflictError 异常类测试。"""

    def test_email_conflict_error_has_code_3010(self) -> None:
        """EmailConflictError 的 code 字段应为 3010。"""
        from src.core.exceptions import EmailConflictError

        assert EmailConflictError.code == 3010

    def test_email_conflict_error_has_default_message(self) -> None:
        """EmailConflictError 应有默认中文消息。"""
        from src.core.exceptions import EmailConflictError

        err = EmailConflictError()
        assert "邮箱" in err.message

    def test_email_conflict_error_accepts_custom_message(self) -> None:
        """EmailConflictError 应接受自定义消息。"""
        from src.core.exceptions import EmailConflictError

        err = EmailConflictError("自定义消息")
        assert err.message == "自定义消息"

    def test_email_conflict_error_is_app_error(self) -> None:
        """EmailConflictError 应继承自 AppError。"""
        from src.core.exceptions import AppError, EmailConflictError

        assert issubclass(EmailConflictError, AppError)

    def test_email_conflict_error_is_exception(self) -> None:
        """EmailConflictError 应可被 raise 和 catch。"""
        from src.core.exceptions import EmailConflictError

        with pytest.raises(EmailConflictError):
            raise EmailConflictError("邮箱已被注册")


class TestLoginNotFoundError:
    """LoginNotFoundError 异常类测试。"""

    def test_login_not_found_error_has_code_1004(self) -> None:
        """LoginNotFoundError 的 code 字段应为 1004。"""
        from src.core.exceptions import LoginNotFoundError

        assert LoginNotFoundError.code == 1004

    def test_login_not_found_error_has_default_message(self) -> None:
        """LoginNotFoundError 应有默认中文消息，包含邮箱或密码错误语义。"""
        from src.core.exceptions import LoginNotFoundError

        err = LoginNotFoundError()
        assert err.message  # 消息非空

    def test_login_not_found_error_accepts_custom_message(self) -> None:
        """LoginNotFoundError 应接受自定义消息。"""
        from src.core.exceptions import LoginNotFoundError

        err = LoginNotFoundError("自定义消息")
        assert err.message == "自定义消息"

    def test_login_not_found_error_is_app_error(self) -> None:
        """LoginNotFoundError 应继承自 AppError。"""
        from src.core.exceptions import AppError, LoginNotFoundError

        assert issubclass(LoginNotFoundError, AppError)

    def test_login_not_found_error_is_exception(self) -> None:
        """LoginNotFoundError 应可被 raise 和 catch。"""
        from src.core.exceptions import LoginNotFoundError

        with pytest.raises(LoginNotFoundError):
            raise LoginNotFoundError()


class TestAccountDisabledError:
    """AccountDisabledError 异常类测试。"""

    def test_account_disabled_error_has_code_1005(self) -> None:
        """AccountDisabledError 的 code 字段应为 1005。"""
        from src.core.exceptions import AccountDisabledError

        assert AccountDisabledError.code == 1005

    def test_account_disabled_error_has_default_message(self) -> None:
        """AccountDisabledError 应有默认中文消息，包含禁用语义。"""
        from src.core.exceptions import AccountDisabledError

        err = AccountDisabledError()
        assert "禁用" in err.message

    def test_account_disabled_error_accepts_custom_message(self) -> None:
        """AccountDisabledError 应接受自定义消息。"""
        from src.core.exceptions import AccountDisabledError

        err = AccountDisabledError("账号已被封禁")
        assert err.message == "账号已被封禁"

    def test_account_disabled_error_is_app_error(self) -> None:
        """AccountDisabledError 应继承自 AppError。"""
        from src.core.exceptions import AccountDisabledError, AppError

        assert issubclass(AccountDisabledError, AppError)

    def test_account_disabled_error_is_exception(self) -> None:
        """AccountDisabledError 应可被 raise 和 catch。"""
        from src.core.exceptions import AccountDisabledError

        with pytest.raises(AccountDisabledError):
            raise AccountDisabledError()


class TestExceptionHandlerMapping:
    """异常处理器 HTTP 状态码映射测试。"""

    def test_email_conflict_error_maps_to_409(self) -> None:
        """EmailConflictError 应映射到 HTTP 409。"""
        from src.core.exception_handlers import _ERROR_HTTP_STATUS
        from src.core.exceptions import EmailConflictError

        assert _ERROR_HTTP_STATUS.get(EmailConflictError) == 409

    def test_login_not_found_error_maps_to_401(self) -> None:
        """LoginNotFoundError 应映射到 HTTP 401。"""
        from src.core.exception_handlers import _ERROR_HTTP_STATUS
        from src.core.exceptions import LoginNotFoundError

        assert _ERROR_HTTP_STATUS.get(LoginNotFoundError) == 401

    def test_account_disabled_error_maps_to_403(self) -> None:
        """AccountDisabledError 应映射到 HTTP 403。"""
        from src.core.exception_handlers import _ERROR_HTTP_STATUS
        from src.core.exceptions import AccountDisabledError

        assert _ERROR_HTTP_STATUS.get(AccountDisabledError) == 403

    def test_new_exceptions_are_imported_in_handler(self) -> None:
        """exception_handlers 模块应能正常导入包含新异常类的配置。"""
        # 如果导入成功说明映射注册无误
        import src.core.exception_handlers as handlers

        assert hasattr(handlers, "_ERROR_HTTP_STATUS")
        assert len(handlers._ERROR_HTTP_STATUS) > 0
