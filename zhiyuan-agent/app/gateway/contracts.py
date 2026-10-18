from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.admission.facts import AdmissionFactError, canonical_admission_mode, derive_risk_tier
from app.domain.career_slots import CAREER_LABEL_MAP, merge_career_labels, normalize_career_labels
from app.gateway.intent_draft import IntentDraft
from app.gateway.rule_fields import ProposalRuleDomain, ProposalRuleKey


class _ContractModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=lambda name: "".join(
            word.capitalize() if index else word
            for index, word in enumerate(name.split("_"))
        ),
        populate_by_name=True,
        extra="forbid",
    )


class EvidenceRef(_ContractModel):
    evidence_id: str
    source_level: Literal["authoritative", "computed", "planner_experience"]
    data_version: str
    # 台账内部标识。Java 的 `ConversationEvidenceDTO` 一直带这三个字段，但快照
    # 过去是空的（`fillEvidence()` 是空方法体），所以契约里没声明也不炸；2026-09-21
    # 快照开始真的带证据之后，`extra="forbid"` 会让**整个快照**解析失败。
    # 实测表现：每个会话从**第二轮**起秒失败（"当前会话状态暂时不可用"），因为
    # 证据是第一轮跑工具时才落台账的——而错误文本里只有字段名，看不出是契约漏字段。
    source_system: str | None = None
    params_digest: str | None = None
    expires_at: str | None = None
    admission_mode: Literal["major", "major_group"] | None = None
    admission_unit_id: str | None = None
    group_code: str | None = None
    algorithm_version: str | None = None
    state_version: int | None = None
    scope: dict[str, Any] = Field(default_factory=dict)
    observed_at: str | None = None
    limitations: list[str] = Field(default_factory=list)

    @field_validator("admission_mode", mode="before")
    @classmethod
    def _normalize_admission_mode(cls, value: Any) -> Any:
        if value is None:
            return value
        try:
            return canonical_admission_mode(value)
        except AdmissionFactError as exc:
            raise ValueError(exc.code) from exc


class AdmissionMajorDetail(_ContractModel):
    major_id: str
    major_name: str | None = None
    major_code: str | None = None
    major_admission_rate: float

    @field_validator("major_admission_rate")
    @classmethod
    def _validate_rate(cls, value: float) -> float:
        try:
            derive_risk_tier(value)
        except AdmissionFactError as exc:
            raise ValueError(exc.code) from exc
        return value


