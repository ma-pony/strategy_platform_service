"""require_admin 依赖注入单元测试（任务 10.2）。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from src.core.exceptions import PermissionError


class TestRequireAdmin:
    """require_admin 鉴权测试。"""

    @pytest.mark.asyncio
    async def test_admin_user_passes(self) -> None:
        """is_admin=True 的用户应通过校验。"""
        from src.core.deps import require_admin

        admin_user = SimpleNamespace(is_admin=True, id=1, username="admin")

        # 直接调用函数，传入 mock 用户
        result = await require_admin(current_user=admin_user)
        assert result is admin_user

    @pytest.mark.asyncio
    async def test_non_admin_user_raises(self) -> None:
        """is_admin=False 的用户应抛 PermissionError(1002)。"""
        from src.core.deps import require_admin

        normal_user = SimpleNamespace(is_admin=False, id=2, username="user")

        with pytest.raises(PermissionError) as exc_info:
            await require_admin(current_user=normal_user)
        assert exc_info.value.code == 1002

    @pytest.mark.asyncio
    async def test_user_without_is_admin_attr_raises(self) -> None:
        """没有 is_admin 属性的用户应抛 PermissionError。"""
        from src.core.deps import require_admin

        legacy_user = SimpleNamespace(id=3, username="legacy")

        with pytest.raises(PermissionError):
            await require_admin(current_user=legacy_user)
