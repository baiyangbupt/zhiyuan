from __future__ import annotations

import asyncio
import hashlib
import json
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
}


def _kind_for(name: str) -> str:
    return TOOL_KINDS.get(name, "catalog")


def _ok(name: str, data: Any, **kwargs: Any) -> dict[str, Any]:
    return ok(data, kind=_kind_for(name), **kwargs)


def _err(name: str, status: str, message: str, **kwargs: Any) -> dict[str, Any]:
    return error(status, message, kind=_kind_for(name), **kwargs)


class ReadonlyDomainTools:
    def __init__(
        self,
        binding: ThreadBinding,
        *,
        backend: Any,
        current_state_version: int = 42,
        max_calls: int = 8,
        backend_timeout: float = 5.0,
    ) -> None:
        self.binding = binding
        self.backend = backend
        self.current_state_version = current_state_version
        self.max_calls = max_calls
        self.backend_timeout = backend_timeout
        self.calls = 0
        self._cache: dict[str, dict[str, Any]] = {}

    async def call(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        arguments = arguments or {}
        if name in WRITE_TOOL_NAMES:
            return _err(name, "capability_denied", "readonly tools cannot perform writes", state_version=self.current_state_version)
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
            required = {"areaId", "batch", "schoolId", "year", "subjectType"}
            required.add("majorId" if requested_mode == "major" else "groupCode")
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
            if resolved.get("status") == "needs_clarification":
                return resolved
            return await self.backend.search_majors(**self._trusted_arguments(arguments))
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
    ) -> None:
        self.tenant_id = tenant_id
        self.chat_session_id = chat_session_id
        self.thread_id = thread_id

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
        return {
            "status": "ok" if code in (None, 0) else "upstream_error",
            "data": response.get("data"),
            "evidence": list(response.get("evidence") or []),
            "limitations": list(response.get("limitations") or []),
            "resolvedEntities": list(response.get("resolvedEntities") or []),
        }

    async def resolve(self, **arguments: Any) -> Any:
        query = str(arguments.get("query") or arguments.get("name") or "")
        if arguments.get("entity_type") == "major":
            return self._data(await internal_client.catalog_lookup_major(query))
        return self._data(await internal_client.catalog_lookup_school(query))

    async def search_schools(self, **arguments: Any) -> Any:
        return self._data(await internal_client.catalog_list_schools(
            province=arguments.get("province"), city=arguments.get("city"),
            school_type=arguments.get("schoolType"), ownership=arguments.get("ownership"),
            education_level=arguments.get("educationLevel")))

    async def get_school(self, **arguments: Any) -> Any:
        return self._data(await internal_client.get_school_profile_by_name(
            str(arguments.get("name") or arguments.get("schoolId") or "")))

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
        return self._preserve_envelope(await internal_client.query_school_major_score_line(
            area_id=str(arguments.get("areaId") or ""), batch=str(arguments.get("batch") or ""),
            school_id=str(arguments.get("schoolId") or ""), major_id=str(arguments.get("majorId") or ""),
            year=int(arguments.get("year") or 0), subject_type=str(arguments.get("subjectType") or ""),
            group_code=str(arguments.get("groupCode") or ""),
            tenant_id=self.tenant_id, chat_session_id=self.chat_session_id,
            thread_id=self.thread_id))

    async def check_eligibility(self, **arguments: Any) -> Any:
        return self._data(await internal_client.check_major_subject_availability(
            self.tenant_id, str(self.chat_session_id),
            majors={"level1": [], "level2": [str(arguments.get("majorId") or "")], "level3": []}))