class AdmissionFact(_ContractModel):
    admission_unit_id: str
    admission_mode: Literal["major", "major_group"]
    school_id: str
    school_name: str | None = None
    major_id: str | None = None
    major_name: str | None = None
    # `group_code`（专业组代码）是**可选**身份：数据源确实不提供这一层
    # （2026-10-09 实测 + 源码复核，见 `_normalize_group_code` 的完整口径）。
    # 这里保留 `str | None`，提供时必须是非空白字符串。
    group_code: str | None = None
    major_items: list[AdmissionMajorDetail] = Field(default_factory=list)
    unit_admission_rate: float
    risk_tier: Literal["冲", "稳", "保"]
    data_version: str | None = None
    algorithm_version: str | None = None
    observed_at: str | None = None
    limitations: list[str] = Field(default_factory=list)

    @field_validator("admission_mode", mode="before")
    @classmethod
    def _normalize_mode(cls, value: Any) -> Any:
        try:
            return canonical_admission_mode(value)
        except AdmissionFactError as exc:
            raise ValueError(exc.code) from exc

    @field_validator("group_code", mode="before")
    @classmethod
    def _normalize_group_code(cls, value: Any) -> Any:
        """专业组代码：**缺就是缺**，不再当"必填"拦下整轮输出（2026-10-09 修）。

        事故形态（会话 10041981 19:51 轮）：`major_group` 下契约强制
        `group_code` 非空，而数据源这一层根本拿不到——候选行
        （`recommendation.preview_candidates`）没有组代码列，Java 侧
        `AdmissionFactDTO.groupCode`/证据台账 `groupCode` 从未被赋值
        （`docs/contracts/admission-identity-and-filters.md` 第六节第 6 条
        就记着它是"悬空字段"）。结果是**每一轮**院校事实输出都先撞一次
        `group_code_required` → 吃一次修复回合（实测 8 条事实全拒，修复耗时
        ~5 分钟，且模型最后索性不再输出事实卡片）。模型面前只剩两条路：
        编一个组代码，或丢掉事实——都比"如实缺"差。

        现在的口径（与 `docs/superpowers/reviews/2026-10-07-…` 队列 14 ① 一致）：
        · 缺（`None`/空白）= **显式未知**，放行；对用户的"以省考试院公布为准"
          由指令侧（`skills/codex/developer_instructions.md`）承担，不在这里编。
        · **提供时仍必须合法**：非字符串由 pydantic 类型层拒绝（含数字/布尔/
          数组）；纯空白 strip 后视为"未提供"（空白不是值），不做插值。
        · 下游绑定不放松：`output_validation` 里事实**带了**组代码时，绑定证据
          仍按逐字相等比对（`fact.group_code is None or reference.group_code ==
          fact.group_code`）——"有则必须准"的路径原样保留。
        """
        if value is None:
            return None
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value

    @field_validator("unit_admission_rate")
    @classmethod
    def _validate_unit_rate(cls, value: float) -> float:
        try:
            derive_risk_tier(value)
        except AdmissionFactError as exc:
            raise ValueError(exc.code) from exc
        return value

    @model_validator(mode="after")
    def _validate_scope_and_tier(self) -> "AdmissionFact":
        if self.admission_mode == "major" and not self.major_id:
            raise ValueError("major_required")
        # `group_code_required` 已删除：数据源不提供专业组代码（见
        # `_normalize_group_code`）。缺代码不再拒整轮，也不静默换别的值。
        try:
            expected = derive_risk_tier(self.unit_admission_rate)
        except AdmissionFactError as exc:
            raise ValueError(exc.code) from exc
        if self.risk_tier != expected:
            raise ValueError("risk_tier_mismatch")
        if self.admission_mode == "major" and len(self.major_items) > 1:
            raise ValueError("major_detail_count_invalid")
        return self


class ArtifactRef(_ContractModel):
    artifact_id: str
    artifact_type: Literal["candidate", "comparison", "plan_draft", "review"]
    state_version: int


class ConversationAction(_ContractModel):
    action_type: Literal[
        "none",
        "request_clarification",
        "continue_readonly",
        "create_proposal",
        "confirm_proposal",
        "cancel_proposal",
        "refresh_proposal",
    ] = "none"
    proposal_ref: str | None = None
    expected_source_version: int | None = None
    intent: Literal["explicit", "inferred", "not_applicable"] = "not_applicable"


class ProposalScope(_ContractModel):
    scope_type: str
    name: str
    normalized_name: str | None = None
    entity_type: str | None = None
    scope_level: str | None = None
    resolution_status: str | None = None
    raw_text: str | None = None


# ── 方案调整规则的白名单（唯一权威 = Java `CoverageRequirementSupport.targetList()`）──
# 2026-10-08 事故：`domain` 曾是自由字符串 ✗ → 模型侧 schema（`_strict_model_schema`
# 直接从 pydantic 模型生成）里没有 enum ✗ → 模型**只能猜**，实测猜了 `location` ✗
# （Java 双重非法：域不在白名单、键也不在）→ prepare 拒单 ✓ → 用户拿到一张
# `status=blocked` 的死卡 ✓（"暂不支持非排他覆盖要求字段：location.…"，没有任何
# 可执行的下一步 ✓）。修在契约上：枚举进 schema（模型**看得见**允许值 ✓）+ 配对校验
# （JSON Schema 表达不了 domain×key 的合取 ✓，pydantic 侧补上 ✓；非法值在
# `TurnOutput.model_validate` 就被拦下 → 走既有的一次修复回合，而不是直通 prepare ✗）。
# `region`/`major`/`school`/`admission` 四域与各自键 = Java 白名单逐字抄录 ✓；
# `admission.tier` 只对 `kind=include` 存在 ✓（`targetListName()` 不含 admission ✗）。
_PRIORITY_RULE_KEYS_BY_DOMAIN: dict[str, tuple[str, ...]] = {
    "region": ("province", "city", "area", "region_group"),
    "major": ("major", "level1", "level2", "level3", "major_tag"),
    "school": (
        "school",
        "schools",
        "school_nature",
        "program_type",
        "school_category",
        "school_level",
        "school_tag",
    ),
    "admission": ("tier",),
}



