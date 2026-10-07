from __future__ import annotations

import asyncio
import hashlib
import html
import json
import re
from datetime import datetime
from typing import Any

from app.admission.facts import (
    AdmissionFactError,
    canonical_admission_mode,
    validate_admission_fact,
)
from app.admission.tool_results import KIND_HISTORY, normalize_history
from app.harness.binding import BindingError, ThreadBinding
from app.mcp_server.response import SCHEMA_VERSION, error, ok
from app.util import internal_client


CAPABILITIES = {
    "entity.resolve": "catalog_read",
    "catalog.search_schools": "catalog_read",
    "catalog.get_school": "catalog_read",
    "catalog.search_majors": "catalog_read",
    "catalog.get_major": "catalog_read",
    "admission.get_current_plan": "admission_read",
    # 新名与旧名指向**同一个实现**：保留两套语义会让"到底哪份是草案"
    # 变成一个靠文档回答的问题。旧名只作一个发布周期的兼容。
    "planning.get_working_plan": "admission_read",
    "admission.get_history": "admission_read",
    "admission.check_eligibility": "admission_read",
    # 同口径并列。存在的理由是**口径一致性只能在这里强制**：
    # 让模型自己调 N 次 get_history 再并列，"这两列是不是同一口径"就没人管了，
    # 而跨年/跨批次的数字并排放进一张表，读者会以为它们可比。
    "admission.compare": "admission_read",
    # 批次字典：**没有它，"录取分"这条路根本走不通**。批次码是地区相关的
    # （浙江第一段=17、上海本科批=01），传"本科批"这种名字上游不报错、只返回空。
    "catalog.list_batches": "catalog_read",
    # 补录编码表：**没有它，"对话式补录"出的卡就是一张废卡**。2026-10-06 真事故：
    # 模型手里只有分数，把 subjectScoreList 出成 [{"score":88},…]（无科目编码），
    # 合并后 null 编码一路炸到下游；批次同理（"本科批"不是批次码）。
    # 模型补录前先查这两张表，用返回的 code 出草稿。
    "catalog.get_batch_options": "catalog_read",
    "catalog.get_subject_options": "catalog_read",
    # 一分一段（分数 → 位次）：用户报"我 610 分"但没报位次时的唯一合法来源。
    # 位次是区间（同分不可分辨），"大概多少名"以前只能靠模型自己算或干脆不答。
    "catalog.get_score_position": "catalog_read",
    # 招生单元树：专业级那条链的入口，**免分数**。没有它，招生计划与专业级录取都无门可入。
    "catalog.list_admission_units": "catalog_read",
    "admission.get_enrollment_plan": "admission_read",
    # 招生章程（招生简章全文）。**免分数**，而且是"原文条款"那条来源——
    # 与 getSchoolRule（录取规则摘要，回占位文案）不是一回事。
    "admission.get_charter": "admission_read",
    # 候选预览：只读的候选纵切（推荐 → 成形 → 一页样例）。
    # 挂在既有 `admission_read` 上而不是新造能力名：Java 侧
    # `ConversationSnapshotService.fillCapabilities` 只签发 catalog_read /
    # admission_read 两种能力，新名字在真实回合里会被**全部拒绝**——
    # 工具注册了却谁也调不到，比不注册更坏。候选属于"志愿/录取"域，
    # admission_read 是它的现役归属。
    "recommendation.preview_candidates": "admission_read",
}
WRITE_TOOL_NAMES = frozenset(
    {
        "profile.propose_patch",
        "plan.propose_changes",
        "plan.propose_finalize",
        "plan_apply",
    }
)



# 工具 → 数据种类。外层统一，内容按 kind 分型：把历史分数当录取概率、
# 把学校口径的率当专业组的，都是这一层要防的事。
TOOL_KINDS = {
    "entity.resolve": "catalog",
    "catalog.search_schools": "catalog",
    "catalog.get_school": "catalog",
    "catalog.search_majors": "catalog",
    "catalog.get_major": "catalog",
    "admission.get_history": "history",
    "admission.check_eligibility": "eligibility",
    "admission.get_current_plan": "workingPlan",
    "planning.get_working_plan": "workingPlan",
    "admission.compare": "comparison",
    "catalog.list_batches": "catalog",
    # 补录编码表：字典/枚举，形状是 catalog（不是观测事实，批次线证据挂在批次查询上）。
    "catalog.get_batch_options": "catalog",
    "catalog.get_subject_options": "catalog",
    # 一分一段：一份**按省的统计表**（不是某个考生的名次），形状同样是 catalog。
    "catalog.get_score_position": "catalog",
    "catalog.list_admission_units": "catalog",
    "admission.get_enrollment_plan": "enrollment",
    "admission.get_charter": "policy",
    "recommendation.preview_candidates": "candidate",
}


def _kind_for(name: str) -> str:
    return TOOL_KINDS.get(name, "catalog")


def _ok(name: str, data: Any, **kwargs: Any) -> dict[str, Any]:
    return ok(data, kind=_kind_for(name), **kwargs)


def _err(name: str, status: str, message: str, **kwargs: Any) -> dict[str, Any]:
    return error(status, message, kind=_kind_for(name), **kwargs)


def _as_int(value: Any) -> int | None:
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return None


def _as_float(value: Any) -> float | None:
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


def _html_to_text(value: str) -> str:
    """把章程正文的 HTML 转成纯文本。

    模型要的是**条款文字**，不是标签；`<p>`/`<span style=...>` 会白占预算。
    实体与 `&nbsp;` 也要解掉——否则"第一章 &nbsp;总 &nbsp;则"会被原样抄进回答。
    """
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", value, flags=re.S | re.I)
    # **块级结束标签要换成换行**，不能直接删掉：章程一条一段，删了标签段落就连成
    # 一片（实测"第一章 总则第一条 为深入贯彻…"），条款边界没了，引用时也没法定位。
    text = re.sub(r"<\s*(br|/p|/div|/li|/tr|/h[1-6])\s*/?\s*>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text).replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n{2,}", "\n", text).strip()


def _flatten_unit_tree(tree: Any) -> list[dict[str, Any]]:
    """把四层嵌套（年份→科类→批次→单元）摊平成行。

    层与层用的是同一个形状，所以按**深度**认层：0=年份、1=科类、2=批次、3=招生单元。
    层名是位置决定的，不是字段名决定的——上游在这四层里用的字段名完全一样。
    """
    rows: list[dict[str, Any]] = []

    def walk(nodes: Any, path: list[tuple[str, str]]) -> None:
        if not isinstance(nodes, list):
            return
        for node in nodes:
            if not isinstance(node, dict):
                continue
            value = str(node.get("value") or "")
            label = str(node.get("label") or "")
            if len(path) >= 3:
                # **value 与 label 都要带出去**：value 是拿来查的（科类 WL/LS/N、
                # 批次 17/01），label 是拿来跟用户说话的（物理/历史、第一段/本科批）。
                # 只带 value，模型说话时只能念代码；只带 label，它拿去查询就查空
                # ——实测江苏传中文"物理"返回 0 行，而上游并不报错。
                rows.append(
                    {
                        "year": path[0][0],
                        "yearLabel": path[0][1],
                        "subjectType": path[1][0],
                        "subjectLabel": path[1][1],
                        "batch": path[2][0],
                        "batchLabel": path[2][1],
                        "schoolUnitId": value,
                        "schoolUnitCode": str(node.get("code") or ""),
                        "schoolLabel": label,
                    }
                )
                continue
            walk(node.get("children"), [*path, (value, label)])

    walk(tree, [])
    return rows


