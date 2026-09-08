from app.engine.tool_errors import classify_tool_error


def test_missing_parameter_is_blocked_and_requests_completion() -> None:
    decision = classify_tool_error("missing_parameter")

    assert decision is not None
    assert decision.execution_status == "blocked"
    assert "补充" in decision.next_step


def test_no_data_is_not_reported_as_backend_failure() -> None:
    decision = classify_tool_error("no_data")

    assert decision is not None
    assert decision.execution_status == "completed"
    assert "没有返回" in decision.limitation


def test_unknown_tool_error_fails_closed() -> None:
    decision = classify_tool_error("new_backend_error")

    assert decision is not None
    assert decision.execution_status == "failed"
