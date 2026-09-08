from __future__ import annotations

from dataclasses import dataclass


ERROR_CLASSES = {
    "needs_clarification": "blocked",
    "missing_parameter": "blocked",
    "entity_not_found": "blocked",
    "no_data": "completed",
    "stale_state": "blocked",
    "backend_timeout": "failed",
    "backend_unavailable": "failed",
    "binding_not_found": "failed",
    "binding_expired": "failed",
    "tool_not_found": "failed",
}


@dataclass(frozen=True, slots=True)
class ToolErrorDecision:
    code: str
    execution_status: str
    limitation: str
    next_step: str


def classify_tool_error(code: str | None) -> ToolErrorDecision | None:
    if not code:
        return None
    normalized = str(code).strip().lower()
    status = ERROR_CLASSES.get(normalized, "failed")
    if status == "blocked":
        return ToolErrorDecision(normalized, status, "工具调用缺少必要条件，未形成可确认事实。", "请补充缺失参数或刷新当前会话状态。")
    if normalized == "no_data":
        return ToolErrorDecision(normalized, status, "当前查询范围没有返回可引用数据。", "请调整查询范围或确认是否查询其他年份/批次。")
    return ToolErrorDecision(normalized, status, "领域工具暂时不可用，当前结果不能视为完整事实。", "请稍后重试，或调整查询条件。")