def _require_supported_rule_field(domain: str, key: str) -> None:
    allowed = _PRIORITY_RULE_KEYS_BY_DOMAIN.get(domain, ())
    if key not in allowed:
        # 报错文本会进修复回合的提示词（`_repair_turn_output` 的 issue ✓），
        # 所以把允许值一起写进去——只说"非法"的话模型还是会再猜一次。
        raise ValueError(
            f"unsupported rule field {domain}.{key}; {domain} supports: "
            + (", ".join(allowed) if allowed else "none")
        )


class ProposalRequirement(_ContractModel):
    # Java `ProjectedHardRequirementSupport.validate()` 只认这三个 kind：
    # 其余值一律"当前只支持 exclude 和 only_keep 复合硬要求"（= 拒单死卡）。
    kind: Literal["include", "exclude", "only_keep"]
    domain: ProposalRuleDomain
    key: ProposalRuleKey
    values: list[str]
    min_count: int = Field(default=1, ge=0)
    raw_text: str | None = None

    @model_validator(mode="after")
    def _validate_domain_key_pair(self) -> "ProposalRequirement":
        _require_supported_rule_field(self.domain, self.key)
        if self.domain == "admission" and self.kind != "include":
            raise ValueError("admission.tier is only supported for kind=include")
        return self


class ProposalPriorityRule(_ContractModel):
    domain: ProposalRuleDomain
    key: ProposalRuleKey
    values: list[str]
    # Java `PriorityRuleSupport.validate()` 只认这两对取值（其余 = 拒单死卡）：
    # 它是把规则映射成 include 覆盖要求后复用同一份 CoverageRequirementSupport 白名单 ✓。
    ordering_target: Literal["rank_before"] = "rank_before"
    scope: Literal["within_tier"] = "within_tier"
    raw_text: str | None = None

    @model_validator(mode="after")
    def _validate_domain_key_pair(self) -> "ProposalPriorityRule":
        _require_supported_rule_field(self.domain, self.key)
        return self


class ProposalTierRange(_ContractModel):
    min_count: int | None = Field(default=None, ge=0)
    max_count: int | None = Field(default=None, ge=0)


class ProposalTierQuota(_ContractModel):
    type: Literal["exact_counts", "count_ranges", "ratios"]
    update_mode: str | None = None
    sprint_count: int | None = Field(default=None, ge=0)
    stable_count: int | None = Field(default=None, ge=0)
    protect_count: int | None = Field(default=None, ge=0)
    sprint: ProposalTierRange | None = None
    stable: ProposalTierRange | None = None
    protect: ProposalTierRange | None = None
    sprint_weight: int | None = Field(default=None, ge=0)
    stable_weight: int | None = Field(default=None, ge=0)
    protect_weight: int | None = Field(default=None, ge=0)


class ProposalContext(_ContractModel):
    min_tuition_per_year: int | None = Field(default=None, ge=0)
    max_tuition_per_year: int | None = Field(default=None, ge=0)


class ExactTarget(_ContractModel):
    """点名加入的精确目标（仅 add_units 使用）。

    names-only / ID-only / both 三种都合法；both 时 Java 必须交叉校验，名称与 ID
    对应的学校/专业不一致 -> target_mismatch，不静默以 ID 为准。
    """

    school_name: str | None = Field(default=None, max_length=80)
    major_name: str | None = Field(default=None, max_length=120)
    volunteer_id: str | None = Field(default=None, max_length=128)

    @model_validator(mode="after")
    def _require_identifier(self) -> "ExactTarget":
        names = bool((self.school_name or "").strip() and (self.major_name or "").strip())
        identifier = bool((self.volunteer_id or "").strip())
        if not names and not identifier:
            raise ValueError("exactTarget requires schoolName+majorName or volunteerId")
        return self


