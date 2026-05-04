"""测试 ScoreDetail 数据结构和解析逻辑。"""

from app.agent.context import ScoreDetail


def test_score_detail_creation():
    """测试 ScoreDetail 创建。"""
    score_detail = ScoreDetail(
        province="北京",
        total_score=620,
        subject_list=["物理", "化学", "生物"],
        sex="男",
    )

    assert score_detail.province == "北京"
    assert score_detail.total_score == 620
    assert score_detail.subject_list == ["物理", "化学", "生物"]
    assert score_detail.sex == "男"


def test_parse_score_detail_from_api_response():
    """测试从 API 响应解析 ScoreDetail。"""
    api_response = {
        "data": {
            "userScoreDetail": {
                "province": {"code": "110000", "name": "北京"},
                "totalScore": 620,
                "subjectList": [
                    {"isFirst": 1, "name": "物理", "value": "01"},
                    {"isFirst": 0, "name": "化学", "value": "05"},
                    {"isFirst": 0, "name": "生物", "value": "06"},
                ],
            }
        },
        "code": 0,
        "msg": "success",
    }

    raw_data = api_response["data"]["userScoreDetail"]
    province_name = raw_data["province"]["name"]
    total_score = raw_data["totalScore"]
    subject_list = [item["name"] for item in raw_data["subjectList"]]

    score_detail = ScoreDetail(
        province=province_name,
        total_score=total_score,
        subject_list=subject_list,
        sex="男",
    )

    assert score_detail.province == "北京"
    assert score_detail.total_score == 620
    assert score_detail.subject_list == ["物理", "化学", "生物"]
