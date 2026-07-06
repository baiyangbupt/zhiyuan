"""集成测试：完整方案流程。

验证 Phase 0-5 引入的新抽象层在端到端场景中的协作：
- ConversationPhase 状态转换
- PlanningStateSync 版本乐观锁
- ActionResolver 意图→动作映射
- PendingConfirmation 生命周期
- Instructions assembler 组装

双模式 (major / majorGroup) 参数化覆盖。
"""

from __future__ import annotations

import pytest
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.models.conversation_phase import (
    ConversationPhase,
    PendingConfirmation,
    PhaseState,
)
from app.models.intent_frame import IntentFrame, ScopeSpec, TargetSpec
from app.resolver.action_resolver import ActionResolution, ActionResolver
from app.sync.state_sync import PlanningStateSync, StaleCause
from app.agent.instructions import build_instructions
from app.agent.context import RequestContext, PlanningSummary, ScoreDetail
from tests.factories import (
    make_plan_context_inputs,
    make_planning_summary,
    make_request_context,
    make_review_issue,
    make_score_detail,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(params=["major", "majorGroup"])
def volunteer_model(request):
    return request.param


@pytest.fixture
def resolver():
    return ActionResolver()


@pytest.fixture
def sync():
    return PlanningStateSync(max_pending_age=3)


def _make_phase(
    *,
    state: PhaseState = PhaseState.EXPLORE,
    version: int = 0,
    turn: int = 0,
    pending: PendingConfirmation | None = None,
) -> ConversationPhase:
    return ConversationPhase(
        state=state,
        pending=pending,
        turn_count=turn,
        last_backend_version=version,
    )


def _make_run_context(
    *,
    volunteer_model: str = "major",
    planning_phase: str = "",
    ordered_total: int = 0,
    chat_history: list[dict] | None = None,
    conversation_phase: ConversationPhase | None = None,
) -> SimpleNamespace:
    ctx = make_request_context(
        volunteer_model=volunteer_model,
        planning_phase=planning_phase,
        planning_ordered_total=ordered_total,
        conversation_phase=conversation_phase,
    )
    ctx.chat_history = chat_history or []
    return SimpleNamespace(deps=ctx)


# ---------------------------------------------------------------------------
# 场景 1: 全新 session → 生成方案 → 审查 → 确认补偿
# ---------------------------------------------------------------------------


class TestFullLifecycle:
    """完整生命周期：Explore → generate → review → compensate。"""

    def test_lifecycle_phase_transitions(self, volunteer_model, resolver, sync):
        """验证状态机在完整流程中的合法转换。"""
        phase = _make_phase(state=PhaseState.EXPLORE)
        context = make_plan_context_inputs(phase="initial", ordered_count=0)

        # Step 1: 用户说"帮我生成方案" → generate_plan
        frame = IntentFrame(
            task_layer="plan",
            topic="general",
            verb="generate",
            raw_utterance="帮我生成一个方案",
        )
        resolution = resolver.resolve(frame, context)
        assert resolution.action_family == "generate_plan"
        assert resolution.stage == "preview"

        # 转换到 PLAN_IDLE（进入方案讨论）
        phase.transition_to(PhaseState.PLAN_IDLE)
        assert phase.state == PhaseState.PLAN_IDLE

        # Step 2: 生成后设置 pending
        pending = PendingConfirmation(
            kind="plan_mutation",
            action_family="generate_plan",
            preview_summary="将生成包含96个志愿的方案",
            execution_payload={"action_family": "generate_plan", "stage": "apply"},
            created_turn=1,
        )
        phase.set_pending(pending)
        assert phase.state == PhaseState.PLAN_PREVIEWING

        # Step 3: 用户确认。
        # 3.0.3 起确认/取消不再作为 IntentFrame verb 进入 ActionResolver，
        # 而是由 service-level pendingConfirmation 入口消费 active pending。
        cleared = phase.clear_pending()
        assert cleared is not None
        assert cleared.action_family == "generate_plan"
        assert phase.state == PhaseState.PLAN_IDLE

        # Step 4: 生成完成，版本更新
        summary_v2 = make_planning_summary(version=2, ordered_total=30)
        sync.update_version(phase, summary_v2)
        assert phase.last_backend_version == 2

        # Step 5: 用户说"审查方案" → review_plan
        context_with_plan = make_plan_context_inputs(
            phase="ordered", ordered_count=30
        )
        frame_review = IntentFrame(
            task_layer="plan",
            topic="general",
            verb="review",
        )
        resolution = resolver.resolve(frame_review, context_with_plan)
        assert resolution.action_family == "review_plan"
        assert resolution.stage == "review"

        # Step 6: 审查后发现高收费 → 用户说"处理补偿"
        # target_count > ordered_count 避免 normalization Rule 4 (plan filled → analyze)
        context_unfilled = make_plan_context_inputs(
            phase="ordered", ordered_count=30, target_count=96
        )
        frame_comp = IntentFrame(
            task_layer="plan",
            topic="general",
            verb="compensate",
        )
        resolution = resolver.resolve(frame_comp, context_unfilled)
        assert resolution.action_family == "preview_fix_proposal"

    def test_lifecycle_version_tracking(self, volunteer_model, sync):
        """验证版本号在流程中的正确追踪。"""
        phase = _make_phase(state=PhaseState.PLAN_IDLE, version=0)

        # 首次获取 → 版本初始化
        v1 = make_planning_summary(version=1)
        sync.update_version(phase, v1)
        assert phase.last_backend_version == 1

        # 生成后 → 版本跳变
        v3 = make_planning_summary(version=3)
        check = sync.check_version(phase, v3)
        assert check.is_current is False
        assert check.drift == 2

        sync.update_version(phase, v3)
        assert phase.last_backend_version == 3


# ---------------------------------------------------------------------------
# 场景 2: Explore → Intent confirm → Plan generate
# ---------------------------------------------------------------------------


class TestStageChaining:
    """阶段串联：Explore → Intent → Plan。"""

    def test_explore_to_intent_to_plan(self, volunteer_model, resolver):
        """从探索阶段经由意向确认进入方案生成。"""
        phase = _make_phase(state=PhaseState.EXPLORE)
        context = make_plan_context_inputs(phase="initial", ordered_count=0)

        # Step 1: Explore — 用户查询概况（plan layer 处理）
        frame_explore = IntentFrame(
            task_layer="plan",
            topic="general",
            verb="query",
            raw_utterance="当前方案什么状态",
        )
        resolution = resolver.resolve(frame_explore, context)
        assert resolution.action_family == "query_state"

        # Step 2: Intent — 设置偏好
        # Resolver 对 non-plan task_layer 返回 blocked（由 intent tool 处理）
        frame_intent = IntentFrame(
            task_layer="intent",
            topic="major",
            verb="set_preference",
            target=TargetSpec(major_names=["计算机科学与技术"]),
        )
        resolution = resolver.resolve(frame_intent, context)
        assert resolution.stage == "blocked"

        # Intent 工具处理后 → 设置 pending
        phase.set_pending(PendingConfirmation(
            kind="intent_change",
            action_family="set_preference",
            preview_summary="添加专业偏好：计算机科学与技术",
            created_turn=2,
        ))
        assert phase.state == PhaseState.INTENT_PREVIEWING

        # Step 3: 确认意向
        phase.clear_pending()
        # 意向确认后可以进入 PLAN_IDLE
        phase.transition_to(PhaseState.PLAN_IDLE)
        assert phase.state == PhaseState.PLAN_IDLE

        # Step 4: 方案生成
        frame_gen = IntentFrame(
            task_layer="plan",
            topic="general",
            verb="generate",
        )
        resolution = resolver.resolve(frame_gen, context)
        assert resolution.action_family == "generate_plan"

    def test_explore_direct_to_plan(self, volunteer_model, resolver):
        """跳过 Intent 直接进入方案（合法转换）。"""
        phase = _make_phase(state=PhaseState.EXPLORE)
        assert phase.can_transition_to(PhaseState.PLAN_IDLE)

        phase.transition_to(PhaseState.PLAN_IDLE)
        context = make_plan_context_inputs(phase="initial", ordered_count=0)
        frame = IntentFrame(task_layer="plan", topic="general", verb="generate")
        resolution = resolver.resolve(frame, context)
        assert resolution.action_family == "generate_plan"


# ---------------------------------------------------------------------------
# 场景 3: Plan preview → 用户确认 → apply
# ---------------------------------------------------------------------------


class TestPendingConfirmation:
    """Pending 确认协议。"""

    def test_preview_confirm_apply(self, volunteer_model, sync):
        """预览 → 确认 → 执行的标准流程。"""
        phase = _make_phase(
            state=PhaseState.PLAN_IDLE,
            version=5,
            turn=10,
        )
        summary = make_planning_summary(version=5)

        # 预览阶段 — 设置 pending
        pending = PendingConfirmation(
            kind="plan_mutation",
            action_family="remove_units",
            preview_summary="将移除3个高收费志愿",
            execution_payload={
                "action_family": "remove_units",
                "stage": "apply",
                "atomic_actions": [{"action": "remove", "volunteer_ids": ["v1", "v2", "v3"]}],
            },
            affected_scope="涉及3个志愿",
            created_turn=10,
        )
        phase.set_pending(pending)
        assert phase.state == PhaseState.PLAN_PREVIEWING

        # 版本仍然一致
        stale_event = sync.invalidate_if_stale(phase, current_turn=11, planning_summary=summary)
        assert stale_event.is_stale is False

        # guard 通过
        guard_event = sync.pre_execute_guard(phase, summary, "remove_units")
        assert guard_event.is_stale is False

        # 执行
        cleared = phase.clear_pending()
        assert cleared is not None
        assert cleared.execution_payload["action_family"] == "remove_units"
        assert phase.state == PhaseState.PLAN_IDLE

        # 版本更新
        summary_v6 = make_planning_summary(version=6)
        sync.update_version(phase, summary_v6)
        assert phase.last_backend_version == 6

    def test_preview_reject(self, volunteer_model):
        """用户拒绝预览操作。"""
        phase = _make_phase(state=PhaseState.PLAN_IDLE, turn=5)
        phase.set_pending(PendingConfirmation(
            kind="plan_mutation",
            action_family="add_units",
            preview_summary="添加5个志愿",
            created_turn=5,
        ))
        assert phase.state == PhaseState.PLAN_PREVIEWING

        # 用户说"不要了"
        cleared = phase.clear_pending()
        assert cleared.action_family == "add_units"
        assert phase.state == PhaseState.PLAN_IDLE
        assert phase.pending is None

    def test_intent_pending_lifecycle(self, volunteer_model):
        """Intent 层 pending 生命周期。"""
        phase = _make_phase(state=PhaseState.EXPLORE, turn=3)

        pending = PendingConfirmation(
            kind="intent_change",
            action_family="set_preference",
            preview_summary="设置城市偏好：北京",
            created_turn=3,
        )
        phase.set_pending(pending)
        assert phase.state == PhaseState.INTENT_PREVIEWING

        # 确认 → 回到 EXPLORE
        phase.clear_pending()
        assert phase.state == PhaseState.EXPLORE


# ---------------------------------------------------------------------------
# 场景 4: Plan preview → 前端操作 → pending 失效
# ---------------------------------------------------------------------------


class TestConcurrentModification:
    """前端并发操作导致 pending 失效。"""

    def test_frontend_mutation_invalidates_pending(self, volunteer_model, sync):
        """前端操作修改了方案，pending 失效。"""
        phase = _make_phase(
            state=PhaseState.PLAN_PREVIEWING,
            version=5,
            turn=10,
            pending=PendingConfirmation(
                kind="plan_mutation",
                action_family="move_unit",
                preview_summary="移动志愿到第3位",
                execution_payload={"action_family": "move_unit", "stage": "apply"},
                created_turn=10,
            ),
        )

        # 前端拖拽了志愿，版本变为 7
        summary_v7 = make_planning_summary(version=7)

        # 检测漂移
        check = sync.check_version(phase, summary_v7)
        assert check.is_current is False
        assert check.drift == 2

        # pending 失效
        event = sync.invalidate_if_stale(phase, current_turn=11, planning_summary=summary_v7)
        assert event.is_stale is True
        assert event.cause == StaleCause.VERSION_MISMATCH
        assert event.should_clear_pending is True
        assert event.should_refresh_context is True

        # 清除并更新
        phase.clear_pending()
        sync.update_version(phase, summary_v7)
        assert phase.state == PhaseState.PLAN_IDLE
        assert phase.last_backend_version == 7

    def test_guard_blocks_stale_execution(self, volunteer_model, sync):
        """执行前 guard 拦截版本不一致的 mutating action。"""
        phase = _make_phase(state=PhaseState.PLAN_IDLE, version=3)
        summary_v5 = make_planning_summary(version=5)

        event = sync.pre_execute_guard(phase, summary_v5, "add_units")
        assert event.is_stale is True
        assert event.cause == StaleCause.VERSION_MISMATCH
        assert "3" in event.message
        assert "5" in event.message

    def test_guard_allows_read_actions_despite_drift(self, volunteer_model, sync):
        """即使版本漂移，查询类操作仍可执行。"""
        phase = _make_phase(state=PhaseState.PLAN_IDLE, version=3)
        summary_v10 = make_planning_summary(version=10)

        for action in ["query_state", "query_ordered", "review_plan", "analyze_adjustment"]:
            event = sync.pre_execute_guard(phase, summary_v10, action)
            assert event.is_stale is False, f"{action} should pass despite drift"


# ---------------------------------------------------------------------------
# 场景 5: 连续 3 轮 pending 未确认 → 自动过期
# ---------------------------------------------------------------------------


class TestPendingExpiry:
    """Turn-based pending 过期。"""

    def test_three_rounds_unconfirmed_expires(self, volunteer_model, sync):
        """超过 3 轮未确认的 pending 自动过期。"""
        phase = _make_phase(
            state=PhaseState.PLAN_PREVIEWING,
            version=5,
            turn=10,
            pending=PendingConfirmation(
                kind="plan_mutation",
                action_family="generate_plan",
                preview_summary="生成方案",
                created_turn=1,
            ),
        )
        summary = make_planning_summary(version=5)

        # 第 2 轮 — 未过期
        event = sync.invalidate_if_stale(phase, current_turn=2, planning_summary=summary)
        assert event.is_stale is False

        # 第 4 轮 — 未过期（刚好 3 轮）
        event = sync.invalidate_if_stale(phase, current_turn=4, planning_summary=summary)
        assert event.is_stale is False

        # 第 5 轮 — 过期（超过 3 轮）
        event = sync.invalidate_if_stale(phase, current_turn=5, planning_summary=summary)
        assert event.is_stale is True
        assert event.cause == StaleCause.TURN_EXPIRED
        assert event.should_clear_pending is True

        phase.clear_pending()
        assert phase.state == PhaseState.PLAN_IDLE

    def test_custom_max_age(self, volunteer_model):
        """自定义 max_age 参数。"""
        sync_strict = PlanningStateSync(max_pending_age=1)
        phase = _make_phase(
            state=PhaseState.PLAN_PREVIEWING,
            version=5,
            pending=PendingConfirmation(
                kind="plan_mutation",
                action_family="move_unit",
                created_turn=3,
            ),
        )
        summary = make_planning_summary(version=5)

        event = sync_strict.invalidate_if_stale(phase, current_turn=5, planning_summary=summary)
        assert event.is_stale is True


# ---------------------------------------------------------------------------
# 场景 6: ActionResolver 结构化映射
# ---------------------------------------------------------------------------


class TestResolverStructuredMapping:
    """ActionResolver 不读取 ConversationPhase，只基于结构化 frame 和上下文映射动作。"""

    def test_resolver_with_review_issues(self, volunteer_model, resolver):
        """包含 review issues 的场景解析。"""
        context = make_plan_context_inputs(
            phase="ordered",
            ordered_count=30,
            review_issues=[
                make_review_issue(
                    code="high_tuition",
                    scope_kind="item_replacement",
                    default_action_family="review_plan",
                ),
            ],
        )

        # 显式 remove 高收费 → remove_units；泛化处理应先走 review/FixProposal。
        frame = IntentFrame(
            task_layer="plan",
            topic="general",
            verb="remove",
            target=TargetSpec(review_issue_code="high_tuition"),
        )
        resolution = resolver.resolve(frame, context)
        assert resolution.action_family == "remove_units"

    def test_resolver_add_without_filters_goes_to_analyze(self, volunteer_model, resolver):
        """添加操作缺少筛选条件时进入 analyze 阶段（提示补充输入）。"""
        context = make_plan_context_inputs(phase="ordered", ordered_count=10)

        frame = IntentFrame(
            task_layer="plan",
            topic="general",
            verb="add",
        )
        resolution = resolver.resolve(frame, context)
        assert resolution.stage == "analyze"
        assert "selection_scope" in resolution.missing_inputs

    def test_resolver_generate_on_existing_plan_stays_generate(
        self, volunteer_model, resolver
    ):
        """已有方案时 verb=generate 仍保持 generate_plan（用户明确要重建）。"""
        context = make_plan_context_inputs(phase="ordered", ordered_count=30)

        frame = IntentFrame(
            task_layer="plan",
            topic="general",
            verb="generate",
        )
        resolution = resolver.resolve(frame, context)
        assert resolution.action_family == "generate_plan"

    def test_resolver_analyze_verb_on_existing_plan(
        self, volunteer_model, resolver
    ):
        """verb=analyze 时直接映射到 analyze_adjustment。"""
        context = make_plan_context_inputs(phase="ordered", ordered_count=30)

        frame = IntentFrame(
            task_layer="plan",
            topic="general",
            verb="analyze",
        )
        resolution = resolver.resolve(frame, context)
        assert resolution.action_family == "analyze_adjustment"

    def test_resolver_move_with_target(self, volunteer_model, resolver):
        """移动操作指定了目标位置。"""
        context = make_plan_context_inputs(phase="ordered", ordered_count=30)

        frame = IntentFrame(
            task_layer="plan",
            topic="general",
            verb="move",
            target=TargetSpec(volunteer_refs=["@5"], position=3),
        )
        resolution = resolver.resolve(frame, context)
        assert resolution.action_family == "move_unit"
        assert resolution.stage == "preview"


# ---------------------------------------------------------------------------
# 场景 7: Instructions assembler 与 pending 集成
# ---------------------------------------------------------------------------


class TestInstructionsIntegration:
    """验证 Instructions assembler 正确集成 pending 信息。"""

    def test_instructions_include_pending_info(self, volunteer_model):
        """conversation_phase.pending 信息出现在指令中。"""
        phase = ConversationPhase(
            state=PhaseState.PLAN_PREVIEWING,
            pending=PendingConfirmation(
                kind="plan_mutation",
                action_family="remove_units",
                preview_summary="将移除5个高收费志愿",
                execution_payload={"action_family": "remove_units", "stage": "apply"},
            ),
        )
        ctx = _make_run_context(
            volunteer_model=volunteer_model,
            planning_phase="ordered",
            ordered_total=30,
            conversation_phase=phase,
            chat_history=[{"role": "user", "content": "好的"}],
        )
        instructions = build_instructions(ctx)
        assert "remove_units" in instructions or "移除" in instructions

    def test_instructions_without_pending(self, volunteer_model):
        """无 pending 时指令中无待确认提示。"""
        ctx = _make_run_context(
            volunteer_model=volunteer_model,
            planning_phase="ordered",
            ordered_total=30,
        )
        instructions = build_instructions(ctx)
        assert "当前存在上一轮待确认的方案动作" not in instructions

    def test_instructions_with_conversation_phase_pending(self, volunteer_model):
        """使用新 ConversationPhase.pending 构建指令。"""
        phase = ConversationPhase(
            state=PhaseState.PLAN_PREVIEWING,
            pending=PendingConfirmation(
                kind="plan_mutation",
                action_family="add_units",
                preview_summary="添加5个志愿到排序方案",
                execution_payload={"action_family": "add_units", "stage": "apply"},
                created_turn=1,
            ),
        )
        ctx = _make_run_context(
            volunteer_model=volunteer_model,
            planning_phase="ordered",
            ordered_total=30,
            conversation_phase=phase,
            chat_history=[{"role": "user", "content": "确认"}],
        )
        instructions = build_instructions(ctx)
        assert "add_units" in instructions or "添加" in instructions


# ---------------------------------------------------------------------------
# 场景 8: Handler registry 与 resolver 联动
# ---------------------------------------------------------------------------


class TestRegistryResolverIntegration:
    """验证 ActionResolver 输出的 action_family 都在 registry 范围内。"""

    def test_all_resolver_families_are_known(self, resolver):
        """ActionResolver 产出的所有 action_family 都是合法值。"""
        known_families = {
            "query_state",
            "query_ordered",
            "query_candidates",
            "generate_plan",
            "analyze_adjustment",
            "preview_fix_proposal",
            "add_units",
            "remove_units",
            "move_unit",
            "move_ordered_unit",
            "replace_units",
            "remove_ordered_unit",
            "sort_ordered_plan",
            "regenerate_order",
            "review_plan",
        }
        phase = _make_phase(state=PhaseState.PLAN_IDLE)
        context = make_plan_context_inputs(phase="ordered", ordered_count=30)

        test_frames = [
            IntentFrame(task_layer="plan", topic="general", verb="query"),
            IntentFrame(task_layer="plan", topic="general", verb="review"),
            IntentFrame(task_layer="plan", topic="general", verb="compensate"),
            IntentFrame(
                task_layer="plan", topic="general", verb="remove",
                target=TargetSpec(volunteer_refs=["@1"]),
            ),
            IntentFrame(
                task_layer="plan", topic="general", verb="add",
                scope=ScopeSpec(school_tags=["985"]),
            ),
            IntentFrame(
                task_layer="plan", topic="general", verb="move",
                target=TargetSpec(volunteer_refs=["@1"], position=3),
            ),
            IntentFrame(task_layer="plan", topic="general", verb="reorder"),
            IntentFrame(task_layer="plan", topic="general", verb="generate"),
        ]
        for frame in test_frames:
            resolution = resolver.resolve(frame, context)
            if resolution.stage != "blocked":
                assert resolution.action_family in known_families or resolution.action_family in {
                    "set_preference", "remove_preference",
                }, f"Unknown family: {resolution.action_family} from verb={frame.verb}"


# ---------------------------------------------------------------------------
# 场景 10: 复合状态转换 — 非法转换被拒绝
# ---------------------------------------------------------------------------


class TestIllegalTransitions:
    """非法状态转换被正确拒绝。"""

    def test_plan_previewing_to_intent_previewing_not_allowed(self, volunteer_model):
        """PLAN_PREVIEWING → INTENT_PREVIEWING 不是直接合法转换。"""
        phase = _make_phase(state=PhaseState.PLAN_PREVIEWING)
        assert not phase.can_transition_to(PhaseState.INTENT_PREVIEWING)

    def test_intent_to_plan_previewing_allowed(self, volunteer_model):
        """INTENT_PREVIEWING → PLAN_PREVIEWING 允许。"""
        phase = _make_phase(state=PhaseState.INTENT_PREVIEWING)
        assert phase.can_transition_to(PhaseState.PLAN_PREVIEWING)

    def test_previewing_to_explore_allowed(self, volunteer_model):
        """从 previewing 可以回到 explore（用户切换话题）。"""
        phase = _make_phase(state=PhaseState.PLAN_PREVIEWING)
        assert phase.can_transition_to(PhaseState.EXPLORE)

    def test_set_pending_forces_previewing_state(self, volunteer_model):
        """set_pending 强制切换到对应的 previewing 状态。"""
        phase = _make_phase(state=PhaseState.PLAN_IDLE)
        phase.set_pending(PendingConfirmation(
            kind="plan_mutation",
            action_family="add_units",
            created_turn=0,
        ))
        assert phase.state == PhaseState.PLAN_PREVIEWING

        phase.clear_pending()
        phase.set_pending(PendingConfirmation(
            kind="intent_change",
            action_family="set_preference",
            created_turn=0,
        ))
        assert phase.state == PhaseState.INTENT_PREVIEWING
