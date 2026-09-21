"""把 admission.* 的原始返回**分型**成互不混用的结果。

六种数据混在一起是这一层要解决的问题。它们混用的后果不是"显示得不好看"，
而是把一种数据当成另一种来回答：拿历年最低分当录取概率、拿学校口径的概率
当专业组的、拿"缺少条件"当"不符合条件"。三者都会让学生按错误信息填报。

外层统一是 `{schemaVersion, kind, status, data, evidenceRefs, limitations, nextCursor}`，
但**外层统一不等于内容可以混**：`data` 的形状由 `kind` 决定。
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

SCHEMA_VERSION = 1

# status 取值是封闭集合：调用方据它决定降级路径，不能出现"其他"。
STATUS_OK = "ok"
STATUS_EMPTY = "empty"
STATUS_INSUFFICIENT = "insufficient_data"
STATUS_UNSUPPORTED = "unsupported"
STATUS_UPSTREAM_ERROR = "upstream_error"

KIND_HISTORY = "history"
KIND_PROBABILITY = "probability"
KIND_ELIGIBILITY = "eligibility"
KIND_ENROLLMENT = "enrollment"
KIND_POLICY = "policy"
KIND_WORKING_PLAN = "workingPlan"


def envelope(
    kind: str,
    status: str,
    data: Any,
    *,
    evidence_refs: list | None = None,
    limitations: list[str] | None = None,
    next_cursor: str | None = None,
    code: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "kind": kind,
        "status": status,
        "data": data,
        "evidenceRefs": list(evidence_refs or []),
        "limitations": list(limitations or []),
        "nextCursor": next_cursor,
    }
    if code is not None:
        # code 只在非 ok 时出现，且必须是稳定的机器可读值：
        # 调用方靠它选降级路径，靠 message 只能靠正则。
        payload["code"] = code
    return payload


def percentage(raw: Any, unit: str | None) -> Decimal:
    """把上游给的录取率转成百分数。

    **单位必须显式配置。** 用"值 ≤1 就当小数"去猜，会在真实值是 0.5 分
    （或 1%）时把结论放大一百倍——而录取率放大一百倍是"稳上"，一个足以
    改变填报决定的方向性错误。
    """
    if not unit:
        raise ValueError("probability_unit_missing")
    if isinstance(raw, str):
        raw = raw.strip().rstrip("%")
    try:
        value = Decimal(str(raw))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("invalid_probability") from exc
    if unit == "fraction":
        value *= 100
    elif unit != "percent":
        raise ValueError("unknown_probability_unit")
    if not value.is_finite() or value < 0 or value > 99:
        # 业务 DTO 与风控定的区间是 0–99。上游若真的会返回 100，
        # 那要连着业务口径一起改，不能在这里静默截断成 99。
        raise ValueError("probability_out_of_contract")
    return value


def normalize_history(raw: Any, query: dict[str, Any]) -> dict[str, Any]:
    """历年录取分数线。**没有概率，也不需要概率。**

    历史事实与个体录取率是两种东西：前者是"去年这个专业录到多少位次"，
    后者是"你这个位次今年有多大概率被录"。把前者当后者用，是在用过去
    回答未来，而且还答错了对象。
    """
    rows = _rows(raw)
    if not rows:
        return envelope(KIND_HISTORY, STATUS_EMPTY, [], limitations=["history_no_data"])

    normalized: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        entry = {
            "admissionYear": _int(row.get("year") or row.get("admissionYear")),
            "minScore": _number(row.get("minScore") or row.get("min_score")),
            "minPos": _number(row.get("minPos") or row.get("minPosition") or row.get("min_pos")),
            "maxScore": _number(row.get("maxScore") or row.get("max_score")),
            "enrollNum": _int(row.get("enrollNum") or row.get("enroll_num")),
            "subjectType": _text(row.get("subjectType") or row.get("subject_type")),
            "areaId": _text(row.get("areaId") or row.get("area_id")) or _text(query.get("areaId")),
            "batch": _text(row.get("batch")),
            "schoolId": _text(row.get("schoolId") or row.get("school_id")) or _text(query.get("schoolId")),
            "majorId": _text(row.get("majorId") or row.get("major_id")) or _text(query.get("majorId")),
        }
        # 招生单元身份只能来自上游或已解析的查询口径，不能从名称或数组序号猜造。
        normalized.append({key: value for key, value in entry.items() if value is not None})

    limitations: list[str] = []
    if any(row.get("year") in (None, "", 0) for row in rows if isinstance(row, dict)):
        limitations.append("history_year_missing")
    return envelope(KIND_HISTORY, STATUS_OK, normalized, limitations=limitations)


def normalize_probability(raw: Any, query: dict[str, Any], rate_unit: str | None) -> dict[str, Any]:
    """上游已算好的录取概率。

    **不自算、不用历年最低分伪造、不补默认零。** 缺真实接口时这项能力显示不可用，
    而不是"用别的东西凑一个看起来像概率的数"。
    """
    rows = _rows(raw)
    if not rows:
        return envelope(KIND_PROBABILITY, STATUS_EMPTY, [], limitations=["probability_no_data"])

    normalized: list[dict[str, Any]] = []
    limitations: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        unit_id = _text(row.get("admissionUnitId") or row.get("admission_unit_id"))
        group_code = _text(row.get("groupCode") or row.get("group_code"))
        raw_rate = row.get("unitAdmissionRate")
        if raw_rate is None:
            raw_rate = row.get("unit_admission_rate")
        if raw_rate is None:
            # 缺单位概率是"不足"，不是"零"。
            limitations.append("unit_admission_rate_missing")
            continue
        try:
            rate = percentage(raw_rate, rate_unit)
        except ValueError as exc:
            limitations.append(str(exc))
            continue
        normalized.append(
            {
                "admissionUnitId": unit_id,
                "groupCode": group_code,
                "schoolId": _text(row.get("schoolId") or row.get("school_id")) or _text(query.get("schoolId")),
                "majorId": _text(row.get("majorId") or row.get("major_id")),
                "unitAdmissionRate": float(rate),
                "rateUnit": "percent",
                "riskTier": _text(row.get("riskTier") or row.get("risk_tier")),
            }
        )

    if not normalized:
        return envelope(
            KIND_PROBABILITY, STATUS_INSUFFICIENT, [], limitations=limitations or ["probability_unavailable"]
        )
    return envelope(KIND_PROBABILITY, STATUS_OK, normalized, limitations=limitations)


def normalize_eligibility(raw: Any, query: dict[str, Any]) -> dict[str, Any]:
    """资格检查。**缺条件不是 false。**

    "我不确定你符不符合"和"你不符合"是两个结论，处置也相反：前者去补条件，
    后者去换志愿。合成一个布尔值会让系统把"不知道"报成"不行"——学生因此
    白白放弃一个本来能报的志愿。
    """
    if not isinstance(raw, dict):
        return envelope(KIND_ELIGIBILITY, STATUS_UPSTREAM_ERROR, [], code="eligibility_unavailable")
    eligible = raw.get("eligible")
    if eligible is None:
        eligible = raw.get("available")
    if isinstance(eligible, bool):
        verdict = "eligible" if eligible else "ineligible"
    else:
        verdict = "unknown"
    return envelope(
        KIND_ELIGIBILITY,
        STATUS_OK,
        {
            "verdict": verdict,
            # 检查了什么、没检查什么是结论的一部分：只写"符合"，学生无法知道
            # 那是"选科符合"还是"什么都符合"。
            "checkedConstraints": ["subjects"],
            "uncheckedConstraints": ["medical", "policy"],
            "reasons": list(raw.get("reasons") or []),
        },
        limitations=[] if verdict != "unknown" else ["eligibility_unknown"],
    )


def _rows(raw: Any) -> list:
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        for key in ("data", "items", "rows", "records", "admissionFacts"):
            value = raw.get(key)
            if isinstance(value, list):
                return value
        if "data" in raw and isinstance(raw["data"], dict):
            return _rows(raw["data"])
    return []


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
