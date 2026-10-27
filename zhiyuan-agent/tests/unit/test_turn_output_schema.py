from app.gateway.service import TURN_OUTPUT_SCHEMA


def scan(node, path="$", bad_any=None, bad_req=None):
    bad_any = [] if bad_any is None else bad_any
    bad_req = [] if bad_req is None else bad_req
    if isinstance(node, dict):
        if "anyOf" in node and "type" not in node:
            bad_any.append(path)
        if node.get("type") == "object" and "properties" in node:
            if set(node["properties"]) != set(node.get("required", [])):
                bad_req.append(path)
        for key, value in node.items():
            scan(value, f"{path}.{key}", bad_any, bad_req)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            scan(value, f"{path}[{index}]", bad_any, bad_req)
    return bad_any, bad_req


def scan_propertyless_objects(node, path="$", bad=None):
    """DeepSeek `/responses` rejects `type: object` nodes without `properties`.

    Free-form dict bags (`list[dict]`) serialize as
    `{"type": "object", "additionalProperties": true}` and fail at runtime with
    "An object with no properties is not allowed."; nested drafts must use
    concrete models instead.
    """
    bad = [] if bad is None else bad
    if isinstance(node, dict):
        node_type = node.get("type")
        if node_type == "object" and not node.get("properties"):
            bad.append(path)
        if isinstance(node_type, list) and "object" in node_type and not node.get("properties"):
            bad.append(path)
        for key, value in node.items():
            scan_propertyless_objects(value, f"{path}.{key}", bad)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            scan_propertyless_objects(value, f"{path}[{index}]", bad)
    return bad


def test_turn_output_schema_has_no_propertyless_objects() -> None:
    assert scan_propertyless_objects(TURN_OUTPUT_SCHEMA) == []


def test_turn_output_schema_keeps_admission_facts_and_confirmation_fields() -> None:
    properties = TURN_OUTPUT_SCHEMA["properties"]

    assert "admissionFacts" in properties
    assert properties["admissionFacts"]["items"]["type"] == "object"
    assert properties["admissionFacts"]["items"]["additionalProperties"] is False
    assert properties["artifactRefs"]["items"]["type"] == "object"
    assert properties["artifactRefs"]["items"]["additionalProperties"] is False
    assert properties["evidenceRefs"]["items"]["type"] == "object"
    assert properties["evidenceRefs"]["items"]["additionalProperties"] is False
    scope = properties["evidenceRefs"]["items"]["properties"]["scope"]
    assert "areaId" in scope["properties"]
    assert scope["additionalProperties"] is False
    assert properties["uncertainties"]["items"]["type"] == "string"
    assert set(TURN_OUTPUT_SCHEMA["required"]) == set(properties)
    assert properties["responseType"]["enum"] == [
        "text",
        "fact",
        "recommendation",
        "review",
        "clarification",
    ]
    major_items = properties["admissionFacts"]["items"]["properties"]["majorItems"]
    assert major_items["items"]["additionalProperties"] is False
    assert "clarification" in properties
    assert "proposalRef" in properties
    proposal_node = TURN_OUTPUT_SCHEMA["properties"]["proposalRequest"]
    proposal_schema = proposal_node["anyOf"][0]
    assert proposal_schema["additionalProperties"] is False
    assert proposal_schema["required"] == list(proposal_schema["properties"])
    # 归一化后：可空对象节点自己带 type + properties，null 分支仍留在 anyOf 里
    assert proposal_node["type"] == "object"
    assert proposal_node["additionalProperties"] is False
    assert set(proposal_node["properties"]) == set(proposal_schema["properties"])
    assert proposal_node["required"] == list(proposal_node["properties"])
    assert {"type": "null"} in proposal_node["anyOf"]
    assert TURN_OUTPUT_SCHEMA["$defs"]["ProposalScope"]["additionalProperties"] is False
    assert TURN_OUTPUT_SCHEMA["additionalProperties"] is False


