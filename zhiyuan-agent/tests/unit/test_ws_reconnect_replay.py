"""断线连上时的补发（A5 七-2 的"resync 快照接线"）：范围、顺序、会话键、以及什么时候只重置基线。

两条路各服务一类断线：
- **补当前回合**（无游标）：刷新把页面状态清掉了，而消息历史里**没有**未结束的回合；
- **补尾巴**（有游标）：短暂断线但页面还活着，它要的是漏掉的那几条（**可能含终态**）。

这里钉住五件在真栈上不好看的：
1. **会话键来自票据**，URL 点名别的会话时**一条都不补**（跨会话泄漏）；
2. 补当前回合时**只补当前回合**——已结束的回合在消息历史里，一起补会出现两次；
3. 补得出来时**不发 `session.resync`**（reducer 的 resync 分支会把补出来的事件当重复丢掉）；
4. **先登记连接、再读存储**——反了会丢这中间的实时事件（丢=缺口，只允许 resync）；
5. 回合的事件走**会话当前连接**（走错连接 = 刷新后终态永远收不到）。
"""
import asyncio

import pytest

from app.gateway.session_runtime import ACCEPTED, ActiveTurn, SessionRuntime
from app.gateway.ui_events import SessionKey, UiEvent
from app.gateway.user_input import UserInputBroker
from app.server import _replay_on_connect, _session_emitter


def _event(sequence: int, turn_id: str) -> UiEvent:
    return UiEvent(
        type="tool.progress",
        sessionId="900047",
        turnId=turn_id,
        streamEpoch="epoch-a",
        sequence=sequence,
        payload={"itemId": f"i{sequence}", "tool": "domain", "status": "started", "label": "正在查询"},
    )


def _clarification_event(sequence: int, turn_id: str) -> UiEvent:
    return UiEvent(
        type="clarification.requested",
        sessionId="900047",
        turnId=turn_id,
        streamEpoch="epoch-a",
        sequence=sequence,
        payload={"requestId": "q1", "inputKind": "choice", "questions": []},
    )


class _ReplayStore:
    def __init__(self, *, epoch: str | None, events: list[UiEvent] | None, watermark: int = 0):
        self._epoch = epoch
        self._events = events
        self._watermark = watermark
        self.calls: list[str] = []
        self.replay_args: tuple[str, int] | None = None

    async def current_epoch(self, key: SessionKey) -> str | None:
        self.calls.append("current_epoch")
        return self._epoch

    async def replay(self, key: SessionKey, epoch: str, after: int):
        self.calls.append("replay")
        self.replay_args = (epoch, after)
        return self._events

    async def watermark(self, key: SessionKey) -> int:
        return self._watermark


class _Runtime:
    def __init__(self, store: _ReplayStore, turn: ActiveTurn | None) -> None:
        self._store = store
        self._turn = turn
        self.attached: list[SessionKey] = []

    def active_turn(self, key: SessionKey) -> ActiveTurn | None:
        return self._turn

    def attach_connection(self, key: SessionKey, channel) -> None:
        self._store.calls.append("attach")
        self.attached.append(key)


class _Channel:
    def __init__(self) -> None:
        self.frames: list[dict] = []
        self.bound: list[tuple[str, object]] = []

    def bind_session(self, key: SessionKey) -> None:
        self.bound.append(("session", key))

    def bind_turn(self, turn_id: str) -> None:
        self.bound.append(("turn", turn_id))

    async def emit_frame(self, frame) -> None:
        self.frames.append(frame)

    emit_replay_frame = emit_frame


def _socket(store, *, granted: str = "900047", asked: str | None = "900047", **params) -> object:
    """假连接 ✓：票据给出的会话是 `granted` ✓，URL 里说的是 `asked` ✓。"""
    from types import SimpleNamespace

    query = {"chatSessionId": asked} if asked is not None else {}
    query.update(params)
    return SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(event_store=store)),
        state=SimpleNamespace(identity=SimpleNamespace(tenant_id="1", session_id=granted)),
        query_params=query,
    )


