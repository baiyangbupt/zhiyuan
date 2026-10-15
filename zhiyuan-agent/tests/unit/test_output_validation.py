from __future__ import annotations

import pytest

from app.gateway.contracts import ConversationTurnSnapshot, EvidenceRef, TurnOutput
from app.gateway.output_validation import (
    OutputContractError,
    merge_artifacts,
    register_scoped_artifacts,
    validate_turn_output,
)


def test_validate_output_ignores_json_schema_root_type_echo():
    output = validate_turn_output(
        turn_output={"type": "object", "responseType": "text", "message": "已完成"},
        current_snapshot={"snapshotVersion": 1, "sessionId": "s"},
        evidence_ledger={},
        artifacts={},
    )

    assert output.response_type == "text"


def test_validate_output_preserves_model_text_with_evidence():
    output = validate_turn_output(
        turn_output={
            "responseType": "text",
            "message": "查询结果",
            "evidenceRefs": [{"evidenceId": "ev-1", "sourceLevel": "authoritative", "dataVersion": "v1"}],
        },
        current_snapshot={"snapshotVersion": 1, "sessionId": "s"},
        evidence_ledger={"ev-1": {"sessionId": "s", "stateVersion": 1}},
        artifacts={},
    )

    assert output.response_type == "text"


def test_output_validation_rejects_fixture_admission_fact():
    with pytest.raises(OutputContractError, match="non_authoritative_admission_fact"):
        validate_turn_output(
            turn_output={
                "responseType": "fact",
                "message": "测试",
                "evidenceRefs": [{"evidenceId": "ev-1", "sourceLevel": "authoritative", "dataVersion": "semantic-fixture-1"}],
                "admissionFacts": [{
                    "admissionUnitId": "school-1/major-cs/2025",
                    "admissionMode": "major",
                    "schoolId": "school-1",
                    "schoolName": "甲大学",
                    "majorId": "major-cs",
                    "majorName": "计算机科学与技术",
                    "majorItems": [{"majorId": "major-cs", "majorName": "计算机科学与技术", "majorAdmissionRate": 0}],
                    "unitAdmissionRate": 0,
                    "riskTier": "稳",
                    "dataVersion": "semantic-fixture-1",
                    "limitations": ["semantic_fixture_only"],
                }],
            },
            current_snapshot={"snapshotVersion": 42, "sessionId": "s1"},
            evidence_ledger={"ev-1": {"sessionId": "s1", "stateVersion": 42}},
            artifacts={},
        )


def _snapshot(version: int = 42) -> ConversationTurnSnapshot:
    return ConversationTurnSnapshot(
        snapshot_version=version,
        session_id="session-1",
        planning_stage="candidate_exploration",
    )


def _group_snapshot(version: int = 42) -> ConversationTurnSnapshot:
    return ConversationTurnSnapshot(
        snapshot_version=version,
        session_id="session-1",
        admission_mode="major_group",
        planning_stage="candidate_exploration",
    )


def _fact_output(*evidence_ids: str) -> TurnOutput:
    return TurnOutput(
        response_type="fact",
        message="招生事实",
        evidence_refs=[
            EvidenceRef(
                evidence_id=evidence_id,
                source_level="authoritative",
                data_version="2026.09.07",
            )
            for evidence_id in evidence_ids
        ],
    )


def test_output_validator_rejects_unknown_evidence() -> None:
    with pytest.raises(OutputContractError, match="evidence_not_found"):
        validate_turn_output(
            turn_output=_fact_output("ev-missing"),
            current_snapshot=_snapshot(),
            evidence_ledger={"ev-known": {"evidenceId": "ev-known"}},
            artifacts={},
        )


def test_output_validator_rejects_cross_session_evidence() -> None:
    with pytest.raises(OutputContractError, match="evidence_scope_violation"):
        validate_turn_output(
            turn_output=_fact_output("ev-other"),
            current_snapshot=_snapshot(),
            evidence_ledger={
                "ev-other": {
                    "evidenceId": "ev-other",
                    "sessionId": "session-other",
                    "threadId": "thread-1",
                }
            },
            artifacts={},
            thread_id="thread-1",
        )


