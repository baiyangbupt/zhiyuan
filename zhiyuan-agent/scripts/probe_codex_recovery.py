#!/usr/bin/env python3
"""进程级恢复探针：原生 runtime 死掉之后，哪种会话还能继续。

评估器（`scripts/evaluate_zhiyuan_acceptance.py`）每个 case 都**新建会话**，所以
它测不到多轮路径；用例注释里写着"重启连续性需要进程级脚本配合"。这个脚本就是
那一环：它按浏览器等价路径（Java 取票 → 带票连 compat WS）跑**同一会话的多轮**，
并在轮次之间/回合之中把 codex 进程杀掉。

四种形状（前三条走 `--shape between-turns`，接着 `--shape mid-turn`，最后一条
`--shape agent-restart`）：

| 形状 | 期望 |
|---|---|
| 既有会话 × 死进程（回合之间） | 这一轮如实失败（可恢复），**不是**永久不可用 |
| 既有会话 × 重拉之后 | 下一轮正常回答（日志里应有 `resumed; keeping the model-side context`） |
| 新会话 × 死进程 | 正常回答（取 thread 那一步自己重拉并重试） |
| 回合进行中 × 死进程 | 这一轮如实失败；下一轮正常回答 |
| **网关重启**（不是 codex 重启） | 重启后同一会话仍然回答，且走的是 resume——断点续跑的 A7 主张本身 |

最后一条是 A7 的**头号场景**，也是 A 线证据表里"真实 Java 未验"的那一格：thread
是运行身份、绑在后端，网关进程一重启，进程内那张表就没了，只能靠 Java 的绑定把
thread 找回来。它需要重启 agent 进程，所以单独一个形状（会打断正在跑的评估）。

**判定写在脚本里**：期望不满足就非零退出。只打印不判定的脚本，看的人得自己
记住哪一行才算对——那正是"全绿"与"真的对"之间的缝。

用法：
    .venv/bin/python scripts/probe_codex_recovery.py --shape between-turns
    .venv/bin/python scripts/probe_codex_recovery.py --shape mid-turn
    .venv/bin/python scripts/probe_codex_recovery.py --shape agent-restart
退出码：0 = 全部符合期望；1 = 有不符合（每条都打印实际形状）。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import aiohttp

# 与本地最小栈的默认值一致（scripts/start-codex-local.sh 的 18090/18091 那套）。
DEFAULTS = {
    "base_url": "http://127.0.0.1:18090",
    "agent_ws": "ws://127.0.0.1:18091",
    "origin": "https://test-www.gaotuzhiyuan.com",
    "tenant": "1",
    "bot": "1",
    "user_id": "900002",
}
QUESTION_1 = "浙江第一段的批次码是多少"
QUESTION_2 = "那第二段的批次码呢"

# 期望值：`text` = 正常回答；`error` = 如实失败（可恢复）。
EXPECTED = {
    "between-turns": [
        ("既有会话·健康", "text"),
        ("既有会话·死进程后第一轮", "error"),
        ("既有会话·重拉后下一轮", "text"),
        ("新会话·死进程后第一轮", "text"),
        ("新会话·第二轮", "text"),
    ],
    "mid-turn": [
        ("回合内死亡", "error"),
        ("下一轮", "text"),
    ],
    "agent-restart": [
        ("重启前一轮", "text"),
        ("重启后同一会话", "text"),
    ],
}

# 恢复走的就是这条路。网关重启后如果改成一律新建，这条日志不会出现——
# 而用户那边"它忘了刚才说过什么"不会有任何报错。
RESUMED_MARK = "resumed; keeping the model-side context"


def _pids_matching(needle: str) -> list[int]:
    out = subprocess.run(["ps", "-eo", "pid,cmd"], capture_output=True, text=True).stdout
    return [
        int(line.strip().split(" ", 1)[0])
        for line in out.splitlines()[1:]
        if needle in line
    ]


def kill_codex() -> list[int]:
    """杀掉原生 runtime（连同 node 包装进程）。

    杀的是**子进程**而不是 agent：要的就是"进程没了、且不会自己复活"这个状态。
    """
    pids = _pids_matching("app-server --stdio")
    for pid in pids:
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    return pids


def agent_pid(port: int) -> int:
    out = subprocess.run(["ss", "-lntp"], capture_output=True, text=True).stdout
    for line in out.splitlines():
        if f":{port}" in line and "pid=" in line:
            return int(line.split("pid=")[1].split(",")[0])
    raise RuntimeError(f"agent pid not found on port {port}")


def restart_agent(pid: int, *, port: int, log_path: str, cwd: str) -> int:
    """原样重启 agent：环境从 `/proc/<pid>/environ` 取，不用重跑整个本地栈。

    `start-codex-local.sh` 明确"不接管、不替换既有进程"，所以重启单个进程只能
    自己来。环境必须原样继承：`GATEWAY_MODE` / `CODEX_APP_SERVER_*` / 绑定登记表
    路径少一个，起的就不是同一个栈了（而那种"重启"验的不是 A7）。
    """
    if not os.path.exists(log_path):
        open(log_path, "ab").close()
    env: dict[str, str] = {}
    with open(f"/proc/{pid}/environ", "rb") as handle:
        for chunk in handle.read().split(b"\0"):
            if not chunk:
                continue
            key, _, value = chunk.decode(errors="replace").partition("=")
            env[key] = value
    os.kill(pid, signal.SIGTERM)
    for _ in range(50):
        time.sleep(0.2)
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            break
    else:
        os.kill(pid, signal.SIGKILL)
    with open(log_path, "ab") as log:
        proc = subprocess.Popen(
            [
                sys.executable,
                ".venv/bin/uvicorn",
                "app.server:app",
                "--host",
                "0.0.0.0",
                "--port",
                str(port),
            ],
            cwd=cwd,
            env=env,
            stdout=log,
            stderr=log,
            start_new_session=True,
        )
    return proc.pid


async def wait_healthy(base_url: str, timeout: float = 60.0) -> None:
    deadline = time.monotonic() + timeout
    async with aiohttp.ClientSession() as http:
        while time.monotonic() < deadline:
            try:
                async with http.get(f"{base_url}/health", timeout=aiohttp.ClientTimeout(total=3)) as resp:
                    if resp.status == 200:
                        return
            except Exception:  # noqa: BLE001 —— 还没起来就是连接被拒，继续等
                pass
            await asyncio.sleep(0.5)
    raise RuntimeError("agent 重启后没有在超时内变健康")


def log_line_count(log_path: str, needle: str) -> int:
    try:
        with open(log_path, "r", errors="replace") as handle:
            return sum(1 for line in handle if needle in line)
    except FileNotFoundError:
        return 0


class Prober:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.failures: list[str] = []

    async def new_session(self, http: aiohttp.ClientSession) -> int:
        async with http.post(
            f"{self.args.base_url}/gaotu-assistant-bot/chat/{self.args.tenant}/session/create",
            headers={"tk": self.args.token, "pf": "WEB", "Content-Type": "application/json"},
            json={
                "botId": self.args.bot,
                "draft": True,
                "prepareType": {"code": "VOLUNTEER", "desc": "智能填报"},
            },
        ) as resp:
            body = await resp.json()
        session_id = (body.get("data") or {}).get("id")
        if not session_id:
            raise RuntimeError(f"建会话失败: {body}")
        return int(session_id)

    async def turn(
        self, http: aiohttp.ClientSession, session_id: int, text: str, timeout: float
    ) -> dict:
        started = time.monotonic()
        headers = {
            "tk": self.args.token,
            "pf": "WEB",
            "Content-Type": "application/json",
            "Origin": self.args.origin,
        }
        async with http.post(
            f"{self.args.base_url}/gaotu-assistant-bot/chat/{self.args.tenant}"
            f"/conversation/ws-ticket",
            headers=headers,
            json={"sessionId": session_id, "botId": self.args.bot},
        ) as resp:
            body = await resp.json()
        ticket = (body.get("data") or {}).get("ticket")
        if not ticket:
            raise RuntimeError(f"取票失败: {body}")
        url = (
            f"{self.args.agent_ws}/gaotu-assistant-agent/plus/chat/{self.args.tenant}"
            f"/bot/{self.args.bot}/do?chatSessionId={session_id}&ticket={ticket}"
        )
        final: dict | None = None
        async with http.ws_connect(url, headers={"Origin": self.args.origin}, heartbeat=None) as ws:
            await ws.send_json(
                {"sessionId": str(session_id), "userId": self.args.user_id, "content": text}
            )
            while True:
                message = await asyncio.wait_for(ws.receive(), timeout=timeout)
                if message.type == aiohttp.WSMsgType.TEXT:
                    payload = json.loads(message.data)
                    if payload.get("type") in {"reply", "error", "recoverable.error"} or payload.get(
                        "end"
                    ):
                        final = payload
                        break
                elif message.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                    break
        elapsed = round(time.monotonic() - started, 1)
        if final is None:
            return {"kind": "no_final", "elapsed": elapsed}
        content = str(final.get("content") or final.get("reply") or "")
        # 终态分两类：拿到回答（可能同时带着结构化输出），或如实失败。
        kind = "error" if final.get("error") or final.get("type") in {"error", "recoverable.error"} else "text"
        return {"kind": kind, "elapsed": elapsed, "error": final.get("error"), "head": content[:80]}

    def check(self, label: str, result: dict, expected: str) -> None:
        ok = result.get("kind") == expected
        if not ok:
            self.failures.append(f"{label}: 期望 {expected}，实际 {result}")
        print(
            f"[{'ok  ' if ok else 'FAIL'}] {label} {result.get('elapsed')}s "
            f"kind={result.get('kind')} error={result.get('error')} {result.get('head', '')}",
            flush=True,
        )


async def run_between_turns(prober: Prober) -> None:
    async with aiohttp.ClientSession() as http:
        existing = await prober.new_session(http)
        fresh = await prober.new_session(http)
        print(f"会话：既有={existing} 新={fresh}", flush=True)

        prober.check(
            "既有会话·健康",
            await prober.turn(http, existing, QUESTION_1, prober.args.timeout),
            "text",
        )
        print(f"--- kill codex {kill_codex()} ---", flush=True)
        await asyncio.sleep(1)
        prober.check(
            "既有会话·死进程后第一轮",
            await prober.turn(http, existing, QUESTION_2, prober.args.timeout),
            "error",
        )
        prober.check(
            "既有会话·重拉后下一轮",
            await prober.turn(http, existing, QUESTION_2, prober.args.timeout),
            "text",
        )
        print(f"--- kill codex {kill_codex()} ---", flush=True)
        await asyncio.sleep(1)
        prober.check(
            "新会话·死进程后第一轮",
            await prober.turn(http, fresh, QUESTION_1, prober.args.timeout),
            "text",
        )
        prober.check(
            "新会话·第二轮",
            await prober.turn(http, fresh, QUESTION_2, prober.args.timeout),
            "text",
        )


async def run_mid_turn(prober: Prober) -> None:
    async with aiohttp.ClientSession() as http:
        session_id = await prober.new_session(http)
        print(f"会话={session_id}", flush=True)
        task = asyncio.create_task(prober.turn(http, session_id, QUESTION_1, prober.args.timeout))
        await asyncio.sleep(prober.args.kill_after)
        print(f"--- 回合进行中 kill codex {kill_codex()} ---", flush=True)
        prober.check("回合内死亡", await task, "error")
        prober.check(
            "下一轮",
            await prober.turn(http, session_id, QUESTION_2, prober.args.timeout),
            "text",
        )


async def run_agent_restart(prober: Prober) -> None:
    """网关进程重启：进程内的 thread 表没了，只能靠 Java 的绑定把 thread 找回来。"""
    port = int(prober.args.agent_ws.rsplit(":", 1)[-1].split("/")[0])
    # `/health` 在 **agent** 上（`--base-url` 是 Java，它没有这个端点——第一版就是
    # 打错了地方，于是"等健康"等到超时，看起来像重启失败）。
    agent_http = "http://" + prober.args.agent_ws.split("://", 1)[-1]
    async with aiohttp.ClientSession() as http:
        session_id = await prober.new_session(http)
        print(f"会话={session_id}", flush=True)
        prober.check(
            "重启前一轮",
            await prober.turn(http, session_id, QUESTION_1, prober.args.timeout),
            "text",
        )
        before = log_line_count(prober.args.agent_log, RESUMED_MARK)
        old_pid = agent_pid(port)
        new_pid = restart_agent(
            old_pid,
            port=port,
            log_path=prober.args.agent_log,
            cwd=prober.args.agent_cwd,
        )
        print(f"--- 网关重启：agent {old_pid} → {new_pid} ---", flush=True)
        await wait_healthy(agent_http)
        prober.check(
            "重启后同一会话",
            await prober.turn(http, session_id, QUESTION_2, prober.args.timeout),
            "text",
        )
        after = log_line_count(prober.args.agent_log, RESUMED_MARK)
        if after <= before:
            prober.failures.append(
                f"重启后没走 resume：日志里 {RESUMED_MARK!r} 没新增（before={before} after={after}）"
            )
            print(f"[FAIL] 重启后没走 resume（before={before} after={after}）", flush=True)
        else:
            print(f"[ok  ] 重启后走的是 resume（日志新增 {after - before} 条）", flush=True)


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--shape", choices=sorted(EXPECTED), default="between-turns")
    parser.add_argument("--base-url", default=DEFAULTS["base_url"])
    parser.add_argument("--agent-ws", default=DEFAULTS["agent_ws"])
    parser.add_argument("--origin", default=DEFAULTS["origin"])
    parser.add_argument("--tenant", default=DEFAULTS["tenant"])
    parser.add_argument("--bot", default=DEFAULTS["bot"])
    parser.add_argument("--user-id", default=DEFAULTS["user_id"])
    parser.add_argument("--token", default="codex-local-test-token")
    parser.add_argument("--timeout", type=float, default=150.0)
    parser.add_argument(
        "--kill-after",
        type=float,
        default=4.0,
        help="mid-turn 形状：回合开始多少秒后杀进程",
    )
    parser.add_argument(
        "--agent-log",
        default="/tmp/agent-18091.log",
        help="agent 的 stdout/stderr 落点（agent-restart 形状要靠它判 resume）",
    )
    parser.add_argument(
        "--agent-cwd",
        default=str(Path(__file__).resolve().parents[1]),
        help="zhiyuan-agent 工程根（重启 agent 时的工作目录）",
    )
    args = parser.parse_args()

    port = int(args.agent_ws.rsplit(":", 1)[-1].split("/")[0])
    print(f"agent_pid={agent_pid(port)} codex_pids={_pids_matching('app-server --stdio')}", flush=True)
    prober = Prober(args)
    try:
        if args.shape == "between-turns":
            await run_between_turns(prober)
        elif args.shape == "mid-turn":
            await run_mid_turn(prober)
        else:
            await run_agent_restart(prober)
    except Exception as exc:  # noqa: BLE001 —— 探针要如实报，不要假装跑通
        prober.failures.append(f"{type(exc).__name__}: {exc}")
        print(f"[FAIL] 探针异常: {type(exc).__name__}: {exc}", flush=True)

    if prober.failures:
        print("\n不符合期望的轮次：", flush=True)
        for item in prober.failures:
            print(f"  - {item}", flush=True)
        return 1
    print("\n全部符合期望。", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
