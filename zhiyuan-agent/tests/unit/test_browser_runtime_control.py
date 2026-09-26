"""合同栈控制服务的守卫（Task C4 ②）。

它能把模型**停在**中间 ✓（这正是流式用例要的 ✓），所以两件事必须钉死 ✓：
**只监听 loopback** ✓、**reset 只清指定 run 的闸门** ✓（清错 run 会让别的用例永久卡住 ✗）。
"""

from __future__ import annotations

import importlib.util
import json
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parents[3]
CONTROL = ROOT_DIR / "zhiyuan-agent" / "tests" / "fixtures" / "codex" / "browser_runtime_control.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("browser_runtime_control", CONTROL)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    # `@dataclass` 与类型注解会回查 `sys.modules` ✗——先登记再 exec ✓（这个坑今天踩过 ✓）。
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


control = _load_module()


@pytest.fixture()
def running_control():
    # 用**临时端口** ✓（0 ✓）——单测不去占 18293 ✓，那是给真跑的合同栈留的 ✓。
    server = control.serve("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = "http://127.0.0.1:%d" % server.server_address[1]
    try:
        yield base, server.registry
    finally:
        server.shutdown()
        server.server_close()


def _get(url: str) -> tuple[int, dict]:
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read().decode("utf-8") or "{}")


def _post(url: str, payload: dict | None = None) -> tuple[int, dict]:
    data = json.dumps(payload or {}).encode("utf-8")
    request = urllib.request.Request(url, data=data, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read().decode("utf-8") or "{}")


def test_identity_says_fake_and_cannot_be_overridden_by_the_caller(running_control) -> None:
    base, _ = running_control

    status, payload = _get(f"{base}/identity")
    assert status == 200
    assert payload["runtimeKind"] == "fake", "身份由服务自己给 ✓（项目名不代表运行时 ✗）"

    # 试图用参数把它说成 real ✗ → 仍必须是 fake ✓
    status, payload = _get(f"{base}/identity?runtimeKind=real")
    assert status == 200
    assert payload["runtimeKind"] == "fake"


def test_control_service_refuses_to_bind_anything_but_loopback() -> None:
    # 断言口语化一点没关系 ✓，但**要匹配信息里真有的东西** ✗（先写英文 loopback 是我想当然 ✓）。
    with pytest.raises(ValueError, match="127.0.0.1"):
        control.serve("0.0.0.0", 0)


def test_gate_release_is_per_turn_and_one_shot(running_control) -> None:
    base, _ = running_control
    status, _ = _post(f"{base}/gates", {"runId": "run-a", "turnId": "turn-1"})
    assert status == 200

    assert _get(f"{base}/gates/turn-1")[1]["released"] is False
    assert _post(f"{base}/gates/turn-1/release")[1]["released"] is True
    assert _get(f"{base}/gates/turn-1")[1]["released"] is True

    # 没登记过的回合 → 404 ✓（不许"放行一个不存在的闸门" ✓）
    assert _post(f"{base}/gates/turn-unknown/release")[0] == 404


def test_reset_only_clears_the_named_run(running_control) -> None:
    """**本文件最要紧的一条** ✓：reset 清错 run，会让别的用例的闸门永久卡住 ✗。"""
    base, _ = running_control
    for turn in ("a-1", "a-2"):
        _post(f"{base}/gates", {"runId": "run-a", "turnId": turn})
    _post(f"{base}/gates", {"runId": "run-b", "turnId": "b-1"})

    status, payload = _post(f"{base}/runs/run-a/reset")
    assert status == 200
    assert payload["cleared"] == 2, "只清 run-a 的两条"

    _post(f"{base}/gates/a-1/release")
    assert _get(f"{base}/gates/a-1")[1]["released"] is False, "run-a 的闸门已被清 → 不能再放行"
    assert _get(f"{base}/gates/b-1")[1]["released"] is False
    assert _post(f"{base}/gates/b-1/release")[1]["released"] is True, "**run-b 的闸门没被动过** ✓"


def test_actions_are_recorded_for_evidence(running_control) -> None:
    base, _ = running_control
    _post(f"{base}/gates", {"runId": "run-a", "turnId": "turn-1"})
    _post(f"{base}/gates/turn-1/release")
    _post(f"{base}/runs/run-a/reset")

    _, payload = _get(f"{base}/gates")
    actions = [row["action"] for row in payload["actions"]]
    assert actions == ["release", "reset"], "动作要留痕 ✓（e2e 报告要引用它 ✓）"
