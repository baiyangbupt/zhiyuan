package com.ytell.zhiyuan.service.biz;

import com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO;
import com.ytell.zhiyuan.model.dto.planning.DraftUnitDTO;
import com.ytell.zhiyuan.model.dto.planning.FixProposalActionDTO;
import com.ytell.zhiyuan.model.dto.planning.FixProposalDTO;
import com.ytell.zhiyuan.model.dto.planning.FixProposalStateDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedItemDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedUnitDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningUnitMajorDTO;
import com.ytell.zhiyuan.model.dto.planning.ReplacementPairDTO;
import com.ytell.zhiyuan.model.dto.planning.UserGoalFixProposalReq;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

public class UserGoalProposalBuilderTest {

    @Test
    void shouldBuildOnlyKeepPreviewFromCurrentPlanAndCandidatePool() {
        PlanningStateDTO state = state(12);
        state.getCandidatePoolState().getItems().add(candidate("v1", "中南大学", "临床医学", "医学", 92D));
        state.getCandidatePoolState().getItems().add(candidate("v2", "湖南师范大学", "汉语言文学", "文学", 88D));
        state.getCandidatePoolState().getItems().add(candidate("v3", "南华大学", "临床医学", "医学", 90D));
        state.getOrderedPlanState().getItems().add(ordered("v1", "中南大学", "临床医学", false));
        state.getOrderedPlanState().getItems().add(ordered("v2", "湖南师范大学", "汉语言文学", false));

        UserGoalFixProposalReq req = req("only_keep_scope", 12, scope("major", "临床医学"));
        req.setUserOriginalText("只保留临床医学");

        FixProposalStateDTO proposalState = UserGoalProposalBuilder.build(state, req);
        FixProposalDTO proposal = proposalState.getProposals().get(0);

        assertEquals("user_goal", proposalState.getProposalSource());
        assertEquals("ready", proposalState.getStatus());
        assertEquals("user_goal", proposal.getProposalSource());
        assertEquals("ready", proposal.getStatus());
        assertEquals("only_keep_scope", proposal.getStrategy());
        assertTrue(proposal.getRequiresConfirmation());
        assertTrue(proposal.getSummary().contains("当前方案中有 1 条符合"));
        assertTrue(proposal.getSummary().contains("本次能替换 1 条"));
        assertEquals(1, proposal.getActions().size());
        assertEquals("replace_volunteers", proposal.getActions().get(0).getActionType());
        assertEquals("v2", proposal.getActions().get(0).getRemoveVolunteerIds().get(0));
        assertEquals("v3", proposal.getActions().get(0).getCandidateVolunteerIds().get(0));
        ReplacementPairDTO pair = proposal.getActions().get(0).getReplacementPairs().get(0);
        assertEquals("v2", pair.getFromVolunteerId());
        assertEquals("v3", pair.getToVolunteerId());
        assertEquals("ready", proposal.getDryRunResult().getStatus());
        assertFalse(proposal.getImpact().contains("只读"));
        assertFalse(proposal.getDryRunResult().getMessage().contains("只读"));
        assertFalse(proposal.getDryRunResult().getMessage().contains("当前不会修改方案"));
        assertTrue(proposal.getDryRunResult().getWarnings().isEmpty());
    }

    @Test
    void shouldBuildInfoWhenMustIncludeScopeAlreadyExists() {
        PlanningStateDTO state = state(12);
        state.getCandidatePoolState().getItems().add(candidate("v1", "中南大学", "临床医学", "医学", 92D));
        state.getOrderedPlanState().getItems().add(ordered("v1", "中南大学", "临床医学", false));

        UserGoalFixProposalReq req = req("must_include_scope", 12, scope("major", "临床医学"));

        FixProposalDTO proposal = UserGoalProposalBuilder.build(state, req).getProposals().get(0);

        assertEquals("info", proposal.getStatus());
        assertEquals("must_include_scope", proposal.getStrategy());
        assertTrue(proposal.getSummary().contains("已经有 1 条"));
        assertTrue(proposal.getActions().isEmpty());
    }

