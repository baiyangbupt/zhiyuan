from app.harness.turn_result import CodexTurnResult
from scripts.codex_semantic_smoke import (
    _build_base_payload,
    _collect_agent_messages,
    _recorded_mcp_events,
    reference_missing_scope_scenario,
)


def test_reference_missing_scope_smoke_scenario_has_candidate_context_and_clarification_expectation() -> None:
    context, message, expectation = reference_missing_scope_scenario()

    assert message == "查那几个学校去年的分数"
    assert expectation.response_type == "clarification"
    assert expectation.clarification_required is True
    assert expectation.required_message_fragments == {"甲大学", "乙大学", "school-1", "school-2"}
    assert expectation.required_entity_ids == set()
    assert context["candidateSet"]["items"][0]["entityId"] == "school-1"


def test_recorded_mcp_events_only_keeps_complete_tool_calls() -> None:
    events = _recorded_mcp_events(
        [
            {"name": "admission.get_history", "arguments": {"schoolId": "school-1"}},
            {"name": "", "arguments": {}},
            {"name": "catalog.search_schools", "arguments": "invalid"},
        ]
    )

    assert events == [
        {
            "type": "mcpToolCall",
            "toolName": "admission.get_history",
            "arguments": {"schoolId": "school-1"},
            "status": "completed",
        }
    ]


def test_build_base_payload_writes_agent_messages_on_every_status_path() -> None:
    """T009 改动 2 regression: `agentMessages` must never be success-path-only.

    Mirrors the earlier `evaluation`-key bug (see `_missing_output_evaluation`
    docstring) where a key only set on the success branch silently read back
    as absent on failure -- `d.get(...)` returned `None` instead of erroring,
    so the gap went unnoticed. Uses `in`, not `.get()`, so a missing key here
    fails loudly.
    """
    _, _, expectation = reference_missing_scope_scenario()

    failed_result = CodexTurnResult(status="failed", error_code="turn_timeout")
    completed_but_unparsed_result = CodexTurnResult(status="completed", output=None)
    completed_ok_result = CodexTurnResult(
        status="completed", output={"responseType": "text", "message": "ok"}
    )

    for result in (failed_result, completed_but_unparsed_result, completed_ok_result):
        payload = _build_base_payload(expectation, result)
        assert "agentMessages" in payload


def test_collect_agent_messages_reads_both_str_and_list_of_dict_text_shapes() -> None:
    """T009 改动 1 regression: `item["text"]` may be a plain str or a list of
    dicts, each carrying its fragment in its own "text" key (see
    app/harness/codex.py:301-315). A naive `str(item["text"])` on the list
    shape would silently produce `"[{'text': ...}]"` instead of raising --
    assert the actual string content comes back, not that.
    """
    events = [
        {
            "type": "item/completed",
            "item": {"type": "agentMessage", "id": "item-str", "text": "plain body text"},
        },
        {
            "type": "item/completed",
            "item": {
                "type": "agentMessage",
                "id": "item-list",
                "text": [{"text": "list body text"}],
            },
        },
    ]

    agent_messages = _collect_agent_messages(events)

    assert agent_messages[0] == {"itemId": "item-str", "text": "plain body text"}
    assert agent_messages[1] == {"itemId": "item-list", "text": "list body text"}
    assert agent_messages[1]["text"] != str(events[1]["item"]["text"])


def test_the_smoke_measures_what_production_returns_not_the_raw_model_value() -> None:
    """P2 成因 4：冒烟要量**生产返回的值**。

    生产把工具批次并进 `executionStatus`（只降不升）。不接这一步，两边量的就是两个
    不同的东西——模型说 `completed`、工具全失败时，生产红、冒烟绿。
    """
    from app.gateway.contracts import TurnOutput
    from scripts.codex_semantic_smoke import _trace_as_production_returns_it

    failed_tool = {
        "type": "mcpToolCall",
        "toolName": "admission.get_history",
        "arguments": {"schoolId": "school-1"},
        "status": "failed",
        "error": "backend unavailable",
    }
    optimistic = TurnOutput(response_type="text", message="都办好了", execution_status="completed")

    downgraded = _trace_as_production_returns_it({"events": [failed_tool]}, optimistic, entity_ids=[])

    # 断言**性质**（被拉低），不断言具体码：降到 blocked / partial / failed 里哪一个由
    # 批次报告的分类决定，那是另一个模块的语义，钉在这里会让两处一起变脆。
    # （反方向"工具成功不许抬高"由 `test_result_synthesis.py` 的单调性用例覆盖——
    #  那里能用最少的依赖构造出"成功的批次"，这里构造不出：少一个参数的调用会被批次
    #  判成 blocked，与工具本身的状态无关。）
    lowered = downgraded.as_payload()["executionStatus"]
    assert lowered not in (None, "", "completed"), f"工具失败必须把 completed 拉低，实得 {lowered!r}"
