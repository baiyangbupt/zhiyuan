"""E2E tests for app.util.internal_client — 需要真实内部服务连接。"""

from __future__ import annotations

import pytest

from app.util.internal_client import get_user_profile, get_user_score_detail


@pytest.mark.e2e
class TestInternalClient:
    """使用真实服务验证 internal_client 功能。"""

    async def test_get_user_profile(self):
        """测试 get_user_profile 能正常获取 chat_session_id=35 的用户画像。"""
        result = await get_user_profile(chat_session_id=35)

        # 基本响应结构校验
        assert isinstance(result, dict), f"返回值应为 dict，实际为 {type(result)}"
        assert "error" not in result, f"请求出错: {result}"

        # 业务字段校验
        assert "code" in result, f"响应缺少 code 字段: {result}"
        assert result["code"] == 0, f"响应 code 非 0: {result}"
        assert "data" in result, f"响应缺少 data 字段: {result}"

        print(f"\n获取用户画像成功:\n{result}")

    async def test_get_user_score_detail(self):
        """测试 get_user_score_detail 能正常获取 thread_id=35 的成绩详情。"""
        result = await get_user_score_detail(thread_id="35")

        # 基本响应结构校验
        assert isinstance(result, dict), f"返回值应为 dict，实际为 {type(result)}"
        assert "error" not in result, f"请求出错: {result}"

        # 业务字段校验
        assert "code" in result, f"响应缺少 code 字段: {result}"
        assert result["code"] == 0, f"响应 code 非 0: {result}"
        assert "data" in result, f"响应缺少 data 字段: {result}"

        print(f"\n获取用户成绩详情成功:\n{result}")