    @Test
    void shouldBuildInfoWhenOnlyKeepScopeAlreadyCoversCurrentPlan() {
        PlanningStateDTO state = state(12);
        state.getCandidatePoolState().getItems().add(candidate("v1", "中南大学", "临床医学", "医学", 92D));
        state.getCandidatePoolState().getItems().add(candidate("v2", "南华大学", "临床医学", "医学", 90D));
        state.getOrderedPlanState().getItems().add(ordered("v1", "中南大学", "临床医学", false));
        state.getOrderedPlanState().getItems().add(ordered("v2", "南华大学", "临床医学", false));

        UserGoalFixProposalReq req = req("only_keep_scope", 12, scope("major", "临床医学"));

        FixProposalDTO proposal = UserGoalProposalBuilder.build(state, req).getProposals().get(0);

        assertEquals("info", proposal.getStatus());
        assertEquals("only_keep_scope", proposal.getStrategy());
        assertTrue(proposal.getSummary().contains("已经都在"));
        assertTrue(proposal.getActions().isEmpty());
    }

    @Test
    void shouldBuildMustIncludePreviewFromCandidatePoolWhenCurrentPlanMissingTarget() {
        PlanningStateDTO state = state(12);
        state.getCandidatePoolState().getItems().add(candidate("v1", "湖南师范大学", "汉语言文学", "文学", 88D));
        state.getCandidatePoolState().getItems().add(candidate("v2", "南华大学", "临床医学", "医学", 90D));
        state.getOrderedPlanState().getItems().add(ordered("v1", "湖南师范大学", "汉语言文学", false));

        UserGoalFixProposalReq req = req("must_include_scope", 12, scope("major", "临床医学"));

        FixProposalDTO proposal = UserGoalProposalBuilder.build(state, req).getProposals().get(0);

        assertEquals("ready", proposal.getStatus());
        assertTrue(proposal.getRequiresConfirmation());
        assertEquals("must_include_scope", proposal.getStrategy());
        assertEquals(1, proposal.getActions().size());
        assertEquals("add_volunteers", proposal.getActions().get(0).getActionType());
        assertEquals("v2", proposal.getActions().get(0).getCandidateVolunteerIds().get(0));
    }

    @Test
    void shouldBuildMustIncludeReplacementPreviewWhenCurrentPlanIsFull() {
        PlanningStateDTO state = state(12);
        state.getCandidatePoolState().setVolunteerModel("major");
        state.getCandidatePoolState().setRequiredCount(1);
        state.getCandidatePoolState().getItems().add(candidate("v1", "湖南师范大学", "汉语言文学", "文学", 72D));
        state.getCandidatePoolState().getItems().add(candidate("v2", "南华大学", "临床医学", "医学", 90D));
        state.getOrderedPlanState().getItems().add(ordered("v1", "湖南师范大学", "汉语言文学", false));

        UserGoalFixProposalReq req = req("must_include_scope", 12, scope("major", "临床医学"));

        FixProposalDTO proposal = UserGoalProposalBuilder.build(state, req).getProposals().get(0);

        assertEquals("ready", proposal.getStatus());
        assertTrue(proposal.getRequiresConfirmation());
        assertEquals(1, proposal.getActions().size());
        FixProposalActionDTO action = proposal.getActions().get(0);
        assertEquals("replace_volunteers", action.getActionType());
        assertEquals("v1", action.getRemoveVolunteerIds().get(0));
        assertEquals("v2", action.getCandidateVolunteerIds().get(0));
        assertFalse(proposal.getImpact().contains("只读"));
        assertFalse(proposal.getDryRunResult().getMessage().contains("当前不会修改方案"));
        assertTrue(proposal.getDryRunResult().getWarnings().isEmpty());
        assertEquals("v1", action.getReplacementPairs().get(0).getFromVolunteerId());
        assertEquals("v2", action.getReplacementPairs().get(0).getToVolunteerId());
    }

