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
