"""Batch A1：完整意图草稿与待确认变更集。

这不是第二套业务真值：`IntentDraft` 只记录“用户这轮说了什么”，
`ChangeSet` 只记录“服务端准备怎么排”，二者都不写有效约束/方案。
当前只做契约与归一化，不接模型/网关；后续 A3/B 再接入。

原则：
- 一次解析全部要求；不因为一轮只能有一个 pending 就丢掉同一句话里的硬要求。
- 当前动作契约不支持复合执行时，明确返回 `needs_constraints_first` /
  `needs_clarification` / `blocked`，不先执行可能违反其他要求的子动作。
- 未确认的草稿不成为有效业务约束。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.gateway.rule_fields import ProposalRuleDomain, ProposalRuleKey


class _DraftModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=lambda name: "".join(
            word.capitalize() if index else word
            for index, word in enumerate(name.split("_"))
        ),
        populate_by_name=True,
        extra="forbid",
    )


class IntentTarget(_DraftModel):
    school_name: str | None = Field(default=None, max_length=80)
    major_name: str | None = Field(default=None, max_length=120)
    volunteer_id: str | None = Field(default=None, max_length=128)

    @model_validator(mode="after")
    def _require_identifier(self):
        # 只读查询可以只点学校名（“湖南大学录取分多少”），不必编造专业；
        # 写动作的“院校+专业/volunteerId”完整性在 ChangeSet 层校验。
        if not ((self.school_name or "").strip()
                or (self.major_name or "").strip()
                or (self.volunteer_id or "").strip()):
            raise ValueError("intent target requires a school, major, or volunteerId")
        return self


class IntentScope(_DraftModel):
    scope_type: Literal["region", "major", "tuition", "school_level", "other"]
    name: str | None = Field(default=None, max_length=120)
    values: list[str] = Field(default_factory=list, max_length=50)
    strength: Literal["only", "prefer", "exclude", "must"] | None = None
    raw_text: str | None = Field(default=None, max_length=300)


class DraftRequirement(_DraftModel):
    """与 Java `RequirementDTO` 同形的完整要求（随草稿/操作保存）。"""

    kind: Literal["include", "exclude", "only_keep"]
    domain: ProposalRuleDomain
    key: ProposalRuleKey
    values: list[str] = Field(default_factory=list, max_length=50)
    min_count: int | None = Field(default=None, ge=1)
    raw_text: str | None = Field(default=None, max_length=300)


class DraftPriorityRule(_DraftModel):
    """与 Java `PriorityRuleDTO` 同形的同档前置规则。"""

    domain: ProposalRuleDomain
    key: ProposalRuleKey
    values: list[str] = Field(default_factory=list, max_length=50)
    ordering_target: Literal["rank_before"] = "rank_before"
    scope: Literal["within_tier"] = "within_tier"
    raw_text: str | None = Field(default=None, max_length=300)


class IntentDraft(_DraftModel):
    source_turn_id: str = Field(min_length=1, max_length=128)
    user_text: str = Field(default="", max_length=2000)
    goal_family: Literal[
        "discover", "query", "preference", "candidate",
        "plan_mutation", "review", "interpret", "meta",
    ]
    action: str = Field(min_length=1, max_length=64)
    # 同一句话里同时出现的其他结构变更（如“加入并删掉 A”）；没有就空。
    additional_mutations: list[MutationKind] = Field(default_factory=list, max_length=10)
    targets: list[IntentTarget] = Field(default_factory=list, max_length=30)
    scopes: list[IntentScope] = Field(default_factory=list, max_length=30)
    count: int | None = Field(default=None, ge=1)
    requirements: list[DraftRequirement] = Field(default_factory=list, max_length=30)
    priority_rules: list[DraftPriorityRule] = Field(default_factory=list, max_length=10)
    risk_posture: Literal["steady", "balanced", "aggressive"] | None = None
    validity: Literal["this_adjustment", "session_future", "unknown"] = "unknown"
    unresolved: list[str] = Field(default_factory=list, max_length=30)
    intent_confidence: float = Field(default=0.0, ge=0.0, le=1.0)


MutationKind = Literal[
    "add", "remove", "replace", "move", "fill", "reorder", "generate",
]


class ChangeOperation(_DraftModel):
    kind: Literal[
        "constrain", "add", "remove", "replace", "move", "fill", "reorder", "generate",
    ]
    targets: list[IntentTarget] = Field(default_factory=list, max_length=30)
    scopes: list[IntentScope] = Field(default_factory=list, max_length=30)
    count: int | None = Field(default=None, ge=1)
    # 完整要求随操作走：后续步骤只凭一个 operation 也能还原覆盖/优先条件。
    requirements: list[DraftRequirement] = Field(default_factory=list, max_length=30)
    priority_rules: list[DraftPriorityRule] = Field(default_factory=list, max_length=10)
    note: str | None = Field(default=None, max_length=300)


class ChangeSet(_DraftModel):
    status: Literal[
        "ready", "needs_constraints_first", "needs_clarification", "needs_negotiation", "blocked",
    ]
    operations: list[ChangeOperation] = Field(default_factory=list, max_length=30)
    unresolved: list[str] = Field(default_factory=list, max_length=30)
    reason: str | None = Field(default=None, max_length=500)
    atomic: bool = False
    # J1：最终 operations 里属于 planned 的 kind；模型可见，用于“尚未支持”提示。
    unsupported_actions: list[str] = Field(default_factory=list, max_length=30)


_ACTION_ALIASES = {
    "add_units": "add",
    "fill_to_count": "fill",
    # 模型会把“出一版方案/生成方案”写成 generate_plan；它是首版补齐的
    # 用户语义，不是尚未支持的整案重排（reorder/generate 才是 planned）。
    "generate_plan": "fill",
    "only_keep_scope": "constrain",
    "exclude_scope": "constrain",
    "tuition_budget_scope": "constrain",
    "must_include_scope": "constrain",
    # 同档优先（priorityRules）是已实现能力，不能归一成 planned 的 reorder。
    "prioritize_within_tier": "prioritize",
    "add_units_by_scope": "add_by_scope",
    # J4a：替换走 add_units + addPolicy=replace（等量替换、总数不变）。
    "replace_units": "replace",
    # J4b：精确移除 / 单条（单组）移动。
    "remove_units": "remove",
    "move_units": "move",
}

# planned 动作：归一化名与原样名都要拦；reorder/generate 是 ChangeOperation 的 kind。
# J4a 起 replace 由 add_units(addPolicy=replace) 承接；J4b 起 remove/move 已实现。
_PLANNED_ACTIONS = {
    "reorder", "generate", "regenerate",
    "undo", "rollback",
}
_PLANNED_KINDS = {"reorder", "generate"}

_CONSTRAINT_ACTION_HINTS = (
    "over_budget",
    "tuition_cap",
    "tuition_budget",
    "tuition_limit",
)


def normalize_action(action: str) -> str:
    """把模型自由命名的动作归一到 ChangeSet 认识的动作族。

    模型自然不会只输出契约里的枚举名（实测：`set_tuition_cap_and_preview`、
    `replace_over_budget_keep_total`）。这些名字描述的是**同一个受支持动作**
    （学费约束 → `apply_constraint_and_regenerate`），不能因为名字不同就判成
    “未支持”并把整轮提案拒掉。
    """
    value = (action or "").strip()
    lowered = value.lower()
    if lowered in _ACTION_ALIASES:
        return _ACTION_ALIASES[lowered]
    if "add_units_by_scope" in lowered or "add_by_scope" in lowered \
            or "add_in_scope" in lowered:
        return "add_by_scope"
    if "replace_over_budget" in lowered or "over_budget" in lowered:
        return "constrain"
    if any(hint in lowered for hint in _CONSTRAINT_ACTION_HINTS):
        return "constrain"
    if "only_keep" in lowered or "must_include" in lowered or "exclude" in lowered:
        return "constrain"
    if "replace" in lowered:
        return "replace"
    if "priorit" in lowered or "priority" in lowered:
        return "prioritize"
    if "reorder" in lowered or "sort" in lowered:
        return "reorder"
    if "fill" in lowered or "complete" in lowered:
        return "fill"
    if "add" in lowered:
        return "add"
    if "remove" in lowered or "delete" in lowered:
        return "remove"
    return value


def build_change_set(draft: IntentDraft) -> ChangeSet:
    """归一化 + planned 收口：最终 operations 全 planned 才 blocked。

    不能按 additionalMutations 一刀切：纯约束里的 replace/fill/remove 是
    apply_constraint_and_regenerate 的执行机制；也不能让 replace_units/undo/rollback
    走“只读动作”早退变成 ready。
    """
    change_set = _build_change_set_inner(draft)
    planned = sorted({op.kind for op in change_set.operations if op.kind in _PLANNED_KINDS})
    normalized_action = normalize_action(draft.action)
    if not planned and not change_set.operations and normalized_action in _PLANNED_ACTIONS:
        planned = [normalized_action]
    change_set.unsupported_actions = planned
    supported = [op for op in change_set.operations if op.kind not in _PLANNED_KINDS]
    if planned and not supported and change_set.status == "ready":
        change_set.status = "blocked"
        change_set.atomic = False
        change_set.reason = change_set.reason or "该动作尚未支持"
        change_set.unresolved = [*change_set.unresolved, "该动作尚未支持"]
    return change_set


def _scope_restates_targets(scopes: list[IntentScope], targets: list[IntentTarget]) -> bool:
    """模型常把 remove/move 的点目标也写进 scopes（实测：school_level）。

    这些 scope 若只是复述 targets，就不构成“先约束后动作”的复合要求；
    真正的额外约束/覆盖/优先仍保留，继续走分步收口。
    """
    if not scopes:
        return True
    if not targets:
        return False
    target_text = " ".join(
        str(getattr(target, "school_name", "") or "")
        + str(getattr(target, "major_name", "") or "")
        + str(getattr(target, "volunteer_id", "") or "")
        for target in targets
    )
    for scope in scopes:
        values = [scope.name, *(scope.values or [])]
        texts = [str(value).strip() for value in values if str(value or "").strip()]
        if not texts or not any(text in target_text for text in texts):
            return False
    return True


def _build_change_set_inner(draft: IntentDraft) -> ChangeSet:
    """把完整意图草稿归一成一个待确认变更集（不执行、不写状态）。

    当前 add_units 契约不允许同时混 scope/requirements/tuition；因此
    “加入 + 限制”返回 `needs_constraints_first`，先确认约束、再预览加入；
    不是把限制丢掉，也不是先执行加入再补限制。
    """
    action = normalize_action(draft.action)
    if draft.unresolved:
        return ChangeSet(
            status="needs_clarification",
            operations=[],
            unresolved=list(draft.unresolved),
            reason="仍有影响执行的歧义，先澄清再做预览。",
            atomic=False,
        )

    if action == "add_by_scope":
        # 范围/学费是**本次新增的筛选条件**，不是全局约束；服务端
        # add_units_by_scope 会把它们解析成明确的待加入条目，再走确认链。
        # 模型常把主动作本身也写进 additionalMutations（["add"]）：不是额外变更。
        extras = [kind for kind in draft.additional_mutations if kind != "add"]
        if extras:
            return ChangeSet(
                status="needs_negotiation",
                operations=[],
                unresolved=["按范围加入不能同时附带其他结构变更，请拆步确认"],
                reason="add_by_scope 是单一原子动作，不接受附加结构变更。",
                atomic=False,
            )
        if draft.count is None or draft.count <= 0:
            return ChangeSet(
                status="needs_clarification",
                operations=[],
                unresolved=["按范围加入缺少明确的新增数量"],
                reason="需要先明确本次要新增几条。",
                atomic=False,
            )
        return ChangeSet(
            status="ready",
            operations=[
                ChangeOperation(
                    kind="add",
                    targets=draft.targets,
                    scopes=draft.scopes,
                    count=draft.count,
                    requirements=draft.requirements,
                    priority_rules=draft.priority_rules,
                    note="按范围加入：筛选条件只作用于本次新增，由服务端解析条目。",
                )
            ],
            unresolved=_unresolved_extras(draft),
            reason=None,
            atomic=True,
        )

    mutation_kinds = {
        "add", "remove", "replace", "move", "fill", "reorder", "generate",
    }
    is_plan_mutation = action in mutation_kinds
    is_constraint_action = action in {"constrain", "prioritize"}
    if is_plan_mutation and any(
            target is not None
            and not (str(target.school_name or "").strip()
                     and str(target.major_name or "").strip())
            and not str(target.volunteer_id or "").strip()
            for target in draft.targets):
        return ChangeSet(
            status="needs_clarification",
            operations=[],
            unresolved=["方案变更目标需要院校+专业或 volunteerId"],
            reason="写动作不能只给学校名，避免把整所学校误当成一个可加入/移除的志愿。",
            atomic=False,
        )
    gate_scopes = draft.scopes
    if action in {"remove", "move"} and _scope_restates_targets(draft.scopes, draft.targets):
        gate_scopes = []
    has_constraints = bool(gate_scopes or draft.requirements or draft.priority_rules)
    has_targets = bool(draft.targets)

    if not is_plan_mutation and not is_constraint_action:
        if draft.additional_mutations:
            return ChangeSet(
                status="blocked",
                operations=[],
                unresolved=["只读动作不允许附加结构变更"],
                reason="intentDraft 是只读动作，却带了 additionalMutations。",
                atomic=False,
            )
        return ChangeSet(
            status="ready",
            operations=[],
            unresolved=[],
            reason="只读/解释动作，不进入方案写变更集。",
            atomic=True,
        )

    # 模型常把主动作本身也写进 additionalMutations（实测：move_units + ["move"]）：
    # 这不是额外变更，不能因此判成复合动作。
    # `generate` 和 `fill` 在首版里是同一个执行机制；模型常把主动作
    # 同时写进 additionalMutations，不能因此判成复合动作。
    primary = action
    structural = ([primary] if is_plan_mutation else []) + [
        kind for kind in draft.additional_mutations
        if kind != primary and not (primary == "fill" and kind == "generate")
    ]
    # 约束动作本来就由 `apply_constraint_and_regenerate` 负责“移出 + 补足”
    # （学费清理/范围筛选都是这样执行的）。`replace/fill/remove` 在这里是执行机制，
    # 不是同一句话里的第二个结构变更；把它们当独立操作会把受支持的原子动作误判成
    # `needs_negotiation`，进而把整轮提案拒掉（2026-10-18 真栈实测）。
    # 只限**没有点名目标**的纯约束：一旦带 targets，就是真正需要拆步的复合动作。
    if (is_constraint_action and not has_targets
            and set(draft.additional_mutations) <= {"replace", "fill", "remove"}):
        structural = []
    if len(structural) > 1:
        return ChangeSet(
            status="needs_negotiation",
            operations=[
                ChangeOperation(
                    kind=kind,
                    targets=draft.targets,
                    scopes=gate_scopes,
                    count=draft.count,
                    requirements=draft.requirements,
                    priority_rules=draft.priority_rules,
                )
                for kind in structural
            ],
            unresolved=_unresolved_extras(draft),
            reason="多个结构变更需要服务端支持复合事务；否则拆步并逐步确认。",
            atomic=False,
        )
    if action == "add" and not has_targets:
        return ChangeSet(
            status="needs_clarification",
            operations=[],
            unresolved=["add 缺少明确目标（院校+专业或 volunteerId）"],
            reason="加入动作缺少具体目标。",
            atomic=False,
        )
    if action == "replace" and not has_targets:
        return ChangeSet(
            status="needs_clarification",
            operations=[],
            unresolved=["replace 缺少明确的换入目标（院校+专业或 volunteerId）"],
            reason="替换动作缺少具体目标。",
            atomic=False,
        )
    if action == "remove" and not has_targets:
        return ChangeSet(
            status="needs_clarification",
            operations=[],
            unresolved=["remove 缺少明确的移除目标（院校+专业或 volunteerId）"],
            reason="移除动作缺少具体目标。",
            atomic=False,
        )
    if action == "move" and not has_targets:
        return ChangeSet(
            status="needs_clarification",
            operations=[],
            unresolved=["move 缺少明确的移动目标（院校+专业或 volunteerId）"],
            reason="移动动作缺少具体目标。",
            atomic=False,
        )

    if has_constraints and structural and not (
            action == "fill" and len(structural) == 1 and structural[0] == "fill"):
        # 除 fill 外的结构动作 + 约束都不是一个原子操作：先约束、再动作。
        # `fill_to_count` 是例外：它的 requirements/scopes 是“这次补齐选什么”的
        # 选入条件，`proposalRequest` 会原样交给 Java 的 user-goal prepare 编译；
        # 实测 prepare 能同一次生成 ready 卡（2026-10-21 会话 10042002）。
        # 若仍在这里拆成 constrain + fill，网关会丢掉同轮 proposalRequest，
        # 用户只会看到正文说“有卡”而实际没有卡。
        operations = [
            ChangeOperation(
                kind="constrain",
                scopes=gate_scopes,
                requirements=draft.requirements,
                priority_rules=draft.priority_rules,
                note="先确认约束/覆盖/优先条件，再执行结构动作。",
            )
        ]
        for kind in structural:
            operations.append(
                ChangeOperation(
                    kind=kind,
                    targets=draft.targets,
                    scopes=gate_scopes,
                    count=draft.count,
                    requirements=draft.requirements,
                    priority_rules=draft.priority_rules,
                    note="仅约束确认后执行；不得先动结构再补约束。",
                )
            )
        return ChangeSet(
            status="needs_constraints_first",
            operations=operations,
            unresolved=_unresolved_extras(draft),
            reason="结构动作与约束/覆盖/优先条件同时出现；当前不是一个原子事务，先约束后动作。",
            atomic=False,
        )

    if not structural:
        operations = [
            ChangeOperation(
                kind="constrain",
                scopes=gate_scopes,
                requirements=draft.requirements,
                priority_rules=draft.priority_rules,
            )
        ]
    else:
        operations = [
            ChangeOperation(
                kind=structural[0],
                targets=draft.targets,
                scopes=gate_scopes,
                count=draft.count,
                requirements=draft.requirements,
                priority_rules=draft.priority_rules,
            )
        ]
    return ChangeSet(
        status="ready",
        operations=operations,
        unresolved=_unresolved_extras(draft),
        reason=None,
        atomic=True,
    )


def _unresolved_extras(draft: IntentDraft) -> list[str]:
    extras: list[str] = []
    if draft.risk_posture is not None:
        extras.append("risk_posture 尚未接入生成器（J6），本次不得宣称已生效")
    if draft.validity == "unknown":
        extras.append("有效期未确认：需说明本次调整还是本会话后续规划")
    return extras
