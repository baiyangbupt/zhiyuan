"""Small deterministic helpers for intent polarity correction."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any


NEGATIVE_CONSTRAINT_REVERSAL_MARKERS = (
    "不要排除",
    "别排除",
    "不用排除",
    "不必排除",
    "无需排除",
    "不排除",
    "不要去掉",
    "别去掉",
    "不用去掉",
    "不必去掉",
    "无需去掉",
    "不去掉",
    "不要避开",
    "别避开",
    "不用避开",
    "不必避开",
    "无需避开",
    "不避开",
    "取消排除",
    "撤销排除",
    "取消去掉",
    "撤销去掉",
)

_POLARITY_CLAUSE_SPLIT_PATTERN = re.compile(
    r"[，,。；;！？?!\n]+|(?:但是|但|不过|然后|同时|并且|而且|另外|此外)"
)


@dataclass(frozen=True)
class IntentPolarityOperation:
    operation: str
    target_polarity: str
    replacement_polarity: str
    replacement_strength: str


def compact_polarity_text(value: Any) -> str:
    return "".join(str(value or "").split())


def split_polarity_clauses(value: Any) -> list[str]:
    text = str(value or "").strip()
    if not text:
        return []
    clauses: list[str] = []
    for raw_clause in _POLARITY_CLAUSE_SPLIT_PATTERN.split(text):
        clause = str(raw_clause or "").strip()
        if clause:
            clauses.append(clause)
    return clauses


def parse_constraint_polarity_operation(value: Any) -> IntentPolarityOperation | None:
    compact = compact_polarity_text(value)
    if not compact:
        return None
    if any(marker in compact for marker in NEGATIVE_CONSTRAINT_REVERSAL_MARKERS):
        return IntentPolarityOperation(
            operation="remove_negative_constraint",
            target_polarity="negative",
            replacement_polarity="positive",
            replacement_strength="acceptable",
        )
    return None


def negative_constraint_reversal_clauses(value: Any) -> list[str]:
    return [
        clause
        for clause in split_polarity_clauses(value)
        if has_negative_constraint_reversal(clause)
    ]


def has_negative_constraint_reversal(value: Any) -> bool:
    operation = parse_constraint_polarity_operation(value)
    return bool(operation and operation.operation == "remove_negative_constraint")
