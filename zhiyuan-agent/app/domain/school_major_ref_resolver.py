"""Shared school+major reference resolution for plan operations."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.domain.entity_resolution import EntityResolutionCandidate
from app.domain.major_entity_resolver import (
    compact_major_text,
    resolve_major_entity,
    resolve_major_mentions_from_text,
)
from app.domain.school_entity_resolver import compact_school_text, resolve_school_entity


_SEPARATORS = ("的", ".", "。", "-", "－", "—", "、", ",", "，", ":", "：")


@dataclass(frozen=True)
class SchoolMajorReferenceResolution:
    raw_text: str
    school_text: str = ""
    major_text: str = ""
    school_candidates: tuple[EntityResolutionCandidate, ...] = ()
    major_candidates: tuple[EntityResolutionCandidate, ...] = ()
    school_ambiguous: bool = False
    major_ambiguous: bool = False
    source: str = ""

    @property
    def ambiguous(self) -> bool:
        return self.school_ambiguous or self.major_ambiguous

    @property
    def school_keywords(self) -> list[str]:
        if self.school_ambiguous:
            return []
        return _unique_names(self.school_candidates)

    @property
    def major_keywords(self) -> list[str]:
        if self.major_ambiguous:
            return []
        names = _unique_names(self.major_candidates)
        if names:
            return names
        stripped = self.major_text.strip()
        return [stripped] if stripped else []

    @property
    def can_query(self) -> bool:
        return bool(self.school_keywords and self.major_keywords)


def _unique_names(candidates: tuple[EntityResolutionCandidate, ...]) -> list[str]:
    names: list[str] = []
    for candidate in candidates:
        name = str(candidate.canonical_name or "").strip()
        if name and name not in names:
            names.append(name)
    return names


def _major_candidates_for_text(text: str, batch: str | None) -> tuple[tuple[EntityResolutionCandidate, ...], bool]:
    result = resolve_major_entity(text, batch)
    candidates = list(result.candidates)
    ambiguous = result.ambiguous
    if not candidates:
        candidates = resolve_major_mentions_from_text(text, batch)
        unique_keys = {(candidate.level, candidate.canonical_name) for candidate in candidates}
        ambiguous = len(unique_keys) > 1
    return tuple(candidates), ambiguous


def _build_resolution(
    raw_text: str,
    school_text: str,
    major_text: str,
    *,
    batch: str | None,
    source: str,
) -> SchoolMajorReferenceResolution | None:
    school_part = school_text.strip()
    major_part = major_text.strip()
    if not school_part or not major_part:
        return None

    school_result = resolve_school_entity(school_part, batch)
    if not school_result.candidates:
        return None

    major_candidates, major_ambiguous = _major_candidates_for_text(major_part, batch)
    return SchoolMajorReferenceResolution(
        raw_text=raw_text,
        school_text=school_part,
        major_text=major_part,
        school_candidates=tuple(school_result.candidates),
        major_candidates=major_candidates,
        school_ambiguous=school_result.ambiguous,
        major_ambiguous=major_ambiguous,
        source=source,
    )


def _candidate_score(candidate: SchoolMajorReferenceResolution) -> tuple[int, int, int, int]:
    school_precise = 1 if len(candidate.school_keywords) == 1 else 0
    major_precise = 1 if len(candidate.major_keywords) == 1 and candidate.major_candidates else 0
    ambiguity_penalty = int(candidate.school_ambiguous) + int(candidate.major_ambiguous)
    return (
        school_precise + major_precise,
        len(compact_school_text(candidate.school_text)),
        len(compact_major_text(candidate.major_text)),
        -ambiguity_penalty,
    )


def _split_by_separators(text: str) -> list[tuple[str, str]]:
    splits: list[tuple[str, str]] = []
    for separator in _SEPARATORS:
        if separator not in text:
            continue
        left, right = text.split(separator, 1)
        if left.strip() and right.strip():
            splits.append((left.strip(), right.strip()))
    return splits


def resolve_school_major_ref(value: Any, batch: str | None = "01") -> SchoolMajorReferenceResolution:
    """Resolve a user-facing school+major reference without choosing a volunteer.

    This layer only normalizes entity hints such as "广西师大统计" to
    "广西师范大学 + 统计学". The caller must still match these hints against the
    current candidate pool or ordered plan and require a single real volunteerId
    before mutating a plan.
    """

    raw_text = str(value or "").strip()
    if not raw_text:
        return SchoolMajorReferenceResolution(raw_text="")

    explicit_candidates = [
        candidate
        for left, right in _split_by_separators(raw_text)
        if (candidate := _build_resolution(raw_text, left, right, batch=batch, source="separator")) is not None
    ]
    if explicit_candidates:
        return max(explicit_candidates, key=_candidate_score)

    compact_text = re.sub(r"\s+", "", raw_text)
    split_candidates: list[SchoolMajorReferenceResolution] = []
    for index in range(2, len(compact_text) - 1):
        left = compact_text[:index]
        right = compact_text[index:]
        candidate = _build_resolution(raw_text, left, right, batch=batch, source="boundary_scan")
        if candidate is not None:
            split_candidates.append(candidate)

    if not split_candidates:
        return SchoolMajorReferenceResolution(raw_text=raw_text)
    return max(split_candidates, key=_candidate_score)
