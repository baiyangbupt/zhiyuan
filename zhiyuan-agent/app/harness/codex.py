from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import Awaitable, Callable
from typing import Any, AsyncIterator, cast

from app.harness.client import AppServerClient
from app.harness.turn_result import CodexTurnResult, TurnStatus

logger = logging.getLogger(__name__)


class CodexAppServerHarness:
    def __init__(
        self,
        command: list[str],
        *,
        request_timeout: float = 30.0,
        skill_root: str | None = None,
        approval_policy: str | None = None,
        sandbox_policy: str | dict[str, Any] | None = None,
        capabilities: dict[str, Any] | None = None,
    ) -> None:
        self.client = AppServerClient(command, request_timeout=request_timeout)
        self.skill_root = skill_root
        self.approval_policy = approval_policy
        self.sandbox_policy = sandbox_policy
        self.capabilities = capabilities
        # 保留握手响应：探针要据它判断服务端是否接受了声明，而不是假定接受。
        self.initialize_result: dict[str, Any] | None = None

    async def start(self) -> None:
        await self.client.start()
        self.initialize_result = await self.client.initialize(
            client_name="zhiyuan_gateway",
            client_version="0.1.0",
            capabilities=self.capabilities,
        )

    def set_server_request_handler(self, handler: Any) -> None:
        self.client.server_request_handler = handler

    async def restart(self) -> None:
        """重拉原生 runtime 并重新握手。

        握手必须重做：能力声明（原生提问那套）是每次连接谈的，
        重拉之后不重新声明，模型就再也提不了问——而且链路上不会报错。
        """
        await self.client.restart()
        self.initialize_result = await self.client.initialize(
            client_name="zhiyuan_gateway",
            client_version="0.1.0",
            capabilities=self.capabilities,
        )

    async def create_thread(
        self,
        *,
        base_instructions: str = "",
        developer_instructions: str = "",
        skill_root: str | None = None,
        approval_policy: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "baseInstructions": base_instructions,
            "developerInstructions": developer_instructions,
        }
        resolved_skill_root = skill_root or self.skill_root
        if resolved_skill_root:
            params["cwd"] = resolved_skill_root
        effective_approval_policy = approval_policy if approval_policy is not None else self.approval_policy
        if effective_approval_policy is not None:
            params["approvalPolicy"] = effective_approval_policy
        sandbox_mode = _sandbox_mode(self.sandbox_policy)
        if sandbox_mode is not None:
            params["sandbox"] = sandbox_mode
        return await self.client.request("thread/start", params)

    async def resume_thread(self, thread_id: str) -> dict[str, Any]:
        return await self.client.request("thread/resume", {"threadId": thread_id})

    async def inject_items(self, thread_id: str, items: list[dict[str, Any]]) -> dict[str, Any]:
        return await self.client.request(
            "thread/inject_items", {"threadId": thread_id, "items": items}
        )

    async def start_turn(
        self,
        thread_id: str,
        input_items: list[dict[str, Any]],
        output_schema: dict[str, Any] | None = None,
        *,
        approval_policy: str | None = None,
        sandbox_policy: str | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"threadId": thread_id, "input": input_items}
        if output_schema is not None:
            params["outputSchema"] = output_schema
        effective_approval_policy = approval_policy if approval_policy is not None else self.approval_policy
        effective_sandbox_policy = sandbox_policy if sandbox_policy is not None else self.sandbox_policy
        if effective_approval_policy is not None:
            params["approvalPolicy"] = effective_approval_policy
        if effective_sandbox_policy is not None:
            params["sandboxPolicy"] = _sandbox_policy(effective_sandbox_policy)
        return await self.client.request("turn/start", params)

    async def start_turn_and_collect(
        self,
        thread_id: str,
        input_items: list[dict[str, Any]],
        output_schema: dict[str, Any] | None = None,
        *,
        timeout: float | None = None,
        approval_policy: str | None = None,
        sandbox_policy: str | dict[str, Any] | None = None,
        on_notification: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
        on_turn_started: Callable[[str], Awaitable[None]] | None = None,
    ) -> CodexTurnResult:
        """Start a turn and wait for its terminal App Server notification.

        `on_notification` 是**实时进度**的唯一注入点：它在既有的 collect 循环里
        被调用，因此不需要第二个通知消费者去和它抢同一个队列
        （stdio 只有一个 reader，两个消费者会互相吃掉对方的事件）。
        回调必须快速返回——它跑在模型 reader 的关键路径上，慢浏览器不能拖住它。
        """
        overflow_before = self.client.protocol_overflow_count
        effective_timeout = timeout if timeout is not None else self.client.request_timeout
        started = await self.start_turn(
            thread_id,
            input_items,
            output_schema,
            approval_policy=approval_policy,
            sandbox_policy=sandbox_policy,
        )
        turn_payload = started.get("turn") if isinstance(started, dict) else None
        turn_payload = turn_payload if isinstance(turn_payload, dict) else {}
        turn_id = str(turn_payload.get("id") or started.get("turnId") or "") or None
        initial_status = str(turn_payload.get("status") or "").lower()
        events: list[dict[str, Any]] = []
        final_output = None
        final_output_extraction = _missing_extraction()

        if on_turn_started is not None and turn_id:
            # 绑定原生回合号：`turn/steer` 的 expectedTurnId 要的是它，
            # 而浏览器只知道自己那个回合号。这层映射不能放浏览器里。
            await on_turn_started(turn_id)
        if initial_status in {"completed", "failed", "interrupted"}:
            started_output, started_extraction = _extract_output_ex(started)
            return CodexTurnResult(
                status=cast(TurnStatus, initial_status),
                turn_id=turn_id,
                output=started_output,
                output_extraction=started_extraction,
                payload=started,
            )
        if not turn_id:
            return CodexTurnResult(
                status="failed",
                error_code="turn_id_missing",
            )

        loop = asyncio.get_running_loop()
        deadline = loop.time() + effective_timeout
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                try:
                    await self.interrupt_turn(thread_id, turn_id)
                except Exception:
                    pass
                return CodexTurnResult(
                    status="timed_out",
                    turn_id=turn_id,
                    events=events,
                    error_code=self._timeout_error_code(overflow_before),
                    payload={"turnId": turn_id},
                )
            try:
                notification = await self.client.wait_for_notification(
                    lambda item: _matches_turn(item, thread_id, turn_id),
                    timeout=remaining,
                )
            except asyncio.TimeoutError:
                try:
                    await self.interrupt_turn(thread_id, turn_id)
                except Exception:
                    pass
                return CodexTurnResult(
                    status="timed_out",
                    turn_id=turn_id,
                    events=events,
                    error_code=self._timeout_error_code(overflow_before),
                    payload={"turnId": turn_id},
                )

            # 先把进度交出去，再解析终态相关字段——顺序反了的话，
            # "还在跑"的那段时间里前端什么也看不到。
            if on_notification is not None:
                await on_notification(notification)
            event = _notification_to_event(notification)
            events.append(event)
            item = event.get("item") or {}
            if event.get("type") == "item/completed" and item.get("type") == "agentMessage":
                final_output, final_output_extraction = _extract_output_ex(event)
            terminal_status = _terminal_status(event)
            if terminal_status is None:
                continue
            event_output, event_extraction = _extract_output_ex(event)
            if terminal_status == "completed":
                output = event_output or final_output
                extraction = event_extraction if event_output else final_output_extraction
            else:
                output = None
                extraction = _missing_extraction()
            return CodexTurnResult(
                status=terminal_status,
                turn_id=turn_id,
                output=output,
                output_extraction=extraction,
                events=events,
                error_code=_extract_error(event),
                payload=event,
            )

    def _timeout_error_code(self, overflow_before: int) -> str:
        """超时是两种不同的失败，必须分开报。

        一种是"模型就是慢"，另一种是"这个回合期间通知被丢弃过，终态可能根本没到"。
        都报 turn_timeout 的话，后者会被当成前者一直重试下去。
        """
        if self.client.protocol_overflow_count > overflow_before:
            return "protocol_overflow"
        return "turn_timeout"

    async def steer_turn(
        self, thread_id: str, turn_id: str, input_items: list[dict[str, Any]]
    ) -> dict[str, Any]:
        return await self.client.request(
            "turn/steer",
            {"threadId": thread_id, "expectedTurnId": turn_id, "input": input_items},
        )

    async def interrupt_turn(self, thread_id: str, turn_id: str) -> dict[str, Any]:
        return await self.client.request(
            "turn/interrupt", {"threadId": thread_id, "turnId": turn_id}
        )

    async def next_event(self) -> dict[str, Any]:
        return await self.client.next_notification()

    async def events(self) -> AsyncIterator[dict[str, Any]]:
        while True:
            yield await self.next_event()

    async def close(self) -> None:
        await self.client.close()


