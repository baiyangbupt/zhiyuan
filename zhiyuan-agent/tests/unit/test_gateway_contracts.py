from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.gateway.contracts import (
    ArtifactRef,
    ConversationTurnSnapshot,
    EvidenceRef,
    StatePatch,
    TurnOutput,
)


def test_recommendation_output_requires_backend_refs() -> None:
    with pytest.raises(ValidationError, match="artifactRefs"):
        TurnOutput.model_validate(
            {
                "responseType": "recommendation",
                "message": "候选已生成",
                "artifactRefs": [],
                "evidenceRefs": [],
            }
        )


def test_fact_output_requires_evidence_refs() -> None:
    with pytest.raises(ValidationError, match="evidenceRefs"):
        TurnOutput.model_validate(
            {
                "responseType": "fact",
                "message": "这是招生事实",
                "artifactRefs": [],
                "evidenceRefs": [],
            }
        )


def test_turn_output_normalizes_needs_clarification_alias() -> None:
    output = TurnOutput.model_validate(
        {
            "responseType": "needs_clarification",
            "message": "请补充省份",
            "artifactRefs": [],
            "evidenceRefs": [],
            "uncertainties": ["province"],
        }
    )

    assert output.response_type == "clarification"


def test_state_patch_rejects_non_adjacent_versions() -> None:
    with pytest.raises(ValidationError, match="targetVersion"):
        StatePatch(
            baseVersion=41,
            targetVersion=43,
            changes=[],
            invalidations=[],
        )


def test_state_patch_rejects_unknown_change_path() -> None:
    with pytest.raises(ValidationError, match="unsupported state path"):
        StatePatch(
            baseVersion=41,
            targetVersion=42,
            changes=[{"path": "workingPlanState", "oldValue": {}, "newValue": {}}],
            invalidations=[],
        )


def test_contracts_accept_backend_camel_case_payloads_and_forbid_unknown_fields() -> None:
    evidence = EvidenceRef.model_validate(
        {
            "evidenceId": "ev-1",
            "sourceLevel": "authoritative",
            "dataVersion": "2026.09.07",
            "limitations": [],
        }
    )
    artifact = ArtifactRef.model_validate(
        {
            "artifactId": "artifact-1",
            "artifactType": "candidate",
            "stateVersion": 42,
        }
    )
    output = TurnOutput.model_validate(
        {
            "responseType": "recommendation",
            "message": "候选已生成",
            "artifactRefs": [artifact.model_dump(by_alias=True)],
            "evidenceRefs": [evidence.model_dump(by_alias=True)],
            "uncertainties": [],
        }
    )

    assert output.model_dump(by_alias=True)["artifactRefs"][0]["artifactId"] == "artifact-1"
    with pytest.raises(ValidationError, match="extraField"):
        EvidenceRef.model_validate(
            {
                "evidenceId": "ev-1",
                "sourceLevel": "authoritative",
                "dataVersion": "2026.09.07",
                "extraField": True,
            }
        )


def test_evidence_ref_accepts_the_ledger_fields_the_snapshot_now_carries() -> None:
    """快照自 2026-09-21 起真的带证据，形状取自 Java `ConversationEvidenceDTO` 的实测回包。

    这一条防的是**整条快照**被拒：`EvidenceRef` 是 `extra="forbid"`，漏声明一个
    字段不是"少了一个字段"，而是整个 `ConversationTurnSnapshot` 解析失败，用户看到
    的是"当前会话状态暂时不可用"，且从第二轮起每轮如此。
    """
    evidence = EvidenceRef.model_validate(
        {
            "evidenceId": "ev_01M31WYBVM8CE5VQ3T4982E7HZ",
            "sourceLevel": "authoritative",
            "dataVersion": "fc7bd2c8d3cd6dad653afc03d4c7b40a",
            "sourceSystem": "gaotu.batchList",
            "paramsDigest": "5c0e803deaefc0e3ee3be13497f84de9",
            "expiresAt": "2026-10-21T19:52:10+08:00",
            "scope": {"tenantId": 1, "chatSessionId": 900048},
            "observedAt": "2026-09-21T19:52:10+08:00",
            "limitations": [],
        }
    )

    assert evidence.source_system == "gaotu.batchList"
    assert evidence.params_digest == "5c0e803deaefc0e3ee3be13497f84de9"
    assert evidence.expires_at == "2026-10-21T19:52:10+08:00"
    # 三个字段是**台账内部标识**，不进模型可见的输出信封：信封由 TurnOutput 决定，
    # 这里是"能读进来"，不是"会发出去"。
    assert set(evidence.model_dump(by_alias=True)) >= {"sourceSystem", "paramsDigest", "expiresAt"}


