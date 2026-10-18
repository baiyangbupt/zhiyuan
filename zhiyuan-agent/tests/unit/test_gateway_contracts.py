from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.gateway.contracts import (
    AdmissionFact,
    ArtifactRef,
    ConversationTurnSnapshot,
    EvidenceRef,
    ProposalPriorityRule,
    ProposalRequirement,
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


def _major_group_fact(**overrides):
    payload = {
        "admissionUnitId": "unit-1",
        "admissionMode": "major_group",
        "schoolId": "school-1",
        "unitAdmissionRate": 55,
        "riskTier": "稳",
    }
    payload.update(overrides)
    return payload


def test_major_group_fact_without_group_code_is_allowed() -> None:
    """数据源不提供专业组代码：缺它不能再拒整轮输出（2026-10-09 修）。

    事故形态（会话 10041981 19:51 轮）：`major_group` 下 `group_code` 必填，
    而候选行/Java 侧都没有这一层 → 8 条事实全被 `group_code_required` 拒 →
    修复回合 ~5 分钟，模型最后索性不再输出事实卡片。
    """
    fact = AdmissionFact.model_validate(_major_group_fact(groupCode=None))

    assert fact.group_code is None


def test_blank_group_code_reads_as_missing_not_as_a_value() -> None:
    """空白不是值：strip 后按"未提供"处理，不插值、也不当合法组代码。"""

    fact = AdmissionFact.model_validate(_major_group_fact(groupCode="   "))

    assert fact.group_code is None


def test_group_code_still_rejects_non_string_values() -> None:
    """放宽的是"缺失"，不是"类型"：提供了就必须合法。"""

    with pytest.raises(ValidationError):
        AdmissionFact.model_validate(_major_group_fact(groupCode=101))


def test_group_code_is_stripped_when_provided() -> None:
    fact = AdmissionFact.model_validate(_major_group_fact(groupCode=" 101 "))

    assert fact.group_code == "101"


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

    名字是**全局按 snake→camel 匹配**的（契约字段名在 schema 里同名 ✓），所以撞上
    手写段里同名但语义无关的自由字段时按**路径**排除（见 `free_form_paths` ✓）。
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

    # 手写证据范围里的这两个名字与契约字面量**同名但无关**：契约侧 `EvidenceRef.scope`
    # 本来就是 `dict[str, Any]`（`scope.kind` 是它的自由字符串字段）。它们是
    # `ProposalPriorityRule.scope` / `ProposalRequirement.kind` 的同名巧合，
    # 不是"漏了 enum"（按路径排除，不放松别处 ✓）。
    free_form_paths = {
        "$.properties.evidenceRefs.items.properties.scope",
        "$.properties.evidenceRefs.items.properties.scope.properties.kind",
        # additionalMutations 是数组：enum 在 items.enum，不在数组节点本身。
        "$.properties.intentDraft.anyOf[0].properties.additionalMutations",
    }

    missing: list[str] = []

    def walk(node: object, path: str = "$") -> None:
        if isinstance(node, dict):
            properties = node.get("properties")
            if isinstance(properties, dict):
                for prop, spec in properties.items():
                    child = f"{path}.properties.{prop}"
                    if isinstance(spec, dict):
                        items = spec.get("items")
                        array_enum = (
                            spec.get("type") == "array"
                            and isinstance(items, dict)
                            and ("enum" in items or "const" in items)
                        )
                        if child not in free_form_paths and not array_enum:
                            for snake, allowed in literals.items():
                                if (
                                    camel(snake) == prop
                                    and "enum" not in spec
                                    and "const" not in spec
                                ):
                                    missing.append(f"{prop}（契约允许 {sorted(allowed)}）")
                        walk(spec, child)
            for key, value in node.items():
                if key != "properties":
                    walk(value, f"{path}.{key}")
        elif isinstance(node, list):
            for index, item in enumerate(node):
                walk(item, f"{path}[{index}]")

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


# ── 2026-10-08「location 死卡」回归：契约必须与 Java 白名单（唯一权威 =
#    `CoverageRequirementSupport.targetList()`）一致 ──────────────────────────
# 事故链：`domain` 曾是自由字符串 → 模型侧 schema 没有 enum → 模型只能猜（它猜了
# `location`）→ Java 双重非法（域不在白名单、键也不在）→ prepare 拒单 → 用户拿到
# 一张 `status=blocked` 的死卡（"暂不支持非排他覆盖要求字段：location.…"）。
# 拒收**必须发生在投递前**：`TurnOutput.model_validate` 拦下 → 走既有的一次修复回合，
# 而不是注定被 Java 拒的死卡。


def test_proposal_priority_rule_rejects_an_unknown_domain() -> None:
    with pytest.raises(ValidationError, match="domain"):
        ProposalPriorityRule(domain="location", key="location", values=["北方", "北京"])


def test_turn_output_rejects_a_proposal_with_an_unknown_rule_domain() -> None:
    """模型输出的**完整形状**（不是裸规则）：非法域在解析层就被拒。

    这一条是根因回归：只要这里拒了，`_extract_output` 就会走修复回合，
    非法规则**没有机会**直通 `prepare`（那条路的终点是死卡）。
    """
    with pytest.raises(ValidationError, match="domain"):
        TurnOutput.model_validate(
            {
                "responseType": "text",
                "message": "我把这个要求整理成提案",
                "proposalRequest": {
                    "goalType": "prioritize_within_tier",
                    "sourceVersionGuard": 7,
                    "userOriginalText": "学校在北方的话，优先北京和上海",
                    "priorityRules": [
                        {"domain": "location", "key": "location", "values": ["北方", "北京", "上海"]}
                    ],
                },
            }
        )


def test_proposal_priority_rule_rejects_a_key_from_another_domain() -> None:
    """域与键必须配对（JSON Schema 表达不了合取，pydantic 侧补上）：

    `region` 只认 province/city/area/region_group；`school_nature` 属于 `school` 域。
    配错在 Java 里同样是"暂不支持…字段"的拒单死卡。
    """
    with pytest.raises(ValidationError, match="school_nature"):
        ProposalPriorityRule(domain="region", key="school_nature", values=["985"])


def test_proposal_priority_rule_rejects_an_unsupported_ordering_target() -> None:
    """`orderingTarget`/`scope` 在 Java 里各自只有**一个**合法取值（其余 = 拒单）。"""
    with pytest.raises(ValidationError, match="ordering_target"):
        ProposalPriorityRule(
            domain="region", key="city", values=["北京"], ordering_target="rank_after"
        )
    with pytest.raises(ValidationError, match="scope"):
        ProposalPriorityRule(domain="region", key="city", values=["北京"], scope="across_tier")


def test_proposal_priority_rule_accepts_region_city() -> None:
    """正常路径不许被误伤：region+city 是 Java 白名单里的合法组合。"""
    rule = ProposalPriorityRule(domain="region", key="city", values=["北京"])

    assert rule.domain == "region"
    assert rule.key == "city"
    assert rule.ordering_target == "rank_before"
    assert rule.scope == "within_tier"


def test_priority_rules_one_at_a_time_guidance_reaches_the_model_facing_schema() -> None:
    """同档前置"只支持一条"（2026-10-13，会话 10041981）的口径要进**模型侧 schema**：

    该列表仅服务"同档前置"链（Java `PriorityRuleSupport.validate()`：>1 条 = 拒单），
    但契约层**不硬拒**（硬拒会连"修不好时的 blocked 卡兜底"一起砍掉、变成整轮失败）——
    改为在 description 里把口径讲给模型（生成时一次只给一条），超条由网关提案分支
    的先修一次守卫兜底（见 `tests/unit/test_gateway_output_repair.py` ⑥）。
    """
    from app.gateway.service import TURN_OUTPUT_SCHEMA

    node = TURN_OUTPUT_SCHEMA["properties"]["proposalRequest"]["anyOf"][0]
    description = node["properties"]["priorityRules"]["description"]

    assert "只支持一条" in description
    assert "顺序" in description


def test_proposal_requirement_kind_domain_key_follow_the_java_whitelist() -> None:
    """`ProposalRequirement` 与 priority 规则同一个校验器家族（`ProjectedHardRequirementSupport.validate`）：

    - kind 只认 include / exclude / only_keep（其余 = "当前只支持 exclude 和 only_keep 复合硬要求"✗）；
    - domain/key 与覆盖要求同一份白名单；
    - `admission.tier` 只对 `kind=include` 存在（`targetListName()` 不含 admission ✗）。
    """
    requirement = ProposalRequirement(kind="include", domain="admission", key="tier", values=["冲"])
    assert requirement.key == "tier"

    with pytest.raises(ValidationError, match="kind"):
        ProposalRequirement(kind="within", domain="region", key="city", values=["北京"])
    with pytest.raises(ValidationError, match="admission"):
        ProposalRequirement(kind="exclude", domain="admission", key="tier", values=["冲"])
    with pytest.raises(ValidationError, match="school_nature"):
        ProposalRequirement(kind="include", domain="region", key="school_nature", values=["985"])


# ── 点名加入（add_units + exactTargets）契约 ────────────────────────────────

def _add_proposal(targets, **overrides):
    from app.gateway.contracts import ProposalRequest

    return ProposalRequest(
        goal_type="add_units",
        source_version_guard=1,
        exact_targets=targets,
        **overrides,
    )


def test_add_units_accepts_names_only_id_only_and_both() -> None:
    names = _add_proposal([{"schoolName": "肇庆学院", "majorName": "地理科学"}])
    assert names.exact_targets[0].school_name == "肇庆学院"

    id_only = _add_proposal([{"volunteerId": "44020271003614_44020272012541"}])
    assert id_only.exact_targets[0].volunteer_id.startswith("4402")

    both = _add_proposal([{
        "schoolName": "肇庆学院", "majorName": "地理科学",
        "volunteerId": "44020271003614_44020272012541",
    }])
    assert both.exact_targets[0].volunteer_id


def test_add_units_defaults_to_expand_and_accepts_replace() -> None:
    expand = _add_proposal([{"schoolName": "肇庆学院", "majorName": "地理科学"}])
    assert expand.add_policy == "expand"

    replace = _add_proposal(
        [{"schoolName": "肇庆学院", "majorName": "地理科学"}],
        add_policy="replace",
    )
    assert replace.add_policy == "replace"


def test_replace_policy_is_rejected_for_non_add_units() -> None:
    from app.gateway.contracts import ProposalRequest

    with pytest.raises(ValidationError, match="addPolicy=replace"):
        ProposalRequest(
            goal_type="fill_to_count",
            source_version_guard=1,
            target_count=10,
            add_policy="replace",
        )


def test_add_units_rejects_empty_targets() -> None:
    from app.gateway.contracts import ProposalRequest

    with pytest.raises(ValidationError, match="exactTargets"):
        ProposalRequest(goal_type="add_units", source_version_guard=1, exact_targets=[])


def test_non_add_units_rejects_exact_targets() -> None:
    from app.gateway.contracts import ProposalRequest

    with pytest.raises(ValidationError, match="exactTargets"):
        ProposalRequest(
            goal_type="fill_to_count",
            source_version_guard=1,
            target_count=10,
            exact_targets=[{"schoolName": "肇庆学院", "majorName": "地理科学"}],
        )


def test_exact_target_requires_names_or_id() -> None:
    from app.gateway.contracts import ExactTarget

    with pytest.raises(ValidationError, match="exactTarget"):
        ExactTarget()
    with pytest.raises(ValidationError, match="exactTarget"):
        ExactTarget(school_name="肇庆学院")  # 只有学校不够


def test_add_units_rejects_mixed_goal_fields() -> None:
    from app.gateway.contracts import ProposalRequest

    targets = [{"schoolName": "肇庆学院", "majorName": "地理科学"}]
    for field, value in (
        ("target_count", 10),
        ("requirements", [{"kind": "include", "domain": "region", "key": "province", "values": ["广东"]}]),
        ("priority_rules", [{"domain": "region", "key": "province", "values": ["广东"]}]),
        ("target_scopes", [{"scope_type": "region", "name": "广东"}]),
        ("negative_scopes", [{"scope_type": "region", "name": "北方"}]),
        ("quality_guards", ["no_private"]),
        ("tradeoff_guards", ["tuition"]),
        ("source_review_issue_codes", ["high_tuition"]),
    ):
        with pytest.raises(ValidationError, match="cannot mix"):
            ProposalRequest(
                goal_type="add_units",
                source_version_guard=1,
                exact_targets=targets,
                **{field: value},
            )
