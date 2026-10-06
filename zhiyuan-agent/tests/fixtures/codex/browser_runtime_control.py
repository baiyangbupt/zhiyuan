#!/usr/bin/env python3
"""合同栈的**运行时控制服务**（Task C4）。

它只做三件事 ✓，都是给 e2e 用的：

    GET  /identity               → {"runtimeKind": "fake", ...}
    GET  /gates/{turnId}         → {"released": bool}（假 app-server **轮询**它 ✓）
    POST /gates/{turnId}/release → 放行这一回合的终态 ✓
    POST /runs/{runId}/reset     → **只清本次 runId 的闸门** ✓
    POST /runs/{runId}/rotate-epoch {sessionId} → 换掉该会话的事件代际（F11 靶子 ✓）

三条硬约束 ✓：

1. **只监听 loopback** ✓（`127.0.0.1` ✓）：这个口子能让模型"停"在中间 ✓，
   绝不能对外 ✓（任务书：不开放该端口到 Nginx ✓）。绑不到 127.0.0.1 就拒 ✓。
2. **项目名不代表运行时** ✗（任务书原话 ✓）：真实/假由 `/identity` 的证据判 ✓，
   所以 `runtimeKind` 必须来自**这个服务自己** ✓，不能由被测方传参覆盖 ✓。
3. **reset 只清闸门** ✓：不碰别的状态 ✗（"只清本次闸门" ✓）——它连 run 记录都不删 ✓，
   只把动作记进内存 ✓。
"""

from __future__ import annotations

import argparse
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse

RUNTIME_KIND_FAKE = "fake"
# 存储轮换（F11）要删的两个键在宿主 Redis 上 ✓——默认就是合同栈事件存储那处
# （`redis://127.0.0.1:16379/9` ✓）；换栈时可用环境变量覆盖 ✓。
REDIS_URL = os.environ.get("CODEX_BROWSER_REDIS_URL", "redis://127.0.0.1:16379/9")
# 隔离栈的数据实例 ✓（与 e2e 注入验证码用的是同一个容器 ✓，见 `inject-codex-e2e-sms-code.sh` ✓）。
MYSQL_CONTAINER = os.environ.get("CODEX_BROWSER_MYSQL_CONTAINER", "zhiyuan-codex-local-mysql-1")
# 隔离栈的私有临时目录 ✓（后端读 legacy 志愿数据的地方 ✓ = Spring 配置里的 `temp-data-path` ✓）。
# 由本文件位置推仓库根 ✓（`zhiyuan-agent/tests/fixtures/codex/…` → 上溯 4 层 ✓），
# 不写死绝对路径 ✗；可用环境变量覆盖 ✓。
TEMP_DATA_PATH = Path(
    os.environ.get(
        "CODEX_BROWSER_TEMP_DATA_PATH",
        str(Path(__file__).resolve().parents[4] / ".local" / "codex-local" / "tmp"),
    )
)
CONTROL_HOST = "127.0.0.1"
CONTROL_PORT = 18293

# 后端（Java）内部接口 ✓：铺分数那一格要用它 ✓（inner 接口不校验登录态 ✓，控制服务够得到 ✓）。
BACKEND_ORIGIN = os.environ.get("CODEX_BROWSER_BACKEND_ORIGIN", "http://127.0.0.1:18290")
SCORE_DATA_KEY = "userScoreDetail"


