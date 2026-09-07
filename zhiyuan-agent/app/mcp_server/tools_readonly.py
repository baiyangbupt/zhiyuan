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
from app.harness.binding import BindingError, ThreadBinding
from app.mcp_server.response import error, ok
from app.util import internal_client


CAPABILITIES = {
    "entity.resolve": "catalog_read",
    "catalog.search_schools": "catalog_read",
    "catalog.get_school": "catalog_read",
    "catalog.search_majors": "catalog_read",
    "catalog.get_major": "catalog_read",
    "admission.get_current_plan": "admission_read",
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
            return error("capability_denied", "readonly tools cannot perform writes", state_version=self.current_state_version)
        if name not in CAPABILITIES:
            return error("tool_not_found", name, state_version=self.current_state_version)
        requested_mode: str | None = None
        if name.startswith("admission."):
            raw_mode = arguments.get("admissionMode", arguments.get("admission_mode"))
            try:
                requested_mode = canonical_admission_mode(
                    self.binding.admission_mode if raw_mode in (None, "") else raw_mode
                )
            except AdmissionFactError as exc:
                return error(exc.code, "unsupported admission mode", state_version=self.current_state_version)
            if requested_mode != self.binding.admission_mode:
                return error(
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
                return error("invalid_state_version", "stateVersion must be an integer", state_version=self.current_state_version)
            if requested_version != self.current_state_version:
                return error("stale_state", "stateVersion is stale", state_version=self.current_state_version)
        try:
            required_capability = CAPABILITIES[name]
            if required_capability in self.binding.allowed_capabilities:
                self.binding.authorize(required_capability)
            elif name in self.binding.allowed_capabilities:
                self.binding.authorize(name)
            else:
                raise BindingError("capability_denied")
        except BindingError as exc:
            return error(exc.code, str(exc), state_version=self.current_state_version)
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
            return error("call_budget_exceeded", "readonly tool call budget exceeded", state_version=self.current_state_version)
        if name == "admission.get_history":
            required = {"areaId", "batch", "schoolId", "year", "subjectType"}
            required.add("majorId" if requested_mode == "major" else "groupCode")
            missing = sorted(key for key in required if arguments.get(key) in (None, ""))
            if missing:
                result = error(
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
                return error("backend_unavailable", str(retry_exc or exc), state_version=self.current_state_version)
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
            "admission.get_history": "get_history",
            "admission.check_eligibility": "check_eligibility",
        }[name]
        return await getattr(self.backend, method)(**self._trusted_arguments(arguments))

    def _trusted_arguments(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in arguments.items() if key not in {"threadId", "tenantId", "sessionId", "userId", "handle", "stateVersion"}}

    def _envelope(self, name: str, result: Any) -> dict[str, Any]:
        if name.startswith("admission."):
            return self._admission_envelope(name, result)
        if isinstance(result, dict):
            evidence = list(result.get("evidence") or [])
            if any(
                item.get("threadId") not in (None, self.binding.thread_id)
                for item in evidence
                if isinstance(item, dict)
            ):
                return error(
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
                return ok(
                    result.get("data"),
                    state_version=self.current_state_version,
                    evidence=evidence,
                    entities=entities,
                    limitations=limitations,
                )
            if not evidence and result.get("dataVersion"):
                evidence = [
                    {
                        "evidenceId": f"ev-{name}",
                        "sourceLevel": "authoritative",
                        "dataVersion": result["dataVersion"],
                        "limitations": limitations,
                    }
                ]
            return ok(
                result,
                state_version=self.current_state_version,
                evidence=evidence,
                entities=entities,
                limitations=limitations,
            )
        return ok(result, state_version=self.current_state_version)

    def _admission_envelope(self, name: str, result: Any) -> dict[str, Any]:
        """Normalize backend admission rows into unit facts plus scoped Evidence."""
        mode = self.binding.admission_mode
        if not isinstance(result, dict):
            return error(
                "insufficient_data",
                "admission backend returned no structured data",
                state_version=self.current_state_version,
                admission_mode=mode,
            )

        status = str(result.get("status") or "ok")
        payload = dict(result.get("data") or result)
        if status != "ok":
            return {
                "status": status,
                "data": payload,
                "resolvedEntities": list(result.get("resolvedEntities") or []),
                "evidence": list(result.get("evidence") or []),
                "limitations": list(result.get("limitations") or []),
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
            evidence.append(
                {
                    "evidenceId": f"admission-unit:{fact['admissionUnitId']}:{data_version or 'unknown'}",
                    "kind": "admission_fact",
                    "admissionMode": mode,
                    "admissionUnitId": fact["admissionUnitId"],
                    "groupCode": fact.get("groupCode"),
                    "sourceLevel": "authoritative",
                    "source": "zhiyuan-server.admission",
                    "dataVersion": data_version,
                    "algorithmVersion": algorithm_version,
                    "stateVersion": self.current_state_version,
                    "scope": {
                        "tenantId": self.binding.tenant_id,
                        "sessionId": self.binding.session_id,
                        "threadId": self.binding.thread_id,
                    },
                    "limitations": [],
                }
            )

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
            "status": result_status,
            "data": data,
            "resolvedEntities": list(result.get("resolvedEntities") or []),
            "evidence": evidence,
            "limitations": limitations,
            "stateVersion": self.current_state_version,
            "admissionMode": mode,
            "dataVersion": data_version,
        }


class InternalClientBackend:
    """Adapter exposing existing internal read paths to Domain MCP."""

    def __init__(self, *, tenant_id: int | str, chat_session_id: int | str) -> None:
        self.tenant_id = tenant_id
        self.chat_session_id = chat_session_id

    @staticmethod
    def _data(response: Any) -> Any:
        return response.get("data") if isinstance(response, dict) and "data" in response else response

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
        return self._data(await internal_client.get_working_plan(self.chat_session_id))

    async def get_history(self, **arguments: Any) -> Any:
        return self._data(await internal_client.query_school_major_score_line(
            area_id=str(arguments.get("areaId") or ""), batch=str(arguments.get("batch") or ""),
            school_id=str(arguments.get("schoolId") or ""), major_id=str(arguments.get("majorId") or ""),
            year=int(arguments.get("year") or 0), subject_type=str(arguments.get("subjectType") or "")))

    async def check_eligibility(self, **arguments: Any) -> Any:
        return self._data(await internal_client.check_major_subject_availability(
            self.tenant_id, str(self.chat_session_id),
            majors={"level1": [], "level2": [str(arguments.get("majorId") or "")], "level3": []}))