    @Test
    void shouldBuildExcludePreviewForCurrentPlanHits() {
        PlanningStateDTO state = state(12);
        state.getCandidatePoolState().getItems().add(candidate("v1", "南京大学", "金融学", "经济学", 91D));
        state.getCandidatePoolState().getItems().add(candidate("v2", "湖南师范大学", "汉语言文学", "文学", 88D));
        state.getOrderedPlanState().getItems().add(ordered("v1", "南京大学", "金融学", false));
        state.getOrderedPlanState().getItems().add(ordered("v2", "湖南师范大学", "汉语言文学", false));

        UserGoalFixProposalReq req = req("exclude_scope", 12, negativeScope("major", "金融学"));
        req.setUserOriginalText("不想学金融");

        FixProposalDTO proposal = UserGoalProposalBuilder.build(state, req).getProposals().get(0);

        assertEquals("ready", proposal.getStatus());
        assertTrue(proposal.getRequiresConfirmation());
        assertEquals("exclude_scope", proposal.getStrategy());
        assertTrue(proposal.getSummary().contains("有 1 条命中"));
        FixProposalActionDTO action = proposal.getActions().get(0);
        assertEquals("remove_volunteers", action.getActionType());
        assertEquals("v1", action.getRemoveVolunteerIds().get(0));
    }

    @Test
    void shouldBuildExcludeReplacementPreviewWhenAlternativeCandidateExists() {
        PlanningStateDTO state = state(12);
        state.getCandidatePoolState().getItems().add(candidate("v1", "南京大学", "金融学", "经济学", 91D));
        state.getCandidatePoolState().getItems().add(candidate("v2", "湖南师范大学", "汉语言文学", "文学", 88D));
        state.getCandidatePoolState().getItems().add(candidate("v3", "湘潭大学", "法学", "法学", 86D));
        state.getOrderedPlanState().getItems().add(ordered("v1", "南京大学", "金融学", false));
        state.getOrderedPlanState().getItems().add(ordered("v2", "湖南师范大学", "汉语言文学", false));

        UserGoalFixProposalReq req = req("exclude_scope", 12, negativeScope("major", "金融学"));

        FixProposalDTO proposal = UserGoalProposalBuilder.build(state, req).getProposals().get(0);

        assertEquals("ready", proposal.getStatus());
        assertTrue(proposal.getRequiresConfirmation());
        assertEquals(1, proposal.getActions().size());
        FixProposalActionDTO action = proposal.getActions().get(0);
        assertEquals("replace_volunteers", action.getActionType());
        assertEquals("v1", action.getRemoveVolunteerIds().get(0));
        assertEquals("v3", action.getCandidateVolunteerIds().get(0));
        assertFalse(proposal.getImpact().contains("只读"));
        assertFalse(proposal.getDryRunResult().getMessage().contains("当前不会修改方案"));
        assertTrue(proposal.getDryRunResult().getWarnings().isEmpty());
    }

    @Test
    void shouldBuildExcludePreviewForProgramTypeScope() {
        PlanningStateDTO state = state(12);
        CandidateItemDTO coop = candidate("v1", "青岛理工大学", "建筑学(中外合作办学)", "建筑类", 91D);
        coop.getReasonCodes().add("中外合作办学");
        CandidateItemDTO normal = candidate("v2", "湖南师范大学", "汉语言文学", "文学", 88D);
        CandidateItemDTO replacement = candidate("v3", "湘潭大学", "法学", "法学", 86D);
        state.getCandidatePoolState().getItems().add(coop);
        state.getCandidatePoolState().getItems().add(normal);
        state.getCandidatePoolState().getItems().add(replacement);
        state.getOrderedPlanState().getItems().add(ordered("v1", "青岛理工大学", "建筑学(中外合作办学)", false));
        state.getOrderedPlanState().getItems().add(ordered("v2", "湖南师范大学", "汉语言文学", false));

        UserGoalFixProposalReq req = req("exclude_scope", 12, negativeScope("program_type", "中外合作办学"));
        req.setUserOriginalText("中外合作的都排除掉，当前方案里有的话先移出去");

        FixProposalDTO proposal = UserGoalProposalBuilder.build(state, req).getProposals().get(0);

        assertEquals("ready", proposal.getStatus());
        assertTrue(proposal.getRequiresConfirmation());
        assertEquals("exclude_scope", proposal.getStrategy());
        FixProposalActionDTO action = proposal.getActions().get(0);
        assertEquals("replace_volunteers", action.getActionType());
        assertEquals("v1", action.getRemoveVolunteerIds().get(0));
        assertEquals("v3", action.getCandidateVolunteerIds().get(0));
    }

