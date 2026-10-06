from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import logging
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from pydantic import ValidationError

from app.gateway.contracts import ConversationTurnSnapshot, ProposalRequest, TurnOutput
from app.gateway.event_adapter import adapt_codex_item, adapt_notification
from app.gateway.output_validation import (
    OutputContractError,
    merge_evidence,
    validate_turn_output,
)
from app.gateway.evidence_verification import Decision, classify
from app.gateway.conversation_actions import ConversationActionResult, execute_conversation_action
from app.gateway.snapshot import build_snapshot, diff_snapshots
from app.gateway.thread_recovery import ThreadRecovery, ThreadRecoveryError
from app.harness.client import AppServerExited
from app.gateway.ui_events import SessionKey
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


def _maybe_await(value: Any) -> Any:
    return value if inspect.isawaitable(value) else _Immediate(value)


def _session_key(tenant_id: str | int, session_id: str | int) -> SessionKey:
    """本进程所有会话级缓存的键。

    两个租户的 sessionId 相同**不是**同一个用户，所以 key 必须带上租户。
    这就是为什么这里返回的是 SessionKey 而不是 str——字符串键会让
    `session_id=42` 在两个租户之间悄悄共享同一份快照和同一个 thread。
    """
    return SessionKey(tenant_id=str(tenant_id), session_id=str(session_id))


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