def _key() -> SessionKey:
    return SessionKey(tenant_id="1", session_id="900047")


def _running_turn() -> ActiveTurn:
    return ActiveTurn(key=_key(), ui_turn_id="turn-live")


@pytest.mark.asyncio
async def test_replays_only_the_active_turn_without_a_resync_frame() -> None:
    store = _ReplayStore(
        epoch="epoch-a",
        events=[_event(1, "turn-old"), _event(2, "turn-live"), _event(3, "turn-live")],
    )
    channel = _Channel()

    await _replay_on_connect(_socket(store), _Runtime(store, _running_turn()), channel)

    # 老回合**不补**：它在消息历史里，补了就是同一个回合两条。
    assert [frame["sequence"] for frame in channel.frames] == [2, 3]
    assert {frame["turnId"] for frame in channel.frames} == {"turn-live"}
    # 补得出来时一条 resync 都不许有：它会把基线设到水位线，把这些事件判成重复。
    assert all(frame["type"] != "session.resync" for frame in channel.frames)


@pytest.mark.asyncio
async def test_a_clarification_stamped_with_the_codex_turn_id_is_replayed_too() -> None:
    """F10 真根 ✓：卡的事件可能被盖成**原生**回合号 ✓——补发不许把它滤掉 ✗✓。

    链路（已定稿 ✓）：桥登记卡时直接把 `params.turnId`（原生号 ✓，如 `turn_22` ✓）
    当业务号用 ✗ → `ConnectionChannel.emit` 的"事件自带 turnId 优先" ✓
    （`session_runtime.py:127` ✓——那条语义是必要的 ✗，不许回退 ✓）把它原样写进流 ✗ →
    刷新补发只认业务号 ✓ → 卡被滤掉、回不来 ✗（F10 自 10-06 红 ✓）。
    真修在**桥边界翻译** ✓（`user_input._business_turn_id` ✓，另一条用例钉它 ✓）；
    这条钉的是过滤这一层的**防御**：当前回合的原生号同样放行 ✓——
    放行的代价是可能多补一条 ✓，滤掉的代价是用户在飞的卡永远看不到 ✗。
    """
    store = _ReplayStore(
        epoch="epoch-a",
        events=[
            _event(1, "turn-old"),
            _clarification_event(2, "turn_22"),
            _event(3, "turn-live"),
        ],
    )
    channel = _Channel()
    turn = ActiveTurn(key=_key(), ui_turn_id="turn-live", codex_turn_id="turn_22")

    await _replay_on_connect(_socket(store), _Runtime(store, turn), channel)

    assert [frame["sequence"] for frame in channel.frames] == [2, 3]
    assert [frame["type"] for frame in channel.frames] == [
        "clarification.requested",
        "tool.progress",
    ]


@pytest.mark.asyncio
async def test_the_broker_stamps_clarifications_with_the_business_turn_id() -> None:
    """桥边界翻译 ✓（真修在哪，这条就钉在哪 ✓）：原生 `turn_22` 进，业务号出 ✓✓。

    复用运行时**已有的**原生↔业务映射 ✓（`bind_codex_turn` 的反向查表 ✓）——
    翻译不另起一套状态 ✗，否则两处映射迟早对不上 ✓。
    **事件与快照（重连恢复的另一条路 ✓）都必须带业务号** ✓：只翻事件不翻快照的话，
    刷新补出来的卡还是会挂到别的 `[data-turn-id]` 块上 ✗。
    """
    runtime = SessionRuntime()
    key = _key()

    async def work() -> None:
        await asyncio.sleep(3600)

    assert (
        await runtime.submit(key, client_request_id="", ui_turn_id="turn-live", work=work)
        == ACCEPTED
    )
    runtime.bind_codex_turn(key, "turn-live", "turn_22")

    published: list[dict] = []

    async def emitter(published_key: SessionKey, event: dict) -> None:
        published.append(event)

    broker = UserInputBroker(
        runtime_generation="gen-1",
        scope_resolver=lambda thread_id: key,
        turn_resolver=runtime.ui_turn_for_codex,
    )
    broker.set_emitter(emitter)

    task = asyncio.create_task(
        broker.handle_server_request(
            {
                "jsonrpc": "2.0",
                "id": 9001,
                "method": "item/tool/requestUserInput",
                "params": {
                    "threadId": "thr_1",
                    "turnId": "turn_22",  # 原生号 ✓（真实形状：`turn_22` 这种 ✓）
                    "questions": [
                        {"id": "major", "header": "专业", "question": "想读什么？", "options": []}
                    ],
                },
            }
        )
    )
    try:
        for _ in range(200):
            if published:
                break
            await asyncio.sleep(0.01)
        assert published, "卡片事件没有发出来"
        assert published[0]["type"] == "clarification.requested"
        # 事件上盖的是**业务**回合号 ✓——原生号直通的话它会等于 "turn_22" ✗。
        assert published[0]["turnId"] == "turn-live"
        assert broker.snapshot(key)[0]["turnId"] == "turn-live"
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await runtime.cancel_all()