    @Test
    void shouldBuildTuitionBudgetReplacementPreviewFromCurrentPlanAndCandidatePool() {
        PlanningStateDTO state = state(12);
        CandidateItemDTO expensive = candidate("v1", "学校A", "金融学", "经济学", 91D);
        expensive.setTuitionPerYear(30000);
        CandidateItemDTO kept = candidate("v2", "学校B", "汉语言文学", "文学", 88D);
        kept.setTuitionPerYear(12000);
        CandidateItemDTO affordable = candidate("v3", "学校C", "法学", "法学", 86D);
        affordable.setTuitionPerYear(18000);
        state.getCandidatePoolState().getItems().add(expensive);
        state.getCandidatePoolState().getItems().add(kept);
        state.getCandidatePoolState().getItems().add(affordable);
        state.getOrderedPlanState().getItems().add(ordered("v1", "学校A", "金融学", false));
        state.getOrderedPlanState().getItems().add(ordered("v2", "学校B", "汉语言文学", false));

        UserGoalFixProposalReq req = new UserGoalFixProposalReq();
        req.setGoalType("tuition_budget_scope");
        req.setSourceVersionGuard(12);
        req.setUserOriginalText("预算上限20000元，超过的先移除再补充");
        req.setContext(java.util.Collections.singletonMap("maxTuitionPerYear", 20000));

        FixProposalDTO proposal = UserGoalProposalBuilder.build(state, req).getProposals().get(0);

        assertEquals("ready", proposal.getStatus());
        assertTrue(proposal.getRequiresConfirmation());
        assertEquals("tuition_budget_scope", proposal.getStrategy());
        assertTrue(proposal.getSummary().contains("学费超过 20000 元/年"));
        FixProposalActionDTO action = proposal.getActions().get(0);
        assertEquals("replace_volunteers", action.getActionType());
        assertEquals("v1", action.getRemoveVolunteerIds().get(0));
        assertEquals("v3", action.getCandidateVolunteerIds().get(0));
        assertEquals("v1", action.getReplacementPairs().get(0).getFromVolunteerId());
        assertEquals("v3", action.getReplacementPairs().get(0).getToVolunteerId());
    }

    @Test
    void shouldBuildInfoWhenTuitionBudgetAlreadySatisfied() {
        PlanningStateDTO state = state(12);
        CandidateItemDTO affordable = candidate("v1", "学校A", "金融学", "经济学", 91D);
        affordable.setTuitionPerYear(18000);
        state.getCandidatePoolState().getItems().add(affordable);
        state.getOrderedPlanState().getItems().add(ordered("v1", "学校A", "金融学", false));

        UserGoalFixProposalReq req = new UserGoalFixProposalReq();
        req.setGoalType("tuition_budget_scope");
        req.setSourceVersionGuard(12);
        req.setContext(java.util.Collections.singletonMap("maxTuitionPerYear", 20000));

        FixProposalDTO proposal = UserGoalProposalBuilder.build(state, req).getProposals().get(0);

        assertEquals("info", proposal.getStatus());
        assertEquals("tuition_budget_scope", proposal.getStrategy());
        assertTrue(proposal.getSummary().contains("没有发现学费超过 20000 元/年"));
        assertTrue(proposal.getActions().isEmpty());
    }

    @Test
    void shouldBlockTuitionBudgetWhenMaxTuitionMissing() {
        PlanningStateDTO state = state(12);
        UserGoalFixProposalReq req = new UserGoalFixProposalReq();
        req.setGoalType("tuition_budget_scope");
        req.setSourceVersionGuard(12);

        FixProposalDTO proposal = UserGoalProposalBuilder.build(state, req).getProposals().get(0);

        assertEquals("blocked", proposal.getStatus());
        assertEquals("tuition_budget_scope", proposal.getStrategy());
        assertEquals("user_goal_unclear", proposal.getBlockingReasonCodes().get(0));
        assertTrue(proposal.getSummary().contains("学费上限"));
    }

