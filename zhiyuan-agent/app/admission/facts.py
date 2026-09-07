"""权威招生事实的纯规范化与校验逻辑。

本模块只消费结构化后端字段。录取率由招生数据服务提供，Python 侧不重新计算。
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from numbers import Real
from typing import Any, Literal


AdmissionMode = Literal["major", "major_group"]


class AdmissionFactError(ValueError):
    """招生事实不满足可信边界时抛出的可分类错误。"""

    def __init__(self, code: str, message: str | None = None) -> None:
        self.code = code
        super().__init__(message or code)


_MODE_ALIASES: dict[object, AdmissionMode] = {
    "major": "major",
    "majorGroup": "major_group",
    "major_group": "major_group",
}


def canonical_admission_mode(raw: object) -> AdmissionMode:
    """将后端兼容值归一化为两个稳定的招生类型值。"""

    if isinstance(raw, str):
        normalized = raw.strip()
        try:
            return _MODE_ALIASES[normalized]
        except KeyError:
            pass
    raise AdmissionFactError("unsupported_admission_mode")


def _finite_rate(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise AdmissionFactError("unsupported_admission_rate")
    rate = float(value)
    if not math.isfinite(rate) or rate < 0 or rate > 99:
        raise AdmissionFactError("unsupported_admission_rate")
    return rate


def derive_risk_tier(rate: object) -> str:
    """按系统定义的固定边界推导招生单元风险层级。"""

    normalized = _finite_rate(rate)
    if normalized < 50:
        return "冲"
    if normalized < 70:
        return "稳"
    return "保"


def _first(value: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in value and value[key] is not None:
            return value[key]
    return None


def adapt_backend_admission_rate(value: Mapping[str, Any], *, mode: object) -> Any:
    """读取现有后端字段，不对缺失数据填充或猜测。"""

    canonical_mode = canonical_admission_mode(mode)
    unit_rate = _first(value, "unitAdmissionRate", "unit_admission_rate")
    if unit_rate is not None:
        return unit_rate
    if canonical_mode == "major":
        return _first(value, "admissionRatio", "admission_ratio")
    return _first(value, "schoolEnrollRatio", "school_enroll_ratio")


def _required(value: Mapping[str, Any], code: str, *keys: str) -> Any:
    result = _first(value, *keys)
    if result is None or (isinstance(result, str) and not result.strip()):
        raise AdmissionFactError(code)
    return result


def _normalize_major_item(item: Mapping[str, Any]) -> dict[str, Any]:
    major_id = _required(item, "major_detail_id_required", "majorId", "major_id")
    raw_rate = _first(item, "majorAdmissionRate", "major_admission_rate")
    if raw_rate is None:
        raise AdmissionFactError("major_admission_rate_required")
    rate = _finite_rate(raw_rate)
    result: dict[str, Any] = {
        "majorId": str(major_id),
        "majorAdmissionRate": rate,
    }
    for output_key, aliases in (
        ("majorName", ("majorName", "major_name")),
        ("majorCode", ("majorCode", "major_code")),
    ):
        optional = _first(item, *aliases)
        if optional is not None:
            result[output_key] = optional
    return result


def validate_admission_fact(value: Mapping[str, Any]) -> dict[str, Any]:
    """校验并规范化一个招生单元事实。

    ``major_group`` 的风险层级只由组级 ``unitAdmissionRate`` 决定；组内专业
    录取率保留为明细证据，不参与组级分层。
    """

    if not isinstance(value, Mapping):
        raise AdmissionFactError("admission_fact_required")

    mode = canonical_admission_mode(_required(value, "admission_mode_required", "admissionMode", "admission_mode"))
    # 先验证模式特有身份，调用方能得到比通用字段缺失更直接的错误。
    major_id: Any | None = None
    group_code: Any | None = None
    if mode == "major":
        major_id = _required(value, "major_required", "majorId", "major_id", "planMajorDataId", "plan_major_data_id")
    else:
        group_code = _required(value, "group_code_required", "groupCode", "group_code", "majorGroup", "major_group")

    unit_id = _required(value, "admission_unit_id_required", "admissionUnitId", "admission_unit_id", "unitId", "unit_id")
    school_id = _required(value, "school_id_required", "schoolId", "school_id", "universityId", "university_id")
    raw_rate = adapt_backend_admission_rate(value, mode=mode)
    if raw_rate is None:
        raise AdmissionFactError("admission_rate_required")
    unit_rate = _finite_rate(raw_rate)
    expected_tier = derive_risk_tier(unit_rate)
    provided_tier = _first(value, "riskTier", "risk_tier", "tier")
    if provided_tier is not None and str(provided_tier).strip() != expected_tier:
        raise AdmissionFactError("risk_tier_mismatch")

    result: dict[str, Any] = {
        "admissionMode": mode,
        "admissionUnitId": str(unit_id),
        "schoolId": str(school_id),
        "unitAdmissionRate": unit_rate,
        "riskTier": expected_tier,
    }

    if mode == "major":
        result["majorId"] = str(major_id)
    else:
        result["groupCode"] = str(group_code)

    raw_items = _first(value, "majorItems", "major_items")
    if raw_items is None:
        raw_items = []
    if not isinstance(raw_items, (list, tuple)):
        raise AdmissionFactError("major_items_invalid")
    normalized_items: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for item in raw_items:
        if not isinstance(item, Mapping):
            raise AdmissionFactError("major_detail_invalid")
        normalized = _normalize_major_item(item)
        if normalized["majorId"] in seen_ids:
            raise AdmissionFactError("duplicate_major_detail")
        seen_ids.add(normalized["majorId"])
        normalized_items.append(normalized)
    if normalized_items:
        result["majorItems"] = normalized_items
    else:
        result["majorItems"] = []
    return result


def mode_dependent_cache_key(mode: object, unit_id: object) -> str:
    """生成不会在两种招生类型间碰撞的只读缓存键。"""

    canonical_mode = canonical_admission_mode(mode)
    if unit_id is None or not str(unit_id).strip():
        raise AdmissionFactError("admission_unit_id_required")
    return f"{canonical_mode}:{str(unit_id).strip()}"
