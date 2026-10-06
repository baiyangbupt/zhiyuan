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
import pytest

from app.gateway.session_runtime import ActiveTurn
from app.gateway.ui_events import SessionKey, UiEvent
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
async def test_nothing_is_sent_when_no_turn_is_running() -> None:
    """没有在跑的回合、也没有游标：别出声——静默重连不该被塞一条控制帧。

    **但连接要登记** ✓✓：不登记的话，这条会话的"当前连接"还是那条已经死掉的旧连接 ✗，
    而**不挂回合**的活儿（确认/取消 ✓，见 `SessionRuntime.detach_work` ✓）照样想推给它 ✗
    → 服务端明明执行成功、事件流里也有结果 ✓，用户页面却永远等不到"已生效" ✗
    （实测复现：重连后的新连接 `received result frames: 0` ✓）。
    登记**不违反**"别出声" ✓：一条帧都不发 ✓（不补发、不 resync ✓）。
    """
    store = _ReplayStore(epoch="epoch-a", events=[_event(1, "turn-live")])
    channel = _Channel()
    runtime = _Runtime(store, None)

    await _replay_on_connect(_socket(store), runtime, channel)

    assert channel.frames == []
    assert channel.bound == [("session", _key())]
    assert runtime.attached == [_key()]
    # 不补发 ⇒ 连存储都不读 ✓（`current_epoch` 是补发的第一步 ✓）。
    assert store.calls == ["attach"]


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
