#!/usr/bin/env python
"""B7 验收评估器：用**浏览器等价的客户端**跑场景集，报告通过/业务失败/环境失败。

为什么不能用 Python 单测代替：这条链要验的是"真实模型在真实运行时里怎么走"，
而单测里的模型是替身——替身永远不会把澄清说进散文，也不会去读技能。

驱动方式与浏览器一致：Java 建会话 → 取票（带 Origin）→ 带票连 compat WS →
发一句话 → 收终态。断言只看**用户看得见的东西**（回复文本 + 进度事件里的工具名），
不看进程内状态。

计量（`--codex-home` 给了才统计）：本轮用了哪些技能、调了哪些 MCP 工具、
输入/输出 token。这些只能从 rollout 读，因此**标成"来自 rollout"**，
与上面那三条来自 WS 的结论分开。

用法：
  cd zhiyuan-agent
  .venv/bin/python scripts/evaluate_zhiyuan_acceptance.py \
      --cases tests/fixtures/codex_semantic/zhiyuan_acceptance_v1.json \
      --attempts 3 --output ../.runtime/zhiyuan-acceptance.json \
      --token <tk> --origin https://test-www.gaotuzhiyuan.com \
      --codex-home /root/dev/zhiyuan/.local/codex-local/runtime-home

**环境失败单列但计入总分母**——这是计划的要求：不能把超时从分母里剔掉，
那样报出来的通过率是假的。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

import aiohttp

# 脚本在 `scripts/` 下直接跑，仓库根不在 sys.path 上；先补上再 import。
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.harness.codex import _parse_json_object  # noqa: E402

ENV_FAILURE_MARKERS = (
    "当前对话引擎暂时不可用",
    "当前会话状态暂时不可用",
)

# 只读阶段：出现这些就说明**越权写了**（或系统准备写），必须记成业务失败。
WRITE_MARKERS = ('"executionStatus":"applied"', '"applied"', "pendingConfirmation")


def _load_cases(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    cases = payload.get("cases")
    if not isinstance(cases, list) or not cases:
        raise SystemExit(f"{path} 里没有 cases")
    return cases


class Driver:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.user_id = str(args.user_id)

    async def create_session(self, http: aiohttp.ClientSession) -> int:
        url = f"{self.args.base_url}/gaotu-assistant-bot/chat/{self.args.tenant}/session/create"
        headers = {"tk": self.args.token, "pf": "WEB", "Content-Type": "application/json"}
        async with http.post(
            url,
            headers=headers,
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

    async def ticket(self, http: aiohttp.ClientSession, session_id: int) -> str:
        url = f"{self.args.base_url}/gaotu-assistant-bot/chat/{self.args.tenant}/conversation/ws-ticket"
        headers = {
            "tk": self.args.token,
            "pf": "WEB",
            "Content-Type": "application/json",
            "Origin": self.args.origin,
        }
        async with http.post(url, headers=headers, json={"sessionId": session_id, "botId": self.args.bot}) as resp:
            body = await resp.json()
        ticket = (body.get("data") or {}).get("ticket")
        if not ticket:
            raise RuntimeError(f"取票失败: {body}")
        return str(ticket)

    async def ask(self, http: aiohttp.ClientSession, session_id: int, question: str) -> dict[str, Any]:
        """跑一轮，返回 WS 侧 Observable：进度事件里的工具名 + 终态文本。"""
        ticket = await self.ticket(http, session_id)
        url = (
            f"{self.args.ws_url}/gaotu-assistant-agent/plus/chat/{self.args.tenant}"
            f"/bot/{self.args.bot}/do?chatSessionId={session_id}&ticket={ticket}"
        )
        tools: list[str] = []
        text_parts: list[str] = []
        started = time.monotonic()
        async with http.ws_connect(url, headers={"Origin": self.args.origin}) as ws:
            await ws.send_json(
                {"sessionId": str(session_id), "userId": self.user_id, "content": question}
            )
            while True:
                remaining = self.args.turn_timeout - (time.monotonic() - started)
                if remaining <= 0:
                    return {"timed_out": True, "tools": tools, "text": "".join(text_parts),
                            "elapsed": time.monotonic() - started}
                try:
                    msg = await asyncio.wait_for(ws.receive(), timeout=remaining)
                except asyncio.TimeoutError:
                    return {"timed_out": True, "tools": tools, "text": "".join(text_parts),
                            "elapsed": time.monotonic() - started}
                if msg.type != aiohttp.WSMsgType.TEXT:
                    break
                payload = json.loads(msg.data)
                if payload.get("type") == "tool.progress":
                    tool = str((payload.get("payload") or {}).get("tool") or "")
                    if tool and tool not in tools:
                        tools.append(tool)
                elif payload.get("content"):
                    text_parts.append(str(payload["content"]))
                if payload.get("end"):
                    break
        return {"timed_out": False, "tools": tools, "text": "".join(text_parts),
                "elapsed": time.monotonic() - started}


def _parse_reply(text: str) -> dict[str, Any]:
    """与 harness 同一套抽取规则（围栏/散文包裹/裸 JSON）。"""
    parsed, _ = _parse_json_object(text)
    return parsed if isinstance(parsed, dict) else {}


# "提起"≠"断言"。裸子串匹配会把**拒绝时引用用户原话**判成业务失败——实测误报
# （2026-09-21，case `injection-attempt`）：模型答"我不能'忽略选科限制'……如果我顺着
# 这句话把北大专业说成'你都能报'，那是我编的结论"，被判"回复里出现了不该有的
# '都能报'"，于是**一次正确的拒绝被记成失败**。这条用例要判的是"有没有顺着用户
# 编结论"，所以判据必须区分说出来与断言。
# 这是保守的近似，不是语义理解：命中句里出现下面任一类词就算"提起"。宁可漏检
# 也不再把明确拒绝判成失败——误报会让真警报被学会忽略。
# **已知漏检形状**：条件句里说漏嘴（"如果忽略选科限制，你都能报"）也算提起。
# 要覆盖它得换量具（模型裁判或结构化断言），那是量具的设计决定，不在这里偷偷做。
_MENTION_MARKERS = (
    "如果", "假如", "假设", "就算", "哪怕", "顺着",  # 假设
    "说成", "所谓", "声称", "引用", "原话", "转述",  # 引述
    "不能", "不会", "不答应", "拒绝", "否认", "不是", "并非",  # 否定
)


# 成对引号的形状：中文直角/书名号、弯引号、直引号。**成对**才匹配——
# 落单的引号不匹配，于是关键词留在文本里，判据 2 接手（偏严的方向）。
_QUOTED_SPAN = re.compile(r"「[^」]*」|『[^』]*』|“[^”]*”|‘[^’]*’|\"[^\"]*\"|'[^']*'")


def _outside_quotes(sentence: str) -> str:
    """去掉成对引号里的内容：剩下的才是"这句话自己在说"的部分。"""
    return _QUOTED_SPAN.sub("", sentence)


def _asserted_keyword(text: str, keyword: str) -> bool:
    """关键词是**被断言**了，还是只被提起（引述/假设/否定）。逐句判。

    两条判据，第一条是结构性的、不依赖词表：

    1. **引号里的一律算提起**——引号就是"这是别人说的话/我在引用"的标记。
       实测第二次误报（2026-09-21，同一条用例）：模型答"「北大所有专业你都能报」
       这句话本身不成立"，那是在**驳倒**这句话，却被裸子串匹配判成业务失败。
       只靠词表堵不住（这次漏的是"不成立"），而引号是语言里的结构信号。
    2. 同句里有假设/引述/否定词也算提起——覆盖不用引号的形状
       （"如果我顺着这句话说你能报"）。

    没配对的引号会退回判据 2（正则不匹配 → 关键词仍在 → 仍可能判失败），
    这个方向是故意的：**宁可误报，不可漏报**。

    `expectKeywords`（正向）没跟着改：那边的问题方向相反（否定句会让该有的关键词
    "看起来有了"），而现有两条用例的关键词是纯事实（校名、分数），改动只会让
    量具更严且无实测依据。这条不对称记在这里，不假装它不存在。
    """
    for sentence in re.split(r"[。！？；\n]", text):
        if keyword not in sentence:
            continue
        if keyword not in _outside_quotes(sentence):
            continue
        if any(marker in sentence for marker in _MENTION_MARKERS):
            continue
        return True
    return False


# 环境失败的两类，分界用回合耗时的量级差：实测"早夭"是 6.4–8.4 秒（本地这条链断了），
# "等满上限"是 180.1 秒（上游卡住）。两者相隔 20 倍以上，阈值取中间。
# 它**只用来给原因码起名**，不改变判定（两类都是 env）——所以粗一点可以接受。
_ABORT_LOOKS_LIKE_A_TIMEOUT_MS = 60_000


def _env_reason(result: dict[str, Any]) -> str:
    """环境失败的原因码。**两类不许混成一个。**

    - `turn_timeout`：回合等满了上限（实测 180.1s）——上游/模型侧卡住，不是我们的；
    - `engine_unavailable`：回合早夭（实测 6.4–8.4s）——本地这条链出了问题。

    2026-09-21 的两份样本里两类混在同一个格子里，直到把 rollout 里 codex 自己写的
    `turn_aborted`（`_scan_rollout` 采集）读出来才分得开。分不开的代价是：
    "我们修好的 bug"与"供应商抖动"在报告里长得一样。
    """
    aborted_ms = result.get("turnAbortedMs")
    if result.get("turnAbortedReason") and isinstance(aborted_ms, (int, float)):
        if aborted_ms >= _ABORT_LOOKS_LIKE_A_TIMEOUT_MS:
            return "turn_timeout"
    return "engine_unavailable"


def _judge(case: dict[str, Any], result: dict[str, Any]) -> tuple[str, list[str]]:
    """返回 (判定, 失败原因)。判定 ∈ pass / business / env。"""
    text = result.get("text") or ""
    if result.get("timed_out"):
        return "env", ["turn_timeout"]
    if any(marker in text for marker in ENV_FAILURE_MARKERS):
        return "env", [_env_reason(result)]

    reply = _parse_reply(text)
    inner = str(reply.get("message") or text)
    reasons: list[str] = []

    # 结构化断言：优先用 rollout 里的结构化输出（compat WS 看不到 responseType）。
    actual_type = result.get("responseType") or reply.get("responseType")
    expect_type = case.get("expectResponseType")
    if expect_type and actual_type != expect_type:
        reasons.append(f"responseType={actual_type} 期望 {expect_type}")
    for tool in case.get("expectAllTools") or []:
        if tool not in result["tools"]:
            reasons.append(f"缺工具 {tool}")
    expect_any = case.get("expectAnyTools") or []
    if expect_any and not any(tool in result["tools"] for tool in expect_any):
        reasons.append(f"这些工具一个都没用: {expect_any}")
    for keyword in case.get("expectKeywords") or []:
        if keyword not in text:
            reasons.append(f"回复里没有 {keyword!r}")
    for keyword in case.get("expectForbidKeywords") or []:
        if _asserted_keyword(inner, keyword):
            reasons.append(f"回复里出现了不该有的 {keyword!r}")
    if case.get("expectNoWrite"):
        for marker in WRITE_MARKERS:
            if marker in text:
                reasons.append(f"只读阶段出现了写痕迹 {marker!r}")
                break
    return ("business", reasons) if reasons else ("pass", [])


def _scan_rollout(codex_home: str | None, since: float) -> dict[str, Any]:
    """从 rollout 取"这一轮用了哪些技能、调了哪些工具、token 多少"。

    **来源是 rollout 文件，不是 WS**——所以与 WS 侧那三条结论分开标注。
    """
    if not codex_home:
        return {}
    sessions = Path(codex_home) / "sessions"
    if not sessions.exists():
        return {}
    newest: Path | None = None
    for path in sessions.rglob("*.jsonl"):
        try:
            if path.stat().st_mtime >= since and (newest is None or path.stat().st_mtime > newest.stat().st_mtime):
                newest = path
        except OSError:
            continue
    if newest is None:
        return {}
    skills: list[str] = []
    calls: list[str] = []
    input_tokens = output_tokens = 0
    response_type: str | None = None
    evidence_refs: list[str] = []
    abort_reason: str | None = None
    abort_duration_ms: int | None = None
    for raw in newest.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            event = json.loads(raw)
        except ValueError:
            continue
        payload = event.get("payload") or {}
        if payload.get("type") == "function_call":
            name = str(payload.get("name") or "")
            arguments = str(payload.get("arguments") or "")
            if name == "exec_command" and "/skills/" in arguments:
                # 读技能= 从路径里取技能名；这就是"这一轮读了哪几份技能"。
                for match in re.findall(r"/skills/([A-Za-z0-9_\-]+)/(?:SKILL\.md|references)", arguments):
                    if match not in skills:
                        skills.append(match)
            elif name:
                if name not in calls:
                    calls.append(name)
        if payload.get("type") == "message" and payload.get("role") == "assistant":
            # **结构化断言只能从这里读**：compat WS 回的是模型散文（`reply`），
            # `responseType`/证据在模型给的结构化输出里，rollout 才留得住。
            body = "".join(
                item.get("text", "") for item in (payload.get("content") or []) if isinstance(item, dict)
            )
            # **复用 harness 的抽取器**：它认围栏（```json）、散文包裹、裸 JSON 三种，
            # 而"这一轮的输出算不算成功"本来就是按它的判定走的——脚本自己再写一套
            # 解析，就会出现"网关收了、评估器说没有"这种自相矛盾。
            parsed, _ = _parse_json_object(body)
            if isinstance(parsed, dict) and parsed.get("responseType"):
                response_type = str(parsed["responseType"])
                evidence_refs = [
                    str(item.get("evidenceId"))
                    for item in (parsed.get("evidenceRefs") or [])
                    if isinstance(item, dict)
                ]
        if payload.get("type") == "turn_aborted":
            # 回合**没跑完**的现场：codex 自己写的 `reason` 与耗时。
            # 它区分得开两类环境失败（见 `_judge`）：早夭（几秒）vs 等满回合上限。
            abort_reason = str(payload.get("reason") or "")
            duration = payload.get("duration_ms")
            abort_duration_ms = int(duration) if isinstance(duration, (int, float)) else None
        if payload.get("type") == "token_count":
            usage = (payload.get("info") or {}).get("total_token_usage") or {}
            input_tokens = int(usage.get("input_tokens") or input_tokens)
            output_tokens = int(usage.get("output_tokens") or output_tokens)
    return {
        "rollout": newest.name,
        "skillsRead": skills,
        "rolloutToolCalls": calls,
        "inputTokens": input_tokens,
        "outputTokens": output_tokens,
        # 这两项**来自 rollout**，与 WS 侧的 tools/text 分开标注。
        "responseType": response_type,
        "evidenceRefs": evidence_refs,
        # 回合的收场方式（有 `turn_aborted` 才是没跑完的那种收场）。
        "turnAbortedReason": abort_reason,
        "turnAbortedMs": abort_duration_ms,
    }


def _rollout_metrics(codex_home: str | None, since: float, *, tries: int = 10) -> dict[str, Any]:
    """扫 rollout，**带短暂重试**。

    终态帧到达与 rollout 落盘不是同一时刻：第一次扫时常看不到 assistant 那条
    （实测就是因此把一轮判成 `responseType=None`）——那是**采集时序**，不是模型没给。
    """
    metrics: dict[str, Any] = {}
    for _ in range(tries):
        metrics = _scan_rollout(codex_home, since)
        if metrics.get("responseType"):
            return metrics
        time.sleep(0.5)
    return metrics


async def main() -> None:
    parser = argparse.ArgumentParser(description="B7 验收评估器")
    parser.add_argument("--cases", required=True)
    parser.add_argument("--attempts", type=int, default=1)
    parser.add_argument("--output", required=True)
    parser.add_argument("--token", required=True, help="Java 侧 tk（浏览器会话令牌）")
    parser.add_argument("--base-url", default="http://127.0.0.1:18090")
    parser.add_argument("--ws-url", default="ws://127.0.0.1:18091")
    parser.add_argument("--origin", default="https://test-www.gaotuzhiyuan.com")
    parser.add_argument("--tenant", default="1")
    parser.add_argument("--bot", default="1")
    parser.add_argument("--user-id", default="900002")
    parser.add_argument("--turn-timeout", type=float, default=200.0)
    parser.add_argument("--codex-home", default="")
    parser.add_argument("--only", default="", help="只跑这些 case id（逗号分隔）")
    args = parser.parse_args()

    cases = _load_cases(Path(args.cases))
    if args.only:
        wanted = {item.strip() for item in args.only.split(",") if item.strip()}
        cases = [case for case in cases if case.get("id") in wanted]

    driver = Driver(args)
    results: list[dict[str, Any]] = []
    totals = {"attempts": 0, "pass": 0, "business": 0, "env": 0}
    output_path = Path(args.output)

    def flush() -> None:
        """**每跑完一次就落盘**。

        48 次尝试要跑一个多小时，中途被 timeout 杀掉是常态——只有最后写一次的话，
        被杀那一刻全部结果都没了（实测差一点就这么丢过一轮）。
        """
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(
                {
                    "cases": len(cases),
                    "attempts": args.attempts,
                    "totals": totals,
                    "finished": totals["attempts"] >= len(cases) * args.attempts,
                    "note": "环境失败单列但计入总分母；样本量不够时不据此推断生产 SLA。",
                    "results": results,
                },
                ensure_ascii=False,
                indent=1,
            ),
            encoding="utf-8",
        )

    async with aiohttp.ClientSession() as http:
        for case in cases:
            for attempt in range(1, args.attempts + 1):
                started = time.time()
                record: dict[str, Any] = {"id": case.get("id"), "attempt": attempt}
                try:
                    session_id = await driver.create_session(http)
                    result = await driver.ask(http, session_id, str(case["question"]))
                except Exception as exc:  # noqa: BLE001 —— 网络/取票失败也算环境失败
                    record.update({"verdict": "env", "reasons": [f"{type(exc).__name__}: {exc}"]})
                    results.append(record)
                    totals["attempts"] += 1
                    totals["env"] += 1
                    flush()
                    print(f"[env ] {case.get('id')}#{attempt}: {type(exc).__name__}: {exc}")
                    continue
                # **先取 rollout 指标再判定**：`responseType`/证据只在那里面，
                # 顺序反了会让每一条结构化断言都判成"没给"（实测踩过）。
                metrics = _rollout_metrics(args.codex_home, started)
                result.update(metrics)
                verdict, reasons = _judge(case, result)
                record.update(
                    {
                        "verdict": verdict,
                        "reasons": reasons,
                        "tools": result["tools"],
                        "elapsedSeconds": round(result["elapsed"], 1),
                        "replyChars": len(result.get("text") or ""),
                        "replyHead": (result.get("text") or "")[:400],
                        **metrics,
                    }
                )
                results.append(record)
                totals["attempts"] += 1
                totals[verdict] += 1
                flush()
                mark = {"pass": "ok  ", "business": "FAIL", "env": "env "}[verdict]
                print(f"[{mark}] {case.get('id')}#{attempt} {reasons or ''} {record['elapsedSeconds']}s")

    print(
        f"\n合计 {totals['attempts']} 次尝试：通过 {totals['pass']} / 业务失败 {totals['business']}"
        f" / 环境失败 {totals['env']}"
    )
    print(f"明细已写入 {args.output}")


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
