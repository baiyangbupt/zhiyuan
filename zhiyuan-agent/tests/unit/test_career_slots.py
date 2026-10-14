import pytest

from app.domain.career_slots import (
    CAREER_FURTHER_STUDY,
    CAREER_MARKET_EMPLOYMENT,
    CAREER_STABLE_EMPLOYMENT,
    CAREER_SYSTEM_PUBLIC_SERVICE,
    diff_career_labels,
    merge_career_labels,
    normalize_career_labels,
    normalize_career_slots,
    to_career_label,
    to_career_labels,
)


def test_to_career_label_and_labels():
    assert to_career_label(CAREER_SYSTEM_PUBLIC_SERVICE) == "体制内/考公导向"
    assert to_career_labels([CAREER_STABLE_EMPLOYMENT, CAREER_FURTHER_STUDY]) == [
        "稳定就业导向",
        "深造发展导向",
    ]
    assert to_career_label(CAREER_MARKET_EMPLOYMENT) == "市场化就业导向"


def test_normalize_career_slots_filters_invalid_and_deduplicates():
    assert normalize_career_slots(
        [
            CAREER_SYSTEM_PUBLIC_SERVICE,
            "unknown",
            CAREER_SYSTEM_PUBLIC_SERVICE,
            CAREER_STABLE_EMPLOYMENT,
        ]
    ) == [
        CAREER_SYSTEM_PUBLIC_SERVICE,
        CAREER_STABLE_EMPLOYMENT,
    ]


def test_normalize_career_slots_accepts_common_direction_aliases():
    assert normalize_career_slots(["体制内", "考公", "稳定就业", "读研", "企业就业"]) == [
        CAREER_SYSTEM_PUBLIC_SERVICE,
        CAREER_STABLE_EMPLOYMENT,
        CAREER_FURTHER_STUDY,
        CAREER_MARKET_EMPLOYMENT,
    ]


# ── 归一表（v1 唯一落库形式 = 中文规范标签）────────────────────────────────────
#
# 入口可以是：规范标签本身 / 英文槽位名（模型或旧数据进场）/ 中文近义词 / 自由文本里
# 常见的说法；出口**一律**是四类中文规范标签（2026-10-14 拍板："中文规范标签是唯一值"）。
# 归不了的整项丢弃（不静默映射到一个"最像的"槽位——错的方向比没有方向更糟）。


@pytest.mark.parametrize(("entry", "expected"), [
    # 规范标签幂等（再归一不动）
    ("体制内/考公导向", "体制内/考公导向"),
    ("稳定就业导向", "稳定就业导向"),
    ("深造发展导向", "深造发展导向"),
    ("市场化就业导向", "市场化就业导向"),
    # 英文槽位名（模型/旧数据可能带它进场）
    ("system_public_service", "体制内/考公导向"),
    ("stable_employment", "稳定就业导向"),
    ("further_study", "深造发展导向"),
    ("market_employment", "市场化就业导向"),
    # 中文近义（用户在对话里的自然表达）
    ("考公", "体制内/考公导向"),
    ("考编", "体制内/考公导向"),
    ("进体制", "体制内/考公导向"),
    ("考研", "深造发展导向"),
    ("保研", "深造发展导向"),
    ("读博", "深造发展导向"),
    ("求稳", "稳定就业导向"),
    ("铁饭碗", "体制内/考公导向"),
    ("进企业", "市场化就业导向"),
    ("去企业", "市场化就业导向"),
    ("大城市就业", "市场化就业导向"),
    # 英文自由说法
    ("gov", "体制内/考公导向"),
    ("public_service", "体制内/考公导向"),
    ("stability", "稳定就业导向"),
    ("postgraduate", "深造发展导向"),
    ("further_education", "深造发展导向"),
    ("enterprise_employment", "市场化就业导向"),
])
def test_normalize_career_labels_maps_every_entry_alias_to_a_canonical_label(entry, expected):
    assert normalize_career_labels([entry]) == [expected]
    assert isinstance(expected, str) and expected.endswith("导向")


def test_normalize_career_labels_filters_unknown_entries_and_deduplicates():
    assert normalize_career_labels(["考公", "当医生", "考公", "读研", "", None, "写代码"]) == [
        "体制内/考公导向",
        "深造发展导向",
    ]


def test_normalize_career_labels_returns_empty_for_missing_input():
    assert normalize_career_labels(None) == []
    assert normalize_career_labels([]) == []


def test_merge_career_labels_is_an_order_preserving_union():
    """合并口径（写 latent 前与既有值对齐）：先落库的顺序保留、两边的别名都归一。"""
    assert merge_career_labels(
        ["体制内/考公导向", "读研"], ["深造发展导向", "进企业"]
    ) == ["体制内/考公导向", "深造发展导向", "市场化就业导向"]


def test_diff_career_labels_only_reports_the_new_ones():
    """`actualChanges` 只报**新增**：已落库的方向重放不产生变化（幂等、可重放）。"""
    assert diff_career_labels(["考公"], ["考公", "market"]) == ["市场化就业导向"]
    assert diff_career_labels(["深造发展导向"], ["考研"]) == []