def test_snapshot_serializes_with_stable_empty_collections() -> None:
    snapshot = ConversationTurnSnapshot(
        snapshot_version=42,
        session_id="session-1",
        planning_stage="candidate_exploration",
    )

    payload = snapshot.model_dump(by_alias=True)

    assert payload["snapshotVersion"] == 42
    assert payload["sessionId"] == "session-1"
    assert payload["missingFacts"] == []
    assert payload["allowedCapabilities"] == []
    assert payload["evidence"] == []


def test_snapshot_requires_canonical_admission_mode() -> None:
    snapshot = ConversationTurnSnapshot.model_validate(
        {
            "snapshotVersion": 3,
            "sessionId": "s1",
            "admissionMode": "major_group",
        }
    )

    assert snapshot.admission_mode == "major_group"


def test_state_patch_mode_change_requires_invalidation() -> None:
    patch = StatePatch.model_validate(
        {
            "baseVersion": 3,
            "targetVersion": 4,
            "changes": [{"path": "admissionMode", "value": "major_group"}],
            "invalidations": [{"kind": "admission_mode", "reason": "mode_changed"}],
        }
    )

    assert patch.changes[0]["value"] == "major_group"


def test_group_evidence_contains_group_scope_and_state_version() -> None:
    evidence = EvidenceRef.model_validate(
        {
            "evidenceId": "ev-1",
            "sourceLevel": "authoritative",
            "dataVersion": "v17",
            "admissionMode": "major_group",
            "admissionUnitId": "unit-1",
            "groupCode": "101",
            "stateVersion": 4,
        }
    )

    assert evidence.admission_mode == "major_group"
    assert evidence.admission_unit_id == "unit-1"


def test_the_model_facing_schema_exposes_every_contract_enum() -> None:
    """模型可见的 schema 必须把契约里的字面量允许值列出来。

    这一条防的是实测踩到的那类事故（2026-09-22）：`artifactType` 在契约里是
    `Literal['candidate','comparison','plan_draft','review']`，而 schema 只写了
    `"type": "string"`——模型**从来不知道**允许值，填了 `"plan"`，
    于是整条 `TurnOutput` 校验失败、走修复路径，而现象看起来像"模型没按契约输出"。

    `const` 与 `enum` 都算合格（前者更严）；递归整棵树，因为最容易漏的正是
    `artifactRefs.items` 这种嵌套字段。
    """
    import re

    from app.gateway import contracts
    from app.gateway.service import TURN_OUTPUT_SCHEMA

    literals: dict[str, set[str]] = {}
    for obj in vars(contracts).values():
        if not isinstance(obj, type):
            continue
        for name, info in getattr(obj, "model_fields", {}).items():
            annotation = str(info.annotation)
            if "Literal[" in annotation:
                literals[name] = set(re.findall(r"'([^']+)'", annotation))

    def camel(snake: str) -> str:
        head, *rest = snake.split("_")
        return head + "".join(word.capitalize() for word in rest)

    missing: list[str] = []

    def walk(node: object) -> None:
        if isinstance(node, dict):
            properties = node.get("properties")
            if isinstance(properties, dict):
                for prop, spec in properties.items():
                    if isinstance(spec, dict):
                        for snake, allowed in literals.items():
                            if camel(snake) == prop and "enum" not in spec and "const" not in spec:
                                missing.append(f"{prop}（契约允许 {sorted(allowed)}）")
                        walk(spec)
            for key, value in node.items():
                if key != "properties":
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(TURN_OUTPUT_SCHEMA)

    assert not missing, "schema 没告诉模型这些字段的允许值，模型只能猜：" + "；".join(sorted(set(missing)))