def test_output_validator_rejects_artifact_from_old_snapshot() -> None:
    output = TurnOutput.model_validate(
        {
            "responseType": "recommendation",
            "message": "候选",
            "artifactRefs": [
                {"artifactId": "artifact-1", "artifactType": "candidate", "stateVersion": 41}
            ],
            "evidenceRefs": [],
        }
    )

    with pytest.raises(OutputContractError, match="stale_state"):
        validate_turn_output(
            turn_output=output,
            current_snapshot=_snapshot(42),
            evidence_ledger={},
            artifacts={"artifact-1": {"artifactId": "artifact-1", "stateVersion": 41}},
        )


def test_output_validator_accepts_a_rebased_artifact_within_the_ceiling() -> None:
    """2026-10-14：回合内版本前进（候选池生成 v42→v43）后重基签发的产物必须放行。

    上限由 Gateway 重新向 Java 读到（这里以参数形式给出）；下界仍是回合起始版本。
    """
    output = TurnOutput.model_validate(
        {
            "responseType": "recommendation",
            "message": "候选",
            "artifactRefs": [
                {"artifactId": "artifact-1", "artifactType": "candidate", "stateVersion": 43}
            ],
            "evidenceRefs": [],
        }
    )

    result = validate_turn_output(
        turn_output=output,
        current_snapshot=_snapshot(42),
        evidence_ledger={},
        artifacts={
            "artifact-1": {
                "artifactId": "artifact-1",
                "stateVersion": 43,
                "sessionId": "session-1",
            }
        },
        artifact_version_ceiling=43,
    )

    assert result.artifact_refs[0].state_version == 43


def test_output_validator_still_rejects_artifacts_older_than_the_turn_version() -> None:
    """上限放宽了，**下界没放宽**：早于回合起始版本的产物依旧 stale_state（旧数据不拼）。"""
    output = TurnOutput.model_validate(
        {
            "responseType": "recommendation",
            "message": "候选",
            "artifactRefs": [
                {"artifactId": "artifact-1", "artifactType": "candidate", "stateVersion": 41}
            ],
            "evidenceRefs": [],
        }
    )

    with pytest.raises(OutputContractError, match="stale_state"):
        validate_turn_output(
            turn_output=output,
            current_snapshot=_snapshot(42),
            evidence_ledger={},
            artifacts={"artifact-1": {"artifactId": "artifact-1", "stateVersion": 41}},
            artifact_version_ceiling=43,
        )


def test_output_validator_rejects_an_artifact_beyond_the_confirmed_ceiling() -> None:
    """上限之外不放行：账本戳与模型声明**各自**核——44 既超过已核实的 43，也拒。"""
    output = TurnOutput.model_validate(
        {
            "responseType": "recommendation",
            "message": "候选",
            "artifactRefs": [
                {"artifactId": "artifact-1", "artifactType": "candidate", "stateVersion": 44}
            ],
            "evidenceRefs": [],
        }
    )

    with pytest.raises(OutputContractError, match="stale_state"):
        validate_turn_output(
            turn_output=output,
            current_snapshot=_snapshot(42),
            evidence_ledger={},
            artifacts={"artifact-1": {"artifactId": "artifact-1", "stateVersion": 44}},
            artifact_version_ceiling=43,
        )

    # 账本戳在界内、模型声明的版本越界：模型自证的"更新"一样拒（上界不是它说了算）。
    with pytest.raises(OutputContractError, match="stale_state"):
        validate_turn_output(
            turn_output=output,
            current_snapshot=_snapshot(42),
            evidence_ledger={},
            artifacts={"artifact-1": {"artifactId": "artifact-1", "stateVersion": 43}},
            artifact_version_ceiling=43,
        )


def test_output_validator_returns_normalized_output_when_refs_are_valid() -> None:
    output = validate_turn_output(
        turn_output=_fact_output("ev-known"),
        current_snapshot=_snapshot(),
        evidence_ledger={
            "ev-known": {
                "evidenceId": "ev-known",
                "sessionId": "session-1",
                "stateVersion": 42,
            }
        },
        artifacts={},
        thread_id="thread-1",
    )

    assert output.response_type == "fact"
    assert output.evidence_refs[0].evidence_id == "ev-known"