    @Test
    void shouldMatchMajorGroupInnerMajorInUserGoalPreview() {
        PlanningStateDTO state = state(12);
        state.getCandidatePoolState().setVolunteerModel("majorGroup");
        state.getCandidatePoolState().getItems().add(candidate("v1", "湖南大学第110组", "工商管理类", "管理学", 91D));
        state.getCandidatePoolState().getItems().add(candidate("v2", "湖南大学第110组", "临床医学", "医学", 90D));
        DraftUnitDTO unit = new DraftUnitDTO();
        unit.setUnitId("u1");
        unit.setSchoolName("湖南大学第110组");
        unit.getMajorItems().add(unitMajor("v1", "工商管理类"));
        unit.getMajorItems().add(unitMajor("v2", "临床医学"));
        state.getWorkingPlanState().getUnits().add(unit);

        UserGoalFixProposalReq req = req("exclude_scope", 12, negativeScope("major", "工商管理"));

        FixProposalDTO proposal = UserGoalProposalBuilder.build(state, req).getProposals().get(0);

        assertEquals("ready", proposal.getStatus());
        assertTrue(proposal.getRequiresConfirmation());
        assertEquals("exclude_scope", proposal.getStrategy());
        assertEquals("v1", proposal.getActions().get(0).getRemoveVolunteerIds().get(0));
        assertEquals("u1", proposal.getActions().get(0).getRemoveUnitIds().get(0));
    }

    @Test
    void shouldBuildMajorGroupReplacementPairWithUnitIds() {
        PlanningStateDTO state = state(12);
        state.getCandidatePoolState().setVolunteerModel("majorGroup");
        state.getCandidatePoolState().setRequiredCount(1);
        state.getCandidatePoolState().getItems().add(candidate("v1", "湖南大学第110组", "工商管理类", "管理学", 91D));
        state.getCandidatePoolState().getItems().get(0).setPlanSchoolDataId("u1");
        state.getCandidatePoolState().getItems().add(candidate("v2", "中南大学第101组", "临床医学", "医学", 90D));
        state.getCandidatePoolState().getItems().get(1).setPlanSchoolDataId("u2");
        OrderedUnitDTO unit = new OrderedUnitDTO();
        unit.setUnitId("u1");
        unit.setSchoolName("湖南大学第110组");
        unit.getMajorItems().add(unitMajor("v1", "工商管理类"));
        state.getOrderedPlanState().getUnits().add(unit);

        UserGoalFixProposalReq req = req("only_keep_scope", 12, scope("major", "临床医学"));

        FixProposalDTO proposal = UserGoalProposalBuilder.build(state, req).getProposals().get(0);

        assertEquals("ready", proposal.getStatus());
        assertTrue(proposal.getRequiresConfirmation());
        FixProposalActionDTO action = proposal.getActions().get(0);
        assertEquals("replace_volunteers", action.getActionType());
        assertEquals("u1", action.getRemoveUnitIds().get(0));
        assertEquals("u2", action.getCandidateUnitIds().get(0));
        assertEquals("u1", action.getReplacementPairs().get(0).getFromUnitId());
        assertEquals("u2", action.getReplacementPairs().get(0).getToUnitId());
    }