def _clean_score(raw: Any, fallback: str) -> str:
    """上游一分一段的分数是四位小数字符串（"610.0000"）；给人看的形状是 610
    ——与 Java 侧 `ScoreCatalogService.parseScore` 同一口径。取不到就回落调用方给的分数。
    """
    text = str(raw or "").strip()
    if not text:
        return fallback
    try:
        value = float(text)
    except ValueError:
        return text
    cleaned = f"{value:.4f}".rstrip("0").rstrip(".")
    return cleaned or fallback


def _pick_comparison_row(rows: list[Any], year: int) -> dict[str, Any] | None:
    """挑出**请求年份**那一行；没有就取最新一年。

    取最新一年是有意为之：它让实体的 `admissionYear` 与请求口径不一致，
    于是 Java 那边按"口径不一致 → 整列不可比"处理。悄悄拿另一年的数字顶上，
    才是真正危险的做法。
    """
    candidates = [row for row in rows if isinstance(row, dict)]
    if not candidates:
        return None
    for row in candidates:
        if _as_int(row.get("year")) == year:
            return row
    return max(candidates, key=lambda row: _as_int(row.get("year")) or 0)


def _write_refusal_message(mode: str) -> str:
    """写工具被拒时**告诉模型怎么做才行**，而不是让它自己试出来（P2 任务书 §一）。

    新链路的写路径是「模型出 `proposalRequest` → Java 编译出 pending → 用户确认 →
    确认链（pending/resolve → pending-command/execute）执行」——模型**始终没有可调的写工具**。
    模式（`MCP_MODE`）只决定这段话怎么说：
    - `write`：指向合法出口（提案），让模型知道"想写就这么做"；
    - 其它（默认只读）：说明这台实例的写路径没活着，别在这里试。
    """
    if mode == "write":
        return (
            "写操作不通过工具执行：请用 proposalRequest 出提案（说明对象、变更和影响），"
            "用户确认后由确认链执行。"
        )
    return "本实例只读：写操作不可用（写路径只在写实例上活着）。"


