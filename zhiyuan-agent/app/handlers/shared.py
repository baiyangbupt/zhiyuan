"""Handler 共享工具函数。

从 plan_execution_tool.py 提取出多个 handler 共同使用的函数。
当前先声明接口，具体实现随各 handler 迁入时逐步填充。
"""

from __future__ import annotations

import re
from typing import Any

from pydantic_ai import RunContext

from app.agent.context import RequestContext


_VOLUNTEER_ID_LIKE_RE = re.compile(r"^[A-Za-z0-9_.:-]+$")


def latest_user_text(ctx: RunContext[RequestContext]) -> str:
    """获取当前轮最近一条用户文本。"""
    for message in reversed(ctx.deps.chat_history or []):
        if isinstance(message, dict) and message.get("role") == "user":
            return str(message.get("content") or "").strip()
    return ""


def summary_total(summary: dict[str, Any] | None) -> int:
    """从 planning state summary 提取 total。"""
    if not summary:
        return 0
    return int(summary.get("unitTotal") or summary.get("total") or 0)


def summary_target_total(summary: dict[str, Any] | None) -> int:
    """从 planning state summary 提取目标 total。"""
    if not summary:
        return 0
    return int(summary.get("targetUnitCount") or summary.get("targetCount") or 0)


def is_volunteer_id_like(text: str) -> bool:
    """判断是否是有效的 volunteerId 格式。"""
    return bool(_VOLUNTEER_ID_LIKE_RE.match(text.strip())) if text else False
