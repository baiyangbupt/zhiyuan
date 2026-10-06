"""统一前后端事件合同（protocolVersion=1）。

这份合同的作用是把"用户看到什么"从"运行时发生了什么"里切出来：
下游只认白名单里的类型，任何原生形状里的额外字段都到不了前端。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


PROTOCOL_VERSION = 1

# 主设计 §5 的固定白名单。**不是示例列表**：任何不在这里的字符串都不该被发出去，
# 所以它同时是类型约束（UiEvent）和适配器的过滤器。
EVENT_TYPES: frozenset[str] = frozenset(
    {
        "turn.started",
        "turn.phase",
        "tool.progress",
        "understanding.preview",
        "clarification.requested",
        "clarification.resolved",
        "proposal.preview",
        "conversationAction.result",
        # **助手增量文本是"可丢弃的提示"** ✓✓：它只负责降低"首字延迟感知" ✓，
        # 丢一条不影响正确性 ✓——答案的**权威来源**始终是终态 `assistant.completed` ✓
        #（重连不补播增量 ✓，端子文本胜出 ✓）。载荷 `{chunk, itemId?}` ✓。
        "assistant.delta",
        "assistant.completed",
        "turn.completed",
        "recoverable.error",
        "session.resync",
    }
)

# 给用户看的阶段标签。**只解释正在发生的操作，不推测用户意图**——
# 所以这里是"正在查询历年录取"而不是"我理解你想查录取"。
TOOL_LABELS: dict[str, str] = {
    "entity.resolve": "正在确认院校专业",
    "catalog.search_schools": "正在检索院校",
    "catalog.get_school": "正在读取院校信息",
    "catalog.search_majors": "正在检索专业",
    "catalog.get_major": "正在读取专业信息",
    "admission.get_history": "正在查询历年录取",
    "admission.get_plan": "正在查询招生计划",
    "admission.get_enrollment_plan": "正在读取招生专业计划",
    "admission.get_current_plan": "正在读取当前方案",
    # 别名与本体**必须同一个标签**：它们是同一个工具，前端看到两个说法会以为
    # 这是两件事（这也是 `_ADMISSION_SHAPED_TOOLS` 用显式集合而不是前缀的原因）。
    "planning.get_working_plan": "正在读取当前方案",
    "admission.check_eligibility": "正在核对选科要求",
    "admission.compare": "正在并列比较",
    "catalog.list_batches": "正在读取批次",
    "catalog.get_batch_options": "正在读取批次编码",
    "catalog.get_subject_options": "正在读取科目编码",
    "catalog.list_admission_units": "正在读取招生单元",
    "admission.get_charter": "正在读取招生章程",
    "recommendation.preview_candidates": "正在预览候选",
}


@dataclass(frozen=True)
class SessionKey:
    """业务隔离边界。

    注意这里**没有** threadId：thread 是运行/审计身份，会随进程重启改变，
    一个易失的标识符不能承载安全语义（台账 2026-09-13 已裁决）。
    """

    tenant_id: str
    session_id: str


class UiEvent(BaseModel):
    """已编号的出站事件。编号由事件存储分配，不在这里生成。"""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    protocol_version: Literal[1] = Field(default=PROTOCOL_VERSION, alias="protocolVersion")
    type: str
    session_id: str = Field(alias="sessionId")
    turn_id: str = Field(alias="turnId")
    stream_epoch: str = Field(alias="streamEpoch", min_length=1)
    sequence: int = Field(ge=1)
    payload: dict[str, Any]

    @field_validator("type")
    @classmethod
    def _type_must_be_known(cls, value: str) -> str:
        if value not in EVENT_TYPES:
            raise ValueError(f"unknown_ui_event_type:{value}")
        return value


def resync_snapshot(
    *,
    session_id: str,
    turn_id: str,
    stream_epoch: str,
    baseline: dict[str, Any],
) -> dict[str, Any]:
    """断线重连的控制快照。

    它刻意**不是** UiEvent：`sequence` 允许为 0，且不经过普通追加路径——
    它重置基线，而不是接在基线后面。把它塞进同一条流水会让重连变成"再等一分钟"。
    """
    return {
        "protocolVersion": PROTOCOL_VERSION,
        "type": "session.resync",
        "sessionId": session_id,
        "turnId": turn_id,
        "streamEpoch": stream_epoch,
        "sequence": 0,
        "payload": {"baseline": baseline},
    }