def test_turn_output_schema_declares_the_score_update_draft() -> None:
    """补录成绩草稿（`scoreUpdateRequest`）必须进模型侧 schema ✓✓。

    严格 schema（`additionalProperties: false`）**不会**因为契约新增字段就放行 ✗：
    漏声明的话模型一输出补录草稿就被自己的 schema 拒 ✓，现象是"模型从不产出补录草稿"
    ✓✗（看不出是 schema 漏字段）。这里钉住它与 `proposalRequest` 同一套纪律：
    required 覆盖全部 properties、可空节点归一化后仍合法（`scan` 那条会全树扫 ✓）。
    """
    assert "scoreUpdateRequest" in TURN_OUTPUT_SCHEMA["required"]
    node = TURN_OUTPUT_SCHEMA["properties"]["scoreUpdateRequest"]
    schema = node["anyOf"][0]
    assert schema["additionalProperties"] is False
    assert schema["required"] == list(schema["properties"])
    assert set(schema["properties"]) == {
        "sourceVersionGuard",
        "userOriginalText",
        "province",
        "subjectType",
        "batch",
        "totalScore",
        "totalScorePos",
        "examYear",
        "subjectScoreList",
        "specialPlan",
    }
    assert schema["properties"]["sourceVersionGuard"]["minimum"] == 0
    # 归一化后：对象自身的键提升到同层 + null 分支留在 anyOf 里（与 proposalRequest 同款）
    assert node["type"] == "object"
    assert node["additionalProperties"] is False
    assert set(node["properties"]) == set(schema["properties"])
    assert node["required"] == list(node["properties"])
    assert {"type": "null"} in node["anyOf"]
    # 嵌套草稿模型进了 $defs（省份/科类/批次/单科），且都是严格对象
    for name in (
        "ScoreUpdateProvince",
        "ScoreUpdateSubjectType",
        "ScoreUpdateBatch",
        "ScoreUpdateSubjectScore",
    ):
        definition = TURN_OUTPUT_SCHEMA["$defs"][name]
        assert definition["additionalProperties"] is False, name
        assert definition["required"] == list(definition["properties"]), name
    # 只被可空位置引用的嵌套模型自己声明可空，引用处是裸 $ref（与 ProposalScope 同款）
    assert TURN_OUTPUT_SCHEMA["$defs"]["ScoreUpdateProvince"]["type"] == ["object", "null"]
    assert TURN_OUTPUT_SCHEMA["$defs"]["ScoreUpdateBatch"]["type"] == ["object", "null"]
    assert schema["properties"]["province"] == {
        "default": None,
        "$ref": "#/$defs/ScoreUpdateProvince",
    }
    assert schema["properties"]["batch"] == {
        "default": None,
        "$ref": "#/$defs/ScoreUpdateBatch",
    }
    # 可空标量必须是类型数组（normalize 之后），且不丢约束
    assert schema["properties"]["totalScore"]["type"] == ["integer", "null"]
    assert TURN_OUTPUT_SCHEMA["$defs"]["ScoreUpdateBatch"]["properties"]["score"]["type"] == [
        "number",
        "null",
    ]


def test_turn_output_schema_is_accepted_by_deepseek_responses() -> None:
    bad_any, bad_req = scan(TURN_OUTPUT_SCHEMA)
    assert bad_any == []
    assert bad_req == []

    # 可空标量必须是类型数组，且不丢约束
    min_count = TURN_OUTPUT_SCHEMA["$defs"]["ProposalTierRange"]["properties"]["minCount"]
    assert min_count["type"] == ["integer", "null"]
    assert min_count["minimum"] == 0
    raw_text = TURN_OUTPUT_SCHEMA["$defs"]["ProposalScope"]["properties"]["rawText"]
    assert raw_text["type"] == ["string", "null"]

    # 只在可空位置被引用的 $def 自己声明可空，引用处是裸 $ref
    for name in ("ProposalTierQuota", "ProposalTierRange"):
        assert TURN_OUTPUT_SCHEMA["$defs"][name]["type"] == ["object", "null"]
    assert TURN_OUTPUT_SCHEMA["$defs"]["ProposalTierQuota"]["properties"]["sprint"] == {
        "default": None,
        "$ref": "#/$defs/ProposalTierRange",
    }


