from __future__ import annotations

from typing import Any

from app.gateway.contracts import TurnOutput
from app.engine.tool_errors import classify_tool_error


# 严重度只用于比较，不用于展示。数值本身没有业务含义。
_SEVERITY = {"completed": 0, "partial": 1, "blocked": 2, "failed": 3}


def synthesize_execution_status(
    output: TurnOutput, batch_report: dict[str, Any]
) -> TurnOutput:
    """叠加可观测的工具状态，但不发明业务事实。

    **只降不升**：工具跑成功不能把用户诉求判成"完成"。
    `executionStatus` 回答的是"用户的诉求满足了吗"，工具批次状态回答的是
    "这些调用成功了吗"——两个不同的问题。用后者覆盖前者，就会出现
    "用户要求读+写，系统只做了读、拒了写，然后报告 completed"这种结果。
    工具失败把 completed 拉低是允许的（那是真的观测）；反过来是撒谎。
    """
    tool_status = str(batch_report.get("status") or "completed")
    if tool_status == "completed" and not batch_report.get("steps"):
        return output
    status = output.execution_status
    if _SEVERITY.get(tool_status, 0) > _SEVERITY.get(status, 0):
        status = tool_status
    limitations = list(output.limitations)
    next_step = output.next_step
    decisions = [
        classify_tool_error(step.get("error"))
        for step in batch_report.get("steps", [])
        if isinstance(step, dict) and step.get("error")
    ]
    decisions = [decision for decision in decisions if decision is not None]
    if decisions:
        for decision in decisions:
            if decision.limitation not in limitations:
                limitations.append(decision.limitation)
        next_step = next_step or decisions[0].next_step
    # 文案按 `tool_status`（观测），状态字段按上面合并后的 `status`（诉求）。
    # 两者共用一个键会让"模型说 blocked、工具其实全成功"时凭空多出一句
    # "部分工具步骤未执行"——那是编造观测。
    if tool_status == "partial":
        message = "工具执行部分成功，以下结果仅覆盖已成功返回的数据。"
        if message not in limitations:
            limitations.append(message)
        next_step = next_step or "确认是否继续处理未完成的查询。"
    elif tool_status == "blocked":
        message = "部分工具步骤因缺少必要参数或前置结果未满足而未执行。"
        if message not in limitations:
            limitations.append(message)
        next_step = next_step or "请补充缺失参数后继续。"
    elif tool_status == "failed":
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
