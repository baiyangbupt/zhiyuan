from app.domain.career_slots import (
    CAREER_FURTHER_STUDY,
    CAREER_MARKET_EMPLOYMENT,
    CAREER_STABLE_EMPLOYMENT,
    CAREER_SYSTEM_PUBLIC_SERVICE,
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
