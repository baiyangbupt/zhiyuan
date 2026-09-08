from scripts.codex_semantic_smoke import reference_missing_scope_scenario


def test_reference_missing_scope_smoke_scenario_has_candidate_context_and_clarification_expectation() -> None:
    context, message, expectation = reference_missing_scope_scenario()

    assert message == "查那几个学校去年的分数"
    assert expectation.response_type == "clarification"
    assert expectation.clarification_required is True
    assert expectation.required_message_fragments == {"甲大学", "乙大学", "school-1", "school-2"}
    assert expectation.required_entity_ids == set()
    assert context["candidateSet"]["items"][0]["entityId"] == "school-1"
