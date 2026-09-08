from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Iterable


@dataclass(frozen=True, slots=True)
class ToolContract:
    name: str
    required_arguments: tuple[str, ...]
    description: str
    read_only: bool = True


@dataclass(frozen=True, slots=True)
class ToolPreparation:
    tool_name: str
    normalized_arguments: dict[str, Any]
    missing_arguments: tuple[str, ...]
    invocation_key: str

    @property
    def ready(self) -> bool:
        return not self.missing_arguments


@dataclass(frozen=True, slots=True)
class ToolStep:
    step_id: str
    tool_name: str
    arguments: dict[str, Any]
    depends_on: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ToolStepReport:
    step_id: str
    tool_name: str
    status: str
    invocation_key: str
    missing_arguments: tuple[str, ...] = ()
    result_count: int = 0
    error: str | None = None


@dataclass(frozen=True, slots=True)
class ToolBatchReport:
    steps: tuple[ToolStepReport, ...]
    merged_results: tuple[dict[str, Any], ...]

    @property
    def status(self) -> str:
        statuses = {step.status for step in self.steps}
        if "blocked" in statuses:
            return "blocked"
        if "failed" in statuses and "completed" in statuses:
            return "partial"
        if "failed" in statuses:
            return "failed"
        return "completed"


def prepare_tool_batch(
    steps: Iterable[ToolStep],
    *,
    completed_keys: Iterable[str] = (),
    results_by_step: dict[str, Iterable[dict[str, Any]]] | None = None,
    errors_by_step: dict[str, str] | None = None,
) -> ToolBatchReport:
    """Report a dependency-ordered read batch without invoking tools."""
    completed = set(completed_keys)
    results_by_step = results_by_step or {}
    errors_by_step = errors_by_step or {}
    reports: list[ToolStepReport] = []
    all_results: list[dict[str, Any]] = []
    known_steps: set[str] = set()
    for step in steps:
        preparation = prepare_tool_invocation(step.tool_name, step.arguments)
        dependency_blocked = any(
            dependency not in known_steps
            or not any(
                report.step_id == dependency and report.status == "completed"
                for report in reports
            )
            for dependency in step.depends_on
        )
        if preparation.missing_arguments:
            status = "blocked"
        elif dependency_blocked:
            status = "blocked"
        elif preparation.invocation_key in completed:
            status = "duplicate"
        elif step.step_id in errors_by_step:
            status = "failed"
        else:
            status = "completed"
        step_results = [item for item in results_by_step.get(step.step_id, ()) if isinstance(item, dict)]
        all_results.extend(step_results)
        reports.append(
            ToolStepReport(
                step_id=step.step_id,
                tool_name=step.tool_name,
                status=status,
                invocation_key=preparation.invocation_key,
                missing_arguments=preparation.missing_arguments,
                result_count=len(step_results),
                error=errors_by_step.get(step.step_id),
            )
        )
        known_steps.add(step.step_id)
    return ToolBatchReport(tuple(reports), tuple(merge_tool_results(all_results)))


TOOL_CONTRACTS: tuple[ToolContract, ...] = (
    ToolContract(
        "catalog.search_schools",
        (),
        "只读搜索学校候选；用户未提供检索条件时应先澄清。",
    ),
    ToolContract(
        "catalog.search_majors",
        (),
        "只读搜索专业候选；用户未提供检索条件时应先澄清。",
    ),
    ToolContract(
        "admission.get_history",
        ("schoolId", "majorId", "areaId", "batch", "year", "subjectType"),
        "只读查询历史录取事实；参数不完整时不得调用。",
    ),
    ToolContract(
        "admission.get_current_plan",
        (),
        "只读读取当前方案；不得直接修改方案。",
    ),
)

_CONTRACT_BY_NAME = {contract.name: contract for contract in TOOL_CONTRACTS}


def prepare_tool_invocation(name: str, arguments: dict[str, Any] | None) -> ToolPreparation:
    """Normalize a proposed invocation without inventing missing values."""
    contract = _CONTRACT_BY_NAME.get(name)
    normalized = _normalize_arguments(arguments or {})
    required = contract.required_arguments if contract else ()
    missing = tuple(
        key for key in required if normalized.get(key) in (None, "", [], {})
    )
    return ToolPreparation(
        tool_name=name,
        normalized_arguments=normalized,
        missing_arguments=missing,
        invocation_key=build_invocation_key(name, normalized),
    )


def build_invocation_key(name: str, arguments: dict[str, Any]) -> str:
    canonical = json.dumps(
        {str(key): arguments[key] for key in sorted(arguments)},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:20]
    return f"{name}:{digest}"


def is_duplicate_invocation(
    name: str, arguments: dict[str, Any], completed_keys: Iterable[str]
) -> bool:
    return build_invocation_key(name, _normalize_arguments(arguments)) in set(completed_keys)


def merge_tool_results(results: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge repeated read results by stable evidence/entity identifiers."""
    merged: dict[str, dict[str, Any]] = {}
    anonymous: list[dict[str, Any]] = []
    for result in results:
        if not isinstance(result, dict):
            continue
        key = (
            result.get("evidenceId")
            or result.get("evidence_id")
            or result.get("entityId")
            or result.get("entity_id")
        )
        if key in (None, ""):
            anonymous.append(result)
        else:
            merged[str(key)] = result
    return list(merged.values()) + anonymous


def render_tool_contracts() -> str:
    lines = ["可用只读工具的确定性编排约束："]
    for contract in TOOL_CONTRACTS:
        required = "、".join(contract.required_arguments) or "由用户目标决定"
        lines.append(f"- {contract.name}：必需参数={required}；{contract.description}")
    lines.append("相同工具和相同参数已经完成时，不要重复调用；不同学校应分别保留各自结果。")
    return "\n".join(lines)


def _normalize_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
    aliases = {
        "school_id": "schoolId",
        "major_id": "majorId",
        "area_id": "areaId",
        "subject_type": "subjectType",
    }
    normalized: dict[str, Any] = {}
    for key, value in arguments.items():
        normalized[aliases.get(str(key), str(key))] = value
    return normalized
