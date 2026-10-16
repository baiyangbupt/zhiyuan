"""原生问答桥：把 Codex 的 server→client 请求接到浏览器上的澄清卡。

链路是**双向**的，这一点决定了实现形状：
Codex 发出带 id 的 JSON-RPC 请求 → 我们把它变成一张卡推给用户 →
用户作答 → 我们**用原来的 id** 把答案回给 Codex。
`turn/steer` 替代不了这条回包：它不是那个请求的 result。

几条不能让步的约束，都来自真实缺陷的形状：

- **答案形状由服务端保存，不信浏览器。** 选项文案、题目 id、可选值全部留在
  broker 里；浏览器只能提交它被告知过的东西。
- **过期不能只回一个 RPC error。** Runtime 可能把它当成 `answers:{}` 继续跑，
  于是"用户没回答"变成"用户回答了空"。过期必须先中断回合、等终态。
- **同一请求重复作答：同答案算收到，不同答案算冲突。** 后者是客户端把两个
  请求搞混了，替它挑一个是错的。
"""
from __future__ import annotations

import asyncio
import logging
import math
import secrets
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from app.gateway.ui_events import SessionKey


logger = logging.getLogger(__name__)

NATIVE_USER_INPUT_METHOD = "item/tool/requestUserInput"
MCP_ELICITATION_METHOD = "mcpServer/elicitation/request"

INPUT_KIND_CHOICE = "choice"
INPUT_KIND_FORM = "form"

# 上限都是**产品约束**，不是技术限制：一张卡超过三个问题，用户就不答了。
MAX_QUESTIONS = 3
MAX_FREE_TEXT = 2000
DEFAULT_TTL_SECONDS = 600.0


class UserInputError(RuntimeError):
    def __init__(self, code: str, message: str = "") -> None:
        # code 必须出现在正文里：只留 detail 的话，日志和断言看到的是
        # "confirm" 这种字段名，读的人要往回翻代码才知道发生了什么。
        super().__init__(f"{code}: {message}" if message else code)
        self.code = code


@dataclass
class PendingInput:
    key: SessionKey
    runtime_generation: str
    rpc_id: int | str
    ui_request_id: str
    ui_turn_id: str
    input_kind: str
    question_ids: frozenset[str]
    questions: list[dict[str, Any]] = field(default_factory=list)
    requested_schema: dict[str, Any] | None = None
    future: asyncio.Future[dict[str, Any]] | None = None
    expires_at: float = 0.0
    answered: bool = False
    answer_digest: str = ""
    native_thread_id: str = ""
    native_turn_id: str = ""


@dataclass(frozen=True)
class _AnswerReceipt:
    key: SessionKey
    runtime_generation: str
    answer_digest: str
    expires_at: float