def test_output_validator_can_require_complete_production_scope() -> None:
    with pytest.raises(OutputContractError, match="evidence_scope_violation"):
        validate_turn_output(
            turn_output=_fact_output("ev-known"),
            current_snapshot=_snapshot(),
            evidence_ledger={"ev-known": {"evidenceId": "ev-known", "stateVersion": 42}},
            artifacts={},
            thread_id="thread-1",
            tenant_id="tenant-1",
            strict_scope=True,
        )


def test_validator_accepts_group_fact_using_group_rate_not_nested_major_rate() -> None:
    output = validate_turn_output(
        turn_output={
            "responseType": "fact",
            "message": "专业组招生事实",
            "evidenceRefs": [
                {
                    "evidenceId": "ev-unit-1",
                    "sourceLevel": "authoritative",
                    "dataVersion": "v17",
                    "admissionMode": "major_group",
                    "admissionUnitId": "unit-1",
                    "groupCode": "101",
                    "stateVersion": 42,
                }
            ],
            "admissionFacts": [
                {
                    "admissionMode": "major_group",
                    "admissionUnitId": "unit-1",
                    "schoolId": "school-1",
                    "groupCode": "101",
                    "unitAdmissionRate": 70,
                    "riskTier": "保",
                    "majorItems": [{"majorId": "m-1", "majorAdmissionRate": 40}],
                }
            ],
        },
        current_snapshot=_group_snapshot(),
        evidence_ledger={
            "ev-unit-1": {
                "evidenceId": "ev-unit-1",
                "sessionId": "session-1",
                "stateVersion": 42,
                "dataVersion": "v17",
                "admissionMode": "major_group",
                "admissionUnitId": "unit-1",
                "groupCode": "101",
            }
        },
        artifacts={},
    )

    assert output.admission_facts[0].risk_tier == "保"
    assert output.admission_facts[0].major_items[0].major_admission_rate == 40


def test_validator_accepts_group_fact_without_group_code() -> None:
    """缺专业组代码的事实：真值来自候选数据（没有组代码列）——放行，不再修复回合。

    证据绑定不因此变松：模式与招生单元仍须逐字相等，且证据必须在台账里、
    会话/数据版本对得上；只有"事实**没带**组代码"时不做组代码比对。
    """
    output = validate_turn_output(
        turn_output={
            "responseType": "fact",
            "message": "专业组招生事实",
            "evidenceRefs": [
                {
                    "evidenceId": "ev-unit-1",
                    "sourceLevel": "authoritative",
                    "dataVersion": "v17",
                    "admissionMode": "major_group",
                    "admissionUnitId": "unit-1",
                    "groupCode": None,
                    "stateVersion": 42,
                }
            ],
            "admissionFacts": [
                {
                    "admissionMode": "major_group",
                    "admissionUnitId": "unit-1",
                    "schoolId": "school-1",
                    "groupCode": None,
                    "unitAdmissionRate": 55,
                    "riskTier": "稳",
                    "majorItems": [{"majorId": "m-1", "majorAdmissionRate": 40}],
                }
            ],
        },
        current_snapshot=_group_snapshot(),
        evidence_ledger={
            "ev-unit-1": {
                "evidenceId": "ev-unit-1",
                "sessionId": "session-1",
                "stateVersion": 42,
                "dataVersion": "v17",
                "admissionMode": "major_group",
                "admissionUnitId": "unit-1",
            }
        },
        artifacts={},
    )

    assert output.admission_facts[0].group_code is None


