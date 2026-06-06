"""Reusable major entity resolution backed by the official major hierarchy."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from app.data.major_aliases import CATEGORY_PREFERRED_MAJOR_ALIASES, COMMON_MAJOR_ALIAS_TABLE
from app.data.major_data import (
    associate_category_line_map,
    associate_major_line_map,
    associate_major_mappings,
    associate_subcategory_line_map,
    bachelor_category_line_map,
    bachelor_major_line_map,
    bachelor_major_mappings,
    bachelor_subcategory_line_map,
)
from app.domain.entity_resolution import EntityResolutionCandidate, EntityResolutionResult


def compact_major_text(value: Any) -> str:
    return "".join(str(value or "").split()).lower()


def major_name_sets_for_batch(batch: str | None) -> dict[str, set[str]]:
    if batch and batch != "01":
        return {
            "level1": set(associate_category_line_map.keys()),
            "level2": set(associate_subcategory_line_map.keys()),
            "level3": set(associate_major_line_map.keys()),
        }
    return {
        "level1": set(bachelor_category_line_map.keys()),
        "level2": set(bachelor_subcategory_line_map.keys()),
        "level3": set(bachelor_major_line_map.keys()),
    }


def major_parent_mappings_for_batch(batch: str | None) -> dict[str, dict[str, str]]:
    return associate_major_mappings if batch and batch != "01" else bachelor_major_mappings


def _auto_alias_candidates_for_major_name(name: str, level: str) -> set[str]:
    compact_name = compact_major_text(name)
    if len(compact_name) < 3:
        return set()
    if level == "level2":
        suffixes = ("学类", "科学类", "工程类", "类")
    elif level == "level3":
        suffixes = ("科学与技术", "工程", "技术", "管理", "学")
    else:
        suffixes = ()

    aliases: set[str] = set()
    for suffix in suffixes:
        compact_suffix = compact_major_text(suffix)
        if compact_suffix and compact_name.endswith(compact_suffix):
            alias = compact_name[: -len(compact_suffix)]
            if len(alias) >= 2:
                aliases.add(alias)
    return aliases


@lru_cache(maxsize=2)
def auto_major_alias_index_for_batch(batch: str | None) -> dict[str, tuple[str, str]]:
    available = major_name_sets_for_batch(batch)
    raw_index: dict[str, list[tuple[str, str]]] = {}
    for level in ("level2", "level3"):
        for name in available[level]:
            for alias in _auto_alias_candidates_for_major_name(name, level):
                raw_index.setdefault(alias, []).append((level, name))

    standard_names = {
        compact_major_text(name)
        for names in available.values()
        for name in names
    }
    deterministic: dict[str, tuple[str, str]] = {}
    for alias, candidates in raw_index.items():
        unique_candidates = list(dict.fromkeys(candidates))
        if len(unique_candidates) != 1:
            continue
        if alias in standard_names:
            continue
        deterministic[alias] = unique_candidates[0]
    return deterministic


def _candidate(
    *,
    raw_text: str,
    canonical_name: str,
    level: str,
    source: str,
    confidence: str = "high",
) -> EntityResolutionCandidate:
    return EntityResolutionCandidate(
        entity_type="major",
        raw_text=raw_text,
        canonical_name=canonical_name,
        level=level,
        source=source,  # type: ignore[arg-type]
        confidence=confidence,  # type: ignore[arg-type]
    )


def _is_level2_category_token_alias(alias: str, level2_names: list[str]) -> bool:
    compact_alias = compact_major_text(alias)
    if not compact_alias:
        return False
    if compact_alias not in CATEGORY_PREFERRED_MAJOR_ALIASES:
        return False
    return any(compact_major_text(_major_target_token(name)) == compact_alias for name in level2_names)


def resolve_major_entity(text: str, batch: str | None = "01") -> EntityResolutionResult:
    """Resolve a single user-facing major expression to official hierarchy nodes.

    The resolver is deterministic and catalog-backed. It returns multiple
    candidates for intentionally broad aliases such as "财会" instead of choosing
    an arbitrary concrete major.
    """

    raw_text = str(text or "").strip()
    compact = compact_major_text(raw_text)
    if not compact:
        return EntityResolutionResult(raw_text=raw_text, entity_type="major")

    available = major_name_sets_for_batch(batch)
    candidates: list[EntityResolutionCandidate] = []
    seen: set[tuple[str, str]] = set()

    def append(level: str, name: str, source: str, confidence: str = "high") -> None:
        if name not in available.get(level, set()):
            return
        key = (level, name)
        if key in seen:
            return
        candidates.append(
            _candidate(
                raw_text=raw_text,
                canonical_name=name,
                level=level,
                source=source,
                confidence=confidence,
            )
        )
        seen.add(key)

    for level in ("level1", "level2", "level3"):
        for name in available[level]:
            if compact_major_text(name) == compact:
                append(level, name, "exact")

    aliases_by_level = COMMON_MAJOR_ALIAS_TABLE.get(compact)
    if aliases_by_level:
        level1_candidates = [name for name in aliases_by_level.get("level1", ()) if name in available["level1"]]
        level2_candidates = [name for name in aliases_by_level.get("level2", ()) if name in available["level2"]]
        level3_candidates = [name for name in aliases_by_level.get("level3", ()) if name in available["level3"]]
        if len(level3_candidates) == 1 and not _is_level2_category_token_alias(raw_text, level2_candidates):
            append("level3", level3_candidates[0], "alias")
        else:
            for name in level1_candidates:
                append("level1", name, "alias")
            for name in level2_candidates:
                append("level2", name, "alias")
            for name in level3_candidates:
                append("level3", name, "alias")

    auto_alias = auto_major_alias_index_for_batch(batch).get(compact)
    if auto_alias:
        level, name = auto_alias
        append(level, name, "auto_alias")

    ambiguous = len({(candidate.level, candidate.canonical_name) for candidate in candidates}) > 1
    return EntityResolutionResult(
        raw_text=raw_text,
        entity_type="major",
        candidates=tuple(candidates),
        ambiguous=ambiguous,
    )


def resolve_major_mentions_from_text(text: str, batch: str | None = "01") -> list[EntityResolutionCandidate]:
    """Find catalog-backed major mentions in a short user utterance."""

    compact_text = compact_major_text(text)
    if not compact_text:
        return []

    available = major_name_sets_for_batch(batch)
    spans: list[tuple[int, int, EntityResolutionCandidate]] = []

    def add_span(start: int, end: int, candidate: EntityResolutionCandidate) -> None:
        spans.append((start, end, candidate))

    for alias in COMMON_MAJOR_ALIAS_TABLE:
        compact_alias = compact_major_text(alias)
        if not compact_alias:
            continue
        start = compact_text.find(compact_alias)
        if start < 0:
            continue
        result = resolve_major_entity(alias, batch)
        candidates = list(result.candidates)
        level2_candidates = [candidate for candidate in candidates if candidate.level == "level2"]
        level3_candidates = [candidate for candidate in candidates if candidate.level == "level3"]
        if level2_candidates and _is_level2_category_token_alias(alias, [candidate.canonical_name for candidate in level2_candidates]):
            candidates = level2_candidates
        elif len(level3_candidates) > 1 and level2_candidates:
            candidates = level2_candidates
        for candidate in candidates:
            add_span(start, start + len(compact_alias), candidate)

    for alias, (level, name) in auto_major_alias_index_for_batch(batch).items():
        start = compact_text.find(alias)
        if start >= 0 and name in available[level]:
            add_span(
                start,
                start + len(alias),
                _candidate(raw_text=alias, canonical_name=name, level=level, source="auto_alias"),
            )

    for level in ("level2", "level3", "level1"):
        for name in available[level]:
            compact_name = compact_major_text(name)
            if len(compact_name) < 2:
                continue
            start = compact_text.find(compact_name)
            if start >= 0:
                add_span(
                    start,
                    start + len(compact_name),
                    _candidate(raw_text=name, canonical_name=name, level=level, source="exact"),
                )

    priority = {"level3": 0, "level2": 1, "level1": 2}
    source_priority = {"exact": 0, "alias": 1, "catalog": 2, "extractor": 2, "auto_alias": 3}
    ordered = sorted(
        spans,
        key=lambda item: (
            -(item[1] - item[0]),
            item[0],
            priority.get(item[2].level or "", 9),
            source_priority.get(str(item[2].source or ""), 9),
            item[2].canonical_name,
        ),
    )
    selected: list[tuple[int, int, EntityResolutionCandidate]] = []
    for start, end, candidate in ordered:
        if any(not (end <= kept_start or start >= kept_end) for kept_start, kept_end, _ in selected):
            continue
        selected.append((start, end, candidate))
    selected.sort(key=lambda item: item[0])

    result: list[EntityResolutionCandidate] = []
    seen: set[tuple[str | None, str]] = set()
    for _, _, candidate in selected:
        key = (candidate.level, candidate.canonical_name)
        if key in seen:
            continue
        result.append(candidate)
        seen.add(key)
    return result


def major_alias_variants_for_name(name: Any, batch: str | None = "01") -> list[str]:
    """Return deterministic user-facing aliases for an official major name."""

    raw_name = str(name or "").strip()
    if not raw_name:
        return []
    base_name = re_split_major_base(raw_name)
    available = major_name_sets_for_batch(batch)
    variants: list[str] = []

    for alias, aliases_by_level in COMMON_MAJOR_ALIAS_TABLE.items():
        for level, names in aliases_by_level.items():
            if base_name in names and base_name in available.get(level, set()):
                variants.append(alias)

    for alias, (level, canonical_name) in auto_major_alias_index_for_batch(batch).items():
        if canonical_name == base_name and canonical_name in available.get(level, set()):
            variants.append(alias)

    target_token = _major_target_token(base_name)
    if target_token and target_token != base_name:
        variants.append(target_token)
    return list(dict.fromkeys(variant for variant in variants if variant and variant != raw_name and variant != base_name))


def re_split_major_base(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return text.split("（", 1)[0].split("(", 1)[0].strip()


def _major_target_token(value: str) -> str:
    text = re_split_major_base(value)
    if text.endswith("类"):
        return text[:-1].strip()
    if text.endswith("学") and len(text) > 2:
        return text[:-1].strip()
    return text


def append_major_mentions_to_payload(
    payload: dict[str, list[str]],
    mentions: list[EntityResolutionCandidate],
    *,
    negative: bool,
) -> None:
    for mention in mentions:
        if mention.level not in {"level1", "level2", "level3"}:
            continue
        key = f"negative_{mention.level}" if negative else mention.level
        bucket = payload.setdefault(key, [])
        if mention.canonical_name not in bucket:
            bucket.append(mention.canonical_name)


_MAJOR_INTENT_POLARITY_GROUPS = (
    ("level3", "level2", "level1"),
    ("negative_level3", "negative_level2", "negative_level1"),
)
_MAJOR_INTENT_KEY_TO_LEVEL = {
    "level1": "level1",
    "level2": "level2",
    "level3": "level3",
    "negative_level1": "level1",
    "negative_level2": "level2",
    "negative_level3": "level3",
}
_MAJOR_INTENT_LEVEL_TO_KEYS = {
    False: {"level1": "level1", "level2": "level2", "level3": "level3"},
    True: {"level1": "negative_level1", "level2": "negative_level2", "level3": "negative_level3"},
}


def _as_major_string_list(values: Any) -> list[str]:
    if values is None:
        return []
    if isinstance(values, str):
        stripped = values.strip()
        return [stripped] if stripped else []
    if not isinstance(values, (list, tuple, set)):
        stripped = str(values or "").strip()
        return [stripped] if stripped else []
    result: list[str] = []
    for value in values:
        stripped = str(value or "").strip()
        if stripped and stripped not in result:
            result.append(stripped)
    return result


def dedupe_major_intent_payload_across_levels(payload: dict[str, Any] | None) -> dict[str, list[str]] | None:
    """Remove duplicate names across official major hierarchy buckets.

    The same Chinese name can appear at multiple official levels, for example
    "法学" can be both a discipline and a concrete major. When both appear under
    the same polarity in one extracted payload, keep the more specific bucket so
    the confirmation card does not show duplicate-looking entries.
    """

    if not payload:
        return None

    result: dict[str, list[str]] = {}
    consumed_keys: set[str] = set()
    for group in _MAJOR_INTENT_POLARITY_GROUPS:
        seen_names: set[str] = set()
        for key in group:
            consumed_keys.add(key)
            values = _as_major_string_list(payload.get(key))
            if not values:
                continue
            bucket: list[str] = []
            for value in values:
                name = re_split_major_base(value)
                if not name or name in seen_names:
                    continue
                bucket.append(name)
                seen_names.add(name)
            if bucket:
                result[key] = bucket

    for key, values in payload.items():
        if key in consumed_keys:
            continue
        normalized_values = _as_major_string_list(values)
        if normalized_values:
            result[key] = normalized_values
    return result or None


def _resolve_major_for_intent_bucket(
    name: str,
    *,
    expected_level: str | None,
    batch: str | None,
) -> tuple[str | None, str]:
    base_name = re_split_major_base(name)
    if not base_name:
        return expected_level, ""

    try:
        resolved = resolve_major_entity(base_name, batch)
    except Exception:
        return expected_level, base_name

    candidates = [
        candidate
        for candidate in resolved.candidates
        if candidate.level in {"level1", "level2", "level3"} and str(candidate.canonical_name or "").strip()
    ]
    if not candidates:
        return expected_level, base_name

    if expected_level:
        exact_expected = [
            candidate
            for candidate in candidates
            if candidate.level == expected_level and compact_major_text(candidate.canonical_name) == compact_major_text(base_name)
        ]
        if exact_expected:
            return str(exact_expected[0].level), str(exact_expected[0].canonical_name).strip()

    exact_candidates = [
        candidate
        for candidate in candidates
        if compact_major_text(candidate.canonical_name) == compact_major_text(base_name)
    ]
    if len(exact_candidates) == 1:
        return str(exact_candidates[0].level), str(exact_candidates[0].canonical_name).strip()

    unique_candidates = list(
        dict.fromkeys(
            (
                str(candidate.level or ""),
                str(candidate.canonical_name or "").strip(),
            )
            for candidate in candidates
        )
    )
    if len(unique_candidates) == 1:
        level, canonical_name = unique_candidates[0]
        return level, canonical_name

    return expected_level, base_name


def normalize_major_intent_payload_by_catalog(
    payload: dict[str, Any] | None,
    batch: str | None = "01",
) -> dict[str, list[str]] | None:
    """Put major intent names into official level1/2/3 buckets.

    LLM extraction may place an official category name in a concrete-major
    bucket, or the opposite. This pass is deterministic and catalog-backed; it
    only rewrites the bucket when the official hierarchy can identify the entity
    type.
    """

    if not payload:
        return None

    normalized: dict[str, list[str]] = {}
    for key, values in payload.items():
        names = _as_major_string_list(values)
        if not names:
            continue
        expected_level = _MAJOR_INTENT_KEY_TO_LEVEL.get(key)
        is_negative = key.startswith("negative_")
        if expected_level is None:
            normalized[key] = list(dict.fromkeys(names))
            continue
        for name in names:
            level, canonical_name = _resolve_major_for_intent_bucket(
                name,
                expected_level=expected_level,
                batch=batch,
            )
            target_key = _MAJOR_INTENT_LEVEL_TO_KEYS[is_negative].get(level or expected_level, key)
            if not canonical_name:
                continue
            bucket = normalized.setdefault(target_key, [])
            if canonical_name not in bucket:
                bucket.append(canonical_name)

    return dedupe_major_intent_payload_across_levels(normalized)


def _major_mentions_by_level(text: str, batch: str | None) -> dict[str, set[str]]:
    mentions: dict[str, set[str]] = {"level1": set(), "level2": set(), "level3": set()}
    for mention in resolve_major_mentions_from_text(text, batch):
        level = str(mention.level or "")
        name = str(mention.canonical_name or "").strip()
        if level in mentions and name:
            mentions[level].add(name)
    return mentions


def refine_major_intent_payload_by_explicit_mentions(
    payload: dict[str, Any] | None,
    latest_utterance: str,
    batch: str | None = "01",
) -> dict[str, list[str]] | None:
    """Keep user-stated major entity boundaries when model output is broader.

    If the user said a concrete major such as "工商管理" but the model inferred
    its parent "工商管理类", narrow the pending update back to the concrete
    major. If the user explicitly said the category, keep the category.
    """

    normalized = normalize_major_intent_payload_by_catalog(payload, batch)
    if not normalized or not str(latest_utterance or "").strip():
        return normalized

    mentions = _major_mentions_by_level(latest_utterance, batch)
    mappings = major_parent_mappings_for_batch(batch)
    available = major_name_sets_for_batch(batch)
    compact_utterance = compact_major_text(latest_utterance)
    level3_to_level2 = mappings.get("level3_to_level2", {})
    level2_to_level1 = mappings.get("level2_to_level1", {})
    refined = {key: list(values) for key, values in normalized.items()}

    def explicitly_mentions_name(name: str) -> bool:
        compact_name = compact_major_text(name)
        return bool(compact_name and compact_name in compact_utterance)

    for level2_key, level3_key in (("level2", "level3"), ("negative_level2", "negative_level3")):
        level2_values = _as_major_string_list(refined.get(level2_key))
        level3_values = _as_major_string_list(refined.get(level3_key))
        explicit_level3 = mentions["level3"]
        explicit_level2 = mentions["level2"]
        explicit_level3_parent_level1 = {
            level2_to_level1.get(level3_to_level2.get(name) or "")
            for name in explicit_level3
            if level2_to_level1.get(level3_to_level2.get(name) or "")
        }
        if level2_values and explicit_level3:
            level3_bucket = list(level3_values)
            for name in explicit_level3:
                parent = level3_to_level2.get(name)
                parent_level1 = level2_to_level1.get(parent or "")
                broad_same_discipline = (
                    parent_level1
                    and not explicit_level2
                    and any(level2_to_level1.get(level2) == parent_level1 for level2 in level2_values)
                )
                if (parent in level2_values or broad_same_discipline) and name not in level3_bucket:
                    level3_bucket.append(name)
            if level3_bucket:
                refined[level3_key] = level3_bucket
                level3_values = level3_bucket
        if not level2_values or not level3_values:
            continue
        child_parent_values = {level3_to_level2.get(name) for name in level3_values}
        kept = []
        for name in level2_values:
            if name in explicit_level2 or (name in available["level2"] and explicitly_mentions_name(name)):
                kept.append(name)
                continue
            if name not in available["level2"] and level3_values:
                continue
            if (
                name not in child_parent_values
                and (
                    not explicit_level3_parent_level1
                    or level2_to_level1.get(name) not in explicit_level3_parent_level1
                )
            ):
                kept.append(name)
        if kept:
            refined[level2_key] = kept
        else:
            refined.pop(level2_key, None)

    for level1_key, level2_key, level3_key in (
        ("level1", "level2", "level3"),
        ("negative_level1", "negative_level2", "negative_level3"),
    ):
        level1_values = _as_major_string_list(refined.get(level1_key))
        if not level1_values:
            continue
        explicit_level1 = mentions["level1"]
        child_parent_values: set[str | None] = {
            level2_to_level1.get(name)
            for name in _as_major_string_list(refined.get(level2_key))
        }
        child_parent_values.update(
            level2_to_level1.get(level3_to_level2.get(name) or "")
            for name in _as_major_string_list(refined.get(level3_key))
        )
        kept = []
        for name in level1_values:
            if name in explicit_level1 or (name in available["level1"] and explicitly_mentions_name(name)):
                kept.append(name)
                continue
            if name not in available["level1"] and (
                _as_major_string_list(refined.get(level2_key))
                or _as_major_string_list(refined.get(level3_key))
            ):
                continue
            if name not in child_parent_values:
                kept.append(name)
        if kept:
            refined[level1_key] = kept
        else:
            refined.pop(level1_key, None)

    return dedupe_major_intent_payload_across_levels(refined)


def canonicalize_major_intent_payload(
    payload: dict[str, Any] | None,
    latest_utterance: str = "",
    batch: str | None = "01",
) -> dict[str, list[str]] | None:
    """Normalize major intent payload for confirmation cards and plan actions."""

    normalized = normalize_major_intent_payload_by_catalog(payload, batch)
    if not latest_utterance:
        return normalized
    return refine_major_intent_payload_by_explicit_mentions(normalized, latest_utterance, batch)


def build_major_relation_notes(major_intents: dict[str, list[str]] | None, batch: str | None = "01") -> list[str]:
    """Build generic parent/child notes from the official major hierarchy."""

    if not major_intents:
        return []
    mappings = major_parent_mappings_for_batch(batch)
    level2_to_level1 = mappings.get("level2_to_level1", {})
    level3_to_level2 = mappings.get("level3_to_level2", {})

    notes: list[str] = []
    negative_level1 = list(major_intents.get("negative_level1") or [])
    negative_level2 = list(major_intents.get("negative_level2") or [])
    negative_level3 = list(major_intents.get("negative_level3") or [])

    if "教育学类" in negative_level2:
        notes.append("如果核心是不想当老师，教育学类和师范培养方向需要谨慎；但师范院校里的非师范专业不等于都要排除。")

    for level2 in negative_level2:
        parent = level2_to_level1.get(level2)
        if parent and parent in negative_level1:
            notes.append(f"{level2}属于{parent}门类；如果确认排除{parent}，这个专业类也会一并避开。")

    for level3 in negative_level3:
        parent_level2 = level3_to_level2.get(level3)
        parent_level1 = level2_to_level1.get(parent_level2 or "")
        if parent_level2 and parent_level2 in negative_level2:
            notes.append(f"{level3}属于{parent_level2}；如果确认排除{parent_level2}，这个具体专业也会一并避开。")
        elif parent_level1 and parent_level1 in negative_level1:
            notes.append(f"{level3}属于{parent_level1}门类；如果确认排除{parent_level1}，这个具体专业也会一并避开。")

    return list(dict.fromkeys(notes))
