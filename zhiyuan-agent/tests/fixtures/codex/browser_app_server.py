#!/usr/bin/env python3
"""合同栈用的**带闸门**假 Codex app-server（Task C4 ②）。

与 `fake_app_server.py` 的关系 ✓：**协议形状照抄它** ✓（jsonrpc 2.0 ✓、item 嵌在 `params` 里 ✓、
delta 用 `item/agentMessage/delta` ✓），但**它是独立实现** ✓——那个文件是脚本、import 即读 stdin ✗，
而 C4 要的是"**经控制服务**放行" ✓（它那边是 `test/release` 走 stdio ✓）。改它又会波及
一堆集成测试 ✗，所以另起一份 ✓。

它只做流式用例需要的那点事 ✓：

1. `turn/start` → 回 result ✓ → 发**一组**（4 条）delta ✓（"分多条"场景，见 `_DELTA_FRAGMENTS` ✓）
   → 发一条 MCP 工具进度 ✓ → **就停住不发终态** ✗✓；
2. 之后**轮询控制服务** `GET /gates/{turnId}` ✓，`released` 为真才发 `agentMessage` + `turn/completed` ✓；
3. `turn/interrupt` → 发**真中断**的终态 ✓（`status: interrupted` ✓，绝不发假的 completed ✗）；
4. 回合号优先用客户端给的 ✓（任务书："客户端测试注入固定下一次 turnId（仅测试构建）" ✓）——
   否则 `data-turn-id` 那类断言无从谈起 ✓。

控制服务不可达时**大声失败** ✗（不许默默把终态发了 ✓）：那会把"没放行"测成"放行了" ✗。
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from typing import Any

CONTROL_BASE = os.environ.get("CODEX_BROWSER_CONTROL_BASE", "http://127.0.0.1:18293")
RUN_ID = os.environ.get("CODEX_BROWSER_RUN_ID", "browser-run")
# 闸门等待上限 ✓：到点仍没放行就**大声失败** ✗（把"卡住"和"通过"分开 ✓）。
RELEASE_TIMEOUT_SECONDS = float(os.environ.get("CODEX_BROWSER_RELEASE_TIMEOUT", "60"))
# 进度里报的工具名 ✓：UI 会把它映成"历年录取"这类字样 ✓（C4 的流式用例就断言这个 ✓）。
PROGRESS_TOOL = os.environ.get("CODEX_BROWSER_PROGRESS_TOOL", "admission.get_history")
# "模型格式坏"场景里塞的泄漏标记 ✓（F15）：用例断言它**不出现**在页面上 ✓。
LEAK_MARKER = os.environ.get("CODEX_BROWSER_LEAK_MARKER", "RAW-MODEL-LEAK-MARKER")

_threads: set[str] = set()
_turn_counter = 0
_clarify_request_id = 9000
# 终态**只发一次** ✓（中断与放行可能同时到 ✓）：两个集合都在锁里改 ✓。
_finished_turns: set[str] = set()
# 澄清的答案：替身发 server→client 请求 ✓，客户端用**原 rpc id** 回 ✓
#（`app/gateway/user_input.py:99` 的桥就是这么回的 ✓）→ 主循环收下 ✓，等待线程取用 ✓。
_answers: dict[int, Any] = {}
_answers_lock = threading.Lock()
_state_lock = threading.Lock()
# stdout 会被主线程与等待线程同时写 ✗——不加锁会写出半行 JSON ✗✗（读方直接解析失败 ✓）。
_send_lock = threading.Lock()
# **替身自己的账本** ✓✓：它跑在 agent 的子进程里，stdout 被网关读走 ✗——
# "闸门到底放行了没有、替身轮询的是哪个 id"这类问题，外面的探针看不见 ✗，
# 只能靠猜 ✓（2026-09-26 实测：放行明明落了、替身却等到超时 ✗，猜了两个来回 ✗）。
# 路径可覆盖 ✓；默认**不带进程号**（一条栈里正常只有一份替身 ✓，多份时自己覆盖 ✓）。
TRACE_PATH = os.environ.get("CODEX_BROWSER_FAKE_TRACE", "/tmp/codex-fake-runtime.log")


def _trace(event: str, **fields: Any) -> None:
    try:
        with open(TRACE_PATH, "a", encoding="utf-8") as handle:
            handle.write(
                json.dumps({"at": round(time.time(), 3), "event": event, **fields}, ensure_ascii=False)
                + "\n"
            )
    except OSError:
        pass  # 账本写不进去**不能**影响替身本身 ✓：它是探针，不是被测物 ✓。


def send(payload: dict) -> None:
    with _send_lock:
        sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
        sys.stdout.flush()


def _finish_once(thread_id: str, turn_id: str, *, interrupted: bool) -> None:
    """终态**最多一条** ✓——中断先到就不再补"放行后的答案" ✓✓。"""
    with _state_lock:
        if turn_id in _finished_turns:
            _trace("finish_once.skipped", turnId=turn_id, interrupted=interrupted)
            return
        _finished_turns.add(turn_id)
    _trace("finish_once", turnId=turn_id, interrupted=interrupted)
    _emit_final(thread_id, turn_id, interrupted=interrupted)


def _control(method: str, path: str, payload: dict | None = None) -> tuple[int, dict]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(f"{CONTROL_BASE}{path}", data=data, method=method)
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read().decode("utf-8") or "{}")


def _wait_for_release(turn_id: str) -> bool | None:
    """轮询控制服务 ✓。`True` = 放行 ✓；`False` = **超时**（一直没放行 ✓）；`None` = **闸门已不存在** ✓。

    **"不存在"与"没放行"必须分开** ✗✓：`cleanGates` 会先放行、再 `reset` ✓，
    而 `reset` 把闸门**删掉** ✗——只认 `released` 的话，"已清理"会被读成"没放行" ✗ →
    空等 60s ✓（实测：一轮用例白等 60s ✓，还把下一条拖成超时 ✓；
    账本里 `timeout … lastPayload {"released": false}` ✓ 而控制服务的动作表里明明有 `release` ✓）。
    """
    deadline = time.time() + RELEASE_TIMEOUT_SECONDS
    status, payload = 0, {}
    _trace("wait_for_release.start", turnId=turn_id, controlBase=CONTROL_BASE)
    while time.time() < deadline:
        status, payload = _control("GET", f"/gates/{turn_id}")
        if status == 200 and payload.get("released"):
            _trace("wait_for_release.released", turnId=turn_id)
            return True
        if status == 200 and payload.get("known") is False:
            _trace("wait_for_release.cleared", turnId=turn_id)
            return None
        time.sleep(0.05)
    # 超时时把**最后一次读数**记下来 ✓✓：是"这个 id 不在名单里" ✗
    # 还是"在、但 released 一直是 false" ✗，两种因的处置完全不同 ✓。
    _trace("wait_for_release.timeout", turnId=turn_id, lastStatus=status, lastPayload=payload)
    return False


def _scenario() -> str:
    """本 run 的场景 ✓（由测试经控制服务设置 ✓；默认 `gate_then_answer` ✓）。"""
    status, payload = _control("GET", f"/runs/{RUN_ID}/scenario")
    if status == 200 and payload.get("scenario"):
        return str(payload["scenario"])
    return "gate_then_answer"


def _scenario_params() -> dict[str, Any]:
    """本 run 的**场景参数** ✓✓（测试喂 ✓）——剧本里替身自己拿不到的数据走这里 ✓。

    最典型的是提案的 `sourceVersionGuard` ✓：它是"会话当前的工作区版本" ✓，
    要经网关/后端才读得到 ✗。缺了它那一轮会被 Java 判 stale ✓，
    看起来像"链路坏了" ✗，其实是剧本没喂参数 ✓。
    """
    status, payload = _control("GET", f"/runs/{RUN_ID}/scenario-params")
    if status == 200 and isinstance(payload.get("params"), dict):
        return payload["params"]
    return {}


def _ask_clarification(thread_id: str, turn_id: str) -> None:
    """发一次"请用户选"的服务端请求 ✓✓——形状照桥那边要的 ✓：

    `item/tool/requestUserInput` + `params.questions[]` ✓（`user_input.py:31/113-120` ✓）。
    桥会把它变成**原生卡** ✓（`clarification.requested` ✓，载荷键见前端白名单 ✓）
    并**等答案** ✓；答案用**原 rpc id** 回 ✓ → 主循环存进 `_answers` ✓ → 这里取用 ✓。
    """
    global _clarify_request_id
    _clarify_request_id += 1
    questions = [{
        "id": "q1",
        "header": "查什么",
        "question": "“计算机”指的是哪一类？（可选项，也可以自己填）",
        # **必须声明 `isOther`** ✓✓：题干自己就写着"也可以自己填" ✓，而桥与卡片都按这条
        # 判据才给自由输入 ✓（`user_input.py:294` ✓、`ClarificationCard.tsx` ✓）——
        # 漏了它，卡上只剩两个选项 ✗（F02 实测就是这么红的 ✓；另一个替身
        # `fake_app_server.py:138` 一直有这一条 ✓，是这里漏了 ✗）。
        "isOther": True,
        "options": [
            {"label": "计算机科学与技术", "description": "专业代码 080901"},
            {"label": "软件工程", "description": "专业代码 080902"},
        ],
    }]
    send({"jsonrpc": "2.0", "id": _clarify_request_id, "method": "item/tool/requestUserInput",
          "params": {"threadId": thread_id, "turnId": turn_id, "questions": questions}})


def _take_answer(request_id: int, timeout: float = 30.0) -> Any:
    deadline = time.time() + timeout
    while time.time() < deadline:
        with _answers_lock:
            if request_id in _answers:
                return _answers.pop(request_id)
        time.sleep(0.05)
    return None


# **"分多条 delta"场景**（2026-10-06 起）✓✓：真实 codex 的增量是**逐字**切的 ✓
#（实测：239 条共 378 字符 ✓），拼接后正好等于终态正文（TurnOutput JSON ✓）。
# 替身按同一口径把**默认终态正文**切成 4 段发 ✓——于是 e2e 能断言：
# ① 闸门放行**前**流式文本已可见 ✓；② 放行后终态**整段替换**、流式文本退场 ✓（不双画 ✓）。
# 网关侧会按 ≥64 字符或 ≥80ms **合并/节流** ✓（`service.py` 的 `_DeltaStreamer` ✓）：
# 首条立即发 ✓，其余在下一个通知（紧随其后的工具进度 / 终态）到达时按序放出 ✓。
_DELTA_FRAGMENTS = (
    '{"responseType": "text", ',
    '"message": "闸门放行后',
    '的答案", ',
    '"executionStatus": "completed"}',
)


def _emit_deltas(thread_id: str, turn_id: str) -> None:
    for fragment in _DELTA_FRAGMENTS:
        send({"jsonrpc": "2.0", "method": "item/agentMessage/delta",
              "params": {"threadId": thread_id, "turnId": turn_id,
                         "itemId": f"msg-{turn_id}", "delta": fragment}})


def _emit_progress(thread_id: str, turn_id: str) -> None:
    send({
        "jsonrpc": "2.0",
        "method": "item/started",
        "params": {
            "threadId": thread_id, "turnId": turn_id,
            "item": {"id": f"progress-{turn_id}", "type": "mcpToolCall", "server": "zhiyuan_domain",
                     "tool": PROGRESS_TOOL, "status": "inProgress",
                     "arguments": {"prompt": "查询测试学校近三年录取位次"}},
        },
    })


def _emit_final(thread_id: str, turn_id: str, *, interrupted: bool) -> None:
    if interrupted:
        send({"jsonrpc": "2.0", "method": "turn/completed",
              "params": {"threadId": thread_id, "turn": {"id": turn_id, "status": "interrupted"}}})
        return
    # 场景 `broken_output`（F15 靶子 ✓）：终态正文**违反契约** ✗——它能被解析 ✓，
    # 但 `responseType` 不在契约的 Literal 里 ✓，而 `message` 里塞了一个泄漏标记 ✓。
    # 这样两条断言才有劲 ✓：① 用户看到的是**可恢复错误** ✓；② 那段原始文本**不许**出现在页面上 ✗——
    # 只造"根本解析不出来"的坏输出 ✗，第 ② 条就会因为"压根没东西可泄"而空转 ✓。
    # 场景 `proposal`（F07/F08 靶子 ✓）：终态正文里带一个**提案草稿** ✓——
    # 形状照 `contracts.py` 的 `ProposalRequest` ✓（"模型产出的语义草稿" ✓，
    # 之后由 Java 的编译器接手 ✓）。这一格要验的是**确认链**（提案 → 待确认 → 确认/取消 ✓），
    # 所以正文必须真的能过契约与编译 ✓，不能只发个像样的字符串 ✗。
    if _scenario() == "proposal":
        params = _scenario_params()
        text = json.dumps(
            {
                # **`responseType` 别写 recommendation** ✗✓：契约的校验器要求
                # "recommendation / review 输出必须带 `artifactRefs`" ✓（实测原文：
                # `Value error, artifactRefs is required for recommendation/review output` ✓）——
                # 而提案是靠 `proposalRequest` 字段承载的 ✓，与响应类型无关 ✓，
                # 所以这里用 `text` 就够 ✓（多写一个 recommendation 只会被整条拒掉 ✗）。
                "responseType": "text",
                "message": "我把这个要求整理成了提案，确认后生效。",
                "executionStatus": "completed",
                "proposalRequest": {
                    "proposalSource": "user_goal",
                    # **必须是"确认链"认得的那两种之一** ✓✓（`fill_to_count` /
                    # `prioritize_within_tier` ✓）——P2 报告 283 行的原话：
                    # 幂等确认链只认这两者 ✓；其余 6 种（含 `exclude_scope` ✗）走的是
                    # **直接应用**那条 ✓——那条**不产生待确认** ✗，于是也就没有 `proposal.preview` ✓
                    # （实测：换成 `exclude_scope` 时整轮成功、却一条 preview 都没有 ✓）。
                    "goalType": "fill_to_count",
                    "userOriginalText": "帮我补足到 80 个志愿",
                    "targetCount": 80,
                    "confidence": "high",
                    # **版本守门值由测试喂** ✓（见 `_scenario_params` 的注释 ✓）。
                    "sourceVersionGuard": int(params.get("sourceVersionGuard") or 0),
                    "negativeScopes": [
                        {
                            "scopeType": "school",
                            "name": "浙江大学",
                            "normalizedName": "浙江大学",
                        }
                    ],
                },
            },
            ensure_ascii=False,
        )
        send({"jsonrpc": "2.0", "method": "item/completed",
              "params": {"threadId": thread_id, "turnId": turn_id,
                         "item": {"id": f"msg-{turn_id}", "type": "agentMessage", "text": text}}})
        send({"jsonrpc": "2.0", "method": "turn/completed",
              "params": {"threadId": thread_id, "turn": {"id": turn_id, "status": "completed"}}})
        return
    # 场景 `score_update`（补录成绩写闭环的靶子 ✓）：终态正文里带一个**补录草稿** ✓——
    # 形状照 `contracts.py` 的 `ScoreUpdateRequest` ✓（"模型产出的语义草稿" ✓：
    # 省份/科类/批次这些**不进草稿** ✓，由 Java 按会话既有成绩合并 ✓；草稿只说用户
    # 这一轮讲了什么 ✓）。与 `proposal` 同一套纪律：正文必须真的能过契约 ✓，
    # 之后由网关 prepare → Java 物化成待确认 ✓——卡片、确认、落库都在那之后 ✓。
    if _scenario() == "score_update":
        params = _scenario_params()
        draft: dict[str, Any] = {
            # 版本守门值由测试喂 ✓（同提案 ✓）：模型看的会话版本必须与快照一致 ✓。
            "sourceVersionGuard": int(params.get("sourceVersionGuard") or 0),
            "userOriginalText": str(params.get("userOriginalText") or "语文118，数学131，英语126，总分641，位次3100"),
        }
        for key in ("totalScore", "totalScorePos", "examYear"):
            if params.get(key) is not None:
                draft[key] = int(params[key])
        if isinstance(params.get("subjectScoreList"), list):
            draft["subjectScoreList"] = params["subjectScoreList"]
        text = json.dumps(
            {
                "responseType": "text",
                "message": "我把这次补录整理好了，确认后写入成绩。",
                "executionStatus": "completed",
                "scoreUpdateRequest": draft,
            },
            ensure_ascii=False,
        )
        send({"jsonrpc": "2.0", "method": "item/completed",
              "params": {"threadId": thread_id, "turnId": turn_id,
                         "item": {"id": f"msg-{turn_id}", "type": "agentMessage", "text": text}}})
        send({"jsonrpc": "2.0", "method": "turn/completed",
              "params": {"threadId": thread_id, "turn": {"id": turn_id, "status": "completed"}}})
        return
    # 场景 `evidence_echo`（"补录确认后的下一轮"靶子 ✓）：终态正文**引用一条证据** ✓，
    # 形状照 2026-10-07 线上事故里模型**实际发出的**那份引用逐字段抄 ✓✓——
    # 只带 `evidenceId`/`sourceLevel`/`dataVersion` 与一个**查询参数** scope ✓，
    # **不带** `sourceSystem`/`paramsDigest` ✓（那是 Java 签发时才有、模型转述时丢掉的 ✓）。
    # 快照里同 ID 的权威记录**带**这两个字段 ✓ → 正是"快照记录 × 模型引用"那一对 ✓。
    # 参数由测试喂（`scenario-params`：evidenceId/dataVersion/message ✓）——替身读不到台账 ✗。
    if _scenario() == "evidence_echo":
        params = _scenario_params()
        ref = {
            "evidenceId": str(params.get("evidenceId") or ""),
            "sourceLevel": "authoritative",
            "dataVersion": str(params.get("dataVersion") or ""),
            "admissionMode": None,
            "admissionUnitId": None,
            "groupCode": None,
            "algorithmVersion": None,
            "stateVersion": None,
            "scope": params.get("scope")
            or {
                "kind": "catalog_batch_options",
                "areaId": "330000",
                "province": "浙江",
                "subjectType": None,
                "batch": "第一段",
                "year": None,
                "majorId": None,
                "schoolId": None,
            },
            "observedAt": params.get("observedAt"),
            "limitations": [],
        }
        text = json.dumps(
            {
                "responseType": "text",
                "message": str(params.get("message") or "补录已经生效，我按已核验过的批次线回答。"),
                "executionStatus": "completed",
                "evidenceRefs": [ref],
            },
            ensure_ascii=False,
        )
        send({"jsonrpc": "2.0", "method": "item/completed",
              "params": {"threadId": thread_id, "turnId": turn_id,
                         "item": {"id": f"msg-{turn_id}", "type": "agentMessage", "text": text}}})
        send({"jsonrpc": "2.0", "method": "turn/completed",
              "params": {"threadId": thread_id, "turn": {"id": turn_id, "status": "completed"}}})
        return
    if _scenario() == "broken_output":
        text = json.dumps(
            {
                "responseType": "bogus_kind",
                "message": f"{LEAK_MARKER} 这段是模型原样输出、不该给用户看",
                "executionStatus": "completed",
            },
            ensure_ascii=False,
        )
        send({"jsonrpc": "2.0", "method": "item/completed",
              "params": {"threadId": thread_id, "turnId": turn_id,
                         "item": {"id": f"msg-{turn_id}", "type": "agentMessage", "text": text}}})
        send({"jsonrpc": "2.0", "method": "turn/completed",
              "params": {"threadId": thread_id, "turn": {"id": turn_id, "status": "completed"}}})
        return
    text = json.dumps({"responseType": "text", "message": "闸门放行后的答案",
                       "executionStatus": "completed"}, ensure_ascii=False)
    send({"jsonrpc": "2.0", "method": "item/completed",
          "params": {"threadId": thread_id, "turnId": turn_id,
                     "item": {"id": f"msg-{turn_id}", "type": "agentMessage", "text": text}}})
    send({"jsonrpc": "2.0", "method": "turn/completed",
          "params": {"threadId": thread_id, "turn": {"id": turn_id, "status": "completed"}}})


def _gated_finish(thread_id: str, turn_id: str) -> None:
    # **场景** ✓：`clarification` = 先要一次澄清 ✓，拿到答案后再等放行 ✓（F02 靶子 ✓）。
    if _scenario() == "clarification":
        _ask_clarification(thread_id, turn_id)
        answer = _take_answer(_clarify_request_id)
        send({"jsonrpc": "2.0", "method": "test/clarification_answered",
              "params": {"turnId": turn_id, "answer": answer}})
    if _scenario() == "broken_output":
        # **这一格不等放行** ✓✓：它要验的是"模型给了坏输出，系统怎么收场" ✓，
        # 与闸门无关 ✗。等着放行会把用例变成"放行时序"的题目 ✓——
        # 实测 F15 就是这么红的：它那一轮**压根没等到放行** ✗，
        # 60s 超时后才以"中断"收尾 ✓，而用例早就在 20s 断言上红了 ✓。
        _finish_once(thread_id, turn_id, interrupted=False)
        return
    outcome = _wait_for_release(turn_id)
    if outcome is None:
        # 闸门**被清掉了** ✓（不是放行 ✗，是 `cleanGates` 的 reset 收走了 ✓）：
        # 立刻按失败态收尾 ✓——再等下去只是白等 60s ✓，而且会把下一条用例拖成超时 ✓。
        _finish_once(thread_id, turn_id, interrupted=True)
        return
    if not outcome:
        # 超时 = **没放行** ✗：先留一条能在大声看见的标记 ✓。
        send({"jsonrpc": "2.0", "method": "test/release_timeout",
              "params": {"turnId": turn_id, "waitedSeconds": RELEASE_TIMEOUT_SECONDS}})
        # **然后仍然把这一轮收尾** ✓✓（用**失败态**，绝不是 completed ✗——任务书 F12 明令
        # "无假 completed" ✓）。为什么必须收尾 ✓：网关那边的回合是跟着它的 App Server 走的 ✓，
        # 若这里静音 ✗，那一轮就**永远关不上** ✓，此后**每条新消息都会被拒**
        #（实测探针原话：`当前回合还在进行，请先等它结束或点停止。` ✓）——
        # 一次超时会把整栈毒住 ✗✗，这是我自己设计"超时即静默"的副作用 ✓。
        _finish_once(thread_id, turn_id, interrupted=True)
        return
    _finish_once(thread_id, turn_id, interrupted=False)


def handle(message: dict) -> None:
    global _turn_counter
    method = message.get("method")
    request_id = message.get("id")
    params = message.get("params") or {}

    if method == "initialize":
        # 形状照抄参照替身 ✓（`fake_app_server.py:186` ✓）：**回显**参数 ✓，
        # 这样测试能断言"客户端到底声明了什么能力" ✓——而不是假定它接受了 ✓。
        send({"jsonrpc": "2.0", "id": request_id,
              "result": {"userAgent": "fake-browser-runtime", "runtimeKind": "fake", "received": params}})
        return
    if method == "initialized":
        return  # 通知 ✓：不需要应答 ✓（参照替身同此 ✓）
    if method == "thread/start":
        # **线程 id 必须跨进程唯一** ✓✓：原来是 `thr_1/thr_2…` ✗——而**绑定表是持久的** ✓
        #（Java 侧按 (租户, 会话, 线程) 存 ✓），替身一重启 id 就从 1 重来 ✗ → 同一个 `thr_1`
        # 被绑到**不同会话**上 ✓ → 后端报 `binding_thread_identity_conflict` ✗ → 网关回
        # `binding_registration_failed` ✗ → 整轮"引擎暂时不可用" ✓。
        # 实测症状很误导：**每轮起栈后的第一条用例必红** ✓（后面几条因为 id 恰好对得上而绿 ✓），
        # 看起来像"首轮有问题" ✗；堆栈与后端日志两处才把它钉死 ✓。
        # 真实 codex 的 thread id 本来就是全局唯一的 ✓——所以这一改是**恢复保真** ✓，
        # 不是给测试打补丁 ✓。
        thread_id = str(params.get("threadId") or f"thr_{os.getpid()}_{len(_threads) + 1}")
        _threads.add(thread_id)
        send({"jsonrpc": "2.0", "id": request_id, "result": {"thread": {"id": thread_id}}})
        return
    if method == "thread/resume":
        thread_id = str(params.get("threadId") or "thr_1")
        # **未知 thread 的 resume：当作新开** ✓✓——并写明为什么这不算放水 ✓：
        #   参照替身对未知 id 回 `thread not found` ✗（那是保真 ✓，A7 那一族的用例要它 ✓）；
        #   但**浏览器合同栈**里，绑定（网关/DB 侧 ✓）比替身进程活得久 ✓——
        #   每次重启隔离栈，替身都是新的 ✓，而旧绑定还在 ✓ → 于是网关一 resume 就失败 ✓，
        #   整轮变成"当前对话引擎暂时不可用" ✗（实测：`thread_resume_failed` ✓）。
        #   那是**环境产物** ✗，不是 C4 要验的行为 ✓——C4 验的是"闸门未放行时终态不许到" ✓✓。
        if thread_id not in _threads:
            _threads.add(thread_id)
            send({"jsonrpc": "2.0", "method": "test/thread_adopted",
                  "params": {"threadId": thread_id}})
        send({"jsonrpc": "2.0", "id": request_id, "result": {"thread": {"id": thread_id}}})
        return
    if method == "turn/start":
        _turn_counter += 1
        thread_id = str(params.get("threadId") or "thr_1")
        _threads.add(thread_id)
        # 客户端（测试构建 ✓）给了回合号就用它 ✓——没有才自己编 ✓。
        turn_id = str(params.get("turnId") or params.get("clientTurnId") or f"turn_{_turn_counter}")
        # 先在控制服务**登记**这个闸门 ✓（reset 才能按 runId 清到它 ✓）。
        register_status, _ = _control("POST", "/gates", {"runId": RUN_ID, "turnId": turn_id})
        # 登记**成不成功**要落账 ✓✓：`_control` 失败时返回的是状态码 ✓，不看就会
        # 变成"登记悄悄丢了 ✗ → 替身空等 60s ✗"，而那看起来像网关的问题 ✗✓。
        _trace("turn_start", threadId=thread_id, turnId=turn_id, runId=RUN_ID,
               counter=_turn_counter, registerStatus=register_status,
               clientTurnId=params.get("turnId") or params.get("clientTurnId"))
        send({"jsonrpc": "2.0", "id": request_id,
              "result": {"turn": {"id": turn_id, "status": "inProgress"}, "received": params}})
        # **分多条**增量（拼接后 = 默认终态正文 ✓）——紧跟其后的工具进度会让网关把
        # 缓冲里的尾部按序放出来 ✓（见 `_DELTA_FRAGMENTS` 的注释 ✓）。
        _emit_deltas(thread_id, turn_id)
        _emit_progress(thread_id, turn_id)
        # **等待必须在后台** ✓：主循环还要继续读 stdin ✓——否则 `turn/interrupt` 永远到不了 ✗
        #（这是测试当场抓出来的真缺陷 ✓，不是测试挑剔 ✓）。
        threading.Thread(target=_gated_finish, args=(thread_id, turn_id), daemon=True).start()
        return
    if method == "turn/interrupt":
        thread_id = str(params.get("threadId") or "thr_1")
        turn_id = str(params.get("turnId") or f"turn_{_turn_counter}")
        send({"jsonrpc": "2.0", "id": request_id, "result": {}})
        _finish_once(thread_id, turn_id, interrupted=True)
        return
    if request_id is not None:
        send({"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": f"method not found: {method}"}})


def main() -> int:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        if message.get("method") is None:
            # 对 server→client 请求的**应答** ✓（澄清的答案就从这里回来 ✓——
            # 客户端用原 rpc id 回 ✓，桥等到了才继续 ✓）。存下来给等待线程取 ✓。
            request_id = message.get("id")
            if isinstance(request_id, int):
                with _answers_lock:
                    _answers[request_id] = message.get("result")
            continue
        handle(message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