class GateRegistry:
    """闸门状态 ✓（进程内 ✓，只在合同栈用 ✓）。

    `released` 是**一次性的** ✓：放行过就不再拦 ✓（否则同一 turnId 复用会卡住 ✓）；
    `reset` 只清**指定 runId** 的闸门 ✓，其余 run 的状态原样保留 ✓。
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._gates: dict[str, dict[str, Any]] = {}
        self._scenarios: dict[str, str] = {}
        # **场景参数** ✓✓：有些剧本需要测试喂数据 ✓，而替身自己拿不到 ✓——
        # 最典型的是提案的 `sourceVersionGuard` ✓：它是"会话当前的工作区版本" ✓，
        # 要经网关/后端才读得到 ✗。缺了它那一轮会被 Java 判 stale ✓，
        # 看起来像"链路坏了" ✗，其实是剧本没喂参数 ✓。
        self._scenario_params: dict[str, dict[str, Any]] = {}
        self._actions: list[dict[str, Any]] = []

    def reset_session_state(self, session_id: str) -> dict[str, Any]:
        """把某条会话的**规划状态**清干净 ✓✓（提案 / 待确认那一族 ✓）。

        为什么要它 ✓✓：会话在服务端**有状态** ✓（待确认修订号、快照版本 ✓），而"干净会话"
        是这条链的前置 ✓——同一条会话被反复试会把两个计数器写岔 ✓（实测原文：
        `pending revision conflict: current=1 expected=0` ✓），于是**同一个守门值不可能同时成立** ✗
        （喂 1 过前一关、卡后一关 ✓；喂 0 反过来 ✓）。

        只删**给定会话**的行 ✓、只连**隔离栈那个容器** ✓（`zhiyuan-codex-local-mysql-1` ✓——
        与 e2e 注入验证码用的是同一处 ✓）；凭据从 `infra.env` 读 ✓，不写死 ✗。
        """
        import subprocess  # 延迟导入 ✓；与 redis 同理 ✓

        env_file = TEMP_DATA_PATH.parent / "infra.env"
        password = ""
        database = "zhiyuan_codex_local"
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.startswith("MYSQL_ROOT_PASSWORD="):
                password = line.split("=", 1)[1].strip()
            elif line.startswith("MYSQL_DATABASE="):
                database = line.split("=", 1)[1].strip()
        if not password:
            raise RuntimeError(f"读不到 MySQL 口令：{env_file}")
        removed: dict[str, int] = {}
        # **`pending_confirmation` 才是"待确认修订号"的来源** ✗✓（实测：把另外两张清空之后，
        # 编译仍然报 `pending revision conflict: current=1 expected=0` ✓，而它在这张表里还有 1 行 ✓）。
        # **`extra_data` 也要清** ✓✓：候选池/快照就存在它里面 ✓——只清待确认的话，
        # 池子还是从**上一份（未裁剪的）数据**建出来的 ✗ → 求解器照旧撞复杂度上限 ✓
        # （实测：卡出现了 ✓，但状态是"无法执行" ✓、`blockingReasonCodes: ["solver_complexity_limit"]` ✓）。
        for table in (
            "assistant_chat_session_pending_confirmation",
            "assistant_chat_session_extra_data",
            "assistant_planning_pending_command",
            "assistant_conversation_proposal_request",
        ):
            sql = (
                "SET @n := 0; DELETE FROM " + table + " WHERE chat_session_id=" + str(int(session_id)) + "; "
                "SELECT ROW_COUNT() AS removed;"
            )
            try:
                out = subprocess.run(
                    ["docker", "exec", MYSQL_CONTAINER, "mysql", "-uroot", f"-p{password}", "-N", "-e", sql, database],
                    capture_output=True, text=True, timeout=30, check=False,
                )
            except OSError as exc:
                raise RuntimeError(f"docker exec 不可用：{exc}") from exc
            if out.returncode != 0:
                raise RuntimeError(f"清 {table} 失败：{(out.stderr or '').strip()[:200]}")
            removed[table] = int((out.stdout or "0").strip().splitlines()[-1] or 0)
        with self._lock:
            self._actions.append(
                {"action": "reset_session_state", "sessionId": session_id, "removed": removed, "at": time.time()}
            )
        return {"sessionId": session_id, "removed": removed}

    def seed_volunteer(
        self, session_id: str, source_session: str | None = None, max_items: int = 120
    ) -> dict[str, Any]:
        """给某条会话**铺一份 legacy 志愿数据** ✓✓（F07/F08 那条路的前置 ✓）。

        为什么必须铺 ✓：提案编译**先读会话的 legacy 志愿数据** ✓
        （`PlanningStateService.loadLegacyPlanSource → VolunteerBizService.loadOriginalVolunteerData ✓`），
        而本地合成会话没有这类文件 ✗ → 实测就是 `NoSuchBucket` + `legacyPlanImport … 下载志愿数据文件失败` ✓。
        铺上之后它才会走通：实测 `成功加载原始志愿数据 … 17350610 bytes` ✓ + `candidates=6236` ✓。

        为什么归控制服务 ✓：命名规则是 `VolunteerFilePathUtil` 定的
        （`<tempDataPath>/session_volunteer_<id><后缀>.json` ✓），而 `tempDataPath` 在**宿主**上 ✓、
        用例在容器里够不到 ✗——与控制服务已有的 `rotate-epoch` 是同一类分工 ✓。
        """
        import shutil  # 与 redis 一样：延迟导入 ✓，不碰它的用例不该因此起不来 ✓

        temp_dir = TEMP_DATA_PATH
        candidates = sorted(temp_dir.glob("session_volunteer_*.json"), key=lambda p: p.stat().st_size)
        # **"挑最大"必须排掉自己** ✗✓（2026-10-06 踩到 ✓）：补录确认（execute）第 7 步会把
        # **全量志愿数据**落回**本会话自己的**文件 ✓（`persistSourceData` ✓，实测它比基准源
        # 900036（17MB）还大 ✓）→ 再跑同一会话时"挑最大"就挑到自己 ✓；而 reset 刚删掉本会话
        # 的成绩 ✓ → 拷贝成绩那步 `源会话没有可用的 userScoreDetail` ✗ → 基线铺不上、
        # 用例在打点处就红 ✓（实测一轮 ✓）。源只能来自**别的**会话 ✓。
        own_file_name = f"session_volunteer_{session_id}.json"
        if source_session:
            source = temp_dir / f"session_volunteer_{source_session}.json"
        else:
            candidates = [path for path in candidates if path.name != own_file_name]
            if candidates:
                # 默认挑**最大**的那份 ✓：village 数据越大，候选池越足 ✓（实测 17MB → 6236 候选 ✓）。
                source = candidates[-1]
            else:
                raise FileNotFoundError(f"没有可用的志愿数据源：{temp_dir}")
        if not source.exists():
            raise FileNotFoundError(f"源文件不存在：{source}")
        target = temp_dir / f"session_volunteer_{session_id}.json"
        items = 0
        # **幂等且总是写"裁剪后"的那份** ✓✓：不这样，早先手工铺过的大文件会留着 ✗ →
        # 求解器撞复杂度上限 ✓ → 提案 `blocked` ✗ → 卡上是"无法执行" ✓（用例就断言不到"待确认" ✓）。
        if True:
            # **要裁小** ✓✓：源文件是 17MB / 6236 条 ✓，原样铺进去求解器会撞复杂度上限 ✗——
            # 实测 Java 回 `blockingReason: canonical solver 输入超过 M1 受控复杂度上限` ✓，
            # 于是提案是 `status: blocked` ✗：链路通、却拿不到**可确认**的提案 ✓。
            with source.open(encoding="utf-8") as handle:
                data = json.load(handle)
            detail_list = data.get("detailList") if isinstance(data, dict) else None
            if isinstance(detail_list, list) and max_items > 0 and len(detail_list) > max_items:
                data["detailList"] = detail_list[:max_items]
            if isinstance(data, dict) and isinstance(data.get("detailList"), list):
                items = len(data["detailList"])
            target.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        # **分数也一起铺** ✓：志愿数据文件与 `userScoreDetail` 是同一个源 ✓——只铺一半的话
        # 编译能过 ✓、确认那一步才 404 ✗（"卡显示未生效" ✓，看上去像链路坏了 ✗）。
        source_session_id = source.stem.replace("session_volunteer_", "", 1)
        try:
            score: dict[str, Any] = self._seed_score_extra_data(session_id, source_session_id)
        except Exception as exc:  # noqa: BLE001 —— 铺不上要**看得见** ✓（记账 ✓ + 回包里带出来 ✓），
            # 但别把"文件铺好了"这件事一起吞掉 ✗（那条是能单独验的 ✓）。
            score = {"source": source_session_id, "error": str(exc)[:300]}
        with self._lock:
            self._actions.append(
                {
                    "action": "seed_volunteer",
                    "sessionId": session_id,
                    "from": source.name,
                    "bytes": target.stat().st_size,
                    "items": items,
                    "score": score,
                    "at": time.time(),
                }
            )
        return {
            "sessionId": session_id,
            "from": source.name,
            "bytes": target.stat().st_size,
            "items": items,
            "score": score,
        }

    def _seed_score_extra_data(self, session_id: str, source_session_id: str) -> dict[str, Any]:
        """把**源会话**的 `userScoreDetail` 原样搬给目标会话 ✓（F07/F08 的**第二条**前置 ✓）。

        为什么必须铺 ✗：确认（apply）那条路会**重新求解** ✓，而 Java 的
        `VolunteerDataProvider.getUserScoreDetail`（:52-58 ✓）在会话缺
        `ChatSessionExtraDataConstants.USER_SCORE_KEY`（库里就是 `userScoreDetail` ✓）时
        **直接 404** `用户分数信息不存在` ✗——2026-09-27 真栈实测：canonical 元数据那关过了之后
        紧接着就是它 ✓，卡上照样只是"未生效" ✗。
        本地合成会话**没有这一行** ✗（实测 900018 的 extra data 只有 `planningState` ✓），
        而志愿数据文件正是从源会话拷来的 ✓ → 分数也照**同一个源**拷 ✓，省份/选科才对得上 ✓
        （分数与志愿数据省份不一致会变成"候选全被过滤" ✗，那是更难查的一种红 ✓）。

        走内部接口 ✓：读 `get-extra-data` ✓ / 写 `add-extra-data` ✓——两个都是 inner ✓、
        不需要登录态 ✓；形状对齐库里既有行 ✓（`dataType=JSON_OBJECT` ✓、`version=0` ✓）。
        端点与用法：`docs/release-3.1.0-production-session-sampling.md:44` ✓、
        `docs/superpowers/tasks/P2-write-closed-loop/REPORT.md:218` ✓。
        """
        import urllib.request  # 延迟导入 ✓：不铺分数的用例不必多一个依赖 ✓

        base = BACKEND_ORIGIN.rstrip("/")
        read_url = (
            f"{base}/gaotu-assistant-bot/inner/chat/1/session/get-extra-data"
            f"?chatSessionId={source_session_id}&keyList={SCORE_DATA_KEY}&version=0"
        )
        with urllib.request.urlopen(read_url, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
        raw = (payload.get("data") or {}).get(SCORE_DATA_KEY)
        # **读回来的是 JSON 串** ✓（库里存的就是文本 ✓）——原样解析再原样写回 ✓，不重编形状 ✓。
        value = json.loads(raw) if isinstance(raw, str) and raw.strip() else raw
        if not isinstance(value, dict) or not value:
            raise ValueError(f"源会话没有可用的 {SCORE_DATA_KEY}：{source_session_id}")
        body = json.dumps(
            {
                "chatSessionId": int(session_id) if str(session_id).isdigit() else session_id,
                "dataKey": SCORE_DATA_KEY,
                "dataType": "JSON_OBJECT",
                "dataValue": value,
                "version": 0,
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            f"{base}/gaotu-assistant-bot/inner/chat/1/session/add-extra-data",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=15) as response:
            json.loads(response.read().decode("utf-8"))
        return {
            "source": source_session_id,
            "province": (value.get("province") or {}).get("name")
            if isinstance(value.get("province"), dict)
            else value.get("province"),
            "totalScore": value.get("totalScore") or value.get("total_score"),
        }

    def rotate_epoch(self, session_id: str, tenant_id: str = "1") -> dict[str, Any]:
        """把某条会话的**事件代际换掉**（F11 靶子 ✓）：删掉 `seq` 与 `epoch` 两个键 ✓——
        下一次追加会由存储脚本生成**新的随机代际** ✓、序号从 1 重新开始 ✓。

        为什么这件事归控制服务 ✓：用例跑在容器里 ✗、够不到宿主 Redis ✗；而控制服务就在宿主上 ✓、
        又跑在测试 venv 里 ✓（`redis` 包在 ✓）。这是"存储轮换了"**唯一**能从测试侧触发的口子 ✓，
        所以它待在控制服务里是分工 ✓，不是塞私货 ✓。
        """
        import redis  # 延迟导入：不碰 Redis 的用例不该因为缺包而起不来 ✓

        tag = f"{{{tenant_id}:{session_id}}}"
        client = redis.Redis.from_url(REDIS_URL, socket_connect_timeout=3)
        try:
            removed = int(client.delete(f"conv:{tag}:seq", f"conv:{tag}:epoch") or 0)
        finally:
            client.close()
        with self._lock:
            self._actions.append(
                {"action": "rotate_epoch", "sessionId": session_id, "removed": removed, "at": time.time()}
            )
        return {"sessionId": session_id, "removedKeys": removed}

    def register(self, run_id: str, turn_id: str) -> None:
        with self._lock:
            self._gates.setdefault(turn_id, {"runId": run_id, "released": False})

    def release(self, turn_id: str) -> bool:
        with self._lock:
            gate = self._gates.get(turn_id)
            if gate is None:
                return False
            gate["released"] = True
            self._actions.append({"action": "release", "turnId": turn_id, "at": time.time()})
            return True

    def is_released(self, turn_id: str) -> bool:
        with self._lock:
            gate = self._gates.get(turn_id)
            return bool(gate and gate["released"])

    def reset_run(self, run_id: str) -> int:
        """**只清这个 run 的闸门** ✓，返回清掉的条数 ✓。"""
        with self._lock:
            doomed = [key for key, gate in self._gates.items() if gate.get("runId") == run_id]
            for key in doomed:
                self._gates.pop(key, None)
            self._actions.append({"action": "reset", "runId": run_id, "cleared": len(doomed), "at": time.time()})
            return len(doomed)

    # ── 场景（Task C4 的 F02/F07/… 要按 case 驱动替身"演什么" ✓）──────────────────
    # 为什么不写进 env 而要放服务里 ✓：**测试可以在用例中途换场景** ✓✓
    #（比如"先要一次澄清，再正常收尾" ✓），而 env 是连接时就定死的 ✗。
    def set_scenario(self, run_id: str, name: str) -> None:
        with self._lock:
            self._scenarios[run_id] = name
            self._actions.append({"action": "set_scenario", "runId": run_id, "scenario": name, "at": time.time()})

    def scenario(self, run_id: str) -> str:
        with self._lock:
            return self._scenarios.get(run_id, "gate_then_answer")

    def set_scenario_params(self, run_id: str, params: Mapping[str, Any] | None) -> dict[str, Any]:
        with self._lock:
            self._scenario_params[run_id] = dict(params or {})
            self._actions.append(
                {
                    "action": "set_scenario_params",
                    "runId": run_id,
                    "keys": sorted(self._scenario_params[run_id].keys()),
                    "at": time.time(),
                }
            )
            return dict(self._scenario_params[run_id])

    def scenario_params(self, run_id: str) -> dict[str, Any]:
        with self._lock:
            return dict(self._scenario_params.get(run_id, {}))

    def actions(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._actions)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {key: dict(gate) for key, gate in self._gates.items()}


def build_handler(registry: GateRegistry) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args: Any) -> None:  # 静音：e2e 日志里不需要每题一行的访问日志 ✓
            return

        def _send(self, status: int, payload: Mapping[str, Any]) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802 —— http.server 的接口名 ✓
            path = urlparse(self.path).path
            if path == "/identity":
                # 证据由服务自己给 ✓：`runtimeKind` 不接受外部覆盖 ✗。
                self._send(200, {"runtimeKind": RUNTIME_KIND_FAKE, "controlPort": CONTROL_PORT})
                return
            if path.startswith("/gates/"):
                turn_id = path[len("/gates/"):]
                # **"不存在"要说出来** ✓✓：`cleanGates` 会先放行、再 reset ✓，而 reset 把闸门**删掉** ✗——
                # 只回 `released: false` 的话，替身把"已清理"读成"没放行" ✗ → 空等 60s ✓
                #（实测：一轮用例因此白等 60s ✓，还把下一条拖成超时 ✓）。
                snapshot = registry.snapshot()
                self._send(
                    200,
                    {
                        "turnId": turn_id,
                        "known": turn_id in snapshot,
                        "released": registry.is_released(turn_id),
                    },
                )
                return
            if path.startswith("/runs/") and path.endswith("/scenario-params"):
                run_id = path[len("/runs/"):-len("/scenario-params")]
                self._send(
                    200,
                    {"runId": run_id, "params": registry.scenario_params(run_id)},
                )
                return
            if path.startswith("/runs/") and path.endswith("/scenario"):
                run_id = path[len("/runs/"):-len("/scenario")]
                self._send(200, {"runId": run_id, "scenario": registry.scenario(run_id)})
                return
            if path == "/gates":
                self._send(200, {"gates": registry.snapshot(), "actions": registry.actions()})
                return
            self._send(404, {"error": "not_found", "path": path})

        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            try:
                payload = json.loads(raw.decode("utf-8") or "{}")
            except json.JSONDecodeError:
                self._send(400, {"error": "invalid_json"})
                return
            path = urlparse(self.path).path
            if path.startswith("/gates/") and path.endswith("/release"):
                turn_id = path[len("/gates/"):-len("/release")]
                if not registry.release(turn_id):
                    self._send(404, {"error": "unknown_turn", "turnId": turn_id})
                    return
                self._send(200, {"turnId": turn_id, "released": True})
                return
            if path == "/gates":
                registry.register(str(payload.get("runId") or ""), str(payload.get("turnId") or ""))
                self._send(200, {"registered": True})
                return
            if path.startswith("/runs/") and path.endswith("/scenario-params"):
                run_id = path[len("/runs/"):-len("/scenario-params")]
                params = payload if isinstance(payload, Mapping) else {}
                self._send(200, {"runId": run_id, "params": registry.set_scenario_params(run_id, params)})
                return
            if path.startswith("/runs/") and path.endswith("/scenario"):
                run_id = path[len("/runs/"):-len("/scenario")]
                name = str(payload.get("scenario") or "").strip() or "gate_then_answer"
                registry.set_scenario(run_id, name)
                self._send(200, {"runId": run_id, "scenario": name})
                return
            if path.startswith("/runs/") and path.endswith("/reset-session"):
                session_id = str(payload.get("sessionId") or "")
                if not session_id:
                    self._send(400, {"error": "missing_session_id"})
                    return
                try:
                    result = registry.reset_session_state(session_id)
                except (RuntimeError, ValueError) as exc:
                    self._send(500, {"error": "reset_failed", "detail": str(exc)[:200]})
                    return
                self._send(200, result)
                return
            if path.startswith("/runs/") and path.endswith("/seed-volunteer"):
                session_id = str(payload.get("sessionId") or "")
                if not session_id:
                    self._send(400, {"error": "missing_session_id"})
                    return
                try:
                    result = registry.seed_volunteer(
                        session_id,
                        str(payload.get("from") or "") or None,
                    )
                except FileNotFoundError as exc:
                    self._send(404, {"error": "no_source", "detail": str(exc)})
                    return
                self._send(200, result)
                return
            if path.startswith("/runs/") and path.endswith("/rotate-epoch"):
                session_id = str(payload.get("sessionId") or "")
                if not session_id:
                    self._send(400, {"error": "missing_session_id"})
                    return
                self._send(
                    200,
                    registry.rotate_epoch(session_id, str(payload.get("tenantId") or "1")),
                )
                return
            if path.startswith("/runs/") and path.endswith("/reset"):
                run_id = path[len("/runs/"):-len("/reset")]
                cleared = registry.reset_run(run_id)
                self._send(200, {"runId": run_id, "cleared": cleared})
                return
            self._send(404, {"error": "not_found", "path": path})

    return Handler


def serve(host: str = CONTROL_HOST, port: int = CONTROL_PORT) -> ThreadingHTTPServer:
    """起控制服务 ✓——**只认 loopback** ✓（传别的地址直接拒 ✗）。"""
    if host != CONTROL_HOST:
        raise ValueError("控制服务只允许监听 %s（它能把模型停在中间 ✗，绝不能对外 ✓）" % CONTROL_HOST)
    registry = GateRegistry()
    server = ThreadingHTTPServer((host, port), build_handler(registry))
    server.registry = registry  # type: ignore[attr-defined]
    return server


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Browser-runtime control service (Task C4).")
    parser.add_argument("--host", default=CONTROL_HOST)
    parser.add_argument("--port", type=int, default=CONTROL_PORT)
    args = parser.parse_args(argv)
    server = serve(args.host, args.port)
    print(json.dumps({"control": "listening", "host": args.host, "port": args.port, "runtimeKind": RUNTIME_KIND_FAKE}))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
