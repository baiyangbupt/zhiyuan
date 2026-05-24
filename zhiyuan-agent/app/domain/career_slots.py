"""Shared career-direction slot definitions and label helpers."""

from __future__ import annotations

CAREER_SYSTEM_PUBLIC_SERVICE = "system_public_service"
CAREER_STABLE_EMPLOYMENT = "stable_employment"
CAREER_FURTHER_STUDY = "further_study"

CAREER_LABEL_MAP: dict[str, str] = {
    CAREER_SYSTEM_PUBLIC_SERVICE: "体制内/考公导向",
    CAREER_STABLE_EMPLOYMENT: "稳定就业导向",
    CAREER_FURTHER_STUDY: "深造发展导向",
}

CAREER_SLOT_VALUES: tuple[str, ...] = tuple(CAREER_LABEL_MAP.keys())

CAREER_SLOT_KEYWORDS: dict[str, tuple[str, ...]] = {
    CAREER_SYSTEM_PUBLIC_SERVICE: (
        "体制内",
        "考公",
        "考编",
        "公务员",
        "事业单位",
        "进编制",
        "有编制",
        "进体制",
        "选调",
    ),
    CAREER_STABLE_EMPLOYMENT: (
        "稳定就业",
        "就业稳定",
        "工作稳定",
        "稳定工作",
        "求稳",
        "抗风险",
        "稳妥就业",
    ),
    CAREER_FURTHER_STUDY: (
        "读研",
        "考研",
        "保研",
        "深造",
        "继续升学",
        "升学",
    ),
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
        if is_career_slot(value) and value not in result:
            result.append(value)
    return result


def to_career_labels(values: list[str] | None) -> list[str]:
    return [to_career_label(value) for value in normalize_career_slots(values)]


def resolve_career_slots_locally(text: str | None) -> list[str]:
    normalized = str(text or "").strip()
    if not normalized:
        return []
    slots: list[str] = []
    for slot, keywords in CAREER_SLOT_KEYWORDS.items():
        if any(keyword in normalized for keyword in keywords):
            slots.append(slot)
    return normalize_career_slots(slots)
