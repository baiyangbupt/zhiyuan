import unittest
from copy import deepcopy
from unittest.mock import patch

import pandas as pd

from services import recommendation


class _StubLoader:
    def __init__(self, tag_major=None):
        self._tag_major = tag_major or {}

    def get_tag_major(self):
        return self._tag_major

    def get_tag_major_02(self):
        return self._tag_major

    def lookup_evaluate_data(self, school_id, major_id, submajor_id):
        return None

    def lookup_evaluate_02_data(self, school_id, major_id, submajor_id):
        return None

    def lookup_special_data(self, school_id, major_id, submajor_id):
        return False

    def lookup_degree_data(self, school_id, major_id, submajor_id):
        return None


def _build_major_score_df(*major_ids: str) -> pd.DataFrame:
    rows = []
    for major_id in major_ids:
        rows.append(
            {
                "major_id": str(major_id),
                "gender_index": 50.0,
                "satisfy_index": 60.0,
                "salary_avg": 70.0,
                "hot_index": 80.0,
                "major_score": 50.0,
            }
        )
    return pd.DataFrame(rows)


def _build_college_score_df(
    category: str = "",
    nature: str = "",
    tag: str = "",
    postgraduate: str = "",
) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "school_id": "S1",
                "province_gdp": 50.0,
                "city_level": 50.0,
                "upgrade_ratio": 50.0,
                "postgraduate_recommend_ratio": 50.0,
                "gaotu_rank": 50.0,
                "level_score": 50.0,
                "college_score": 60.0,
                "category": category,
                "nature": nature,
                "postgraduate": postgraduate,
                "tag": tag,
            }
        ]
    )


def _studentinfo() -> dict:
    return {
        "batch": {"level": "01"},
        "filterType": "1",
    }


def _profileinfo(
    *,
    positive_tags=None,
    negative_tags=None,
    positive_city_codes=None,
    negative_city_codes=None,
    positive_province_codes=None,
    negative_province_codes=None,
) -> dict:
    return {
        "college_info": {"values_code": [], "values_emotion": []},
        "negative_college_info": {"values_code": [], "values_emotion": []},
        "major_intent": {
            "level2_code": [],
            "level2_emotion": [],
            "level3_code": [],
            "level3_emotion": [],
        },
        "negative_major_intent": {
            "level2_code": [],
            "level2_emotion": [],
            "level3_code": [],
            "level3_emotion": [],
        },
        "city_info": {
            "city_code": positive_city_codes or [],
            "city_emotion": ["Strong"] * len(positive_city_codes or []),
            "province_code": positive_province_codes or [],
            "province_emotion": ["Strong"] * len(positive_province_codes or []),
        },
        "negative_city_info": {
            "city_code": negative_city_codes or [],
            "city_emotion": ["Strong"] * len(negative_city_codes or []),
            "province_code": negative_province_codes or [],
            "province_emotion": ["Strong"] * len(negative_province_codes or []),
        },
        "tag_info": {
            "values": positive_tags or [],
            "values_emotion": ["Strong"] * len(positive_tags or []),
        },
        "negative_tag_info": {
            "values": negative_tags or [],
            "values_emotion": ["Strong"] * len(negative_tags or []),
        },
    }


def _volunteerinfo(major_id: str = "1001", subcategory_id: str = "2001") -> list[dict]:
    return [
        {
            "schoolId": "S1",
            "provinceId": "P1",
            "cityId": "C1",
            "majorList": [
                {
                    "majorId": major_id,
                    "subCategoryId": subcategory_id,
                    "planMoney": "5000元/年",
                }
            ],
        }
    ]