def _matches_turn(notification: dict[str, Any], thread_id: str, turn_id: str) -> bool:
    params = notification.get("params") or {}
    turn = params.get("turn") or {}
    notification_thread_id = str(params.get("threadId") or params.get("thread_id") or "")
    notification_turn_id = str(
        params.get("turnId") or params.get("turn_id") or turn.get("id") or ""
    )
    return notification_thread_id == thread_id and (
        not notification_turn_id or notification_turn_id == turn_id
    )


def _sandbox_policy(value: str | dict[str, Any]) -> dict[str, Any]:
    """Convert the legacy config spelling into the v2 turn policy object."""
    if isinstance(value, dict):
        return dict(value)
    mapping = {
        "read-only": {"type": "readOnly", "networkAccess": False},
        "workspace-write": {"type": "workspaceWrite", "networkAccess": False},
        "danger-full-access": {"type": "dangerFullAccess"},
    }
    try:
        return mapping[value]
    except KeyError as exc:
        raise ValueError(f"unsupported sandbox policy: {value}") from exc


def _sandbox_mode(value: str | dict[str, Any] | None) -> str | None:
    """Return the thread/start SandboxMode counterpart for a turn policy."""
    if value is None:
        return None
    if isinstance(value, str):
        if value not in {"read-only", "workspace-write", "danger-full-access"}:
            raise ValueError(f"unsupported sandbox policy: {value}")
        return value
    type_name = str(value.get("type") or "")
    mapping = {
        "readOnly": "read-only",
        "workspaceWrite": "workspace-write",
        "dangerFullAccess": "danger-full-access",
    }
    try:
        return mapping[type_name]
    except KeyError as exc:
        raise ValueError(f"unsupported sandbox policy type: {type_name}") from exc


