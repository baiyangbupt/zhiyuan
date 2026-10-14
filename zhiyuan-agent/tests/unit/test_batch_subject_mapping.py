"""resolve_subject_type 的首选项判定（选科适配 P0-2，2026-10-14）。

回归背景：3+1+2 省份原来用裸子串匹配（`"物" in "生物"` 先于历史判断命中），
"历史+生物" 被误判成物理类（WL）。现在先按整词判首选：含历史=历史类，含物理且不含历史=物理类。
"""

import pytest

from app.util.batch_subject_mapping import resolve_subject_type

# 430000 湖南 / 130000 河北 / 340000 安徽：新高考 WL/LS；310000 上海：综合 N。
HUNAN = "430000"
HEBEI = "130000"
ANHUI = "340000"
SHANGHAI = "310000"


@pytest.mark.parametrize(
    ("subjects", "expected"),
    [
        # 历史类：首选历史（此前"历史+生物"因 "物" in "生物" 被判 WL）
        (["历史", "生物"], "LS"),
        (["历史", "地理", "政治"], "LS"),
        (["历史", "化学", "生物"], "LS"),
        # 物理类
        (["物理", "生物"], "WL"),
        (["物理", "化学", "生物"], "WL"),
        (["物理", "政治", "地理"], "WL"),
        # 首选冲突（数据异常）：含历史一律历史类，与"先判首选"口径一致
        (["物理", "历史", "生物"], "LS"),
        # 单字缩写形态
        (["物", "生"], "WL"),
        (["史", "生"], "LS"),
        # 无首选信息的非法组合：保持旧的默认物理口径（不因"生物"误推物理）
        (["生物", "地理", "政治"], "WL"),
        # 旧写法仍走包含匹配兜底
        (["文科"], "LS"),
        (["理科"], "WL"),
    ],
)
def test_resolve_subject_type_first_choice(subjects, expected):
    assert resolve_subject_type(HUNAN, subjects) == expected


@pytest.mark.parametrize("area", [HUNAN, HEBEI, ANHUI])
def test_history_plus_biology_is_history_track_across_provinces(area):
    """核心回归：历史+生物 在任一 WL/LS 省份都必须判历史类。"""
    assert resolve_subject_type(area, ["历史", "生物"]) == "LS"


def test_physics_plus_biology_stays_physics_track():
    assert resolve_subject_type(HUNAN, ["物理", "生物"]) == "WL"


def test_comprehensive_province_returns_n():
    assert resolve_subject_type(SHANGHAI, ["物理", "化学", "生物"]) == "N"