    @Test
    void shouldSkipCurrentUnitCandidateWhenBuildingMajorGroupMustIncludeReplacement() {
        PlanningStateDTO state = state(12);
        state.getCandidatePoolState().setVolunteerModel("majorGroup");
        state.getCandidatePoolState().setRequiredCount(1);
        state.getCandidatePoolState().getItems().add(candidate("v1", "湖南大学第110组", "工商管理类", "管理学", 91D));
        state.getCandidatePoolState().getItems().get(0).setPlanSchoolDataId("u1");
        state.getCandidatePoolState().getItems().add(candidate("v2", "湖南大学第110组", "临床医学", "医学", 95D));
        state.getCandidatePoolState().getItems().get(1).setPlanSchoolDataId("u1");
        state.getCandidatePoolState().getItems().add(candidate("v3", "中南大学第101组", "临床医学", "医学", 90D));
        state.getCandidatePoolState().getItems().get(2).setPlanSchoolDataId("u2");
        OrderedUnitDTO unit = new OrderedUnitDTO();
        unit.setUnitId("u1");
        unit.setSchoolName("湖南大学第110组");
        unit.getMajorItems().add(unitMajor("v1", "工商管理类"));
        state.getOrderedPlanState().getUnits().add(unit);

        UserGoalFixProposalReq req = req("must_include_scope", 12, scope("major", "临床医学"));

        FixProposalDTO proposal = UserGoalProposalBuilder.build(state, req).getProposals().get(0);

        assertEquals("ready", proposal.getStatus());
        assertTrue(proposal.getRequiresConfirmation());
        FixProposalActionDTO action = proposal.getActions().get(0);
        assertEquals("replace_volunteers", action.getActionType());
        assertEquals("v3", action.getCandidateVolunteerIds().get(0));
        assertEquals("u2", action.getCandidateUnitIds().get(0));
        assertEquals("v3", action.getReplacementPairs().get(0).getToVolunteerId());
    }

    @Test
    void shouldBlockOnlyKeepWhenScopeIsMissing() {
        PlanningStateDTO state = state(12);
        UserGoalFixProposalReq req = new UserGoalFixProposalReq();
        req.setGoalType("only_keep_scope");
        req.setUserOriginalText("只保留临床医学");
        req.setSourceVersionGuard(12);

        FixProposalStateDTO proposalState = UserGoalProposalBuilder.build(state, req);

        assertEquals("user_goal", proposalState.getProposalSource());
        assertEquals("blocked_or_info", proposalState.getStatus());
        assertEquals(Integer.valueOf(12), proposalState.getSourceVersionGuard());
        assertEquals(1, proposalState.getProposals().size());

        FixProposalDTO proposal = proposalState.getProposals().get(0);
        assertTrue(proposal.getProposalId().startsWith("ugp_"));
        assertEquals("user_goal", proposal.getProposalSource());
        assertEquals("blocked", proposal.getStatus());
        assertEquals("cannot_satisfy", proposal.getStrategy());
        assertFalse(proposal.getRequiresConfirmation());
        assertTrue(proposal.getActions().isEmpty());
        assertEquals("user_goal_unclear", proposal.getBlockingReasonCodes().get(0));
        assertEquals("proposal_engine", proposal.getCandidateShortages().get(0).getScope());
        assertTrue(proposal.getSummary().contains("目标还不够明确"));
    }

    @Test
    void shouldBlockWhenScopeResolutionNeedsClarification() {
        PlanningStateDTO state = state(12);
        state.getCandidatePoolState().getItems().add(candidate("v1", "中南大学", "临床医学", "医学", 92D));
        state.getOrderedPlanState().getItems().add(ordered("v1", "中南大学", "临床医学", false));
        UserGoalFixProposalReq.ScopeDTO scope = scope("major", "医学");
        scope.setResolutionStatus("multiple_match");
        UserGoalFixProposalReq req = req("only_keep_scope", 12, scope);

        FixProposalDTO proposal = UserGoalProposalBuilder.build(state, req).getProposals().get(0);

        assertEquals("blocked", proposal.getStatus());
        assertEquals("only_keep_scope", proposal.getStrategy());
        assertEquals("user_goal_entity_needs_clarification", proposal.getBlockingReasonCodes().get(0));
        assertTrue(proposal.getActions().isEmpty());
        assertTrue(proposal.getBlockingReason().contains("还没有对应到明确范围"));
    }

    @Test
    void shouldBlockWhenScopeEntityTypeIsMissing() {
        PlanningStateDTO state = state(12);
        state.getCandidatePoolState().getItems().add(candidate("v1", "中南大学", "临床医学", "医学", 92D));
        state.getOrderedPlanState().getItems().add(ordered("v1", "中南大学", "临床医学", false));
        UserGoalFixProposalReq.ScopeDTO scope = new UserGoalFixProposalReq.ScopeDTO();
        scope.setNormalizedName("临床医学");
        UserGoalFixProposalReq req = req("only_keep_scope", 12, scope);

        FixProposalDTO proposal = UserGoalProposalBuilder.build(state, req).getProposals().get(0);

        assertEquals("blocked", proposal.getStatus());
        assertEquals("user_goal_entity_needs_clarification", proposal.getBlockingReasonCodes().get(0));
        assertTrue(proposal.getActions().isEmpty());
    }