# 原生通知的**斜杠**名字 → V1 事件合同的**点号**名字 ✓✓。
#
# 为什么必须映射 ✓：`_notification_to_event` 原先把类型设成 method 本身 ✗（`turn/completed` ✓），
# 而 `UiEvent` 的类型白名单是**点号**的（`turn.completed` ✓，`app/gateway/ui_events.py:18-30` ✓）→
# 事件**过不了事件存储的入流校验** ✗ → `ConnectionChannel` 退回老信封的投影 ✓✓
#（实测：放行后答案以 `reply` 回到页面 ✗、V1 那条 `assistant.completed` 从未出现 ✓）。
_TERMINAL_TYPE_MAP = {
    "turn/completed": "turn.completed",
    "turn/failed": "turn.completed",
    "turn/interrupted": "turn.completed",
    "item/agentMessage/completed": "assistant.completed",
    "item/agentMessage/delta": "assistant.delta",
    "item/mcpToolCall": "tool.progress",
}


def _notification_to_event(notification: dict[str, Any]) -> dict[str, Any]:
    params = notification.get("params") or {}
    event = dict(params) if isinstance(params, dict) else {}
    raw_type = str(notification.get("method") or event.get("type") or "").strip()
    event["type"] = _TERMINAL_TYPE_MAP.get(raw_type, raw_type)
    # 终态要带**白名单里的 payload** ✓✓（前端只认这些键 ✓：`conversationEvents.mjs:35-36` ✓）：
    # `assistant.completed` → `message/responseType/executionStatus/limitations` ✓；
    # `turn.completed` → `executionStatus/toolStatus/runtimeStatus` ✓。
    if event["type"] == "assistant.completed" and "payload" not in event:
        item = event.get("item") if isinstance(event.get("item"), dict) else {}
        message = item.get("text") or event.get("message") or event.get("delta") or ""
        event["payload"] = {
            "message": str(message),
            "responseType": "text",
            "executionStatus": "completed",
            "limitations": [],
        }
    if event["type"] == "turn.completed" and "payload" not in event:
        status = str((event.get("turn") or {}).get("status") or "completed").lower()
        event["payload"] = {
            "executionStatus": status,
            "toolStatus": "completed" if status == "completed" else status,
            "runtimeStatus": "native",
        }
    return event


