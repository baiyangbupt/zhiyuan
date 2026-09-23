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


def test_business_no_data_status_adds_limit_even_when_batch_completed() -> None:
    output = TurnOutput(responseType="text", message="查询完成")

    result = synthesize_execution_status(
        output,
        {"status": "completed", "steps": [{"error": "no_data"}]},
    )

    assert result.execution_status == "completed"
    assert result.limitations == ["当前查询范围没有返回可引用数据。"]
    assert result.next_step == "请调整查询范围或确认是否查询其他年份/批次。"


def test_a_successful_batch_never_upgrades_the_models_partial() -> None:
    """**只降不升**的另一半：工具全成功，也不能把模型说的 `partial` 抬成 `completed`。

    这一条是 P2 成因 4 的核心——`executionStatus` 回答"用户的诉求满足了吗"（模型说了算），
    工具批次回答"这些调用成功了吗"（harness 说了算）。用后者覆盖前者，就会出现
    "用户要求读+写、系统只做了读、然后报告 completed"。

    以前这条路上**没有专测**：既有四条量的都是"工具失败/部分成功把状态拉低"，
    而"工具成功不许抬高"恰恰是被覆盖掉的那一半。
    """
    output = TurnOutput(response_type="text", message="只完成了读，写没做", execution_status="partial")

    result = synthesize_execution_status(
        output,
        {"status": "completed", "steps": [{"status": "ok"}, {"status": "ok"}]},
    )

    assert result.execution_status == "partial", "工具跑成功不是'用户诉求被满足'"
    assert result.next_step == output.next_step
