from app.agent.context import PlanningSummary, RequestContext, ScoreDetail
from app.resolver.region_safety_tradeoff_renderer import render_region_safety_tradeoff_reply


def _context() -> RequestContext:
    return RequestContext(
        userid="u1",
        sessionid="s1",
        score_detail=ScoreDetail(
            province="山东",
            total_score=450,
            subject_list=["物理", "历史", "地理"],
            sex="女",
        ),
        planning_summary=PlanningSummary(
            ordered_total=4,
            ordered_target_total=4,
            tier_counts={"冲": 2, "稳": 2, "保": 0},
        ),
    )


def test_render_region_safety_tradeoff_uses_major_mode_plan_facts():
    state = {
        "orderedPlanState": {
            "summary": {"unitTotal": 4, "targetUnitCount": 4, "unitTierCounts": {"冲": 2, "稳": 2, "保": 0}},
            "items": [
                {
                    "volunteerId": "tj-1",
                    "schoolName": "天津财经大学珠江学院",
                    "majorName": "会计学",
                    "tier": "稳",
                },
                {
                    "volunteerId": "xj-1",
                    "schoolName": "新疆理工学院",
                    "majorName": "金融学",
                    "tier": "稳",
                },
            ],
        },
        "candidatePoolState": {
            "items": [
                {
                    "volunteerId": "tj-1",
                    "schoolName": "天津财经大学珠江学院",
                    "majorName": "会计学",
                    "provinceName": "天津",
                    "cityName": "天津",
                    "schoolNature": "民办",
                    "tier": "稳",
                    "admissionRatio": 58,
                    "tuitionPerYear": 15000,
                },
                {
                    "volunteerId": "xj-1",
                    "schoolName": "新疆理工学院",
                    "majorName": "金融学",
                    "provinceName": "新疆",
                    "cityName": "阿克苏",
                    "schoolNature": "公办",
                    "tier": "稳",
                    "admissionRatio": 70,
                    "tuitionPerYear": 3200,
                },
            ],
        },
        "reviewState": {"checks": [{"passed": False, "level": "risk", "summary": "保区占比过低"}]},
    }

    reply = render_region_safety_tradeoff_reply("北京天津想去但别最后没学上", state, _context())

    assert reply is not None
    assert "想去北京、天津" in reply
    assert "冲 2、稳 2、保 0" in reply
    assert "天津财经大学珠江学院-会计学" in reply
    assert "当前方案里命中北京、天津的有 1 个" in reply
    assert "新疆理工学院-金融学" in reply
    assert "录取率58%" in reply
    assert "没有修改方案" in reply


def test_render_region_safety_tradeoff_uses_major_group_inner_major_name():
    state = {
        "orderedPlanState": {
            "summary": {"unitTotal": 2, "targetUnitCount": 2, "unitTierCounts": {"冲": 1, "稳": 1, "保": 0}},
            "items": [
                {
                    "schoolName": "天津财经大学珠江学院第01组",
                    "provinceName": "天津",
                    "cityName": "天津",
                    "schoolNature": "民办",
                    "tier": "稳",
                    "admissionRatio": 62,
                    "majorItems": [
                        {"majorName": "会计学", "admissionRatio": 62, "tuitionPerYear": 15000},
                        {"majorName": "审计学", "admissionRatio": 59, "tuitionPerYear": 15000},
                    ],
                },
                {
                    "schoolName": "喀什大学第01组",
                    "provinceName": "新疆",
                    "cityName": "喀什",
                    "schoolNature": "公办",
                    "tier": "稳",
                    "admissionRatio": 72,
                    "majorItems": [{"majorName": "金融学", "admissionRatio": 72, "tuitionPerYear": 3500}],
                },
            ],
        }
    }

    reply = render_region_safety_tradeoff_reply("孩子就想去北京天津但分数不算高太冒险吗", state, _context())

    assert reply is not None
    assert "天津财经大学珠江学院第01组-会计学" in reply
    assert "喀什大学第01组-金融学" in reply


def test_render_region_safety_tradeoff_returns_none_without_plan_items():
    reply = render_region_safety_tradeoff_reply(
        "孩子就想去北京天津但分数不算高太冒险吗",
        {"orderedPlanState": {"summary": {"unitTotal": 2}, "items": []}},
        _context(),
    )

    assert reply is None