class ProposalRequest(_ContractModel):
    """Model-produced semantic draft accepted by the Java proposal compiler."""

    proposal_source: Literal["user_goal"] = "user_goal"
    goal_type: Literal[
        "only_keep_scope",
        "must_include_scope",
        "exclude_scope",
        "tuition_budget_scope",
        "fill_to_count",
        "prioritize_within_tier",
        "add_units",
        "add_units_by_scope",
        "remove_units",
        "move_units",
    ]
    user_original_text: str = ""
    confidence: Literal["low", "medium", "high"] = "medium"
    source_version_guard: int = Field(ge=0)
    target_count: int | None = Field(
        default=None,
        gt=0,
        description=(
            "fill_to_count 必填且 >0（补齐目标数量）；数字是提案内容，供用户确认或调整。"
        ),
    )
    persist_target_count: bool = Field(
        default=True,
        description=(
            "true=按新总数补齐；false=保持当前方案总数（preserve；仅当已有正式方案时有效）。"
        ),
    )
    # 点名加入（add_units）：精确的学校+专业目标，和 targetScopes/requirements 的
    # 范围 OR 语义分开。模型侧严格 schema 会把它设为 required：非 add_units 也必须
    # 输出空数组 `[]`（description 写进 schema 让模型看得见）。
    add_count: int | None = Field(
        default=None,
        gt=0,
        description=(
            "仅 add_units_by_scope 使用：本次要新增的条数/专业组数（>0）。"
            "与 target_count（补足到某个总数）不是一回事。"
        ),
    )
    exact_targets: list[ExactTarget] = Field(
        default_factory=list,
        max_length=20,
        description=(
            "精确的学校+专业目标列表（最多 20 条）。add_units 必填；"
            "remove_units 用它列要移除的条目；move_units 必须恰好 1 条。"
            "remove/move 的目标只能写这里，**不要写进 targetScopes/requirements**；"
            "其余提案输出 []。"
        ),
    )
    add_policy: Literal["expand", "replace"] = Field(
        default="expand",
        description=(
            "仅 add_units 使用：expand（默认）=纯加入、总数增长；"
            "replace=等量替换、总数不变（预览会列全新增加与移出条目）。"
            "用户明确说“总数不变 / 换掉 / 替换”时才用 replace；其余提案保持 expand。"
        ),
    )
    move_position: Literal["top", "bottom", "before", "after"] | None = Field(
        default=None,
        description=(
            "仅 move_units 使用：移到 top/bottom，或锚点条目的 before/after。"
            "一次只移动一条（专业组模式下按组移动），不增删条目。"
        ),
    )
    move_anchor: ExactTarget | None = Field(
        default=None,
        description=(
            "仅 move_units 且 movePosition=before/after 时使用：锚点条目"
            "（schoolName+majorName 或 volunteerId）。"
        ),
    )
    tier_quota_goal: ProposalTierQuota | None = None
    requirements: list[ProposalRequirement] = Field(default_factory=list)
    # 同档前置"只支持一条"（2026-10-13 实测，会话 10041981）在 **Java 侧**是硬约束
    # （`PriorityRuleSupport.validate()`：`size() > 1` → "当前只支持一条同档前置规则"
    # → 拒单死卡）。这里**不在契约层硬拒**（硬拒会把"修不好时的 blocked 卡兜底"也
    # 一起砍掉、变成整轮失败），改为把口径写进模型侧 schema 的 description 让它在生成
    # 时就一次只给一条；模型仍给多条时，由网关提案分支的先修一次守卫
    # （`service.py` `_PRIORITY_RULE_COUNT_REPAIR_HINT` / `_repair_priority_rule_count`）兜底。
    priority_rules: list[ProposalPriorityRule] = Field(
        default_factory=list,
        description=(
            "同档前置每次只支持一条规则；多条/分层偏好请先选最重要的一条进入本轮提案，"
            "或先向用户确认先后顺序，其余分步推进。"
        ),
    )
    target_scopes: list[ProposalScope] = Field(
        default_factory=list,
        description=(
            "范围约束（only_keep/exclude/tuition/add_units_by_scope）。"
            "remove_units/move_units 不使用 targetScopes；它们的点目标必须写 exactTargets。"
        ),
    )
    negative_scopes: list[ProposalScope] = Field(default_factory=list)
    quality_guards: list[str] = Field(default_factory=list)
    tradeoff_guards: list[str] = Field(default_factory=list)
    source_review_issue_codes: list[str] = Field(default_factory=list)
    context: ProposalContext = Field(default_factory=ProposalContext)

    @model_validator(mode="before")
    @classmethod
    def _drop_scope_restatements_for_atomic_actions(cls, data: Any) -> Any:
        """remove/move 的目标常被模型重复写进 targetScopes（实测 school_level）。

        scope 只是复述点目标时不构成额外约束，丢掉它让原子动作通过；
        真正的额外范围仍保留，由 `_validate_exact_targets` 拒绝并要求拆步。
        """
        if not isinstance(data, dict):
            return data
        goal = str(data.get("goalType") or data.get("goal_type") or "").strip()
        if goal not in {"remove_units", "move_units"}:
            return data
        targets = data.get("exactTargets") or data.get("exact_targets") or []
        scopes = data.get("targetScopes") or data.get("target_scopes") or []
        if not scopes or not targets:
            return data
        target_text = " ".join(
            str(target.get("schoolName") or target.get("school_name") or "")
            + str(target.get("majorName") or target.get("major_name") or "")
            + str(target.get("volunteerId") or target.get("volunteer_id") or "")
            for target in targets
            if isinstance(target, dict)
        )

        def restates(scope: Any) -> bool:
            if not isinstance(scope, dict):
                return False
            values = [scope.get("name"), *(scope.get("values") or [])]
            texts = [str(value).strip() for value in values if str(value or "").strip()]
            return bool(texts) and any(text in target_text for text in texts)

        if all(restates(scope) for scope in scopes):
            data = dict(data)
            data.pop("targetScopes", None)
            data.pop("target_scopes", None)
            data["targetScopes"] = []
        return data

    @model_validator(mode="after")
    def _validate_exact_targets(self) -> "ProposalRequest":
        is_add = self.goal_type == "add_units"
        is_scope_add = self.goal_type == "add_units_by_scope"
        is_remove = self.goal_type == "remove_units"
        is_move = self.goal_type == "move_units"
        is_exact_action = is_add or is_remove or is_move
        if self.add_policy == "replace" and not is_add:
            raise ValueError("addPolicy=replace is only supported for add_units")
        if is_add and not self.exact_targets:
            raise ValueError("add_units requires exactTargets")
        if is_remove and not self.exact_targets:
            raise ValueError("remove_units requires exactTargets")
        if is_move and len(self.exact_targets) != 1:
            raise ValueError("move_units requires exactly one exactTarget")
        if not is_exact_action and self.exact_targets:
            raise ValueError("exactTargets is only supported for add/remove/move units")
        if is_scope_add:
            if self.add_count is None or self.add_count <= 0:
                raise ValueError("add_units_by_scope requires addCount > 0")
            if self.exact_targets:
                raise ValueError("add_units_by_scope does not accept exactTargets")
            if (
                self.target_count is not None
                or self.tier_quota_goal is not None
                or self.requirements
                or self.priority_rules
                or self.source_review_issue_codes
            ):
                raise ValueError(
                    "add_units_by_scope only supports scopes/negativeScopes/context/guards"
                )
            if self.move_position is not None or self.move_anchor is not None:
                raise ValueError("movePosition/moveAnchor are only supported for move_units")
            return self
        if is_move:
            if self.move_position is None:
                raise ValueError("move_units requires movePosition")
            if self.move_position in {"before", "after"} and self.move_anchor is None:
                raise ValueError("movePosition=before/after requires moveAnchor")
            if self.move_position in {"top", "bottom"} and self.move_anchor is not None:
                raise ValueError("moveAnchor is only allowed for movePosition=before/after")
        elif self.move_position is not None or self.move_anchor is not None:
            raise ValueError("movePosition/moveAnchor are only supported for move_units")
        if not is_scope_add and self.add_count is not None:
            raise ValueError("addCount is only supported for add_units_by_scope")
        if is_exact_action and (
            self.target_count is not None
            or self.tier_quota_goal is not None
            or self.requirements
            or self.priority_rules
            or self.target_scopes
            or self.negative_scopes
            or self.quality_guards
            or self.tradeoff_guards
            or self.source_review_issue_codes
        ):
            raise ValueError(
                f"{self.goal_type} cannot mix with count/requirements/priority/tier/scopes/guards"
            )
        return self


