from __future__ import annotations

from typing import Any

from app.gateway.contracts import TurnOutput


def synthesize_execution_status(
    output: TurnOutput, batch_report: dict[str, Any]
) -> TurnOutput:
    """Overlay observable tool status without inventing business facts."""
    status = str(batch_report.get("status") or "completed")
    if status == "completed" or output.execution_status == status:
        return output
    limitations = list(output.limitations)
    next_step = output.next_step
    if status == "partial":
        message = "工具执行部分成功，以下结果仅覆盖已成功返回的数据。"
        if message not in limitations:
            limitations.append(message)
        next_step = next_step or "确认是否继续处理未完成的查询。"
    elif status == "blocked":
        message = "部分工具步骤因缺少必要参数或前置结果未满足而未执行。"
        if message not in limitations:
            limitations.append(message)
        next_step = next_step or "请补充缺失参数后继续。"
    elif status == "failed":
        message = "工具查询失败，当前没有可确认的完整结果。"
        if message not in limitations:
            limitations.append(message)
        next_step = next_step or "请稍后重试，或调整查询条件。"
    return output.model_copy(
        update={
            "execution_status": status,
            "limitations": limitations,
            "next_step": next_step,
        }
    )