@pytest.mark.asyncio
async def test_attachment_happens_before_the_store_is_read() -> None:
    """先登记、后读存储：反了就会丢这中间的实时事件（丢=缺口，只允许 resync）。"""
    store = _ReplayStore(epoch="epoch-a", events=[_event(1, "turn-live")])
    channel = _Channel()
    runtime = _Runtime(store, _running_turn())

    await _replay_on_connect(_socket(store), runtime, channel)

    assert store.calls.index("attach") < store.calls.index("replay")
    assert runtime.attached == [_key()]
    assert channel.bound == [("session", _key()), ("turn", "turn-live")]


@pytest.mark.asyncio
async def test_a_cursor_replays_the_tail_even_without_a_running_turn() -> None:
    """有游标时补**尾巴**（可能含已结束回合的终态）——这时没有在跑的回合同样要补 ✓。"""
    store = _ReplayStore(
        epoch="epoch-a",
        events=[_event(9, "turn-done"), _event(10, "turn-done")],
    )
    channel = _Channel()

    await _replay_on_connect(
        _socket(store, epoch="epoch-a", since="8"), _Runtime(store, None), channel
    )

    assert store.replay_args == ("epoch-a", 8)
    # 按游标补时不按回合过滤：客户端缺的就是 8 之后那一段，谁在里面都该补 ✓。
    assert [frame["sequence"] for frame in channel.frames] == [9, 10]


@pytest.mark.asyncio
async def test_an_unusable_cursor_asks_for_resync_with_the_current_epoch() -> None:
    """游标用不了（代际变了/窗口被裁）：发 resync，且代际必须是**当前**那个。

    给客户端手上那个旧代际，会让它继续按另一条时间线走——那正是它要 resync 的原因。
    """
    store = _ReplayStore(epoch="epoch-now", events=None, watermark=42)
    channel = _Channel()

    await _replay_on_connect(
        _socket(store, epoch="epoch-old", since="8"), _Runtime(store, None), channel
    )

    assert [frame["type"] for frame in channel.frames] == ["session.resync"]
    assert channel.frames[0]["streamEpoch"] == "epoch-now"
    assert channel.frames[0]["payload"]["baseline"]["lastSequence"] == 42


@pytest.mark.asyncio
async def test_a_session_the_ticket_does_not_grant_is_never_replayed() -> None:
    """URL 里点名另一条会话：**一条都不补** ✗✓——持 A 的票不能读 B 的事件。"""
    store = _ReplayStore(epoch="epoch-a", events=[_event(1, "turn-x")])
    channel = _Channel()

    await _replay_on_connect(
        _socket(store, granted="900047", asked="900002"), _Runtime(store, _running_turn()), channel
    )

    assert channel.frames == []
    assert channel.bound == []
    assert store.calls == []  # 连读都不读 ✓


