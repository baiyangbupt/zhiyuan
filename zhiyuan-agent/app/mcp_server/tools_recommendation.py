"""推荐与比较工具（B4）。

这一层**不重算**比较矩阵——矩阵由 Java 的 `CandidateComparisonService` 算。
在这里再实现一遍就是"同一个规则两处实现"，两边迟早会不一致，而比较的错误
方向是"把不可比的数放在一起比"，错了也看不出来。

这里做的是**守约检查**：Java 返回的矩阵必须满足与 Java 侧同一份口径合同
（`comparable` 的五个字段）。不满足就降级为 unavailable，而不是把数字透给模型。
"""
from __future__ import annotations

from typing import Any

# 口径身份：五个字段全等才算同口径。与 Java `CandidateComparisonService.SCOPE_FIELDS` 一一对应。
SCOPE_KEYS = ("admissionYear", "areaId", "batch", "admissionMode", "rateUnit")

# 需要口径一致才有意义的维度。名称类维度（城市/校名）不受口径影响。
NUMERIC_DIMENSIONS = frozenset(
    {"admissionRatio", "schoolEnrollRatio", "finalScore", "planNum", "tuitionPerYear"}
)

# 允许比较的维度白名单。不在表里的一律拒绝，避免任意字段被搬上比较面。
ALLOWED_DIMENSIONS = frozenset(NUMERIC_DIMENSIONS | {"cityName", "schoolName", "majorName"})

MIN_ENTITIES = 2
MAX_ENTITIES = 5


def comparable(left: dict[str, Any], right: dict[str, Any]) -> bool:
    """两个招生单元是否同口径。

    **缺失算不可比**——"不知道口径是否相同"不等于"相同"。把缺失当相同，
    正是把 2024 的分数和 2026 的分数放在一起减的那种错。
    """
    if not isinstance(left, dict) or not isinstance(right, dict):
        return False
    return all(
        left.get(key) is not None and left.get(key) == right.get(key) for key in SCOPE_KEYS
    )


def comparison_problems(payload: dict[str, Any]) -> list[str]:
    """检查 Java 返回的矩阵有没有违反口径合同。返回问题清单，空表示没问题。

    检查的是**"不可比的口径下有没有出现数字"**，而不是数值对不对——
    后者是 Java 的事，前者是合同的底线。
    """
    problems: list[str] = []
    if not isinstance(payload, dict):
        return ["comparison_payload_invalid"]
    entities = payload.get("entities") or []
    if not isinstance(entities, list) or not (MIN_ENTITIES <= len(entities) <= MAX_ENTITIES):
        problems.append("comparison_entity_count_invalid")

    dimensions = payload.get("dimensions") or []
    for dimension in dimensions:
        if dimension not in ALLOWED_DIMENSIONS:
            problems.append(f"comparison_dimension_unsupported:{dimension}")

    scope_ok = _all_same_scope(entities)
    for cell in payload.get("cells") or []:
        if not isinstance(cell, dict):
            problems.append("comparison_cell_invalid")
            continue
        if cell.get("dimension") not in NUMERIC_DIMENSIONS:
            continue
        if cell.get("value") is None:
            # 缺失必须有原因：留空的格子读者无法判断是"没有数据"还是"忘了填"。
            if not cell.get("unavailableReason"):
                problems.append(f"comparison_missing_reason:{cell.get('dimension')}")
            continue
        if not scope_ok:
            problems.append(f"comparison_incomparable_value:{cell.get('dimension')}")
        if not cell.get("source"):
            problems.append(f"comparison_cell_without_source:{cell.get('dimension')}")
    return problems


def _all_same_scope(entities: list) -> bool:
    if not isinstance(entities, list) or len(entities) < 2:
        return False
    first = entities[0]
    return all(comparable(first, other) for other in entities[1:])


def unavailable_dimensions(payload: dict[str, Any]) -> list[str]:
    """整列不可比的维度。用于在 UI 上把这一列标灰，而不是逐格解释。"""
    value = payload.get("unavailableDimensions") if isinstance(payload, dict) else None
    return list(value) if isinstance(value, list) else []
