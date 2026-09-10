from app.gateway.service import TURN_OUTPUT_SCHEMA


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
    proposal_schema = TURN_OUTPUT_SCHEMA["properties"]["proposalRequest"]["anyOf"][0]
    assert proposal_schema["additionalProperties"] is False
    assert proposal_schema["required"] == list(proposal_schema["properties"])
    assert TURN_OUTPUT_SCHEMA["$defs"]["ProposalScope"]["additionalProperties"] is False
    assert TURN_OUTPUT_SCHEMA["additionalProperties"] is False