@pytest.mark.asyncio
async def test_window_gone_resets_the_baseline_to_the_watermark() -> None:
    """`replay` 回 None = 补不出来：这时才发 resync，且基线要落在水位线上。

    落在 0 上会让客户端以为"下一条该是 1"，而流里早就到别的号了 → 先缺口、
    再永久 resync。
    """
    store = _ReplayStore(epoch="epoch-a", events=None, watermark=7)
    channel = _Channel()

    await _replay_on_connect(_socket(store), _Runtime(store, _running_turn()), channel)

    assert [frame["type"] for frame in channel.frames] == ["session.resync"]
    frame = channel.frames[0]
    assert frame["sequence"] == 0
    assert frame["streamEpoch"] == "epoch-a"
    assert frame["payload"]["baseline"]["lastSequence"] == 7


@pytest.mark.asyncio
async def test_idle_reconnect_refreshes_durable_cards_without_replaying_answers() -> None:
    store = _ReplayStore(epoch="epoch-a", events=[_event(1, "turn-done")], watermark=7)
    channel = _Channel()
    runtime = _Runtime(store, None)

    await _replay_on_connect(_socket(store), runtime, channel)

    assert [frame["type"] for frame in channel.frames] == ["session.resync"]
    assert channel.frames[0]["payload"]["baseline"] == {
        "reason": "idle_reconnect", "lastSequence": 7,
    }
    assert runtime.attached == [_key()]


@pytest.mark.asyncio
async def test_nothing_is_sent_when_the_session_never_wrote_an_event() -> None:
    """回合在跑、流里却一条都没有（存储刚重建/被清）：不补，也不假装 resync 过。

    登记照旧 ✓（理由同上一条 ✓）——"补不出东西"不是"这条连接不配收后续事件"。
    """
    store = _ReplayStore(epoch=None, events=[])
    channel = _Channel()
    runtime = _Runtime(store, _running_turn())

    await _replay_on_connect(_socket(store), runtime, channel)

    assert channel.frames == []
    assert runtime.attached == [_key()]


class _PublishingRuntime:
    """只做 publish：返回 True = 会话当前有连接（事件该走它）。"""

    def __init__(self, verdict: bool) -> None:
        self._verdict = verdict
        self.published: list[tuple[SessionKey, dict]] = []

    async def publish(self, key: SessionKey, event: dict) -> bool:
        self.published.append((key, event))
        return self._verdict


class _CountingChannel:
    def __init__(self) -> None:
        self.events: list[dict] = []

    async def emit(self, event: dict) -> None:
        self.events.append(event)


@pytest.mark.asyncio
async def test_turn_events_go_to_the_session_current_connection() -> None:
    """收尾要落到**会话当前**的连接 ✓✓，不是"这条消息当初那条" ✗。

    真缺陷就是后者：刷新之后旧连接已经关了，终态发上去**永远收不到** ✓
    （实测：刷新后放行闸门，终态 20s 到不了 ✓）。判据必须钉住"优先走会话域" ✓——
    钉成"发到本通道"的话，这条缺陷会在没人注意时回来 ✓。
    """
    runtime = _PublishingRuntime(verdict=True)
    channel = _CountingChannel()
    emit = _session_emitter(runtime, channel, _key())

    await emit({"type": "turn.completed"})

    assert runtime.published == [(_key(), {"type": "turn.completed"})]
    assert channel.events == []  # 走了会话域就**不该**再发一遍（重复帧会让 reducer 判缺口）


@pytest.mark.asyncio
async def test_turn_events_fall_back_to_this_connection_when_nobody_is_attached() -> None:
    """会话当前没有连接（用户全关了页面）→ 仍走本连接的通道 ✓：发不出去也比丢了好 ✓。"""
    runtime = _PublishingRuntime(verdict=False)
    channel = _CountingChannel()
    emit = _session_emitter(runtime, channel, _key())

    await emit({"type": "turn.completed"})

    assert channel.events == [{"type": "turn.completed"}]


@pytest.mark.asyncio
async def test_turn_events_work_without_a_runtime() -> None:
    """没有运行时（老路由/无存储）时，行为必须与从前一致 ✓。"""
    channel = _CountingChannel()
    emit = _session_emitter(None, channel, _key())

    await emit({"type": "tool.progress"})

    assert channel.events == [{"type": "tool.progress"}]