def test_validator_still_requires_the_group_code_to_match_when_provided() -> None:
    """有则必须准：事实带了组代码时，证据的组代码必须逐字相等。"""
    with pytest.raises(OutputContractError, match="admission_evidence_missing"):
        validate_turn_output(
            turn_output={
                "responseType": "fact",
                "message": "专业组招生事实",
                "evidenceRefs": [
                    {
                        "evidenceId": "ev-unit-1",
                        "sourceLevel": "authoritative",
                        "dataVersion": "v17",
                        "admissionMode": "major_group",
                        "admissionUnitId": "unit-1",
                        "groupCode": "102",
                        "stateVersion": 42,
                    }
                ],
                "admissionFacts": [
                    {
                        "admissionMode": "major_group",
                        "admissionUnitId": "unit-1",
                        "schoolId": "school-1",
                        "groupCode": "101",
                        "unitAdmissionRate": 55,
                        "riskTier": "稳",
                    }
                ],
            },
            current_snapshot=_group_snapshot(),
            evidence_ledger={
                "ev-unit-1": {
                    "evidenceId": "ev-unit-1",
                    "sessionId": "session-1",
                    "stateVersion": 42,
                    "dataVersion": "v17",
                    "admissionMode": "major_group",
                    "admissionUnitId": "unit-1",
                }
            },
            artifacts={},
        )


def test_validator_rejects_admission_fact_without_matching_evidence() -> None:
    with pytest.raises(OutputContractError, match="admission_evidence_missing"):
        validate_turn_output(
            turn_output={
                "responseType": "fact",
                "message": "招生事实",
                "evidenceRefs": [
                    {
                        "evidenceId": "ev-other",
                        "sourceLevel": "authoritative",
                        "dataVersion": "v17",
                    }
                ],
                "admissionFacts": [
                    {
                        "admissionMode": "major",
                        "admissionUnitId": "unit-1",
                        "schoolId": "school-1",
                        "majorId": "m-1",
                        "unitAdmissionRate": 40,
                        "riskTier": "冲",
                    }
                ],
            },
            current_snapshot=_snapshot(),
            evidence_ledger={
                "ev-other": {
                    "evidenceId": "ev-other",
                    "sessionId": "session-1",
                    "stateVersion": 42,
                    "dataVersion": "v17",
                }
            },
            artifacts={},
        )


def test_validator_rejects_cross_mode_evidence_and_fact() -> None:
    with pytest.raises(OutputContractError, match="admission_mode_mismatch"):
        validate_turn_output(
            turn_output={
                "responseType": "fact",
                "message": "招生事实",
                "evidenceRefs": [
                    {
                        "evidenceId": "ev-unit-1",
                        "sourceLevel": "authoritative",
                        "dataVersion": "v17",
                        "admissionMode": "major",
                        "admissionUnitId": "unit-1",
                    }
                ],
                "admissionFacts": [
                    {
                        "admissionMode": "major",
                        "admissionUnitId": "unit-1",
                        "schoolId": "school-1",
                        "majorId": "m-1",
                        "unitAdmissionRate": 40,
                        "riskTier": "冲",
                    }
                ],
            },
            current_snapshot=_group_snapshot(),
            evidence_ledger={
                "ev-unit-1": {
                    "evidenceId": "ev-unit-1",
                    "sessionId": "session-1",
                    "stateVersion": 42,
                    "dataVersion": "v17",
                    "admissionMode": "major",
                    "admissionUnitId": "unit-1",
                }
            },
            artifacts={},
        )


@pytest.mark.parametrize("rate", [99.01, float("nan"), float("inf")])
def test_validator_rejects_unsupported_admission_rates(rate: float) -> None:
    with pytest.raises(OutputContractError, match="schema_invalid"):
        validate_turn_output(
            turn_output={
                "responseType": "fact",
                "message": "招生事实",
                "evidenceRefs": [
                    {
                        "evidenceId": "ev-unit-1",
                        "sourceLevel": "authoritative",
                        "dataVersion": "v17",
                    }
                ],
                "admissionFacts": [
                    {
                        "admissionMode": "major",
                        "admissionUnitId": "unit-1",
                        "schoolId": "school-1",
                        "majorId": "m-1",
                        "unitAdmissionRate": rate,
                        "riskTier": "保",
                    }
                ],
            },
            current_snapshot=_snapshot(),
            evidence_ledger={"ev-unit-1": {"dataVersion": "v17"}},
            artifacts={},
        )


