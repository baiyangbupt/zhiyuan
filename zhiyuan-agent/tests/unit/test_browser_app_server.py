"""带闸门的假 app-server（Task C4 ②）——**重点是"闸门没放行就不许有终态"** ✓✓。

这条不是普通单测 ✓：它是 C4 那条"不依赖固定延时的流式断言"的**地基** ✓——
如果替身在没放行时也会发 **`status=completed`** ✗，"UI 先显示进度、终态还没来" 就成了永远为真的假绿 ✗✓。
（注意 ✓：`turn/completed` 是终态**方法名** ✓，成功与否看 `status` ✓——替身超时后会用 `interrupted` 收尾 ✓，
 那是"必须收尾、不许假成功" ✓，不是假绿 ✓。）
"""

from __future__ import annotations

import importlib.util
import json
import os
import queue
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parents[3]
FIXTURES = ROOT_DIR / "zhiyuan-agent" / "tests" / "fixtures" / "codex"
APP_SERVER = FIXTURES / "browser_app_server.py"
WRAPPER = FIXTURES / "browser_codex_wrapper.sh"
CONTROL = FIXTURES / "browser_runtime_control.py"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


control = _load(CONTROL, "browser_runtime_control")


class ServerSession:
    """把子进程的 stdout 收进队列 ✓——不这样就得阻塞读，超时无从谈起 ✗。"""

    def __init__(self, env_extra: dict[str, str]) -> None:
        env = dict(os.environ)
        env.update(env_extra)
        self.process = subprocess.Popen(
            [sys.executable, str(APP_SERVER)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, env=env,
        )
        self.lines: "queue.Queue[dict]" = queue.Queue()
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self) -> None:
        assert self.process.stdout is not None
        for raw in self.process.stdout:
            raw = raw.strip()
            if not raw:
                continue
            try:
                self.lines.put(json.loads(raw))
            except json.JSONDecodeError:
                self.lines.put({"raw": raw})

    def send(self, payload: dict) -> None:
        assert self.process.stdin is not None
        self.process.stdin.write(json.dumps(payload) + "\n")
        self.process.stdin.flush()

    def drain(self, seconds: float = 0.6) -> list[dict]:
        """收一段时间的消息 ✓（用它来断言"**没有**终态" ✗——必须等一小会儿才可信 ✓）。"""
        got: list[dict] = []
        deadline = time.time() + seconds
        while time.time() < deadline:
            try:
                got.append(self.lines.get(timeout=0.05))
            except queue.Empty:
                continue
        return got

    def close(self) -> None:
        self.process.kill()
        self.process.wait(timeout=10)