@pytest.mark.asyncio
async def test_large_replay_does_not_overflow_the_live_queue() -> None:
    from app.gateway.session_runtime import ConnectionChannel

    sent = []
    complete = asyncio.Event()

    async def send(frame):
        sent.append(frame)
        if len(sent) == 600:
            complete.set()
        return True

    store = _ReplayStore(
        epoch="epoch-a", events=[_event(i, "turn-live") for i in range(1, 601)],
    )
    runtime = SessionRuntime()
    channel = ConnectionChannel(send, maxsize=256)
    await _replay_on_connect(
        _socket(store, epoch="epoch-a", since="0"), runtime, channel,
    )
    channel.start()
    try:
        await asyncio.wait_for(complete.wait(), 1)
        assert not channel.overflowed
        assert [frame["sequence"] for frame in sent] == list(range(1, 601))
    finally:
        await channel.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("overlap", [False, True])
async def test_live_events_during_store_read_follow_replay_without_duplicates(overlap) -> None:
    from app.gateway.session_runtime import ConnectionChannel

    reading = asyncio.Event()
    release = asyncio.Event()
    sent = []
    complete = asyncio.Event()

    class Store(_ReplayStore):
        async def replay(self, key, epoch, after):
            reading.set()
            await release.wait()
            return [_event(i, "turn-live") for i in range(1, 4 if overlap else 3)]

        async def append(self, key, event):
            return _event(3, "turn-live")

    async def send(frame):
        sent.append(frame)
        if len(sent) == 3:
            complete.set()
        return True

    store = Store(epoch="epoch-a", events=[])
    runtime = SessionRuntime()
    channel = ConnectionChannel(send, store=store)
    reconnect = asyncio.create_task(_replay_on_connect(
        _socket(store, epoch="epoch-a", since="0"), runtime, channel,
    ))
    try:
        await asyncio.wait_for(reading.wait(), 1)
        assert await runtime.publish(_key(), {"type": "tool.progress"})
        release.set()
        await reconnect
        channel.start()
        await asyncio.wait_for(complete.wait(), 1)
        await asyncio.sleep(0)
        assert [frame["sequence"] for frame in sent] == [1, 2, 3]
    finally:
        release.set()
        await asyncio.gather(reconnect, return_exceptions=True)
        await channel.close()


@pytest.mark.asyncio
async def test_closed_channel_is_not_a_successful_publish_target() -> None:
    from app.gateway.session_runtime import ConnectionChannel

    async def send(frame):
        raise AssertionError("closed sender must not run")

    runtime = SessionRuntime()
    channel = ConnectionChannel(send)
    runtime.attach_connection(_key(), channel)
    await channel.close()
    assert not await runtime.publish(_key(), {"type": "turn.completed"})
    assert runtime.current_channel(_key()) is None
    await channel.emit_frame({"type": "turn.completed"})
    assert channel._queue.empty()


@pytest.mark.asyncio
async def test_active_replay_preserves_global_sequence_with_detached_action_in_the_middle():
    old_answer = UiEvent(
        type="assistant.completed", sessionId="900047", turnId="old-turn",
        streamEpoch="epoch-a", sequence=1, payload={"message": "already in history"},
    )
    action_result = UiEvent(
        type="conversationAction.result", sessionId="900047", turnId="action-turn",
        streamEpoch="epoch-a", sequence=3,
        payload={"proposalRef": "p1", "actionStatus": "applied"},
    )
    store = _ReplayStore(epoch="epoch-a", events=[
        old_answer, _event(2, "turn-live"), action_result, _event(4, "turn-live"),
    ])
    channel = _Channel()
    await _replay_on_connect(_socket(store), _Runtime(store, _running_turn()), channel)
    assert [frame["sequence"] for frame in channel.frames] == [2, 3, 4]
    assert channel.frames[1]["type"] == "conversationAction.result"
    assert all(frame["type"] != "assistant.completed" for frame in channel.frames)
