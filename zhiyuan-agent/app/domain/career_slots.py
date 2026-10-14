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
    # v1 统一词表（2026-10-14 拍板）：入口别名（中/英/近义）→ 四槽；落库只写中文规范标签。
    # 英文槽位名本身也是合法入口（模型/旧数据可能带它进场）。
    CAREER_SYSTEM_PUBLIC_SERVICE: CAREER_SYSTEM_PUBLIC_SERVICE,
    CAREER_STABLE_EMPLOYMENT: CAREER_STABLE_EMPLOYMENT,
    CAREER_FURTHER_STUDY: CAREER_FURTHER_STUDY,
    CAREER_MARKET_EMPLOYMENT: CAREER_MARKET_EMPLOYMENT,
    "体制内": CAREER_SYSTEM_PUBLIC_SERVICE,
    "体制": CAREER_SYSTEM_PUBLIC_SERVICE,
    "考公": CAREER_SYSTEM_PUBLIC_SERVICE,
    "考编": CAREER_SYSTEM_PUBLIC_SERVICE,
    "公务员": CAREER_SYSTEM_PUBLIC_SERVICE,
    "事业单位": CAREER_SYSTEM_PUBLIC_SERVICE,
    "进编制": CAREER_SYSTEM_PUBLIC_SERVICE,
    "进体制": CAREER_SYSTEM_PUBLIC_SERVICE,
    "编制": CAREER_SYSTEM_PUBLIC_SERVICE,
    "铁饭碗": CAREER_SYSTEM_PUBLIC_SERVICE,
    "体制内/考公导向": CAREER_SYSTEM_PUBLIC_SERVICE,
    "gov": CAREER_SYSTEM_PUBLIC_SERVICE,
    "public_service": CAREER_SYSTEM_PUBLIC_SERVICE,
    "稳定": CAREER_STABLE_EMPLOYMENT,
    "稳定就业": CAREER_STABLE_EMPLOYMENT,
    "稳定发展": CAREER_STABLE_EMPLOYMENT,
    "稳定就业导向": CAREER_STABLE_EMPLOYMENT,
    "求稳": CAREER_STABLE_EMPLOYMENT,
    "工作稳定": CAREER_STABLE_EMPLOYMENT,
    "稳定工作": CAREER_STABLE_EMPLOYMENT,
    "stable_job": CAREER_STABLE_EMPLOYMENT,
    "stability": CAREER_STABLE_EMPLOYMENT,
    "读研": CAREER_FURTHER_STUDY,
    "保研": CAREER_FURTHER_STUDY,
    "考研": CAREER_FURTHER_STUDY,
    "升学": CAREER_FURTHER_STUDY,
    "深造": CAREER_FURTHER_STUDY,
    "读博": CAREER_FURTHER_STUDY,
    "研究生": CAREER_FURTHER_STUDY,
    "硕博": CAREER_FURTHER_STUDY,
    "学术发展": CAREER_FURTHER_STUDY,
    "深造发展导向": CAREER_FURTHER_STUDY,
    "postgraduate": CAREER_FURTHER_STUDY,
    "further_education": CAREER_FURTHER_STUDY,
    "市场化就业": CAREER_MARKET_EMPLOYMENT,
    "市场化就业导向": CAREER_MARKET_EMPLOYMENT,
    "市场化": CAREER_MARKET_EMPLOYMENT,
    "企业就业": CAREER_MARKET_EMPLOYMENT,
    "进企业": CAREER_MARKET_EMPLOYMENT,
    "去企业": CAREER_MARKET_EMPLOYMENT,
    "就业导向": CAREER_MARKET_EMPLOYMENT,
    "大城市就业": CAREER_MARKET_EMPLOYMENT,
    "就业": CAREER_MARKET_EMPLOYMENT,
    "market": CAREER_MARKET_EMPLOYMENT,
    "market_employment": CAREER_MARKET_EMPLOYMENT,
    "enterprise_employment": CAREER_MARKET_EMPLOYMENT,
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


def normalize_career_labels(values: list[str] | None) -> list[str]:
    """入口值（中/英/别名/规范标签混着来）→ **中文规范标签**（v1 唯一落库形式）。

    与 `normalize_career_slots` 的差别只有一个：出口是标签而不是槽位名——
    `latentProfile.futureDevelopment.careerTypes` 只落中文标签（2026-10-14 拍板），
    槽位名继续只做内部分类键。
    """
    return to_career_labels(values)


def merge_career_labels(existing: list[str] | None, incoming: list[str] | None) -> list[str]:
    """并集（保留先出现的顺序）：写 latent 前与既有值对齐的合并口径（幂等、可重放）。"""
    merged = normalize_career_labels(existing)
    for label in normalize_career_labels(incoming):
        if label not in merged:
            merged.append(label)
    return merged


def diff_career_labels(existing: list[str] | None, incoming: list[str] | None) -> list[str]:
    """新增部分（用于执行结果里给人看的 actualChanges）。"""
    current = normalize_career_labels(existing)
    return [label for label in normalize_career_labels(incoming) if label not in current]
