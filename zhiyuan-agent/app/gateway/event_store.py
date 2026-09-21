"""对话事件流：原子追加、按 cursor 重放、请求幂等。

三件事都在 Redis 侧保证，原因各不相同：

- **追加原子**：计数器自增与写流必须同时发生，否则并发下会出现
  "编号跳号但事件补上了"或反之，而客户端靠编号判重，两种都不是它猜得到的。
  所以走一段 Lua，而不是两个 Python await。
- **重放按 cursor**：断线重连要么补齐差量，要么明确说"补不了，重建"。
  含糊其辞（少给几条、静默从头来）会让前端把旧消息当新消息再渲染一遍。
- **请求幂等**：同一个 clientRequestId 重发必须拿到同一个结果，而不是又跑一次。

首期只支持**一个 Gateway worker**：这里的锁全在单进程内，多 worker 会让
"同一会话串行"这个前提失效。这里不是集群调度器，也不假装是。
"""
from __future__ import annotations

import asyncio
import json
import secrets
from typing import Any

from app.gateway.ui_events import EVENT_TYPES, PROTOCOL_VERSION, SessionKey, UiEvent


class EventStoreUnavailable(RuntimeError):
    """存储没配置或连不上。绝不退回进程内存。"""


class EventTooLarge(ValueError):
    """事件超过单条上限。调用方应改为存 Artifact 引用，而不是截断 JSON。"""


ACCEPTED = "accepted"
DUPLICATE = "duplicate"
CONFLICT = "conflict"

# Lua 的返回值里 sequence/streamEpoch 由脚本写入，会比原像多出这一截。
# 上限判定把它算进去，避免"过了 Python 检查、进了流才发现超限"。
_ENVELOPE_MARGIN = 64

# KEYS: 1=计数器 2=事件流 3=代际
# ARGV: 1=事件 JSON（无 sequence/streamEpoch） 2=TTL 秒 3=新的随机代际
_APPEND_LUA = """
local epoch = redis.call('GET', KEYS[3])
if not epoch or redis.call('EXISTS', KEYS[1]) == 0 or redis.call('EXISTS', KEYS[2]) == 0 then
    redis.call('DEL', KEYS[1], KEYS[2])
    epoch = ARGV[3]
    redis.call('SET', KEYS[3], epoch)
end
local seq = redis.call('INCR', KEYS[1])
local ev = cjson.decode(ARGV[1])
ev.sequence = seq
ev.streamEpoch = epoch
redis.call('XADD', KEYS[2], 'MAXLEN', '~', ARGV[4], '*', 'event', cjson.encode(ev))
redis.call('EXPIRE', KEYS[1], ARGV[2])
redis.call('EXPIRE', KEYS[2], ARGV[2])
redis.call('EXPIRE', KEYS[3], ARGV[2])
return cjson.encode(ev)
"""


def _tag(key: SessionKey) -> str:
    """hash tag：同一会话的所有键落在同一个槽，Lua 才能原子地操作它们。"""
    tenant = str(key.tenant_id)
    session = str(key.session_id)
    if "{" in tenant or "}" in tenant or "{" in session or "}" in session:
        # 花括号会改变槽的解析方式，进而让"同一会话同槽"这个前提失效。
        raise ValueError("session_key_must_not_contain_braces")
    return f"{{{tenant}:{session}}}"


def _key_names(key: SessionKey) -> tuple[str, str, str]:
    tag = _tag(key)
    return f"conv:{tag}:seq", f"conv:{tag}:stream", f"conv:{tag}:epoch"


def _request_key(key: SessionKey, request_id: str) -> str:
    return f"conv:{_tag(key)}:req:{request_id}"


def _result_key(key: SessionKey, request_id: str) -> str:
    return f"conv:{_tag(key)}:res:{request_id}"