    @Test
    void shouldBlockWhenSourceVersionGuardMismatch() {
        PlanningStateDTO state = state(13);
        UserGoalFixProposalReq req = new UserGoalFixProposalReq();
        req.setGoalType("exclude_scope");
        req.setSourceVersionGuard(12);

        FixProposalDTO proposal = UserGoalProposalBuilder.build(state, req).getProposals().get(0);

        assertEquals("source_version_mismatch", proposal.getBlockingReasonCodes().get(0));
        assertTrue(proposal.getBlockingReason().contains("方案已经变化"));
        assertTrue(proposal.getActions().isEmpty());
    }

    @Test
    void shouldBlockWhenGoalTypeIsMissing() {
        PlanningStateDTO state = state(14);
        UserGoalFixProposalReq req = new UserGoalFixProposalReq();
        req.setUserOriginalText("帮我调整一下");

        FixProposalDTO proposal = UserGoalProposalBuilder.build(state, req).getProposals().get(0);

        assertEquals("user_goal_unclear", proposal.getBlockingReasonCodes().get(0));
        assertTrue(proposal.getBlockingReason().contains("目标还不够明确"));
        assertFalse(proposal.getRequiresConfirmation());
    }

    private PlanningStateDTO state(Integer version) {
        PlanningStateDTO state = new PlanningStateDTO();
        state.setSessionId(100L);
        state.setVersion(version);
        return state;
    }

    private UserGoalFixProposalReq req(String goalType, Integer sourceVersionGuard, UserGoalFixProposalReq.ScopeDTO scope) {
        UserGoalFixProposalReq req = new UserGoalFixProposalReq();
        req.setGoalType(goalType);
        req.setSourceVersionGuard(sourceVersionGuard);
        if ("exclude_scope".equals(goalType)) {
            req.getNegativeScopes().add(scope);
        } else {
            req.getTargetScopes().add(scope);
        }
        return req;
    }

    private UserGoalFixProposalReq.ScopeDTO scope(String entityType, String normalizedName) {
        UserGoalFixProposalReq.ScopeDTO scope = new UserGoalFixProposalReq.ScopeDTO();
        scope.setEntityType(entityType);
        scope.setNormalizedName(normalizedName);
        return scope;
    }

    private UserGoalFixProposalReq.ScopeDTO negativeScope(String entityType, String normalizedName) {
        return scope(entityType, normalizedName);
    }

    private CandidateItemDTO candidate(String volunteerId, String schoolName, String majorName, String majorCategory, Double finalScore) {
        CandidateItemDTO candidate = new CandidateItemDTO();
        candidate.setVolunteerId(volunteerId);
        candidate.setPlanSchoolDataId("u_" + volunteerId);
        candidate.setSchoolName(schoolName);
        candidate.setDisplaySchoolName(schoolName);
        candidate.setMajorName(majorName);
        candidate.setMajorCategory(majorCategory);
        candidate.setFinalScore(finalScore);
        candidate.setAdmissionRatio(50D);
        candidate.setIntentScore(40D);
        return candidate;
    }

    private OrderedItemDTO ordered(String volunteerId, String schoolName, String majorName, boolean locked) {
        OrderedItemDTO item = new OrderedItemDTO();
        item.setVolunteerId(volunteerId);
        item.setSchoolName(schoolName);
        item.setMajorName(majorName);
        item.setLocked(locked);
        return item;
    }

    private PlanningUnitMajorDTO unitMajor(String volunteerId, String majorName) {
        PlanningUnitMajorDTO major = new PlanningUnitMajorDTO();
        major.setVolunteerId(volunteerId);
        major.setMajorName(majorName);
        return major;
    }
}