def test_validator_accepts_confirm_action_for_current_active_proposal() -> None:
    snapshot = ConversationTurnSnapshot(
        snapshotVersion=42,
        sessionId="session-1",
        activeProposal={"proposalRef": "proposal-1", "sourceVersion": 42},
    )
    output = validate_turn_output(
        turn_output={
            "responseType": "clarification",
            "message": "请确认方案变更",
            "proposalRef": "proposal-1",
            "conversationAction": {
                "actionType": "confirm_proposal",
                "proposalRef": "proposal-1",
                "expectedSourceVersion": 42,
                "intent": "explicit",
            },
        },
        current_snapshot=snapshot,
        evidence_ledger={},
        artifacts={},
        allow_proposal=True,
    )

    assert output.conversation_action.action_type == "confirm_proposal"


def test_validator_rejects_confirm_action_for_stale_proposal() -> None:
    snapshot = ConversationTurnSnapshot(
        snapshotVersion=42,
        sessionId="session-1",
        activeProposal={"proposalRef": "proposal-1", "sourceVersion": 43},
    )

    with pytest.raises(OutputContractError, match="proposal_version_mismatch"):
        validate_turn_output(
            turn_output={
                "responseType": "clarification",
                "message": "确认",
                "conversationAction": {
                    "actionType": "confirm_proposal",
                    "proposalRef": "proposal-1",
                    "expectedSourceVersion": 42,
                    "intent": "explicit",
                },
            },
            current_snapshot=snapshot,
            evidence_ledger={},
            artifacts={},
            allow_proposal=True,
        )


def test_evidence_in_the_producers_shape_passes_scope_checks() -> None:
    """Java 签发的证据形状：作用域在 `scope` 里，键名是 `chatSessionId`、值是**数字**。

    这里以前只认顶层的 `sessionId`/`session_id`，于是**任何真实签发的证据**
    都会被判成 `evidence_scope_violation`——证据本身完全合规，只是键名不同；
    改对键名之后还有第二关：`900017 != "900017"`，值一样、类型不同同样被拒。
    键名与类型都要在消费侧对齐生产者，不是反过来要求生产者改名。
    """
    snapshot = ConversationTurnSnapshot(
        snapshot_version=42, session_id="900017", planning_stage="candidate_exploration"
    )
    ledger = {
        "ev-1": {
            "evidenceId": "ev-1",
            "sourceLevel": "authoritative",
            "dataVersion": "2026.09.07",
            "scope": {"tenantId": 1, "chatSessionId": 900017, "threadId": "thr-other"},
        }
    }

    validated = validate_turn_output(
        turn_output=_fact_output("ev-1"),
        current_snapshot=snapshot,
        evidence_ledger=ledger,
        artifacts={},
        thread_id="thr-current",
        tenant_id="1",
        strict_scope=True,
    )

    assert validated is not None


def test_evidence_from_another_session_is_still_refused() -> None:
    """形状对了不等于可以放松：**别的会话**的证据仍然必须拒。

    上面那条修的是"键名/类型对不上"，不是"别比了"——把这条一起钉住，
    免得下次有人为了让它通过而把比较删掉。
    """
    snapshot = ConversationTurnSnapshot(
        snapshot_version=42, session_id="900017", planning_stage="candidate_exploration"
    )
    ledger = {
        "ev-1": {
            "evidenceId": "ev-1",
            "sourceLevel": "authoritative",
            "dataVersion": "2026.09.07",
            "scope": {"tenantId": 1, "chatSessionId": 900018, "threadId": "thr-other"},
        }
    }

    with pytest.raises(OutputContractError, match="evidence_scope_violation"):
        validate_turn_output(
            turn_output=_fact_output("ev-1"),
            current_snapshot=snapshot,
            evidence_ledger=ledger,
            artifacts={},
            thread_id="thr-current",
            tenant_id="1",
            strict_scope=True,
        )