def test_nullable_contract_literals_are_expressible_in_the_model_facing_schema() -> None:
    """可空 `Literal` 字段：schema 的 `enum` 必须**把 None 也列出来**。

    2026-09-23 复核实测：JSON Schema 的 `type` 与 `enum` 是**合取**关系——
    `{"type": ["string", "null"], "enum": ["major", "major_group"]}` 会把契约允许的
    合法 `null` 判非法（`None is not one of ['major', 'major_group']`），于是"证据没有
    招生模式"这种输出被模型侧 schema 拒掉，走修复回合甚至 `output_schema_invalid`。
    上一条用例只核对"字面量在不在 enum 里"，正好漏掉这一半——两条合起来才是
    "模型可见 schema 与契约一致"。

    判定方式：对每个契约里的 Literal 字段，schema 中同名节点的 `enum`（去掉 None 后）
    必须等于契约字面量集合，且**可空性一致**（契约可空 ⟺ enum 含 None）。
    """
    import re

    from app.gateway import contracts
    from app.gateway.service import TURN_OUTPUT_SCHEMA

    def camel(snake: str) -> str:
        head, *rest = snake.split("_")
        return head + "".join(word.capitalize() for word in rest)

    # 同名契约字段可能来自不同模型、可空性不同（EvidenceRef.admission_mode 可空、
    # AdmissionFact.admission_mode 不可空），所以收的是"这个名字有哪些合法形态"。
    variants: dict[str, list[tuple[frozenset[str], bool]]] = {}
    for obj in vars(contracts).values():
        if not isinstance(obj, type):
            continue
        for name, info in getattr(obj, "model_fields", {}).items():
            annotation = str(info.annotation)
            if "Literal[" not in annotation:
                continue
            allowed = frozenset(re.findall(r"'([^']+)'", annotation))
            nullable = any(tag in annotation for tag in ("None", "Optional", "NoneType"))
            entry = (allowed, nullable)
            if entry not in variants.setdefault(camel(name), []):
                variants[camel(name)].append(entry)

    mismatches: list[str] = []

    def walk(node: object) -> None:
        if isinstance(node, dict):
            properties = node.get("properties")
            if isinstance(properties, dict):
                for prop, spec in properties.items():
                    if isinstance(spec, dict) and prop in variants:
                        enum_values = spec.get("enum")
                        if isinstance(enum_values, list):
                            values = frozenset(v for v in enum_values if v is not None)
                            has_none = any(v is None for v in enum_values)
                            variants_of_prop = variants[prop]
                            if not any(
                                values == allowed and has_none == nullable
                                for allowed, nullable in variants_of_prop
                            ):
                                expected = "；".join(
                                    f"{sorted(allowed)}{' + None' if nullable else ''}"
                                    for allowed, nullable in variants_of_prop
                                )
                                mismatches.append(
                                    f"{prop}: schema={sorted(values)}"
                                    f"{' + None' if has_none else ''}，契约={expected}"
                                )
                        # `const` 比 enum 更严：与上一条用例一致，不在此处判
                        walk(spec)
            for key, value in node.items():
                if key != "properties":
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(TURN_OUTPUT_SCHEMA)

    assert not mismatches, (
        "可空 Literal 与 schema 不一致（None 必须列进 enum）：" + "；".join(mismatches)
    )
