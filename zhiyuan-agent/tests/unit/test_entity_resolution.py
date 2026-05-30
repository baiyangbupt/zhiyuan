from __future__ import annotations

from app.domain.major_entity_resolver import (
    append_major_mentions_to_payload,
    build_major_relation_notes,
    major_alias_variants_for_name,
    resolve_major_entity,
    resolve_major_mentions_from_text,
)
from app.domain.school_entity_resolver import resolve_school_entity
from app.domain.school_major_ref_resolver import resolve_school_major_ref


def test_resolve_major_entity_handles_common_single_alias():
    result = resolve_major_entity("计科", "01")

    assert result.best is not None
    assert result.best.level == "level3"
    assert result.best.canonical_name == "计算机科学与技术"
    assert result.best.source == "alias"


def test_resolve_major_entity_keeps_broad_alias_as_candidates():
    result = resolve_major_entity("财会", "01")

    names = result.canonical_names
    assert "工商管理类" in names
    assert "会计学" in names
    assert "财务管理" in names
    assert "审计学" in names
    assert result.ambiguous is True


def test_resolve_major_mentions_supports_mixed_positive_negative_sentence():
    positive_mentions = resolve_major_mentions_from_text("会计审计还行", "01")
    negative_mentions = resolve_major_mentions_from_text("土木别要", "01")
    payload: dict[str, list[str]] = {}

    append_major_mentions_to_payload(payload, positive_mentions, negative=False)
    append_major_mentions_to_payload(payload, negative_mentions, negative=True)

    assert payload == {
        "level3": ["会计学", "审计学"],
        "negative_level3": ["土木工程"],
    }


def test_major_alias_variants_for_name_uses_common_alias_table():
    assert "审计" in major_alias_variants_for_name("审计学", "01")
    assert "软工" in major_alias_variants_for_name("软件工程", "01")
    assert "国贸" in major_alias_variants_for_name("国际经济与贸易", "01")
    assert "新媒体" in major_alias_variants_for_name("网络与新媒体", "01")


def test_build_major_relation_notes_uses_catalog_parent_child_relationship():
    notes = build_major_relation_notes(
        {
            "negative_level1": ["医学"],
            "negative_level2": ["中医学类"],
            "negative_level3": ["中医学"],
        },
        "01",
    )

    assert any("中医学类属于医学门类" in note for note in notes)
    assert any("中医学属于中医学类" in note for note in notes)


def test_resolve_school_entity_handles_unambiguous_short_alias():
    result = resolve_school_entity("广西师大", "01")

    assert result.best is not None
    assert result.best.canonical_name == "广西师范大学"


def test_resolve_school_entity_marks_ambiguous_short_alias():
    result = resolve_school_entity("湖工", "01")

    assert result.ambiguous is True
    assert "湖北工程学院" in result.canonical_names
    assert "湖北工业大学" in result.canonical_names


def test_resolve_school_major_ref_handles_attached_short_names():
    result = resolve_school_major_ref("广西师大统计", "01")

    assert result.can_query is True
    assert result.school_keywords == ["广西师范大学"]
    assert result.major_keywords == ["统计学"]


def test_resolve_school_major_ref_marks_ambiguous_school_alias():
    result = resolve_school_major_ref("湖工计科", "01")

    assert result.ambiguous is True
    assert result.school_keywords == []
    assert result.major_keywords == ["计算机科学与技术"]