def test_the_model_facing_schema_pins_the_proposal_rule_domains_and_keys() -> None:
    """2026-10-08「location 死卡」的根因回归：**模型侧** schema 必须带 enum。

    事故链：`ProposalPriorityRule.domain` 是自由字符串 → schema 只写 `type: string`
    → 模型看不到允许值、只能猜（实测猜了 `location`）→ Java 白名单
    （`CoverageRequirementSupport.targetList()`）双重非法 → prepare 拒单 → 死卡。
    这一条钉住"允许值对模型可见"：域、键、kind、orderingTarget/scope **一个都不许**
    退回自由字符串（退回 = 模型重新开始猜）。
    """
    definitions = TURN_OUTPUT_SCHEMA["$defs"]

    rule = definitions["ProposalPriorityRule"]["properties"]
    assert rule["domain"]["enum"] == ["region", "major", "school", "admission"]
    keys = rule["key"]["enum"]
    assert {"province", "city", "area", "region_group"} <= set(keys)
    assert {"major", "level1", "level2", "level3", "major_tag"} <= set(keys)
    assert {"school", "schools", "school_nature", "program_type", "school_category",
            "school_level", "school_tag"} <= set(keys)
    assert "tier" in keys
    # Java 白名单之外的域/键**不在** enum 里（模型看不到 = 猜不出来）
    assert "location" not in keys and "location" not in rule["domain"]["enum"]
    # 单值 Literal 在 pydantic 里渲染成 `const`（比 enum 更严，合格）
    assert rule["orderingTarget"]["const"] == "rank_before"
    assert rule["scope"]["const"] == "within_tier"

    requirement = definitions["ProposalRequirement"]["properties"]
    assert requirement["kind"]["enum"] == ["include", "exclude", "only_keep"]
    assert requirement["domain"]["enum"] == ["region", "major", "school", "admission"]
    assert "city" in requirement["key"]["enum"]


def test_turn_output_schema_declares_add_units_and_exact_targets() -> None:
    """点名加入（add_units）必须进模型侧严格 schema。"""
    proposal_schema = TURN_OUTPUT_SCHEMA["properties"]["proposalRequest"]["anyOf"][0]
    properties = proposal_schema["properties"]
    assert "exactTargets" in properties
    assert "exactTargets" in proposal_schema["required"]
    assert "add_units" in properties["goalType"]["enum"]
    node = properties["exactTargets"]
    assert node["type"] == "array"
    assert node["maxItems"] == 20
    target = TURN_OUTPUT_SCHEMA["$defs"]["ExactTarget"]
    assert target["additionalProperties"] is False
    assert set(target["required"]) == set(target["properties"]) == {
        "schoolName", "majorName", "volunteerId",
    }
    # 可空字符串统一归一化为类型数组（nullable 归一化之后）
    for field in ("schoolName", "majorName", "volunteerId"):
        assert target["properties"][field]["type"] == ["string", "null"]
    assert target["properties"]["schoolName"]["maxLength"] == 80
    assert target["properties"]["majorName"]["maxLength"] == 120
    assert target["properties"]["volunteerId"]["maxLength"] == 128
    bad_any, bad_req = scan(TURN_OUTPUT_SCHEMA)
    assert bad_any == []
    assert bad_req == []


def test_turn_output_schema_declares_scoped_add_fields() -> None:
    proposal = TURN_OUTPUT_SCHEMA["properties"]["proposalRequest"]["anyOf"][0]
    goal = proposal["properties"]["goalType"]
    assert "add_units_by_scope" in goal["enum"]
    assert "addCount" in proposal["properties"]
    assert "addCount" in proposal["required"]


def test_preview_turn_mislabeled_as_recommendation_downgrades_to_text() -> None:
    from app.gateway.contracts import TurnOutput

    output = TurnOutput(
        responseType="recommendation",
        message="按范围加入预览",
        executionStatus="partial",
        proposalRequest={
            "goalType": "add_units_by_scope",
            "sourceVersionGuard": 5,
            "addCount": 2,
            "exactTargets": [],
            "targetScopes": [
                {"scopeType": "region", "name": "安徽", "normalizedName": "安徽", "entityType": "region"}
            ],
        },
    )

    # 预览卡不是“推荐结论”：没有 artifactRefs 时降级为 text，而不是整轮失败。
    assert output.response_type == "text"
