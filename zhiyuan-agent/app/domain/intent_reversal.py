"""Helpers for explicit negative-requirement reversal.

These functions support phrases such as "不要排除民办" by extracting the
entities that should move from negative requirements back to positive scope.
They are domain helpers, not a model-node benchmark surface.
"""

from __future__ import annotations

from app.domain.intent_polarity import negative_constraint_reversal_clauses, parse_constraint_polarity_operation
from app.domain.major_entity_resolver import resolve_major_mentions_from_text
from app.domain.region_entity_resolver import resolve_region_entity, resolve_region_mentions_from_text
from app.domain.school_entity_resolver import compact_school_text, resolve_school_mention_spans_from_text


_SCHOOL_NATURE_ALIASES = {
    "公办": "公办",
    "公立": "公办",
    "公办院校": "公办",
    "公办学校": "公办",
    "公办大学": "公办",
    "公立院校": "公办",
    "公立学校": "公办",
    "公立大学": "公办",
    "民办": "民办",
    "私立": "民办",
    "民办院校": "民办",
    "民办学校": "民办",
    "民办大学": "民办",
    "私立院校": "民办",
    "私立学校": "民办",
    "私立大学": "民办",
}

_SPECIAL_LIMIT_ALIASES = {
    "高收费": "高收费",
    "高学费": "高收费",
    "高费": "高收费",
    "高高学费": "高收费",
    "稿费": "高收费",
    "学费高": "高收费",
    "中外合作": "中外合作",
    "中外合作办学": "中外合作",
    "合作办学": "中外合作",
    "国际项目": "中外合作",
}


def _compact_profile_text(value: object) -> str:
    return "".join(str(value or "").split())


def _region_reversal_values_from_utterance(
    utterance: str,
    *,
    excluded_compact_spans: list[tuple[int, int]] | None = None,
) -> list[str]:
    compact = compact_school_text(utterance)
    excluded_compact_spans = excluded_compact_spans or []
    values: list[str] = []
    seen_spans: set[tuple[int, int, str]] = set()
    for mention in resolve_region_mentions_from_text(utterance):
        entity = str(mention.canonical_name or "").strip()
        raw_text = str(getattr(mention, "raw_text", "") or entity).strip()
        compact_mention = compact_school_text(raw_text) or compact_school_text(entity)
        start = compact.find(compact_mention) if compact_mention else -1
        if start >= 0:
            search_start = 0
            while True:
                candidate_start = compact.find(compact_mention, search_start)
                if candidate_start < 0:
                    break
                candidate_end = candidate_start + len(compact_mention)
                search_start = candidate_start + 1
                span_key = (candidate_start, candidate_end, entity)
                if span_key in seen_spans:
                    continue
                seen_spans.add(span_key)
                if any(
                    candidate_start >= used_start and candidate_end <= used_end
                    for used_start, used_end in excluded_compact_spans
                ):
                    continue
                if entity and entity not in values:
                    values.append(entity)
            continue
        if entity and entity not in values:
            values.append(entity)
    return values


def _special_limit_reversal_values_from_utterance(utterance: str) -> list[str]:
    compact = _compact_profile_text(utterance)
    values: list[str] = []
    for alias, canonical in sorted(_SPECIAL_LIMIT_ALIASES.items(), key=lambda item: len(_compact_profile_text(item[0])), reverse=True):
        compact_alias = _compact_profile_text(alias)
        if compact_alias and compact_alias in compact and canonical not in values:
            values.append(canonical)
    return values


def negative_constraint_reversal_targets(utterance: str, batch: str = "01") -> dict[str, list[str]]:
    operation = parse_constraint_polarity_operation(utterance)
    if operation is None or operation.operation != "remove_negative_constraint":
        return {}
    reversal_clauses = negative_constraint_reversal_clauses(utterance)
    if not reversal_clauses:
        return {}
    targets: dict[str, list[str]] = {
        "major": [],
        "school": [],
        "region": [],
        "budget": [],
    }

    def append(kind: str, value: str) -> None:
        text = str(value or "").strip()
        if not text:
            return
        bucket = targets.setdefault(kind, [])
        if text not in bucket:
            bucket.append(text)

    for clause in reversal_clauses:
        for mention in resolve_major_mentions_from_text(clause, batch):
            entity = str(mention.canonical_name or "").strip()
            append("major", entity)
        school_name_spans = resolve_school_mention_spans_from_text(clause, batch)
        for value, _start, _end in school_name_spans:
            append("school", value)
        compact_clause = _compact_profile_text(clause)
        for value in ("公办", "民办"):
            if any(alias in compact_clause for alias, canonical in _SCHOOL_NATURE_ALIASES.items() if canonical == value):
                append("school", value)
        for value in _region_reversal_values_from_utterance(
            clause,
            excluded_compact_spans=[(start, end) for _name, start, end in school_name_spans],
        ):
            append("region", value)
        for value in _special_limit_reversal_values_from_utterance(clause):
            append("budget", value)
    return {key: values for key, values in targets.items() if values}