def _progress_emitter(
    emit: Callable[[dict[str, Any]], Awaitable[None]] | None, ui_turn_id: str
) -> Callable[[dict[str, Any]], Awaitable[None]] | None:
    """把原生通知适配成展示事件后交给 `emit`。

    这个回调跑在**模型 reader 的关键路径**上：它不 await 浏览器。调用方拿到事件后
    应当写进队列/事件存储就返回，慢消费者由发送侧自己处理（超限断连并让它 resume）。
    """
    if emit is None:
        return None
    # **`turn.phase` 要有人发** ✓✓：白名单里一直有它 ✓、前端 reducer 也在等它 ✓
    #（`conversationSession.mjs:51-52` ✓），全仓却**没有任何生产者** ✗——阶段永远是空的 ✓。
    # 最小实现：**首次**工具进度到达时补一条（阶段就是"正在调工具/取数" ✓，标签用
    # 第一个工具自己的标签 ✓——`TOOL_LABELS` 是"只解释正在发生的操作" ✓）。
    # 只发一次：重查轮复用同一个 emitter ✓（`collect_kwargs` ✓），阶段不会被重复播报 ✓。
    phase_sent = False

    async def callback(notification: dict[str, Any]) -> None:
        nonlocal phase_sent
        events = adapt_notification(notification, ui_turn_id)
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
        base_instructions: str = "",
        developer_instructions: str = "",
        current_binding_loader: Callable[..., Any] | None = None,
        evidence_verifier: Callable[..., Any] | None = None,
    ) -> None:
        # `codex_write`（P2）：允许写闭环的模式。它与 readonly 的差别**不在模型能调什么**
        # ——写路径由"模型出提案（proposalRequest）→ Java 编译出 pending → 用户确认 →
        # 网关执行（pending/resolve → pending-command/execute）"承担，模型始终没有
        # 可以自己调用的写工具（P2 任务书二之二的形状）。模式名的意义是让部署侧
        # 明确"这个实例的确认链是活的"，并与只读实例分开配置。
        if mode not in {"legacy", "codex_shadow", "codex_readonly", "codex_write"}:
            raise ValueError("unsupported gateway mode")
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
        self.session_runtime = session_runtime
        self.base_instructions = base_instructions
        self.developer_instructions = developer_instructions
        self._threads: dict[SessionKey, str] = {}
        self._snapshots: dict[SessionKey, ConversationTurnSnapshot] = {}
        self._working_sets: dict[SessionKey, ConversationWorkingSet] = {}
        self._turn_cache: dict[tuple[SessionKey, str], dict[str, Any]] = {}
        self._turn_digests: dict[tuple[SessionKey, str], str] = {}
        self._session_locks: dict[SessionKey, asyncio.Lock] = {}
        self.thread_recovery = ThreadRecovery(
            resume=self._resume_thread,
            create=self._create_thread,
            lookup=current_binding_loader,
            restart=self._restart_runtime,
        )

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

    async def interrupt_codex_turn(self, key: Any, codex_turn_id: str) -> bool:
        """停止一个**原生**回合。只停推理，不撤销已提交的 Java 事务。"""
        thread_id = self._threads.get(self._as_session_key(key))
        if not thread_id or self.codex is None:
            return False
        await self.codex.interrupt_turn(thread_id, codex_turn_id)
        return True

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
        self._working_sets[key] = ConversationWorkingSet.from_snapshot(fresh)

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

    async def execute_action_and_refresh(
        self,
        *,
        tenant_id: str,
        session_id: str,
        action: Any,
        snapshot: ConversationTurnSnapshot | Mapping[str, Any],
    ) -> dict[str, Any]:
        """显式执行动作，并在后端成功变更后刷新权威会话状态。"""
        result = await self.execute_action(
            tenant_id=tenant_id,
            session_id=session_id,
            action=action,
            snapshot=snapshot,
        )
        payload: dict[str, Any] = {"actionResult": result.as_dict()}
        if result.action_status not in {"applied", "cancelled"}:
            return payload
        refreshed = _snapshot_payload(
            await _maybe_await(
                self.snapshot_loader(
                    tenant_id=tenant_id,
                    session_id=str(session_id),
                    skill=None,
                )
            )
        )
        key = _session_key(tenant_id, session_id)
        self._store_snapshot(key, refreshed)
        self._working_sets[key] = ConversationWorkingSet.from_snapshot(refreshed)
        payload["snapshot"] = refreshed.model_dump(by_alias=True)
        payload["snapshotVersion"] = refreshed.snapshot_version
        return payload

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
        session_lock = self._session_locks.setdefault(cache_key[0], asyncio.Lock())
        async with session_lock:
            cached = self._turn_cache.get(cache_key)
            if cached is not None:
                if self._turn_digests.get(cache_key) != input_digest:
                    return {
                        "mode": self.mode,
                        "reply": "同一回合编号对应了不同内容，请重新发起本次请求。",
                        "events": [],
                        "snapshotVersion": cached.get("snapshotVersion"),
                        "writeAttempted": False,
                        "error": "turn_id_input_conflict",
                    }
                return cached
            result = await self._handle_uncached(
                tenant_id=tenant_id,
                session_id=session_id,
                user_id=user_id,
                turn_id=turn_id,
                content=content,
                emit=emit,
            )
            self._turn_cache[cache_key] = result
            self._turn_digests[cache_key] = input_digest
            return result

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
            working_set.admission_facts = list(previous_working_set.admission_facts)
            working_set.artifact_refs = list(previous_working_set.artifact_refs)
            working_set.last_response_type = previous_working_set.last_response_type
            working_set.last_turn_id = previous_working_set.last_turn_id
            working_set.candidate_scope_version = previous_working_set.candidate_scope_version
            working_set.candidate_scope_stage = previous_working_set.candidate_scope_stage
            working_set.candidate_source_turn_id = previous_working_set.candidate_source_turn_id
            if working_set.active_proposal is None:
                working_set.active_proposal = previous_working_set.active_proposal
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
            return {
                "mode": self.mode,
                "reply": "当前对话引擎暂时不可用，请稍后重试。",
                "events": codex_result.get("events", []),
                "snapshotVersion": snapshot.snapshot_version,
                "statePatch": state_patch.model_dump(by_alias=True) if state_patch else None,
                "writeAttempted": False,
                "error": codex_result["error"],
                # "这一回合失败了"和"这个会话坏了"要分得开：恢复失败属于前者，
                # 下一回合重试即可，调用方（以及前端）不必把它当成终局。
                "recoverable": bool(codex_result.get("recoverable")),
            }
        output = codex_result["output"]
        await self._persist_agent(session_id, output.message)
        return {
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
        }

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
    ) -> dict[str, Any]:
        if self.codex is None:
            return {"error": "codex_unavailable", "events": []}
        try:
            key = _session_key(tenant_id, session_id)
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
            snapshot_item = {"type": "text", "text": json.dumps(state_payload, ensure_ascii=False)}
            working_set = self._working_sets.get(key)
            context_items = [snapshot_item]
            if working_set is not None:
                context_items.append(
                    {"type": "text", "text": working_set.as_context_text()}
                )
                execution_plan = build_execution_plan(snapshot, working_set)
                context_items.append(
                    {
                        "type": "text",
                        "text": (
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
                        "text": (
                            "【工具编排约束】\n"
                            "以下约束用于避免不完整查询和重复读取，不是用户新问题。\n"
                            + render_tool_contracts()
                        ),
                    }
                )
            turn_input = list(context_items)
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
                    repaired = await self._repair_turn_output(thread_id, str(exc))
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

            def _validate_round(
                output_value: TurnOutput,
                evidence_ledger: list[dict[str, Any]],
                artifacts: dict[str, Any],
            ) -> None:
                try:
                    validate_turn_output(
                        turn_output=output_value,
                        current_snapshot=snapshot,
                        evidence_ledger=evidence_ledger,
                        artifacts=artifacts,
                        thread_id=thread_id,
                        tenant_id=tenant_id,
                        allow_proposal=True,
                        strict_scope=True,
                    )
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
                    raise

            output, output_repaired = await _extract_output(turn)
            evidence_ledger, artifacts = self._evidence_inputs(turn, snapshot)
            _validate_round(output, evidence_ledger, artifacts)
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
                evidence_ledger, artifacts = self._evidence_inputs(turn, snapshot)
                _validate_round(output, evidence_ledger, artifacts)
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
            events: list[dict[str, Any]] = []
            for item in turn.get("events", []) if isinstance(turn, Mapping) else []:
                event = adapt_codex_item(item)
                if event is not None:
                    events.append(event)
            proposal_preview = None
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
                if active is not None and isinstance(proposal_preview, Mapping):
                    override = dict(proposal_preview)
                    # **`active_proposal` 是模型，不是 dict** ✗✓（实测：按字典读**一次都没命中** ✓，
                    # 而版本看起来"对"是因为 Java 在 pending 存在后自己就返回 1 ✓——差点被这个巧合骗过去 ✓）。
                    # 所以字典键与属性两条路都走 ✓，别名（驼峰/snake）也各试一次 ✓。
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

                    # **要覆盖的是快照的 `sourceVersion`，不是 `revision`** ✗✓（实测判据原文 ✓）：
                    # `conversation_actions.py:139-152` 拿 `activeProposal.sourceVersion`（或
                    # `data.sourceVersion` / `data.sourceBackendVersion` ✓）与动作里的
                    # `expectedSourceVersion` 相减 ✓，不等就 `proposal_version_mismatch` ✓。
                    # `revision` 是**另一个字段** ✓（同文件 156 行起另有用处 ✓）——
                    # 上一轮我把 `sourceVersion` 覆盖成了 `revision` ✓，于是"身份对了、版本错了" ✓✗。
                    source_version = _field("sourceVersion", "source_version")
                    if source_version is None:
                        # 判据里的第二、三个来源在 `active.data` 上 ✓（`conversation_actions.py:142-143` ✓）。
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
                    proposal_preview = override
            working_set = self._working_sets.get(key)
            if working_set is not None:
                working_set.ingest_payload(turn, turn_id=turn_id)
                working_set.apply_output(output, turn_id)
            trace = build_turn_trace(
                turn,
                output,
                entity_ids=[
                    str(item["entityId"])
                    for item in (working_set.candidate_entities if working_set else [])
                    if item.get("entityId")
                ],
            )
            output = synthesize_execution_status(output, trace.batch_report)
            return {
                "output": output,
                "events": events,
                "threadId": thread_id,
                "trace": trace.as_payload(),
                "recovery": {"outputRepaired": output_repaired},
                "proposalPreview": dict(proposal_preview) if proposal_preview is not None else None,
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
            return {"error": str(exc), "events": []}
        except Exception as exc:
            # **堆栈必须留下** ✗✓：原来只回一个类名（`RuntimeError` ✗）——
            # 用户看到的是"引擎暂时不可用" ✓，而日志里**没有任何可查的东西** ✗：
            # 实测就是这么卡住的（首轮一个 `RuntimeError` ✗，来回猜了几轮 ✓）。
            # 回给用户的那句仍然是通用的 ✓（不泄漏内部细节 ✓），但日志要能定位 ✓。
            logger.exception("codex turn crashed: %s", type(exc).__name__)
            return {"error": type(exc).__name__, "events": []}

    def _evidence_inputs(
        self, turn: Any, snapshot: ConversationTurnSnapshot
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """账本与产物表：**快照证据 + 本回合证据**，缺一不可。

        只从本回合建账本的话，快照里那些权威证据虽然被摆到了模型面前，
        模型一引用就 `evidence_not_found`——看得见、够不着（断链 4）。
        重查（P1c-2）之后要**重建**而不是复用首轮那份：模型第二轮引用的是
        新证据，拿首轮的账本去校验新输出，会把新证据判成 `evidence_not_found`。
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
        artifacts = _by_id(
            _collect_records(
                [
                    turn.get("artifacts", []),
                    turn.get("events", []),
                ]
                if isinstance(turn, Mapping)
                else [],
                "artifacts",
                "artifactRefs",
                "artifact_refs",
            ),
            "artifactId",
            "artifact_id",
        )
        return merge_evidence(snapshot_evidence, turn_evidence), artifacts

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

    async def _repair_turn_output(self, thread_id: str, issue: str) -> dict[str, Any] | None:
        if not hasattr(self.codex, "start_turn_and_collect"):
            return None
        collected = await self.codex.start_turn_and_collect(
            thread_id,
            [
                {
                    "type": "text",
                    "text": (
                        "上一回合已经完成用户问题和已有工具调用，但最终结构化输出未通过契约校验。"
                        "不要重新解释用户意图、不要调用新工具、不要编造事实；仅依据本线程已有上下文和工具结果，"
                        "修正并返回符合输出 Schema 的最终结果。校验问题："
                        + issue
                    ),
                }
            ],
            TURN_OUTPUT_SCHEMA,
        )
        if collected.status != "completed" or not isinstance(collected.output, dict):
            return None
        return {"output": collected.output, "events": collected.events}
