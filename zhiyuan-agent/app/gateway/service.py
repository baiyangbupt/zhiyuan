from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import logging
import math
import time
import uuid
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from functools import wraps
from typing import Any

from pydantic import ValidationError

from app.domain.career_slots import normalize_career_labels
from app.gateway.artifact_store import ArtifactStoreError
from app.gateway.contracts import (
    CareerUpdateRequest,
    ConversationTurnSnapshot,
    IntentDraft,
    ProposalRequest,
    ScoreUpdateRequest,
    TurnOutput,
)
from app.gateway.intent_draft import build_change_set
from app.gateway.event_adapter import adapt_codex_item, adapt_notification
from app.gateway.output_validation import (
    OutputContractError,
    merge_evidence,
    validate_turn_output,
)
from app.gateway.evidence_verification import Decision, classify
from app.gateway.conversation_actions import (
    CAREER_UPDATE_KIND,
    UPDATE_CAREER_TYPES,
    ConversationActionResult,
    execute_conversation_action,
)
from app.gateway.snapshot import build_snapshot, diff_snapshots
from app.gateway.journey import (
    context_text as journey_context_text,
    from_snapshot as journey_from_snapshot,
    turn_journey_result,
)
from app.gateway.thread_recovery import ThreadRecovery, ThreadRecoveryError
from app.harness.client import AppServerExited
from app.gateway.ui_events import SessionKey
from app.gateway.session_lifecycle import SessionLifecycle
from app.gateway.session_runtime import SessionRuntime
from app.engine.working_set import ConversationWorkingSet
from app.engine.execution_plan import build_execution_plan
from app.engine.tool_orchestration import render_tool_contracts
from app.engine.turn_trace import build_turn_trace
from app.engine.result_synthesis import synthesize_execution_status
from app.util import internal_client

logger = logging.getLogger(__name__)


TURN_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": [
        "responseType",
        "message",
        "artifactRefs",
        "evidenceRefs",
        "admissionFacts",
        "uncertainties",
        "limitations",
        "clarification",
        "nextStep",
        "executionStatus",
        "proposalRef",
        "proposalRequest",
        "conversationAction",
    ],
    "properties": {
        "responseType": {
            "type": "string",
            "enum": ["text", "fact", "recommendation", "review", "clarification"],
        },
        "message": {"type": "string"},
        "artifactRefs": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "artifactId": {"type": "string"},
                    # 契约是 `Literal['candidate','comparison','plan_draft','review']`。
                    # 只写 `"type": "string"` 时模型**从来不知道**允许值，只能猜——
                    # 实测它猜了 `"plan"`，整条 `TurnOutput` 校验失败，而现象看起来
                    # 像"模型没按契约输出"（P2d）。
                    "artifactType": {
                        "type": "string",
                        "enum": ["candidate", "comparison", "plan_draft", "review"],
                    },
                    "stateVersion": {"type": "integer"},
                },
                "required": ["artifactId", "artifactType", "stateVersion"],
                "additionalProperties": False,
            },
        },
        "evidenceRefs": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "evidenceId": {"type": "string"},
                    "sourceLevel": {
                        "type": "string",
                        "enum": ["authoritative", "computed", "planner_experience"],
                    },
                    "dataVersion": {"type": "string"},
                    # 契约是 `Literal['major','major_group'] | None`，**enum 里必须带上 None**：
                    # JSON Schema 的 `type` 与 `enum` 是**合取**——只写 `type` 允许 null，
                    # 枚举仍会把合法的 `null` 判非法（2026-09-23 复核用 jsonschema 实测），
                    # 于是"证据没有招生模式"这种合法输出反而被模型侧 schema 拒掉。
                    # 这正是 P2d 修的那类「schema 与契约不一致」，别在反方向再犯一次。
                    "admissionMode": {
                        "type": ["string", "null"],
                        "enum": ["major", "major_group", None],
                    },
                    "admissionUnitId": {"type": ["string", "null"]},
                    "groupCode": {"type": ["string", "null"]},
                    "algorithmVersion": {"type": ["string", "null"]},
                    "stateVersion": {"type": ["integer", "null"]},
                    "scope": {
                        "type": "object",
                        "properties": {
                            "kind": {"type": "string"},
                            "areaId": {"type": ["string", "null"]},
                            "province": {"type": ["string", "null"]},
                            "subjectType": {"type": ["string", "null"]},
                            "batch": {"type": ["string", "null"]},
                            "year": {"type": ["integer", "null"]},
                            "majorId": {"type": ["string", "null"]},
                            "schoolId": {"type": ["string", "null"]},
                        },
                        "required": [
                            "kind",
                            "areaId",
                            "province",
                            "subjectType",
                            "batch",
                            "year",
                            "majorId",
                            "schoolId",
                        ],
                        "additionalProperties": False,
                    },
                    "observedAt": {"type": ["string", "null"]},
                    "limitations": {"type": "array", "items": {"type": "string"}},
                },
                "required": [
                    "evidenceId",
                    "sourceLevel",
                    "dataVersion",
                    "admissionMode",
                    "admissionUnitId",
                    "groupCode",
                    "algorithmVersion",
                    "stateVersion",
                    "scope",
                    "observedAt",
                    "limitations",
                ],
                "additionalProperties": False,
            },
        },
        "admissionFacts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "admissionUnitId": {"type": "string"},
                    "admissionMode": {"type": "string", "enum": ["major", "major_group"]},
                    "schoolId": {"type": "string"},
                    "schoolName": {"type": ["string", "null"]},
                    "majorId": {"type": ["string", "null"]},
                    "majorName": {"type": ["string", "null"]},
                    # `groupCode` 允许 `null` 且**就该是 null**：数据源不返回
                    # 专业组代码（候选行没有这一列、Java `groupCode` 从未被赋值）。
                    # 契约侧 2026-10-09 已把"major_group 必须带组代码"拿掉，
                    # schema 这里保持 null 合法即可；模型**不要**为了填满字段
                    # 去编一个组代码（指令侧同口径）。
                    "groupCode": {"type": ["string", "null"]},
                    "majorItems": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "majorId": {"type": "string"},
                                "majorName": {"type": ["string", "null"]},
                                "majorCode": {"type": ["string", "null"]},
                                "majorAdmissionRate": {"type": "number"},
                            },
                            "required": [
                                "majorId",
                                "majorName",
                                "majorCode",
                                "majorAdmissionRate",
                            ],
                            "additionalProperties": False,
                        },
                    },
                    "unitAdmissionRate": {"type": "number"},
                    "riskTier": {"type": "string", "enum": ["冲", "稳", "保"]},
                    "dataVersion": {"type": ["string", "null"]},
                    "algorithmVersion": {"type": ["string", "null"]},
                    "observedAt": {"type": ["string", "null"]},
                    "limitations": {"type": "array", "items": {"type": "string"}},
                },
                "required": [
                    "admissionUnitId",
                    "admissionMode",
                    "schoolId",
                    "schoolName",
                    "majorId",
                    "majorName",
                    "groupCode",
                    "majorItems",
                    "unitAdmissionRate",
                    "riskTier",
                    "dataVersion",
                    "algorithmVersion",
                    "observedAt",
                    "limitations",
                ],
                "additionalProperties": False,
            },
        },
        "uncertainties": {"type": "array", "items": {"type": "string"}},
        "limitations": {"type": "array", "items": {"type": "string"}},
        "clarification": {"type": ["string", "null"]},
        "nextStep": {"type": ["string", "null"]},
        "executionStatus": {
            "type": "string",
            "enum": ["completed", "partial", "blocked", "failed"],
        },
        "proposalRef": {"type": ["string", "null"]},
        "proposalRequest": {"anyOf": [{"$ref": "#/$defs/ProposalRequest"}, {"type": "null"}]},
        "conversationAction": {
            "type": "object",
            "properties": {
                "actionType": {
                    "type": "string",
                    "enum": ["none", "request_clarification", "continue_readonly", "create_proposal", "confirm_proposal", "cancel_proposal", "refresh_proposal"],
                },
                "proposalRef": {"type": ["string", "null"]},
                "expectedSourceVersion": {"type": ["integer", "null"]},
                "intent": {"type": "string", "enum": ["explicit", "inferred", "not_applicable"]},
            },
            "required": ["actionType", "proposalRef", "expectedSourceVersion", "intent"],
            "additionalProperties": False,
        },
    },
    "additionalProperties": False,
}


