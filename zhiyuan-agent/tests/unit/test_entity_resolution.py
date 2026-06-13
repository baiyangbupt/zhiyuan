from __future__ import annotations

from app.domain.major_entity_resolver import (
    append_major_mentions_to_payload,
    build_major_relation_notes,
    refine_major_intent_payload_by_explicit_mentions,
    major_alias_variants_for_name,
    resolve_major_entity,
    resolve_major_mentions_from_text,
)
from app.domain.region_entity_resolver import contains_concrete_region_mention, resolve_region_entity
from app.domain.school_entity_resolver import resolve_school_entity
from app.domain.school_major_ref_resolver import resolve_school_major_ref


def test_resolve_major_entity_handles_common_single_alias():
    result = resolve_major_entity("计科", "01")

    assert result.best is not None
    assert result.best.level == "level3"
    assert result.best.canonical_name == "计算机科学与技术"
    assert result.best.source == "alias"


def test_resolve_major_mentions_keeps_category_token_alias_broad():
    mentions = resolve_major_mentions_from_text("后面想重点看看计算机和电子信息方向", "01")

    assert [mention.canonical_name for mention in mentions] == ["计算机类", "电子信息类"]
    assert [mention.level for mention in mentions] == ["level2", "level2"]


def test_resolve_major_mentions_keeps_specific_alias_concrete():
    mentions = resolve_major_mentions_from_text("计科和会计也可以看看", "01")

    assert [mention.canonical_name for mention in mentions] == ["计算机科学与技术", "会计学"]
    assert [mention.level for mention in mentions] == ["level3", "level3"]


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


def test_refine_major_intent_does_not_expand_concrete_major_to_parent_discipline():
    refined = refine_major_intent_payload_by_explicit_mentions(
        {"level1": ["医学"], "level3": ["临床医学"]},
        "我只想学临床医学，其他专业先不要",
        "01",
    )

    assert refined == {"level3": ["临床医学"]}


def test_refine_major_intent_keeps_explicit_parent_discipline():
    refined = refine_major_intent_payload_by_explicit_mentions(
        {"level1": ["医学"], "negative_level1": ["工学"]},
        "不考虑工科，只考虑医学类",
        "01",
    )

    assert refined == {"level1": ["医学"], "negative_level1": ["工学"]}


def test_resolve_major_mentions_prefers_common_alias_over_auto_alias():
    mentions = resolve_major_mentions_from_text("新媒体和跨电哪个更适合", "01")

    assert [mention.canonical_name for mention in mentions] == ["网络与新媒体", "跨境电子商务"]
    assert [mention.source for mention in mentions] == ["alias", "alias"]


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


def test_build_major_relation_notes_explains_teacher_track_is_not_all_teacher_colleges():
    notes = build_major_relation_notes({"negative_level2": ["教育学类"]}, "01")

    assert any("师范院校里的非师范专业不等于都要排除" in note for note in notes)


def test_resolve_school_entity_handles_unambiguous_short_alias():
    result = resolve_school_entity("广西师大", "01")

    assert result.best is not None
    assert result.best.canonical_name == "广西师范大学"


def test_resolve_school_entity_marks_ambiguous_short_alias():
    result = resolve_school_entity("湖工", "01")

    assert result.ambiguous is True
    assert "湖北工程学院" in result.canonical_names
    assert "湖北工业大学" in result.canonical_names


def test_resolve_region_entity_handles_common_province_alias():
    result = resolve_region_entity("内蒙", expected_level="province")

    assert result.best is not None
    assert result.best.canonical_name == "内蒙古"
    assert result.best.level == "province"
    assert result.best.source == "alias"


def test_resolve_region_entity_handles_area_aliases():
    south = resolve_region_entity("南方")
    north = resolve_region_entity("北方地区")

    assert south.best is not None
    assert south.best.canonical_name == "南方"
    assert south.best.level == "area"
    assert north.best is not None
    assert north.best.canonical_name == "北方"
    assert north.best.level == "area"


def test_contains_concrete_region_mention_distinguishes_abstract_region_language():
    assert contains_concrete_region_mention("广西贵州内蒙这些要不要放") is True
    assert contains_concrete_region_mention("省外可以，但太偏的地方不想去") is False
    assert contains_concrete_region_mention("南方可以，北方先别考虑") is True


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
