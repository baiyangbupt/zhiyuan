"""B2：admission.* 结果分型。

三种生产者的形状各有一份 fixture：历史数组（无概率）、program 分层列表
（`enrollRatio` 是字符串）、资格布尔。形状取自 Java DTO 序列化结果，
不是从消费侧的期望编的。
"""
from __future__ import annotations

import pytest

from app.admission.tool_results import (
    normalize_eligibility,
    normalize_history,
    normalize_probability,
    percentage,
)

QUERY = {
    "schoolId": "school-fixture",
    "majorId": "major-fixture",
    "areaId": "area-fixture",
    "batch": "batch-fixture",
}


def test_history_does_not_require_probability() -> None:
    result = normalize_history(
        {"data": [{"year": 2025, "minScore": 612, "minPos": 9000}], "evidence": []},
        QUERY,
    )

    assert result["kind"] == "history"
    assert result["data"][0]["minScore"] == 612
    # 历史事实里**不该**出现录取率：那是另一种数据，混进来就会被当概率用。
    assert "unitAdmissionRate" not in result["data"][0]
    assert result["status"] == "ok"


def test_history_keeps_query_scope_when_the_row_omits_it() -> None:
    result = normalize_history({"data": [{"year": 2025, "minScore": 612}]}, QUERY)

    row = result["data"][0]
    assert row["schoolId"] == "school-fixture"
    assert row["areaId"] == "area-fixture"


def test_history_reports_empty_rather_than_fabricating_a_row() -> None:
    result = normalize_history({"data": []}, QUERY)

    assert result["status"] == "empty"
    assert result["data"] == []


def test_percentage_requires_an_explicit_unit() -> None:
    # 缺单位时**不猜**：猜错的方向是把 0.5% 放大成 50%，那是"稳上"级的错误。
    with pytest.raises(ValueError, match="probability_unit_missing"):
        percentage("50", None)
    with pytest.raises(ValueError, match="unknown_probability_unit"):
        percentage("50", "ratio")


def test_percentage_converts_fraction_and_strips_the_percent_sign() -> None:
    assert percentage("0.5", "fraction") == 50
    assert percentage("50%", "percent") == 50
    assert percentage(45, "percent") == 45


def test_percentage_refuses_out_of_contract_values_instead_of_clamping() -> None:
    # 上游若真的会返回 100，那要连着业务口径一起改，不能静默截断成 99——
    # 截断后的值看起来合理，而它已经不代表上游说的任何事。
    with pytest.raises(ValueError, match="probability_out_of_contract"):
        percentage("100", "percent")
    with pytest.raises(ValueError, match="probability_out_of_contract"):
        percentage("-1", "percent")


def test_probability_takes_the_unit_rate_from_the_row_not_the_school_rate() -> None:
    """学校口径的率**不能**复制到每个专业组。"""
    result = normalize_probability(
        {
            "data": [
                {"admissionUnitId": "unit-1", "groupCode": "101", "unitAdmissionRate": "45%"},
                {"admissionUnitId": "unit-2", "groupCode": "102", "unitAdmissionRate": "62%"},
            ]
        },
        QUERY,
        "percent",
    )

    assert [row["groupCode"] for row in result["data"]] == ["101", "102"]
    assert [row["unitAdmissionRate"] for row in result["data"]] == [45.0, 62.0]


def test_probability_without_a_unit_rate_is_insufficient_not_zero() -> None:
    result = normalize_probability(
        {"data": [{"admissionUnitId": "unit-1", "groupCode": "101", "enrollRatio": "45%"}]},
        QUERY,
        "percent",
    )

    # 缺单位概率 = 不足，**不是**零。补零会让"没有数据"看起来像"录取概率 0%"。
    assert result["status"] == "insufficient_data"
    assert result["data"] == []
    assert "unit_admission_rate_missing" in result["limitations"]


def test_probability_never_invents_a_default_from_history_rows() -> None:
    """只给历史分数时不能凑出一个概率。"""
    result = normalize_probability(
        {"data": [{"year": 2025, "minScore": 612, "minPos": 9000}]},
        QUERY,
        "percent",
    )

    assert result["status"] == "insufficient_data"
    assert result["data"] == []


def test_eligibility_keeps_unknown_distinct_from_ineligible() -> None:
    unknown = normalize_eligibility({}, QUERY)

    assert unknown["data"]["verdict"] == "unknown"
    assert "eligibility_unknown" in unknown["limitations"]

    ineligible = normalize_eligibility({"eligible": False}, QUERY)

    assert ineligible["data"]["verdict"] == "ineligible"
    assert ineligible["limitations"] == []


def test_eligibility_declares_what_it_checked_and_what_it_did_not() -> None:
    result = normalize_eligibility({"eligible": True, "reasons": ["选科满足"]}, QUERY)

    # 只写"符合"，学生无法知道那是"选科符合"还是"什么都符合"。
    assert result["data"]["checkedConstraints"] == ["subjects"]
    assert "medical" in result["data"]["uncheckedConstraints"]
    assert "policy" in result["data"]["uncheckedConstraints"]


def test_every_result_carries_the_unified_outer_shape() -> None:
    for result in (
        normalize_history({"data": [{"year": 2025}]}, QUERY),
        normalize_probability({"data": []}, QUERY, "percent"),
        normalize_eligibility({"eligible": True}, QUERY),
    ):
        assert set(result) >= {
            "schemaVersion",
            "kind",
            "status",
            "data",
            "evidenceRefs",
            "limitations",
            "nextCursor",
        }
        assert result["schemaVersion"] == 1