class ScoreUpdateProvince(_ContractModel):
    code: str | None = None
    name: str | None = None


class ScoreUpdateSubjectType(_ContractModel):
    code: str | None = None
    desc: str | None = None


class ScoreUpdateBatch(_ContractModel):
    code: str | None = None
    name: str | None = None
    level: str | None = None
    score: float | None = None


class ScoreUpdateSubjectScore(_ContractModel):
    subject: str | None = None
    subject_name: str | None = None
    score: int | None = None


class ScoreUpdateRequest(_ContractModel):
    """模型产出的**补录成绩草稿**（写闭环第二族：score_update）。

    与 `ProposalRequest` 同一个角色定位：模型只表达**结构化草稿**（"用户说了哪些
    字段就带哪些"——合并、校验、摘要都由 Java 在生产端完成），网关不解析自然语言、
    也不自己算成绩。`source_version_guard` 与提案同一条纪律：模型看到的会话版本
    必须与当前快照一致，不一致就 `stale_state`（拿旧版本确认一个已经变化的会话，
    比让用户失败一次糟得多）。
    """

    source_version_guard: int = Field(ge=0)
    user_original_text: str = ""
    province: ScoreUpdateProvince | None = None
    subject_type: ScoreUpdateSubjectType | None = None
    batch: ScoreUpdateBatch | None = None
    total_score: int | None = None
    total_score_pos: int | None = None
    exam_year: int | None = None
    subject_score_list: list[ScoreUpdateSubjectScore] = Field(default_factory=list)


