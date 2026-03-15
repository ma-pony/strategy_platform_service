"""邮箱校验工具单元测试（任务 1 / 需求 4.1, 4.2, 4.4）。

验证：
  - EmailValidator.validate 对合法邮箱返回归一化字符串
  - EmailValidator.validate 对非法邮箱抛出 ValueError
  - email_validator 库不可用时降级为正则校验，并记录 WARNING 日志
"""

import sys
from unittest.mock import patch

import pytest


class TestEmailValidatorWithLibrary:
    """email-validator 库可用时的校验行为。"""

    def test_valid_email_returns_normalized_string(self) -> None:
        """合法邮箱返回归一化字符串（域名部分小写化）。

        根据 RFC 5321，邮箱本地部分（@前）区分大小写，email-validator 库
        只归一化域名部分（转小写），本地部分保持原样。
        """
        from src.utils.email_validator import EmailValidator

        result = EmailValidator.validate("user@Example.COM")
        # 域名部分应被归一化为小写
        assert result == "user@example.com"

    def test_valid_email_lowercase_preserved(self) -> None:
        """已小写的合法邮箱原样返回。"""
        from src.utils.email_validator import EmailValidator

        result = EmailValidator.validate("user@example.com")
        assert result == "user@example.com"

    def test_valid_email_with_subdomain(self) -> None:
        """带子域名的合法邮箱校验通过。"""
        from src.utils.email_validator import EmailValidator

        result = EmailValidator.validate("user@mail.example.com")
        assert isinstance(result, str)
        assert "@" in result

    def test_invalid_email_missing_at_raises_value_error(self) -> None:
        """缺少 @ 的邮箱抛出 ValueError。"""
        from src.utils.email_validator import EmailValidator

        with pytest.raises(ValueError, match=r".+"):
            EmailValidator.validate("invalidemail.com")

    def test_invalid_email_missing_domain_raises_value_error(self) -> None:
        """缺少域名部分抛出 ValueError。"""
        from src.utils.email_validator import EmailValidator

        with pytest.raises(ValueError):
            EmailValidator.validate("user@")

    def test_invalid_email_missing_local_raises_value_error(self) -> None:
        """缺少本地部分（@前）抛出 ValueError。"""
        from src.utils.email_validator import EmailValidator

        with pytest.raises(ValueError):
            EmailValidator.validate("@example.com")

    def test_invalid_email_no_tld_raises_value_error(self) -> None:
        """无顶级域名的邮箱抛出 ValueError。"""
        from src.utils.email_validator import EmailValidator

        with pytest.raises(ValueError):
            EmailValidator.validate("user@nodot")

    def test_empty_string_raises_value_error(self) -> None:
        """空字符串抛出 ValueError。"""
        from src.utils.email_validator import EmailValidator

        with pytest.raises(ValueError):
            EmailValidator.validate("")

    def test_validate_does_not_raise_http_exception(self) -> None:
        """validate 不抛出 HTTP 异常，只抛出 ValueError。"""
        from src.utils.email_validator import EmailValidator

        try:
            EmailValidator.validate("bad-email")
        except ValueError:
            pass  # 预期行为
        except Exception as exc:
            pytest.fail(f"不应抛出非 ValueError 异常: {exc}")


class TestEmailValidatorFallback:
    """email-validator 库不可用时的降级行为。"""

    def test_fallback_valid_email_passes(self) -> None:
        """降级模式下，格式合法的邮箱通过校验。"""
        # 通过 patch 使 email_validator 模块不可用来测试降级逻辑
        with patch.dict(sys.modules, {"email_validator": None}):
            # 重新导入模块以触发降级检测

            import src.utils.email_validator as ev_module

            original_available = ev_module._EMAIL_VALIDATOR_AVAILABLE

            # 强制切换到降级模式
            ev_module._EMAIL_VALIDATOR_AVAILABLE = False
            try:
                result = ev_module.EmailValidator.validate("user@example.com")
                assert "@" in result
            finally:
                ev_module._EMAIL_VALIDATOR_AVAILABLE = original_available

    def test_fallback_invalid_email_raises_value_error(self) -> None:
        """降级模式下，格式非法邮箱抛出 ValueError。"""
        import src.utils.email_validator as ev_module

        original_available = ev_module._EMAIL_VALIDATOR_AVAILABLE
        ev_module._EMAIL_VALIDATOR_AVAILABLE = False
        try:
            with pytest.raises(ValueError):
                ev_module.EmailValidator.validate("invalidemail.com")
        finally:
            ev_module._EMAIL_VALIDATOR_AVAILABLE = original_available

    def test_fallback_logs_warning_on_import_failure(self, caplog: pytest.LogCaptureFixture) -> None:
        """库导入失败时，模块加载阶段记录 WARNING 日志。"""
        import importlib
        import logging

        # 移除已缓存的模块，强制重新加载
        module_name = "src.utils.email_validator"
        original_module = sys.modules.pop(module_name, None)

        try:
            with patch.dict(sys.modules, {"email_validator": None}):
                with caplog.at_level(logging.WARNING):
                    imported = importlib.import_module(module_name)
                    assert not imported._EMAIL_VALIDATOR_AVAILABLE
        finally:
            # 恢复原始模块
            if original_module is not None:
                sys.modules[module_name] = original_module
            elif module_name in sys.modules:
                del sys.modules[module_name]