def test_evidence_signed_in_a_previous_thread_is_still_accepted() -> None:
    """P1c-1 验收 5 的判据本身：**thread 不参与证据准入**（重启模拟的本质）。

    `service.py` 的 `self._threads` 是纯进程内 dict、从不持久化——Gateway 一重启，
    同一 session 拿到新 thread，存量证据不该因此全部作废（隔离边界是
    `(tenantId, chatSessionId)`，Java 侧一直强制）。这里直接量那条判据：
    签发时 thread 是 `thr-old`、现在引用它是 `thr-current` → 必须通过。
    """
    validated = validate_turn_output(
        turn_output=_fact_output("ev-1"),
        current_snapshot=ConversationTurnSnapshot(
            snapshot_version=42, session_id="900017", planning_stage="candidate_exploration"
        ),
        evidence_ledger={
            "ev-1": {
                "evidenceId": "ev-1",
                "sourceLevel": "authoritative",
                "dataVersion": "2026.09.07",
                # 记录仍然带着签发线程（审计用），但它**不参与准入判定**。
                "scope": {"tenantId": 1, "chatSessionId": 900017, "threadId": "thr-old"},
            }
        },
        artifacts={},
        thread_id="thr-current",
        tenant_id="1",
        strict_scope=True,
    )

    assert validated is not None


def test_artifact_from_a_previous_thread_is_no_longer_refused() -> None:
    """§41（2026-10-15）与证据侧对齐：**artifact 侧的 thread 检查删了**。

    理由与证据侧逐字同源：thread 是运行身份，Gateway/运行时重启就变；易失标识符
    不能承载安全语义——留着它，一次重启就把同会话在世产物全部作废（B 类硬失败），
    而隔离边界本来是 (tenantId, chatSessionId)。会话/租户/stateVersion 三项**一项
    没少**（跨会话的对照见 `test_artifact_from_another_session_is_still_refused`）。
    """
    output = TurnOutput.model_validate(
        {
            "responseType": "recommendation",
            "message": "候选",
            "artifactRefs": [
                {"artifactId": "artifact-1", "artifactType": "candidate", "stateVersion": 42}
            ],
            "evidenceRefs": [],
        }
    )

    validated = validate_turn_output(
        turn_output=output,
        current_snapshot=ConversationTurnSnapshot(
            snapshot_version=42, session_id="900017", planning_stage="candidate_exploration"
        ),
        evidence_ledger={},
        artifacts={
            "artifact-1": {
                "artifactId": "artifact-1",
                "stateVersion": 42,
                "sessionId": "900017",
                "threadId": "thr-old",
            }
        },
        thread_id="thr-current",
        tenant_id="1",
        strict_scope=True,
    )

    assert validated.artifact_refs[0].artifact_id == "artifact-1"


def test_artifact_without_a_thread_stamp_is_not_refused() -> None:
    """④ thread 空（旧记录/未盖线程章）也不再拒：它本就不参与准入判定。"""
    validated = validate_turn_output(
        turn_output={
            "responseType": "recommendation",
            "message": "候选",
            "artifactRefs": [
                {"artifactId": "artifact-1", "artifactType": "candidate", "stateVersion": 42}
            ],
            "evidenceRefs": [],
        },
        current_snapshot=_snapshot(42),
        evidence_ledger={},
        artifacts={
            "artifact-1": {
                "artifactId": "artifact-1",
                "stateVersion": 42,
                "sessionId": "session-1",
            }
        },
        thread_id="thr-current",
        tenant_id="1",
        strict_scope=True,
    )

    assert validated.artifact_refs[0].artifact_id == "artifact-1"


def test_artifact_from_another_session_is_still_refused() -> None:
    """② 跨会话照旧 fail-closed：thread 放宽**没有**顺手把会话检查也放宽。

    这条在会话级登记表引入之后更要点名：登记表只收本会话的章，别的会话的章
    进不去；当回合事件里带着别的会话的章时，校验一样当场拒。
    """
    with pytest.raises(OutputContractError, match="artifact_scope_violation"):
        validate_turn_output(
            turn_output={
                "responseType": "recommendation",
                "message": "候选",
                "artifactRefs": [
                    {"artifactId": "artifact-1", "artifactType": "candidate", "stateVersion": 42}
                ],
                "evidenceRefs": [],
            },
            current_snapshot=_snapshot(42),
            evidence_ledger={},
            artifacts={
                "artifact-1": {
                    "artifactId": "artifact-1",
                    "stateVersion": 42,
                    "sessionId": "session-other",
                    "threadId": "thr-current",
                }
            },
            thread_id="thr-current",
            tenant_id="1",
            strict_scope=True,
        )