class CareerUpdateRequest(_ContractModel):
    """模型产出的**发展方向草稿**（career v1「完整落库」：写 latentProfile）。

    与 `ScoreUpdateRequest` 同一个角色定位：模型只表达**结构化草稿**（用户表达过的
    发展方向），归一化、合并、写库由网关执行链完成（`career_slots` 词表是唯一权威）。

    · **中文规范标签唯一落库**（2026-10-14 拍板）：入口可以是别名/英文槽位名/近义
      说法（见 `career_slots.CAREER_ALIAS_MAP`），契约层归一成四类之一——
      `体制内/考公导向`、`稳定就业导向`、`深造发展导向`、`市场化就业导向`；
      归不了一律**拒绝**（修复回合），不许静默丢弃：丢掉一项等于"用户说了、
      卡片上没有"，用户看不见的分叉比整轮失败糟得多。
    · **弱偏好语义**：这些方向只用于推荐理由/排序/解释与方案方向覆盖核对，
      **不做硬筛**（不排除院校/专业），模型侧描述与技能口径一致。
    · `source_version_guard` 与提案同一条纪律：模型看到的会话版本必须与当前
      快照一致，不一致就 `stale_state`。
    """

    source_version_guard: int = Field(ge=0)
    user_original_text: str = ""
    career_types: list[str] = Field(
        default_factory=list,
        description=(
            "用户表达的发展方向，必须是这四类之一（同义说法会自动归一）："
            "体制内/考公导向、稳定就业导向、深造发展导向、市场化就业导向。"
            "只放用户真正表达过的方向，不要替用户补充。"
        ),
    )

    @field_validator("career_types", mode="before")
    @classmethod
    def _coerce_text_list(cls, value: Any) -> Any:
        if value is None:
            return []
        if isinstance(value, str):
            return [value]
        return value

    @field_validator("career_types")
    @classmethod
    def _require_canonical_labels(cls, value: list[str]) -> list[str]:
        normalized = merge_career_labels(None, [str(item) for item in value])
        unknown = [
            str(item)
            for item in value
            if not normalize_career_labels([str(item)])
        ]
        if unknown:
            raise ValueError(
                "unsupported careerTypes "
                + "、".join(unknown)
                + "；仅支持："
                + "、".join(CAREER_LABEL_MAP.values())
            )
        if not normalized:
            raise ValueError("careerTypes must contain at least one direction")
        return normalized


