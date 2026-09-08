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