def test_tool_issued_artifact_ref_with_turn_scope_passes() -> None:
    """工具在签发点盖了章的产物引用必须通过——2026-10-08 事故的回归位。

    事故的形态：契约要求 recommendation/review 输出必须带 `artifactRefs`，
    而工具结果里没有一个可引用的产物 id，模型只能自己编一个
    （`session:10041979:major_direction_ranking:v3`），那条记录没有会话/线程章
    → `artifact_scope_violation` → 整轮不可恢复地失败。
    修的方向是**签发点补章**（工具结果带 `artifacts`），不是把这两处校验放松：
    下面这条记录的形状就是工具现在签发的形状（`mcp_art_<tool>_<digest>` + 会话身份）。
    """
    artifact_id = "mcp_art_preview_majors_a5af5a07bf98b144cc60"
    output = validate_turn_output(
        turn_output={
            "responseType": "recommendation",
            "message": "专业方向排序",
            "artifactRefs": [
                {"artifactId": artifact_id, "artifactType": "candidate", "stateVersion": 42}
            ],
            "evidenceRefs": [],
        },
        current_snapshot=ConversationTurnSnapshot(
            snapshot_version=42, session_id="10041979", planning_stage="candidate_exploration"
        ),
        evidence_ledger={},
        artifacts={
            artifact_id: {
                "artifactId": artifact_id,
                "artifactType": "candidate",
                "stateVersion": 42,
                "tenantId": "1",
                "sessionId": "10041979",
                "threadId": "thr-current",
            }
        },
        thread_id="thr-current",
        tenant_id="1",
        strict_scope=True,
    )

    assert output.artifact_refs[0].artifact_id == artifact_id


def test_artifact_without_a_session_stamp_is_still_refused() -> None:
    """模型自己编的产物 id（没有会话章）仍必须拒——补的是签发点，不是校验。

    事故里那条 `session:10041979:major_direction_ranking:v3` 走的就是这个分支：
    记录找得到（模型自己写的 JSON 被收集器当成了产物记录），
    但记录上没有任何会话身份 → `artifact_scope_violation`。
    放宽这里就等于"模型写什么就信什么"，那不是修复，是把检查作废。
    """
    fabricated = {
        "artifactId": "session:10041979:major_direction_ranking:v3",
        "artifactType": "candidate",
        "stateVersion": 42,
    }

    with pytest.raises(OutputContractError, match="artifact_scope_violation"):
        validate_turn_output(
            turn_output={
                "responseType": "recommendation",
                "message": "专业方向排序",
                "artifactRefs": [fabricated],
                "evidenceRefs": [],
            },
            current_snapshot=ConversationTurnSnapshot(
                snapshot_version=42, session_id="10041979", planning_stage="candidate_exploration"
            ),
            evidence_ledger={},
            artifacts={fabricated["artifactId"]: dict(fabricated)},
            thread_id="thr-current",
            tenant_id="1",
            strict_scope=True,
        )