class RedisEventStore:
    def __init__(
        self,
        redis_url: str,
        *,
        ttl_seconds: int = 24 * 60 * 60,
        max_events: int = 2000,
        max_event_bytes: int = 16 * 1024,
        max_connections: int = 256,
    ) -> None:
        if not redis_url:
            raise EventStoreUnavailable("event store redis url is not configured")
        # 延迟导入：没配置事件流的部署不该因为缺 redis 包而起不来。
        import redis.asyncio as redis_asyncio

        # 连接池必须显式定容：redis-py 默认 100，而一个 Gateway worker 同时服务
        # 的会话数可以超过它。池满时是**硬失败**（MaxConnectionsError），不是排队——
        # 结果是正在进行的回合丢事件。256 是给单 worker 的起步值，不是上限。
        self._redis = redis_asyncio.from_url(
            redis_url, decode_responses=True, max_connections=int(max_connections)
        )
        self._ttl = int(ttl_seconds)
        self._max_events = int(max_events)
        self._max_event_bytes = int(max_event_bytes)
        self._sha: str | None = None
        # 首次并发追加时，所有协程都会看到 _sha 为空并各发一次 SCRIPT LOAD。
        # 锁住它，把 N 次装载收敛成一次。
        self._script_lock = asyncio.Lock()

    async def close(self) -> None:
        await self._redis.aclose()

    async def ping(self) -> bool:
        return bool(await self._redis.ping())

    async def _script(self) -> str:
        if self._sha is not None:
            return self._sha
        async with self._script_lock:
            if self._sha is None:
                self._sha = await self._redis.script_load(_APPEND_LUA)
        return self._sha

    async def _eval_append(self, keys: list[str], args: list[str]) -> str:
        sha = await self._script()
        try:
            return await self._redis.evalsha(sha, 3, *keys, *args)
        except Exception as exc:  # NOSCRIPT：脚本被刷掉了，重装一次再试
            if "NOSCRIPT" not in str(exc):
                raise
            async with self._script_lock:
                self._sha = await self._redis.script_load(_APPEND_LUA)
            return await self._redis.evalsha(self._sha, 3, *keys, *args)

    async def append(self, key: SessionKey, event: dict[str, Any]) -> UiEvent:
        """追加一条事件并返回**已编号**的事件。

        入参里的 sequence/streamEpoch 一律忽略：编号属于存储，不属于调用方。
        """
        candidate = {k: v for k, v in event.items() if k not in {"sequence", "streamEpoch", "stream_epoch"}}
        candidate.setdefault("protocolVersion", PROTOCOL_VERSION)
        candidate.setdefault("sessionId", key.session_id)
        # 先用占位值过一遍校验：类型白名单与必填字段在**入流之前**就要判掉，
        # 否则脏事件已经进了流，前端才发现不认识它。
        try:
            UiEvent(
                protocolVersion=candidate.get("protocolVersion", PROTOCOL_VERSION),
                type=candidate.get("type"),
                sessionId=candidate.get("sessionId", ""),
                turnId=candidate.get("turnId", ""),
                streamEpoch="pending",
                sequence=1,
                payload=candidate.get("payload") or {},
            )
        except Exception as exc:
            raise ValueError(f"invalid_ui_event:{exc}") from exc
        if candidate.get("type") not in EVENT_TYPES:
            raise ValueError(f"unknown_ui_event_type:{candidate.get('type')}")

        pre_image = json.dumps(candidate, ensure_ascii=False, separators=(",", ":"))
        if len(pre_image.encode("utf-8")) + _ENVELOPE_MARGIN > self._max_event_bytes:
            # 不截断：截断后的 JSON 既不是原事件，也无法被前端解析。
            raise EventTooLarge(
                f"event exceeds {self._max_event_bytes} bytes; store an artifact reference instead"
            )

        counter, stream, epoch = _key_names(key)
        raw = await self._eval_append(
            [counter, stream, epoch],
            [pre_image, str(self._ttl), secrets.token_hex(16), str(self._max_events)],
        )
        return UiEvent.model_validate(json.loads(raw))

    async def replay(
        self, key: SessionKey, epoch: str, after: int
    ) -> list[UiEvent] | None:
        """补齐 `after` 之后的事件；返回 None 表示**必须 resync**。

        None 的每一种成因都要能被客户端理解成"重建基线"，而不是"再等等"：
        代际不同、计数器丢了、cursor 落后到窗口之外、cursor 跑到前面。
        """
        counter, stream, epoch_key = _key_names(key)
        stored_epoch = await self._redis.get(epoch_key)
        if stored_epoch is None:
            # 计数器/代际都没了。若客户端也还没有任何游标，从零开始是合法的。
            return [] if after == 0 else None
        if epoch != stored_epoch:
            return None

        entries = await self._redis.xrange(stream)
        if not entries:
            return [] if after == 0 else None

        events = [UiEvent.model_validate(json.loads(fields["event"])) for _, fields in entries]
        sequences = [event.sequence for event in events]
        if after > sequences[-1]:
            # cursor 超前：客户端记的是另一条时间线，继续等下去只会永远等不到。
            return None
        if after + 1 < sequences[0]:
            # 中间被裁掉了：补齐会留下一个洞，而洞是看不见的。
            return None
        return [event for event in events if event.sequence > after]

    async def watermark(self, key: SessionKey) -> int:
        counter, _, _ = _key_names(key)
        value = await self._redis.get(counter)
        return int(value) if value is not None else 0

    async def admit(self, key: SessionKey, request_id: str, request_digest: str) -> str:
        """请求占位。同 id 同摘要 = 重发，同 id 异摘要 = 冲突。"""
        request_key = _request_key(key, request_id)
        stored = await self._redis.set(
            request_key, request_digest, nx=True, ex=self._ttl
        )
        if stored:
            return ACCEPTED
        current = await self._redis.get(request_key)
        return DUPLICATE if current == request_digest else CONFLICT

    async def finish_request(
        self, key: SessionKey, request_id: str, result_ref: str
    ) -> None:
        await self._redis.set(_result_key(key, request_id), result_ref, ex=self._ttl)

    async def request_result(self, key: SessionKey, request_id: str) -> str | None:
        return await self._redis.get(_result_key(key, request_id))
