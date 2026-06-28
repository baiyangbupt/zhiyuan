"""3.2.0 TurnDecision live-node classifier.

This tool is intentionally benchmark-facing for now. It emits the target
TurnDecision schema and does not create pending cards, call planning tools, or
write runtime state.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import BaseModel, Field, field_validator
from pydantic_ai import Agent

from app.config import LLMConfig
from app.llm.client import LLMClient
from app.tools.extraction_json import parse_extraction_json

logger = logging.getLogger(__name__)

_turn_decision_client: LLMClient | None = None

TASK_LAYER_VALUES = ["pending", "policy", "explore", "intent", "plan", "mixed"]
SIDE_EFFECT_VALUES = [
    "readonly",
    "readonly_while_pending",
    "intent_pending",
    "plan_preview",
    "profile_change_replan",
    "profile_replan_adhoc",
    "profile_replan_ambiguous",
    "readonly_or_plan_preview",
    "needs_plan_first",
    "conflict_with_existing_pending",
    "apply_pending_then_new_request",
    "apply_pending_then_readonly",
]
SCOPE_ANCHOR_VALUES = [
    "general",
    "current_plan",
    "current_profile",
    "current_major_group",
    "candidate_pool",
    "future_reference",
    "pending_reference",
]
SCENARIO_VALUES = [
    "atomic_mutation",
    "plan_query",
    "plan_review_or_repair_preview",
    "intent_update",
    "major_group_local_policy_query",
    "apply_intent_then_generate_plan",
    "pending_conflict_new_mutation",
    "apply_pending_then_readonly_query",
    "pending_impact_query",
    "state_query_while_pending",
    "profile_change_state_query",
    "plan_query_while_pending",
    "no_plan_fact_query",
    "profile_update_replan",
    "profile_adhoc_replan",
    "profile_scope_ambiguous",
]


def _normalize_text_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if not isinstance(value, (list, tuple, set)):
        value = [value]
    result: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if text and text not in result:
            result.append(text)
    return result


class TurnDecisionResult(BaseModel):
    taskLayer: str = ""
    sideEffect: str = ""
    scopeAnchor: str = ""
    scenario: str = ""
    missingInfo: list[str] = Field(default_factory=list)
    referenceResolution: str = ""
    targetIssue: list[str] = Field(default_factory=list)
    profileScenario: str = "none"
    proposedProfile: dict[str, Any] = Field(default_factory=dict)
    confidence: float = 0.0
    reason: str = ""

    @field_validator("missingInfo", "targetIssue", mode="before")
    @classmethod
    def _coerce_list_fields(cls, value: Any) -> list[str]:
        return _normalize_text_list(value)

    @field_validator("confidence", mode="before")
    @classmethod
    def _coerce_confidence(cls, value: Any) -> float:
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"high", "高", "高置信"}:
                return 0.9
            if normalized in {"medium", "中", "中等", "中置信"}:
                return 0.65
            if normalized in {"low", "低", "低置信"}:
                return 0.35
        return float(value or 0.0)

    @field_validator("proposedProfile", mode="before")
    @classmethod
    def _coerce_proposed_profile(cls, value: Any) -> dict[str, Any]:
        return value if isinstance(value, dict) else {}


def _get_turn_decision_client() -> LLMClient:
    global _turn_decision_client
    if _turn_decision_client is None:
        _turn_decision_client = LLMClient(LLMConfig())
    return _turn_decision_client


def _build_prompt(latest_utterance: str, payload: dict[str, Any] | None = None) -> str:
    payload = payload or {}
    return json.dumps(
        {
            "latestUserText": latest_utterance,
            "planningStateProfile": payload.get("planningStateProfile") or {},
            "pendingState": payload.get("pendingState") or {},
            "historyContext": payload.get("historyContext") or [],
            "task": (
                "判断当前用户回合的 3.2.0 TurnDecision。只输出结构化 JSON，不执行任何动作。"
                "所有枚举字段必须从 allowedValues 中原样选择英文 ID。"
            ),
            "allowedValues": {
                "taskLayer": TASK_LAYER_VALUES,
                "sideEffect": SIDE_EFFECT_VALUES,
                "scopeAnchor": SCOPE_ANCHOR_VALUES,
                "scenario": SCENARIO_VALUES,
            },
            "schemaRules": [
                "最终回答必须只包含一个 JSON object。第一个字符必须是 {，最后一个字符必须是 }，禁止 markdown、禁止解释文字、禁止连续输出多个 JSON object。",
                "scenario 只能是 allowedValues.scenario 中的英文 ID，禁止输出解释句、中文句子或自造 ID。",
                "解释必须放在 reason，不要放在 scenario。",
                "planningStateProfile 是权威状态输入。formalPlanPresent、pendingExists、candidatePoolPresent、scoreReady、majorGroupPlanPresent 必须按输入布尔值使用，禁止根据历史或用户话术反推成相反值。",
                "formalPlanPresent=false 时，即使用户说“刚那个方案/当前方案/方案里”，也必须判断为没有可引用的正式方案；不能把这些话术反推成 formalPlanPresent=true。",
                "pendingExists=false 时，禁止在 reason 或输出中说当前存在 pending，也禁止输出 conflict_with_existing_pending、apply_pending_then_new_request、apply_pending_then_readonly、readonly_while_pending。",
                "pendingExists=true 时，只能在用户明确要求确认/执行已有 pending 时 apply；普通查询不能 apply。",
                "pendingExists=true 且用户提出新的删除、替换、减少、移动、重排等当前方案 mutation 时，active pending 冲突优先于 formalPlanPresent 判断，必须输出 conflict_with_existing_pending。",
                "pendingExists=true 且 pendingState.kind=intent_change 时，用户提出新的未来偏好、排除、关注院校/专业/地域、院校性质（公办/民办）或特殊录取路径更新，不属于当前方案 mutation；输出 intent_pending/future_reference/intent_update，用新的 intent pending 替换或刷新旧 intent pending。",
                "referenceResolution 使用 current_plan、current_profile、current_major_group、candidate_pool、future_reference、pending_reference、no_referent 等短 ID。",
                "taskLayer=explore 只用于非方案、非候选池、非偏好写入的泛兴趣闲聊；候选池机会查询属于 plan 层。",
                "taskLayer=policy 只用于不绑定当前方案、当前专业组或个人 profile 的通用招生政策问答；当前专业组策略问题属于 plan 层。",
            ],
            "hardRules": [
                "formalPlanPresent=false 时，当前方案事实查询、删除、减少、替换、查看方案内民办等必须是 needs_plan_first；referenceResolution=no_referent。",
                "pendingExists=true 且用户只是问有没有、多少、看下、是不是按某条件算，必须 readonly_while_pending，不能 apply/cancel pending。",
                "pendingExists=true 且用户询问当前这条待采纳内容、偏好或调整预览会有什么影响、确认前后有什么变化，输出 readonly_while_pending、scopeAnchor=pending_reference、scenario=pending_impact_query。",
                "pendingExists=true 且用户提出新的当前方案 mutation，必须 conflict_with_existing_pending，不能创建第二个 pending。",
                "pendingExists=true 且 pendingState.kind=intent_change，用户提出新的未来报考意向更新时，不能误判为 pending_conflict_new_mutation，也不能误判为 atomic_mutation/current_plan，也不能因为句子里说“方案/你这”就降级成 readonly_while_pending。",
                "pendingExists=true 且用户说先执行已有 pending 再查询结果，例如“删完了再看看”，输出 taskLayer=mixed、sideEffect=apply_pending_then_readonly、scenario=apply_pending_then_readonly_query。",
                "pendingState.kind=intent_change 且用户说基于这些出方案，输出 taskLayer=mixed、sideEffect=apply_pending_then_new_request、scopeAnchor=future_reference、scenario=apply_intent_then_generate_plan。",
                "用户明确设置未来偏好/排除，例如倾向某专业但不要某专业，输出 taskLayer=intent、sideEffect=intent_pending、scopeAnchor=future_reference、scenario=intent_update；即使 formalPlanPresent=true 也不能改成 taskLayer=plan。",
                "用户说加入/加上/记上某省份、城市、地域、院校、专业或发展方向，但没有明确说加入当前方案、候选志愿、刚才推荐的条目或具体志愿项时，属于未来报考意向更新；输出 taskLayer=intent、sideEffect=intent_pending、scopeAnchor=future_reference、scenario=intent_update，不能输出 add_units/plan_preview。",
                "用户点名某个学校+专业、学校简称+专业、候选志愿或刚才推荐的具体条目，并说加进来/加入方案/放进方案/补进来时，属于当前方案 add_units 预览；formalPlanPresent=true 且 pendingExists=false 时输出 taskLayer=plan、sideEffect=plan_preview、scopeAnchor=current_plan、scenario=atomic_mutation。只有用户明确说加到意向、后续参考、以后推荐按这个考虑时，才输出 future_reference/intent_update。",
                "用户说加点/增加/补点/优先/可以考虑公办、民办、某类院校或学校性质，即使同时抱怨“你这全是民办/中外合作/公办太少”，也是新的未来院校性质偏好更新；pendingState.kind=intent_change 时必须输出 intent_pending/future_reference/intent_update，用新 pending 替换旧 pending。",
                "用户说不接受/不要/排除高学费、高收费、费用太高、中外合作、民办等，且没有明确要求删除/替换当前方案里的命中项时，属于费用或项目限制的未来报考意向；输出 taskLayer=intent、sideEffect=intent_pending、scopeAnchor=future_reference、scenario=intent_update，targetIssue 可包含 tuition/high_tuition/cooperative_program/college_type。",
                "ASR/错别字要按语义理解，例如“稿费”“高高学费”在学费上下文中通常是“高费/高学费/高收费”，不能因此输出低置信的无关 replace_units 或 profile 缺失兜底。",
                "用户明确设置长期报考范围，例如只保留/仅保留/只看/必须有/至少保留某专业、院校、地域，且没有明确要求把当前方案里的非匹配项删除、移出、替换或生成调整预览时，输出 taskLayer=intent、sideEffect=intent_pending、scopeAnchor=future_reference、scenario=intent_update；即使说“方案里必须有”也先视为待采纳报考要求。",
                "用户要求按录取率、院校层次、学校质量、推荐分等规则重新排列当前方案，例如“按好学校排下看看/按院校层次排序/按录取率重排”，属于会改变导出顺序的当前方案 mutation；formalPlanPresent=true 且 pendingExists=false 时输出 taskLayer=plan、sideEffect=plan_preview、scopeAnchor=current_plan、scenario=atomic_mutation。",
                "用户修正或更新当前学生本人的分数、位次、省份、选科、批次，并要求当前会话按新资料重新规划，输出 taskLayer=plan、sideEffect=profile_change_replan、scopeAnchor=current_profile、scenario=profile_update_replan、profileScenario=current_student_update。",
                "如果用户只是临时拿一组资料测算、假设推演、帮别人问，输出 sideEffect=profile_replan_adhoc、scopeAnchor=current_profile、scenario=profile_adhoc_replan、profileScenario=adhoc_scenario；不能让当前 profile 或当前方案继承这组资料。",
                "如果无法确定是临时测算还是当前学生资料更新，输出 sideEffect=profile_replan_ambiguous、scopeAnchor=current_profile、scenario=profile_scope_ambiguous、profileScenario=ambiguous。",
                "profile update/replan 必须把用户本轮明确给出的 score、rank、province、subjects、subjectCombo、batch 放进 proposedProfile；不要为了凑字段猜测缺失资料。",
                "用户说别直接动、先看看怎么处理，可以输出 readonly_or_plan_preview，但不能直接 apply。",
                "候选池机会查询在缺少分数/位次时仍是 taskLayer=plan、sideEffect=readonly、scopeAnchor=candidate_pool，并在 missingInfo 放 score_or_rank；不要输出 taskLayer=explore。",
                "用户问某地大学/学校/院校/候选机会有哪些、哪几个适合我、推荐哪些学校，例如“江西的大学有哪些适合我”，属于候选池或学校机会只读查询；输出 taskLayer=plan、sideEffect=readonly、scopeAnchor=candidate_pool，不能输出 intent_pending/future_reference。",
                "专业组局部政策/可不可以类问题是 taskLayer=plan、sideEffect=readonly、scopeAnchor=current_major_group，不是 policy 层，不是未来偏好写入；例如“专业组里只保留最稳的专业行不行”是 scenario=major_group_local_policy_query。",
                "当前方案按分数、省份、选科、批次等计算依据的确认问题，scopeAnchor=current_profile；pendingExists=true 时 scenario=state_query_while_pending。",
                "如果 historyContext 中已有 ProfileChangeReplan DSL，用户追问当前正式方案是不是已经按这组新资料计算/重算，输出 scopeAnchor=current_profile、scenario=profile_change_state_query；pendingExists=true 时 sideEffect=readonly_while_pending，否则 sideEffect=readonly。",
                "pendingExists=true 且用户问当前方案有没有/是否包含某专业或风险，scenario=plan_query；pendingExists=true 且用户要求查看方案列表、保底学校、梯度等范围列表，scenario=plan_query_while_pending。",
            ],
            "scenarioGuide": {
                "atomic_mutation": "有正式方案、无 pending，用户要求对当前方案做删除/替换/减少/新增/排序/重排等 mutation，输出 plan_preview/current_plan。",
                "plan_query": "有 pending 时，用户问当前方案里有没有/是否包含某类、某专业、某风险，输出 readonly_while_pending/current_plan。",
                "pending_impact_query": "已有 pending，用户询问这条 pending 本身的影响、确认前是否生效、会怎么影响当前方案或后续参考，输出 readonly_while_pending/pending_reference。",
                "plan_review_or_repair_preview": "用户要求先看怎么处理风险、别直接动，输出 readonly_or_plan_preview/current_plan。",
                "intent_update": "用户设置未来偏好/排除，不是修改当前方案，输出 intent_pending/future_reference。",
                "major_group_local_policy_query": "用户问专业组内部策略是否可行，语气是“行不行/可不可以”，输出 readonly/current_major_group。",
                "apply_intent_then_generate_plan": "已有 intent_change pending，用户要求基于这些出方案，输出 mixed/apply_pending_then_new_request/future_reference。",
                "pending_conflict_new_mutation": "已有 pending，用户又提出新的当前方案 mutation，输出 conflict_with_existing_pending/current_plan。",
                "apply_pending_then_readonly_query": "已有 pending，用户说执行完再查询结果，输出 mixed/apply_pending_then_readonly/current_plan。",
                "state_query_while_pending": "已有 pending，用户询问方案是否按某分数、省份、选科等 profile 计算，输出 readonly_while_pending/current_profile。",
                "profile_change_state_query": "已有 ProfileChangeReplan 状态，用户追问正式方案是否已按新资料重算，输出 current_profile readonly/readonly_while_pending。",
                "plan_query_while_pending": "已有 pending，用户要求看当前方案列表、保底学校、梯度等范围列表，输出 readonly_while_pending/current_plan。",
                "no_plan_fact_query": "没有正式方案，用户问方案内事实，输出 needs_plan_first/current_plan/no_referent。",
                "profile_update_replan": "用户更新当前学生基础资料并要求按新资料重新规划，输出 profile_change_replan/current_profile/current_student_update。",
                "profile_adhoc_replan": "用户临时测算或帮别人问，不更新当前 profile，输出 profile_replan_adhoc/current_profile/adhoc_scenario。",
                "profile_scope_ambiguous": "无法判断是否更新当前学生资料，输出 profile_replan_ambiguous/current_profile/ambiguous。",
            },
            "examples": [
                {
                    "latestUserText": "按好学校排下看看",
                    "planningStateProfile": {"formalPlanPresent": True, "pendingExists": False},
                    "output": {
                        "taskLayer": "plan",
                        "sideEffect": "plan_preview",
                        "scopeAnchor": "current_plan",
                        "scenario": "atomic_mutation",
                    },
                },
                {
                    "latestUserText": "不要英语相关专业，当前方案里有的话也删掉",
                    "planningStateProfile": {"formalPlanPresent": True, "pendingExists": False},
                    "output": {
                        "taskLayer": "plan",
                        "sideEffect": "plan_preview",
                        "scopeAnchor": "current_plan",
                        "scenario": "atomic_mutation",
                    },
                },
                {
                    "latestUserText": "方案里必须有法学，其他专业可以先保留",
                    "planningStateProfile": {"formalPlanPresent": True, "pendingExists": False},
                    "output": {
                        "taskLayer": "intent",
                        "sideEffect": "intent_pending",
                        "scopeAnchor": "future_reference",
                        "scenario": "intent_update",
                    },
                },
                {
                    "latestUserText": "仅保留江苏的学校",
                    "planningStateProfile": {"formalPlanPresent": True, "pendingExists": False},
                    "output": {
                        "taskLayer": "intent",
                        "sideEffect": "intent_pending",
                        "scopeAnchor": "future_reference",
                        "scenario": "intent_update",
                    },
                },
                {
                    "latestUserText": "加入广东和江西",
                    "planningStateProfile": {"formalPlanPresent": False, "pendingExists": False},
                    "output": {
                        "taskLayer": "intent",
                        "sideEffect": "intent_pending",
                        "scopeAnchor": "future_reference",
                        "scenario": "intent_update",
                    },
                },
                {
                    "latestUserText": "把湖北工程学院的计算机科学与技术加进来",
                    "planningStateProfile": {"formalPlanPresent": True, "candidatePoolPresent": True, "pendingExists": False},
                    "output": {
                        "taskLayer": "plan",
                        "sideEffect": "plan_preview",
                        "scopeAnchor": "current_plan",
                        "scenario": "atomic_mutation",
                    },
                },
                {
                    "latestUserText": "我的意思是能加点公办院校可以考虑吗你这全是民办院校",
                    "planningStateProfile": {"formalPlanPresent": False, "pendingExists": True},
                    "pendingState": {"kind": "intent_change", "actionFamily": "apply_selected_intents"},
                    "output": {
                        "taskLayer": "intent",
                        "sideEffect": "intent_pending",
                        "scopeAnchor": "future_reference",
                        "scenario": "intent_update",
                    },
                },
                {
                    "latestUserText": "那如果我不接受稿费呢高高学费",
                    "planningStateProfile": {"formalPlanPresent": True, "pendingExists": False},
                    "output": {
                        "taskLayer": "intent",
                        "sideEffect": "intent_pending",
                        "scopeAnchor": "future_reference",
                        "scenario": "intent_update",
                        "targetIssue": ["tuition", "high_tuition"],
                    },
                },
                {
                    "latestUserText": "现在基于这些出方案",
                    "planningStateProfile": {"formalPlanPresent": False, "candidatePoolPresent": True, "pendingExists": True},
                    "pendingState": {"kind": "intent_change"},
                    "output": {
                        "taskLayer": "mixed",
                        "sideEffect": "apply_pending_then_new_request",
                        "scopeAnchor": "future_reference",
                        "scenario": "apply_intent_then_generate_plan",
                    },
                },
                {
                    "latestUserText": "现在方案是按620湖北算的吧",
                    "planningStateProfile": {"formalPlanPresent": True, "pendingExists": True},
                    "historyContext": [
                        {
                            "type": "profileChangeReplanDsl",
                            "value": {
                                "type": "ProfileChangeReplan",
                                "profileMode": "current_student_update",
                                "proposedProfileSummary": "620分、湖北",
                            },
                        }
                    ],
                    "output": {
                        "taskLayer": "plan",
                        "sideEffect": "readonly_while_pending",
                        "scopeAnchor": "current_profile",
                        "scenario": "profile_change_state_query",
                    },
                },
                {
                    "latestUserText": "分数也说错了应该是620不是630",
                    "planningStateProfile": {"formalPlanPresent": True, "pendingExists": False},
                    "output": {
                        "taskLayer": "plan",
                        "sideEffect": "profile_change_replan",
                        "scopeAnchor": "current_profile",
                        "scenario": "profile_update_replan",
                        "profileScenario": "current_student_update",
                        "proposedProfile": {"score": 620},
                    },
                },
                {
                    "latestUserText": "那基于620湖北物化生重来",
                    "planningStateProfile": {"formalPlanPresent": True, "pendingExists": False},
                    "output": {
                        "taskLayer": "plan",
                        "sideEffect": "profile_change_replan",
                        "scopeAnchor": "current_profile",
                        "scenario": "profile_update_replan",
                        "profileScenario": "current_student_update",
                        "proposedProfile": {"score": 620, "province": "湖北", "subjectCombo": "物化生"},
                    },
                },
                {
                    "latestUserText": "如果按515分临时看看能报什么",
                    "planningStateProfile": {"formalPlanPresent": True, "pendingExists": False},
                    "output": {
                        "taskLayer": "plan",
                        "sideEffect": "profile_replan_adhoc",
                        "scopeAnchor": "current_profile",
                        "scenario": "profile_adhoc_replan",
                        "profileScenario": "adhoc_scenario",
                        "proposedProfile": {"score": 515},
                    },
                },
                {
                    "latestUserText": "我是湖北物化生，想看看候选里计算机和数据科学方向多不多",
                    "planningStateProfile": {
                        "scoreReady": False,
                        "formalPlanPresent": False,
                        "candidatePoolPresent": False,
                        "pendingExists": False,
                    },
                    "output": {
                        "taskLayer": "plan",
                        "sideEffect": "readonly",
                        "scopeAnchor": "candidate_pool",
                        "missingInfo": ["score_or_rank"],
                    },
                },
                {
                    "latestUserText": "专业组里只保留最稳的专业行不行",
                    "planningStateProfile": {
                        "formalPlanPresent": True,
                        "majorGroupPlanPresent": True,
                        "pendingExists": False,
                    },
                    "output": {
                        "taskLayer": "plan",
                        "sideEffect": "readonly",
                        "scopeAnchor": "current_major_group",
                        "scenario": "major_group_local_policy_query",
                    },
                },
                {
                    "latestUserText": "我倾向会计学和审计学，但土木工程不要",
                    "planningStateProfile": {"formalPlanPresent": True, "pendingExists": False},
                    "output": {
                        "taskLayer": "intent",
                        "sideEffect": "intent_pending",
                        "scopeAnchor": "future_reference",
                        "scenario": "intent_update",
                    },
                },
                {
                    "latestUserText": "刚那个方案民办能少点不",
                    "planningStateProfile": {"formalPlanPresent": False, "pendingExists": False},
                    "output": {
                        "taskLayer": "plan",
                        "sideEffect": "needs_plan_first",
                        "scopeAnchor": "current_plan",
                        "scenario": "no_plan_fact_query",
                        "referenceResolution": "no_referent",
                    },
                },
                {
                    "latestUserText": "冲档太冒险了删掉一个",
                    "planningStateProfile": {"formalPlanPresent": False, "pendingExists": True},
                    "pendingState": {"kind": "plan_mutation", "actionFamily": "generate_plan"},
                    "output": {
                        "taskLayer": "plan",
                        "sideEffect": "conflict_with_existing_pending",
                        "scopeAnchor": "current_plan",
                        "scenario": "pending_conflict_new_mutation",
                    },
                },
            ],
            "returnJson": {
                "taskLayer": "",
                "sideEffect": "",
                "scopeAnchor": "",
                "scenario": "one of allowedValues.scenario",
                "missingInfo": [],
                "referenceResolution": "",
                "targetIssue": [],
                "profileScenario": "none",
                "proposedProfile": {},
                "confidence": 0.0,
                "reason": "",
            },
        },
        ensure_ascii=False,
    )


def _payload_bool(payload: dict[str, Any] | None, key: str) -> bool | None:
    if not isinstance(payload, dict):
        return None
    planning_state = payload.get("planningStateProfile")
    if not isinstance(planning_state, dict) or key not in planning_state:
        return None
    value = planning_state.get(key)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "y"}:
            return True
        if lowered in {"false", "0", "no", "n"}:
            return False
    return None


def _normalize_turn_decision(
    result: TurnDecisionResult,
    *,
    payload: dict[str, Any] | None = None,
) -> TurnDecisionResult:
    confidence = max(0.0, min(1.0, float(result.confidence or 0.0)))
    task_layer = str(result.taskLayer or "").strip()
    side_effect = str(result.sideEffect or "").strip()
    scope_anchor = str(result.scopeAnchor or "").strip()
    scenario = str(result.scenario or "").strip()
    pending_exists = _payload_bool(payload, "pendingExists")
    if pending_exists is False:
        if side_effect == "readonly_while_pending":
            side_effect = "readonly"
        if scenario == "plan_query_while_pending":
            scenario = "plan_query"
        if scenario == "pending_impact_query":
            scenario = "plan_query"
            if scope_anchor == "pending_reference":
                scope_anchor = "current_plan"
    return TurnDecisionResult(
        taskLayer=task_layer,
        sideEffect=side_effect,
        scopeAnchor=scope_anchor,
        scenario=scenario,
        missingInfo=result.missingInfo,
        referenceResolution=str(result.referenceResolution or "").strip(),
        targetIssue=result.targetIssue,
        profileScenario=str(result.profileScenario or "none").strip() or "none",
        proposedProfile=dict(result.proposedProfile or {}),
        confidence=confidence,
        reason=result.reason,
    )


async def classify_turn_decision(
    latest_utterance: str,
    *,
    payload: dict[str, Any] | None = None,
) -> TurnDecisionResult:
    text = str(latest_utterance or "").strip()
    if not text:
        return TurnDecisionResult(taskLayer="explore", sideEffect="readonly", scopeAnchor="general")
    agent = Agent(
        model=_get_turn_decision_client().model,
        output_type=str,
        instructions=_build_prompt(text, payload),
    )
    result = await agent.run("请输出 TurnDecision JSON", model_settings={"temperature": 0})
    parsed = parse_extraction_json(result.output, TurnDecisionResult)
    normalized = _normalize_turn_decision(parsed, payload=payload)
    logger.info(
        "classify_turn_decision: task_layer=%s side_effect=%s scope=%s scenario=%s confidence=%s",
        normalized.taskLayer,
        normalized.sideEffect,
        normalized.scopeAnchor,
        normalized.scenario,
        normalized.confidence,
    )
    return normalized
