"""Shared career-direction slot definitions and label helpers."""

from __future__ import annotations

CAREER_SYSTEM_PUBLIC_SERVICE = "system_public_service"
CAREER_STABLE_EMPLOYMENT = "stable_employment"
CAREER_FURTHER_STUDY = "further_study"
CAREER_MARKET_EMPLOYMENT = "market_employment"

CAREER_LABEL_MAP: dict[str, str] = {
    CAREER_SYSTEM_PUBLIC_SERVICE: "体制内/考公导向",
    CAREER_STABLE_EMPLOYMENT: "稳定就业导向",
    CAREER_FURTHER_STUDY: "深造发展导向",
    CAREER_MARKET_EMPLOYMENT: "市场化就业导向",
}

CAREER_SLOT_VALUES: tuple[str, ...] = tuple(CAREER_LABEL_MAP.keys())

CAREER_ALIAS_MAP: dict[str, str] = {
    "体制内": CAREER_SYSTEM_PUBLIC_SERVICE,
    "考公": CAREER_SYSTEM_PUBLIC_SERVICE,
    "考编": CAREER_SYSTEM_PUBLIC_SERVICE,
    "公务员": CAREER_SYSTEM_PUBLIC_SERVICE,
    "事业单位": CAREER_SYSTEM_PUBLIC_SERVICE,
    "进编制": CAREER_SYSTEM_PUBLIC_SERVICE,
    "进体制": CAREER_SYSTEM_PUBLIC_SERVICE,
    "体制内/考公导向": CAREER_SYSTEM_PUBLIC_SERVICE,
    "稳定": CAREER_STABLE_EMPLOYMENT,
    "稳定就业": CAREER_STABLE_EMPLOYMENT,
    "稳定就业导向": CAREER_STABLE_EMPLOYMENT,
    "求稳": CAREER_STABLE_EMPLOYMENT,
    "工作稳定": CAREER_STABLE_EMPLOYMENT,
    "读研": CAREER_FURTHER_STUDY,
    "保研": CAREER_FURTHER_STUDY,
    "深造": CAREER_FURTHER_STUDY,
    "深造发展导向": CAREER_FURTHER_STUDY,
    "市场化就业": CAREER_MARKET_EMPLOYMENT,
    "市场化就业导向": CAREER_MARKET_EMPLOYMENT,
    "企业就业": CAREER_MARKET_EMPLOYMENT,
    "大城市就业": CAREER_MARKET_EMPLOYMENT,
}


def is_career_slot(value: str | None) -> bool:
    return bool(value and value in CAREER_LABEL_MAP)


def to_career_label(value: str) -> str:
    return CAREER_LABEL_MAP.get(value, value)


def normalize_career_slots(values: list[str] | None) -> list[str]:
    if not values:
        return []
    result: list[str] = []
    for value in values:
        slot = CAREER_ALIAS_MAP.get(str(value or "").strip(), value)
        if is_career_slot(slot) and slot not in result:
            result.append(slot)
    return result


def to_career_labels(values: list[str] | None) -> list[str]:
    return [to_career_label(value) for value in normalize_career_slots(values)]