class ReadonlyDomainTools:
    def __init__(
        self,
        binding: ThreadBinding,
        *,
        backend: Any,
        current_state_version: int = 42,
        max_calls: int = 8,
        backend_timeout: float = 5.0,
        mode: str = "readonly",
    ) -> None:
        self.binding = binding
        self.backend = backend
        self.current_state_version = current_state_version
        # `readonly` / `write`：只影响**写工具被拒时怎么解释**（工具面本身不变——
        # 写路径是提案/确认链，不是给模型一把写枪；P2 报告第三节堵点 2 的结论）。
        self.mode = mode
        self.max_calls = max_calls
        self.backend_timeout = backend_timeout
        self.calls = 0
        self._cache: dict[str, dict[str, Any]] = {}

    async def call(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        arguments = arguments or {}
        if name in WRITE_TOOL_NAMES:
            return _err(name, "capability_denied", _write_refusal_message(self.mode), state_version=self.current_state_version)
        if name not in CAPABILITIES:
            return _err(name, "tool_not_found", name, state_version=self.current_state_version)
        requested_mode: str | None = None
        if name.startswith("admission."):
            raw_mode = arguments.get("admissionMode", arguments.get("admission_mode"))
            try:
                requested_mode = canonical_admission_mode(
                    self.binding.admission_mode if raw_mode in (None, "") else raw_mode
                )
            except AdmissionFactError as exc:
                return _err(name, exc.code, "unsupported admission mode", state_version=self.current_state_version)
            if requested_mode != self.binding.admission_mode:
                return _err(name, 
                    "admission_mode_mismatch",
                    "requested admission mode differs from trusted session mode",
                    state_version=self.current_state_version,
                    admission_mode=self.binding.admission_mode,
                )
            arguments = dict(arguments)
            arguments["admissionMode"] = requested_mode
        requested_version = arguments.get("stateVersion")
        if requested_version is not None:
            try:
                requested_version = int(requested_version)
            except (TypeError, ValueError):
                return _err(name, "invalid_state_version", "stateVersion must be an integer", state_version=self.current_state_version)
            if requested_version != self.current_state_version:
                return _err(name, "stale_state", "stateVersion is stale", state_version=self.current_state_version)
        try:
            required_capability = CAPABILITIES[name]
            if required_capability in self.binding.allowed_capabilities:
                self.binding.authorize(required_capability)
            elif name in self.binding.allowed_capabilities:
                self.binding.authorize(name)
            else:
                raise BindingError("capability_denied")
        except BindingError as exc:
            return _err(name, exc.code, str(exc), state_version=self.current_state_version)
        cache_key = hashlib.sha256(
            json.dumps(
                [name, arguments, self.binding.admission_mode, self.current_state_version],
                sort_keys=True,
                ensure_ascii=False,
            ).encode()
        ).hexdigest()
        if cache_key in self._cache:
            return self._cache[cache_key]
        if self.calls >= self.max_calls:
            return _err(name, "call_budget_exceeded", "readonly tool call budget exceeded", state_version=self.current_state_version)
        if name == "admission.get_history":
            # **不要求 majorId / groupCode**。上游按"`majorId` 是否非空"分流：
            # 非空 → 专业级表（`z_enroll_major_data`，实测该省分数多为 0）；
            # 空 → 院校/**专业组**级表（投档线就在这里，实测有真分数）。
            # 以前在 major 模式下强制要求 majorId，等于**把唯一能返回数据的查法
            # 挡在门外**：模型收到 `needs_clarification: majorId`，而它问的那条
            # 本来查得到（北大浙江第一段 707 分 / 位次 2）。
            required = {"areaId", "batch", "schoolId", "year", "subjectType"}
            missing = sorted(key for key in required if arguments.get(key) in (None, ""))
            if missing:
                result = _err(name, 
                    "needs_clarification",
                    f"missing history scope: {', '.join(missing)}",
                    state_version=self.current_state_version,
                )
                result["data"]["missingFields"] = missing
                return result
        self.calls += 1
        try:
            result = await asyncio.wait_for(self._dispatch(name, arguments), timeout=self.backend_timeout)
        except Exception as exc:
            # One retry is reserved for transient backend failures.
            try:
                result = await asyncio.wait_for(self._dispatch(name, arguments), timeout=self.backend_timeout)
            except Exception as retry_exc:
                return _err(name, "backend_unavailable", str(retry_exc or exc), state_version=self.current_state_version)
        envelope = self._envelope(name, result)
        self._cache[cache_key] = envelope
        return envelope

    async def _dispatch(self, name: str, arguments: dict[str, Any]) -> Any:
        if self.backend is None:
            raise RuntimeError("backend unavailable")
        if name == "catalog.search_schools":
            resolved = await self.backend.resolve(query=arguments.get("query", ""), entity_type="school")
            if isinstance(resolved, dict) and resolved.get("status") == "needs_clarification":
                return resolved
            return await self.backend.search_schools(**self._trusted_arguments(arguments))
        if name == "catalog.search_majors":
            resolved = await self.backend.resolve(query=arguments.get("query", ""), entity_type="major")
            # `resolve` 的"没有唯一实体"是以 **None** 回来的（Java 侧
            # `resultType=empty` → `data=null`），不是 dict。这里曾经直接
            # `resolved.get(...)`，于是"计算机"这种俗称——目录里没有同名专业，
            # 恰恰是最常见的一类输入——会让工具抛
            # `AttributeError: 'NoneType' object has no attribute 'get'`，
            # 再被包成 `backend_unavailable`。用户读到的结论是"后端不可用"，
            # 而后端是好的、检索接口本来就会给出多个候选。
            # `catalog.search_schools` 那一支早就判了 isinstance，这一支漏了。
            if isinstance(resolved, dict) and resolved.get("status") == "needs_clarification":
                return resolved
            return await self.backend.search_majors(**self._trusted_arguments(arguments))
        if name == "catalog.list_admission_units":
            return await self.backend.list_admission_units(**self._trusted_arguments(arguments))
        if name == "admission.get_charter":
            return await self.backend.get_charter(**self._trusted_arguments(arguments))
        if name == "admission.get_enrollment_plan":
            return await self.backend.get_enrollment_plan(**self._trusted_arguments(arguments))
        if name == "catalog.list_batches":
            return await self.backend.list_batches(**self._trusted_arguments(arguments))
        if name == "catalog.get_batch_options":
            return await self.backend.get_batch_options(**self._trusted_arguments(arguments))
        if name == "catalog.get_subject_options":
            return await self.backend.get_subject_options(**self._trusted_arguments(arguments))
        if name == "catalog.get_score_position":
            return await self.backend.get_score_position(**self._trusted_arguments(arguments))
        if name == "admission.compare":
            # 不在这里 resolve：对比的实体是**已确认**的院校/专业（调用方给 ID），
            # 歧义应当在进入对比之前就解决掉，否则表格里会出现"同一个名字的两个东西"。
            return await self.backend.compare(**self._trusted_arguments(arguments))
        if name == "recommendation.preview_candidates":
            # 只收过滤与分页；tenant/session 由受信 binding 注入——
            # `_trusted_arguments` 会把模型塞的 tenantId/sessionId 全部丢掉。
            return await self.backend.preview_candidates(**self._trusted_arguments(arguments))
        method = {
            "entity.resolve": "resolve",
            "catalog.get_school": "get_school",
            "catalog.get_major": "get_major",
            "admission.get_current_plan": "get_current_plan",
            "planning.get_working_plan": "get_current_plan",
            "admission.get_history": "get_history",
            "admission.check_eligibility": "check_eligibility",
        }[name]
        return await getattr(self.backend, method)(**self._trusted_arguments(arguments))

    def _trusted_arguments(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in arguments.items() if key not in {"threadId", "tenantId", "sessionId", "userId", "handle", "stateVersion"}}

    # 走"事实/证据配对"那条路的工具。按**名字前缀**判断是错的：
    # `planning.get_working_plan` 是 `admission.get_current_plan` 的新名，
    # 前缀不同却走同一个实现，于是同一个工具因名字不同给出两种结果形状。
    # 用显式集合，别名不可能再分叉。
    _ADMISSION_SHAPED_TOOLS = frozenset(
        {
            "admission.get_current_plan",
            "admission.get_history",
            "admission.check_eligibility",
            "planning.get_working_plan",
        }
    )

    def _envelope(self, name: str, result: Any) -> dict[str, Any]:
        if name in self._ADMISSION_SHAPED_TOOLS:
            return self._admission_envelope(name, result)
        if isinstance(result, dict):
            evidence = list(result.get("evidence") or [])
            if any(
                item.get("threadId") not in (None, self.binding.thread_id)
                for item in evidence
                if isinstance(item, dict)
            ):
                return _err(name, 
                    "evidence_scope_violation",
                    "evidence belongs to another thread",
                    state_version=self.current_state_version,
                )
            limitations = list(result.get("limitations") or [])
            entities = list(result.get("resolvedEntities") or [])
            if result.get("status") and "data" in result:
                status = str(result["status"])
                if status != "ok":
                    return {
                        "status": status,
                        "data": result.get("data") or {},
                        "resolvedEntities": entities,
                        "evidence": evidence,
                        "limitations": limitations,
                        "stateVersion": self.current_state_version,
                    }
                return _ok(name, 
                    result.get("data"),
                    state_version=self.current_state_version,
                    evidence=evidence,
                    entities=entities,
                    limitations=limitations,
                )
            # 这里曾经在无证据时自铸一条 `ev-{name}` / sourceLevel=authoritative。
            # 权威只能由签发方声明：自铸的 ID 让"有证据"变成永远为真，
            # 于是下游那些"必须引用证据"的检查从来没做过判定。
            # 现在无证据就是无证据——数据仍可作为**候选**返回，但不能被当成
            # 已核验的权威事实展示。
            return _ok(name, 
                result,
                state_version=self.current_state_version,
                evidence=evidence,
                entities=entities,
                limitations=limitations,
            )
        return _ok(name, result, state_version=self.current_state_version)

    def _history_envelope(self, result: Any, query: dict[str, Any]) -> dict[str, Any]:
        """历年录取分数：**历史事实**，不是录取概率。

        它没有、也不需要概率。历史回答"去年录到多少位次"，概率回答"你今年
        有多大概率被录"——把前者当后者用，是用过去回答未来，而且答错了对象。
        证据挂在**查询**这一层（Java 按来源+参数签一条），不逐行挂。
        """
        normalized = normalize_history({"data": result.get("data")}, query)
        normalized["evidenceRefs"] = list(result.get("evidence") or result.get("evidenceRefs") or [])
        # 上游信封里的 limitations 要**带出去**：口径（unit 级 vs 专业级）、
        # 覆盖范围这些都在那里，这里重建信封时丢掉的话，模型会把这些行当成
        # 默认口径的"专业级数据"——而它们其实是院校/专业组投档线。
        normalized["limitations"] = list(
            result.get("limitations") or normalized.get("limitations") or []
        )
        normalized["stateVersion"] = self.current_state_version
        normalized["admissionMode"] = self.binding.admission_mode
        return normalized

    def _admission_envelope(self, name: str, result: Any) -> dict[str, Any]:
        """Normalize backend admission rows into unit facts plus scoped Evidence."""
        mode = self.binding.admission_mode
        if name == "admission.get_history" and mode == "major":
            # major 口径下这条工具就是历史查询：返回逐年事实，不返回"事实+率"。
            # major_group 走下面那条路（组级率来自 program 接口，属 B2 的 get_probability）。
            return self._history_envelope(
                result if isinstance(result, dict) else {},
                {
                    "schoolId": getattr(self.binding, "school_id", None),
                    "areaId": None,
                    "batch": None,
                },
            )
        if isinstance(result, bool):
            # `admission.check_eligibility` 的返回**就是一个布尔**（选科是否满足）。
            # 它以前落到下面那条 `not isinstance(result, dict)` 分支，被当成
            # "后端没返回结构化数据"——于是模型既看不到"合格"也看不到"不合格"，
            # 只收到一句 insufficient_data。**布尔是结论，不是缺数据**：
            # 该如实包成结论，让"不合格"有地方说出口。
            return {
                "schemaVersion": SCHEMA_VERSION,
                "kind": _kind_for(name),
                "status": "ok",
                "data": {"eligible": result, "checked": "subject_requirement"},
                "resolvedEntities": [],
                "evidenceRefs": [],
                "limitations": [],
                "nextCursor": None,
                "stateVersion": self.current_state_version,
                "admissionMode": mode,
            }
        if not isinstance(result, dict):
            return _err(name, 
                "insufficient_data",
                "admission backend returned no structured data",
                state_version=self.current_state_version,
                admission_mode=mode,
            )

        status = str(result.get("status") or "ok")
        raw_data = result.get("data")
        if isinstance(raw_data, list):
            # 真实上游的 `data` 是**数组**（历年分数线若干行）。
            # `dict([...])` 会直接抛 ValueError——这是"从消费者的期望编形状"
            # 留下的坑：替身返回 dict，真实返回数组。
            payload = {"items": raw_data}
        else:
            payload = dict(raw_data or result)
        if status != "ok":
            return {
                "schemaVersion": SCHEMA_VERSION,
                "kind": _kind_for(name),
                "status": status,
                "data": payload,
                "resolvedEntities": list(result.get("resolvedEntities") or []),
                "evidenceRefs": list(result.get("evidence") or result.get("evidenceRefs") or []),
                "limitations": list(result.get("limitations") or []),
                "nextCursor": None,
                "stateVersion": self.current_state_version,
                "admissionMode": mode,
            }

        raw_facts = payload.get("admissionFacts") or payload.get("admission_facts")
        if raw_facts is None:
            raw_facts = payload.get("items") if isinstance(payload.get("items"), list) else []
        if not isinstance(raw_facts, list):
            raw_facts = []
        data_version = result.get("dataVersion") or payload.get("dataVersion") or payload.get("data_version")
        algorithm_version = result.get("algorithmVersion") or payload.get("algorithmVersion")
        limitations = list(result.get("limitations") or payload.get("limitations") or [])
        facts: list[dict[str, Any]] = []
        for raw in raw_facts:
            if not isinstance(raw, dict):
                limitations.append("admission_fact_invalid")
                continue
            candidate = dict(raw)
            candidate.setdefault("admissionMode", mode)
            try:
                fact = validate_admission_fact(candidate)
            except AdmissionFactError as exc:
                limitations.append(exc.code)
                continue
            if fact["admissionMode"] != mode:
                limitations.append("admission_mode_mismatch")
                continue
            facts.append(fact)

        source_evidence = list(result.get("evidence") or payload.get("evidence") or [])
        evidence: list[dict[str, Any]] = []
        for fact in facts:
            matching = next(
                (
                    item
                    for item in source_evidence
                    if isinstance(item, dict)
                    and item.get("admissionUnitId", item.get("admission_unit_id")) == fact["admissionUnitId"]
                ),
                None,
            )
            if matching is not None:
                evidence.append(matching)
                continue
            # 没有对应证据就不造一条。自铸的 `admission-unit:*` 摘要对不上
            # Java 台账里的任何一条，下游 verify 一定会说"查不到"——
            # 与其让它走一遍注定失败的流程，不如在这里就如实返回"这份事实没有证据"。
            limitations.append("admission_evidence_missing")

        if not data_version and evidence:
            # 真实上游**不返回** `dataVersion`——P1b-1 实测结案：上游响应里根本没有
            # 这个字段，Java 改成对 `data` 算内容摘要，并把摘要签进**证据**。
            # 所以数据版本要从证据取，而不是盯着信封里一个不存在的字段判"缺版本"，
            # 那会把每一次真实调用都判成 insufficient_data。
            data_version = evidence[0].get("dataVersion") or evidence[0].get("data_version")
        if not data_version:
            limitations.append("dataVersion_missing")
        if mode == "major_group" and name == "admission.check_eligibility":
            if not facts or not any(fact.get("majorItems") for fact in facts):
                limitations.append("majorDetailAvailable=false")

        data = {
            "admissionMode": mode,
            "admissionFacts": facts,
            "limitations": limitations,
        }
        group_detail_missing = (
            mode == "major_group"
            and name == "admission.check_eligibility"
            and not any(fact.get("majorItems") for fact in facts)
        )
        result_status = "ok" if facts and data_version and not group_detail_missing else "insufficient_data"
        return {
            "schemaVersion": SCHEMA_VERSION,
            "kind": _kind_for(name),
            "status": result_status,
            "data": data,
            "resolvedEntities": list(result.get("resolvedEntities") or []),
            "evidenceRefs": evidence,
            "limitations": limitations,
            "nextCursor": None,
            "stateVersion": self.current_state_version,
            "admissionMode": mode,
            "dataVersion": data_version,
        }


class InternalClientBackend:
    """Adapter exposing existing internal read paths to Domain MCP."""

    def __init__(
        self,
        *,
        tenant_id: int | str,
        chat_session_id: int | str,
        thread_id: str | None = None,
        current_state_version: int = 42,
    ) -> None:
        self.tenant_id = tenant_id
        self.chat_session_id = chat_session_id
        self.thread_id = thread_id
        # 本类的若干方法（check_eligibility / compare / get_charter / get_enrollment_plan /
        # list_admission_units）用它给信封盖版本戳，而它原来只挂在**另一个类**
        # （ReadonlyDomainTools）上 ✗ → 那 5 个工具全部
        # `backend_unavailable: 'InternalClientBackend' object has no attribute
        # 'current_state_version'`（2026-09-24 真栈 E2E 抓到；推荐路径的入口正好在其中 ✗）。
        self.current_state_version = current_state_version

    @staticmethod
    def _data(response: Any) -> Any:
        return response.get("data") if isinstance(response, dict) and "data" in response else response

    @staticmethod
    def _preserve_envelope(response: Any) -> Any:
        """保留上游信封里的 `evidence`，而不是只取 `data` 把它扔掉。

        生产者形状（Java `ResponseDTO`）是 `{code, msg, data, evidence}`——
        `evidence` 是 `data` 的**兄弟字段**。只取 `data` 会让签发出来的证据
        在进入 Agent 的第一步就消失，于是下游一切"这条事实有没有证据"的判断
        都失去依据（这正是断链 2）。形状取自 Java DTO，不是从消费侧的期望编的。
        """
        if not isinstance(response, dict):
            return response
        if "code" not in response and "evidence" not in response:
            return response
        code = response.get("code")
        message = str(response.get("msg") or response.get("message") or "")
        limitations = list(response.get("limitations") or [])
        if code not in (None, 0):
            # 上游的错误码与原文必须一起带出去：只给一个 `upstream_error`，
            # 模型看不出缺的是哪个参数（实测：它连调三次都因为同一个必填项失败，
            # 而失败信息里没有任何可行动的东西）。原文里那句
            # `admission_source_school_required` 才是它自我纠正的依据。
            limitations = [*limitations, f"upstream_code:{code}", f"upstream_message:{message}"]
        return {
            "status": "ok" if code in (None, 0) else "upstream_error",
            "data": response.get("data"),
            "evidence": list(response.get("evidence") or []),
            "limitations": limitations,
            "resolvedEntities": list(response.get("resolvedEntities") or []),
        }

    async def resolve(self, **arguments: Any) -> Any:
        query = str(arguments.get("query") or arguments.get("name") or "")
        if arguments.get("entity_type") == "major":
            return self._data(await internal_client.catalog_lookup_major(query))
        return self._data(await internal_client.catalog_lookup_school(query))

    # 章程正文的硬上限（字符）。不设上限的话，一所大学的章程能把整轮上下文吃掉
    # ——实测福建师大那条正文去标签后 5581 字，还有更长的。
    CHARTER_CONTENT_LIMIT = 4000

    async def get_charter(self, **arguments: Any) -> Any:
        """招生章程：学校发布的**招生简章全文**。

        来源是"院校资讯"里的招生简章（标题自带年份、有上下架标志）。
        **不要**拿 `getSchoolRule` 那条（录取规则摘要）当原文：该校没有规则时它回
        占位文案"正在更新中"，而响应**没有标志位**区分——那段文字不能引用。
        """
        school_id = str(arguments.get("schoolId") or "").strip()
        if not school_id:
            result = _err(
                "admission.get_charter",
                "needs_clarification",
                "schoolId is required",
                state_version=self.current_state_version,
            )
            result["data"]["missingFields"] = ["schoolId"]
            return result
        year = str(arguments.get("year") or "").strip()

        listing = await internal_client.get_school_news(school_id)
        page = (listing or {}).get("data") if isinstance(listing, dict) else None
        records = [
            item for item in ((page or {}).get("records") or []) if isinstance(item, dict)
        ]
        if not records:
            # 措辞要准：**平台未收录**不等于"该校没有章程"。
            return {
                "status": "empty",
                "data": {"schoolId": school_id, "schoolsCharterKnown": False},
                "evidence": [],
                "limitations": ["charter_not_in_platform_catalog"],
            }
        chosen = next(
            (item for item in records if year and year in str(item.get("title") or "")),
            records[0],
        )
        detail = await internal_client.get_school_news_detail(
            chosen.get("id"),
            tenant_id=self.tenant_id,
            chat_session_id=self.chat_session_id,
            thread_id=self.thread_id,
        )
        payload = self._preserve_envelope(detail)
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        content_html = str(data.get("content") or "")
        content_text = _html_to_text(content_html)
        limitations = list(payload.get("limitations") or [])
        if not content_text:
            limitations.append("charter_content_empty")
        elif len(content_text) > self.CHARTER_CONTENT_LIMIT:
            content_text = content_text[: self.CHARTER_CONTENT_LIMIT]
            limitations.append("charter_content_truncated")
        # 平台收录版与学校官网可能有时差：正文可引用，但最终以官网为准。
        limitations.append("platform_copy_check_school_site")
        # payload 的 evidence 已经在明文里，外层 `_envelope` 会认；
        # 这里只把 data 换成人读的形状。
        return {
            "status": "ok",
            "data": {
                "schoolId": str(data.get("schoolId") or school_id),
                "schoolName": data.get("schoolName"),
                "newsId": data.get("id"),
                "title": data.get("title"),
                "year": year or None,
                "displayTime": data.get("displayTime"),
                "contentText": content_text,
            },
            "evidence": list(payload.get("evidence") or []),
            "limitations": limitations,
        }

    async def list_admission_units(self, **arguments: Any) -> Any:
        """该省、该校的**招生单元**树：年份 → 科类 → 批次 → 招生单元。

        上游返回的是四层嵌套，这里**摊平成行**：模型要的是
        (年份, 科类, 批次, 招生单位编号) 这个四元组，嵌套形状只会让它多绕一层。
        摊平后的行同时给 `label`（学校在该省的显示名）与 `schoolUnitCode`（省院校代码）。
        """
        school_id = str(arguments.get("schoolId") or "").strip()
        area_id = str(arguments.get("areaId") or "").strip()
        missing = [name for name, value in (("schoolId", school_id), ("areaId", area_id)) if not value]
        if missing:
            result = _err(
                "catalog.list_admission_units",
                "needs_clarification",
                f"missing: {', '.join(missing)}",
                state_version=self.current_state_version,
            )
            result["data"]["missingFields"] = missing
            return result
        response = await internal_client.get_plan_major_filter_list(school_id, area_id)
        payload = response if isinstance(response, dict) else {}
        if payload.get("code") not in (None, 0):
            return _err(
                "catalog.list_admission_units",
                "upstream_error",
                str(payload.get("msg") or "招生单元查询失败"),
                state_version=self.current_state_version,
            )
        rows = _flatten_unit_tree(payload.get("data"))
        return {
            "status": "ok" if rows else "empty",
            "data": {"units": rows},
            "limitations": [] if rows else ["no_admission_units_for_this_school_and_area"],
        }

    async def get_enrollment_plan(self, **arguments: Any) -> Any:
        """某个招生单元的招生计划：专业、计划数、学费、选考要求。

        回答的是"这所学校在我省**按什么**招生"——名校常按试验班/大类招，
        用户嘴里的"计算机"可能只出现在某个试验班的**包含专业**里。这条能如实说清，
        而且**不需要分数**。
        """
        required = {
            "schoolUnitId": arguments.get("schoolUnitId"),
            "schoolId": arguments.get("schoolId"),
            "areaId": arguments.get("areaId"),
            "year": arguments.get("year"),
            "subjectType": arguments.get("subjectType") or arguments.get("subject"),
            "batch": arguments.get("batch"),
        }
        missing = sorted(name for name, value in required.items() if str(value or "").strip() == "")
        if missing:
            # 六个都要：只给 unit id 或只给 schoolId+unitId 时，上游返回的是**空列表**
            # 而不是报错（实测：模型因此连查四年、四年都"0 行"，最后只能说"取不到"）。
            # 缺参必须在这里说清楚，并指出从哪拿——`catalog.list_admission_units`
            # 返回的每一行就带着 (年份/科类/批次)。
            result = _err(
                "admission.get_enrollment_plan",
                "needs_clarification",
                "missing enrollment scope: " + ", ".join(missing)
                + "（先调 catalog.list_admission_units，按它返回的行取值）",
                state_version=self.current_state_version,
            )
            result["data"]["missingFields"] = missing
            return result
        payload = {
            "schoolUnitId": str(required["schoolUnitId"]),
            "schoolId": str(required["schoolId"]),
            "areaId": str(required["areaId"]),
            "year": str(required["year"]),
            "subject": str(required["subjectType"]),
            "batch": str(required["batch"]),
        }
        return self._preserve_envelope(
            await internal_client.get_enrollment_plan(
                payload,
                tenant_id=self.tenant_id,
                chat_session_id=self.chat_session_id,
                thread_id=self.thread_id,
            )
        )

    async def list_batches(self, **arguments: Any) -> Any:
        """批次字典。`admission.get_history` / `admission.compare` 的 `batch` 必须来自这里。

        上游 `batchList[].batch` 就是那个码（浙江第一段 = "17"、上海本科批 = "01"），
        而且是**按省份不同**的。传"本科批"这种名字上游**不报错**，它只是返回空——
        于是每一次录取分查询都像"没有数据"，而真相是批次码不对。
        """
        area_id = str(arguments.get("areaId") or "").strip()
        if not area_id:
            result = _err(
                "catalog.list_batches",
                "needs_clarification",
                "areaId is required",
                state_version=self.current_state_version,
            )
            result["data"]["missingFields"] = ["areaId"]
            return result
        return self._preserve_envelope(
            await internal_client.get_batch_info(
                area_id,
                str(arguments.get("prepareType") or "VOLUNTEER"),
                str(arguments.get("subjectType") or "N"),
                tenant_id=self.tenant_id,
                chat_session_id=self.chat_session_id,
                thread_id=self.thread_id,
            )
        )

    async def get_batch_options(self, **arguments: Any) -> Any:
        """**补录成绩用**的批次编码表：`[{code, name, level, score, pos}]`。

        与 `catalog.list_batches`（上游 DTO 原样透传，给查录取分用）的分工：
        这条返回的是**补录草稿要填的编码**——`batch.code` + `level`（01 本科/02 专科）。
        省份必填（批次码按省份不同）；多科类省份（江苏）需要 `subjectType`
        （WL/LS，也可以给选考科目码/名称，Java 侧翻译）。`score` 是契约保留字段：
        上游批次策略不按分数筛批次，传了也只是原样收下（结果里如实标注）。
        """
        area_id = str(arguments.get("provinceCode") or arguments.get("areaId") or "").strip()
        if not area_id:
            result = _err(
                "catalog.get_batch_options",
                "needs_clarification",
                "provinceCode is required",
                state_version=self.current_state_version,
            )
            result["data"]["missingFields"] = ["provinceCode"]
            return result
        payload = self._preserve_envelope(
            await internal_client.get_batch_options(
                area_id,
                str(arguments.get("subjectType") or ""),
                tenant_id=self.tenant_id,
                chat_session_id=self.chat_session_id,
                thread_id=self.thread_id,
            )
        )
        if payload.get("status") == "ok" and str(arguments.get("score") or "").strip():
            # 批次不是按分数筛出来的：不说的话模型会把"我传了 610 分"读成因果。
            payload["limitations"] = [
                *(payload.get("limitations") or []),
                "batch_policy_ignores_score",
            ]
        return payload

    async def get_subject_options(self, **arguments: Any) -> Any:
        """**补录成绩用**的科目编码表：`[{code, name}]`（01-07 选考 + 08/10/11 语数外）。

        补录草稿的 `subjectScoreList[].subject` 只能取这里的 `code`：
        只报分数（无编码）或报科目名，都会在落库前被 110 拒。
        """
        area_id = str(arguments.get("provinceCode") or arguments.get("areaId") or "").strip()
        if not area_id:
            result = _err(
                "catalog.get_subject_options",
                "needs_clarification",
                "provinceCode is required",
                state_version=self.current_state_version,
            )
            result["data"]["missingFields"] = ["provinceCode"]
            return result
        return self._preserve_envelope(
            await internal_client.get_subject_options(area_id)
        )

    async def get_score_position(self, **arguments: Any) -> Any:
        """一分一段：分数 → 位次**区间**（展示）+ **单一默认位次**（测算）。

        **同分考生不可分辨**：`highest_rank`~`lowest_rank` 是区间
        （`same_score_count` 人同分），只能报区间，不能报单一名次。
        `default_rank` = `lowest_rank`（同分最后一名 / 累计人数口径 / 最保守）：
        与 hl-wish `ScoreAlgorithmImpl.scoreToPos` 取 `positionTotal` 的**同一口径**，
        供下一轮出方案/冲稳保测算做默认位次用（区间用于展示，测算用它）。
        上游没有该省数据时（如安徽）Java 如实回 `data: null`：这里转成
        `unavailable=true` + limitation，**不估算、不替上游编一个名次**。
        """
        area_id = str(arguments.get("provinceCode") or arguments.get("areaId") or "").strip()
        score = str(arguments.get("score") or "").strip()
        missing = [
            name
            for name, value in (("provinceCode", area_id), ("score", score))
            if not value
        ]
        if missing:
            result = _err(
                "catalog.get_score_position",
                "needs_clarification",
                f"missing: {', '.join(missing)}",
                state_version=self.current_state_version,
            )
            result["data"]["missingFields"] = missing
            return result
        payload = self._preserve_envelope(
            await internal_client.get_score_position(
                area_id,
                score,
                subject=str(arguments.get("subjectType") or "").strip() or "N",
                data_level=str(arguments.get("batchLevel") or "").strip() or "01",
                # 年份缺省**当前年**（会话里给了年份以会话为准）：上游按年份取表，
                # 不带年份会先失败一次再靠 Java 侧回退，白多一跳。
                year=str(arguments.get("year") or "").strip() or str(datetime.now().year),
            )
        )
        if not isinstance(payload, dict):
            return payload
        limitations = list(payload.get("limitations") or [])
        raw = payload.get("data")
        if isinstance(raw, dict):
            payload["data"] = {
                "score": _clean_score(raw.get("score"), score),
                "same_score_count": raw.get("students"),
                "highest_rank": raw.get("highestRank"),
                "lowest_rank": raw.get("lowestRank"),
                # 单一默认位次：`lowest_rank`（同分最后一名 / 累计人数 / 最保守）。
                # 口径与 hl-wish `scoreToPos` 的 `positionTotal` 一致（产品裁决，
                # 2026-10-07）——区间只用于展示，测算用这个值。
                "default_rank": raw.get("lowestRank"),
                "data_level": raw.get("dataLevel"),
            }
        elif payload.get("status") == "ok":
            # 上游没有该省的一分一段数据：如实说**不可用**，不给数字。
            payload["data"] = {"score": score, "unavailable": True}
            limitations.append("score_position_unavailable")
        payload["limitations"] = limitations
        return payload

    async def search_schools(self, **arguments: Any) -> Any:
        # `query` 曾经在这里被**静默丢掉**：工具声明了它，模型也按声明传了，
        # 而后端只拿省份/城市/类型去筛，于是 `query="北京大学"` 返回的是一批
        # 与该名字无关的学校（实测第一所是"赣州起元职业学院"）。模型只能自己
        # 发现并绕道（补上 province=北京），换一个不那么谨慎的模型就会把
        # 那份列表当答案念给用户。名字条件走按名搜索端点，筛选题材走高级搜索。
        query = str(arguments.get("query") or arguments.get("name") or "").strip()
        if query:
            return self._data(await internal_client.search_schools_by_name(query))
        return self._data(await internal_client.catalog_list_schools(
            province=arguments.get("province"), city=arguments.get("city"),
            school_type=arguments.get("schoolType"), ownership=arguments.get("ownership"),
            education_level=arguments.get("educationLevel")))

    async def get_school(self, **arguments: Any) -> Any:
        return self._data(await internal_client.get_school_profile_by_name(
            str(arguments.get("name") or arguments.get("schoolId") or "")))

    # 分数线来源能填的维度。录取率、学费那几个维度来自**别的来源**
    # （录取率引擎 / 招生计划），这里如实列进 unavailableDimensions，
    # 而不是留空——留空会被读成"值为 0 或没查到"。
    COMPARISON_SCORE_DIMENSIONS = ("finalScore", "planNum")

    async def compare(self, **arguments: Any) -> Any:
        """把 2–5 个院校/专业在**同一口径**下并列。

        口径 = (年份, 省份, 批次, 科类)，四项必须由调用方显式给全：
        缺一项就拒绝，不用"最近一年"或默认省份凑——跨年、跨批次的数字并排
        放进一张表，读者会默认它们可比，而那是这张表最危险的错误。
        """
        raw_entities = arguments.get("entities")
        if not isinstance(raw_entities, list) or not (2 <= len(raw_entities) <= 5):
            return _err(
                "admission.compare",
                "needs_clarification",
                "comparison needs 2 to 5 entities",
                state_version=self.current_state_version,
            )

        scope = {
            "areaId": str(arguments.get("areaId") or "").strip(),
            "batch": str(arguments.get("batch") or "").strip(),
            "year": arguments.get("year"),
            "subjectType": str(arguments.get("subjectType") or "").strip(),
        }
        missing = sorted(
            key for key, value in scope.items() if value in (None, "")
        )
        if missing:
            result = _err(
                "admission.compare",
                "needs_clarification",
                f"missing comparison scope: {', '.join(missing)}",
                state_version=self.current_state_version,
            )
            result["data"]["missingFields"] = missing
            return result

        requested_dimensions = [
            str(item) for item in (arguments.get("dimensions") or []) if str(item).strip()
        ]

        entities: list[dict[str, Any]] = []
        evidence: list[Any] = []
        limitations: list[str] = []
        for raw in raw_entities:
            if not isinstance(raw, dict):
                return _err("admission.compare", "invalid_request", "entity must be an object",
                            state_version=self.current_state_version)
            school_id = str(raw.get("schoolId") or "").strip()
            major_id = str(raw.get("majorId") or "").strip()
            if not school_id:
                return _err("admission.compare", "needs_clarification", "entity.schoolId is required",
                            state_version=self.current_state_version)
            response = await internal_client.query_school_major_score_line(
                area_id=scope["areaId"],
                batch=scope["batch"],
                school_id=school_id,
                major_id=major_id,
                year=int(scope["year"]),
                subject_type=scope["subjectType"],
                group_code="",
                tenant_id=self.tenant_id,
                chat_session_id=self.chat_session_id,
                thread_id=self.thread_id,
            )
            payload = response if isinstance(response, dict) else {}
            rows = payload.get("data") if isinstance(payload.get("data"), list) else []
            evidence.extend(payload.get("evidence") or [])
            row = _pick_comparison_row(rows, int(scope["year"]))
            if row is None:
                limitations.append(f"no_score_line_for:{school_id}")
            entities.append(
                {
                    "entityId": f"{school_id}:{major_id}" if major_id else school_id,
                    "schoolId": school_id,
                    "schoolName": str((row or {}).get("name") or ""),
                    "majorId": major_id,
                    # 口径身份。**学校级与专业级不能并排**：它们的招生单元不同，
                    # 混在一张表里等于拿两个口径的数字比大小。
                    "admissionMode": "major" if major_id else "school",
                    # 被比较量的单位。分数线口径下恒为 score——这个字段只用于
                    # "是不是同一个口径"的判定，不代表录取率单位。
                    "rateUnit": "score",
                    "admissionYear": (_as_int((row or {}).get("year")) or (int(scope["year"]) if row else None)),
                    "areaId": scope["areaId"],
                    "batch": scope["batch"],
                    "finalScore": _as_float((row or {}).get("minScore")),
                    "planNum": _as_int((row or {}).get("enrollNum")),
                }
            )

        dimensions = requested_dimensions or list(self.COMPARISON_SCORE_DIMENSIONS)
        unavailable_by_source = [
            item
            for item in dimensions
            if item not in self.COMPARISON_SCORE_DIMENSIONS
            and item not in ("cityName",)
        ]
        if unavailable_by_source:
            limitations.append("dimension_source_not_wired:" + ",".join(sorted(unavailable_by_source)))

        comparison = await internal_client.compare_candidates(
            self.tenant_id, entities, [d for d in dimensions if d not in unavailable_by_source]
        )
        payload_data = (comparison or {}).get("data") or {}
        if (comparison or {}).get("code") not in (None, 0) or not isinstance(payload_data, dict):
            raise RuntimeError("comparison_contract_unavailable")
        payload_data.setdefault("limitations", [])
        payload_data["limitations"] = list(payload_data["limitations"]) + limitations
        if unavailable_by_source:
            payload_data["unavailableDimensions"] = sorted(
                set(payload_data.get("unavailableDimensions") or []) | set(unavailable_by_source)
            )
        # 同一个实体被查两次、或两条证据指向同一条记录时会出现重复条目：
        # 信封里同一条证据出现两次，下游按 id 合并时不会出错，但会让"引用了
        # 几条证据"这个计数变假。按 id 去重，保持首次出现的顺序。
        unique_evidence: list[Any] = []
        seen_evidence: set[str] = set()
        for item in evidence:
            key = str((item or {}).get("evidenceId") or "") if isinstance(item, dict) else str(item)
            if key and key in seen_evidence:
                continue
            seen_evidence.add(key)
            unique_evidence.append(item)

        # 返回**裸形状**交给外层 `_envelope` 包：自己先包一层的话，证据会被
        # 它当成"已经没有 evidence 键"而丢掉（它认的键是 `evidence`）。
        return {
            "status": "ok",
            "data": payload_data,
            "evidence": unique_evidence,
            "limitations": payload_data["limitations"],
        }

    # 候选预览一次带回的条数上限。与 Java 侧硬上限一致：**全量候选留在服务器**，
    # 模型拿到的是"一页样例 + 全量计数"，整池候选吃不掉一轮上下文。
    CANDIDATE_PREVIEW_PAGE_SIZE_CAP = 20

    # 过滤器别名 → Java 侧字段名。模型措辞不稳定（tier/tiers、province/provinceNames、
    # 蛇形/驼峰、单值/列表），这里统一归一；**不认识的键原样透传**——
    # 猜不出的维度宁可让上游如实回 `filter_unsupported:*`，也不能静默丢掉。
    _PREVIEW_FILTER_ALIASES = {
        "tier": "tiers",
        "tiers": "tiers",
        "province": "provinceNames",
        "provinces": "provinceNames",
        "province_names": "provinceNames",
        "provinceNames": "provinceNames",
        "negative_province_names": "negativeProvinceNames",
        "negativeProvinceNames": "negativeProvinceNames",
        "city": "cityNames",
        "cities": "cityNames",
        "city_names": "cityNames",
        "cityNames": "cityNames",
        "negative_city_names": "negativeCityNames",
        "negativeCityNames": "negativeCityNames",
        "school": "schoolKeywords",
        "school_keywords": "schoolKeywords",
        "schoolKeywords": "schoolKeywords",
        "negative_school_keywords": "negativeSchoolKeywords",
        "negativeSchoolKeywords": "negativeSchoolKeywords",
        "major": "majorKeywords",
        "major_keywords": "majorKeywords",
        "majorKeywords": "majorKeywords",
        "negative_major_keywords": "negativeMajorKeywords",
        "negativeMajorKeywords": "negativeMajorKeywords",
        "school_tags": "schoolTags",
        "schoolTags": "schoolTags",
        "negative_school_tags": "negativeSchoolTags",
        "negativeSchoolTags": "negativeSchoolTags",
        "major_tags": "majorTags",
        "majorTags": "majorTags",
        "negative_major_tags": "negativeMajorTags",
        "negativeMajorTags": "negativeMajorTags",
    }

    @classmethod
    def _normalize_preview_filters(cls, raw: Any) -> dict[str, Any]:
        if not isinstance(raw, dict):
            return {}
        normalized: dict[str, Any] = {}
        for key, value in raw.items():
            name = cls._PREVIEW_FILTER_ALIASES.get(str(key), str(key))
            if isinstance(value, str):
                value = [value] if value.strip() else []
            if isinstance(value, list):
                normalized[name] = [str(item) for item in value if str(item).strip()]
            else:
                normalized[name] = value
        return normalized

    async def preview_candidates(self, **arguments: Any) -> Any:
        """候选预览（只读）：过滤后全量计数 + 一页样例，**不落规划状态**。

        `returned_items_are_sample` 是**边界声明**（同 `discover_options` 口径）：
        `total` 是全量条数，`items` 只是这一页，不能拿这 20 条概括分布。
        """
        page = _as_int(arguments.get("page")) or 1
        requested_size = _as_int(arguments.get("pageSize", arguments.get("page_size")))
        page_size = (
            requested_size
            if requested_size and requested_size > 0
            else self.CANDIDATE_PREVIEW_PAGE_SIZE_CAP
        )
        page_size = min(page_size, self.CANDIDATE_PREVIEW_PAGE_SIZE_CAP)
        filters = self._normalize_preview_filters(arguments.get("filters"))

        response = await internal_client.preview_candidates(
            self.tenant_id,
            self.chat_session_id,
            filters=filters,
            page=max(page, 1),
            page_size=page_size,
        )
        payload = self._preserve_envelope(response)
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        items = [item for item in (data.get("items") or []) if isinstance(item, dict)]
        total = _as_int(data.get("total")) or 0
        limitations = list(payload.get("limitations") or [])
        for limitation in data.get("limitations") or []:
            if limitation not in limitations:
                limitations.append(limitation)
        return {
            "status": payload.get("status") or "ok",
            "data": {
                "items": items,
                "total": total,
                "returned_total": len(items),
                # 样例边界：total 是全量条数，items 只是这一页。
                "returned_items_are_sample": total > len(items),
                "page": data.get("page", max(page, 1)),
                "page_size": data.get("pageSize", page_size),
                "profile_version": data.get("profileVersion"),
                "data_version": data.get("dataVersion"),
                "limitations": limitations,
                # 预览不是写操作：不存在"预览把候选加入/落盘"这种事。
                "state_mutation": False,
            },
            "evidence": list(payload.get("evidence") or []),
            "limitations": limitations,
        }

    async def search_majors(self, **arguments: Any) -> Any:
        return self._data(await internal_client.catalog_search_major(
            str(arguments.get("query") or arguments.get("keyword") or ""),
            arguments.get("educationLevel")))

    async def get_major(self, **arguments: Any) -> Any:
        return self._data(await internal_client.get_major_profile(
            major_name=arguments.get("name"), major_id=arguments.get("majorId")))

    async def get_current_plan(self, **arguments: Any) -> Any:
        # tenant 从**可信 binding** 传入，不从模型参数取：
        # 一旦模型能指定 tenant，它就能读别的租户的志愿表。
        return self._data(await internal_client.get_working_plan(
            self.chat_session_id, self.tenant_id))

    async def get_history(self, **arguments: Any) -> Any:
        group_code = str(arguments.get("groupCode") or "").strip()
        if group_code:
            # Java 侧的分数线 DTO 目前**不消费 groupCode**，也就是说这条链路
            # 拿不到组级来源。把学校级结果标成组级会让"这个专业组去年录到
            # 多少位次"变成一个用别的数据回答的问题——宁可如实说"这条口径
            # 还不支持"，也不要给一个看起来对、其实不是组级的数。
            return {
                "status": "unsupported",
                "code": "unsupported_scope",
                "data": [],
                "evidence": [],
                "limitations": ["group_scope_source_unavailable"],
            }
        payload = self._preserve_envelope(await internal_client.query_school_major_score_line(
            area_id=str(arguments.get("areaId") or ""), batch=str(arguments.get("batch") or ""),
            school_id=str(arguments.get("schoolId") or ""), major_id=str(arguments.get("majorId") or ""),
            year=int(arguments.get("year") or 0), subject_type=str(arguments.get("subjectType") or ""),
            group_code=str(arguments.get("groupCode") or ""),
            tenant_id=self.tenant_id, chat_session_id=self.chat_session_id,
            thread_id=self.thread_id))
        if not str(arguments.get("majorId") or "").strip():
            # 口径必须写在明面上：这是**院校/专业组级**投档线。混成"专业级数据"
            # 会让"这个专业多少分"变成一个用别的数据回答的问题。
            payload.setdefault("limitations", [])
            payload["limitations"] = list(payload["limitations"]) + [
                "caliber_unit_level_not_major"
            ]
        return payload

    async def check_eligibility(self, **arguments: Any) -> Any:
        """选科资格。**三级专业 id 必须落在 `level3`。**

        Java 侧 `PlanValidationService.checkMajorSubjectAvailability` 只读
        `majors["level3"]`。这个 id 以前被塞进 `level2`，于是那边的 for 循环
        一次都不执行、直接 `return true`——**对任何专业都说"选科要求都满足"**，
        日志还会打印"所有专业的选科要求都满足"。这比 fail-closed 更糟：
        它给用户一个假的肯定，而用户会据此填报。
        """
        major_id = str(arguments.get("majorId") or "").strip()
        if not major_id:
            result = _err(
                "admission.check_eligibility",
                "needs_clarification",
                "majorId is required",
                state_version=self.current_state_version,
            )
            result["data"]["missingFields"] = ["majorId"]
            return result
        return self._data(await internal_client.check_major_subject_availability(
            self.tenant_id, str(self.chat_session_id),
            majors={"level1": [], "level2": [], "level3": [major_id]}))
