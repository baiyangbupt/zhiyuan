import pytest

from app.admission.facts import (
    AdmissionFactError,
    adapt_backend_admission_rate,
    canonical_admission_mode,
    derive_risk_tier,
    mode_dependent_cache_key,
    validate_admission_fact,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("major", "major"),
        ("majorGroup", "major_group"),
        ("major_group", "major_group"),
    ],
)
def test_canonical_admission_mode_maps_backend_values(raw, expected):
    assert canonical_admission_mode(raw) == expected


@pytest.mark.parametrize(
    ("rate", "expected"),
    [
        (49.99, "冲"),
        (50.0, "稳"),
        (69.99, "稳"),
        (70.0, "保"),
        (98.99, "保"),
        (99.0, "保"),
    ],
)
def test_derive_risk_tier_uses_fixed_unit_boundaries(rate, expected):
    assert derive_risk_tier(rate) == expected


def test_rate_above_99_is_not_silently_classified():
    with pytest.raises(AdmissionFactError, match="unsupported_admission_rate"):
        derive_risk_tier(99.01)


def test_major_mode_requires_specific_major_and_major_group_requires_group_code():
    with pytest.raises(AdmissionFactError, match="major_required"):
        validate_admission_fact({"admissionMode": "major", "unitAdmissionRate": 40})
    with pytest.raises(AdmissionFactError, match="group_code_required"):
        validate_admission_fact(
            {
                "admissionMode": "major_group",
                "unitAdmissionRate": 40,
                "admissionUnitId": "unit-1",
                "schoolId": "school-1",
            }
        )


def test_major_group_keeps_unit_rate_separate_from_nested_major_rate():
    fact = validate_admission_fact(
        {
            "admissionMode": "major_group",
            "admissionUnitId": "unit-1",
            "groupCode": "101",
            "schoolId": "school-1",
            "unitAdmissionRate": 45,
            "riskTier": "冲",
            "majorItems": [{"majorId": "m-1", "majorAdmissionRate": 85}],
        }
    )
    assert fact["riskTier"] == "冲"
    assert fact["majorItems"][0]["majorAdmissionRate"] == 85


def test_invalid_model_tier_is_rejected_instead_of_trusted():
    with pytest.raises(AdmissionFactError, match="risk_tier_mismatch"):
        validate_admission_fact(
            {
                "admissionMode": "major",
                "admissionUnitId": "unit-1",
                "majorId": "m-1",
                "schoolId": "school-1",
                "unitAdmissionRate": 40,
                "riskTier": "保",
            }
        )


def test_duplicate_group_detail_ids_are_rejected():
    with pytest.raises(AdmissionFactError, match="duplicate_major_detail"):
        validate_admission_fact(
            {
                "admissionMode": "major_group",
                "admissionUnitId": "unit-1",
                "groupCode": "101",
                "schoolId": "school-1",
                "unitAdmissionRate": 70,
                "majorItems": [
                    {"majorId": "m-1", "majorAdmissionRate": 70},
                    {"majorId": "m-1", "majorAdmissionRate": 80},
                ],
            }
        )


def test_backend_rate_adaptation_never_invents_missing_rate():
    assert adapt_backend_admission_rate({"admissionRatio": 45}, mode="major") == 45
    assert adapt_backend_admission_rate({"schoolEnrollRatio": 75}, mode="major_group") == 75
    assert adapt_backend_admission_rate({}, mode="major") is None


def test_mode_dependent_cache_key_separates_modes():
    assert mode_dependent_cache_key("major", "unit-1") != mode_dependent_cache_key(
        "major_group", "unit-1"
    )
