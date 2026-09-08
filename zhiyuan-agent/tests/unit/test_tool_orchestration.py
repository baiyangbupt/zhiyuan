from app.engine.tool_orchestration import (
    build_invocation_key,
    is_duplicate_invocation,
    merge_tool_results,
    prepare_tool_invocation,
    render_tool_contracts,
)


def test_history_invocation_requires_all_authoritative_query_slots() -> None:
    preparation = prepare_tool_invocation(
        "admission.get_history",
        {
            "school_id": "school-1",
            "major_id": "major-cs",
            "area_id": "330000",
            "batch": "本科批",
            "year": 2025,
        },
    )

    assert preparation.ready is False
    assert preparation.missing_arguments == ("subjectType",)
    assert preparation.normalized_arguments["schoolId"] == "school-1"


def test_same_read_invocation_has_stable_deduplication_key() -> None:
    first = prepare_tool_invocation(
        "admission.get_history",
        {"schoolId": "school-1", "year": 2025},
    )
    second = prepare_tool_invocation(
        "admission.get_history",
        {"year": 2025, "schoolId": "school-1"},
    )

    assert first.invocation_key == second.invocation_key
    assert is_duplicate_invocation(
        "admission.get_history",
        {"school_id": "school-1", "year": 2025},
        [build_invocation_key("admission.get_history", first.normalized_arguments)],
    )


def test_tool_results_merge_by_stable_evidence_or_entity_id() -> None:
    merged = merge_tool_results(
        [
            {"evidenceId": "ev-1", "score": 600},
            {"evidenceId": "ev-1", "score": 612},
            {"entityId": "school-1", "name": "甲大学"},
            {"entityId": "school-1", "name": "甲大学（更新）"},
            {"status": "ok"},
        ]
    )

    assert merged == [
        {"evidenceId": "ev-1", "score": 612},
        {"entityId": "school-1", "name": "甲大学（更新）"},
        {"status": "ok"},
    ]


def test_tool_contract_text_emphasizes_no_incomplete_query() -> None:
    text = render_tool_contracts()

    assert "admission.get_history" in text
    assert "参数不完整时不得调用" in text