def _strict_model_schema(model: type[Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    schema = model.model_json_schema(by_alias=True)
    definitions = schema.pop("$defs", {})
    for definition in definitions.values():
        if definition.get("type") == "object":
            definition["required"] = list(definition.get("properties", {}))
            definition.pop("default", None)
    schema["required"] = list(schema.get("properties", {}))
    schema.pop("default", None)
    return schema, definitions


_proposal_schema, _proposal_definitions = _strict_model_schema(ProposalRequest)
TURN_OUTPUT_SCHEMA["$defs"] = _proposal_definitions
TURN_OUTPUT_SCHEMA["properties"]["proposalRequest"] = {
    "anyOf": [_proposal_schema, {"type": "null"}]
}

# 补录成绩草稿（score_update 动作族）：与提案同一条纪律——模型侧 schema 必须**先声明**
# 它，`additionalProperties: false` 的严格 schema 不会因为契约新增字段就放行 ✗
#（不声明的话模型一输出 `scoreUpdateRequest` 就被自己的 schema 拒，现象是"模型从不
# 产出补录草稿"，看不出是 schema 漏字段）。
_score_update_subject_schema, _score_update_definitions = _strict_model_schema(ScoreUpdateRequest)
TURN_OUTPUT_SCHEMA["$defs"].update(_score_update_definitions)
TURN_OUTPUT_SCHEMA["required"].append("scoreUpdateRequest")
TURN_OUTPUT_SCHEMA["properties"]["scoreUpdateRequest"] = {
    "anyOf": [_score_update_subject_schema, {"type": "null"}]
}

# 发展方向草稿（career v1「完整落库」）：同样必须**先声明**进严格 schema——
# `additionalProperties: false` 不会因为契约新增字段就放行（症状是"模型从不产出
# 方向草稿"，与补录那条同款）。字段 description 一并进 schema：模型从这里读到
# 四类规范标签的口径（弱偏好语义也在 description 里，见契约）。
_career_update_schema, _career_update_definitions = _strict_model_schema(CareerUpdateRequest)
TURN_OUTPUT_SCHEMA["$defs"].update(_career_update_definitions)
TURN_OUTPUT_SCHEMA["required"].append("careerUpdateRequest")
TURN_OUTPUT_SCHEMA["properties"]["careerUpdateRequest"] = {
    "anyOf": [_career_update_schema, {"type": "null"}]
}

# 完整意图草稿（Batch B）：模型把一句话里的所有要求一次说清；不写业务状态。
_intent_draft_schema, _intent_draft_definitions = _strict_model_schema(IntentDraft)
TURN_OUTPUT_SCHEMA["$defs"].update(_intent_draft_definitions)
TURN_OUTPUT_SCHEMA["required"].append("intentDraft")
TURN_OUTPUT_SCHEMA["properties"]["intentDraft"] = {
    "anyOf": [_intent_draft_schema, {"type": "null"}]
}


def _normalize_nullable_for_upstream(schema: dict[str, Any]) -> dict[str, Any]:
    """把 ``anyOf: [X, {"type": "null"}]`` 改写成 DeepSeek ``/responses`` 接受的等价写法。

    上游实测约束（T003 步骤 1 探测表）：
    1. ``anyOf`` 分支里出现 ``$ref`` 时该节点必须带 ``type``，而带 ``type: "object"`` 的节点必须有
       非空 ``properties``；
    2. ``type`` 数组只接受 ``string`` / ``number`` / ``integer`` / ``boolean`` / ``null``，不接受
       ``object`` / ``array``。

    于是三类可空节点分别改写为：标量 → 类型数组；``$ref`` → ``$def`` 自身声明
    ``["object", "null"]`` 后用裸 ``$ref``；内联对象 → 把对象自身的键提升到同层，``anyOf`` 原样保留。

    只改表达形式：可空性、``enum`` / ``minimum`` / ``exclusiveMinimum`` 等约束一律保留；
    ``required`` 覆盖全部 ``properties`` 的性质由 ``_strict_model_schema()`` 保证，此处不触碰。
    """
    definitions = schema.get("$defs", {})

    def rewrite(node: Any) -> Any:
        if isinstance(node, dict):
            for key, value in list(node.items()):
                node[key] = rewrite(value)
            any_of = node.get("anyOf")
            if not isinstance(any_of, list) or len(any_of) != 2:
                return node
            branches = [item for item in any_of if item != {"type": "null"}]
            if len(branches) != 1 or not isinstance(branches[0], dict):
                return node
            branch = branches[0]
            if "$ref" in branch:
                definition = definitions.get(str(branch["$ref"]).rsplit("/", 1)[-1])
                if definition is not None:
                    definition["type"] = ["object", "null"]
                node.pop("anyOf")
                node.update(branch)
            elif branch.get("type") == "object":
                node.update({**branch, "anyOf": any_of})
            elif isinstance(branch.get("type"), str):
                node.pop("anyOf")
                node.update({**branch, "type": [branch["type"], "null"]})
            return node
        if isinstance(node, list):
            for index, value in enumerate(node):
                node[index] = rewrite(value)
        return node

    rewrite(schema)
    return schema


_normalize_nullable_for_upstream(TURN_OUTPUT_SCHEMA)


# 文本回合里模型**可以直接执行**的动作类型：只有确认/取消有执行器
# （`conversation_actions.execute_conversation_action` ✓——与点卡路径用的是同一份 ✓）。
# 其余类型没有执行语义：提案走 `proposalRequest` ✓、澄清走 `clarification` 字段 ✓、
# `refresh_proposal` / `create_proposal` 只是模型的一句话（今天没有对应的执行器 ✓）——
# 把它们送去执行只会得到一串 `not_executable` 的噪声结果 ✗。
EXECUTABLE_CONVERSATION_ACTIONS: frozenset[str] = frozenset(
    {"confirm_proposal", "cancel_proposal"}
)


def _turn_action_payload(action_result: Any, snapshot_version: Any) -> dict[str, Any]:
    """把已产出的动作结果挂进**任何**返回路径（成功/失败/异常）✓。

    执行一旦出站，结果就是"这次写入算不算数"的唯一凭据 ✓（与
    `execute_action_and_refresh` 的 docstring 是同一条不变量 ✓）——之后任何一步
    （working set、trace、合成的收尾）失败，都不许把它带走 ✗。
    """
    if not isinstance(action_result, Mapping) or not action_result:
        return {}
    payload: dict[str, Any] = {"actionResult": dict(action_result)}
    if snapshot_version is not None:
        payload["actionSnapshotVersion"] = snapshot_version
    return payload


def _active_proposal_preview_override(
    preview: Mapping[str, Any], active: Any
) -> dict[str, Any]:
    """把预览的**身份与版本**换成"待确认那一条"的值（提案/补录两族共用同一口径）。

    为什么必须换 ✗：Java 编译返回的预览带的是**编译前**的 `sourceVersion` ✗，而确认/放弃
    时服务端拿快照里 `activeProposal.sourceVersion` 与动作里的 `expectedSourceVersion`
    相减 ✓，不等就 `proposal_version_mismatch` ✗；身份同理——卡片必须带 `pendingId` ✗，
    不是编译器的 `ugp_…` ✗，否则确认第一步就 `proposal_reference_mismatch` ✗。
    `active_proposal` 是**模型不是 dict** ✗（实测按字典读一次都没命中 ✓），所以字典键与
    属性两条路都走 ✓，别名（驼峰/snake）也各试一次 ✓。
    """

    def _field(*names: str) -> Any:
        if isinstance(active, Mapping):
            for name in names:
                if active.get(name) is not None:
                    return active[name]
            return None
        for name in names:
            value = getattr(active, name, None)
            if value is not None:
                return value
        return None

    override = dict(preview)
    source_version = _field("sourceVersion", "source_version")
    if source_version is None:
        active_data = active.get("data") if isinstance(active, Mapping) else None
        if isinstance(active_data, Mapping):
            source_version = (
                active_data.get("sourceVersion")
                or active_data.get("source_version")
                or active_data.get("sourceBackendVersion")
                or active_data.get("source_backend_version")
            )
    if source_version is not None:
        override["sourceVersion"] = source_version
    active_ref = _field("proposalRef", "proposal_ref", "pendingId", "pending_id")
    if active_ref:
        override["proposalRef"] = str(active_ref)
    return override


# 规则域 → 用户看得懂的中文（只给"被拒的死卡"用：`blocked` 卡上的 `blockingReason`
# 是 Java 的校验原文 ✓，用户读不出"它本来想调整什么" ✗）。
_RULE_DOMAIN_LABELS = {
    "region": "地域",
    "major": "专业",
    "school": "院校",
    "admission": "录取档位",
}


def _attempted_rule_brief(request: ProposalRequest) -> str | None:
    """把模型**实际发出的**规则（requirements + priorityRules）翻成一句人话。

    为什么在网关侧生成 ✓：`blocked` 预览里的 `blockingReason` 来自 Java 校验器 ✗
    （"同档前置规则：暂不支持非排他覆盖要求字段：location.xxx" ✓），而"模型本来想
    调整什么"只有**我们发出去的那份 `userGoalRequest`** 知道 ✓——Java 不背这个包袱 ✗
    （改 Java 要动拒单文案的既有语义 ✗），前端也不该去解析内部字段名 ✗。
    形状（示例）："地域：北方/北京/上海/广州/深圳；专业：临床医学"。
    取不到规则就返回 None（**不造字段** ✓：空字符串只会让卡片多一行空白 ✗）。
    """
    briefs: list[str] = []
    for rule in (*request.priority_rules, *request.requirements):
        label = _RULE_DOMAIN_LABELS.get(rule.domain, rule.domain)
        values = "/".join(value for value in rule.values if value)
        briefs.append(f"{label}：{values}" if values else label)
    return "；".join(briefs) if briefs else None


def _score_update_summary_text(summary: Mapping[str, Any]) -> str:
    """补录卡的一句话摘要（给人看的那份，全部来自 Java 按**合并后**成绩算的 summary）。"""
    parts: list[str] = []
    if summary.get("provinceName"):
        parts.append(str(summary["provinceName"]))
    if summary.get("subjectType"):
        parts.append(str(summary["subjectType"]))
    if summary.get("batchName"):
        parts.append(str(summary["batchName"]))
    if summary.get("examYear") is not None:
        parts.append(f"{summary['examYear']} 年")
    if summary.get("totalScore") is not None:
        parts.append(f"总分 {summary['totalScore']}")
    if summary.get("totalScorePos") is not None:
        parts.append(f"位次 {summary['totalScorePos']}")
    subjects = summary.get("subjects")
    if isinstance(subjects, list):
        rendered = "、".join(
            f"{item.get('subjectName') or item.get('subject') or '科目'} {item.get('score')}"
            for item in subjects
            if isinstance(item, Mapping) and item.get("score") is not None
        )
        if rendered:
            parts.append(rendered)
    return " · ".join(parts)


# 补录被 Java 拒时的通用描述：只在 Java **没有**回 msg 时才用它兜底（原文优先）。
_SCORE_UPDATE_DEFAULT_REJECTION = "Java score update preview rejected the request"

# 回合失败时回给用户的通用文案（不泄漏内部细节）。
_RECOVERABLE_TURN_FAILURE = "当前对话引擎暂时不可用，请稍后重试。"

# **唯一**会把内部错误原文带上用户面的前缀：补录预览/执行的业务拒绝。Java 的 110
# 原文（"请选择批次后再创建会话"/"非标准选科编码"…）是**可行动的**：它告诉用户/模型
# 缺的是什么、下一步查什么。2026-10-06 实测里它被通用文案吞掉，用户连"缺批次"都读不出来。
_SCORE_UPDATE_ERROR_PREFIX = "score_update_unavailable:"


def _recoverable_turn_reply(error: Any) -> str:
    """失败回给用户的那句话：默认通用文案，**唯**放行补录的业务拒绝原文。"""
    text = str(error or "")
    if text.startswith(_SCORE_UPDATE_ERROR_PREFIX):
        detail = text[len(_SCORE_UPDATE_ERROR_PREFIX):].strip()
        if detail and detail != _SCORE_UPDATE_DEFAULT_REJECTION:
            return detail
    return _RECOVERABLE_TURN_FAILURE


# 注入上下文里机器可读块的内部分隔标签（2026-10-06）。
#
# 事故：模型把「规划阶段也从「ordered」推进到「profile_ready」」原样讲给用户。
# 根源不是模型"不听话"——快照/state_patch/执行计划/工具契约每轮都以裸 JSON 或
# 半结构化文本注入，读起来和"可以转述的内容"没有区别。这里给每个机器块套上
# 显式边界 + 紧邻的转述纪律，让"这段是内部状态、只能翻译成业务语言"成为
# 注入内容本身的一部分（base_instructions 第 10 条是另一道闸）。
#
# 块内内容**逐字不变**：模型仍要看到真值（版本、缺口、候选、约束），只是被
# 明确标记为不可原样转述。
INTERNAL_STATE_OPEN_TAG = "【内部状态（机器格式，禁止原样转述给用户）】"
INTERNAL_STATE_CLOSE_TAG = "【内部状态结束】"
INTERNAL_STATE_REMINDER = (
    "以上是内部状态，只能用业务语言转述给用户；不要原样输出其中的字段名、枚举值、"
    "版本号或内部标识。"
)


def _internal_state_block(text: str) -> str:
    """把一段机器可读上下文包进内部分隔标签，并附上紧邻的转述纪律。"""
    return (
        f"{INTERNAL_STATE_OPEN_TAG}\n{text}\n{INTERNAL_STATE_CLOSE_TAG}\n"
        f"{INTERNAL_STATE_REMINDER}"
    )


# 用户消息正文的显式分隔（2026-10-13，"短消息被读成空"事故）。
#
# 事故形状：4 块【内部状态】都带标签，最后一条**裸文本**恰恰是用户消息（"1"、"好"）——
# 短消息挂在大段机器文本末尾时，模型会把它读成机器块的尾注、"这一轮没有新消息"，
# 于是自我否读。即"有标签的是机器内容、没标签的反倒像内部尾注"：边界单边清晰，
# 反而把用户那一侧衬成了可忽略的。
#
# 修法=把用户正文也框起来：开标签点明"这是本轮唯一需要回应的内容"，两侧都有边界，
# 最后一条的归属不再需要模型自己猜。与 `INTERNAL_STATE_*` 互斥使用（机器块 vs 用户正文），
# 内容**逐字不变**（同款纪律：只加边界，不动真值）。
#
# 只在**用户消息**上用；续接 nudge 有自己的 `CONTINUATION_*` 标签（它是系统指令、
# 不是用户消息），套上"用户消息"标记会让两套标签的语义互相污染。
USER_MESSAGE_OPEN_TAG = "【以下是用户消息原文（本轮唯一需要回应的内容）】"
USER_MESSAGE_CLOSE_TAG = "【用户消息结束】"


def _user_message_block(text: str) -> str:
    """把用户正文包进显式分隔标签，正文本身逐字不变。"""
    return f"{USER_MESSAGE_OPEN_TAG}\n{text}\n{USER_MESSAGE_CLOSE_TAG}"


# 确认生效后的**自动续接**（2026-10-09，用户实测：会话 10041981 里助手先承诺了
# "确认成绩后我先按方向给你几个院校专业组参考…" ✓，用户点确认后只收到一句写死的
# "操作已处理。" ✗——话头断了 ✓）。续接回合的输入是一条**内部指令**：它不是用户
# 消息 ✓（所以不落 user 消息、不进会话 transcript 的用户那一侧 ✓），只是告诉模型
# "刚才那个确认已经生效，按你上文的承诺接着做"。
#
# 与 `INTERNAL_STATE_*` 是**两套标签** ✗✓：那一套说的是"机器状态，转述成业务语言"；
# 这一条是**给模型的行动指令**（继续干活），语义不同就不共用标签——
# 混在一起会让"内部状态"这个标记失去它唯一的意思。
CONTINUATION_OPEN_TAG = "【内部续接指令（系统自动生成，不是用户消息）】"
CONTINUATION_CLOSE_TAG = "【内部续接指令结束】"


def _continuation_nudge(action_result: Mapping[str, Any]) -> str:
    """续接回合的内部提示：说明"确认已生效"，要求**主动走下一步**。"""
    ref = str(action_result.get("proposalRef") or "").strip()
    ref_clause = f"（本条对应 {ref}）" if ref else ""
    return (
        f"{CONTINUATION_OPEN_TAG}\n"
        f"用户刚才的确认**已经生效**，改动已经写入{ref_clause}。"
        "这一段不是用户发来的消息，是系统在确认生效后自动触发的续接指令。\n"
        "请接着你上一条回复里对用户的承诺，主动把下一步**做出来**（该查的查、该给的给），"
        "不要停在「已确认」「已生效」这句话上。\n"
        "纪律：① 不要重复已经完成或已经说过的内容，也不要再让用户确认同一件事"
        "（这张已经生效，对同一引用再发确认只会被拒）；"
        "② 需要用户表态时用**封闭式**提问（给 2-4 个明确选项）；"
        "③ 如果你上一条回复并没有承诺下一步，就用一两句话说明已生效，"
        "并把明确的下一步选择摆给用户；"
        "④ 这段是内部指令：不要原样转述它，也不要输出其中的字段名或内部标识。\n"
        f"{CONTINUATION_CLOSE_TAG}"
    )


def _continuation_nudge_failed(action_result: Mapping[str, Any]) -> str:
    """续接回合的内部提示（**失败版**）：说明"确认收到、执行没成功"，要求**如实解释 + 给替代路径**。

    2026-10-13 实测（会话 10041981）："学费≤2 万"优先规则 preview=ready ✓、用户打字确认 ✓，
    apply 却以 `409 priority_target_not_in_plan: 当前方案没有命中优先目标` 失败 ✗——失败后
    **没有任何助手跟话** ✗，用户只见一张失败卡，观感=割裂/报错 ✓。失败同样得接住话头 ✓。

    与生效版只差一个前提 ✓，但这个前提要命 ✗✓：那一版说"已经生效、接着往下做"；
    这一版必须说"**没有生效**"，并把**后端给的原因原样喂进来** ✓（`code: message` ✓）——
    原因不给到，模型只能猜 ✗，而"猜失败原因"正是最容易编出错误解释的地方 ✗✗。
    转述纪律照旧 ✓：模型看得见错误码，用户不该看见 ✗（翻成业务语言 ✓）。
    """
    ref = str(action_result.get("proposalRef") or "").strip()
    ref_clause = f"（本条对应 {ref}）" if ref else ""
    code = str(action_result.get("code") or "").strip()
    message = str(action_result.get("message") or "").strip()
    reason = f"{code}: {message}" if code and message else (code or message or "后端未给出具体原因")
    return (
        f"{CONTINUATION_OPEN_TAG}\n"
        f"用户刚才的确认**执行失败**，本次改动没有生效{ref_clause}。"
        f"后端给出的原因：{reason}。"
        "这一段不是用户发来的消息，是系统在确认执行失败后自动触发的续接指令。\n"
        "请主动接住这一轮，把失败讲清楚、把路给出来：\n"
        "① **如实解释**刚才这一步为什么没成——把上面的原因翻成用户能懂的业务语言"
        "（不原样甩错误码/字段名，也不许含糊带过；原因里读不出的细节不要编造，"
        "就按这个原因的直白含义说明）；"
        "② 给出**替代路径**：放宽口径（把范围放小一点或换相近条件）、换一种做法"
        "（换个顺序，比如先补进方案再设优先）、先补数据（先把缺的目标选进来）——"
        "挑最贴合用户诉求的一到两种，并说清每种大概会得到什么；"
        "③ 不要重复已经说过的内容，也不要把责任推回给用户（别暗示「你没说清楚」）；"
        "④ 需要用户表态时用**封闭式**提问（给 2-4 个明确选项）；"
        "⑤ 不要原样重发同一个提案——同样的口径再来一次还会失败；用户要的若是原方向，"
        "先把口径谈拢（放宽/换方向/先筛）再动；"
        "⑥ 这段是内部指令：不要原样转述它，也不要输出其中的字段名或内部标识。\n"
        f"{CONTINUATION_CLOSE_TAG}"
    )


# J1：固定错误码的用户文案（不进修复回合）。server.py 的失败分支优先用 `reply`。
_FIXED_TURN_REPLIES = {
    "pending_applying": "上一条变更正在生效，请稍候；结果会以回执为准。",
}

_CONTINUATION_FAILURE_REPLY = (
    "刚才的确认已经生效。接下来这一步我没能自动接上——"
    "你回一句「继续」，我就接着往下做。"
)
# 失败版续接自己又失败时的措辞：**不能说"已生效"** ✗（本次执行就是没成功 ✓）；
# 说清"哪一步没成" + 给一个用户零成本的动作（回一句「继续」→ 普通用户回合 ✓）。
_CONTINUATION_FAILURE_REPLY_FAILED = (
    "刚才这一步没能执行成功，本次改动没有生效。"
    "详细的解释和替代做法我没能自动接上——你回一句「继续」，我就接着说清楚。"
)
# 续接的幂等台账上限（同一个操作只续一次 ✓）：按到达顺序裁掉最旧的，
# 台账只是"别重复触发"的短期记忆，不是审计账本。
_CONTINUATION_LEDGER_MAX = 2048


# ── 预览结局跟话：这一轮**没有生成可确认的卡片**时，助手的收尾必须被纠正 ──────────
#
# 2026-10-13 用户实测（会话 10041981，20:22 ✓）：用户选了三所学校 ✓，模型回复
# "我把它们和「学费一年 3 万以内」合成一件事，**提交给你确认了**……点卡片或回复确认" ✓，
# 而本轮 `proposal.preview` 的真实结局是 `info` ✓（"当前方案里已经有 3 个专业组……
# 本轮不需要调整方案" ✓，**无按钮** ✓）——用户被引向一个**不存在的确认动作** ✗✗。
# 同族历史：更早的多规则场景里 blocked 卡而文案称"待确认"（review §五-19/23 异常 B ✓）。
#
# 触发源与 applied/failed 两版**不同** ✗✓：那两版从**动作结果**
# （`conversationAction.result` ✓）触发 ✓；这一版从**回合内的预览结局**触发 ✓——
# 回合收尾时它已经在 `result["proposalPreview"]["status"]` 里 ✓
# （server.py 收尾发 `proposal.preview` 事件读的就是同一处 ✓），
# 判据挂在 `_maybe_continue_after_preview`（server.py ✓）这一处 ✓。
_PREVIEW_CONTINUATION_STATUSES = frozenset({"blocked", "info", "preview_only"})

# 三种结局各自的**事实**与**动线**（写给模型看，由它翻成用户语言 ✓）。
# `ready` 不在表里 ✓：那是有可确认卡片的正常路径 ✓，模型收尾说"点卡确认"是对的 ✓
# ——那条路一个字节都不动 ✗✓（`applied` 同此 ✓）。
_PREVIEW_OUTCOME_FACTS = {
    "info": "本轮提案想做的事，**方案里已经满足了**（后端结论原文：{reason}）"
    "——本轮**没有产生任何需要调整的改动**，也**没有生成可确认的卡片**",
    "blocked": "本轮提案**被校验拒绝了**（后端原因原文：{reason}）"
    "——这件事**没有落成待确认**，也**没有生成可确认的卡片**",
    "preview_only": "本轮只给出了**参考预览**（后端说明原文：{reason}）"
    "——它**仅供参考、不能确认落地**，也**没有生成可确认的卡片**",
}

_PREVIEW_OUTCOME_NEXT_STEPS = {
    "info": "这一轮不需要做任何调整——把结论说清（哪些要求已经满足、方案现在是什么样），"
    "再问用户接下来想看什么；",
    "blocked": "说明为什么这次没成，并给出替代路径（放宽口径 / 换个顺序 / 分步来），"
    "挑最贴合用户诉求的一到两种；",
    "preview_only": "说明这次只是参考预览、要真正落地需要先把口径谈拢，"
    "并给出可执行的下一步（例如把口径确认下来后重新整理一次）；",
}


def _preview_outcome_nudge(preview: Mapping[str, Any]) -> str:
    """预览没有生成可确认卡片时的内部跟话指令：**如实纠正收尾** + 讲清结局 + 给动线。

    与 `_continuation_nudge*` 同一族 ✓（同一对 `CONTINUATION_*` 标签 ✓、同样
    `content_is_user_message=False` ✓），差别只在**要纠正的事实**：那两版的前提是
    "用户做了确认动作" ✓，这一版的前提是"用户拿不到可确认的卡，而助手可能刚刚
    让他去点卡" ✗✓。原因原文必须喂进来 ✓（同 `_continuation_nudge_failed` 的道理 ✓：
    不给原因，模型只能猜 ✓，而"猜结局"正是最容易再造一遍谎话的地方 ✗✗）。
    """
    status = str(preview.get("status") or "").strip().lower()
    reason = str(
        preview.get("blockingReason") or preview.get("summary") or preview.get("title") or ""
    ).strip()
    fact = (_PREVIEW_OUTCOME_FACTS.get(status) or _PREVIEW_OUTCOME_FACTS["preview_only"]).format(
        reason=reason or "后端未给出具体说明"
    )
    next_step = (
        _PREVIEW_OUTCOME_NEXT_STEPS.get(status) or _PREVIEW_OUTCOME_NEXT_STEPS["preview_only"]
    )
    return (
        f"{CONTINUATION_OPEN_TAG}\n"
        f"本轮提案的**真实结局**：{fact}。\n"
        "这一段不是用户发来的消息，是系统在「本轮没有生成可确认的卡片」之后自动触发的跟话指令。\n"
        "请接住这一轮，把收尾纠正过来、把路指出来：\n"
        "① **如实纠正收尾**：如果你上一条回复里让用户「点卡片确认」「回复确认」"
        "「提交给你确认了」（或任何让用户去做确认动作的说法），而**实际并没有可确认的卡片**——"
        "请明确纠正这一点（例如「这一轮其实没有需要你确认的卡片」），"
        "**不要重复那条确认指令**，也不要装作已经提交给用户确认了；\n"
        "② **说清真实结局**：把上面的结局翻成用户能懂的业务语言"
        "（不要原样甩状态名、字段名或错误码；原因里读不出的细节不要编造）；\n"
        f"③ **给出下一步动线**：{next_step}\n"
        "④ 不要原样重发同一个提案——同样的口径再来一次结局不会变；"
        "也不要停在「已提交」「待确认」这类话术上；\n"
        "⑤ 需要用户表态时用**封闭式**提问（给 2-4 个明确选项）；\n"
        "⑥ 这一段是内部指令：不要原样转述它，也不要输出其中的字段名或内部标识。\n"
        f"{CONTINUATION_CLOSE_TAG}"
    )


# 预览跟话**自己**没跑起来时的措辞：不许说"已提交/待确认" ✗（这一轮本来就没有卡 ✓），
# 只如实说"没有可确认的卡片" + 给一个零成本动作（回「继续」→ 普通用户回合 ✓）。
_PREVIEW_CONTINUATION_FAILURE_REPLY = (
    "刚才这一轮的提案预览没有生成可确认的卡片。"
    "接下来这一步的说明我没能自动接上——你回一句「继续」，我就接着说清楚。"
)


def _maybe_await(value: Any) -> Any:
    return value if inspect.isawaitable(value) else _Immediate(value)


def _session_key(tenant_id: str | int, session_id: str | int) -> SessionKey:
    """本进程所有会话级缓存的键。

    两个租户的 sessionId 相同**不是**同一个用户，所以 key 必须带上租户。
    这就是为什么这里返回的是 SessionKey 而不是 str——字符串键会让
    `session_id=42` 在两个租户之间悄悄共享同一份快照和同一个 thread。
    """
    return SessionKey(tenant_id=str(tenant_id), session_id=str(session_id))


_REPAIR_OUTPUT_EXCERPT_LIMIT = 1500

# 引用失效提案的动作被拒（`proposal_reference_mismatch`）时的修复提示。
#
# 2026-10-09 真事故（会话 10041980，18:46 与 19:05 连续两轮同族失败）：模型在文本
# 回合里对一张**已失效的提案卡**反复发 confirm → 网关校验判
# `proposal_reference_mismatch` → 整轮硬失败（`recoverable=False`）→ 模型**收不到
# 任何纠错反馈** → 下一次用户消息它继续确认同一张死卡，用户被卡死。只丢一个错误码
# 不够——要把"这张卡已经不是当前有效的了、该往哪走"讲给它，修复回合才有可执行的
# 修改目标（与 schema 修复同一条道理）。
_PROPOSAL_REFERENCE_REPAIR_HINT = (
    "你引用的提案不是当前有效提案（可能已被替换或失效）。不要再对这个引用发起确认/取消，"
    "也不要重复同一个动作。请三选一：①仍要确认，就改用本轮注入的内部状态里当前有效的提案"
    "引用与版本；②重新发起提案（proposalRequest / create_proposal）；③直接向用户如实说明"
    "这张提案已失效、需要重新发起，不要声称已提交。"
)

# 招生事实对不上证据（`admission_evidence_missing` / `admission_mode_mismatch`）时的修复提示。
#
# 2026-10-13 真事故（会话 10041981，18:51:49 与 18:55:19 连续两轮同族硬失败）：模型把
# `recommendation.preview_candidates` 候选行里的 `entityId`/`volunteerId` 直接当成
# `admissionFacts[].admissionUnitId` 填了（实测 `43020271000088_43020272000269`、
# `43020271000538_43020272001410`）。那个 `A_B` 形状**本身是合法的**——它是"专业+大学"
# 那条链的**方案行键**（Java `PlanningStateService.canonicalMajorVolunteerId`：
# `planSchoolDataId + "_" + majorId`；`WorkingPlanMutationSupport.resolveWorkingPlanUnitId`
# 取第一个 `_` 之前那段当单元号）——但它**不是招生单元号**：招生单元（`schoolUnitId`/
# 招生单位编号）是单值（`PlanMajorFilterNode` 末层、`queryPlanMajorData` 入参），
# `A_B` 是"单元_专业行"。两条链（院校专业组 / 专业+大学）的证据里 unit id 长什么样，
# 模型都只能**照证据填**。这两轮里 `preview_candidates` 都已成功返回但**没有签发任何
# 证据**（`evidenceRefs` 空数组），模型等于拿方案行键给无证据的事实凑了个 id → 与本回合
# 证据永远对不上 → 硬失败（`recoverable=False`），用户只看到"对话引擎暂时不可用"。
# 问题不在工具，而在模型输出的 fact 构造与证据绑定——与 proposal 一族同病：模型收不到
# "哪条事实被拒、为什么"，下一轮还会照旧填。所以同样**先给一次修复回合**。
# 口径是"**与证据同套同值**"（不是简单禁拼接）：证据是哪套 ID 就填哪套、逐字相等才许勾；
# 今天两套链的 unit id 都是单值，候选行的 `A_B` 只有与证据逐字相同时才合法。
# `admission_mode_mismatch` 是同一形态的另一扇门（fact/证据的模式写错），处置方式相同
# （改对/删掉），一并纳入；其余校验失败照旧直接硬失败。
_ADMISSION_EVIDENCE_REPAIR_HINT = (
    "你输出里的招生事实（admissionFacts）没有匹配到本回合证据。硬规则：每条事实必须匹配"
    "本回合输出 evidenceRefs 里的一条**真实存在**的证据（引用的 evidenceId 必须在账本里）："
    "admissionMode 与本会话快照一致，admissionUnitId 与证据里的那个值**逐字相等**"
    "（证据是哪套 ID 逻辑就填哪套、同值才许勾上），groupCode 两边都有时必须一致。"
    "候选名单行（preview_candidates 等）的 entityId/volunteerId 是 `_` 拼接的**方案行定位键**"
    "（形如 43020271000088_43020272000269：前半是院校计划行、后半是专业行），**不是**招生"
    "单元号；除非某条证据的 admissionUnitId 本身就是这个值（那就像其他值一样逐字照抄），"
    "否则不得拿它当 unit id，也不得把两个单元拼成一条。请三选一：①跨单元/拼接的汇总拆成"
    "逐条事实，每条与各自证据同值，并在 evidenceRefs 里补上对应证据引用（证据 id 抄本回合"
    "工具结果里真实签发的那条，不要编造）；②事实的单元或模式写错了就更正为与证据一致的值；"
    "③没有对应证据的事实直接删掉——不要为了让事实留下而拼 id 或编证据。"
)

# 同档前置"只支持一条"（2026-10-13 实测，会话 10041981）：模型把多层偏好
# （"地域：北京；院校：财经；地域：上海/广州/深圳"）塞进**一次提案**的
# `priorityRules` → Java `PriorityRuleSupport.validate()` 拒单（"当前只支持一条
# 同档前置规则；多个有先后层级的优先目标需要先明确顺序"）→ `blocked` 死卡，
# 用户走不通。处置与 832c53c 同族：先给**一次**修复回合让它自纠。它**不在**
# `_REPAIR_HINT_BY_CODE` 里：那条回路修不好会硬失败，而这里修不好必须**维持
# 原行为**（原请求照发 Java、照旧出 blocked 卡）——所以单列常量，由提案分支
# 的守卫（`_repair_priority_rule_count`）使用：采纳成功才替换本轮输出。
_PRIORITY_RULE_COUNT_REPAIR_HINT = (
    "你本轮 proposalRequest 的 priorityRules 给了多条同档前置规则；"
    "**同档前置每次只支持一条规则**，多条会整单被后端拒绝、用户拿到一张走不通的死卡。"
    "请三选一：①只保留最重要的一条 priorityRule（其余偏好后续轮次再推进），"
    "其余的用正文说明会分步处理；②如果这些偏好本身有先后层级（先地域后院校等），"
    "也可以不带提案、先向用户确认顺序，再按顺序分步推进；③确实不需要前置时，"
    "干脆不带 priorityRules。goalType 等其余字段保持不变，不要调用工具、不要编造事实。"
)

# 产物引用被拒的修复提示（2026-10-15 §41）。被拒的形态有二：跨会话/跨租户的章
# （**不修**——那是越权，改不掉也不许改）、以及"引用不在账本里/版本对不上"（可以
# 修：照抄本会话真实签发的 id，或**重新调只读工具**拿一份新的）。允许重调工具的
# 那一支对应 `_LEDGER_REBUILD_REPAIR_CODES` 的账本重建——不重建的话，重签的产物
# 在旧账本里查不到，修复回合修了也照挂。
_ARTIFACT_REF_REPAIR_HINT = (
    "你输出里的产物引用（artifactRefs）没有对上产物账本。硬规则：引用的 artifactId 必须"
    "来自**本会话真实签发**的产物（工具结果里 `artifacts` 那条记录，带 tenantId/sessionId/"
    "stateVersion 的章）——不得自己编造 id、不得改写 id 形状、不得引用别的会话的产物，"
    "也不得用它并未在工作区版本内签发过的版本号。请二选一：①本会话真实签发过、且版本与"
    "当前工作区一致的那份，就**原样照抄**它的 artifactId/artifactType/stateVersion；"
    "②手头没有有效引用（例如工作区版本已经推进、旧产物过期）时，**允许调用只读工具重新"
    "获取**，把工具结果里新签发的产物 id 原样填进 artifactRefs（推荐类输出必须带引用，"
    "不能留空）。**关键：引用列表里只要还留着一条旧版本引用，整份输出仍会被拒**——"
    "先把所有版本与当前工作区不一致的旧引用**删掉**，只保留本回合重新签发的；"
    "只补新的、不删旧的等于没修。仍不确定时，如实向用户说明当前没有可引用的产物，不要编造。"
)

# 先给一次修复回合、修不好再维持硬失败的校验码 → 对应的修复提示（一次、不循环）。
# 三类："模型对提案状态的声明与网关状态不符"（引用对不上/版本过旧）；"招生事实/
# 证据的声明与账本不符"（证据缺失/模式写错）；"产物引用与产物账本不符"（不在账本/
# 章对不上/版本过期）。其余校验失败（一致性/范围…）保持原样：直接硬失败，不修
# （它们要么不可修复，要么不属于本回路的处置范围）。
# 点名加入（add_units）的 sourceVersionGuard 修复提示（2026-10-17）。
_PROPOSAL_SOURCE_VERSION_REPAIR_HINT = (
    "你的 proposalRequest.sourceVersionGuard 不是当前快照版本（点名加入 add_units 的版本守门）。"
    "不要改动用户目标或 exactTargets；重新读取本轮内部状态里的当前版本，把 sourceVersionGuard "
    "改成该值后重新输出。不要重复提交旧版本，也不要把 goalType 改成别的类型。"
)

_REPAIR_HINT_BY_CODE = {
    "proposal_reference_mismatch": _PROPOSAL_REFERENCE_REPAIR_HINT,
    "proposal_version_mismatch": _PROPOSAL_REFERENCE_REPAIR_HINT,
    "proposal_source_version_mismatch": _PROPOSAL_SOURCE_VERSION_REPAIR_HINT,
    "admission_evidence_missing": _ADMISSION_EVIDENCE_REPAIR_HINT,
    "admission_mode_mismatch": _ADMISSION_EVIDENCE_REPAIR_HINT,
    "artifact_scope_violation": _ARTIFACT_REF_REPAIR_HINT,
    "artifact_not_found": _ARTIFACT_REF_REPAIR_HINT,
    "artifact_mismatch": _ARTIFACT_REF_REPAIR_HINT,
    # 2026-10-17 真事故（10041984 "继续"回合）：模型同时引用了旧产物（v1）和本回合
    # 新签发的产物（v5）——新引用没能抵消旧引用，整轮被判 stale_state 硬失败。
    # stale_state 与 artifact_mismatch 是同一族（版本对不上），必须允许重签/删旧。
    "stale_state": _ARTIFACT_REF_REPAIR_HINT,
}
_REPAIRABLE_CONTRACT_CODES = frozenset(_REPAIR_HINT_BY_CODE)
# 修复回合**允许重调工具**、修完必须重建账本的码：只有产物引用这一族（重签发的产物
# 只会进"按最新载荷重建"的账本；证据侧的提示写死了"不要编造/重查走核验回路"，
# 维持原样不重建，见 `_repair_priority_rule_count` 的同款说明）。
_LEDGER_REBUILD_REPAIR_CODES = frozenset({
    "artifact_scope_violation", "artifact_not_found", "artifact_mismatch", "stale_state",
})


def _agent_message_text(item: Any) -> str | None:
    """从一个事件 item 里取 agent 最终文本；不是 agentMessage 就返回 None。"""
    if not isinstance(item, Mapping):
        return None
    if item.get("type") not in (None, "agentMessage"):
        return None
    text = item.get("text")
    if isinstance(text, str) and text.strip():
        return text
    return None


def _last_agent_text(turn_payload: Any) -> str | None:
    """取上一回合**最后一段原始 agent 文本**（修复回合要把坏文本摆给模型看）。

    2026-10-06 真事故：模型在 JSON 字符串值里写了未转义的 `"`，harness 解析
    失败 → `output_missing` → 修复回合只拿到一句 issue，看不到自己写坏的那段
    文本，于是又写坏一遍。这里把原文找回来（形状兜底：终态事件自带的 item、
    `collected.events` 里的 agentMessage item/completed、事件适配后的
    `payload.message`），取**最后一个**——重查等场景下多个回合的事件拼在一起，
    最后那段才是模型刚写的。
    """
    if not isinstance(turn_payload, Mapping):
        return None
    found = _agent_message_text(turn_payload.get("item"))
    events = turn_payload.get("events")
    if isinstance(events, list):
        for event in events:
            if not isinstance(event, Mapping):
                continue
            text = _agent_message_text(event.get("item"))
            if text is not None:
                found = text
                continue
            payload = event.get("payload")
            if isinstance(payload, Mapping) and isinstance(payload.get("message"), str):
                if payload["message"].strip():
                    found = payload["message"]
    return found


def _repair_output_excerpt(raw_output: str | None) -> str | None:
    """修复提示里随附的上一回合原文：最多 1500 字符（超出截断，提示里注明）。"""
    if raw_output is None:
        return None
    text = raw_output.strip()
    if not text:
        return None
    return text[:_REPAIR_OUTPUT_EXCERPT_LIMIT]


class _Immediate:
    def __init__(self, value: Any) -> None:
        self.value = value

    def __await__(self):
        async def _return():
            return self.value

        return _return().__await__()


def _snapshot_payload(payload: Any) -> ConversationTurnSnapshot:
    if isinstance(payload, ConversationTurnSnapshot):
        return payload
    if isinstance(payload, Mapping) and "data" in payload and "sessionId" not in payload:
        payload = payload.get("data")
    return build_snapshot(payload)


def _by_id(values: Any, *keys: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    if isinstance(values, Mapping):
        return {str(key): value for key, value in values.items()}
    for value in values or []:
        if isinstance(value, Mapping):
            for key in keys:
                identifier = value.get(key)
                if identifier:
                    result[str(identifier)] = value
                    break
        else:
            identifier = getattr(value, keys[0], None)
            if identifier:
                result[str(identifier)] = value
    return result


def _collect_records(payload: Any, *record_keys: str) -> list[dict[str, Any]]:
    """Collect tool records from both turn payloads and nested App Server events."""
    records: list[dict[str, Any]] = []
    visited: set[int] = set()
    seen_record_keys: set[str] = set()
    # `visited` 用**对象身份**去重，就必须保证被访问过的对象活到遍历结束：
    # 解析 JSON 字符串会临时造出对象，它们一旦被回收，`id()` 会被下一个临时对象
    # 复用 → 第二条证据的包裹体被误判成"已遍历过"而整条跳过。实测就是这样丢的
    # （三条工具结果里只进账本一条，而模型引用的恰好是被丢的那条）。
    keepalive: list[Any] = []

    def walk_json_string(value: str) -> None:
        """MCP 工具结果是 `{"content": [{"type": "text", "text": "<JSON>"}]}`。

        证据在那个 **JSON 字符串**里。以前只遍历 dict/list，于是工具签发的证据
        永远进不了账本：模型引用它 → `evidence_not_found` → 整轮 fail closed。
        表现是"带证据的最终答案"从来没通过，而链路上只看得到一句
        evidence_not_found——查不出证据其实一直在工具结果里。
        """
        text = value.strip()
        if len(text) < 2 or text[0] not in "{[":  # 不是 JSON 的字符串一律跳过
            return
        try:
            parsed = json.loads(text)
        except (ValueError, TypeError):
            return
        keepalive.append(parsed)  # 见上面 keepalive 的说明：不持有就会撞 id() 复用
        walk(parsed)

    def add(candidate: Any) -> None:
        """同一条记录只进一次账本。

        一条证据既是一个"记录"（带 evidenceId），又挂在某个记录键下，
        两条路径都会遇到它；不去重的话"引用了 N 条证据"这个计数就是假的。
        """
        if not isinstance(candidate, Mapping):
            return
        key = str(
            candidate.get("evidenceId")
            or candidate.get("evidence_id")
            or candidate.get("artifactId")
            or candidate.get("artifact_id")
            or ""
        )
        if key:
            if key in seen_record_keys:
                return
            seen_record_keys.add(key)
        records.append(dict(candidate))

    def walk(value: Any) -> None:
        if isinstance(value, str):
            walk_json_string(value)
            return
        if isinstance(value, Mapping):
            identity = id(value)
            if identity in visited:
                return
            visited.add(identity)
            if value.get("evidenceId") or value.get("evidence_id") or value.get("artifactId") or value.get("artifact_id"):
                add(value)
            for key in record_keys:
                nested = value.get(key)
                if isinstance(nested, Mapping):
                    add(nested)
                elif isinstance(nested, list):
                    for item in nested:
                        add(item)
            for nested in value.values():
                walk(nested)
        elif isinstance(value, list):
            for nested in value:
                walk(nested)

    walk(payload)
    return records


# **增量文本的合流/节流参数**（任务书口径：≥80ms 或 ≥64 字符 flush 一次）。
# 选值理由：
# · 64 字符：真实 codex 的 delta 是**逐字**切的（实测 239 条共 378 字符，均长 ≈1.6）——
#   不合并的话，一次长回答会往事件存储灌上千条 1–2 字符的事件（每条都要走一遍
#   Redis Lua 原子追加 + WS 帧 + 前端 reducer）。64 字符把"可读的一段"当最小单位；
#   首条仍然**立即**发出（见 `push`），首字延迟不受节流影响。
# · 80ms：≈12.5 条/秒的上限，打字机观感不变，却把逐字事件摊平成 ~12 倍少的条数。
# · 2048 字符单条截断：事件存储单条上限 16KB（`event_store.max_event_bytes`，含 64B 信封余量）。
#   合并后的缓冲上界 = 63（未达阈值）+ 2048（被截断后的单条最大入账）≈ 2111 字符；
#   按中文 UTF-8 3 字节/字算 ≈6.3KB，离 16KB 仍有一个数量级的余量。
#   （delta 是**可丢弃的提示**：真出现超长原生增量被截断，丢的也只是提示，终态兜底。）
DELTA_FLUSH_SECONDS = 0.08
DELTA_FLUSH_CHARS = 64
DELTA_MAX_CHUNK_CHARS = 2048
# 原生终态方法名（`app/harness/codex.py` 的 `_TERMINAL_TYPE_MAP` 同一组）。
_TURN_TERMINAL_METHODS = frozenset({"turn/completed", "turn/failed", "turn/interrupted"})


class _DeltaStreamer:
    """`assistant.delta` 的合并/节流器（时钟**可注入**，单测据此确定性断言）。

    规则（全部在**通知到达**时判定，不引入后台定时器——回调跑在模型 reader 的关键
    路径上，定时器会把"事件顺序"变成两条时间线）：

    · `push`：累积增量；够 64 字符、或距上次 flush 够 80ms、或**首条**（`_last_flush_at`
      为空）就发一条。首条立即发，首字延迟不被节流吃掉。
    · `maybe_flush`：旁路通知（推理增量、token 用量…）打点用——够阈值才发。
    · `flush_now`：无条件发（换 `itemId` 前、发别的 UI 事件前、终态通知到达时）——
      保证**后到的工具进度/终态不会插到先到的答案文本前面**。
    · 一条事件只描述一个 `itemId`（前端按 itemId 归并）：换 item 先 flush。

    终态**不在这里发**：`assistant.completed` 由回合 worker 发一次，并且是**权威**——
    这里发出去的每条增量都只是可丢弃的提示（重连不补播，终态整段替换）。
    """

    def __init__(
        self,
        emit: Callable[[dict[str, Any]], Awaitable[None]],
        *,
        now: Callable[[], float] = time.monotonic,
    ) -> None:
        self._emit = emit
        self._now = now
        self._pending: list[str] = []
        self._chars = 0
        self._item_id = ""
        self._last_flush_at: float | None = None

    def _should_flush(self) -> bool:
        if not self._pending:
            return False
        if self._last_flush_at is None or self._chars >= DELTA_FLUSH_CHARS:
            return True
        return (self._now() - self._last_flush_at) >= DELTA_FLUSH_SECONDS

    async def push(self, payload: Mapping[str, Any]) -> None:
        chunk = str(payload.get("chunk") or "")
        if not chunk:
            return
        if len(chunk) > DELTA_MAX_CHUNK_CHARS:
            chunk = chunk[:DELTA_MAX_CHUNK_CHARS]
        item_id = str(payload.get("itemId") or "")
        if item_id and self._pending and item_id != self._item_id:
            await self.flush_now()
        if item_id:
            self._item_id = item_id
        self._pending.append(chunk)
        self._chars += len(chunk)
        if self._should_flush():
            await self.flush_now()

    async def maybe_flush(self) -> None:
        if self._should_flush():
            await self.flush_now()

    async def flush_now(self) -> None:
        if not self._pending:
            return
        chunk = "".join(self._pending)
        self._pending.clear()
        self._chars = 0
        self._last_flush_at = self._now()
        payload: dict[str, Any] = {"chunk": chunk}
        if self._item_id:
            payload["itemId"] = self._item_id
        await self._emit({"type": "assistant.delta", "payload": payload})


def _progress_emitter(
    emit: Callable[[dict[str, Any]], Awaitable[None]] | None,
    ui_turn_id: str,
    *,
    now: Callable[[], float] = time.monotonic,
) -> Callable[[dict[str, Any]], Awaitable[None]] | None:
    """把原生通知适配成展示事件后交给 `emit`。

    这个回调跑在**模型 reader 的关键路径**上：它不 await 浏览器。调用方拿到事件后
    应当写进队列/事件存储就返回，慢消费者由发送侧自己处理（超限断连并让它 resume）。

    `assistant.delta` 在这里**合流/节流**（`_DeltaStreamer`）：逐字增量先攒进缓冲，
    够 64 字符或 80ms 才入一条事件；任何别的 UI 事件（工具进度等）发出前先把缓冲
    按序放出来。它只是"可丢弃的提示"——终态 `assistant.completed` 才是权威文本。
    """
    if emit is None:
        return None
    # **`turn.phase` 要有人发** ✓✓：白名单里一直有它 ✓、前端 reducer 也在等它 ✓
    #（`conversationSession.mjs:51-52` ✓），全仓却**没有任何生产者** ✗——阶段永远是空的 ✓。
    # 最小实现：**首次**工具进度到达时补一条（阶段就是"正在调工具/取数" ✓，标签用
    # 第一个工具自己的标签 ✓——`TOOL_LABELS` 是"只解释正在发生的操作" ✓）。
    # 只发一次：重查轮复用同一个 emitter ✓（`collect_kwargs` ✓），阶段不会被重复播报 ✓。
    phase_sent = False
    streamer = _DeltaStreamer(emit, now=now)

    async def callback(notification: dict[str, Any]) -> None:
        nonlocal phase_sent
        method = str(notification.get("method") or "") if isinstance(notification, Mapping) else ""
        events = adapt_notification(notification, ui_turn_id)
        if events and events[0].get("type") == "assistant.delta":
            await streamer.push(events[0].get("payload") or {})
            return
        if events or method in _TURN_TERMINAL_METHODS:
            # 要发别的 UI 事件 / 已到原生终态：先把已积累的答案文本按序放出来
            #（终态之后再不会有增量，尾部提示别烂在缓冲里；它仍会被权威终态整段替换）。
            await streamer.flush_now()
        else:
            # 旁路通知（推理增量、用量更新…）：只做阈值打点——推理 token 很密，
            # 拿它当"无条件 flush"的话节流就形同虚设。
            await streamer.maybe_flush()
        if not phase_sent:
            first_tool = next(
                (event for event in events if event.get("type") == "tool.progress"), None
            )
            if first_tool is not None:
                phase_sent = True
                await emit({
                    "type": "turn.phase",
                    "payload": {
                        "phase": "querying",
                        "status": "started",
                        "label": (first_tool.get("payload") or {}).get("label") or "",
                    },
                })
        for event in events:
            await emit(event)

    return callback


@dataclass(frozen=True)
class _CachedTurn:
    result: dict[str, Any]
    input_digest: str
    expires_at: float


def _session_owner(kind: str, *, key_argument: bool = False):
    def decorate(method):
        @wraps(method)
        async def owned(self, *args, **kwargs):
            key = (
                self._as_session_key(kwargs["key"] if "key" in kwargs else args[0])
                if key_argument
                else _session_key(kwargs.get("tenant_id", 1), kwargs["session_id"])
            )
            with self.lifecycle.acquire(key, kind):
                return await method(self, *args, **kwargs)
        return owned
    return decorate


class GatewayService:
    """Orchestrate one conversation turn behind a stable Gateway contract."""

    def __init__(
        self,
        *,
        mode: str,
        codex: Any,
        legacy: Any,
        message_store: Any,
        binding_loader: Callable[..., Any],
        snapshot_loader: Callable[..., Any],
        session_runtime: Any | None = None,
        lifecycle: SessionLifecycle | None = None,
        base_instructions: str = "",
        developer_instructions: str = "",
        current_binding_loader: Callable[..., Any] | None = None,
        evidence_verifier: Callable[..., Any] | None = None,
        artifact_store: Any | None = None,
        task_ledger: Any | None = None,
        turn_cache_max_entries: int = 1024,
        turn_cache_ttl_seconds: float = 3600.0,
        turn_cache_clock: Callable[[], float] = time.monotonic,
    ) -> None:
        # `codex_write`（P2）：允许写闭环的模式。它与 readonly 的差别**不在模型能调什么**
        # ——写路径由"模型出提案（proposalRequest）→ Java 编译出 pending → 用户确认 →
        # 网关执行（pending/resolve → pending-command/execute）"承担，模型始终没有
        # 可以自己调用的写工具（P2 任务书二之二的形状）。模式名的意义是让部署侧
        # 明确"这个实例的确认链是活的"，并与只读实例分开配置。
        if mode not in {"legacy", "codex_shadow", "codex_readonly", "codex_write"}:
            raise ValueError("unsupported gateway mode")
        if (
            not isinstance(turn_cache_max_entries, int)
            or isinstance(turn_cache_max_entries, bool)
            or turn_cache_max_entries <= 0
        ):
            raise ValueError("turn_cache_max_entries must be a positive integer")
        if not math.isfinite(turn_cache_ttl_seconds) or turn_cache_ttl_seconds <= 0:
            raise ValueError("turn_cache_ttl_seconds must be positive and finite")
        self.mode = mode
        self.codex = codex
        self.legacy = legacy
        self.message_store = message_store
        self.binding_loader = binding_loader
        self.snapshot_loader = snapshot_loader
        self.current_binding_loader = current_binding_loader
        # P1c-2：证据核验器。None ＝ 不核验（本地最小栈、单测），是显式的选择而不是
        # "忘了接"；有它的时候，模型每引用一次证据都要去问一次 Java 台账。
        self.evidence_verifier = evidence_verifier
        runtime_lifecycle = session_runtime.lifecycle if isinstance(session_runtime, SessionRuntime) else None
        if lifecycle is not None and runtime_lifecycle is not None and lifecycle is not runtime_lifecycle:
            raise ValueError("gateway/session runtime lifecycle mismatch")
        self.lifecycle = lifecycle or runtime_lifecycle or SessionLifecycle()
        self.session_runtime = session_runtime
        self.base_instructions = base_instructions
        self.developer_instructions = developer_instructions
        self._threads: dict[SessionKey, str] = {}
        self._snapshots: dict[SessionKey, ConversationTurnSnapshot] = {}
        self._working_sets: dict[SessionKey, ConversationWorkingSet] = {}
        self.artifact_store = artifact_store
        self.task_ledger = task_ledger
        self._turn_cache_max_entries = turn_cache_max_entries
        self._turn_cache_ttl_seconds = turn_cache_ttl_seconds
        self._turn_cache_clock = turn_cache_clock
        self._turn_cache: OrderedDict[tuple[SessionKey, str], _CachedTurn] = OrderedDict()
        self._session_locks: dict[SessionKey, asyncio.Lock] = {}
        # 用户回合水位（`user_turn_watermark` ✓）与续接台账（`continue_after_action` ✓）——
        # 两样都只为"确认生效后的自动续接"服务（见那里的 docstring ✓）。
        self._user_turn_seq: dict[SessionKey, int] = {}
        self._continued_actions: dict[str, None] = {}
        self.thread_recovery = ThreadRecovery(
            resume=self._resume_thread,
            create=self._create_thread,
            lookup=current_binding_loader,
            restart=self._restart_runtime,
        )

    @property
    def session_runtime(self) -> Any | None:
        return self._session_runtime

    @session_runtime.setter
    def session_runtime(self, runtime: Any | None) -> None:
        if isinstance(runtime, SessionRuntime) and runtime.lifecycle is not self.lifecycle:
            raise ValueError("gateway/session runtime lifecycle mismatch")
        self._session_runtime = runtime

    @_session_owner("action")
    async def execute_action(
        self,
        *,
        tenant_id: str | int = 1,
        session_id: str,
        action: Any,
        snapshot: ConversationTurnSnapshot | Mapping[str, Any],
    ) -> ConversationActionResult:
        """显式执行已校验动作；默认不启用，避免只读回合隐式写入。"""
        return await execute_conversation_action(
            tenant_id=tenant_id,
            session_id=session_id,
            action=action,
            snapshot=snapshot,
        )

    def scope_for_thread(self, thread_id: str) -> Any:
        """由 threadId 反查业务身份。**这是唯一可信的来源。**

        请求参数里的 tenant/session 是运行时转述的，模型可能参与其中；
        拿它当隔离边界等于把边界交给被隔离的一方。

        A7 之前这里要靠 `_snapshots` 反查租户，因为 `_threads` 的键只是
        sessionId——两个租户同号时会返回**先匹配到的那一个**。现在键本身就是
        权威身份，查表即答案，不再有"猜租户"的分支。
        """
        for key, bound_thread in self._threads.items():
            if str(bound_thread) == str(thread_id):
                return key
        return None

    def _turn_binder(self, tenant_id: str, session_id: str, ui_turn_id: str):
        """把原生回合号绑到会话运行时上，`turn/steer` 才找得到目标。"""
        runtime = getattr(self, "session_runtime", None)
        if runtime is None:
            return None

        async def bind(codex_turn_id: str) -> None:
            runtime.bind_codex_turn(
                _session_key(tenant_id, session_id),
                ui_turn_id,
                codex_turn_id,
            )

        return bind

    @_session_owner("gateway_read", key_argument=True)
    async def interrupt_codex_turn(self, key: Any, codex_turn_id: str) -> bool:
        """停止一个**原生**回合。只停推理，不撤销已提交的 Java 事务。"""
        thread_id = self._threads.get(self._as_session_key(key))
        if not thread_id or self.codex is None:
            return False
        await self.codex.interrupt_turn(thread_id, codex_turn_id)
        return True

    @_session_owner("gateway_read", key_argument=True)
    async def steer_codex_turn(self, key: Any, codex_turn_id: str, text: str) -> bool:
        thread_id = self._threads.get(self._as_session_key(key))
        if not thread_id or self.codex is None:
            return False
        await self.codex.steer_turn(
            thread_id, codex_turn_id, [{"type": "text", "text": text}]
        )
        return True

    @staticmethod
    def _as_session_key(key: Any) -> SessionKey:
        """把运行时报文里的会话标识收敛成 SessionKey。

        带租户的 SessionKey 直接用；只有一个裸 sessionId 的（旧报文）退回
        一个空租户的键——**查得到就查，查不到就返回 False**，不会跨租户命中，
        因为空租户不会等于任何一个真实租户。
        """
        if isinstance(key, SessionKey):
            return key
        tenant_id = getattr(key, "tenant_id", "")
        session_id = getattr(key, "session_id", key)
        return _session_key(tenant_id, session_id)

    async def _create_thread(self) -> dict[str, Any]:
        """新建原生 thread。只应由 ThreadRecovery 调用。"""
        return await self.codex.create_thread(
            base_instructions=self.base_instructions,
            developer_instructions=self.developer_instructions,
        )

    async def _resume_thread(self, thread_id: str) -> Any:
        """恢复既有原生 thread。只应由 ThreadRecovery 调用。"""
        return await self.codex.resume_thread(thread_id)

    async def _ensure_thread(self, key: Any, snapshot: Any) -> str:
        """拿到本回合该用的 thread；**进程刚好死了就重拉一次再试**。

        "进程死亡只在 resume 路径上被处理"是不够的：新会话（没有绑定）走的是
        `create`，同样会撞上死进程，而那条路上没有重拉逻辑——实测后果是
        **整个 agent 一直不可用**（每轮秒失败 `AppServerExited`），
        直到人工重启。进程不会自己复活，所以这一步必须自己兜住。
        """
        try:
            return await self.thread_recovery.load_or_resume(key, snapshot)
        except AppServerExited:
            logger.warning(
                "app server exited while acquiring a thread (session=%s); restarting runtime",
                key.session_id,
            )
            await self._restart_runtime()
            return await self.thread_recovery.load_or_resume(key, snapshot)

    async def _reconcile_applying_snapshot(
        self,
        key: SessionKey,
        tenant_id: str,
        session_id: str,
        snapshot: ConversationTurnSnapshot,
    ) -> ConversationTurnSnapshot:
        """applying 的受信对账：只查 Java 台账/CAS，不重发命令。

        失败 fail-safe：保持原快照、按“仍在生效”处理；绝不凭异常判未执行。
        """
        raw = getattr(snapshot, "journey", None)
        if not isinstance(raw, Mapping) or raw.get("pendingStatus") != "applying":
            return snapshot
        try:
            response = await internal_client.reconcile_pending_confirmation(
                session_id, tenant_id=tenant_id
            )
        except Exception as exc:  # noqa: BLE001 —— 对账不可用不等于未执行
            logger.warning("pending reconcile failed (session=%s): %s", session_id, exc)
            return snapshot
        # http_client 返回的是 Java BaseResponse 信封（code/data）；测试/替身也可能
        # 直接给 data。两种形状都认，避免把“有 data”读成 outcome 缺失。
        payload = response.get("data") if isinstance(response, Mapping) else None
        if not isinstance(payload, Mapping):
            payload = response if isinstance(response, Mapping) else {}
        outcome = str(payload.get("outcome") or "")
        if outcome in {"", "still_applying"}:
            return snapshot
        try:
            await self._refresh_snapshot_cache(
                key, tenant_id=tenant_id, session_id=str(session_id)
            )
            return self._snapshots.get(key) or snapshot
        except Exception as exc:  # noqa: BLE001 —— 对账已成功但刷新失败：保持旧快照
            logger.warning("pending reconcile refresh failed (session=%s): %s", session_id, exc)
            return snapshot

    async def _refresh_snapshot_cache(self, key: SessionKey, *, tenant_id: str, session_id: str) -> None:
        """重读权威快照并写进缓存（提案/动作这类**状态变更**之后必须做）。

        失败只告警不抛：刷新是"让下一轮看到最新"，不是本轮的正确性前提——
        拖着它失败会把一次成功的提案变成一次失败的回合。
        """
        try:
            fresh = _snapshot_payload(
                await _maybe_await(
                    self.snapshot_loader(tenant_id=tenant_id, session_id=str(session_id), skill=None)
                )
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("snapshot refresh failed (session=%s): %s", session_id, exc)
            return
        # **权威写入** ✓：刚刚那次提案/动作已经把服务端状态改了 ✓，重读回来的这份就是事实 ✓
        # ——哪怕它的版本比缓存里那张小（reset / supersede 之后本来就该小 ✓）。
        self._store_snapshot(key, fresh, authoritative=True)
        previous = self._working_sets.get(key)
        refreshed = ConversationWorkingSet.from_snapshot(fresh)
        if previous is not None:
            # 人工审查摘要与任务草稿都不是 Java 业务状态，重读快照不能把它们抹掉。
            refreshed.last_manual_review_digest = previous.last_manual_review_digest
            refreshed.last_manual_review_version = previous.last_manual_review_version
            refreshed.task_draft = previous.task_draft
        self._working_sets[key] = refreshed

    async def _prepare_score_update_preview(
        self,
        key: SessionKey,
        *,
        tenant_id: str,
        session_id: str,
        turn_id: str,
        request: ScoreUpdateRequest,
        snapshot: ConversationTurnSnapshot,
    ) -> dict[str, Any]:
        """补录成绩（score_update 动作族）的 prepare/preview —— 与提案分支同构的一段。

        - 写模式走 `prepare`：Java 把预览物化成 pending（`kind=score_update`），
          `dataValue` 里落下 Java 产出的 `operationId`（确认时 fail-closed 的幂等键）；
        - 只读模式走 `preview`：只出只读预览，**不做成可确认的卡**（写路径不在这台实例上活着）。
        返回的是前端合同形状（`_proposal_preview_payload` 消费它），身份与版本在
        `_refresh_snapshot_cache` 之后换成"待确认那一条"的值（与提案同一处口径）。
        """
        if request.source_version_guard != snapshot.snapshot_version:
            raise OutputContractError(
                "stale_state",
                "score update source version does not match the current snapshot",
            )
        payload = request.model_dump(by_alias=True, exclude_none=True)
        # **空数组 ≠ "把各科清空" ✗✓**：契约里 `subject_score_list` 的默认值是空列表 ✓，
        # `model_dump` 会把"模型没提各科"渲染成 `"subjectScoreList": []` ✗——而 Java 的合并是
        # "数组整体替换" ✓（表单补录要靠这条清空负面意向 ✓，改不得 ✓），于是空数组会把
        # **服务端既有的各科**整个抹掉 ✗ → 合并校验 110「请填写各科成绩后再创建会话」✓
        #（2026-10-06 实测 ✓：带 `[]` 必红 ✓、省掉该字段必绿 ✓）。按设计口径还原成"没带" ✓：
        # 没说过的字段根本不该出现在增量草稿里 ✓——真模型漏输出各科时同样会踩这里 ✓，
        # 这行是它的护栏 ✓；用户**真说了**各科时（非空列表）原样透传 ✓（替换语义在那里才是对的 ✓）。
        if not payload.get("subjectScoreList"):
            payload.pop("subjectScoreList", None)
        if self.mode == "codex_write":
            response = await internal_client.prepare_score_update(
                tenant_id,
                session_id,
                request_id=f"{tenant_id}:{session_id}:{turn_id}",
                payload=payload,
            )
        else:
            response = await internal_client.preview_score_update(tenant_id, session_id, payload)
        if (response or {}).get("code") not in (None, 0):
            # **Java 的 msg 要原样带走**（2026-10-06 实测：这条回包是
            # `code:110 / msg:"请选择批次后再创建会话"`，而网关把它替换成了一句英文
            # 通用文案，用户最终只看到"当前对话引擎暂时不可用"——**缺的是批次**这个
            # 可行动的事实被整段吞掉）。Java 的 110 原文本来就是写给用户和模型看的，
            # 这里只在它**没有**原文时才回退到通用描述。
            java_msg = str((response or {}).get("msg") or (response or {}).get("message") or "").strip()
            raise OutputContractError(
                "score_update_unavailable",
                java_msg or _SCORE_UPDATE_DEFAULT_REJECTION,
            )
        data = (response or {}).get("data") or {}
        # prepare 的返回是 PrepareResultDTO（预览在 `result` 里，外面是 pendingId 等）；
        # preview 的返回直接就是预览 DTO。两种形状都认（与提案侧同一条容错）。
        nested = data.get("result") if isinstance(data, Mapping) else None
        preview_data = nested if isinstance(nested, Mapping) else data
        summary = preview_data.get("summary") if isinstance(preview_data, Mapping) else None
        if not isinstance(summary, Mapping):
            raise OutputContractError(
                "score_update_unavailable",
                "Java score update preview returned no summary",
            )
        # **扁平形状** ✓：`_proposal_preview_payload`（server.py ✓）从**顶层**读
        # title/summary/status（Java 提案预览本来就是平铺的 ✓）——这里必须与它同一个口径，
        # 包一层 `diff` 的话翻译出来的 `diff` 会是空对象 ✗（卡成一张没有内容的壳 ✓）。
        preview: dict[str, Any] = {
            # **状态词表三端统一**（2026-10-16 修订 ✗）：原来写死的 `pending` 前端卡面
            # 词表根本不认识（`proposalCardText.mjs` 只有 ready/info/preview_only/
            # blocked ✗）→ 兜底成"处理结果未知" ✗（而这张卡明明是"待确认" ✓）。
            # 写模式 = 待确认 pending 已落库 ⇒ `ready` ✓（web 本该有的按钮判据/词表就
            # 认识它 ✓）；只读模式 = 没有可确认的卡 ⇒ `preview_only` ✓（与 Java
            # `Status.PREVIEW_ONLY` 逐字一致 ✓、web 不给按钮 ✓）。**不给 web 词表
            # 补 `pending` 映射** ✗（10-13 前车之鉴：错标"待确认"事故，加词只会把
            # "这张卡要用户做什么"的语义搅浑 ✓）。
            "status": "ready" if self.mode == "codex_write" else "preview_only",
            "title": "更新成绩",
            "summary": _score_update_summary_text(summary),
            # 只读模式下**不给确认按钮**：按钮背后没有可确认的 pending，
            # 点了只会得到一个看不懂的失败（写路径不在这台实例上活着）。
            "requiresConfirmation": self.mode == "codex_write",
            "sourceVersion": preview_data.get("sourceVersion"),
            # 待确认身份只认 pendingId（preview 只读模式下没有它 → 卡片不带确认按钮）。
            "proposalRef": data.get("pendingId") if isinstance(data, Mapping) else None,
            # 给人看的结构化那份（省份/科类/批次/各科/总分/位次 ✓）：全部来自
            # Java 按**合并后**成绩算的 summary，模型文本里的复述不作数。
            "scoreUpdate": dict(summary),
        }
        # 提案**改变了服务端状态**（写模式下 pending 已落库）：把快照缓存刷掉
        # （理由与提案分支逐字相同：不刷的话下一轮确认会被自己的旧缓存挡掉）。
        await self._refresh_snapshot_cache(key, tenant_id=tenant_id, session_id=session_id)
        fresh = self._snapshots.get(key)
        active = getattr(fresh, "active_proposal", None) if fresh is not None else None
        if active is not None:
            preview = _active_proposal_preview_override(preview, active)
        return preview

    async def _prepare_career_update_preview(
        self,
        key: SessionKey,
        *,
        tenant_id: str,
        session_id: str,
        turn_id: str,
        request: CareerUpdateRequest,
        snapshot: ConversationTurnSnapshot,
    ) -> dict[str, Any]:
        """发展方向草稿（career v1）的 prepare/preview —— 与补录成绩同构的一段。

        - 写模式：**agent 侧**把预览物化成 pending（`kind=career_update`）——
          Java 没有 profile-patch 命令类型（`PendingPlanningCommandBizService` 的分支
          里没有它），所以"写 latent"由执行链自己完成（读-合并-写），pending 只承担
          "待确认 + 幂等键（operationId）+ 结果回写"三件事；
        - 只读模式：只出只读预览，**不做成可确认的卡**（写路径不在这台实例上活着）。
        返回前端合同形状（`_proposal_preview_payload` 消费它）；身份与版本在
        `_refresh_snapshot_cache` 之后换成"待确认那一条"的值（与提案同一处口径）。
        """
        if request.source_version_guard != snapshot.snapshot_version:
            raise OutputContractError(
                "stale_state",
                "career update source version does not match the current snapshot",
            )
        # 契约层已归一（`CareerUpdateRequest._require_canonical_labels`），这里再归一是
        # "落库前最后一道"：唯一落库形式 = 中文规范标签（2026-10-14 拍板）。
        labels = normalize_career_labels(request.career_types)
        summary = "、".join(labels)
        preview: dict[str, Any] = {
            # **与补录同口径**（2026-10-16 ✓）：写模式 pending 落库 ⇒ `ready` ✓（卡上
            # 有待确认按钮 ✓）；只读模式 ⇒ `preview_only` ✓。理由与词表约束见
            # `_prepare_score_update_preview` 里那段注释（同一件事只说一次 ✓）。
            "status": "ready" if self.mode == "codex_write" else "preview_only",
            "title": "更新发展方向",
            "summary": f"发展方向：{summary}",
            # 只读模式下**不给确认按钮**：按钮背后没有可确认的 pending
            # （与补录那条同一口径）。
            "requiresConfirmation": self.mode == "codex_write",
            "sourceVersion": snapshot.snapshot_version,
            # 待确认身份只认 pendingId（只读模式下没有它 → 卡片不带确认按钮）。
            "proposalRef": None,
            # 给人看的结构化那份：**只看中文规范标签**（模型复述不作数）。
            "careerUpdate": {
                "careerTypes": list(labels),
                "userOriginalText": request.user_original_text,
            },
        }
        if self.mode == "codex_write":
            # 幂等键与待确认身份都**按回合派生**：同一回合的重试是重放（upsert 命中
            # `isSameActiveSnapshot` 直接返回当前那条 ✓）；新回合的新提案按 pending
            # 的 supersede 语义替换旧的（与 Java prepare 同一条口径）。
            operation_id = uuid.uuid5(
                uuid.NAMESPACE_URL, f"zhiyuan:career:{tenant_id}:{session_id}:{turn_id}"
            ).hex
            pending_id = f"career_{operation_id[:24]}"
            response = await internal_client.save_pending_confirmation(
                session_id,
                {
                    "pendingId": pending_id,
                    "kind": CAREER_UPDATE_KIND,
                    "actionFamily": UPDATE_CAREER_TYPES,
                    "status": "active",
                    "sourceVersion": snapshot.snapshot_version,
                    # operationId 由**生产者**（这一层）落下：执行时只复用、不自铸
                    # （与 Java prepare 的纪律逐字相同，见 `_execute_claimed_command`）。
                    "operationId": operation_id,
                    "proposalSource": CAREER_UPDATE_KIND,
                    "careerUpdateRequest": {
                        "careerTypes": list(labels),
                        "userOriginalText": request.user_original_text,
                    },
                },
                tenant_id=tenant_id,
            )
            if (response or {}).get("code") not in (None, 0):
                java_msg = str(
                    (response or {}).get("msg") or (response or {}).get("message") or ""
                ).strip()
                logger.warning(
                    "career update pending rejected: code=%s msg=%s session=%s",
                    (response or {}).get("code"),
                    java_msg,
                    session_id,
                )
                raise OutputContractError(
                    "career_update_unavailable",
                    java_msg or "career update pending was rejected",
                )
            pending_data = (response or {}).get("data") or {}
            if isinstance(pending_data, Mapping) and pending_data.get("pendingId"):
                preview["proposalRef"] = str(pending_data["pendingId"])
            if isinstance(pending_data, Mapping) and pending_data.get("sourceVersion") is not None:
                preview["sourceVersion"] = pending_data["sourceVersion"]
            # 提案**改变了服务端状态**（pending 已落库）：把快照缓存刷掉（理由与
            # 提案/补录分支逐字相同：不刷的话下一轮确认会被自己的旧缓存挡掉）。
            await self._refresh_snapshot_cache(key, tenant_id=tenant_id, session_id=session_id)
            fresh = self._snapshots.get(key)
            active = getattr(fresh, "active_proposal", None) if fresh is not None else None
            if active is not None:
                preview = _active_proposal_preview_override(preview, active)
        return preview

    async def _restart_runtime(self) -> None:
        """重拉原生 runtime。调用点只有恢复路径：ThreadRecovery 的进程退出分支、
        `_ensure_thread` 的兜底、回合内的兜底——三处都必须经过这里，否则新进程
        会拿到死进程的 threadId。"""
        restart = getattr(self.codex, "restart", None)
        if restart is None:
            raise RuntimeError("codex harness cannot restart")
        await _maybe_await(restart())
        # 重拉之后，缓存里每一个 threadId 都属于**已经死掉的那个进程**：codex 的
        # thread 表是进程内的（`turn_processor.rs` 的 `load_thread` →
        # `thread_manager.get_thread`），没在新进程里 resume 过就一律回
        # `-32600 thread not found`。不清的话，重拉只是把这一轮的 `AppServerExited`
        # 换成下一轮的 `AppServerProtocolError`——用户看到的还是"每轮都不可用，
        # 直到人工重启"，正是 A7 要修的那个症状（实测：19:56 那次复现）。
        # 清空后每个会话在下一轮各自走 `load_or_resume`：有绑定的 resume（rollout
        # 在磁盘上，模型侧上下文保得住），查不到绑定的才重建。
        if self._threads:
            logger.warning(
                "dropping %d cached thread binding(s) after a runtime restart "
                "(they belong to the dead process)",
                len(self._threads),
            )
            self._threads.clear()

    @_session_owner("gateway_read")
    async def get_current_snapshot(
        self, *, tenant_id: str, session_id: str
    ) -> ConversationTurnSnapshot | None:
        """Return the cached snapshot or load the current authoritative one."""
        key = _session_key(tenant_id, session_id)
        cached = self._snapshots.get(key)
        if cached is not None:
            return cached
        try:
            snapshot = _snapshot_payload(
                await _maybe_await(
                    self.snapshot_loader(
                        tenant_id=tenant_id,
                        session_id=str(session_id),
                        skill=None,
                    )
                )
            )
        except Exception:
            return None
        self._store_snapshot(key, snapshot)
        self._working_sets[key] = ConversationWorkingSet.from_snapshot(snapshot)
        return snapshot

    @_session_owner("gateway_read")
    async def get_authoritative_snapshot(
        self, *, tenant_id: str, session_id: str
    ) -> ConversationTurnSnapshot | None:
        """**强制重读**权威快照——确认/取消这类"按最新状态执行"的路径专用 ✓✓。

        与 `get_current_snapshot` 的差别只有一个：**不吃缓存优先** ✗✓。缓存优先是为
        "同一回合内多处读取"设计的 ✓，但动作路径恰好是"用户刚在别处改了状态、马上就点确认" ✓
        （空会话补录成绩、另一条线写工作区 ✓）——缓存里那份可能已经比 Java 权威状态旧 ✗：
        拿旧快照执行动作，`expectedSourceVersion` 会对不上 ✗ → 一张本该能点的卡被误判
        `stale_state` ✓✗。所以先重读 ✓（复用 `_refresh_snapshot_cache` 的 **authoritative 语义** ✓：
        刚重读回来的这份**就是事实** ✓，版本合法回退也照收 ✓）；读失败时退回缓存里那份 ✓
        （退化但不比以前差 ✓），缓存也没有才返回 None ✓（调用方照旧 fail closed ✓）。
        """
        key = _session_key(tenant_id, session_id)
        await self._refresh_snapshot_cache(
            key, tenant_id=tenant_id, session_id=str(session_id)
        )
        return self._snapshots.get(key)

    def _store_snapshot(
        self, key: SessionKey, snapshot: ConversationTurnSnapshot, *, authoritative: bool = False
    ) -> bool:
        """写入快照缓存，**按版本淘汰**：不比缓存旧的那份才写得进去。

        迟到的旧快照（重放、并发回合、后端回滚）如果直接覆盖，用户会看到
        "东西自己变回去了"，而链路上没有任何迹象。返回是否真的写入。

        `authoritative=True` 时**跳过淘汰**：这是"我们自己刚改了状态、刚重读回来"的那份 ✓
        （见 `_refresh_snapshot_cache` ✓）。为什么必须能跳过 ✗✓：版本**会合法地往回走** ✗——
        会话被 reset（待确认与规划状态清掉 ✓）或被后一次预览 supersede 之后 ✓，
        读回来的版本比缓存里那张**更小** ✓，而它才是对的 ✓。不跳过的后果实测过 ✓：
        提案已经落库（pending 建出来了 ✓）、缓存却钉在旧快照上（`activeProposal` 已清 ✗）→
        **提案卡根本不出现** ✗，而报错落在"卡要进已生效"上 ✓，看着像写链坏了 ✗
        （2026-09-27：F08 在"同一条会话被重复使用"时假红 ✓，换新盐即好 ✗——那正是这个守卫在作祟 ✓）。
        """
        cached = self._snapshots.get(key)
        if cached is not None and not authoritative:
            try:
                if int(snapshot.snapshot_version) < int(cached.snapshot_version):
                    return False
            except (TypeError, ValueError):
                # 版本号取不出来时不拦：宁可写进去，也不要因为一个畸形字段
                # 让整个会话停在旧快照上。
                pass
        self._snapshots[key] = snapshot
        return True

    @_session_owner("action")
    async def execute_action_and_refresh(
        self,
        *,
        tenant_id: str,
        session_id: str,
        action: Any,
        snapshot: ConversationTurnSnapshot | Mapping[str, Any],
    ) -> dict[str, Any]:
        """显式执行动作，并在后端成功变更后刷新权威会话状态。

        **重读失败不许吞掉终局** ✓✓：`execute_action` 已经回来了（`applied`/`cancelled` ✓，
        写入已经落地 ✓），后面这一步只是**顺带**刷新缓存快照 ✓——它失败时若把异常抛出去 ✗，
        调用方（`_run_native_turn` ✓）只会回一条通用 `gateway_failure` ✗，
        `actionResult` 随之丢失 ✗ → `conversationAction.result` **永远进不了事件流** ✗，
        而库里那次写入**是成功的** ✓：页面上卡停在"待确认"，用户只能反复点 ✓✗
        （任务书的不变量：只要 execute 回了终局，结果事件就必须进流 ✓）。
        """
        result = await self.execute_action(
            tenant_id=tenant_id,
            session_id=session_id,
            action=action,
            snapshot=snapshot,
        )
        payload: dict[str, Any] = {"actionResult": result.as_dict()}
        if result.action_status not in {"applied", "cancelled"}:
            return payload
        try:
            refreshed = _snapshot_payload(
                await _maybe_await(
                    self.snapshot_loader(
                        tenant_id=tenant_id,
                        session_id=str(session_id),
                        skill=None,
                    )
                )
            )
        except Exception:
            # 缓存这侧降级（接下来的回合会自己重读 ✓），但终局**照原样**带回去 ✓。
            logger.warning(
                "action applied but snapshot refresh failed: tenant=%s session=%s",
                tenant_id, session_id, exc_info=True,
            )
            return payload
        key = _session_key(tenant_id, session_id)
        self._store_snapshot(key, refreshed)
        self._working_sets[key] = ConversationWorkingSet.from_snapshot(refreshed)
        payload["snapshot"] = refreshed.model_dump(by_alias=True)
        payload["snapshotVersion"] = refreshed.snapshot_version
        return payload

    async def _execute_turn_action(
        self,
        *,
        tenant_id: str,
        session_id: str,
        action: Any,
        snapshot: ConversationTurnSnapshot,
    ) -> tuple[dict[str, Any], int | None]:
        """文本回合里模型发出的确认/取消：**复用点卡路径的执行器** ✓✓。

        与点卡路径（`server.py::_run_action_work` → `execute_action_and_refresh` ✓）
        的对称关系，逐项对齐：
        · 执行前都**重读权威快照** ✓——用户可能刚在别处改了状态（空会话补录成绩、
          另一条线写工作区 ✓），拿旧快照执行会把一张有效的卡误判 `stale_state` ✗；
          读不到时退回本回合开头那份 ✓（它就在手上，退化不比原来差 ✗✓；
          点卡路径那里读不到是 fail closed，因为它手里没有备用的）；
        · 执行都走 `execute_action_and_refresh` ✓：CAS/修订号、Java 校验、两段式
          claim→execute、pending 结果回写全在同一处 ✓，这里**不自造锁、不复制判据** ✗；
        · 终局（applied / cancelled / stale_state / failed…）都必须变成
          `conversationAction.result` ✓：点卡路径由 `_run_action_work` →
          `_emit_turn_terminal` 发 ✓；这里把结果挂进回合结果（`actionResult` 键 ✓），
          由**同一个** `_emit_turn_terminal` 发 ✓——载荷合同因此完全一致 ✓。
          发射走"会话当前连接 + 事件流"（`_session_emitter` ✓），**不依赖本连接存活** ✓
          ——与 `detach_work` 要保的是同一件事 ✓：连接死没死，结果都要进流 ✓。
          执行本身跑在回合任务里（`SessionRuntime.submit` 的后台任务 ✓，不绑连接 ✓）。

        执行**绝不把异常抛给回合**（取消除外 ✓）：任何异常都翻成 `failed` 结果 ✓——
        "静默丢弃"正是修前的老毛病 ✓，换成"整轮失败"同样把它藏起来 ✗。

        返回 `(actionResult, 执行后的快照版本)`：版本只在 applied/cancelled 时是**新**值
        （卡片据此对齐 workspaceVersion ✓），其余情况为 None（回合版本照旧 ✓）。
        """
        try:
            fresh = await self.get_authoritative_snapshot(
                tenant_id=tenant_id, session_id=str(session_id)
            )
        except Exception:  # noqa: BLE001 —— 刷新失败不否决执行：用手上这份（fail closed 在 CAS 里）
            logger.warning(
                "authoritative snapshot read failed before turn action (session=%s)",
                session_id,
                exc_info=True,
            )
            fresh = None
        proposal_ref = getattr(action, "proposal_ref", None)
        try:
            payload = await self.execute_action_and_refresh(
                tenant_id=tenant_id,
                session_id=str(session_id),
                action=action,
                snapshot=fresh or snapshot,
            )
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 —— 异常也要有终局：结果事件不许缺
            logger.exception(
                "turn conversation action crashed (session=%s action=%s)",
                session_id,
                getattr(action, "action_type", None),
            )
            return (
                ConversationActionResult(
                    "failed",
                    proposal_ref,
                    code="action_execution_exception",
                    message="执行确认时出现内部错误，本次操作未生效，请重试。",
                ).as_dict(),
                None,
            )
        result = payload.get("actionResult")
        if not isinstance(result, Mapping) or not result:
            # `execute_action_and_refresh` 必带 actionResult ✓；万一缺了也得有终局 ✗。
            return (
                ConversationActionResult(
                    "failed",
                    proposal_ref,
                    code="action_result_missing",
                    message="这次确认没有拿到执行结果，请重试或重新生成预览后再确认。",
                ).as_dict(),
                None,
            )
        snapshot_version = payload.get("snapshotVersion")
        try:
            snapshot_version = int(snapshot_version) if snapshot_version is not None else None
        except (TypeError, ValueError):
            snapshot_version = None
        return dict(result), snapshot_version

    @_session_owner("turn")
    async def handle_turn(
        self,
        *,
        tenant_id: str,
        session_id: str,
        user_id: str,
        turn_id: str,
        content: str,
        emit: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    ) -> dict[str, Any]:
        cache_key = (_session_key(tenant_id, session_id), str(turn_id))
        input_digest = hashlib.sha256(str(content).encode("utf-8")).hexdigest()
        # **用户回合水位**：在**拿锁之前** +1 ✓——一个已经在锁上排队的用户回合也算
        # "用户已经动过话头" ✓，续接回合据此让路（见 `continue_after_action` ✓）。
        # 记在拿锁之前而不是 turn 跑完：拿锁之后才记的话，"用户消息排着队、动作刚好
        # 执行完"那一瞬就是盲区 ✓✗。
        self._user_turn_seq[cache_key[0]] = self._user_turn_seq.get(cache_key[0], 0) + 1
        session_lock = self._session_locks.setdefault(cache_key[0], asyncio.Lock())
        async with session_lock:
            self._prune_turn_cache(self._turn_cache_clock())
            cached = self._turn_cache.get(cache_key)
            if cached is not None:
                if cached.input_digest != input_digest:
                    return {
                        "mode": self.mode,
                        "reply": "同一回合编号对应了不同内容，请重新发起本次请求。",
                        "events": [],
                        "snapshotVersion": cached.result.get("snapshotVersion"),
                        "writeAttempted": False,
                        "error": "turn_id_input_conflict",
                    }
                return cached.result
            result = await self._handle_uncached(
                tenant_id=tenant_id,
                session_id=session_id,
                user_id=user_id,
                turn_id=turn_id,
                content=content,
                emit=emit,
            )
            now = self._turn_cache_clock()
            self._turn_cache[cache_key] = _CachedTurn(
                result=result,
                input_digest=input_digest,
                expires_at=now + self._turn_cache_ttl_seconds,
            )
            self._prune_turn_cache(now)
            return result

    def _prune_turn_cache(self, now: float) -> None:
        while self._turn_cache:
            oldest = next(iter(self._turn_cache.values()))
            if (
                len(self._turn_cache) <= self._turn_cache_max_entries
                and oldest.expires_at > now
            ):
                break
            self._turn_cache.popitem(last=False)

    def user_turn_watermark(self, *, tenant_id: str | int, session_id: str | int) -> int:
        """这个会话已经开跑过多少个**用户回合**（续接回合的"别打架"基线 ✓）。

        调用方在"动作开始/本轮收尾"那一刻取一份 ✓，续接执行前再比一次 ✓：
        对不上就说明用户已经说了新话 ✓——让路，不续接（用户的诉求优先 ✗✗）。
        续接回合**自己不**计数 ✓（它不是用户回合 ✓，见 `continue_after_action` ✓）。
        """
        return self._user_turn_seq.get(_session_key(tenant_id, session_id), 0)

    @_session_owner("continuation")
    async def continue_after_action(
        self,
        *,
        tenant_id: str,
        session_id: str,
        user_id: str,
        turn_id: str,
        action_result: Mapping[str, Any],
        user_turn_watermark: int,
        emit: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    ) -> dict[str, Any] | None:
        """确认之后，让助手自动接住这一轮（一个新的助手回合 ✓）——生效照旧、**失败也接** ✓。

        为什么要有它 ✗✓（2026-10-09 用户实测，会话 10041981 ✓）：助手在上文承诺了
        下一步（"确认成绩后我先按方向给你几个院校专业组参考…" ✓），用户点卡确认后
        只收到一句写死的"操作已处理。" ✗——话头断了 ✓。写死的回执不可能是"下一步"，
        而**只有模型知道它承诺过什么** ✓，所以续接必须真跑一个回合 ✓。

        为什么失败也要续 ✗✓（2026-10-13 同一会话实测 ✓）："学费≤2 万"优先规则
        preview=ready ✓、用户打字确认 ✓，apply 失败 `409 priority_target_not_in_plan`
        （"当前方案没有命中优先目标" ✓）——失败后**没有任何助手跟话** ✗，用户只见一张
        失败卡 ✓；失败比成功更欠用户一个解释和替代路径 ✓，所以失败也续 ✓。

        形状（每一条都是硬约束 ✓）：
        · 触发档 = `applied` ∪ `failed` ✓。其余维持现状 ✗：`cancelled` 是用户自己的
          取消（没有下一步欠他 ✓）；`stale_state`（`_status` 把 `conflict` 也并进
          这一档 ✓）/`expired` 是"这张卡已经过期" ✓——要做的是刷新重来 ✓，接话会盖过
          刷新动线 ✗；`applying` **不是终态** ✗✓——它后面还会到 applied/failed ✓，
          此刻续接既可能接早 ✓✗、又会先把幂等台账占掉 ✓（终态到达时反而续不了 ✓），
          所以**死等终态** ✓；`not_executable` 是动作类型就不对 ✗（什么都没试过 ✓），
          没有可解释的事 ✓。
        · **不伪造用户消息** ✓✓：续接回合不走 `handle_turn` → `_handle_uncached` ✓，
          所以不落 user 消息、不进会话 transcript 的用户那一侧 ✓；喂给模型的是一条
          带内部分隔标签的**续接指令** ✓（生效版 `_continuation_nudge` ✓ / 失败版
          `_continuation_nudge_failed` ✓，与每轮注入的内部状态同一类 ✓——模型看得见、
          用户看不见 ✓），产出照旧是**助手消息** ✓
          （回合事件 + `_persist_agent` 落库 ✓，与普通回合同一条路径 ✓）。
        · 同一操作**只续一次** ✓：键取 `proposalRef`（没有才退到 turn_id ✓）——
          applied/failed 都是终态、提案随之被消费 ✓，同一次写入不会产出第二个终态 ✓；
          台账在**入口就记** ✓（跳过也算"处理过" ✓），并发重入因此不会双跑 ✓。
        · **不打架** ✓：续接前先看两样——会话锁空不空 ✓、用户回合水位动没动 ✓；
          任一不满足就**放弃** ✓（不排队、不等待 ✓——让路给用户 ✓）。真的跑起来之后
          它就在锁里 ✓，后来的用户回合按既有串行语义排在它后面 ✓。
        · **失败不重试不循环** ✓：模型回合只跑一次 ✓，失败翻成一条带措辞的
          `continuation_turn_failed` ✓（由调用方发终态 ✓，措辞分两版：生效版说"已生效" ✓、
          失败版说"没成功" ✓），不再触发第二次 ✓；续接回合自己若又执行了动作 ✓，
          也**不会**再触发续接（触发点只有用户回合那两处 ✓）。

        返回：跑了 → 回合结果（形状与 `_handle_uncached` 一致 ✓，调用方交
        `_emit_turn_terminal` 发终态 ✓）；跳过 → None ✓（**什么事件都没发** ✓）。
        """
        status = str((action_result or {}).get("actionStatus") or "")
        if status not in {"applied", "failed"}:
            return None
        if self.mode == "legacy" or self.codex is None:
            return None
        key = _session_key(tenant_id, session_id)
        ref = str(action_result.get("proposalRef") or "").strip()
        once_key = f"{key.tenant_id}:{key.session_id}:{ref or f'turn:{turn_id}'}"
        if not self._claim_continuation(once_key):
            logger.info(
                "action continuation already handled: session=%s ref=%s", session_id, ref
            )
            return None
        lock = self._session_locks.setdefault(key, asyncio.Lock())
        # **锁被占着就不插队** ✓✗（含"自己在锁里"这种**将来**可能的误用 ✓：
        # `asyncio.Lock` 不可重入 ✓，这里先判一下，宁可少续一次，也不许死锁 ✓）。
        if lock.locked() or self._user_turn_seq.get(key, 0) != int(user_turn_watermark):
            logger.info(
                "action continuation skipped (session busy or user moved on): session=%s ref=%s",
                session_id,
                ref,
            )
            return None
        async with lock:
            # 排队等锁的这中间用户可能又说话了 ✓：进锁之后**再比一次** ✓。
            if self._user_turn_seq.get(key, 0) != int(user_turn_watermark):
                logger.info(
                    "action continuation skipped (user turn started while waiting): session=%s",
                    session_id,
                )
                return None
            try:
                snapshot = _snapshot_payload(
                    await _maybe_await(
                        self.snapshot_loader(
                            tenant_id=tenant_id, session_id=str(session_id), skill=None
                        )
                    )
                )
            except Exception:
                # 快照读不到就没有可注入的上下文 ✓：放弃（**不**发 turn.started ✓）。
                logger.warning(
                    "continuation snapshot unavailable (session=%s)", session_id, exc_info=True
                )
                return None
            self._store_snapshot(key, snapshot, authoritative=True)
            if emit is not None:
                await emit({"type": "turn.started", "payload": {"startedAt": int(time.time() * 1000)}})
            try:
                codex_result = await self._codex_turn(
                    snapshot,
                    # 两版 nudge：生效版"接着做"✓ / 失败版"如实解释 + 给替代路径"✓（见各自 docstring ✓）。
                    _continuation_nudge(action_result)
                    if status == "applied"
                    else _continuation_nudge_failed(action_result),
                    str(session_id),
                    user_id,
                    str(tenant_id),
                    str(turn_id),
                    snapshot.allowed_capabilities,
                    snapshot.admission_mode,
                    state_patch=None,
                    emit=emit,
                    # 这一段是系统内部指令（自带 CONTINUATION 标签），不是用户消息：
                    # 不套用户消息分隔（见 `_codex_turn` 里该参数与两套标签的注释）。
                    content_is_user_message=False,
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("continuation turn crashed (session=%s)", session_id)
                codex_result = {"error": "continuation_turn_failed", "events": []}
            if not isinstance(codex_result, Mapping) or codex_result.get("error"):
                error = (
                    str(codex_result.get("error"))
                    if isinstance(codex_result, Mapping)
                    else "continuation_turn_failed"
                )
                logger.warning(
                    "continuation turn failed: session=%s ref=%s error=%s", session_id, ref, error
                )
                # 措辞要点 ✗✓（分两版 ✓）：applied 时说"**别让用户以为确认失败**"——
                # 确认已经生效 ✓，这里丢的是"自动接上"的那一步 ✓；failed 时反过来 ✓，
                # **别让用户以为已经生效** ✗（本次执行就是没成功 ✓）。两版都给
                # 可行动的下一句 ✓（不重试、不循环 ✓；用户回一句"继续"就是普通用户回合 ✓）。
                return {
                    "error": error,
                    "reply": _CONTINUATION_FAILURE_REPLY
                    if status == "applied"
                    else _CONTINUATION_FAILURE_REPLY_FAILED,
                    "events": list(codex_result.get("events", [])) if isinstance(codex_result, Mapping) else [],
                    "snapshotVersion": snapshot.snapshot_version,
                }
            output = codex_result["output"]
            await self._persist_agent(session_id, output.message)
            working_set = self._working_sets.get(key)
            return {
                "mode": self.mode,
                "reply": output.message,
                "events": codex_result.get("events", []),
                "trace": codex_result.get("trace", {}),
                "snapshotVersion": snapshot.snapshot_version,
                "writeAttempted": bool(output.proposal_ref),
                "output": output.model_dump(by_alias=True),
                "workingSet": working_set.as_payload() if working_set is not None else None,
                "proposalPreview": codex_result.get("proposalPreview"),
            }

    @_session_owner("continuation")
    async def continue_after_proposal_preview(
        self,
        *,
        tenant_id: str,
        session_id: str,
        user_id: str,
        turn_id: str,
        preview: Mapping[str, Any],
        user_turn_watermark: int,
        source_turn_id: str | None = None,
        emit: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    ) -> dict[str, Any] | None:
        """预览**没有生成可确认的卡片**（blocked / info / preview_only）时，让助手自动接住这一轮。

        缺口（2026-10-13 用户实测 ✓，会话 10041981，20:22）：用户选了三所学校 ✓，
        模型回复"我把它们和「学费一年 3 万以内」合成一件事，**提交给你确认了**……
        点卡片或回复确认" ✓——而本轮 `proposal.preview` 的真实结局是 `info` ✓
        （"当前方案里已经有 3 个专业组……本轮不需要调整方案" ✓，**无按钮** ✓）：
        用户被引向一个**不存在的确认动作** ✗✗。更早的同族：多规则场景 blocked 卡
        而文案称"待确认"（review §五-19/23 异常 B ✓）。

        与 `continue_after_action` 的差别只有**触发源** ✗✓：那一版吃
        `conversationAction.result`（applied/failed ✓），这一版吃**回合内的
        `proposal.preview` 结局** ✓（回合收尾时已在 `result["proposalPreview"]` 里 ✓，
        server.py 发事件读的是同一处 ✓）。其余每一条硬约束逐条同构 ✓：

        · 触发档 = `blocked` ∪ `info` ∪ `preview_only` ✓。`ready` **不在**触发集里 ✓
          ——那是有可确认卡片的正常路径 ✓（补录/发展方向预览在**写模式**下发的就是它 ✓，
          2026-10-16 词表统一后 ✓）；`applied` 同此 ✓：一个字节都不动 ✗✓。
          **只读模式**的补录/发展方向预览改发 `preview_only` ✓ → 落进触发档 ✓：那正是
          "给了一张没有确认按钮的预览、而文案可能让用户去点卡"的情形 ✓（这台实例上写路
          径不活着 ✓），跟话纠正本来就是为它准备的 ✓。
        · **不伪造用户消息** ✓✓：不走 `handle_turn` → `_handle_uncached` ✓，不落 user
          消息 ✓；喂给模型的是 `_preview_outcome_nudge`（自带 `CONTINUATION_*` 标签的
          系统指令 ✓），产出照旧是**助手消息** ✓（`_persist_agent` ✓）。
        · **同一触发回合只跟一次** ✓：键取**触发它的那个用户回合** `source_turn_id`
          （缺省退到本回合号 ✓）——预览结局是**回合事实** ✓，一条收尾话术对应一个回合 ✓；
          写成"按 proposalRef"会把后续回合该有的纠正也吞掉 ✗（ref 会被活动提案覆盖成
          跨回合复用的值 ✓，见 `_active_proposal_preview_override` ✓）。
          台账在**入口就记** ✓（跳过也算"处理过" ✓），并发重入不会双跑 ✓。
        · **不打架** ✓：与动作续接同款——会话锁空 ✓、用户回合水位没动 ✓，任一不满足
          就放弃 ✓（不排队、不等待 ✓，用户优先 ✗✗）。
        · **不递归** ✓✓：触发点只有用户回合收尾那一处（server.py
          `_maybe_continue_after_preview` ✓）——跟话回合自己（cont-… ✓）哪怕又产出
          info/blocked 预览 ✓，也不会再触发第二轮 ✓；模型回合只跑一次 ✓，失败翻成一条
          带措辞的 `_PREVIEW_CONTINUATION_FAILURE_REPLY` ✓（由调用方发终态 ✓），
          不重试、不循环 ✓。

        返回：跑了 → 回合结果（形状与 `_handle_uncached` 一致 ✓，调用方交
        `_emit_turn_terminal` 发终态 ✓——跟话回合若修出了可确认的卡片 ✓，那条
        `proposal.preview` 事件也会照常发出去 ✓）；跳过 → None ✓（**什么事件都没发** ✓）。
        """
        status = str((preview or {}).get("status") or "").strip().lower()
        if status not in _PREVIEW_CONTINUATION_STATUSES:
            return None
        if self.mode == "legacy" or self.codex is None:
            return None
        key = _session_key(tenant_id, session_id)
        anchor = str(source_turn_id or turn_id).strip() or str(turn_id)
        once_key = f"{key.tenant_id}:{key.session_id}:preview:turn:{anchor}"
        if not self._claim_continuation(once_key):
            logger.info(
                "preview continuation already handled: session=%s turn=%s status=%s",
                session_id,
                anchor,
                status,
            )
            return None
        lock = self._session_locks.setdefault(key, asyncio.Lock())
        # 锁被占着就不插队（与 `continue_after_action` 逐条同款 ✓）。
        if lock.locked() or self._user_turn_seq.get(key, 0) != int(user_turn_watermark):
            logger.info(
                "preview continuation skipped (session busy or user moved on): session=%s turn=%s",
                session_id,
                anchor,
            )
            return None
        async with lock:
            # 排队等锁的这中间用户可能又说话了：进锁之后**再比一次** ✓。
            if self._user_turn_seq.get(key, 0) != int(user_turn_watermark):
                logger.info(
                    "preview continuation skipped (user turn started while waiting): session=%s",
                    session_id,
                )
                return None
            try:
                snapshot = _snapshot_payload(
                    await _maybe_await(
                        self.snapshot_loader(
                            tenant_id=tenant_id, session_id=str(session_id), skill=None
                        )
                    )
                )
            except Exception:
                # 快照读不到就没有可注入的上下文：放弃（**不**发 turn.started ✓）。
                logger.warning(
                    "preview continuation snapshot unavailable (session=%s)", session_id, exc_info=True
                )
                return None
            self._store_snapshot(key, snapshot, authoritative=True)
            if emit is not None:
                await emit({"type": "turn.started", "payload": {"startedAt": int(time.time() * 1000)}})
            try:
                codex_result = await self._codex_turn(
                    snapshot,
                    _preview_outcome_nudge(preview),
                    str(session_id),
                    user_id,
                    str(tenant_id),
                    str(turn_id),
                    snapshot.allowed_capabilities,
                    snapshot.admission_mode,
                    state_patch=None,
                    emit=emit,
                    # 系统内部指令（自带 CONTINUATION 标签），不是用户消息：
                    # 不套用户消息分隔（与 `continue_after_action` 同一条理由）。
                    content_is_user_message=False,
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("preview continuation turn crashed (session=%s)", session_id)
                codex_result = {"error": "continuation_turn_failed", "events": []}
            if not isinstance(codex_result, Mapping) or codex_result.get("error"):
                error = (
                    str(codex_result.get("error"))
                    if isinstance(codex_result, Mapping)
                    else "continuation_turn_failed"
                )
                logger.warning(
                    "preview continuation turn failed: session=%s turn=%s status=%s error=%s",
                    session_id,
                    anchor,
                    status,
                    error,
                )
                return {
                    "error": error,
                    "reply": _PREVIEW_CONTINUATION_FAILURE_REPLY,
                    "events": list(codex_result.get("events", [])) if isinstance(codex_result, Mapping) else [],
                    "snapshotVersion": snapshot.snapshot_version,
                }
            output = codex_result["output"]
            await self._persist_agent(session_id, output.message)
            working_set = self._working_sets.get(key)
            return {
                "mode": self.mode,
                "reply": output.message,
                "events": codex_result.get("events", []),
                "trace": codex_result.get("trace", {}),
                "snapshotVersion": snapshot.snapshot_version,
                "writeAttempted": bool(output.proposal_ref),
                "output": output.model_dump(by_alias=True),
                "workingSet": working_set.as_payload() if working_set is not None else None,
                "proposalPreview": codex_result.get("proposalPreview"),
            }

    def _claim_continuation(self, once_key: str) -> bool:
        """续接台账：第一次见到这个操作就记账并放行 ✓，之后一律 False ✓。

        有界（`_CONTINUATION_LEDGER_MAX` ✓）：它只是"同一操作别续两次"的短期记忆 ✓，
        不是审计账本 ✗——满了按到达顺序裁掉最旧的 ✓（`dict` 保序 ✓）。
        """
        if once_key in self._continued_actions:
            return False
        self._continued_actions[once_key] = None
        while len(self._continued_actions) > _CONTINUATION_LEDGER_MAX:
            self._continued_actions.pop(next(iter(self._continued_actions)))
        return True

    async def _handle_uncached(
        self,
        *,
        tenant_id: str,
        session_id: str,
        user_id: str,
        turn_id: str,
        content: str,
        emit: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    ) -> dict[str, Any]:
        key = _session_key(tenant_id, session_id)
        if self.message_store is not None:
            await self.message_store.save_user_message(str(session_id), content)

        if self.mode == "legacy":
            reply = await self._legacy_reply(session_id, user_id, content)
            await self._persist_agent(session_id, reply)
            return {
                "mode": self.mode,
                "reply": reply,
                "events": [],
                "snapshotVersion": None,
                "writeAttempted": False,
            }

        try:
            snapshot = _snapshot_payload(
                await _maybe_await(
                    self.snapshot_loader(
                        tenant_id=tenant_id,
                        session_id=session_id,
                        skill=None,
                    )
                )
            )
        except Exception as exc:
            return {
                "mode": self.mode,
                "reply": "当前会话状态暂时不可用，请稍后重试。",
                "events": [],
                "snapshotVersion": None,
                "writeAttempted": False,
                "error": f"context_unavailable: {type(exc).__name__}",
            }
        previous_snapshot = self._snapshots.get(key)
        state_patch = None
        if previous_snapshot is not None:
            try:
                if snapshot.snapshot_version == previous_snapshot.snapshot_version + 1:
                    state_patch = diff_snapshots(previous_snapshot, snapshot)
            except ValueError:
                state_patch = None
        self._store_snapshot(key, snapshot)
        working_set = ConversationWorkingSet.from_snapshot(snapshot)
        previous_working_set = self._working_sets.get(key)
        if previous_working_set is not None:
            previous_working_set.reconcile_snapshot(snapshot)
            working_set.candidate_entities = list(previous_working_set.candidate_entities)
            # 证据**不从这里继承**（P1b-3）：`working_set` 建自
            # `ConversationWorkingSet.from_snapshot()`，证据以 snapshot 为准——
            # 进程内存里有、snapshot 里没有的（Java 已判 stale/expired/unknown）
            # 一律丢弃。写成"取交集"的表达式会让这条边界看起来像实现细节，
            # 而它其实是"Java 说失效了就不再作数"本身。
            if not snapshot.admission_facts:
                working_set.admission_facts = list(previous_working_set.admission_facts)
            working_set.artifact_refs = list(previous_working_set.artifact_refs)
            working_set.last_response_type = previous_working_set.last_response_type
            working_set.last_turn_id = previous_working_set.last_turn_id
            working_set.candidate_scope_version = previous_working_set.candidate_scope_version
            working_set.candidate_scope_stage = previous_working_set.candidate_scope_stage
            working_set.candidate_source_turn_id = previous_working_set.candidate_source_turn_id
            working_set.task_draft = previous_working_set.task_draft
            working_set.last_manual_review_digest = previous_working_set.last_manual_review_digest
            working_set.last_manual_review_version = previous_working_set.last_manual_review_version
        if self.task_ledger is not None:
            persisted_task = await _maybe_await(
                self.task_ledger.load(key.tenant_id, key.session_id)
            )
            if isinstance(persisted_task, dict):
                working_set.task_draft = persisted_task
        self._working_sets[key] = working_set

        codex_task = asyncio.create_task(
            self._codex_turn(
                snapshot,
                content,
                session_id,
                user_id,
                tenant_id,
                turn_id,
                snapshot.allowed_capabilities,
                snapshot.admission_mode,
                state_patch,
                emit=emit,
            )
        )
        if self.mode == "codex_shadow":
            legacy_task = asyncio.create_task(self._legacy_reply(session_id, user_id, content))
            codex_result, reply = await asyncio.gather(codex_task, legacy_task, return_exceptions=True)
            if isinstance(reply, Exception):
                return {
                    "mode": self.mode,
                    "reply": "处理消息时出错，请稍后重试",
                    "events": [],
                    "snapshotVersion": snapshot.snapshot_version,
                    "statePatch": state_patch.model_dump(by_alias=True) if state_patch else None,
                    "writeAttempted": False,
                    "codexError": type(codex_result).__name__ if isinstance(codex_result, Exception) else None,
                }
            await self._persist_agent(session_id, reply)
            result: dict[str, Any] = {
                "mode": self.mode,
                "reply": reply,
                "events": [],
                "snapshotVersion": snapshot.snapshot_version,
                "statePatch": state_patch.model_dump(by_alias=True) if state_patch else None,
                "writeAttempted": False,
            }
            if isinstance(codex_result, Exception):
                result["codexError"] = str(codex_result)
            else:
                result["codex"] = codex_result
            return result

        codex_result = await codex_task
        if codex_result.get("error"):
            # 这条错误以前**不落任何日志**：用户看到"当前对话引擎暂时不可用"，
            # 而真正的原因（哪一步、什么码）在链路上不留痕迹，只能靠复现去猜。
            logger.warning(
                "codex turn failed tenant=%s session=%s turn=%s error=%s recoverable=%s",
                tenant_id,
                session_id,
                turn_id,
                codex_result.get("error"),
                bool(codex_result.get("recoverable")),
            )
            return self._with_turn_action(
                {
                    "mode": self.mode,
                    # 失败回复：默认通用文案；**补录的业务拒绝**放行 Java 原文
                    # （"请选择批次后再创建会话"这种话才让用户知道下一步做什么）。
                    "reply": _recoverable_turn_reply(codex_result.get("error")),
                    "events": codex_result.get("events", []),
                    "snapshotVersion": snapshot.snapshot_version,
                    "statePatch": state_patch.model_dump(by_alias=True) if state_patch else None,
                    "writeAttempted": False,
                    "error": codex_result["error"],
                    # "这一回合失败了"和"这个会话坏了"要分得开：恢复失败属于前者，
                    # 下一回合重试即可，调用方（以及前端）不必把它当成终局。
                    "recoverable": bool(codex_result.get("recoverable")),
                },
                codex_result,
            )
        output = codex_result["output"]
        await self._persist_agent(session_id, output.message)
        return self._with_turn_action(
            {
                "mode": self.mode,
                "reply": output.message,
                "events": codex_result.get("events", []),
                "trace": codex_result.get("trace", {}),
                "recovery": codex_result.get("recovery", {"outputRepaired": False}),
                "snapshotVersion": snapshot.snapshot_version,
                "statePatch": state_patch.model_dump(by_alias=True) if state_patch else None,
                "writeAttempted": bool(output.proposal_ref),
                "output": output.model_dump(by_alias=True),
                "workingSet": self._working_sets[key].as_payload(),
                "proposalPreview": codex_result.get("proposalPreview"),
            },
            codex_result,
        )

    @staticmethod
    def _with_turn_action(result: dict[str, Any], codex_result: Mapping[str, Any]) -> dict[str, Any]:
        """把模型发起的确认/取消结果挂进回合结果（成功与失败两支都要 ✓）。

        挂上之后 `server.py::_emit_turn_terminal` 一见 `actionResult` 就发
        `conversationAction.result` ✓（点卡路径用的是同一个键、同一个发射器 ✓）——
        即"模型打字确认"与"用户点卡确认"在事件流里是同一种结果事件 ✓。

        `snapshotVersion` 在执行成功时换成**执行后**的版本 ✓：卡片据此对齐
        workspaceVersion ✓（与点卡路径 `execute_action_and_refresh` 的返回一致 ✓）；
        失败/冲突时保持回合开头那份 ✓（并没有新版本 ✓）。
        """
        action_result = codex_result.get("actionResult")
        if not isinstance(action_result, Mapping) or not action_result:
            return result
        result["actionResult"] = dict(action_result)
        snapshot_version = codex_result.get("actionSnapshotVersion")
        if snapshot_version is not None:
            result["snapshotVersion"] = snapshot_version
        return result

    async def _legacy_reply(self, session_id: str, user_id: str, content: str) -> str:
        if self.legacy is None:
            raise RuntimeError("legacy service unavailable")
        reply = await self.legacy.handle_message(
            session_id=str(session_id), user_id=str(user_id), content=content
        )
        if hasattr(reply, "content"):
            return str(reply.content)
        return str(reply)

    async def _persist_agent(self, session_id: str, reply: Any) -> None:
        if self.message_store is not None:
            await self.message_store.save_agent_message(str(session_id), str(reply), "reply")

    async def _codex_turn(
        self,
        snapshot: ConversationTurnSnapshot,
        content: str,
        session_id: str,
        user_id: str,
        tenant_id: str,
        turn_id: str,
        allowed_capabilities: list[str],
        admission_mode: str,
        state_patch: Any = None,
        emit: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
        # 最后一条输入是**用户正文**还是**系统内部指令**（续接 nudge）。默认 True：
        # 绝大多数调用就是用户回合；续接路径显式传 False（见 `continue_after_action`）。
        content_is_user_message: bool = True,
    ) -> dict[str, Any]:
        if self.codex is None:
            return {"error": "codex_unavailable", "events": []}
        # J1：applying 回合先做一次受信对账；状态变了就整份快照重注入
        # （旧 state_patch 的 baseVersion 已不对，不能继续用）。
        key = _session_key(tenant_id, session_id)
        reconciled = await self._reconcile_applying_snapshot(
            key, tenant_id, session_id, snapshot
        )
        if reconciled is not snapshot:
            snapshot = reconciled
            state_patch = None
        # 模型在文本回合里发出的确认/取消（执行结果）。在 try **之外**初始化：
        # 异常分支也要能把已经出站的结果原样带回去（见 `_turn_action_payload` ✓）。
        action_result_payload: dict[str, Any] | None = None
        action_snapshot_version: int | None = None
        try:
            thread_id = self._threads.get(key)
            if not thread_id:
                thread_id = await self._ensure_thread(key, snapshot)
            binding = await _maybe_await(
                self.binding_loader(
                    tenant_id=tenant_id,
                    session_id=session_id,
                    user_id=user_id,
                    turn_id=turn_id,
                    thread_id=thread_id,
                    allowed_capabilities=allowed_capabilities,
                    admission_mode=admission_mode,
                    snapshot_version=snapshot.snapshot_version,
                )
            )
            if binding is None:
                return {"error": "binding_unavailable", "events": []}
            # 缓存写在**绑定成功之后**。提前缓存的话，一次注册失败会留下一个
            # 进过缓存的裸 thread：下一回合直接拿它跑工具，而 MCP 那边没有
            # 对应绑定。这条顺序就是"不暴露无绑定 thread 给 MCP"本身。
            self._threads[key] = thread_id
            if state_patch is not None:
                state_payload = {"kind": "state_patch", "patch": state_patch.model_dump(by_alias=True)}
            else:
                state_payload = {
                    "kind": "turn_snapshot",
                    "snapshot": snapshot.model_dump(by_alias=True),
                }
            snapshot_item = {
                "type": "text",
                "text": _internal_state_block(
                    json.dumps(state_payload, ensure_ascii=False)
                ),
            }
            working_set = self._working_sets.get(key)
            context_items = [snapshot_item]
            # 本轮标识：`intentDraft.sourceTurnId` 是模型侧必填字段，但当前回合号
            # 由网关生成、此前没有进模型上下文——模型只能编或干脆省略整个草稿。
            # 显式给出唯一可用的值（不得编造），草稿才能稳定落进 TaskDraft。
            context_items.append(
                {
                    "type": "text",
                    "text": _internal_state_block(
                        "【本轮标识】\n"
                        f"turnId: {turn_id}\n"
                        "intentDraft.sourceTurnId 必须原样使用这个值，不得编造。"
                    ),
                }
            )
            if working_set is not None:
                context_items.append(
                    {
                        "type": "text",
                        "text": _internal_state_block(working_set.as_context_text()),
                    }
                )
                execution_plan = build_execution_plan(snapshot, working_set)
                context_items.append(
                    {
                        "type": "text",
                        "text": _internal_state_block(
                            "【本轮执行计划骨架】\n"
                            "这是执行约束和完成条件提示，不是用户新问题。"
                            "Codex 仍需根据用户原话确定任务类型、工具和最终步骤。\n"
                            + json.dumps(
                                execution_plan.as_payload(), ensure_ascii=False
                            )
                        ),
                    }
                )
                context_items.append(
                    {
                        "type": "text",
                        "text": _internal_state_block(
                            "【工具编排约束】\n"
                            "以下约束用于避免不完整查询和重复读取，不是用户新问题。\n"
                            + render_tool_contracts()
                        ),
                    }
                )
            journey_ctx = journey_from_snapshot(
                snapshot,
                manual_review_digest=getattr(working_set, "last_manual_review_digest", None),
                has_open_task=bool(working_set and working_set.has_open_task()),
            )
            if journey_ctx is not None:
                context_items.append(
                    {
                        "type": "text",
                        "text": _internal_state_block(journey_context_text(journey_ctx)),
                    }
                )
            turn_input = list(context_items)
            if content_is_user_message:
                # 用户正文带显式边界（2026-10-13 短消息事故，见 `USER_MESSAGE_OPEN_TAG`）：
                # 多块机器文本之后，最后一条必须是"框起来、点明归属"的用户原话。
                turn_input.append({"type": "text", "text": _user_message_block(content)})
            else:
                # 续接 nudge：它自带 `CONTINUATION_*` 标签（系统指令，不是用户消息），
                # **不**套用户消息标记——套上会把"这不是用户发的"这件事又说反。
                turn_input.append({"type": "text", "text": content})
            # 没有 emit 时**不传**这个参数：多传一个 None 会让所有既有的
            # 替身 harness（签名里没有它）当场 TypeError——"旧调用不变"
            # 指的是调用形态也不变，不只是语义不变。
            # 同一份 kwargs 也交给重查轮（见 `_recheck_turn` 的 docstring）：
            # 重查是用户看得见的第二轮，进度事件与 native turn 绑定都得有。
            collect_kwargs: dict[str, Any] = {}
            emitter = _progress_emitter(emit, str(turn_id))
            if emitter is not None:
                collect_kwargs["on_notification"] = emitter
            binder = self._turn_binder(tenant_id, session_id, str(turn_id))
            if binder is not None:
                collect_kwargs["on_turn_started"] = binder
            if hasattr(self.codex, "start_turn_and_collect"):
                collected = await self.codex.start_turn_and_collect(
                    thread_id,
                    turn_input,
                    TURN_OUTPUT_SCHEMA,
                    **collect_kwargs,
                )
                if collected.status != "completed":
                    return {
                        "error": collected.error_code or f"turn_{collected.status}",
                        "events": [
                            event
                            for item in collected.events
                            if (event := adapt_codex_item(item)) is not None
                        ],
                    }
                turn = {
                    "output": collected.output,
                    "events": collected.events,
                }
                if collected.payload:
                    turn.update(collected.payload)
            else:
                turn = await self.codex.start_turn(
                    thread_id,
                    turn_input,
                    TURN_OUTPUT_SCHEMA,
                )
            async def _extract_output(turn_payload: Any) -> tuple[TurnOutput, bool]:
                """取结构化输出；不合契约就先走一次修复回合再取。

                重查（P1c-2）之后要**再取一遍**，所以抽成函数而不是内联两段：
                两遍的行为必须一模一样。
                """
                raw_output = turn_payload.get("output") if isinstance(turn_payload, Mapping) else None
                if raw_output is None and isinstance(turn_payload, Mapping):
                    raw_output = turn_payload.get("turn", {}).get("output")
                try:
                    if not isinstance(raw_output, Mapping):
                        raise OutputContractError("output_missing", "completed turn did not return structured output")
                    return TurnOutput.model_validate(raw_output), False
                except (OutputContractError, ValidationError) as exc:
                    raw_text = _last_agent_text(turn_payload)
                    # 2026-10-17 真事故（10041984 续接回合）：模型输出 review 时
                    # `artifactRefs` 为空 → schema 修复回合**默认不许调工具** →
                    # 只能从工作区里翻出一份旧产物（stateVersion=1，当前=4）→
                    # 修完立刻又撞 `stale_state`，整轮白修 ✗。缺 artifactRefs
                    # 与"产物版本过期"是同一族问题，修复回合必须允许重调只读工具
                    # 拿一份**本回合签发**的新产物；否则修复提示里那句"允许重新
                    # 获取"等于空话。修复回合的事件会并回 turn payload，后面
                    # `_evidence_inputs` 能看见新签发的产物 ✓。
                    artifact_refs_missing = (
                        "artifactRefs is required for recommendation/review output" in str(exc)
                    )
                    logger.warning(
                        "turn output rejected (%s); attempting one repair turn (raw text %s)",
                        exc,
                        "included" if raw_text else "unavailable",
                    )
                    repaired = await self._repair_turn_output(
                        thread_id,
                        (
                            f"{exc}\n{_ARTIFACT_REF_REPAIR_HINT}"
                            if artifact_refs_missing
                            else str(exc)
                        ),
                        raw_output=raw_text,
                        allow_tool_calls=artifact_refs_missing,
                    )
                    if repaired is None:
                        raise OutputContractError("output_schema_invalid", str(exc)) from exc
                    repaired_events = repaired.get("events") or []
                    turn_payload.update(
                        {
                            "output": repaired["output"],
                            "events": [*(turn_payload.get("events") or []), *repaired_events],
                        }
                    )
                    return TurnOutput.model_validate(repaired["output"]), True

            async def _validate_round(
                output_value: TurnOutput | Mapping[str, Any],
                evidence_ledger: list[dict[str, Any]],
                artifacts: dict[str, Any],
                turn_payload: Any,
                artifact_ceiling: int | None = None,
            ) -> tuple[TurnOutput, bool, list[dict[str, Any]], dict[str, Any]]:
                """校验本回合输出；可修复的契约违反先给模型一次纠错回合再定生死。

                2026-10-09 真事故（会话 10041980）：模型对一张早已失效的提案卡反复发
                confirm → `proposal_reference_mismatch` → 整轮 `recoverable=False` 硬
                失败 → 模型**收不到任何纠错反馈** → 下一轮继续确认同一张死卡，用户
                被卡死。这类失败与 schema 失败一样是**可修复**的：把冲突讲给模型
                （`_PROPOSAL_REFERENCE_REPAIR_HINT`），让它改用当前有效引用 / 重新提案
                / 如实说明。2026-10-13 同病又见于招生事实（会话 10041981）：模型把
                候选行的 `entityId` 拼接串当 `admissionUnitId` → `admission_evidence_missing`
                硬失败，修复提示见 `_ADMISSION_EVIDENCE_REPAIR_HINT`（拆单值 / 更正 /
                删掉）。修复回合再被拒（或压根拿不到结构化输出）时**维持现状硬
                失败**，错误码不变（前端按码查兜底文案 ✓），也不许再修第二次。
                2026-10-15 增补（§41）：产物引用被拒（`artifact_scope_violation`）同样
                先给一次纠错机会，且**允许修复回合调用只读工具重新签发**——所以修完
                要按**含修复回合事件**的载荷重建产物/证据账本（`_LEDGER_REBUILD_REPAIR_CODES`；
                不重建的话，重新签发的产物在旧账本里查不到，修了也照挂）。返回值把
                （可能重建过的）账本带回给调用方，重查与后续守卫用的是同一份。
                """
                def _check(value: TurnOutput | Mapping[str, Any]) -> TurnOutput:
                    return validate_turn_output(
                        turn_output=value,
                        current_snapshot=snapshot,
                        evidence_ledger=evidence_ledger,
                        artifacts=artifacts,
                        thread_id=thread_id,
                        tenant_id=tenant_id,
                        allow_proposal=True,
                        strict_scope=True,
                        artifact_version_ceiling=artifact_ceiling,
                    )

                try:
                    return _check(output_value), False, evidence_ledger, artifacts
                except OutputContractError as exc:
                    # 拒收时把**账本里有什么**一起打出来：只报一个
                    # `evidence_not_found: ev_xxx` 的话，"模型引用了不存在的证据"
                    # 与"证据本来就没进账本"在日志上长得一样，而处置完全不同
                    # （前者是模型编造，后者是我们的管道丢的）。
                    logger.warning(
                        "turn output rejected: %s | ledger=%d ids=%s | cited=%s",
                        exc,
                        len(evidence_ledger),
                        sorted(evidence_ledger.keys())[:8],
                        [ref.evidence_id for ref in getattr(output_value, "evidence_refs", [])],
                    )
                    if exc.code not in _REPAIRABLE_CONTRACT_CODES:
                        raise
                    # 复用 schema 修复那条回路（`_repair_turn_output`）：一次、不循环。
                    logger.warning(
                        "turn output rejected (%s); attempting one repair turn for a repairable contract violation",
                        exc,
                    )
                    fresh = await self._repair_turn_output(
                        thread_id,
                        f"{exc}\n{_REPAIR_HINT_BY_CODE[exc.code]}",
                        raw_output=_last_agent_text(turn_payload),
                        # 产物引用这一族允许修复回合**重新调只读工具**拿新签发的引用
                        # （旧引用可能因版本推进而过期）——所以下面要重建账本。
                        allow_tool_calls=exc.code in _LEDGER_REBUILD_REPAIR_CODES,
                    )
                    if fresh is None:
                        raise
                    # 与 `_extract_output` 的修复支同形：修复回合的输出与事件替进本回合。
                    turn_payload.update(
                        {
                            "output": fresh["output"],
                            "events": [
                                *(turn_payload.get("events") or []),
                                *(fresh.get("events") or []),
                            ],
                        }
                    )
                    if exc.code in _LEDGER_REBUILD_REPAIR_CODES:
                        # 重建（与 `_recheck_turn` 同一条理由：账本按**最新载荷**建，
                        # 否则修复回合新签发的产物一引用就是 `artifact_not_found`）。
                        # 重建失败维持原账本：`_evidence_inputs` 只在证据真冲突时抛，
                        # 那种情况本来就该硬失败（错误码仍是原码）。
                        evidence_ledger, artifacts = self._evidence_inputs(
                            turn_payload,
                            snapshot,
                            tenant_id=tenant_id,
                            session_id=session_id,
                        )
                    else:
                        artifacts = self._artifact_inputs(
                            turn_payload, snapshot, tenant_id=tenant_id, session_id=session_id,
                        )
                    artifact_ceiling = await self._artifact_version_ceiling(
                        artifacts,
                        snapshot=snapshot,
                        tenant_id=tenant_id,
                        session_id=session_id,
                        cache=artifact_ceiling_cache,
                    )
                    try:
                        return _check(fresh["output"]), True, evidence_ledger, artifacts
                    except OutputContractError as second:
                        # 修复无效：按**原错误码**硬失败（与修复前逐字一致；前端兜底
                        # 文案按码查表，码不许换）。
                        logger.warning("repair turn output rejected too: %s", second)
                        raise exc

            output, output_repaired = await _extract_output(turn)
            evidence_ledger, artifacts = self._evidence_inputs(
                turn, snapshot, tenant_id=tenant_id, session_id=session_id
            )
            # 产物版本上限（按回合缓存，见 `_artifact_version_ceiling`）：没有"本回合
            # 重基过的产物"时是 None，校验逐字维持旧行为（只认回合起始版本）。
            artifact_ceiling_cache: dict[str, Any] = {}
            artifact_ceiling = await self._artifact_version_ceiling(
                artifacts,
                snapshot=snapshot,
                tenant_id=tenant_id,
                session_id=session_id,
                cache=artifact_ceiling_cache,
            )
            output, round_repaired, evidence_ledger, artifacts = await _validate_round(
                output, evidence_ledger, artifacts, turn, artifact_ceiling
            )
            output_repaired = output_repaired or round_repaired
            # P1c-2：核验在**事件展开之前**——整轮作废时用户侧不许留下任何东西
            #（连已经"发生过"的进度事件也不行，那会让人以为这一步跑通了）。
            decision = await self._settle_evidence(
                output,
                tenant_id=tenant_id,
                session_id=session_id,
                thread_id=thread_id,
            )
            if decision.action == "recheck":
                rechecked = await self._recheck_turn(
                    thread_id, decision.recheck_hint, collect_kwargs=collect_kwargs
                )
                if rechecked is None:
                    return {
                        "error": "evidence_recheck_failed: 重查回合没有产出结构化输出",
                        "events": [],
                    }
                turn = {
                    **turn,
                    **rechecked,
                    # 首轮的工具事件要留着（那是用户看得见的工具卡片），重查轮的接在后面。
                    "events": [*(turn.get("events") or []), *(rechecked.get("events") or [])],
                }
                output, recheck_repaired = await _extract_output(turn)
                output_repaired = output_repaired or recheck_repaired
                # 账本要**重建**：模型第二轮引用的是新证据，拿首轮那份去校验
                # 会把新证据判成 `evidence_not_found`。
                evidence_ledger, artifacts = self._evidence_inputs(
                    turn, snapshot, tenant_id=tenant_id, session_id=session_id
                )
                # 上限同样重算（重查轮可能按更高的版本读到新产物）；已缓存的
                # 权威读数不会重复取（见 `_artifact_version_ceiling`）。
                artifact_ceiling = await self._artifact_version_ceiling(
                    artifacts,
                    snapshot=snapshot,
                    tenant_id=tenant_id,
                    session_id=session_id,
                    cache=artifact_ceiling_cache,
                )
                output, round_repaired, evidence_ledger, artifacts = await _validate_round(
                    output, evidence_ledger, artifacts, turn, artifact_ceiling
                )
                output_repaired = output_repaired or round_repaired
                decision = await self._settle_evidence(
                    output,
                    tenant_id=tenant_id,
                    session_id=session_id,
                    thread_id=thread_id,
                )
                if decision.action == "recheck":
                    # 上限一次：同样参数再查一遍是确定性操作，再试无益
                    #（分流表那条"上限 1 次由调用方保证"就是这里）。
                    decision = Decision(
                        "fail",
                        code="evidence_recheck_failed",
                        detail=", ".join(str(item) for item in decision.recheck_ids),
                    )
            if decision.blocks_the_turn:
                logger.warning(
                    "evidence settlement failed the turn code=%s detail=%s cited=%s",
                    decision.code,
                    decision.detail,
                    [ref.evidence_id for ref in output.evidence_refs],
                )
                return {"error": f"{decision.code}: {decision.detail}", "events": []}
            # 同档前置一次一条（2026-10-13，会话 10041981 死卡）：多条 priorityRules 直投
            # 必被 Java 拒成 blocked 卡。这里在**投递前**先给一次修复回合让它自纠
            # （选一条 / 先问顺序）；修不成**原样放行**（照旧由 Java 出 blocked 卡）——
            # 不新增失败路径，也不许修第二次（见 `_repair_priority_rule_count`）。
            # 与 `scoreUpdateRequest` / `careerUpdateRequest` 同轮的形状排除在外：那是
            # `conflicting_proposals` 硬错误，处置在下面那条检查，不走本守卫。
            if (
                output.proposal_request is not None
                and output.score_update_request is None
                and output.career_update_request is None
                and len(output.proposal_request.priority_rules) > 1
            ):
                output, priority_repaired = await self._repair_priority_rule_count(
                    thread_id,
                    output,
                    turn,
                    snapshot=snapshot,
                    evidence_ledger=evidence_ledger,
                    artifacts=artifacts,
                    tenant_id=tenant_id,
                    artifact_version_ceiling=artifact_ceiling,
                    artifact_ceiling_cache=artifact_ceiling_cache,
                )
                output_repaired = output_repaired or priority_repaired
            events: list[dict[str, Any]] = []
            for item in turn.get("events", []) if isinstance(turn, Mapping) else []:
                event = adapt_codex_item(item)
                if event is not None:
                    events.append(event)
            proposal_preview = None
            _draft_count = sum(
                draft is not None
                for draft in (
                    output.proposal_request,
                    output.score_update_request,
                    output.career_update_request,
                )
            )
            if _draft_count > 1:
                # 两个待确认草稿 = 两张卡，而一次确认只能落一个动作：**按契约错误拒** ✗，
                # 不许"先提案后补录"这种静默取舍（用户根本不知道自己确认的是哪一件事）。
                # 三个草稿（提案 / 补录 / 发展方向）两两互斥，判据统一在这里。
                raise OutputContractError(
                    "conflicting_proposals",
                    "a single turn must not carry more than one of "
                    "proposalRequest / scoreUpdateRequest / careerUpdateRequest",
                )
            _action_type = str(
                getattr(output.conversation_action, "action_type", "") or ""
            )
            _intent_draft_present = output.intent_draft is not None
            if _action_type in {"confirm_proposal", "cancel_proposal"} and (
                _draft_count > 0 or _intent_draft_present
            ):
                # “确认，但预算改成两万”这类纠正不能先执行原卡再补条件；
                # 模型必须输出新的 proposalRequest（重新预览），不能同轮 confirm + 新草稿。
                # intentDraft 也算新要求：确认回合应输出 intentDraft=null。
                raise OutputContractError(
                    "confirmation_conflicts_with_new_intent",
                    "confirm/cancel cannot be combined with a new proposal draft or intentDraft",
                )
            if output.intent_draft is not None:
                change_set = build_change_set(output.intent_draft)
                if (change_set.status != "ready" or not change_set.atomic) and _draft_count > 0:
                    # 复合要求尚未被服务端支持为原子事务：不许先执行一个
                    # 可能违反其他硬要求的子动作（例如先加入、下一轮再限学费）。
                    # **丢掉附带草稿、保留正文**：整轮失败会让用户只看到“引擎暂不可用”，
                    # 而正文本来就该说明先澄清/先约束（2026-10-18 真栈实测）。
                    output.proposal_request = None
                    output.proposal_ref = None
                    output.score_update_request = None
                    output.career_update_request = None
                    _draft_count = 0
                    output.limitations = [
                        *list(output.limitations),
                        "本轮要求尚未收敛为单个可执行动作，附带的提案已取消；请按正文说明分步确认。",
                    ]
                    # 正文可能已经写了“这是加入预览/请确认”——草稿被丢后那句话就不成立了。
                    # 必须当场纠正，不能让用户去找一张根本没生成的卡。
                    output.message = (
                        str(output.message).rstrip()
                        + "\n\n（本轮没有生成可确认的卡片：这条要求还需要先澄清或分步确认，"
                        "请按上面的说明回复。）"
                    )
            if output.proposal_request is not None:
                if output.proposal_request.source_version_guard != snapshot.snapshot_version:
                    raise OutputContractError(
                        "stale_state",
                        "proposal source version does not match the current snapshot",
                    )
                proposal_request_payload = output.proposal_request.model_dump(
                    by_alias=True, exclude_none=True
                )
                if self.mode == "codex_write":
                    # 写模式：走 prepare —— Java 把预览**物化成 pending**，并在 pending 的
                    # dataValue 里落下它产出的 operationId（写闭环的幂等键）。requestId 取
                    # "租户:会话:回合"，于是**同一回合的重试是重放**（同一个 operationId），
                    # 新回合会按 prepare 的 supersede 规则把旧的标掉。
                    proposal_response = await internal_client.prepare_user_goal_planning_fix_proposals(
                        tenant_id,
                        session_id,
                        request_id=f"{tenant_id}:{session_id}:{turn_id}",
                        payload=proposal_request_payload,
                    )
                else:
                    # 只读模式：只出预览，不产生待确认（写路径不在这台实例上活着）。
                    proposal_response = await internal_client.generate_user_goal_planning_fix_proposals(
                        tenant_id,
                        session_id,
                        proposal_request_payload,
                    )
                if (proposal_response or {}).get("code") not in (None, 0):
                    raise OutputContractError(
                        "proposal_preview_unavailable",
                        "Java proposal compiler rejected the request",
                    )
                proposal_data = (proposal_response or {}).get("data") or {}
                if isinstance(proposal_data, Mapping) and not proposal_data.get("proposals"):
                    # prepare 的返回是 PrepareResultDTO：预览在 `result` 里（外面是
                    # status/requestId/pendingId/operationId）。两种形状都认。
                    nested = proposal_data.get("result")
                    if isinstance(nested, Mapping):
                        proposal_data = nested
                proposals = proposal_data.get("proposals") if isinstance(proposal_data, Mapping) else None
                if not isinstance(proposals, list) or not proposals:
                    raise OutputContractError(
                        "proposal_preview_unavailable",
                        "Java proposal compiler returned no proposal",
                    )
                proposal_preview = next((item for item in proposals if isinstance(item, Mapping)), None)
                if proposal_preview is None:
                    raise OutputContractError(
                        "proposal_preview_unavailable",
                        "Java proposal compiler returned an invalid proposal",
                    )
                # 提案**改变了服务端状态**（写模式下 pending 已落库）：把快照缓存刷掉。
                # 不刷的后果是自锁：下一轮确认时网关拿**旧**快照核对 `proposalRef`，
                # 必然 `proposal_reference_mismatch`，而链路看上去只是"确认没生效"
                # （2026-09-24 真栈实测 —— 确认永远被自己的缓存挡住 ✗）。
                await self._refresh_snapshot_cache(key, tenant_id=tenant_id, session_id=session_id)
                # **预览里的"版本"必须换成待确认的修订号** ✓✓：Java 编译返回的预览带的是
                # **编译前**的 `sourceVersion` ✗，而确认/放弃时服务端拿它核版本 ✓ →
                # 必然判 `stale_state` ✗（实测：卡上点"放弃" ✓，回来的 `actionStatus` 就是
                # `stale_state` ✓；对照 pending 行：`revision: 1` ✓，而预览里是 `sourceVersion: 0` ✗）。
                # 刷新后的快照里 `activeProposal.data.revision` 才是**这张卡要用**的那个 ✓
                #（白名单里的 `sourceVersion` 正好是它的位置 ✓，不用扩载荷 ✗）。
                # **两样都要换成"待确认那一条"的值** ✓✓（实测形状，curl turn-snapshot 得的原文 ✓）：
                #   `activeProposal.revision = 1` ✓（在**顶层** ✓，不是 `data.revision` ✗）；
                #   `activeProposal.proposalRef = <pendingId>` ✓（**不是**编译器的 `ugp_…` ✗——
                #   卡片若带 `ugp_…` 去确认 ✓，服务端拿快照里这个核对 ✓ → 必然对不上 ✗）。
                # 白名单里的 `proposalRef`/`sourceVersion` 正好是这两个位置 ✓，载荷不用扩 ✗。
                fresh = self._snapshots.get(key)
                active = getattr(fresh, "active_proposal", None) if fresh is not None else None
                logger.info(
                    "proposal preview override: snapshot=%s active=%s attrs=%s",
                    type(fresh).__name__ if fresh is not None else "None",
                    type(active).__name__ if active is not None else "None",
                    sorted(getattr(active, "__dict__", {}).keys())[:12]
                    if not isinstance(active, Mapping) and active is not None
                    else sorted(active.keys())[:12] if isinstance(active, Mapping) else [],
                )
                # **要覆盖的是 `sourceVersion`，不是 `revision`** ✗✓（实测判据原文 ✓）：
                # `conversation_actions.py:139-152` 拿 `activeProposal.sourceVersion`（或
                # `data.sourceVersion` / `data.sourceBackendVersion` ✓）与动作里的
                # `expectedSourceVersion` 相减 ✓，不等就 `proposal_version_mismatch` ✓。
                # 覆盖语义见 `_active_proposal_preview_override`（提案/补录共用同一份 ✓）。
                if active is not None and isinstance(proposal_preview, Mapping):
                    proposal_preview = _active_proposal_preview_override(proposal_preview, active)
                # **被拒的卡要说人话** ✓（2026-10-08 "location 死卡"事故）：`blocked`
                # 预览只有 Java 的校验原文 ✓（用户读不懂它本来想调整什么 ✗）。补一句
                # 从我们**发出去的规则**生成的人话摘要 ✓；只在 blocked 卡上加 ✓——
                # 正常路径的载荷**一个字节都不变** ✓（前端白名单见到新键就当没有 ✓）。
                if isinstance(proposal_preview, Mapping) and str(
                    proposal_preview.get("status") or ""
                ).lower() == "blocked":
                    attempted_brief = _attempted_rule_brief(output.proposal_request)
                    if attempted_brief:
                        proposal_preview = {
                            **proposal_preview,
                            "attemptedRuleBrief": attempted_brief,
                        }
            elif output.score_update_request is not None:
                # **补录成绩草稿**（写闭环第二族：score_update ✓）——与提案同一张卡、
                # 同一条确认链（`proposal.preview` → `conversationAction` ✓）：
                # 模型只说"要补哪些字段" ✓，预览/校验/摘要/待确认由 Java 生产 ✓。
                proposal_preview = await self._prepare_score_update_preview(
                    key,
                    tenant_id=tenant_id,
                    session_id=session_id,
                    turn_id=turn_id,
                    request=output.score_update_request,
                    snapshot=snapshot,
                )
            elif output.career_update_request is not None:
                # **发展方向草稿**（career v1「完整落库」）——与提案/补录同一张卡、
                # 同一条确认链；差别只在执行体在网关侧（Java 没有 profile-patch 命令）。
                proposal_preview = await self._prepare_career_update_preview(
                    key,
                    tenant_id=tenant_id,
                    session_id=session_id,
                    turn_id=turn_id,
                    request=output.career_update_request,
                    snapshot=snapshot,
                )
            elif output.conversation_action.action_type in EXECUTABLE_CONVERSATION_ACTIONS:
                # **打字"确认"也要真的执行** ✓✓（2026-10-08 修：两处"吞事件"缺口之一）。
                # 文本回合里模型用 `conversationAction` 表达确认/取消时，这一支以前
                # **不存在** ✗：校验器放行（`output_validation.py` 只做 ref/版本核对 ✓），
                # 之后没有任何执行分支 ✓ → 无 Java 调用 ✓、无结果事件 ✓、无报错 ✓，
                # 而模型嘴上照说"已提交" ✓（会话 10041979 的谎报正是这个形状 ✓）。
                # 现在复用点卡路径的执行器 ✓（见 `_execute_turn_action` 的对称关系 ✓），
                # 结果经 `actionResult` 键由 `_emit_turn_terminal` 发成
                # `conversationAction.result` ✓——与点卡路径同一个发射器 ✓。
                action_result_payload, action_snapshot_version = await self._execute_turn_action(
                    tenant_id=tenant_id,
                    session_id=session_id,
                    action=output.conversation_action,
                    snapshot=snapshot,
                )
            elif output.conversation_action.action_type not in {
                "none",
                "continue_readonly",
                "request_clarification",
            }:
                # 无执行器的动作类型（`create_proposal` / `refresh_proposal` ✓）：保持原行为 ✗，
                # 但不再**无声**——提案要走 `proposalRequest` ✓，这两类动作今天没有对应执行器 ✓；
                # 留一行日志，下一次有人追问"模型说要做却没发生"时查得到 ✓。
                logger.info(
                    "model conversationAction %r has no executor (turn=%s session=%s); "
                    "proposal path is proposalRequest",
                    output.conversation_action.action_type,
                    turn_id,
                    session_id,
                )
            working_set = self._working_sets.get(key)
            if working_set is not None:
                working_set.ingest_payload(turn, turn_id=turn_id)
                working_set.apply_output(output, turn_id)
                if self.task_ledger is not None:
                    if working_set.task_draft is not None:
                        await _maybe_await(
                            self.task_ledger.save(
                                key.tenant_id, key.session_id, working_set.task_draft
                            )
                        )
                    elif (
                        str(getattr(output.conversation_action, "action_type", "") or "")
                        == "cancel_proposal"
                        or (
                            output.intent_draft is not None
                            and build_change_set(output.intent_draft).status == "blocked"
                        )
                    ):
                        # blocked 草稿不落任务页；旧账本也要清，否则“继续”会捞出
                        # 一个未实现动作（J1）。
                        await _maybe_await(
                            self.task_ledger.clear(key.tenant_id, key.session_id)
                        )
            trace = build_turn_trace(
                turn,
                output,
                entity_ids=[
                    str(item["entityId"])
                    for item in (working_set.candidate_entities if working_set else [])
                    if item.get("entityId")
                ],
            )
            journey_result = turn_journey_result(
                snapshot,
                output,
                [str(call.get("name") or "") for call in trace.tool_calls],
            )
            if journey_result and journey_result.get("taskIntent") == "review":
                raw_journey = snapshot.journey if isinstance(snapshot.journey, Mapping) else {}
                current_ws = self._working_sets.get(key) or working_set
                if current_ws is not None:
                    current_ws.mark_manual_review(
                        raw_journey.get("planContentDigest"),
                        raw_journey.get("planVersion"),
                    )
            output = synthesize_execution_status(output, trace.batch_report)
            return {
                "output": output,
                "events": events,
                "threadId": thread_id,
                "trace": trace.as_payload(),
                "recovery": {"outputRepaired": output_repaired},
                "proposalPreview": dict(proposal_preview) if proposal_preview is not None else None,
                **({"journey": journey_result} if journey_result is not None else {}),
                # 模型发起的确认/取消：结果与点卡路径同形 ✓（`_handle_uncached` 把它带进
                # 回合结果 ✓，`server.py::_emit_turn_terminal` 一见它发
                # `conversationAction.result` ✓——同一个发射器、同一份载荷合同 ✓）。
                **_turn_action_payload(action_result_payload, action_snapshot_version),
            }
        except ThreadRecoveryError as exc:
            # 恢复失败是**可恢复错误**，不是"这个会话坏了"：既不许建一个新身份
            # 把用户上下文换掉（那是最坏的结果：看起来正常，其实丢了历史），
            # 也不许把会话判死——下一回合重试即可。
            # detail 必须一起打：`thread_resume_failed` 这一个码对应好几种成因，
            # 而"等锁 / 重建 / 报错"的处置各不相同。只有码的日志会让人重新去猜。
            logger.warning(
                "thread recovery failed session=%s code=%s detail=%s",
                session_id,
                exc.code,
                exc,
            )
            return {"error": exc.code, "recoverable": True, "events": []}
        except AppServerExited as exc:
            # 回合中途进程死了：**当轮失败**（如实说），但要把 runtime 拉起来——
            # 不拉的话下一轮还是秒失败，而进程不会自己复活。
            logger.warning("app server exited during the turn (session=%s): %s", session_id, exc)
            try:
                await self._restart_runtime()
            except Exception as restart_exc:  # noqa: BLE001 —— 拉不起来也要如实报错
                logger.warning("runtime restart failed: %s", restart_exc)
            return {"error": "app_server_exited", "recoverable": True, "events": []}
        except (OutputContractError, ValueError, KeyError) as exc:
            # 结果已经出站（模型发起的确认/取消执行成功而收尾失败）时必须**原样带回** ✓：
            # 它由 `_emit_turn_terminal` 在失败分支**先于** `recoverable.error` 发出 ✓，
            # 漏了它，库里已经落地的改动在页面上永远停在"待确认" ✗
            # （与 `execute_action_and_refresh` docstring 同一条不变量 ✓）。
            code = str(getattr(exc, "code", "") or exc)
            fixed_reply = _FIXED_TURN_REPLIES.get(code)
            return {
                "error": str(exc),
                "events": [],
                **({"reply": fixed_reply} if fixed_reply else {}),
                **_turn_action_payload(action_result_payload, action_snapshot_version),
            }
        except Exception as exc:
            # **堆栈必须留下** ✗✓：原来只回一个类名（`RuntimeError` ✗）——
            # 用户看到的是"引擎暂时不可用" ✓，而日志里**没有任何可查的东西** ✗：
            # 实测就是这么卡住的（首轮一个 `RuntimeError` ✗，来回猜了几轮 ✓）。
            # 回给用户的那句仍然是通用的 ✓（不泄漏内部细节 ✓），但日志要能定位 ✓。
            logger.exception("codex turn crashed: %s", type(exc).__name__)
            return {
                "error": type(exc).__name__,
                "events": [],
                **_turn_action_payload(action_result_payload, action_snapshot_version),
            }

    def _evidence_inputs(
        self,
        turn: Any,
        snapshot: ConversationTurnSnapshot,
        *,
        tenant_id: str | int | None = None,
        session_id: str | int | None = None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """账本与产物表：**快照证据 + 本回合证据**，缺一不可。

        只从本回合建账本的话，快照里那些权威证据虽然被摆到了模型面前，
        模型一引用就 `evidence_not_found`——看得见、够不着（断链 4）。
        重查（P1c-2）之后要**重建**而不是复用首轮那份：模型第二轮引用的是
        新证据，拿首轮的账本去校验新输出，会把新证据判成 `evidence_not_found`。

        产物只按当前输出的引用 ID 查询可信签发 store。事件与模型正文均无登记权限；
        修复和重查后以最新输出重读，跨回合与重启不依赖本进程内存。
        """
        snapshot_evidence = [
            item.model_dump(by_alias=True) if hasattr(item, "model_dump") else item
            for item in (getattr(snapshot, "evidence", None) or [])
        ]
        turn_evidence = _collect_records(
            [
                turn.get("evidenceLedger", []),
                turn.get("events", []),
            ]
            if isinstance(turn, Mapping)
            else [],
            "evidenceLedger",
            "evidence",
            "evidenceRefs",
            "evidence_refs",
        )
        return merge_evidence(snapshot_evidence, turn_evidence), self._artifact_inputs(
            turn, snapshot, tenant_id=tenant_id, session_id=session_id,
        )

    def _artifact_inputs(
        self,
        turn: Any,
        snapshot: ConversationTurnSnapshot,
        *,
        tenant_id: str | int | None = None,
        session_id: str | int | None = None,
    ) -> dict[str, Any]:
        raw_output = turn.get("output") if isinstance(turn, Mapping) else None
        if raw_output is None and isinstance(turn, Mapping):
            raw_output = turn.get("turn", {}).get("output")
        references = (
            raw_output.get("artifactRefs", raw_output.get("artifact_refs", []))
            if isinstance(raw_output, Mapping) else []
        )
        artifact_ids = list(_by_id(references, "artifactId", "artifact_id"))
        artifacts: dict[str, Any] = {}
        if artifact_ids:
            if self.artifact_store is None or tenant_id is None:
                raise OutputContractError("artifact_store_unavailable", "artifact authority is not configured")
            try:
                artifacts = self.artifact_store.get_many(
                    tenant_id=str(tenant_id),
                    session_id=str(session_id if session_id is not None else snapshot.session_id),
                    artifact_ids=artifact_ids,
                )
            except ArtifactStoreError as exc:
                raise OutputContractError(exc.code, "artifact authority rejected the lookup") from None
        return artifacts

    async def _artifact_version_ceiling(
        self,
        artifacts: Mapping[str, Any],
        *,
        snapshot: ConversationTurnSnapshot,
        tenant_id: str,
        session_id: str,
        cache: dict[str, Any],
    ) -> int | None:
        """本回合成品引用的**版本上限**；没有"重基过的产物"时返回 None（＝旧行为）。

        2026-10-14 事故（会话 10041982）：回合内候选池生成把版本从 v 推到 v+1，
        MCP 侧有界重基之后工具按 **v+1** 签发产物；网关若仍拿回合起始的 v 严格
        相等去卡，模型终态引用 v+1 产物就会在收尾处以**非可修复**的 `stale_state`
        硬失败——"回合不再被挡死"在最后一步落空。上限让这些产物过闸。

        上限**不是**产物自证的版本：产物记录虽来自可信签发 store，仍不能替代
        Java 对当前工作区版本的权威读数。
        所以这里只在检测到"有产物版本高于回合起始"时，**重新向 Java 读一次**
        权威快照，取它的版本作上限；读不到 → 保持 None（回到严格相等，fail-closed，
        与今天一致）。`cache` 按回合传入：权威读数一个回合只取一次；没触发
        （最常见的路径）则一次都不取——旧行为在代码路径上也逐字不变。
        """
        bumped = False
        for entry in (artifacts or {}).values():
            state = entry.get("stateVersion", entry.get("state_version")) if isinstance(entry, Mapping) else None
            if state in (None, ""):
                continue
            try:
                parsed = int(state)
            except (TypeError, ValueError):
                continue
            if parsed > snapshot.snapshot_version:
                bumped = True
                break
        if not bumped:
            return None
        if "resolved" not in cache:
            cache["resolved"] = None
            try:
                fresh = _snapshot_payload(
                    await _maybe_await(
                        self.snapshot_loader(
                            tenant_id=tenant_id,
                            session_id=str(session_id),
                            skill=None,
                        )
                    )
                )
            except Exception as exc:  # noqa: BLE001 —— 读不到就退回严格相等（fail-closed）
                logger.warning(
                    "artifact version ceiling unavailable (session=%s): %s",
                    session_id,
                    exc,
                )
            else:
                cache["resolved"] = int(fresh.snapshot_version)
        return cache["resolved"]

    async def _settle_evidence(
        self,
        output: TurnOutput,
        *,
        tenant_id: str,
        session_id: str,
        thread_id: str | None = None,
    ) -> Decision:
        """问一次 Java 台账"这些证据还作数吗"，再按第六章分流表给出处置。

        权威性**不能缓存**：同一条证据上一轮还作数、这一轮可能已经失效
        （上游数据变了、过了新鲜度上限、版本台账重建过），所以模型每次引用
        都要去问一次。问完之后怎么处置全部来自
        `evidence_verification.classify`（纯函数，逐态写死），这里不自行发挥。

        没配核验器＝不核验（本地最小栈、单测）：这条是显式的，不是"忘了接"——
        所以分流表里每条 fail-closed 都不能拿"反正没核验"当解释，对照用例
        （`test_without_a_verifier_the_turn_is_unchanged`）就是为此存在。

        **拿不到答案 ≠ 没有证据要核验**：客户端层的 `verify_evidence` 已经把
        "失败也返回 dict"那个 fail-open 的形状转成异常，这里再把它转成"整轮
        作废、不放行"——依赖不可用时放宽校验，是这一步最自然的手滑。
        """
        verifier = self.evidence_verifier
        if verifier is None:
            return Decision("proceed")
        evidence_ids = [str(ref.evidence_id) for ref in output.evidence_refs]
        if not evidence_ids:
            return Decision("proceed")
        try:
            records = await _maybe_await(
                verifier(
                    tenant_id=tenant_id,
                    chat_session_id=str(session_id),
                    evidence_ids=evidence_ids,
                    thread_id=thread_id,
                )
            )
        except Exception as exc:  # noqa: BLE001 —— 任何拿不到答案的方式都算"不可用"
            logger.warning(
                "evidence verification unavailable tenant=%s session=%s ids=%s: %s",
                tenant_id,
                session_id,
                evidence_ids,
                exc,
            )
            return Decision("fail", code="evidence_verification_unavailable", detail=str(exc))
        return classify(evidence_ids, records if isinstance(records, Mapping) else {})

    async def _recheck_turn(
        self,
        thread_id: str,
        hint: str,
        *,
        collect_kwargs: Mapping[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """把重查指令回注给模型，重跑**一个**回合；拿不到结构化输出返回 None。

        只跑一次，上限由调用方保证（`_codex_turn` 里"重查后仍失效 → 整轮作废"）。
        写成循环迟早会变成无限重试，而同样参数再查一遍是确定性操作，再试无益。

        `collect_kwargs` 与首轮是**同一份**（实时进度回调 + native turn 绑定）：
        重查也是用户看得见的一轮，浏览器要能收到它的进度；`turn/steer`、
        `turn/interrupt` 也要能指到**正在跑的那一轮**——不传的话它们会指到已经
        结束的首轮（2026-09-23 复核第 2 项，我的实现漏了这个对称性）。

        没有 `start_turn_and_collect` 的 harness：**不放行**。`start_turn` 只发
        `turn/start` 就返回启动确认（`app/harness/codex.py`），那个 ack 不是回合
        结果——把 `inProgress` 当结果往下走，等于用"还没生成完"骗过重查判定。
        宁可整轮按 `evidence_recheck_failed` 作废。
        """
        recheck_input = [{"type": "text", "text": hint}]
        if not hasattr(self.codex, "start_turn_and_collect"):
            logger.warning(
                "recheck needs a harness that waits for the terminal turn; "
                "failing this turn instead (thread=%s)",
                thread_id,
            )
            return None
        collected = await self.codex.start_turn_and_collect(
            thread_id,
            recheck_input,
            TURN_OUTPUT_SCHEMA,
            **dict(collect_kwargs or {}),
        )
        if collected.status != "completed":
            return None
        turn: dict[str, Any] = {"output": collected.output, "events": collected.events}
        if collected.payload:
            turn.update(collected.payload)
        return turn

    async def _repair_turn_output(
        self,
        thread_id: str,
        issue: str,
        *,
        raw_output: str | None = None,
        allow_tool_calls: bool = False,
    ) -> dict[str, Any] | None:
        """让模型修一次不合格的最终输出；拿不到合法结构化输出返回 None。

        `raw_output` 是**上一回合的原始最终文本**（截断到 1500 字符，见
        `_repair_output_excerpt`）。2026-10-06 真事故：模型在 JSON 字符串值里写了
        未转义的英文双引号（`有的省是"第一段/第二段"…`）→ 解析失败 →
        修复回合只拿到 `output_missing` 一句 issue，看不到自己写坏的那段文本，
        于是**重复同类错误**，整轮升级成 `output_schema_invalid`，用户看到
        "当前对话引擎暂时不可用"。把坏文本摆回去 + 写死引号规则，修复回合才有
        可执行的修改目标。没拿到文本（旧 harness / 非 collect 路径）时，提示词
        退化成原来的形状，行为不变。

        `allow_tool_calls=True`（2026-10-15 §41，仅产物引用一族）：把"不要调用
        新工具"换成"允许调用只读工具重新取引用"——旧产物可能因版本推进而没得引，
        而推荐类输出又必须带引用，不给重取的路，模型只能编。调用方负责在这种修复
        之后**重建账本**（`_LEDGER_REBUILD_REPAIR_CODES`）。
        """
        if not hasattr(self.codex, "start_turn_and_collect"):
            return None
        tool_rule = (
            "允许调用只读工具重新获取产物引用（不得编造 id）；"
            if allow_tool_calls
            else "不要调用新工具；"
        )
        instruction = (
            "上一回合已经完成用户问题和已有工具调用，但最终结构化输出未通过契约校验。"
            "不要重新解释用户意图、"
            + tool_rule
            + "不要编造事实；仅依据本线程已有上下文和工具结果，"
            "修正并返回符合输出 Schema 的最终结果。"
            "硬性要求：只输出一段合法 JSON（不要 markdown 围栏、不要任何解释文字）；"
            "字符串值内不得出现英文双引号（\"），需要引用时一律用「」或『』；"
            "字符串内的引号、反斜杠、换行必须按 JSON 规则转义。"
            "校验问题：" + issue
        )
        excerpt = _repair_output_excerpt(raw_output)
        if excerpt is not None:
            instruction += (
                "\n\n上一回合失败输出的原始文本（最多截取前 1500 字符，用于定位；"
                "截断处不完整属正常）：\n" + excerpt
            )
        collected = await self.codex.start_turn_and_collect(
            thread_id,
            [{"type": "text", "text": instruction}],
            TURN_OUTPUT_SCHEMA,
        )
        if collected.status != "completed" or not isinstance(collected.output, dict):
            return None
        return {"output": collected.output, "events": collected.events}

    async def _repair_priority_rule_count(
        self,
        thread_id: str,
        output: TurnOutput,
        turn: Any,
        *,
        snapshot: Any,
        evidence_ledger: list[dict[str, Any]],
        artifacts: dict[str, Any],
        tenant_id: str,
        artifact_version_ceiling: int | None = None,
        artifact_ceiling_cache: dict[str, Any] | None = None,
    ) -> tuple[TurnOutput, bool]:
        """同档前置多条 → 先给**一次**纠错回合；修不成原样返回（不吞、不硬失败）。

        2026-10-13 真事故（会话 10041981）：多层偏好被模型压进一次提案的多条
        `priorityRules`（"北京→财经→沪广深"）→ Java `priority_rule_invalid`
        （"当前只支持一条同档前置规则"）→ `blocked` 死卡。与契约层的拒收（如
        location 域）不同：那条路的语义是"拒了就走修复回合、修不好 `output_schema_invalid`
        硬失败"，而这里**修不好必须维持原行为**（原请求照发 Java、照旧出 blocked 卡，
        用户至少能看到"为什么没成"的解释）——所以修复提示不挂 `_REPAIR_HINT_BY_CODE`，
        采纳与否由本方法看守：

        - 修复回合拿不到输出（或拿到的输出连 `TurnOutput` 都不合法 / 仍多条）→
          返回原输出，`False`，后续一切照旧；
        - 修好的候选还要过 `validate_turn_output`（与 `_validate_round` 的 `_check`
          同一套参数）才采纳：替换输出、把修复回合事件并进本回合，返回 `True`。
          不调用新工具也可能改引已签发的其他产物，因此候选引用仍要重查可信 store；
          不重建证据账本，候选不合格时整体退回原输出。
        """
        if not isinstance(turn, dict):
            return output, False
        repaired = await self._repair_turn_output(
            thread_id,
            _PRIORITY_RULE_COUNT_REPAIR_HINT,
            raw_output=_last_agent_text(turn),
        )
        if repaired is None:
            return output, False
        try:
            candidate = TurnOutput.model_validate(repaired["output"])
            if (
                candidate.proposal_request is not None
                and (
                    # 又给多条：不修第二次——原样放行（Java 照旧拒单）。
                    len(candidate.proposal_request.priority_rules) > 1
                    # 版本守卫必须在采纳前核掉：否则下面的提案分支会以 `stale_state`
                    # 硬失败——修复回合反而制造了一条新的失败路径。
                    or candidate.proposal_request.source_version_guard
                    != snapshot.snapshot_version
                )
            ):
                return output, False
            if candidate.conversation_action.action_type in EXECUTABLE_CONVERSATION_ACTIONS:
                # 修复回合不是执行回合：候选若带上可执行的确认/取消动作，一律不采纳
                # （多规则提案这条路上，原输出今天走不到任何动作执行）。
                return output, False
            artifacts = self._artifact_inputs(
                repaired, snapshot, tenant_id=tenant_id, session_id=snapshot.session_id,
            )
            refreshed_ceiling = await self._artifact_version_ceiling(
                artifacts, snapshot=snapshot, tenant_id=tenant_id,
                session_id=snapshot.session_id,
                cache=artifact_ceiling_cache if artifact_ceiling_cache is not None else {},
            )
            if refreshed_ceiling is not None:
                artifact_version_ceiling = refreshed_ceiling
            validate_turn_output(
                turn_output=candidate,
                current_snapshot=snapshot,
                evidence_ledger=evidence_ledger,
                artifacts=artifacts,
                thread_id=thread_id,
                tenant_id=tenant_id,
                allow_proposal=True,
                strict_scope=True,
                artifact_version_ceiling=artifact_version_ceiling,
            )
        except (ValidationError, OutputContractError):
            # 候选自身不合格：丢掉它、维持原行为（这里绝不让修复变成新的失败路径）。
            return output, False
        turn.update(
            {
                "output": repaired["output"],
                "events": [*(turn.get("events") or []), *(repaired.get("events") or [])],
            }
        )
        return candidate, True