class TurnOutput(_ContractModel):
    response_type: Literal["text", "fact", "recommendation", "review", "clarification"]
    message: str
    artifact_refs: list[ArtifactRef] = Field(default_factory=list)
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)
    admission_facts: list[AdmissionFact] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    clarification: str | None = None
    next_step: str | None = None
    execution_status: Literal["completed", "partial", "blocked", "failed"] = "completed"
    proposal_ref: str | None = None
    proposal_request: ProposalRequest | None = None
    # 与 `proposal_request` 互斥（同一次输出不许携带两个待确认草稿——卡片只能是
    # 一个"要用户确认的东西"；网关对"两个都带"按契约错误拒）。
    score_update_request: ScoreUpdateRequest | None = None
    # 发展方向草稿（career v1）：与上面两个草稿**三者互斥**（同一口径：一次确认只落一个动作）。
    career_update_request: CareerUpdateRequest | None = None
    # 完整意图草稿（Batch B）：模型把一句话里的所有要求一次说清；不写业务状态。
    # 可选：旧输出不带它时行为不变。
    intent_draft: IntentDraft | None = None
    conversation_action: ConversationAction = Field(default_factory=ConversationAction)

    @field_validator("response_type", mode="before")
    @classmethod
    def _normalize_clarification_response_type(cls, value: Any) -> Any:
        return "clarification" if value == "needs_clarification" else value

    @model_validator(mode="after")
    def _require_backend_refs(self) -> "TurnOutput":
        if self.response_type == "fact" and not self.evidence_refs:
            raise ValueError("evidenceRefs is required for fact output")
        if self.response_type in {"recommendation", "review"} and not self.artifact_refs:
            # 预览回合（有 proposalRequest）不是“推荐结论”，模型常把它的 responseType
            # 写成 recommendation 但没 artifactRefs；这是标签错误，不是缺证据——
            # 降级为 text，避免整轮失败；真正的 recommendation/review 仍必须有产物引用。
            if self.proposal_request is not None:
                self.response_type = "text"
            else:
                raise ValueError("artifactRefs is required for recommendation/review output")
        return self


class StatePatch(_ContractModel):
    base_version: int
    target_version: int
    changes: list[dict[str, Any]] = Field(default_factory=list)
    invalidations: list[dict[str, Any]] = Field(default_factory=list)

    @field_validator("target_version")
    @classmethod
    def _require_adjacent_version(cls, value: int, info: Any) -> int:
        base_version = info.data.get("base_version")
        if base_version is not None and value != base_version + 1:
            raise ValueError("targetVersion must equal baseVersion + 1")
        return value

    @field_validator("changes")
    @classmethod
    def _validate_change_paths(cls, changes: list[dict[str, Any]]) -> list[dict[str, Any]]:
        allowed = {
            "scoreContext",
            "confirmedConstraints",
            "preferences",
            "planningStage",
            "activeProposal",
            "missingFacts",
            "allowedCapabilities",
            "admissionMode",
            "journey",
        }
        for change in changes:
            path = str(change.get("path") or "")
            if path not in allowed:
                raise ValueError(f"unsupported state path: {path}")
        return changes

    @model_validator(mode="after")
    def _mode_change_requires_invalidation(self) -> "StatePatch":
        if any(change.get("path") == "admissionMode" for change in self.changes):
            has_mode_invalidation = any(
                invalidation.get("kind") == "admission_mode"
                or invalidation.get("path") == "admissionMode"
                for invalidation in self.invalidations
            )
            if not has_mode_invalidation:
                raise ValueError("admissionMode change requires admission_mode invalidation")
        return self


class ConversationTurnSnapshot(_ContractModel):
    snapshot_version: int
    session_id: str
    admission_mode: Literal["major", "major_group"] = "major"
    planning_stage: str = ""
    score_context: dict[str, Any] = Field(default_factory=dict)
    confirmed_constraints: dict[str, Any] = Field(default_factory=dict)
    preferences: dict[str, Any] = Field(default_factory=dict)
    active_proposal: dict[str, Any] | None = None
    missing_facts: list[str] = Field(default_factory=list)
    allowed_capabilities: list[str] = Field(default_factory=list)
    evidence: list[EvidenceRef] = Field(default_factory=list)
    admission_facts: list[AdmissionFact] = Field(default_factory=list)
    # J1：Java 派生的紧凑旅程块。**dict 透传、缺省容忍**，不建严格模型——
    # Java 先加字段时，extra="forbid" 的严格块会让整个快照解析失败。
    journey: dict[str, Any] | None = None

    @field_validator("admission_mode", mode="before")
    @classmethod
    def _normalize_mode(cls, value: Any) -> Any:
        try:
            return canonical_admission_mode(value)
        except AdmissionFactError as exc:
            raise ValueError(exc.code) from exc
