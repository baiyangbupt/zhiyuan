#!/usr/bin/env python3
"""Offline Release 4.1 PlanChangeSpec reference contract.

This module is intentionally not imported by the production Agent. It tracks
the evolving 4.1 schema, cross-field invariants and canonical reference output
without becoming a second runtime implementation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator


SCHEMA_VERSION = "4.1.0-m2"
TIER_ORDER = ("sprint", "stable", "protect")

NonNegativeInt = Annotated[int, Field(ge=0)]
PositiveInt = Annotated[int, Field(gt=0)]
ProbabilityPoint = Annotated[int, Field(ge=0, le=100)]


class ContractError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _normalized_values(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in result:
            result.append(text)
    if not result:
        raise ValueError("values must contain at least one non-empty item")
    return result


class PlanSelectionGoal(StrictModel):
    type: Literal["fill_to_count"]
    target_count: PositiveInt


class PlanHardRequirement(StrictModel):
    kind: Literal["exclude", "only_keep", "include"]
    domain: Literal["school", "region", "major", "admission"]
    key: str = Field(min_length=1)
    values: list[str] = Field(min_length=1)
    min_count: NonNegativeInt | None = None
    raw_text: str | None = None

    _normalize_values = field_validator("values")(_normalized_values)

    @model_validator(mode="after")
    def validate_min_count(self) -> "PlanHardRequirement":
        if self.kind != "include" and self.min_count is not None:
            raise ValueError("min_count is only valid for include requirements")
        return self


class TierCountBound(StrictModel):
    min_count: NonNegativeInt | None = None
    max_count: NonNegativeInt | None = None

    @model_validator(mode="after")
    def validate_bound(self) -> "TierCountBound":
        if self.min_count is None and self.max_count is None:
            raise ValueError("at least one count bound is required")
        if (
            self.min_count is not None
            and self.max_count is not None
            and self.min_count > self.max_count
        ):
            raise ValueError("min_count must not exceed max_count")
        return self


class ExactTierQuotaGoal(StrictModel):
    type: Literal["exact_counts"]
    update_mode: Literal["replace"] | None = None
    sprint_count: NonNegativeInt
    stable_count: NonNegativeInt
    protect_count: NonNegativeInt


class RangeTierQuotaGoal(StrictModel):
    type: Literal["count_ranges"]
    update_mode: Literal["patch", "replace"]
    sprint: TierCountBound | None = None
    stable: TierCountBound | None = None
    protect: TierCountBound | None = None

    @model_validator(mode="after")
    def validate_any_bound(self) -> "RangeTierQuotaGoal":
        if self.sprint is None and self.stable is None and self.protect is None:
            raise ValueError("count_ranges requires at least one tier bound")
        return self


class RatioTierQuotaGoal(StrictModel):
    type: Literal["ratios"]
    update_mode: Literal["replace"]
    sprint_weight: NonNegativeInt
    stable_weight: NonNegativeInt
    protect_weight: NonNegativeInt

    @model_validator(mode="after")
    def validate_positive_total(self) -> "RatioTierQuotaGoal":
        if self.sprint_weight + self.stable_weight + self.protect_weight <= 0:
            raise ValueError("ratio weights must have a positive total")
        return self


PlanTierQuotaGoal = Annotated[
    ExactTierQuotaGoal | RangeTierQuotaGoal | RatioTierQuotaGoal,
    Field(discriminator="type"),
]


class ContextExactTierQuotaGoal(StrictModel):
    type: Literal["exact_counts"]
    sprint_count: NonNegativeInt
    stable_count: NonNegativeInt
    protect_count: NonNegativeInt


class ContextRangeTierQuotaGoal(StrictModel):
    type: Literal["count_ranges"]
    sprint: TierCountBound | None = None
    stable: TierCountBound | None = None
    protect: TierCountBound | None = None

    @model_validator(mode="after")
    def validate_any_bound(self) -> "ContextRangeTierQuotaGoal":
        if self.sprint is None and self.stable is None and self.protect is None:
            raise ValueError("count_ranges requires at least one tier bound")
        return self


class ContextRatioTierQuotaGoal(StrictModel):
    type: Literal["ratios"]
    sprint_weight: NonNegativeInt
    stable_weight: NonNegativeInt
    protect_weight: NonNegativeInt

    @model_validator(mode="after")
    def validate_positive_total(self) -> "ContextRatioTierQuotaGoal":
        if self.sprint_weight + self.stable_weight + self.protect_weight <= 0:
            raise ValueError("ratio weights must have a positive total")
        return self


ContextTierQuotaGoal = Annotated[
    ContextExactTierQuotaGoal | ContextRangeTierQuotaGoal | ContextRatioTierQuotaGoal,
    Field(discriminator="type"),
]


class TierGoalContext(StrictModel):
    tier_quota_goal: ContextTierQuotaGoal


class SelectorLeaf(StrictModel):
    kind: Literal["exclude", "only_keep", "include"]
    domain: Literal["school", "region", "major", "admission"]
    key: str = Field(min_length=1)
    values: list[str] = Field(min_length=1)

    _normalize_values = field_validator("values")(_normalized_values)


class SelectorAnyOf(StrictModel):
    operator: Literal["any_of"]
    children: list[SelectorLeaf] = Field(min_length=1)


class SelectorExpression(StrictModel):
    operator: Literal["all_of"]
    children: list[SelectorLeaf | SelectorAnyOf] = Field(min_length=1)

    def leaf_count(self) -> int:
        return sum(
            1 if isinstance(child, SelectorLeaf) else len(child.children)
            for child in self.children
        )

    @model_validator(mode="after")
    def validate_complexity(self) -> "SelectorExpression":
        if self.leaf_count() > 16:
            raise ValueError("selector expression supports at most 16 leaves")
        return self


class PlanPriorityRule(StrictModel):
    domain: Literal["school", "region", "major"]
    key: str = Field(min_length=1)
    values: list[str] = Field(min_length=1)
    ordering_target: Literal["rank_before"] = "rank_before"
    scope: Literal["within_tier"] = "within_tier"
    raw_text: str | None = None

    _normalize_values = field_validator("values")(_normalized_values)


class ProbabilityGapGoal(StrictModel):
    type: Literal["probability_gap"]
    scope: Literal["global", "within_tier"]
    max_adjacent_gap_points: PositiveInt = Field(le=100)


class SafetyFloorGoal(StrictModel):
    type: Literal["safety_floor"]
    min_admission_probability: ProbabilityPoint
    min_count: PositiveInt


PlanRiskStructureGoal = Annotated[
    ProbabilityGapGoal | SafetyFloorGoal,
    Field(discriminator="type"),
]


class PlanRepairGoal(StrictModel):
    objective: Literal["increase_stability"] | None = None
    review_issue_code: str | None = None
    strategy: str | None = None

    @model_validator(mode="after")
    def validate_selection_or_exact_pair(self) -> "PlanRepairGoal":
        exact_pair = bool(self.review_issue_code and self.strategy)
        partial_pair = bool(self.review_issue_code) != bool(self.strategy)
        if partial_pair:
            raise ValueError("review_issue_code and strategy must be provided together")
        if not exact_pair and self.objective != "increase_stability":
            raise ValueError("repair_goal requires an exact pair or increase_stability selection")
        return self


class PlanChangeSpec410(StrictModel):
    selection_goal: PlanSelectionGoal | None = None
    tier_quota_goal: PlanTierQuotaGoal | None = None
    requirements: list[PlanHardRequirement] | None = None
    selector_expression: SelectorExpression | None = None
    priority_rules: list[PlanPriorityRule] | None = None
    risk_structure_goal: PlanRiskStructureGoal | None = None
    repair_goal: PlanRepairGoal | None = None

    @model_validator(mode="after")
    def validate_top_level(self) -> "PlanChangeSpec410":
        if not any(
            (
                self.selection_goal,
                self.tier_quota_goal,
                self.requirements,
                self.selector_expression,
                self.priority_rules,
                self.risk_structure_goal,
                self.repair_goal,
            )
        ):
            raise ValueError("PlanChangeSpec requires at least one objective")
        if self.requirements is not None and not self.requirements:
            raise ValueError("requirements must be omitted or non-empty")
        if self.priority_rules is not None:
            if not self.priority_rules:
                raise ValueError("priority_rules must be omitted or non-empty")
            if len(self.priority_rules) > 4:
                raise ValueError("priority_rules supports at most four rules")
        return self


def _resolved_target_count(spec: PlanChangeSpec410, context_target_count: int | None) -> int | None:
    if spec.selection_goal is not None:
        return spec.selection_goal.target_count
    if context_target_count is not None and context_target_count > 0:
        return context_target_count
    return None


def _resolve_tier_goal(
    goal: PlanTierQuotaGoal | None,
    target_count: int | None,
    context_tier_goal: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if goal is None:
        return None
    if target_count is None or target_count <= 0:
        raise ContractError("tier_target_count_required", "tier allocation requires a target count")
    if isinstance(goal, ExactTierQuotaGoal):
        counts = {
            "sprint": goal.sprint_count,
            "stable": goal.stable_count,
            "protect": goal.protect_count,
        }
        if sum(counts.values()) != target_count:
            raise ContractError(
                "tier_exact_total_mismatch",
                f"exact tier total {sum(counts.values())} does not equal {target_count}",
            )
        return {"type": goal.type, "counts": counts}
    if isinstance(goal, RangeTierQuotaGoal):
        request_bounds = {
            tier: source.model_dump(mode="json", exclude_none=True)
            for tier in TIER_ORDER
            if (source := getattr(goal, tier)) is not None
        }
        if goal.update_mode == "patch" and context_tier_goal is None:
            return {
                "type": goal.type,
                "update_mode": goal.update_mode,
                "request_bounds": request_bounds,
                "resolved": False,
            }
        if goal.update_mode == "patch":
            try:
                context = TierGoalContext.model_validate(
                    {"tier_quota_goal": context_tier_goal}
                ).tier_quota_goal
            except ValidationError as exc:
                raise ContractError("tier_context_validation_failed", str(exc)) from exc
            if not isinstance(context, ContextRangeTierQuotaGoal):
                raise ContractError(
                    "tier_patch_type_mismatch",
                    "count_ranges patch requires historical count_ranges goal",
                )
            effective_goal = context.model_dump(mode="json", exclude_none=True)
            for tier, requested in request_bounds.items():
                effective_goal[tier] = {**effective_goal.get(tier, {}), **requested}
        else:
            effective_goal = {
                "type": goal.type,
                **request_bounds,
            }
        bounds: dict[str, dict[str, int]] = {}
        for tier in TIER_ORDER:
            source = effective_goal.get(tier) or {}
            bounds[tier] = {
                "min_count": source.get("min_count", 0),
                "max_count": source.get("max_count", target_count),
            }
        if sum(item["min_count"] for item in bounds.values()) > target_count:
            raise ContractError("tier_range_min_infeasible", "tier minimums exceed target count")
        if sum(item["max_count"] for item in bounds.values()) < target_count:
            raise ContractError("tier_range_max_infeasible", "tier maximums cannot reach target count")
        return {
            "type": goal.type,
            "update_mode": goal.update_mode,
            "request_bounds": request_bounds,
            "effective_goal": effective_goal,
            "bounds": bounds,
            "resolved": True,
        }

    submitted_weights = {
        "sprint": goal.sprint_weight,
        "stable": goal.stable_weight,
        "protect": goal.protect_weight,
    }
    divisor = math.gcd(
        math.gcd(submitted_weights["sprint"], submitted_weights["stable"]),
        submitted_weights["protect"],
    )
    weights = {tier: weight // divisor for tier, weight in submitted_weights.items()}
    total_weight = sum(weights.values())
    counts = {tier: target_count * weights[tier] // total_weight for tier in TIER_ORDER}
    remainders = {tier: target_count * weights[tier] % total_weight for tier in TIER_ORDER}
    remaining = target_count - sum(counts.values())
    tie_order = {tier: index for index, tier in enumerate(TIER_ORDER)}
    for tier in sorted(TIER_ORDER, key=lambda item: (-remainders[item], tie_order[item]))[:remaining]:
        counts[tier] += 1
    return {
        "type": goal.type,
        "submitted_weights": submitted_weights,
        "weights": weights,
        "counts": counts,
        "resolution": "largest_remainder",
        "tie_break_order": list(TIER_ORDER),
    }


def compile_reference(
    raw_spec: dict[str, Any],
    *,
    context_target_count: int | None = None,
    context_tier_goal: dict[str, Any] | None = None,
) -> dict[str, Any]:
    try:
        spec = PlanChangeSpec410.model_validate(raw_spec)
    except ValidationError as exc:
        raise ContractError("schema_validation_failed", str(exc)) from exc

    target_count = _resolved_target_count(spec, context_target_count)
    tier_result = _resolve_tier_goal(
        spec.tier_quota_goal,
        target_count,
        context_tier_goal=context_tier_goal,
    )
    normalized_spec = spec.model_dump(mode="json", exclude_none=True)
    objective_types = [key for key, value in normalized_spec.items() if value not in (None, [], {})]
    selector_leaf_count = spec.selector_expression.leaf_count() if spec.selector_expression else 0
    result: dict[str, Any] = {
        "plan_change_spec_version": SCHEMA_VERSION,
        "normalized_spec": normalized_spec,
        "summary": {
            "target_count": target_count,
            "objective_types": objective_types,
            "selector_leaf_count": selector_leaf_count,
            "priority_rule_count": len(spec.priority_rules or []),
            "tier_result": tier_result,
        },
    }
    encoded = json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    result["canonical_digest"] = hashlib.sha256(encoded).hexdigest()
    return result


def run_golden(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    failures: list[dict[str, Any]] = []
    passed = 0
    for case in payload.get("cases", []):
        name = str(case.get("name") or "unnamed")
        expected_valid = bool(case.get("valid"))
        try:
            compiled = compile_reference(
                case.get("spec") or {},
                context_target_count=case.get("contextTargetCount"),
                context_tier_goal=case.get("contextTierGoal"),
            )
            if not expected_valid:
                failures.append({"name": name, "reason": "expected_invalid_but_compiled"})
                continue
            expected_summary = case.get("expectedSummary") or {}
            actual_summary = compiled["summary"]
            mismatches = {
                key: {"expected": value, "actual": actual_summary.get(key)}
                for key, value in expected_summary.items()
                if actual_summary.get(key) != value
            }
            if mismatches:
                failures.append({"name": name, "reason": "summary_mismatch", "mismatches": mismatches})
                continue
            passed += 1
        except ContractError as exc:
            if expected_valid:
                failures.append({"name": name, "reason": "unexpected_contract_error", "code": exc.code})
                continue
            if exc.code != case.get("expectedError"):
                failures.append(
                    {
                        "name": name,
                        "reason": "error_code_mismatch",
                        "expected": case.get("expectedError"),
                        "actual": exc.code,
                    }
                )
                continue
            passed += 1
    return {
        "schemaVersion": payload.get("schemaVersion"),
        "total": len(payload.get("cases", [])),
        "passed": passed,
        "failures": failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--golden",
        type=Path,
        default=Path(__file__).with_name("plan_change_spec_410_golden.json"),
    )
    args = parser.parse_args()
    result = run_golden(args.golden)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not result["failures"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