class UserInputBroker:
    def __init__(
        self,
        *,
        runtime_generation: str,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
        on_expired: Any | None = None,
        scope_resolver: Any | None = None,
        turn_resolver: Any | None = None,
        answer_cache_max_entries: int = 1024,
        answer_cache_ttl_seconds: float = 600.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not math.isfinite(ttl_seconds) or ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive and finite")
        if type(answer_cache_max_entries) is not int or answer_cache_max_entries <= 0:
            raise ValueError("answer_cache_max_entries must be a positive integer")
        if not math.isfinite(answer_cache_ttl_seconds) or answer_cache_ttl_seconds <= 0:
            raise ValueError("answer_cache_ttl_seconds must be positive and finite")
        self.runtime_generation = str(runtime_generation)
        self._ttl = float(ttl_seconds)
        self._clock = clock
        self._answer_cache_max_entries = answer_cache_max_entries
        self._answer_cache_ttl = float(answer_cache_ttl_seconds)
        self._answered: OrderedDict[str, _AnswerReceipt] = OrderedDict()
        self._pending: dict[str, PendingInput] = {}
        self._by_rpc: dict[tuple[str, type, int | str], str] = {}
        self._on_expired = on_expired
        # 卡片要推给前端才有意义。没有 emitter 时桥是**惰性**的——
        # 模型提问、服务端挂起、十分钟后过期，而用户从头到尾没被告知过。
        self._emitter: Any | None = None
        # 身份只能由**服务端**给出：从 threadId 查回我们自己的绑定。
        # 请求参数里的 tenant/session 是运行时转述的，模型也可能参与其中，
        # 拿它当可信身份就是把隔离边界交给了被隔离的一方。
        self._scope_resolver = scope_resolver
        # 回合号同样要**翻译**（见 `_business_turn_id`）：请求里带的是 codex
        # 原生号，而事件流按业务号索引。解析器由装配侧注入（运行时晚于本桥创建）。
        self._turn_resolver = turn_resolver

    def set_emitter(self, emitter: Any) -> None:
        """注入"把事件推给该会话当前连接"的函数。"""
        self._emitter = emitter

    def set_scope_resolver(self, resolver: Any) -> None:
        """延迟注入：解析器要拿业务绑定，而绑定在 broker 建好之后才存在。"""
        self._scope_resolver = resolver

    def scope_for_request(self, raw: dict[str, Any]) -> SessionKey | None:
        if raw.get("method") not in {NATIVE_USER_INPUT_METHOD, MCP_ELICITATION_METHOD}:
            return None
        params = raw.get("params")
        if not isinstance(params, dict):
            raise PermissionError("clarification_scope_unavailable")
        return self._scope_from_params(params)

    # ── Codex → 我们 ────────────────────────────────────────────────
    async def handle_server_request(self, raw: dict[str, Any]) -> dict[str, Any] | None:
        """挂到 `set_server_request_handler` 上。

        返回值会由 client 用**原来的 rpc id** 写回 Codex——所以这里只负责
        "把问题变成卡片并等答案"，不负责拼 JSON-RPC。
        """
        method = str(raw.get("method") or "")
        if method == NATIVE_USER_INPUT_METHOD:
            return await self._handle_native(raw)
        if method == MCP_ELICITATION_METHOD:
            return await self._handle_elicitation(raw)
        return None

    async def _handle_native(self, raw: dict[str, Any]) -> dict[str, Any]:
        params = raw.get("params") or {}
        questions = params.get("questions") or []
        if len(questions) > MAX_QUESTIONS:
            raise UserInputError("too_many_questions", f"at most {MAX_QUESTIONS} questions per card")
        for question in questions:
            if question.get("isSecret"):
                # 口令类输入不进卡片、不落库、不经过模型：这条桥没有它的位置。
                raise UserInputError("secret_input_unsupported")
        record = await self._register(
            raw,
            native_turn_id=str(params.get("turnId") or ""),
            input_kind=INPUT_KIND_CHOICE,
            questions=[dict(question) for question in questions],
            question_ids=frozenset(
                str(question.get("id")) for question in questions if question.get("id")
            ),
            key=self._scope_from_params(params),
        )
        return await self._await_answer(record)

    async def _handle_elicitation(self, raw: dict[str, Any]) -> dict[str, Any]:
        params = raw.get("params") or {}
        mode = str(params.get("mode") or "")
        if mode != "form":
            # URL 流程首期不接：它把用户带去站外，而我们既看不到也控制不了那边发生了什么。
            raise UserInputError("unsupported_elicitation_mode", mode)
        schema = params.get("requestedSchema")
        if not isinstance(schema, dict):
            raise UserInputError("missing_requested_schema")
        record = await self._register(
            raw,
            native_turn_id=str(params.get("turnId") or ""),
            input_kind=INPUT_KIND_FORM,
            questions=[],
            question_ids=frozenset(),
            requested_schema=schema,
            key=self._scope_from_params(params),
        )
        result = await self._await_answer(record)
        # form 的回包形状与 choice 不同：action + typed content，不是一个 answers 数组。
        if result.get("action") in {"decline", "cancel"}:
            return {"action": result["action"], "content": None, "_meta": None}
        return {
            "action": "accept",
            "content": result.get("content") or {},
            "_meta": None,
        }

    async def _register(
        self,
        raw: dict[str, Any],
        *,
        native_turn_id: str,
        input_kind: str,
        questions: list[dict[str, Any]],
        question_ids: frozenset[str],
        key: SessionKey,
        requested_schema: dict[str, Any] | None = None,
    ) -> PendingInput:
        rpc_id = raw.get("id")
        if rpc_id is None:
            raise UserInputError("server_request_without_id")
        if type(rpc_id) not in (int, str):
            raise UserInputError("server_request_invalid_id")
        rpc_key = self._rpc_key(self.runtime_generation, rpc_id)
        if rpc_key in self._by_rpc:
            raise UserInputError("server_request_id_conflict")
        self._prune_answered()
        # **原生回合号在**这里**翻译成业务回合号** ✓✓：这条事件从头到尾都该
        # 以业务号出现（入流盖章 ✓、快照恢复 ✓、前端按 `[data-turn-id]` 归位 ✓）
        # ——见 `_business_turn_id` 里那条实测根因 ✓。
        ui_turn_id = self._business_turn_id(key, native_turn_id)
        # UI requestId 必须不可预测：它同时是浏览器唯一能引用的句柄，
        # 可预测的 id 等于让一个用户去猜另一个用户的卡片。
        ui_request_id = secrets.token_urlsafe(16)
        record = PendingInput(
            key=key,
            runtime_generation=self.runtime_generation,
            rpc_id=rpc_id,
            ui_request_id=ui_request_id,
            ui_turn_id=ui_turn_id,
            input_kind=input_kind,
            question_ids=question_ids,
            questions=questions,
            requested_schema=requested_schema,
            future=asyncio.get_running_loop().create_future(),
            expires_at=self._clock() + self._ttl,
            native_thread_id=str((raw.get("params") or {}).get("threadId") or ""),
            native_turn_id=native_turn_id,
        )
        self._pending[ui_request_id] = record
        self._by_rpc[rpc_key] = ui_request_id
        try:
            if self._emitter is not None:
                await self._emitter(
                    key,
                    {
                        "type": "clarification.requested",
                        "sessionId": key.session_id,
                        "turnId": ui_turn_id,
                        "payload": {
                            "requestId": ui_request_id,
                            "inputKind": input_kind,
                            "questions": questions,
                            "requestedSchema": requested_schema,
                            "expiresIn": max(record.expires_at - self._clock(), 0.0),
                        },
                    },
                )
        except BaseException:
            self._release_record(record)
            if not record.future.done():
                record.future.cancel()
            elif not record.future.cancelled():
                record.future.exception()
            raise
        return record

    def _release_record(self, record: PendingInput) -> None:
        if self._pending.get(record.ui_request_id) is record:
            self._pending.pop(record.ui_request_id)
        rpc_key = self._rpc_key(record.runtime_generation, record.rpc_id)
        if self._by_rpc.get(rpc_key) == record.ui_request_id:
            self._by_rpc.pop(rpc_key)

    def _prune_answered(self) -> None:
        now = self._clock()
        while self._answered:
            oldest = next(iter(self._answered.values()))
            if len(self._answered) <= self._answer_cache_max_entries and oldest.expires_at > now:
                break
            self._answered.popitem(last=False)

    async def _await_answer(self, record: PendingInput) -> dict[str, Any]:
        assert record.future is not None
        remaining = max(record.expires_at - self._clock(), 0.0)
        try:
            return await asyncio.wait_for(record.future, timeout=remaining or 0.001)
        except asyncio.TimeoutError as exc:
            self._release_record(record)
            if self._on_expired is not None:
                # 过期**不能只回一个 RPC error**：调用方需要先中断回合、
                # 等它到终态，否则 Runtime 可能把错误当成空答案继续跑。
                await self._on_expired(record)
            raise UserInputError("clarification_expired") from exc
        finally:
            self._release_record(record)
            if record.future.done() and not record.future.cancelled():
                record.future.exception()

    # ── 浏览器 → 我们 ───────────────────────────────────────────────
    async def answer(
        self, key: SessionKey, ui_request_id: str, response: dict[str, Any]
    ) -> dict[str, Any]:
        self._prune_answered()
        receipt = self._answered.get(str(ui_request_id))
        if receipt is not None:
            if receipt.key != key:
                raise PermissionError("clarification_scope_mismatch")
            return {"status": "accepted" if _digest(response) == receipt.answer_digest else "conflict"}
        record = self._pending.get(str(ui_request_id))
        if record is None:
            return {"status": "unknown_request"}
        if record.key != key:
            # 跨会话作答：这是越权，不是"输错了"。
            raise PermissionError("clarification_scope_mismatch")
        if record.expires_at <= self._clock():
            return {"status": "unknown_request"}
        if record.future is None or record.future.done():
            self._release_record(record)
            return {"status": "already_answered"}
        payload = self._validate(record, response)
        record.answered = True
        record.answer_digest = _digest(response)
        record.future.set_result(payload)
        self._release_record(record)
        self._answered[record.ui_request_id] = _AnswerReceipt(
            key=key, runtime_generation=record.runtime_generation,
            answer_digest=record.answer_digest, expires_at=self._clock() + self._answer_cache_ttl,
        )
        self._prune_answered()
        return {"status": "accepted"}

    def _validate(self, record: PendingInput, response: dict[str, Any]) -> dict[str, Any]:
        kind = str(response.get("inputKind") or record.input_kind)
        if kind != record.input_kind:
            # inputKind 是判别式，不能靠"字段在不在"来猜是哪一种卡。
            raise UserInputError("clarification_input_kind_mismatch")
        if record.input_kind == INPUT_KIND_FORM:
            action = str(response.get("action") or "")
            if action not in {"accept", "decline", "cancel"}:
                raise UserInputError("clarification_action_invalid")
            content = response.get("content")
            if action == "accept":
                if not isinstance(content, dict):
                    raise UserInputError("clarification_content_required")
                _validate_against_schema(content, record.requested_schema or {})
            elif content is not None:
                raise UserInputError("clarification_content_must_be_null")
            return {"action": action, "content": content}
        answers = response.get("answers")
        if not isinstance(answers, dict):
            raise UserInputError("clarification_answer_shape")
        if set(str(name) for name in answers) != set(record.question_ids):
            raise UserInputError("clarification_answer_shape")
        normalized: dict[str, Any] = {}
        for question_id, value in answers.items():
            answers_list = (value or {}).get("answers")
            if not isinstance(answers_list, list) or len(answers_list) != 1:
                # 多选需要新协议版本，不在这一版里假装支持。
                raise UserInputError("clarification_answer_shape")
            text = str(answers_list[0])
            if len(text) > MAX_FREE_TEXT:
                raise UserInputError("clarification_answer_too_long")
            allowed = self._allowed_labels(record, str(question_id))
            if allowed is not None and text not in allowed:
                # 自由输入是允许的，但只有在题目声明了 isOther 时——
                # 否则浏览器可以凭空造一个选项出来。
                raise UserInputError("clarification_option_not_offered")
            normalized[str(question_id)] = {"answers": [text]}
        return {"answers": normalized}

    @staticmethod
    def _allowed_labels(record: PendingInput, question_id: str) -> set[str] | None:
        for question in record.questions:
            if str(question.get("id")) != question_id:
                continue
            if question.get("isOther"):
                return None
            return {
                str(option.get("label"))
                for option in (question.get("options") or [])
                if option.get("label")
            }
        return None

    # ── 生命周期 ────────────────────────────────────────────────────
    def snapshot(self, key: SessionKey) -> list[dict[str, Any]]:
        """仍然可答的卡片。断线重连时用它把卡恢复出来。"""
        self._prune_answered()
        now = self._clock()
        return [
            {
                "requestId": record.ui_request_id,
                "turnId": record.ui_turn_id,
                "inputKind": record.input_kind,
                "questions": record.questions,
                "requestedSchema": record.requested_schema,
                "expiresAt": record.expires_at - now,
            }
            for record in self._pending.values()
            if record.key == key and not record.answered and record.expires_at > now
            and record.future is not None and not record.future.done()
        ]

    def resolve_native(self, runtime_generation: str, rpc_id: int | str, reason: str) -> None:
        """服务端说这个请求已经解决了（`serverRequest/resolved`）。

        注意该通知**只有 threadId/requestId，没有原因**——所以原因由本地状态决定，
        拿不到就记 `resolved`，不猜。
        """
        ui_request_id = self._by_rpc.get(self._rpc_key(runtime_generation, rpc_id))
        if ui_request_id is None:
            return
        record = self._pending.get(ui_request_id)
        if record is None or record.runtime_generation != runtime_generation:
            return
        self._release_record(record)
        if record.future is not None and not record.future.done():
            record.future.set_exception(UserInputError("clarification_resolved", reason))

    def expire_runtime(self, runtime_generation: str) -> None:
        """运行时换代（进程退出）：未答的原生请求全部作废。

        不能"等它回来再答"——JSON-RPC 请求不跨进程复活，那个 id 已经不存在了。
        """
        for ui_request_id, record in list(self._pending.items()):
            if record.runtime_generation != runtime_generation:
                continue
            self._release_record(record)
            if record.future is not None and not record.future.done():
                record.future.set_exception(UserInputError("clarification_runtime_gone"))
        for ui_request_id, receipt in list(self._answered.items()):
            if receipt.runtime_generation == runtime_generation:
                self._answered.pop(ui_request_id)

    def start_runtime(self, runtime_generation: str) -> None:
        if self.runtime_generation != runtime_generation:
            self.expire_runtime(self.runtime_generation)
            self.runtime_generation = str(runtime_generation)

    def handle_notification(self, runtime_generation: str, notification: dict[str, Any]) -> None:
        if notification.get("method") != "serverRequest/resolved":
            return
        params = notification.get("params")
        if not isinstance(params, dict) or type(params.get("requestId")) not in (int, str):
            return
        rpc_id = params["requestId"]
        request_id = self._by_rpc.get(self._rpc_key(runtime_generation, rpc_id))
        record = self._pending.get(request_id) if request_id is not None else None
        if record is None or record.native_thread_id != str(params.get("threadId") or ""):
            return
        self.resolve_native(runtime_generation, rpc_id, "resolved")

    def _business_turn_id(self, key: SessionKey, native_turn_id: str) -> str:
        """codex **原生**回合号 → **业务**回合号 ✓✓（F10 的真根就在这一步 ✗✓）。

        原生请求（`item/tool/requestUserInput` / elicitation ✓）的 `params.turnId`
        是 `turn_22` 这种原生号 ✓，而事件流按业务号索引 ✓（`turn.started` 与进度
        都用它盖章 ✓）。修前这里直接把它当业务号用 ✗，配上 `ConnectionChannel.emit`
        的"事件自带 turnId 优先" ✓（`session_runtime.py:127` ✓，那个语义是必要的 ✗）
        → 原生号直通进流 ✗：刷新补发 `_replay_active_turn` 只认业务号 ✓ →
        **卡被滤掉、回不来** ✗（F10 实测 ✓），副产物是卡被画进另一个
        `[data-turn-id]` 块（原生号 ✓）。

        解析不出（没注入解析器 / 映射还没绑上 ✓）就**原样返回**：与修前一致 ✓，
        不在这里猜"唯一活动回合就是它" ✗——猜错的归属比不翻更难查 ✓。
        """
        if self._turn_resolver is None or not native_turn_id:
            return native_turn_id
        try:
            resolved = self._turn_resolver(key, native_turn_id)
        except Exception:  # noqa: BLE001 - 解析失败不该让这轮提问整个消失
            logger.warning(
                "codex turn id resolution failed (%s); keeping it as-is", native_turn_id,
                exc_info=True,
            )
            return native_turn_id
        return str(resolved) if resolved else native_turn_id

    def _scope_from_params(self, params: dict[str, Any]) -> SessionKey:
        thread_id = str(params.get("threadId") or "")
        if self._scope_resolver is not None:
            resolved = self._scope_resolver(thread_id) if thread_id else None
            if resolved is not None:
                return resolved
            raise PermissionError("clarification_scope_unavailable")
        meta = params.get("_meta") or {}
        return SessionKey(
            tenant_id=str(meta.get("tenantId") or params.get("tenantId") or ""),
            session_id=str(meta.get("sessionId") or params.get("sessionId") or ""),
        )

    @staticmethod
    def _rpc_key(runtime_generation: str, rpc_id: int | str) -> tuple[str, type, int | str]:
        return runtime_generation, type(rpc_id), rpc_id


def _digest(payload: dict[str, Any]) -> str:
    import hashlib
    import json

    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def _validate_against_schema(content: dict[str, Any], schema: dict[str, Any]) -> None:
    """只接受短字符串/布尔/枚举，且必填项齐全。

    刻意**不**做通用 JSON Schema 实现：能进的类型越少，能出的错越少。
    """
    properties = schema.get("properties") or {}
    for name in schema.get("required") or []:
        if name not in content:
            raise UserInputError("clarification_required_field_missing", str(name))
    for name, value in content.items():
        spec = properties.get(name)
        if not isinstance(spec, dict):
            # 未知字段一律拒绝：白名单之外的字段没有解释得清的语义。
            raise UserInputError("clarification_unknown_field", str(name))
        expected = spec.get("type")
        if expected == "boolean":
            if not isinstance(value, bool):
                raise UserInputError("clarification_field_type", str(name))
        elif expected == "string":
            if not isinstance(value, str):
                raise UserInputError("clarification_field_type", str(name))
            if len(value) > MAX_FREE_TEXT:
                raise UserInputError("clarification_field_too_long", str(name))
            options = spec.get("enum")
            if isinstance(options, list) and value not in options:
                raise UserInputError("clarification_field_not_in_enum", str(name))
        else:
            raise UserInputError("clarification_field_type_unsupported", str(name))
