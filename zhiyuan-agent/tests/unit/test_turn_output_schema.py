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