def test_evidence_signed_before_a_workspace_write_is_still_accepted() -> None:
    """P1c-1 的验收原话：**第 3 回合产出的证据，在中间发生过一次工作区写入之后，
    第 7 回合引用它必须通过。**

    判据的实质：证据的 `stateVersion`（签发时的工作区版本）**不再**与当前快照版本
    比较——招生事实的新鲜度由 `dataVersion` 判，工作区版本回答的是"方案改过没有"，
    两个不同的问题（混用会把"用户改了方案"读成"录取数据过期"）。

    对照在同文件的 artifact 侧：产物**确实**绑定工作区版本，旧快照的产物仍必须拒
    （`test_output_validator_rejects_artifact_from_old_snapshot`）。只删证据那两处、
    不动 artifact 那两处，就是这次改动划的边界。
    """
    snapshot = ConversationTurnSnapshot(
        snapshot_version=42, session_id="900017", planning_stage="candidate_exploration"
    )
    ledger = {
        "ev-1": {
            "evidenceId": "ev-1",
            "sourceLevel": "authoritative",
            "dataVersion": "2026.09.07",
            # 签发时工作区在第 3 版；现在是第 42 版——中间改过方案。
            "stateVersion": 3,
            "scope": {"tenantId": 1, "chatSessionId": 900017},
        }
    }

    validated = validate_turn_output(
        turn_output=_fact_output("ev-1"),
        current_snapshot=snapshot,
        evidence_ledger=ledger,
        artifacts={},
        thread_id="thr-current",
        tenant_id="1",
        strict_scope=True,
    )

    assert validated is not None


def test_register_scoped_artifacts_keeps_only_this_sessions_stamps() -> None:
    """登记表只收**本会话完整章**的产物（会话级登记的第 1 步，§41）。

    · 带完整章（tenant + session + stateVersion）的本会话产物 → 入表；
    · 无章转述（模型正文里那种只有 id/type/version 的）→ 不收；
    · 别的会话的章 → 不收（收了就是把越权引用洗白）；
    · 别的租户、以及缺 stateVersion 的 → 不收。
    """
    registry: dict = {}
    register_scoped_artifacts(
        registry,
        {
            "art-ok": {
                "artifactId": "art-ok",
                "stateVersion": 42,
                "tenantId": "1",
                "sessionId": "session-1",
            },
            "art-nostamp": {"artifactId": "art-nostamp", "stateVersion": 42},
            "art-other-session": {
                "artifactId": "art-other-session",
                "stateVersion": 42,
                "tenantId": "1",
                "sessionId": "session-other",
            },
            "art-other-tenant": {
                "artifactId": "art-other-tenant",
                "stateVersion": 42,
                "tenantId": "2",
                "sessionId": "session-1",
            },
            "art-no-version": {
                "artifactId": "art-no-version",
                "tenantId": "1",
                "sessionId": "session-1",
            },
        },
        tenant_id="1",
        session_id="session-1",
    )

    assert sorted(registry) == ["art-ok"]


def test_merge_artifacts_prefers_the_registered_stamp_over_a_restatement() -> None:
    """登记优先、转述不覆盖：模型正文的残缺转述**不许**把签发章的记录挤掉。

    形状就是 10041983 那一轮：账本里同时有"登记的本会话签发章"与"模型转述
    （无 scope）"，合并后留的必须是前者——校验随后拿它去对，会话检查才有东西可对。
    """
    registered = {
        "mcp_art_preview_candidates_abc": {
            "artifactId": "mcp_art_preview_candidates_abc",
            "artifactType": "candidate",
            "stateVersion": 42,
            "tenantId": "1",
            "sessionId": "10041983",
            "threadId": "01a13df2",
        }
    }
    restatement = {
        "mcp_art_preview_candidates_abc": {
            "artifactId": "mcp_art_preview_candidates_abc",
            "artifactType": "candidate",
            "stateVersion": 42,
        }
    }

    merged = merge_artifacts(registered, restatement)

    assert merged["mcp_art_preview_candidates_abc"] is registered["mcp_art_preview_candidates_abc"]


def test_merge_artifacts_collects_newly_signed_artifacts_from_the_turn() -> None:
    """本回合新签照收（登记表非空时也一样）：只认登记会让新产物一引用就 not_found。"""
    registered = {"art-old": {"artifactId": "art-old", "stateVersion": 42, "sessionId": "s"}}
    turn = {
        "art-old": {"artifactId": "art-old", "stateVersion": 42},
        "art-new": {"artifactId": "art-new", "stateVersion": 42, "sessionId": "s"},
    }

    merged = merge_artifacts(registered, turn)

    assert sorted(merged) == ["art-new", "art-old"]
    assert merged["art-old"] is registered["art-old"], "登记的旧产物不被本回合转述覆盖"
    assert merged["art-new"] is turn["art-new"], "本回合新签的照收"