def _terminal_status(event: dict[str, Any]) -> str | None:
    event_type = str(event.get("type") or "").lower()
    if event_type in {"turn/completed", "turn.completed"}:
        status = str((event.get("turn") or {}).get("status") or "completed").lower()
        return status if status in {"completed", "failed", "interrupted"} else None
    if event_type in {"turn/failed", "turn.failed"}:
        return "failed"
    if event_type in {"turn/interrupted", "turn.interrupted"}:
        return "interrupted"
    return None


def _extract_output(payload: dict[str, Any]) -> dict[str, Any] | None:
    return _extract_output_ex(payload)[0]


def _extract_output_ex(payload: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Like `_extract_output`, but also returns how the output was obtained.

    The second element is `{"source": "direct"|"fenced"|"embedded"|"missing",
    "candidateCount": int | None}`. Recursion always propagates the record of the
    call that actually produced a hit (via return values, never a shared mutable
    that a later failed attempt could clobber).
    """
    for key in ("output", "structuredOutput", "structured_output"):
        value = payload.get(key)
        if isinstance(value, dict):
            return value, {"source": "direct", "candidateCount": None}
        if isinstance(value, str):
            parsed, extraction = _parse_json_object(value)
            if parsed is not None:
                return parsed, extraction
    item = payload.get("item")
    if isinstance(item, dict):
        extracted, extraction = _extract_output_ex(item)
        if extracted is not None:
            return extracted, extraction
        for key in ("text", "content"):
            value = item.get(key)
            if isinstance(value, str):
                parsed, extraction = _parse_json_object(value)
                if parsed is not None:
                    return parsed, extraction
            if isinstance(value, list):
                for content in value:
                    if not isinstance(content, dict):
                        continue
                    text = content.get("text")
                    if isinstance(text, str):
                        parsed, extraction = _parse_json_object(text)
                        if parsed is not None:
                            return parsed, extraction
                    structured = content.get("structuredContent") or content.get("structured_content")
                    if isinstance(structured, dict):
                        return structured, {"source": "direct", "candidateCount": None}
    turn = payload.get("turn")
    if isinstance(turn, dict):
        return _extract_output_ex(turn)
    return None, _missing_extraction()


def _missing_extraction() -> dict[str, Any]:
    return {"source": "missing", "candidateCount": None}


_FENCE_PATTERN = re.compile(r"```[ \t]*[\w.+-]*[ \t]*\r?\n?(.*?)```", re.DOTALL)


def _find_outermost_braces(value: str) -> str | None:
    """Return the span from the first '{' to its balanced '}', or None.

    Simple depth counting, no string-literal awareness. If the braces never
    balance, or content isn't valid JSON, callers must treat that as a miss
    rather than falling back to any kind of regex text scraping.
    """
    start = value.find("{")
    if start == -1:
        return None
    depth = 0
    for index in range(start, len(value)):
        char = value[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return value[start : index + 1]
    return None


def _lenient_json(value: str) -> Any:
    """解析模型给的 JSON，**容忍字符串里的裸控制字符**。

    `json.loads` 默认严格：字符串里出现真的换行/制表符就整段拒绝。而模型经常
    直接写多段中文回答（`message` 里带真换行），于是一层一层全失败 → `missing`
    → `output_missing` → **整轮失败**，而内容本身完全合规。

    实测：2026-09-21 一轮查北大招生章程的回答（2435 字、含"第一章"分段），
    在 `line 1 column 76` 报 `Invalid control character`，抽取返回 None。

    放宽的只有这一条（`strict=False` 只影响字符串内的控制字符；尾逗号、
    单引号等一律照旧拒绝）。**契约校验不在这里**——解析出来的 dict 仍要过
    pydantic schema，所以这不是"放松校验"，是"先把话听清再判"。
    """
    return json.loads(value, strict=False)


def _try_json_object(value: str) -> dict[str, Any] | None:
    """解析出 dict 才算命中；其它一律 None（与三层抽取的判据一致）。"""
    try:
        parsed = _lenient_json(value)
    except (TypeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _strip_leading_and_trailing_fence(text: str) -> str:
    """整段被 markdown 围栏包住时去掉围栏（含未收口的围栏）。

    只有"开头就是围栏"才动：围栏在正文中间的情形由 `_FENCE_PATTERN` 那一层管。
    内容一个字符不改，只去掉 ``` 那一行与语言标签。
    """
    stripped = text.lstrip()
    if not stripped.startswith("```"):
        return text
    body = stripped[3:]
    newline = body.find("\n")
    if newline == -1:
        return text
    body = body[newline + 1 :].rstrip()
    if body.endswith("```"):
        body = body[:-3]
    return body.strip()


def _strip_trailing_commas(text: str) -> str:
    """去掉对象/数组收尾前的尾逗号（`,}` / `,]`）。

    严格 JSON 里尾逗号本来就不合法，去掉它不会改变任何**合法**写法；字符串里的
    逗号不动（那是内容）。只在字符串外判断，转义状态照常跟踪。
    """
    out: list[str] = []
    in_string = False
    escaped = False
    index = 0
    length = len(text)
    while index < length:
        char = text[index]
        if in_string:
            out.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            index += 1
            continue
        if char == '"':
            in_string = True
            out.append(char)
            index += 1
            continue
        if char == ",":
            probe = index + 1
            while probe < length and text[probe] in " \t\r\n":
                probe += 1
            if probe < length and text[probe] in "}]":
                index += 1  # 尾逗号：丢掉，别的一个字符不动
                continue
        out.append(char)
        index += 1
    return "".join(out)


def _previous_unescaped_quote(text: str, position: int) -> int | None:
    index = position - 1
    while index >= 0:
        if text[index] == '"':
            backslashes = 0
            probe = index - 1
            while probe >= 0 and text[probe] == "\\":
                backslashes += 1
                probe -= 1
            if backslashes % 2 == 0:
                return index
        index -= 1
    return None


def _next_unescaped_quote(text: str, position: int) -> int | None:
    index = position
    while index < len(text):
        if text[index] == '"':
            backslashes = 0
            probe = index - 1
            while probe >= 0 and text[probe] == "\\":
                backslashes += 1
                probe -= 1
            if backslashes % 2 == 0:
                return index
        index += 1
    return None


# 内部引号扫描上限：正常回答里不会有这么多，超了就是形状不对，直接放弃。
_SALVAGE_MAX_SCANNED_QUOTES = 64


def _repair_in_string_quotes(text: str) -> str | None:
    """把"能证明在字符串值内部"的英文引号成对换成「」，证明不了返回 None。

    2026-10-06 真事故：模型在 `message` 字符串里写
    `有的省是"第一段/第二段"，有的是"本科批/专科批"`，四个未转义 `"` 让
    `json.loads` 报 `Expecting ',' delimiter`，整轮死在 `output_missing`。

    证明链（任何一步不成立就放弃——宁失败不可改错内容）：
      1. 严格解析的失败点必须是 `Expecting ',' delimiter`。这正是"一个字符串被
         提前关闭、后面跟着的却是正文"的形状；别的报错（缺值、缺逗号在结构位）
         不在救回范围。
      2. 失败点的字符必须是**非 ASCII 正文**：ASCII 的 `"`/字母/数字都可能是
         合法的下一个 token（`{"a": "x" "b": "y"}` 的失败点就是 `"`），不能算证据。
      3. 失败点之前要有那个"提前关闭字符串"的引号。
      4. 从失败点往后把引号当候选收尾逐个试探：某个引号后面跟的是 JSON 分隔符
         （`,`/`}`/`]`）时，它才是字符串真正的收尾；被它跳过的都是内部引号。
      5. 内部引号必须成对（偶数），且每一对引号之间至少有一个非 ASCII 字符
         （包的确实是中文正文，而不是 `"message"` 这种结构片段）。
      6. 替换后再解析一次必须成功——最终以"整段能解析"为准，最多重试 1 次。
    """
    try:
        _lenient_json(text)
    except json.JSONDecodeError as exc:
        if exc.msg != "Expecting ',' delimiter":
            return None
        error_position = exc.pos
    except (TypeError, ValueError):
        return None
    else:
        return None

    if error_position >= len(text) or ord(text[error_position]) <= 127:
        return None

    closing = _previous_unescaped_quote(text, error_position)
    if closing is None:
        return None

    internal = [closing]
    cursor = error_position
    while len(internal) <= _SALVAGE_MAX_SCANNED_QUOTES:
        found = _next_unescaped_quote(text, cursor)
        if found is None:
            return None
        after = found + 1
        while after < len(text) and text[after] in " \t\r\n":
            after += 1
        if after < len(text) and text[after] in ",}]":
            break
        internal.append(found)
        cursor = found + 1
    else:
        return None
    if len(internal) < 2 or len(internal) % 2 != 0:
        return None

    for opening, partner in zip(internal[0::2], internal[1::2]):
        if not any(ord(char) > 127 for char in text[opening + 1 : partner]):
            return None

    repaired = list(text)
    for index, position in enumerate(internal):
        repaired[position] = "「" if index % 2 == 0 else "」"
    candidate = "".join(repaired)
    return candidate if _try_json_object(candidate) is not None else None


def _salvage_json(text: str) -> tuple[dict[str, Any] | None, list[str]]:
    """严格解析失败后的**窄口径**救回；返回 (解析结果, 用过的处理)。

    只做三种可证明的处理：
      ① 去 markdown 围栏（无损：只去掉 ``` 与语言标签）；
      ② 去尾随逗号（无损：尾逗号在严格 JSON 里本来就不合法）；
      ③ 字符串值内成对的英文引号 → 「」（**会改内容**，所以证明链在
         `_repair_in_string_quotes` 里，任何一步证明不了就整体放弃）。
    ③ 最多重解析 1 次；仍然不成功就返回 None，让上层走修复回合。
    """
    candidate = text
    actions: list[str] = []
    defenced = _strip_leading_and_trailing_fence(candidate)
    if defenced != candidate:
        candidate = defenced
        actions.append("fence")
    without_trailing = _strip_trailing_commas(candidate)
    if without_trailing != candidate:
        candidate = without_trailing
        actions.append("trailing_comma")
    if actions:
        parsed = _try_json_object(candidate)
        if parsed is not None:
            return parsed, actions
    repaired = _repair_in_string_quotes(candidate)
    if repaired is not None:
        parsed = _try_json_object(repaired)
        if parsed is not None:
            return parsed, [*actions, "in_string_quotes"]
    return None, []


_SALVAGE_EXCERPT_CHARS = 200


def _salvage_excerpt(text: str) -> str:
    return text[:_SALVAGE_EXCERPT_CHARS] + ("…" if len(text) > _SALVAGE_EXCERPT_CHARS else "")


def _salvage_candidates(stripped: str, span: str | None) -> list[tuple[str, str]]:
    """救回层要试的候选文本，顺序与严格层同款：direct → fenced(最后一个优先) → embedded。"""
    candidates: list[tuple[str, str]] = [("direct", stripped)]
    fenced_blocks = [
        match.group(1).strip()
        for match in _FENCE_PATTERN.finditer(stripped)
        if match.group(1).strip()
    ]
    candidates.extend(("fenced", block) for block in reversed(fenced_blocks))
    if span is not None:
        candidates.append(("embedded", span))
    return candidates


def _parse_json_object(value: str) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Layered extraction of a JSON object from model output.

    Order is fixed and each layer only counts as a hit on a full parse success:
      1. direct  - the entire (stripped) string is valid JSON.
      2. fenced  - scan all ``` fenced blocks (anywhere in the string, including
         a language tag like ```json), parse each; if more than one parses to a
         dict, the last one wins (model's final answer). This is a superset of
         the historical "whole value starts with ```" behavior, not a replacement.
      3. embedded - no fenced hit; take the outermost balanced {...} span in the
         prose and try to parse it. No field-level patching, no regex scraping:
         if that span isn't valid JSON, this is a miss.
      4. salvaged - only after 1-3 all miss: narrow, provable repairs (fence
         strip / trailing comma / in-string quotes to 「」, see `_salvage_json`).
         A hit is logged at WARNING with a truncated excerpt; a failure keeps the
         historical `missing` answer.
      5. missing - none of the above produced a dict.
    """
    stripped = value.strip()

    try:
        direct = _lenient_json(stripped)
    except (TypeError, ValueError):
        direct = None
    if isinstance(direct, dict):
        return direct, {"source": "direct", "candidateCount": None}

    fenced_candidates: list[dict[str, Any]] = []
    for match in _FENCE_PATTERN.finditer(stripped):
        block = match.group(1).strip()
        if not block:
            continue
        try:
            parsed_block = _lenient_json(block)
        except (TypeError, ValueError):
            continue
        if isinstance(parsed_block, dict):
            fenced_candidates.append(parsed_block)
    if fenced_candidates:
        return fenced_candidates[-1], {
            "source": "fenced",
            "candidateCount": len(fenced_candidates),
        }

    span = _find_outermost_braces(stripped)
    if span is not None:
        try:
            embedded = _lenient_json(span)
        except (TypeError, ValueError):
            embedded = None
        if isinstance(embedded, dict):
            return embedded, {"source": "embedded", "candidateCount": None}

    # 第四层：窄口径救回。只在严格三层**全部落空**之后跑，命中必留痕（WARNING +
    # 截断摘录）——救回是"把话听清"，不是"放松校验"，所以它改动过什么必须能查。
    for layer, candidate in _salvage_candidates(stripped, span):
        salvaged, actions = _salvage_json(candidate)
        if salvaged is None:
            continue
        logger.warning(
            "salvaged malformed model JSON (layer=%s actions=%s excerpt=%r)",
            layer,
            ",".join(actions),
            _salvage_excerpt(candidate),
        )
        return salvaged, {
            "source": "salvaged",
            "candidateCount": None,
            "salvageLayer": layer,
            "salvageActions": actions,
        }

    return None, _missing_extraction()


def _extract_error(payload: dict[str, Any]) -> str | None:
    value = payload.get("errorCode") or payload.get("error_code") or payload.get("error")
    if not value and isinstance(payload.get("turn"), dict):
        return _extract_error(payload["turn"])
    if isinstance(value, dict):
        value = value.get("code") or value.get("message")
    return str(value) if value else None
