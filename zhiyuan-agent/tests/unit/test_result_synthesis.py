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
