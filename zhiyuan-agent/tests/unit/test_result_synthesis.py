from app.engine.result_synthesis import synthesize_execution_status
from app.gateway.contracts import TurnOutput


def test_partial_batch_status_is_visible_without_changing_facts() -> None:
    output = TurnOutput(responseType="fact", message="已返回部分结果", evidenceRefs=[
        {"evidenceId": "ev-1", "sourceLevel": "authoritative", "dataVersion": "v1"}
    ])

    result = synthesize_execution_status(output, {"status": "partial"})

    assert result.execution_status == "partial"
    assert result.evidence_refs == output.evidence_refs
    assert result.next_step == "确认是否继续处理未完成的查询。"


def test_blocked_batch_status_exposes_next_step() -> None:
    output = TurnOutput(responseType="clarification", message="还缺少参数")

    result = synthesize_execution_status(output, {"status": "blocked"})

    assert result.execution_status == "blocked"
    assert result.next_step == "请补充缺失参数后继续。"


def test_failed_batch_status_never_claims_complete_fact() -> None:
    output = TurnOutput(responseType="text", message="暂未完成查询")

    result = synthesize_execution_status(output, {"status": "failed"})

    assert result.execution_status == "failed"
    assert result.limitations == ["工具查询失败，当前没有可确认的完整结果。"]
    assert result.next_step == "请稍后重试，或调整查询条件。"
