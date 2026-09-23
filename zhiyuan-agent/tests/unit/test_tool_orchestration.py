from app.engine.tool_orchestration import (
    build_invocation_key,
    is_duplicate_invocation,
    merge_tool_results,
    prepare_tool_invocation,
    render_tool_contracts,
    ToolStep,
    prepare_tool_batch,
    build_tool_batch_report,
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


def test_tool_batch_reports_dependency_block_and_partial_success() -> None:
    report = prepare_tool_batch(
        [
            ToolStep("schools", "catalog.search_schools", {"query": "计算机"}),
            ToolStep(
                "majors",
                "catalog.search_majors",
                {"query": "计算机"},
                depends_on=("schools",),
            ),
            ToolStep(
                "current-plan",
                "admission.get_current_plan",
                {},
                depends_on=("schools",),
            ),
        ],
        results_by_step={
            "schools": [{"entityId": "school-1", "name": "甲大学"}],
            "majors": [{"entityId": "major-cs", "name": "计算机科学与技术"}],
        },
        errors_by_step={"current-plan": "backend_timeout"},
    )

    assert report.status == "partial"
    assert [step.status for step in report.steps] == ["completed", "completed", "failed"]
    assert report.steps[2].error == "backend_timeout"
    assert report.merged_results == (
        {"entityId": "school-1", "name": "甲大学"},
        {"entityId": "major-cs", "name": "计算机科学与技术"},
    )


def test_tool_batch_marks_completed_invocation_as_duplicate() -> None:
    step = ToolStep("schools", "catalog.search_schools", {"query": "计算机"})
    report = prepare_tool_batch(
        [step], completed_keys=[build_invocation_key(step.tool_name, step.arguments)]
    )

    assert report.status == "completed"
    assert report.steps[0].status == "duplicate"


def test_build_tool_batch_report_reads_real_mcp_events() -> None:
    report = build_tool_batch_report(
        {
            "events": [
                {
                    "type": "item/mcpToolCall",
                    "id": "call-1",
                    "tool": "catalog.search_schools",
                    "arguments": {"query": "计算机"},
                    "status": "completed",
                    "result": {"items": [{"entityId": "school-1"}]},
                },
                {
                    "type": "item/mcpToolCall",
                    "id": "call-2",
                    "tool": "admission.get_history",
                    "arguments": {
                        "schoolId": "school-1",
                        "majorId": "major-cs",
                        "areaId": "330000",
                        "batch": "本科批",
                        "year": 2025,
                        "subjectType": "物理类",
                    },
                    "status": "failed",
                    "errorMessage": "backend_timeout",
                },
            ]
        }
    )

    assert report.status == "partial"
    assert report.as_payload()["steps"][0]["resultCount"] == 1
    assert report.as_payload()["steps"][1]["error"] == "backend_timeout"


def test_build_tool_batch_report_reads_business_status_from_result_body() -> None:
    report = build_tool_batch_report(
        {
            "events": [{
                "type": "item/mcpToolCall",
                "id": "call-1",
                "tool": "admission.get_history",
                "arguments": {
                    "schoolId": "school-1", "majorId": "major-cs", "areaId": "330000",
                    "batch": "本科批", "year": 2025, "subjectType": "物理类",
                },
                "status": "completed",
                "result": {"status": "no_data", "data": {"history": []}},
            }]
        }
    )

    assert report.status == "completed"
    assert report.steps[0].error == "no_data"


def test_the_orchestration_contract_matches_the_real_mcp_tool_schemas() -> None:
    """编排层对"必需参数"的说法，必须与真实 MCP 工具一致。

    两处描述同一件事，漂移的后果是**用户可见**的：编排层多要一个参数时，模型没传就被
    `prepare_tool_invocation` 判 `blocked` → 批次报告降级 → `result_synthesis` 给整轮补一句
    "请补充缺失参数后继续"，**而工具本可以正常回答**。

    实测（2026-09-22）：`admission.get_history` 在编排层多要了 `majorId`（真实工具是
    学校级口径，没有这个参数）。这条用例就是那次漂移留下的钉子。
    """
    from app.engine.tool_orchestration import TOOL_CONTRACTS
    from app.mcp_server.server import tool_listing

    real = {
        entry["name"]: set((entry.get("inputSchema") or {}).get("required") or [])
        for entry in tool_listing()
    }

    unknown = [c.name for c in TOOL_CONTRACTS if c.name not in real]
    assert not unknown, f"编排层列了真实工具里没有的名字：{unknown}"

    mismatches = [
        f"{c.name}: 编排 {sorted(c.required_arguments)} vs 真实 {sorted(real[c.name])}"
        for c in TOOL_CONTRACTS
        if set(c.required_arguments) != real[c.name]
    ]
    assert not mismatches, "编排层与真实工具的必需参数不一致：" + "；".join(mismatches)