class RecommendationMappingTest(unittest.TestCase):
    def _run_recommendation(
        self,
        *,
        volunteerinfo,
        profileinfo,
        tag_major=None,
        major_ids=("1001",),
        college_category="",
        college_nature="",
        college_tag="",
        college_postgraduate="",
    ):
        loader = _StubLoader(tag_major=tag_major)
        with patch.object(recommendation, "major_Recommand", return_value=(_build_major_score_df(*major_ids), {})), \
                patch.object(
                    recommendation,
                    "college_Recommand",
                    return_value=(
                        _build_college_score_df(
                            category=college_category,
                            nature=college_nature,
                            tag=college_tag,
                            postgraduate=college_postgraduate,
                        ),
                        {},
                    ),
                ), \
                patch.object(recommendation, "get_data_loader", return_value=loader):
            return recommendation.volunteer_Recommand(
                studentinfo=_studentinfo(),
                volunteerinfo=deepcopy(volunteerinfo),
                profileinfo=deepcopy(profileinfo),
            )

    def test_subcategory_tag_info_boosts_major_score(self):
        base_result = self._run_recommendation(
            volunteerinfo=_volunteerinfo(),
            profileinfo=_profileinfo(),
            tag_major={"计算机类": {"id": ["2001"]}},
        )
        tagged_result = self._run_recommendation(
            volunteerinfo=_volunteerinfo(),
            profileinfo=_profileinfo(positive_tags=["计算机类"]),
            tag_major={"计算机类": {"id": ["2001"]}},
        )

        base_major = base_result[0]["majorList"][0]
        tagged_major = tagged_result[0]["majorList"][0]

        self.assertGreater(tagged_major["major_score_new"], base_major["major_score_new"])
        self.assertIn("计算机类（类）标签正向加分", tagged_major["major_remark"])

    def test_major_group_uses_subcategory_when_major_id_is_zero(self):
        result = self._run_recommendation(
            volunteerinfo=_volunteerinfo(major_id="0", subcategory_id="2001"),
            profileinfo=_profileinfo(positive_tags=["计算机类"]),
            tag_major={"计算机类": {"id": ["2001"]}},
            major_ids=("2001",),
        )

        major = result[0]["majorList"][0]
        self.assertGreater(major["major_score_new"], 50.0)
        self.assertIn("计算机类标签正向加分", major["major_remark"])
        self.assertNotIn("未知专业", major["major_remark"])

    def test_school_category_tag_info_still_affects_college_score(self):
        base_result = self._run_recommendation(
            volunteerinfo=_volunteerinfo(),
            profileinfo=_profileinfo(),
            tag_major={},
            college_category="理工",
        )
        tagged_result = self._run_recommendation(
            volunteerinfo=_volunteerinfo(),
            profileinfo=_profileinfo(positive_tags=["理工院校"]),
            tag_major={},
            college_category="理工",
        )

        base_plan = base_result[0]
        tagged_plan = tagged_result[0]

        self.assertGreater(tagged_plan["college_score_new"], base_plan["college_score_new"])
        self.assertIn("院校类型正向加分", tagged_plan["college_remark"])

    def test_negative_subcategory_tag_reduces_major_score(self):
        base_result = self._run_recommendation(
            volunteerinfo=_volunteerinfo(),
            profileinfo=_profileinfo(),
            tag_major={"材料类": {"id": ["2001"]}},
        )
        tagged_result = self._run_recommendation(
            volunteerinfo=_volunteerinfo(),
            profileinfo=_profileinfo(negative_tags=["材料类"]),
            tag_major={"材料类": {"id": ["2001"]}},
        )

        base_major = base_result[0]["majorList"][0]
        tagged_major = tagged_result[0]["majorList"][0]

        self.assertLess(tagged_major["major_score_new"], base_major["major_score_new"])
        self.assertIn("材料类（类）标签负向减分", tagged_major["major_remark"])

    def test_positive_province_preference_increases_college_score(self):
        base_result = self._run_recommendation(
            volunteerinfo=_volunteerinfo(),
            profileinfo=_profileinfo(),
            tag_major={},
        )
        preferred_result = self._run_recommendation(
            volunteerinfo=_volunteerinfo(),
            profileinfo=_profileinfo(positive_province_codes=["P1"]),
            tag_major={},
        )

        base_plan = base_result[0]
        preferred_plan = preferred_result[0]

        self.assertGreater(preferred_plan["college_score_new"], base_plan["college_score_new"])
        self.assertIn("省份正向加分", preferred_plan["college_remark"])

    def test_negative_city_preference_reduces_college_score(self):
        base_result = self._run_recommendation(
            volunteerinfo=_volunteerinfo(),
            profileinfo=_profileinfo(),
            tag_major={},
        )
        rejected_result = self._run_recommendation(
            volunteerinfo=_volunteerinfo(),
            profileinfo=_profileinfo(negative_city_codes=["C1"]),
            tag_major={},
        )

        base_plan = base_result[0]
        rejected_plan = rejected_result[0]

        self.assertLess(rejected_plan["college_score_new"], base_plan["college_score_new"])
        self.assertIn("城市负向减分", rejected_plan["college_remark"])

    def test_school_nature_tag_info_still_affects_college_score(self):
        base_result = self._run_recommendation(
            volunteerinfo=_volunteerinfo(),
            profileinfo=_profileinfo(),
            tag_major={},
            college_nature="公办",
        )
        tagged_result = self._run_recommendation(
            volunteerinfo=_volunteerinfo(),
            profileinfo=_profileinfo(positive_tags=["公办院校"]),
            tag_major={},
            college_nature="公办",
        )

        base_plan = base_result[0]
        tagged_plan = tagged_result[0]

        self.assertGreater(tagged_plan["college_score_new"], base_plan["college_score_new"])
        self.assertIn("院校性质正向加分", tagged_plan["college_remark"])

    def test_negative_province_preference_reduces_college_score(self):
        base_result = self._run_recommendation(
            volunteerinfo=_volunteerinfo(),
            profileinfo=_profileinfo(),
            tag_major={},
        )
        rejected_result = self._run_recommendation(
            volunteerinfo=_volunteerinfo(),
            profileinfo=_profileinfo(negative_province_codes=["P1"]),
            tag_major={},
        )

        base_plan = base_result[0]
        rejected_plan = rejected_result[0]

        self.assertLess(rejected_plan["college_score_new"], base_plan["college_score_new"])
        self.assertIn("省份负向减分", rejected_plan["college_remark"])

    def test_city_preference_takes_priority_over_province_preference(self):
        prioritized_result = self._run_recommendation(
            volunteerinfo=_volunteerinfo(),
            profileinfo=_profileinfo(
                positive_province_codes=["P1"],
                negative_city_codes=["C1"],
            ),
            tag_major={},
        )

        prioritized_plan = prioritized_result[0]

        self.assertIn("城市负向减分", prioritized_plan["college_remark"])
        self.assertNotIn("省份正向加分", prioritized_plan["college_remark"])

    def test_school_level_tag_from_tag_field_affects_college_score(self):
        base_result = self._run_recommendation(
            volunteerinfo=_volunteerinfo(),
            profileinfo=_profileinfo(),
            tag_major={},
            college_tag="双一流",
        )
        tagged_result = self._run_recommendation(
            volunteerinfo=_volunteerinfo(),
            profileinfo=_profileinfo(positive_tags=["双一流院校"]),
            tag_major={},
            college_tag="双一流",
        )

        base_plan = base_result[0]
        tagged_plan = tagged_result[0]

        self.assertGreater(tagged_plan["college_score_new"], base_plan["college_score_new"])
        self.assertIn("院校层次正向加分", tagged_plan["college_remark"])

    def test_school_postgraduate_tag_info_affects_college_score(self):
        base_result = self._run_recommendation(
            volunteerinfo=_volunteerinfo(),
            profileinfo=_profileinfo(),
            tag_major={},
            college_postgraduate="保研",
        )
        tagged_result = self._run_recommendation(
            volunteerinfo=_volunteerinfo(),
            profileinfo=_profileinfo(positive_tags=["保研院校"]),
            tag_major={},
            college_postgraduate="保研",
        )

        base_plan = base_result[0]
        tagged_plan = tagged_result[0]

        self.assertGreater(tagged_plan["college_score_new"], base_plan["college_score_new"])
        self.assertIn("院校硕博点正向加分", tagged_plan["college_remark"])


if __name__ == "__main__":
    unittest.main()