@pytest.fixture()
def stack():
    server = control.serve("127.0.0.1", 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d" % server.server_address[1]
    session = ServerSession({
        "CODEX_BROWSER_CONTROL_BASE": base,
        "CODEX_BROWSER_RUN_ID": "run-1",
        "CODEX_BROWSER_RELEASE_TIMEOUT": "5",
    })
    try:
        yield session, base, server.registry
    finally:
        session.close()
        server.shutdown()
        server.server_close()


def _methods(messages: list[dict]) -> list[str]:
    return [str(m.get("method") or "") for m in messages]


def _release(base: str, turn_id: str) -> None:
    request = urllib.request.Request(f"{base}/gates/{turn_id}/release", data=b"{}", method="POST")
    urllib.request.urlopen(request, timeout=5).read()


def test_progress_arrives_but_the_terminal_waits_for_the_gate(stack) -> None:
    session, base, registry = stack
    session.send({"jsonrpc": "2.0", "id": 1, "method": "turn/start",
                  "params": {"threadId": "thr_1", "turnId": "turn-fixed-1"}})

    before = session.drain(0.8)
    methods = _methods(before)
    assert "item/agentMessage/delta" in methods, "先要有进度 ✓"
    assert "item/started" in methods, "工具进度也要到 ✓（UI 靠它显示阶段 ✓）"
    assert "turn/completed" not in methods, "**闸门没放行就不许有终态** ✗✓"
    assert registry.is_released("turn-fixed-1") is False

    _release(base, "turn-fixed-1")
    after = session.drain(1.5)
    methods = _methods(after)
    assert "turn/completed" in methods, "放行后终态才到 ✓"
    assert any(m.get("method") == "item/completed" and m["params"]["item"]["type"] == "agentMessage"
               for m in after), "终态要带合法的结构化输出 ✓（否则测的是输出修复路径 ✗）"


def test_the_fixture_streams_multiple_deltas_that_rebuild_the_final_text(stack) -> None:
    """**"分多条 delta"场景** ✓✓：替身发的增量必须**不止一条**、且拼接后 = 默认终态正文 ✓——
    只发一条的替身会让网关的合并/节流与"终态整段替换"都测不到 ✓
    （真实 codex 的口径同此：逐字切、拼接 = 终态正文 ✓）。
    """
    session, base, _ = stack
    session.send({"jsonrpc": "2.0", "id": 1, "method": "turn/start",
                  "params": {"threadId": "thr_1", "turnId": "turn-stream-1"}})

    before = session.drain(0.8)
    deltas = [m for m in before if m.get("method") == "item/agentMessage/delta"]
    assert len(deltas) >= 2, f"要发多条增量 ✓（收到 {len(deltas)} 条）"
    assert all((m.get("params") or {}).get("itemId") for m in deltas), "增量要带 itemId ✓（真实形状 ✓）"
    streamed = "".join(str((m.get("params") or {}).get("delta") or "") for m in deltas)
    assert streamed == (
        '{"responseType": "text", "message": "闸门放行后的答案", "executionStatus": "completed"}'
    )

    _release(base, "turn-stream-1")
    after = session.drain(1.5)
    completed = [
        m for m in after
        if m.get("method") == "item/completed" and m["params"]["item"]["type"] == "agentMessage"
    ]
    assert completed, "放行后要有终态正文 ✓"
    assert completed[-1]["params"]["item"]["text"] == streamed, (
        "增量拼接后必须与终态正文一致 ✓（真实运行时的实测口径同此 ✓）"
    )


def test_interrupt_produces_a_real_interrupted_terminal(stack) -> None:
    """F12 的地基 ✓：中断要发**真中断** ✓，绝不能补一个假的 completed ✗。"""
    session, _, _ = stack
    session.send({"jsonrpc": "2.0", "id": 1, "method": "turn/start",
                  "params": {"threadId": "thr_1", "turnId": "turn-int-1"}})
    session.drain(0.5)

    session.send({"jsonrpc": "2.0", "id": 2, "method": "turn/interrupt",
                  "params": {"threadId": "thr_1", "turnId": "turn-int-1"}})
    after = session.drain(1.0)

    terminals = [m for m in after if m.get("method") == "turn/completed"]
    assert terminals, "中断要有终态 ✓"
    assert terminals[-1]["params"]["turn"]["status"] == "interrupted"
    assert not [m for m in after if m.get("method") == "item/completed"
                and m["params"]["item"]["type"] == "agentMessage"], "中断不该带出答案 ✗"


def test_unreleased_turn_fails_loudly_instead_of_faking_a_terminal(stack) -> None:
    """超时 = 没放行 ✗：必须**大声失败** ✓（不许顺手补终态 ✗——那会把"卡住"测成"通过" ✗✗）。"""
    session, _, _ = stack
    session.send({"jsonrpc": "2.0", "id": 1, "method": "turn/start",
                  "params": {"threadId": "thr_1", "turnId": "turn-timeout-1"}})

    messages = session.drain(6.5)  # 替身自己的超时是 5s ✓
    methods = _methods(messages)
    assert "test/release_timeout" in methods, "要明确报「没放行」 ✓"
    # 断言对象要选对 ✓✓：`turn/completed` 是**终态事件的方法名** ✓，"是否真成功"由
    # `status` 字段区分 ✓（参照替身的中断路径也是 `turn/completed` + `interrupted` ✓）。
    # 所以断的是"**不许有 status=completed**" ✓（F12 原话"无假 completed" ✓），
    # 而不是"不许有终态事件" ✗——后者会把"超时也必须收尾"这条正确行为判死 ✓。
    terminals = [m for m in messages if m.get("method") == "turn/completed"]
    assert terminals, "超时也必须收尾 ✓（否则网关回合永远关不上 ✗，整栈被毒住 ✓）"
    assert all(m["params"]["turn"]["status"] != "completed" for m in terminals), "**不许假 completed** ✗✗"
    assert not [m for m in messages if m.get("method") == "item/completed"
                and m["params"]["item"]["type"] == "agentMessage"], "超时不该带出答案 ✗"


def test_client_supplied_turn_id_is_echoed_for_data_turn_id_assertions(stack) -> None:
    """任务书要 `data-turn-id` 那类断言 ✓ → 回合号必须能用客户端给的 ✓。"""
    session, base, _ = stack
    session.send({"jsonrpc": "2.0", "id": 1, "method": "turn/start",
                  "params": {"threadId": "thr_1", "turnId": "turn-injected-7"}})
    messages = session.drain(0.6)
    events = [m for m in messages if m.get("method") in {"item/agentMessage/delta", "item/started"}]
    assert events, "要发出进度 ✓"
    assert all(m["params"]["turnId"] == "turn-injected-7" for m in events), "回合号必须是注入的那个 ✓"

def test_wrapper_accepts_the_real_composition_shape() -> None:
    """**回归**：真实 argv 的**子命令在最后** ✓。

    实测形状（`app/gateway/composition.py:build_codex_command` ✓）：
    `<bin> [--config mcp_servers.…={…}] [NATIVE_USER_INPUT_FLAGS…] app-server --stdio` ✓。
    第一版 wrapper 假设 `$1` 就是 `app-server` ✗ → 真栈上被拒 ✓
    （日志 `app server exited on its own returncode=64` ✓，退出码 64 正是 wrapper 的用法错误 ✓）。
    """
    good = subprocess.run(
        ["bash", str(WRAPPER), "--config", "mcp_servers.zhiyuan_domain={}", "app-server", "--stdio"],
        input='{"jsonrpc": "2.0", "id": 1, "method": "thread/start", "params": {}}\n',
        text=True, capture_output=True, timeout=20,
    )
    assert '"result"' in good.stdout, f"真实形状必须被接受 ✓：stdout={good.stdout!r} stderr={good.stderr!r}"

    bad = subprocess.run(
        ["bash", str(WRAPPER), "--config", "x", "tui"],
        text=True, capture_output=True, timeout=20,
    )
    assert bad.returncode == 64, "非 app-server 子命令仍要拒 ✓"


def test_clarification_scenario_asks_then_resumes_after_the_answer(stack) -> None:
    """**场景表的第一支** ✓✓：`clarification` = 先要一次澄清 ✓，拿到答案后再收尾 ✓。

    这验的是夹具本身 ✓（F02 的地基 ✓）：
      · 替身发的是 `item/tool/requestUserInput` ✓ + `params.questions[]` ✓
        （`app/gateway/user_input.py:31/113-120` ✓ 要的就是这个形状 ✓）；
      · 客户端用**原 rpc id** 回答案 ✓（桥就是这么回的 ✓）→ 替身**收下并继续** ✓✓；
      · 全程不需要真栈 ✓——所以形状错误会在**单测**里就暴露 ✓，不会等到浏览器里 ✓。
    """
    session, base, registry = stack
    registry.set_scenario("run-1", "clarification")

    session.send({"jsonrpc": "2.0", "id": 1, "method": "turn/start",
                  "params": {"threadId": "thr_1", "turnId": "turn-clarify-1"}})

    asked = session.drain(0.8)
    request = next((m for m in asked if m.get("method") == "item/tool/requestUserInput"), None)
    assert request is not None, f"要发一次澄清请求 ✓（收到：{_methods(asked)}）"
    questions = (request.get("params") or {}).get("questions") or []
    assert questions and questions[0].get("id"), "questions 要有 id ✓（桥按 id 收答案 ✓）"
    assert (request.get("params") or {}).get("turnId") == "turn-clarify-1", "请求要带回合号 ✓"
    assert "turn/completed" not in _methods(asked), "答案没回来之前不许收尾 ✓"

    # 客户端角色：用**原 rpc id** 回答案 ✓
    session.send({"jsonrpc": "2.0", "id": request["id"], "result": {"answers": {"q1": ["软件工程"]}}})

    resumed = session.drain(1.0)
    assert "test/clarification_answered" in _methods(resumed), "收到答案后要继续 ✓（不是忽略它 ✗）"
    # 放行之后才收尾 ✓（场景不影响闸门语义 ✓）
    _release(base, "turn-clarify-1")
    final = session.drain(1.5)
    assert "turn/completed" in _methods(final), "放行后照常收尾 ✓"
