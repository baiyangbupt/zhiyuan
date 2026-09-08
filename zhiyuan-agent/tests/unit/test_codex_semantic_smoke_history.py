from scripts.codex_semantic_smoke import complete_history_scenario


def test_complete_history_scenario_requires_read_tool_and_no_clarification() -> None:
    _, message, expectation = complete_history_scenario()

    assert "2025" in message
    assert expectation.required_tool_names == {"admission.get_history"}
    assert expectation.clarification_required is False
    assert expectation.response_type == "fact"
