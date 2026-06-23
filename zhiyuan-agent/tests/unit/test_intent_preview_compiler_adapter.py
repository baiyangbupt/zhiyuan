import importlib.util
import sys
from pathlib import Path


ADAPTER_PATH = Path(__file__).resolve().parents[2] / "examples" / "intent_preview_compiler_adapter.py"
SINK_CONTRACT_PATH = Path(__file__).resolve().parents[2] / "examples" / "compiled_pending_sink_contract.py"

ADAPTER_SPEC = importlib.util.spec_from_file_location("intent_preview_compiler_adapter", ADAPTER_PATH)
assert ADAPTER_SPEC and ADAPTER_SPEC.loader
adapter = importlib.util.module_from_spec(ADAPTER_SPEC)
sys.modules[ADAPTER_SPEC.name] = adapter
ADAPTER_SPEC.loader.exec_module(adapter)

SINK_SPEC = importlib.util.spec_from_file_location("compiled_pending_sink_contract", SINK_CONTRACT_PATH)
assert SINK_SPEC and SINK_SPEC.loader
sink_contract = importlib.util.module_from_spec(SINK_SPEC)
sys.modules[SINK_SPEC.name] = sink_contract
SINK_SPEC.loader.exec_module(sink_contract)


def test_intent_preview_compiler_adapter_fixture_passes():
    cases = adapter._load_cases(
        str(Path(__file__).resolve().parents[2] / "examples" / "intent_preview_compiler_adapter_320_cases.json")
    )

    report = adapter.build_report(cases)

    assert report["summary"]["total"] == 5
    assert report["summary"]["passed"] == 5
    assert report["summary"]["byPendingType"] == {"intent_change": 2, "none": 3}
    assert report["summary"]["blockingReasons"] == {
        "intent_preview_requires_confirmed_stage": 1,
        "intent_preview_requires_selected_values": 1,
        "constraint_intent_requires_scope": 1,
    }


def test_intent_preview_compiled_preference_can_enter_intent_sink_contract():
    compiled = adapter.build_compiled_proposal(
        {
            "caseId": "preference",
            "batch": "01",
            "previewPayload": {
                "status": "ready",
                "analysisStage": "confirmed",
                "intentMode": "preference",
                "items": [
                    {
                        "content": "偏好地域：北京",
                        "selected": True,
                        "value": {"city_intents": {"province": ["北京"]}},
                    }
                ],
            },
        }
    )

    sink_request = sink_contract._build_sink_request(compiled)

    assert sink_request["sinkType"] == "intent"
    assert sink_request["allowed"] is True
    assert sink_request["actionFamily"] == "apply_selected_intents"
    assert sink_request["payload"]["intentPayload"]["merged"] == {
        "city_intents": {"province": ["北京"]}
    }


def test_intent_preview_blocked_case_cannot_enter_pending_sink():
    compiled = adapter.build_compiled_proposal(
        {
            "caseId": "empty",
            "batch": "01",
            "previewPayload": {
                "status": "ready",
                "analysisStage": "confirmed",
                "intentMode": "preference",
                "items": [],
            },
        }
    )

    sink_request = sink_contract._build_sink_request(compiled)

    assert compiled["pendingType"] == "none"
    assert "intent_preview_requires_selected_values" in compiled["blockingReasons"]
    assert sink_request["sinkType"] == "none"
    assert sink_request["allowed"] is False
    assert "no_pending_requested" in sink_request["blockingReasons"]
