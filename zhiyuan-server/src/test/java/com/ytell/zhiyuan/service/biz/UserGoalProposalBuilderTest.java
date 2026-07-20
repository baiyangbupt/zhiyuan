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
import com.ytell.zhiyuan.model.dto.planning.PriorityRuleDTO;
import com.ytell.zhiyuan.model.dto.planning.ReplacementPairDTO;
import com.ytell.zhiyuan.model.dto.planning.TierCountRangeDTO;
import com.ytell.zhiyuan.model.dto.planning.TierQuotaGoalDTO;
import com.ytell.zhiyuan.model.dto.planning.TierQuotaGoalRequestDTO;
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
        assertTrue(proposal.getActions().get(0).getDetail().contains("湖南师范大学-汉语言文学"));
        assertTrue(proposal.getActions().get(0).getDetail().contains("南华大学-临床医学"));
        assertTrue(proposal.getActions().get(0).getDetail().contains("->"));
        assertEquals("ready", proposal.getDryRunResult().getStatus());
        assertFalse(proposal.getImpact().contains("只读"));
        assertFalse(proposal.getDryRunResult().getMessage().contains("只读"));
        assertFalse(proposal.getDryRunResult().getMessage().contains("当前不会修改方案"));
        assertTrue(proposal.getDryRunResult().getWarnings().isEmpty());
    }

    @Test
    void shouldBuildOnlyKeepPreviewForRegionAreaScope() {
        PlanningStateDTO state = state(12);
        CandidateItemDTO southCurrent = candidate("v1", "广州新华学院", "金融工程", "金融学类", 92D);
        southCurrent.setProvinceName("广东");
        CandidateItemDTO northCurrent = candidate("v2", "天津仁爱学院", "金融工程", "金融学类", 88D);
        northCurrent.setProvinceName("天津");
        CandidateItemDTO southCandidate = candidate("v3", "海南热带海洋学院", "汉语言文学", "文学", 90D);
        southCandidate.setProvinceName("海南");
        state.getCandidatePoolState().getItems().add(southCurrent);
        state.getCandidatePoolState().getItems().add(northCurrent);
        state.getCandidatePoolState().getItems().add(southCandidate);
        state.getOrderedPlanState().getItems().add(ordered("v1", "广州新华学院", "金融工程", false));
        state.getOrderedPlanState().getItems().add(ordered("v2", "天津仁爱学院", "金融工程", false));

        UserGoalFixProposalReq.ScopeDTO scope = scope("region", "南方");
        scope.setScopeLevel("area");
        UserGoalFixProposalReq req = req("only_keep_scope", 12, scope);
        req.setUserOriginalText("孩子就想去南方，北方先别考虑");

        FixProposalDTO proposal = UserGoalProposalBuilder.build(state, req).getProposals().get(0);

        assertEquals("ready", proposal.getStatus());
        assertEquals("only_keep_scope", proposal.getStrategy());
        assertTrue(proposal.getSummary().contains("符合“南方”"));
        assertFalse(proposal.getSummary().contains("广东、广西、海南"));
        FixProposalActionDTO action = proposal.getActions().get(0);
        assertEquals("replace_volunteers", action.getActionType());
        assertEquals("v2", action.getRemoveVolunteerIds().get(0));
        assertEquals("v3", action.getCandidateVolunteerIds().get(0));
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
    void shouldPreferIntentScoreForMustIncludeCandidatePreview() {
        PlanningStateDTO state = state(12);
        CandidateItemDTO current = candidate("v1", "湖南师范大学", "汉语言文学", "文学", 88D);
        CandidateItemDTO highRecommendLowIntent = candidate("v2", "学校A", "法学", "法学类", 98D);
        highRecommendLowIntent.setIntentScore(20D);
        highRecommendLowIntent.setAdmissionRatio(80D);
        CandidateItemDTO lowerRecommendHighIntent = candidate("v3", "学校B", "法学", "法学类", 86D);
        lowerRecommendHighIntent.setIntentScore(95D);
        lowerRecommendHighIntent.setAdmissionRatio(70D);
        state.getCandidatePoolState().getItems().add(current);
        state.getCandidatePoolState().getItems().add(highRecommendLowIntent);
        state.getCandidatePoolState().getItems().add(lowerRecommendHighIntent);
        state.getOrderedPlanState().getItems().add(ordered("v1", "湖南师范大学", "汉语言文学", false));

        UserGoalFixProposalReq req = req("must_include_scope", 12, scope("major", "法学"));

        FixProposalDTO proposal = UserGoalProposalBuilder.build(state, req).getProposals().get(0);

        assertEquals("ready", proposal.getStatus());
        assertEquals("add_volunteers", proposal.getActions().get(0).getActionType());
        assertEquals("v3", proposal.getActions().get(0).getCandidateVolunteerIds().get(0));
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
    void shouldPreferIntentScoreForFullPlanReplacementPreviewAfterHardMatch() {
        PlanningStateDTO state = state(12);
        state.getCandidatePoolState().setVolunteerModel("major");
        state.getCandidatePoolState().setRequiredCount(1);
        CandidateItemDTO current = candidate("v1", "湖南师范大学", "汉语言文学", "文学", 88D);
        current.setIntentScore(70D);
        CandidateItemDTO highRecommendLowIntent = candidate("v2", "学校A", "法学", "法学类", 99D);
        highRecommendLowIntent.setIntentScore(20D);
        highRecommendLowIntent.setAdmissionRatio(90D);
        CandidateItemDTO lowerRecommendHighIntent = candidate("v3", "学校B", "法学", "法学类", 86D);
        lowerRecommendHighIntent.setIntentScore(95D);
        lowerRecommendHighIntent.setAdmissionRatio(70D);
        state.getCandidatePoolState().getItems().add(current);
        state.getCandidatePoolState().getItems().add(highRecommendLowIntent);
        state.getCandidatePoolState().getItems().add(lowerRecommendHighIntent);
        state.getOrderedPlanState().getItems().add(ordered("v1", "湖南师范大学", "汉语言文学", false));

        UserGoalFixProposalReq req = req("must_include_scope", 12, scope("major", "法学"));

        FixProposalDTO proposal = UserGoalProposalBuilder.build(state, req).getProposals().get(0);

        assertEquals("ready", proposal.getStatus());
        FixProposalActionDTO action = proposal.getActions().get(0);
        assertEquals("replace_volunteers", action.getActionType());
        assertEquals("v3", action.getCandidateVolunteerIds().get(0));
        assertEquals("v3", action.getReplacementPairs().get(0).getToVolunteerId());
        assertTrue(action.getDetail().contains("湖南师范大学-汉语言文学"));
        assertTrue(action.getDetail().contains("学校B-法学"));
        assertTrue(action.getDetail().contains("->"));
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
    void shouldNotLimitReplacementPairsByPreviewCandidateLimitForProgramTypeScope() {
        PlanningStateDTO state = state(12);
        for (int index = 1; index <= 6; index++) {
            String volunteerId = "coop" + index;
            CandidateItemDTO coop = candidate(volunteerId, "中外合作学校" + index,
                    "专业" + index + "(中外合作办学)", "工学", 90D - index);
            coop.getReasonCodes().add("中外合作办学");
            state.getCandidatePoolState().getItems().add(coop);
            state.getOrderedPlanState().getItems().add(ordered(volunteerId, coop.getSchoolName(), coop.getMajorName(), false));
        }
        for (int index = 1; index <= 6; index++) {
            state.getCandidatePoolState().getItems().add(candidate("normal" + index, "普通学校" + index,
                    "普通专业" + index, "工学", 80D - index));
        }

        UserGoalFixProposalReq req = req("exclude_scope", 12, negativeScope("program_type", "中外合作办学"));
        req.setUserOriginalText("不要中外合作");

        FixProposalDTO proposal = UserGoalProposalBuilder.build(state, req).getProposals().get(0);

        assertEquals("ready", proposal.getStatus());
        assertTrue(proposal.getSummary().contains("当前方案里有 6 条命中"));
        assertTrue(proposal.getSummary().contains("本次能替换 6 条"));
        FixProposalActionDTO action = proposal.getActions().get(0);
        assertEquals("replace_volunteers", action.getActionType());
        assertEquals(6, action.getReplacementPairs().size());
        assertEquals(6, action.getRemoveVolunteerIds().size());
        assertEquals(6, action.getCandidateVolunteerIds().size());
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
    void shouldBuildExactFillToCountPreviewForMajorMode() {
        PlanningStateDTO state = state(12);
        state.getCandidatePoolState().setVolunteerModel("major");
        state.getCandidatePoolState().getItems().add(candidate("v1", "学校1", "专业1", "类别1", 80D));
        state.getCandidatePoolState().getItems().add(candidate("v2", "学校2", "专业2", "类别2", 81D));
        state.getCandidatePoolState().getItems().add(candidate("v3", "学校3", "专业3", "类别3", 95D));
        state.getCandidatePoolState().getItems().add(candidate("v4", "学校4", "专业4", "类别4", 90D));
        state.getOrderedPlanState().getItems().add(ordered("v1", "学校1", "专业1", false));
        state.getOrderedPlanState().getItems().add(ordered("v2", "学校2", "专业2", false));
        UserGoalFixProposalReq req = new UserGoalFixProposalReq();
        req.setGoalType("fill_to_count");
        req.setTargetCount(4);
        req.setSourceVersionGuard(12);

        FixProposalDTO proposal = UserGoalProposalBuilder.build(state, req).getProposals().get(0);

        assertEquals("ready", proposal.getStatus());
        assertEquals("fill_missing_count", proposal.getStrategy());
        assertTrue(proposal.getRequiresConfirmation());
        assertEquals(1, proposal.getActions().size());
        FixProposalActionDTO action = proposal.getActions().get(0);
        assertEquals("fill_total_count", action.getActionType());
        assertEquals(2, action.getVolunteerIds().size());
        assertEquals("v3", action.getVolunteerIds().get(0));
        assertEquals(Integer.valueOf(2), proposal.getDryRunResult().getBeforeVolunteerTotal());
        assertEquals(Integer.valueOf(4), proposal.getDryRunResult().getAfterVolunteerTotal());
        assertTrue(proposal.getCanonicalObjectiveDigest().matches("[0-9a-f]{64}"));
        assertEquals("ojalgo-48.4.2-m2", proposal.getSolverVersion());
        assertTrue(proposal.getSolverInputDigest().matches("[0-9a-f]{64}"));
        assertEquals(java.util.Arrays.asList("v1", "v2", "v3", "v4"),
                proposal.getSolverResult().getSelectedEntityIds());
    }

    @Test
    void shouldCombineFillRequirementsAndPriorityInOneProposal() {
        PlanningStateDTO state = state(12);
        state.getCandidatePoolState().setVolunteerModel("major");
        CandidateItemDTO beijing = candidate("v1", "北京学校", "数学", "理学", 90D);
        beijing.setProvinceName("北京");
        beijing.setTier("稳");
        beijing.setSchoolNature("公办");
        CandidateItemDTO shanghai = candidate("v2", "上海学校", "法学", "法学", 89D);
        shanghai.setProvinceName("上海");
        shanghai.setTier("稳");
        shanghai.setSchoolNature("公办");
        CandidateItemDTO tianjin = candidate("v3", "天津学校", "金融学", "经济学", 88D);
        tianjin.setProvinceName("天津");
        tianjin.setTier("稳");
        tianjin.setSchoolNature("公办");
        state.getCandidatePoolState().getItems().addAll(
                java.util.Arrays.asList(beijing, shanghai, tianjin));
        state.getOrderedPlanState().getItems().add(orderedWithTier("v1", "北京学校", "数学", "稳"));
        state.getOrderedPlanState().getItems().add(orderedWithTier("v2", "上海学校", "法学", "稳"));
        UserGoalFixProposalReq req = new UserGoalFixProposalReq();
        req.setGoalType("fill_to_count");
        req.setTargetCount(3);
        req.setSourceVersionGuard(12);
        req.getRequirements().add(requirement("exclude", "school", "school_nature", "民办"));
        req.getPriorityRules().add(priorityRule("region", "province", "上海"));

        FixProposalDTO proposal = UserGoalProposalBuilder.build(state, req).getProposals().get(0);

        assertEquals("ready", proposal.getStatus());
        assertEquals("fill_missing_count", proposal.getStrategy());
        assertEquals(2, proposal.getActions().size());
        assertEquals("fill_total_count", proposal.getActions().get(0).getActionType());
        assertEquals("reorder_volunteers", proposal.getActions().get(1).getActionType());
        assertEquals(Integer.valueOf(1), proposal.getDryRunResult().getPriorityMatchedCount());
        assertEquals(Integer.valueOf(1), proposal.getDryRunResult().getPriorityBeforeInversionCount());
        assertEquals(Integer.valueOf(0), proposal.getDryRunResult().getPriorityAfterInversionCount());
        assertTrue(proposal.getSummary().contains("同档逆序"));
        assertTrue(proposal.getSummary().contains("排除民办（院校性质）"));
        assertTrue(proposal.getSummary().contains("上海（地域）"));
    }

    @Test
    void shouldAllowPriorityTargetIntroducedByFillCandidate() {
        PlanningStateDTO state = state(12);
        state.getCandidatePoolState().setVolunteerModel("major");
        CandidateItemDTO beijing = candidate("v1", "北京学校", "数学", "理学", 90D);
        beijing.setProvinceName("北京");
        beijing.setTier("稳");
        CandidateItemDTO shanghai = candidate("v2", "上海学校", "法学", "法学", 89D);
        shanghai.setProvinceName("上海");
        shanghai.setTier("稳");
        state.getCandidatePoolState().getItems().addAll(java.util.Arrays.asList(beijing, shanghai));
        state.getOrderedPlanState().getItems().add(orderedWithTier("v1", "北京学校", "数学", "稳"));
        UserGoalFixProposalReq req = new UserGoalFixProposalReq();
        req.setGoalType("fill_to_count");
        req.setTargetCount(2);
        req.setSourceVersionGuard(12);
        req.getPriorityRules().add(priorityRule("region", "province", "上海"));

        FixProposalDTO proposal = UserGoalProposalBuilder.build(state, req).getProposals().get(0);

        assertEquals("ready", proposal.getStatus());
        assertEquals(Integer.valueOf(1), proposal.getDryRunResult().getPriorityMatchedCount());
        assertEquals(Integer.valueOf(1), proposal.getDryRunResult().getPriorityBeforeInversionCount());
    }

    @Test
    void shouldBlockWhenProjectedRequirementsRemoveEveryPriorityMatch() {
        PlanningStateDTO state = state(12);
        state.getCandidatePoolState().setVolunteerModel("major");
        CandidateItemDTO shanghaiPrivate = candidate("v1", "上海民办学校", "法学", "法学", 90D);
        shanghaiPrivate.setProvinceName("上海");
        shanghaiPrivate.setSchoolNature("民办");
        shanghaiPrivate.setTier("稳");
        CandidateItemDTO beijingPublic = candidate("v2", "北京公办学校", "数学", "理学", 89D);
        beijingPublic.setProvinceName("北京");
        beijingPublic.setSchoolNature("公办");
        beijingPublic.setTier("稳");
        state.getCandidatePoolState().getItems().addAll(
                java.util.Arrays.asList(shanghaiPrivate, beijingPublic));
        state.getOrderedPlanState().getItems().add(
                orderedWithTier("v1", "上海民办学校", "法学", "稳"));
        UserGoalFixProposalReq req = new UserGoalFixProposalReq();
        req.setGoalType("fill_to_count");
        req.setTargetCount(1);
        req.setSourceVersionGuard(12);
        req.getRequirements().add(requirement("exclude", "school", "school_nature", "民办"));
        req.getPriorityRules().add(priorityRule("region", "province", "上海"));

        FixProposalDTO proposal = UserGoalProposalBuilder.build(state, req).getProposals().get(0);

        assertEquals("blocked", proposal.getStatus());
        assertEquals("priority_target_not_in_plan", proposal.getBlockingReasonCodes().get(0));
        assertTrue(proposal.getBlockingReason().contains("投影后的最终方案"));
    }

    @Test
    void shouldProjectCompleteMajorGroupForFillPriorityComposite() {
        PlanningStateDTO state = state(12);
        state.getCandidatePoolState().setVolunteerModel("majorGroup");
        CandidateItemDTO current = candidate("v1", "北京学校", "数学", "理学", 90D);
        current.setPlanSchoolDataId("u1");
        current.setProvinceName("北京");
        current.setTier("稳");
        CandidateItemDTO shanghaiA = candidate("v2", "上海学校", "法学", "法学", 89D);
        shanghaiA.setPlanSchoolDataId("u2");
        shanghaiA.setProvinceName("上海");
        shanghaiA.setTier("稳");
        CandidateItemDTO shanghaiB = candidate("v2b", "上海学校", "金融学", "经济学", 88D);
        shanghaiB.setPlanSchoolDataId("u2");
        shanghaiB.setProvinceName("上海");
        shanghaiB.setTier("稳");
        state.getCandidatePoolState().getItems().addAll(
                java.util.Arrays.asList(current, shanghaiA, shanghaiB));
        OrderedUnitDTO currentUnit = new OrderedUnitDTO();
        currentUnit.setUnitId("u1");
        currentUnit.setTier("稳");
        currentUnit.setProvinceName("北京");
        currentUnit.getMajorItems().add(unitMajor("v1", "数学"));
        state.getOrderedPlanState().getUnits().add(currentUnit);
        UserGoalFixProposalReq req = new UserGoalFixProposalReq();
        req.setGoalType("fill_to_count");
        req.setTargetCount(2);
        req.setSourceVersionGuard(12);
        req.getPriorityRules().add(priorityRule("region", "province", "上海"));

        FixProposalDTO proposal = UserGoalProposalBuilder.build(state, req).getProposals().get(0);

        assertEquals("ready", proposal.getStatus());
        assertEquals(2, proposal.getActions().size());
        assertEquals(java.util.Arrays.asList("u2"), proposal.getActions().get(0).getCandidateUnitIds());
        assertEquals("reorder_volunteers", proposal.getActions().get(1).getActionType());
        assertEquals("unit", proposal.getActions().get(1).getLevel());
        assertEquals(Integer.valueOf(1), proposal.getDryRunResult().getPriorityMatchedCount());
        assertEquals(Integer.valueOf(1), proposal.getDryRunResult().getPriorityBeforeInversionCount());
    }

    @Test
    void shouldReturnInfoWhenFillTargetAlreadyReached() {
        PlanningStateDTO state = state(12);
        state.getCandidatePoolState().setVolunteerModel("major");
        state.getCandidatePoolState().getItems().add(candidate("v1", "学校1", "专业1", "类别1", 80D));
        state.getCandidatePoolState().getItems().add(candidate("v2", "学校2", "专业2", "类别2", 81D));
        state.getOrderedPlanState().getItems().add(ordered("v1", "学校1", "专业1", false));
        state.getOrderedPlanState().getItems().add(ordered("v2", "学校2", "专业2", false));
        UserGoalFixProposalReq req = new UserGoalFixProposalReq();
        req.setGoalType("fill_to_count");
        req.setTargetCount(2);
        req.setSourceVersionGuard(12);

        FixProposalDTO proposal = UserGoalProposalBuilder.build(state, req).getProposals().get(0);

        assertEquals("info", proposal.getStatus());
        assertFalse(proposal.getRequiresConfirmation());
        assertTrue(proposal.getActions().isEmpty());
        assertEquals("no_change", proposal.getSolverResult().getStatus());
        assertEquals(java.util.Arrays.asList("v1", "v2"),
                proposal.getSolverResult().getSelectedEntityIds());
    }

    @Test
    void shouldBlockFillRatherThanCreatePartialPreviewWhenCandidatesAreInsufficient() {
        PlanningStateDTO state = state(12);
        state.getCandidatePoolState().setVolunteerModel("major");
        state.getCandidatePoolState().getItems().add(candidate("v1", "学校1", "专业1", "类别1", 80D));
        state.getCandidatePoolState().getItems().add(candidate("v2", "学校2", "专业2", "类别2", 81D));
        state.getOrderedPlanState().getItems().add(ordered("v1", "学校1", "专业1", false));
        UserGoalFixProposalReq req = new UserGoalFixProposalReq();
        req.setGoalType("fill_to_count");
        req.setTargetCount(3);
        req.setSourceVersionGuard(12);

        FixProposalDTO proposal = UserGoalProposalBuilder.build(state, req).getProposals().get(0);

        assertEquals("blocked", proposal.getStatus());
        assertEquals("candidate_pool_insufficient", proposal.getBlockingReasonCodes().get(0));
        assertTrue(proposal.getActions().isEmpty());
        assertTrue(proposal.getBlockingReason().contains("不能生成部分执行预览"));
    }

    @Test
    void shouldAttributeFillShortageToConfirmedHardConstraints() {
        PlanningStateDTO state = state(12);
        state.getCandidatePoolState().setVolunteerModel("major");
        state.getCandidatePoolState().getItems().add(candidate("v1", "学校1", "数学", "理学", 80D));
        state.getCandidatePoolState().getItems().add(candidate("v2", "学校2", "法学", "法学", 90D));
        state.getCandidatePoolState().getItems().add(candidate("v3", "学校3", "金融学", "经济学", 88D));
        state.getOrderedPlanState().getItems().add(ordered("v1", "学校1", "数学", false));
        state.getConstraintState().getHardConstraints().setMustExcludeMajors(
                java.util.Arrays.asList("法学", "金融学"));
        UserGoalFixProposalReq req = new UserGoalFixProposalReq();
        req.setGoalType("fill_to_count");
        req.setTargetCount(3);
        req.setSourceVersionGuard(12);

        FixProposalDTO proposal = UserGoalProposalBuilder.build(state, req).getProposals().get(0);

        assertEquals("blocked", proposal.getStatus());
        assertEquals("hard_constraints_candidate_insufficient", proposal.getBlockingReasonCodes().get(0));
        assertEquals("hard_constraints", proposal.getCandidateShortages().get(0).getScope());
        assertTrue(proposal.getActions().isEmpty());
    }

    @Test
    void shouldProjectExcludeRequirementBeforeFillingToCount() {
        PlanningStateDTO state = state(12);
        state.getCandidatePoolState().setVolunteerModel("major");
        CandidateItemDTO publicCurrent = candidate("v1", "公办学校1", "数学", "理学", 80D);
        publicCurrent.setSchoolNature("公办");
        CandidateItemDTO privateCurrent = candidate("v2", "民办学校", "法学", "法学", 90D);
        privateCurrent.setSchoolNature("民办");
        CandidateItemDTO publicReplacement = candidate("v3", "公办学校2", "金融学", "经济学", 88D);
        publicReplacement.setSchoolNature("公办");
        state.getCandidatePoolState().getItems().addAll(
                java.util.Arrays.asList(publicCurrent, privateCurrent, publicReplacement));
        state.getOrderedPlanState().getItems().add(ordered("v1", "公办学校1", "数学", false));
        state.getOrderedPlanState().getItems().add(ordered("v2", "民办学校", "法学", false));
        UserGoalFixProposalReq req = new UserGoalFixProposalReq();
        req.setGoalType("fill_to_count");
        req.setTargetCount(2);
        req.setSourceVersionGuard(12);
        req.getRequirements().add(requirement("exclude", "school", "school_nature", "民办"));

        FixProposalDTO proposal = UserGoalProposalBuilder.build(state, req).getProposals().get(0);

        assertEquals("ready", proposal.getStatus());
        assertEquals(2, proposal.getActions().size());
        assertEquals("remove_volunteers", proposal.getActions().get(0).getActionType());
        assertEquals(java.util.Arrays.asList("v2"), proposal.getActions().get(0).getRemoveVolunteerIds());
        assertEquals("fill_total_count", proposal.getActions().get(1).getActionType());
        assertEquals(java.util.Arrays.asList("v3"), proposal.getActions().get(1).getCandidateVolunteerIds());
        assertTrue(proposal.getSummary().contains("排除民办（院校性质）"));
        assertEquals(Integer.valueOf(1), proposal.getDryRunResult().getRemoveVolunteerCount());
        assertEquals(Integer.valueOf(1), proposal.getDryRunResult().getAddVolunteerCount());
        assertEquals(Integer.valueOf(2), proposal.getDryRunResult().getAfterVolunteerTotal());
    }

    @Test
    void shouldProjectOrderedUnitAttributesWhenCurrentCandidateIsMissing() {
        PlanningStateDTO state = state(12);
        state.getCandidatePoolState().setVolunteerModel("majorGroup");
        CandidateItemDTO publicReplacement = candidate("v2", "公办学校", "金融学", "经济学", 88D);
        publicReplacement.setPlanSchoolDataId("u2");
        publicReplacement.setSchoolNature("公办");
        state.getCandidatePoolState().getItems().add(publicReplacement);

        OrderedUnitDTO privateUnit = new OrderedUnitDTO();
        privateUnit.setUnitId("u1");
        privateUnit.setSchoolName("民办学校");
        privateUnit.setSchoolNature("民办");
        privateUnit.getMajorItems().add(unitMajor("v1", "法学"));
        state.getOrderedPlanState().getUnits().add(privateUnit);

        UserGoalFixProposalReq req = new UserGoalFixProposalReq();
        req.setGoalType("fill_to_count");
        req.setTargetCount(1);
        req.setSourceVersionGuard(12);
        req.getRequirements().add(requirement("exclude", "school", "school_nature", "民办"));

        FixProposalDTO proposal = UserGoalProposalBuilder.build(state, req).getProposals().get(0);

        assertEquals("ready", proposal.getStatus());
        assertEquals(2, proposal.getActions().size());
        assertEquals(java.util.Arrays.asList("u1"), proposal.getActions().get(0).getRemoveUnitIds());
        assertEquals(java.util.Arrays.asList("v1"), proposal.getActions().get(0).getRemoveVolunteerIds());
        assertEquals(java.util.Arrays.asList("u2"), proposal.getActions().get(1).getCandidateUnitIds());
        assertEquals(java.util.Arrays.asList("v2"), proposal.getActions().get(1).getCandidateVolunteerIds());
    }

    @Test
    void shouldEnrichMajorItemFromOrderedUnitWhenCurrentCandidateIsMissing() {
        PlanningStateDTO state = state(12);
        state.getCandidatePoolState().setVolunteerModel("major");
        CandidateItemDTO publicReplacement = candidate("v2", "公办学校", "金融学", "经济学", 88D);
        publicReplacement.setPlanSchoolDataId("u2");
        publicReplacement.setSchoolNature("公办");
        state.getCandidatePoolState().getItems().add(publicReplacement);

        state.getOrderedPlanState().getItems().add(ordered("v1", "民办学校", "法学", false));
        OrderedUnitDTO privateUnit = new OrderedUnitDTO();
        privateUnit.setUnitId("u1");
        privateUnit.setSchoolName("民办学校");
        privateUnit.setSchoolNature("民办");
        privateUnit.getMajorItems().add(unitMajor("v1", "法学"));
        state.getOrderedPlanState().getUnits().add(privateUnit);

        UserGoalFixProposalReq req = new UserGoalFixProposalReq();
        req.setGoalType("fill_to_count");
        req.setTargetCount(1);
        req.setSourceVersionGuard(12);
        req.getRequirements().add(requirement("exclude", "school", "school_nature", "民办"));

        FixProposalDTO proposal = UserGoalProposalBuilder.build(state, req).getProposals().get(0);

        assertEquals("ready", proposal.getStatus());
        assertEquals(java.util.Arrays.asList("v1"), proposal.getActions().get(0).getRemoveVolunteerIds());
        assertEquals(java.util.Arrays.asList("v2"), proposal.getActions().get(1).getCandidateVolunteerIds());
        assertEquals(Integer.valueOf(1), proposal.getDryRunResult().getAfterVolunteerTotal());
    }

    @Test
    void shouldBlockProjectedRequirementWhenViolatingItemIsLocked() {
        PlanningStateDTO state = state(12);
        state.getCandidatePoolState().setVolunteerModel("major");
        CandidateItemDTO privateCurrent = candidate("v1", "民办学校", "法学", "法学", 90D);
        privateCurrent.setSchoolNature("民办");
        state.getCandidatePoolState().getItems().add(privateCurrent);
        state.getOrderedPlanState().getItems().add(ordered("v1", "民办学校", "法学", true));
        UserGoalFixProposalReq req = new UserGoalFixProposalReq();
        req.setGoalType("fill_to_count");
        req.setTargetCount(1);
        req.setSourceVersionGuard(12);
        req.getRequirements().add(requirement("exclude", "school", "school_nature", "民办"));

        FixProposalDTO proposal = UserGoalProposalBuilder.build(state, req).getProposals().get(0);

        assertEquals("blocked", proposal.getStatus());
        assertEquals("projected_requirements_locked_item", proposal.getBlockingReasonCodes().get(0));
        assertTrue(proposal.getActions().isEmpty());
    }

    @Test
    void shouldReplaceExistingOnlyKeepScopeInSameDomain() {
        PlanningStateDTO state = state(12);
        state.getCandidatePoolState().setVolunteerModel("major");
        state.getConstraintState().getHardConstraints().getMustIncludeRegions().add("北京");
        CandidateItemDTO beijing = candidate("v1", "北京学校", "数学", "理学", 80D);
        beijing.setProvinceName("北京");
        CandidateItemDTO shanghai = candidate("v2", "上海学校", "法学", "法学", 90D);
        shanghai.setProvinceName("上海");
        state.getCandidatePoolState().getItems().addAll(java.util.Arrays.asList(beijing, shanghai));
        state.getOrderedPlanState().getItems().add(ordered("v1", "北京学校", "数学", false));
        state.getOrderedPlanState().getItems().add(ordered("v2", "上海学校", "法学", false));
        UserGoalFixProposalReq req = new UserGoalFixProposalReq();
        req.setGoalType("fill_to_count");
        req.setTargetCount(1);
        req.setSourceVersionGuard(12);
        req.getRequirements().add(requirement("only_keep", "region", "province", "上海"));

        FixProposalDTO proposal = UserGoalProposalBuilder.build(state, req).getProposals().get(0);

        assertEquals("ready", proposal.getStatus());
        assertEquals(1, proposal.getActions().size());
        assertEquals(java.util.Arrays.asList("v1"), proposal.getActions().get(0).getRemoveVolunteerIds());
        assertEquals(Integer.valueOf(1), proposal.getDryRunResult().getAfterVolunteerTotal());
    }

    @Test
    void shouldFillWithNonExclusiveIncludeWithoutRemovingOtherMajors() {
        PlanningStateDTO state = state(12);
        state.getCandidatePoolState().setVolunteerModel("major");
        state.getCandidatePoolState().getItems().add(candidate("v1", "学校1", "数学", "理学", 90D));
        state.getCandidatePoolState().getItems().add(candidate("v2", "学校2", "法学", "法学", 88D));
        state.getCandidatePoolState().getItems().add(candidate("v3", "学校3", "金融学", "经济学", 95D));
        state.getOrderedPlanState().getItems().add(ordered("v1", "学校1", "数学", false));
        UserGoalFixProposalReq req = new UserGoalFixProposalReq();
        req.setGoalType("fill_to_count");
        req.setTargetCount(2);
        req.setSourceVersionGuard(12);
        req.getRequirements().add(requirement("include", "major", "major", "法学"));

        FixProposalDTO proposal = UserGoalProposalBuilder.build(state, req).getProposals().get(0);

        assertEquals("ready", proposal.getStatus());
        assertEquals(1, proposal.getActions().size());
        assertEquals("fill_total_count", proposal.getActions().get(0).getActionType());
        assertEquals(java.util.Arrays.asList("v2"), proposal.getActions().get(0).getCandidateVolunteerIds());
        assertTrue(proposal.getSummary().contains("至少包含法学（专业）"));
        assertEquals(Integer.valueOf(0), proposal.getDryRunResult().getRemoveVolunteerCount());
        assertEquals(Integer.valueOf(1), proposal.getDryRunResult().getAddVolunteerCount());
    }

    @Test
    void shouldReplaceUnlockedItemForIncludeWhenPlanIsFull() {
        PlanningStateDTO state = state(12);
        state.getCandidatePoolState().setVolunteerModel("major");
        state.getCandidatePoolState().getItems().add(candidate("v1", "学校1", "数学", "理学", 90D));
        state.getCandidatePoolState().getItems().add(candidate("v2", "学校2", "法学", "法学", 88D));
        state.getOrderedPlanState().getItems().add(ordered("v1", "学校1", "数学", false));
        UserGoalFixProposalReq req = new UserGoalFixProposalReq();
        req.setGoalType("fill_to_count");
        req.setTargetCount(1);
        req.setSourceVersionGuard(12);
        req.getRequirements().add(requirement("include", "major", "major", "法学"));

        FixProposalDTO proposal = UserGoalProposalBuilder.build(state, req).getProposals().get(0);

        assertEquals("ready", proposal.getStatus());
        assertEquals(2, proposal.getActions().size());
        assertEquals(java.util.Arrays.asList("v1"), proposal.getActions().get(0).getRemoveVolunteerIds());
        assertEquals(java.util.Arrays.asList("v2"), proposal.getActions().get(1).getCandidateVolunteerIds());
        assertEquals(Integer.valueOf(1), proposal.getDryRunResult().getAfterVolunteerTotal());
        assertTrue(proposal.getActions().get(0).getDetail().contains("等量替换"));
    }

    @Test
    void shouldPersistAlreadySatisfiedIncludeWithoutRemovingNonMatchingItems() {
        PlanningStateDTO state = state(12);
        state.getCandidatePoolState().setVolunteerModel("major");
        state.getCandidatePoolState().getItems().add(candidate("v1", "学校1", "法学", "法学", 90D));
        state.getCandidatePoolState().getItems().add(candidate("v2", "学校2", "数学", "理学", 88D));
        state.getOrderedPlanState().getItems().add(ordered("v1", "学校1", "法学", false));
        state.getOrderedPlanState().getItems().add(ordered("v2", "学校2", "数学", false));
        UserGoalFixProposalReq req = new UserGoalFixProposalReq();
        req.setGoalType("fill_to_count");
        req.setTargetCount(2);
        req.setSourceVersionGuard(12);
        req.getRequirements().add(requirement("include", "major", "major", "法学"));

        FixProposalDTO proposal = UserGoalProposalBuilder.build(state, req).getProposals().get(0);

        assertEquals("ready", proposal.getStatus());
        assertTrue(proposal.getActions().isEmpty());
        assertTrue(proposal.getSummary().contains("已经满足目标"));
        assertEquals(Integer.valueOf(0), proposal.getDryRunResult().getRemoveVolunteerCount());
    }

    @Test
    void shouldIncreaseExplicitCoverageWhilePreservingCurrentPlanCount() {
        PlanningStateDTO state = state(12);
        state.getCandidatePoolState().setVolunteerModel("major");
        CandidateItemDTO beijing = candidate("v1", "北京学校", "数学", "理学", 90D);
        beijing.setProvinceName("北京");
        CandidateItemDTO shanghaiLaw = candidate("v2", "上海学校1", "法学", "法学", 88D);
        shanghaiLaw.setProvinceName("上海");
        CandidateItemDTO shanghaiFinance = candidate("v3", "上海学校2", "金融学", "经济学", 86D);
        shanghaiFinance.setProvinceName("上海");
        state.getCandidatePoolState().getItems().addAll(
                java.util.Arrays.asList(beijing, shanghaiLaw, shanghaiFinance));
        state.getOrderedPlanState().getItems().add(ordered("v1", "北京学校", "数学", false));
        state.getOrderedPlanState().getItems().add(ordered("v2", "上海学校1", "法学", false));
        UserGoalFixProposalReq req = new UserGoalFixProposalReq();
        req.setGoalType("fill_to_count");
        req.setTargetCount(2);
        req.setPersistTargetCount(false);
        req.setSourceVersionGuard(12);
        UserGoalFixProposalReq.RequirementDTO coverage = requirement(
                "include", "region", "province", "上海");
        coverage.setMinCount(2);
        req.getRequirements().add(coverage);

        FixProposalDTO proposal = UserGoalProposalBuilder.build(state, req).getProposals().get(0);

        assertEquals("ready", proposal.getStatus());
        assertEquals(2, proposal.getActions().size());
        assertEquals(java.util.Arrays.asList("v1"), proposal.getActions().get(0).getRemoveVolunteerIds());
        assertEquals(java.util.Arrays.asList("v3"), proposal.getActions().get(1).getCandidateVolunteerIds());
        assertEquals(Integer.valueOf(2), proposal.getDryRunResult().getBeforeVolunteerTotal());
        assertEquals(Integer.valueOf(2), proposal.getDryRunResult().getAfterVolunteerTotal());
        assertTrue(proposal.getTitle().contains("保持当前 2 个志愿"));
        assertTrue(proposal.getSummary().contains("至少包含2个上海（地区）"), proposal.getSummary());
        assertEquals(java.util.Arrays.asList("v2", "v3"),
                proposal.getSolverResult().getSelectedEntityIds());
        assertEquals(1, proposal.getSolverResult().getObjectiveResults().stream()
                .filter(item -> "coverage".equals(item.getObjectiveType())).count());
    }

    @Test
    void shouldIncreaseProtectTierMinimumWhilePreservingCurrentPlanCount() {
        PlanningStateDTO state = state(12);
        state.getCandidatePoolState().setVolunteerModel("major");
        CandidateItemDTO safeOne = candidate("v1", "学校1", "数学", "理学", 90D);
        safeOne.setTier("稳");
        CandidateItemDTO protectOne = candidate("v2", "学校2", "法学", "法学", 88D);
        protectOne.setTier("保");
        CandidateItemDTO safeTwo = candidate("v3", "学校3", "金融学", "经济学", 87D);
        safeTwo.setTier("稳");
        CandidateItemDTO protectTwo = candidate("v4", "学校4", "会计学", "管理学", 86D);
        protectTwo.setTier("保底");
        CandidateItemDTO protectThree = candidate("v5", "学校5", "审计学", "管理学", 85D);
        protectThree.setTier("protect");
        state.getCandidatePoolState().getItems().addAll(java.util.Arrays.asList(
                safeOne, protectOne, safeTwo, protectTwo, protectThree));
        state.getOrderedPlanState().getItems().add(orderedWithTier("v1", "学校1", "数学", "稳"));
        state.getOrderedPlanState().getItems().add(orderedWithTier("v2", "学校2", "法学", "保"));
        state.getOrderedPlanState().getItems().add(orderedWithTier("v3", "学校3", "金融学", "稳"));
        UserGoalFixProposalReq req = new UserGoalFixProposalReq();
        req.setGoalType("fill_to_count");
        req.setTargetCount(3);
        req.setPersistTargetCount(false);
        req.setSourceVersionGuard(12);
        UserGoalFixProposalReq.RequirementDTO minimum = requirement(
                "include", "admission", "tier", "保");
        minimum.setMinCount(3);
        req.getRequirements().add(minimum);

        FixProposalDTO proposal = UserGoalProposalBuilder.build(state, req).getProposals().get(0);

        assertEquals("ready", proposal.getStatus());
        assertEquals(Integer.valueOf(3), proposal.getDryRunResult().getBeforeVolunteerTotal());
        assertEquals(Integer.valueOf(3), proposal.getDryRunResult().getAfterVolunteerTotal());
        assertEquals(Integer.valueOf(2), proposal.getDryRunResult().getRemoveVolunteerCount());
        assertEquals(Integer.valueOf(2), proposal.getDryRunResult().getAddVolunteerCount());
        assertTrue(proposal.getSummary().contains("至少包含3个保（录取档位）"), proposal.getSummary());
    }

    @Test
    void shouldRejectUnknownAdmissionTierMinimum() {
        PlanningStateDTO state = state(12);
        UserGoalFixProposalReq req = new UserGoalFixProposalReq();
        req.setGoalType("fill_to_count");
        req.setTargetCount(3);
        req.setSourceVersionGuard(12);
        UserGoalFixProposalReq.RequirementDTO minimum = requirement(
                "include", "admission", "tier", "超稳");
        minimum.setMinCount(2);
        req.getRequirements().add(minimum);

        FixProposalDTO proposal = UserGoalProposalBuilder.build(state, req).getProposals().get(0);

        assertEquals("blocked", proposal.getStatus());
        assertTrue(proposal.getBlockingReason().contains("冲、稳、保"));
    }

    @Test
    void shouldReplaceExcessTierForExactTierQuota() {
        PlanningStateDTO state = state(12);
        state.getCandidatePoolState().setVolunteerModel("major");
        CandidateItemDTO sprintOne = candidate("v1", "学校1", "数学", "理学", 90D);
        sprintOne.setTier("冲");
        CandidateItemDTO sprintTwo = candidate("v2", "学校2", "物理学", "理学", 88D);
        sprintTwo.setTier("冲刺");
        CandidateItemDTO stable = candidate("v3", "学校3", "金融学", "经济学", 87D);
        stable.setTier("稳");
        CandidateItemDTO protect = candidate("v4", "学校4", "会计学", "管理学", 86D);
        protect.setTier("protect");
        state.getCandidatePoolState().getItems().addAll(java.util.Arrays.asList(
                sprintOne, sprintTwo, stable, protect));
        state.getOrderedPlanState().getItems().add(orderedWithTier("v1", "学校1", "数学", "冲"));
        state.getOrderedPlanState().getItems().add(orderedWithTier("v2", "学校2", "物理学", "冲"));
        state.getOrderedPlanState().getItems().add(orderedWithTier("v3", "学校3", "金融学", "稳"));
        UserGoalFixProposalReq req = new UserGoalFixProposalReq();
        req.setGoalType("fill_to_count");
        req.setTargetCount(3);
        req.setPersistTargetCount(false);
        req.setSourceVersionGuard(12);
        req.setTierQuotaGoal(tierQuota(1, 1, 1));

        FixProposalDTO proposal = UserGoalProposalBuilder.build(state, req).getProposals().get(0);

        assertEquals("ready", proposal.getStatus());
        assertEquals(2, proposal.getActions().size());
        assertEquals(Integer.valueOf(1), proposal.getDryRunResult().getRemoveVolunteerCount());
        assertEquals(Integer.valueOf(1), proposal.getDryRunResult().getAddVolunteerCount());
        assertEquals(java.util.Arrays.asList("v4"),
                proposal.getActions().get(1).getCandidateVolunteerIds());
        assertTrue(proposal.getSummary().contains("冲1个、稳1个、保1个"), proposal.getSummary());
        assertEquals(Integer.valueOf(2), proposal.getDryRunResult()
                .getBeforeVolunteerTierCounts().get("冲"));
        assertEquals(Integer.valueOf(1), proposal.getDryRunResult()
                .getAfterVolunteerTierCounts().get("保"));
        assertEquals(java.util.Arrays.asList("v1", "v3", "v4"),
                proposal.getSolverResult().getSelectedEntityIds());
        assertEquals(0, proposal.getSolverResult().getObjectiveResults().stream()
                .filter(item -> "coverage".equals(item.getObjectiveType())).count());
        assertEquals(3, proposal.getSolverResult().getObjectiveResults().stream()
                .filter(item -> "tier_exact".equals(item.getObjectiveType())).count());
    }

    @Test
    void shouldCreateReadyProposalWhenNewMaximumNeedsOnlyPersistence() {
        PlanningStateDTO state = stateWithTierCounts(1, 2, 1);
        UserGoalFixProposalReq request = fillWithSprintRange("patch", 0, 2);
        request.setPersistTargetCount(false);

        FixProposalDTO proposal = UserGoalProposalBuilder.build(
                state, request).getProposals().get(0);

        assertEquals("ready", proposal.getStatus());
        assertTrue(proposal.getActions().isEmpty());
        assertEquals("no_change", proposal.getSolverResult().getStatus());
        assertTrue(proposal.getTierQuotaChange().getStateChanged());
        assertTrue(proposal.getSummary().contains("当前方案有 4 个志愿"), proposal.getSummary());
        assertTrue(proposal.getSummary().contains("方案项目不变"));
        assertTrue(proposal.getTitle().contains("冲稳保数量范围"));
        assertTrue(proposal.getSummary().contains("冲稳保数量范围"));
        assertTrue(proposal.getDryRunResult().getMessage().contains("冲稳保数量范围"));
        assertFalse(proposal.getTitle().contains("精确配额"));
        assertFalse(proposal.getDryRunResult().getMessage().contains("精确配额"));
        assertEquals(Integer.valueOf(1), proposal.getDryRunResult()
                .getAfterVolunteerTierCounts().get("冲"));
        assertEquals(null, proposal.getTierQuotaChange().getRequestedGoal()
                .getSprint().getMinCount());
        assertEquals(Integer.valueOf(2), proposal.getTierQuotaChange().getRequestedGoal()
                .getSprint().getMaxCount());
    }

    @Test
    void shouldExposeOnlyChangedBoundsWhenModelRepeatsHistoricalRangePatch() {
        PlanningStateDTO state = stateWithTierCounts(1, 2, 1);
        state.getConstraintState().getHardPlanningObjectives().setTierQuotaGoal(
                rangeGoal(bound(0, 2), bound(1, 3), bound(0, 4)));
        UserGoalFixProposalReq request = fillRequest(4);
        request.setPersistTargetCount(false);
        TierQuotaGoalRequestDTO requested = new TierQuotaGoalRequestDTO();
        requested.setType("count_ranges");
        requested.setUpdateMode("patch");
        requested.setSprint(bound(0, 1));
        requested.setStable(bound(1, 3));
        requested.setProtect(bound(0, 4));
        request.setTierQuotaGoal(requested);

        FixProposalDTO proposal = UserGoalProposalBuilder.build(
                state, request).getProposals().get(0);

        TierQuotaGoalRequestDTO delta = proposal.getTierQuotaChange().getRequestedGoal();
        assertEquals("patch", delta.getUpdateMode());
        assertEquals(Integer.valueOf(1), delta.getSprint().getMaxCount());
        assertEquals(null, delta.getSprint().getMinCount());
        assertEquals(null, delta.getStable());
        assertEquals(null, delta.getProtect());
        assertEquals(Integer.valueOf(0), proposal.getTierQuotaChange()
                .getEffectiveGoal().getSprint().getMinCount());
        assertEquals(Integer.valueOf(3), proposal.getTierQuotaChange()
                .getEffectiveGoal().getStable().getMaxCount());
    }

    @Test
    void shouldReturnInfoWhenPlanAndEffectiveGoalAreBothUnchanged() {
        PlanningStateDTO state = stateWithTierCounts(1, 2, 1);
        state.getConstraintState().getHardPlanningObjectives().setTierQuotaGoal(
                rangeGoal(bound(null, 2), null, null));

        FixProposalDTO proposal = UserGoalProposalBuilder.build(
                state, fillWithSprintRange("patch", null, 2)).getProposals().get(0);

        assertEquals("info", proposal.getStatus());
        assertFalse(proposal.getRequiresConfirmation());
        assertFalse(proposal.getTierQuotaChange().getStateChanged());
    }

    @Test
    void shouldExposeRemovedHistoricalBoundsForRangeReplace() {
        PlanningStateDTO state = stateWithTierCounts(1, 2, 1);
        state.getConstraintState().getHardPlanningObjectives().setTierQuotaGoal(
                rangeGoal(bound(null, 2), bound(1, null), null));
        UserGoalFixProposalReq request = fillWithSprintRange("replace", null, 3);

        FixProposalDTO proposal = UserGoalProposalBuilder.build(state, request).getProposals().get(0);

        assertEquals(Integer.valueOf(1), proposal.getTierQuotaChange()
                .getBeforeGoal().getStable().getMinCount());
        assertEquals("replace", proposal.getTierQuotaChange().getRequestedGoal().getUpdateMode());
        assertEquals(Integer.valueOf(3), proposal.getTierQuotaChange()
                .getEffectiveGoal().getSprint().getMaxCount());
        assertEquals(null, proposal.getTierQuotaChange().getEffectiveGoal().getStable());
    }

    @Test
    void shouldExposeSubmittedCanonicalAndResolvedRatioValues() {
        PlanningStateDTO state = stateWithTierCounts(1, 2, 1);
        UserGoalFixProposalReq request = fillRequest(4);
        request.setPersistTargetCount(false);
        request.setTierQuotaGoal(ratio(30, 40, 30));

        FixProposalDTO proposal = UserGoalProposalBuilder.build(state, request).getProposals().get(0);

        assertEquals(Integer.valueOf(30), proposal.getTierQuotaChange()
                .getRequestedGoal().getSprintWeight());
        assertEquals(Integer.valueOf(30), proposal.getTierQuotaChange()
                .getEffectiveGoal().getSprintWeight());
        assertEquals(Integer.valueOf(3), proposal.getTierQuotaChange()
                .getResolution().getCanonicalWeights().getSprintWeight());
        assertEquals(Integer.valueOf(2), proposal.getTierQuotaChange()
                .getResolution().getResolvedCounts().getStableCount());
        assertTrue(proposal.getTitle().contains("冲稳保比例"));
        assertTrue(proposal.getSummary().contains("冲稳保比例"));
        assertTrue(proposal.getDryRunResult().getMessage().contains("冲稳保比例"));
        assertFalse(proposal.getTitle().contains("精确配额"));
        assertFalse(proposal.getDryRunResult().getMessage().contains("精确配额"));
    }

    @Test
    void shouldDescribeRangeCompositeGuardWithoutCallingItExactQuota() {
        PlanningStateDTO state = stateWithTierCounts(1, 2, 1);
        UserGoalFixProposalReq request = fillWithSprintRange("patch", null, 2);
        request.getRequirements().add(
                requirement("exclude", "school", "school_nature", "民办"));

        FixProposalDTO proposal = UserGoalProposalBuilder.build(state, request)
                .getProposals().get(0);

        assertEquals("blocked", proposal.getStatus());
        assertEquals("tier_quota_composite_not_supported",
                proposal.getBlockingReasonCodes().get(0));
        assertTrue(proposal.getBlockingReason().contains("冲稳保数量范围"));
        assertFalse(proposal.getBlockingReason().contains("精确配额"));
    }

    @Test
    void shouldBlockCrossTypePatchWithoutActions() {
        PlanningStateDTO state = stateWithTierCounts(1, 2, 1);
        state.getConstraintState().getHardPlanningObjectives().setTierQuotaGoal(quotaGoal(1, 2, 1));

        FixProposalDTO proposal = UserGoalProposalBuilder.build(
                state, fillWithSprintRange("patch", null, 2)).getProposals().get(0);

        assertEquals("blocked", proposal.getStatus());
        assertEquals("tier_quota_update_type_conflict", proposal.getBlockingReasonCodes().get(0));
        assertTrue(proposal.getActions().isEmpty());
        assertFalse(proposal.getRequiresConfirmation());
    }

    @Test
    void shouldExposeTierSolverDiagnosticWhenCandidateCapacityIsInsufficient() {
        PlanningStateDTO state = stateWithTierCounts(1, 2, 1);

        FixProposalDTO proposal = UserGoalProposalBuilder.build(
                state, fillWithSprintRange("replace", 2, null)).getProposals().get(0);

        assertEquals("blocked", proposal.getStatus());
        assertEquals("tier_min_infeasible", proposal.getBlockingReasonCodes().get(0));
        assertEquals("tier_min_infeasible",
                proposal.getSolverResult().getDiagnostics().get(0).getReasonCode());
        assertTrue(proposal.getActions().isEmpty());
    }

    @Test
    void shouldBlockExactTierQuotaWhenTotalDoesNotMatchTarget() {
        PlanningStateDTO state = state(12);
        UserGoalFixProposalReq req = new UserGoalFixProposalReq();
        req.setGoalType("fill_to_count");
        req.setTargetCount(4);
        req.setSourceVersionGuard(12);
        req.setTierQuotaGoal(tierQuota(1, 1, 1));

        FixProposalDTO proposal = UserGoalProposalBuilder.build(state, req).getProposals().get(0);

        assertEquals("blocked", proposal.getStatus());
        assertEquals("tier_quota_invalid", proposal.getBlockingReasonCodes().get(0));
        assertTrue(proposal.getBlockingReason().contains("合计必须等于"));
    }

    @Test
    void shouldBlockExactTierQuotaComposite() {
        PlanningStateDTO state = state(12);
        UserGoalFixProposalReq req = new UserGoalFixProposalReq();
        req.setGoalType("fill_to_count");
        req.setTargetCount(3);
        req.setSourceVersionGuard(12);
        req.setTierQuotaGoal(tierQuota(1, 1, 1));
        req.getRequirements().add(requirement("exclude", "school", "school_nature", "民办"));

        FixProposalDTO proposal = UserGoalProposalBuilder.build(state, req).getProposals().get(0);

        assertEquals("blocked", proposal.getStatus());
        assertEquals("tier_quota_composite_not_supported", proposal.getBlockingReasonCodes().get(0));
        assertTrue(proposal.getActions().isEmpty());
    }

    @Test
    void shouldBlockExactTierQuotaOnNonFillProposal() {
        PlanningStateDTO state = state(12);
        UserGoalFixProposalReq req = new UserGoalFixProposalReq();
        req.setGoalType("prioritize_within_tier");
        req.setSourceVersionGuard(12);
        req.setTierQuotaGoal(tierQuota(1, 1, 1));
        req.getPriorityRules().add(priorityRule("region", "province", "上海"));

        FixProposalDTO proposal = UserGoalProposalBuilder.build(state, req).getProposals().get(0);

        assertEquals("blocked", proposal.getStatus());
        assertEquals("tier_quota_invalid", proposal.getBlockingReasonCodes().get(0));
        assertTrue(proposal.getBlockingReason().contains("fill_to_count"));
    }

    @Test
    void shouldBlockPreserveCoverageWhenFrozenCountIsStale() {
        PlanningStateDTO state = state(12);
        state.getCandidatePoolState().setVolunteerModel("major");
        state.getCandidatePoolState().getItems().add(candidate("v1", "学校1", "法学", "法学", 90D));
        state.getOrderedPlanState().getItems().add(ordered("v1", "学校1", "法学", false));
        UserGoalFixProposalReq req = new UserGoalFixProposalReq();
        req.setGoalType("fill_to_count");
        req.setTargetCount(2);
        req.setPersistTargetCount(false);
        req.setSourceVersionGuard(12);
        UserGoalFixProposalReq.RequirementDTO coverage = requirement(
                "include", "major", "major", "法学");
        coverage.setMinCount(1);
        req.getRequirements().add(coverage);

        FixProposalDTO proposal = UserGoalProposalBuilder.build(state, req).getProposals().get(0);

        assertEquals("blocked", proposal.getStatus());
        assertEquals("preserve_count_mismatch", proposal.getBlockingReasonCodes().get(0));
        assertTrue(proposal.getActions().isEmpty());
    }

    @Test
    void shouldBlockIncludeReplacementWhenOnlyRemovableItemIsLocked() {
        PlanningStateDTO state = state(12);
        state.getCandidatePoolState().setVolunteerModel("major");
        state.getCandidatePoolState().getItems().add(candidate("v1", "学校1", "数学", "理学", 90D));
        state.getCandidatePoolState().getItems().add(candidate("v2", "学校2", "法学", "法学", 88D));
        state.getOrderedPlanState().getItems().add(ordered("v1", "学校1", "数学", true));
        UserGoalFixProposalReq req = new UserGoalFixProposalReq();
        req.setGoalType("fill_to_count");
        req.setTargetCount(1);
        req.setSourceVersionGuard(12);
        req.getRequirements().add(requirement("include", "major", "major", "法学"));

        FixProposalDTO proposal = UserGoalProposalBuilder.build(state, req).getProposals().get(0);

        assertEquals("blocked", proposal.getStatus());
        assertEquals("coverage_replacement_locked_item", proposal.getBlockingReasonCodes().get(0));
        assertTrue(proposal.getActions().isEmpty());
    }

    @Test
    void shouldBlockIncludeWhenNoMatchingCandidateExists() {
        PlanningStateDTO state = state(12);
        state.getCandidatePoolState().setVolunteerModel("major");
        state.getCandidatePoolState().getItems().add(candidate("v1", "学校1", "数学", "理学", 90D));
        UserGoalFixProposalReq req = new UserGoalFixProposalReq();
        req.setGoalType("fill_to_count");
        req.setTargetCount(1);
        req.setSourceVersionGuard(12);
        req.getRequirements().add(requirement("include", "major", "major", "法学"));

        FixProposalDTO proposal = UserGoalProposalBuilder.build(state, req).getProposals().get(0);

        assertEquals("blocked", proposal.getStatus());
        assertEquals("coverage_requirement_insufficient", proposal.getBlockingReasonCodes().get(0));
        assertTrue(proposal.getActions().isEmpty());
    }

    @Test
    void shouldUseOneCandidateToCoverMultipleIncludeRequirements() {
        PlanningStateDTO state = state(12);
        state.getCandidatePoolState().setVolunteerModel("major");
        CandidateItemDTO shanghaiLaw = candidate("v1", "上海政法学院", "法学", "法学", 90D);
        shanghaiLaw.setProvinceName("上海");
        state.getCandidatePoolState().getItems().add(shanghaiLaw);
        UserGoalFixProposalReq req = new UserGoalFixProposalReq();
        req.setGoalType("fill_to_count");
        req.setTargetCount(1);
        req.setSourceVersionGuard(12);
        req.getRequirements().add(requirement("include", "major", "major", "法学"));
        req.getRequirements().add(requirement("include", "region", "province", "上海"));

        FixProposalDTO proposal = UserGoalProposalBuilder.build(state, req).getProposals().get(0);

        assertEquals("ready", proposal.getStatus());
        assertEquals(1, proposal.getActions().size());
        assertEquals(java.util.Arrays.asList("v1"), proposal.getActions().get(0).getCandidateVolunteerIds());
        assertEquals(Integer.valueOf(1), proposal.getDryRunResult().getAfterVolunteerTotal());
    }

    @Test
    void shouldCountMajorGroupUnitsAndIncludeCompleteSelectedUnits() {
        PlanningStateDTO state = state(12);
        state.getCandidatePoolState().setVolunteerModel("majorGroup");
        CandidateItemDTO v1 = candidate("v1", "学校1", "专业1", "类别1", 80D);
        v1.setPlanSchoolDataId("u1");
        CandidateItemDTO v1b = candidate("v1b", "学校1", "专业1B", "类别1", 79D);
        v1b.setPlanSchoolDataId("u1");
        CandidateItemDTO v2 = candidate("v2", "学校2", "专业2A", "类别2", 95D);
        v2.setPlanSchoolDataId("u2");
        CandidateItemDTO v3 = candidate("v3", "学校2", "专业2B", "类别2", 90D);
        v3.setPlanSchoolDataId("u2");
        CandidateItemDTO v4 = candidate("v4", "学校3", "专业3", "类别3", 85D);
        v4.setPlanSchoolDataId("u3");
        state.getCandidatePoolState().getItems().add(v1);
        state.getCandidatePoolState().getItems().add(v1b);
        state.getCandidatePoolState().getItems().add(v2);
        state.getCandidatePoolState().getItems().add(v3);
        state.getCandidatePoolState().getItems().add(v4);
        OrderedUnitDTO currentUnit = new OrderedUnitDTO();
        currentUnit.setUnitId("u1");
        currentUnit.getMajorItems().add(unitMajor("v1", "专业1"));
        currentUnit.getMajorItems().add(unitMajor("v1b", "专业1B"));
        state.getOrderedPlanState().getUnits().add(currentUnit);
        state.getOrderedPlanState().getItems().add(ordered("v1", "学校1", "专业1", false));
        state.getOrderedPlanState().getItems().add(ordered("v1b", "学校1", "专业1B", false));
        UserGoalFixProposalReq req = new UserGoalFixProposalReq();
        req.setGoalType("fill_to_count");
        req.setTargetCount(3);
        req.setSourceVersionGuard(12);

        FixProposalDTO proposal = UserGoalProposalBuilder.build(state, req).getProposals().get(0);

        assertEquals("ready", proposal.getStatus());
        FixProposalActionDTO action = proposal.getActions().get(0);
        assertEquals("unit", action.getLevel());
        assertEquals(java.util.Arrays.asList("u2", "u3"), action.getUnitIds());
        assertEquals(java.util.Arrays.asList("v2", "v3", "v4"), action.getVolunteerIds());
        assertEquals(Integer.valueOf(1), proposal.getDryRunResult().getBeforeUnitTotal());
        assertEquals(Integer.valueOf(3), proposal.getDryRunResult().getAfterUnitTotal());
        assertEquals(Integer.valueOf(5), proposal.getDryRunResult().getAfterVolunteerTotal());
    }

    @Test
    void shouldBuildWithinTierPriorityPreview() {
        PlanningStateDTO state = state(12);
        state.getCandidatePoolState().setVolunteerModel("major");
        CandidateItemDTO other1 = candidate("v1", "北京学校", "数学", "理学", 90D);
        other1.setProvinceName("北京");
        CandidateItemDTO shanghai1 = candidate("v2", "上海学校1", "法学", "法学", 89D);
        shanghai1.setProvinceName("上海");
        CandidateItemDTO other2 = candidate("v3", "天津学校", "金融学", "经济学", 88D);
        other2.setProvinceName("天津");
        CandidateItemDTO shanghai2 = candidate("v4", "上海学校2", "会计学", "管理学", 87D);
        shanghai2.setProvinceName("上海");
        state.getCandidatePoolState().getItems().addAll(
                java.util.Arrays.asList(other1, shanghai1, other2, shanghai2));
        state.getOrderedPlanState().getItems().add(orderedWithTier("v1", "北京学校", "数学", "稳"));
        state.getOrderedPlanState().getItems().add(orderedWithTier("v2", "上海学校1", "法学", "稳"));
        state.getOrderedPlanState().getItems().add(orderedWithTier("v3", "天津学校", "金融学", "稳"));
        state.getOrderedPlanState().getItems().add(orderedWithTier("v4", "上海学校2", "会计学", "稳"));
        UserGoalFixProposalReq req = new UserGoalFixProposalReq();
        req.setGoalType("prioritize_within_tier");
        req.setSourceVersionGuard(12);
        req.getPriorityRules().add(priorityRule("region", "province", "上海"));

        FixProposalDTO proposal = UserGoalProposalBuilder.build(state, req).getProposals().get(0);

        assertEquals("ready", proposal.getStatus());
        assertEquals("prioritize_within_tier", proposal.getStrategy());
        assertEquals(1, proposal.getActions().size());
        assertEquals("reorder_volunteers", proposal.getActions().get(0).getActionType());
        assertEquals(java.util.Arrays.asList("v2", "v4"), proposal.getActions().get(0).getVolunteerIds());
        assertEquals(Integer.valueOf(2), proposal.getDryRunResult().getPriorityMatchedCount());
        assertEquals(Integer.valueOf(3), proposal.getDryRunResult().getPriorityBeforeInversionCount());
        assertEquals(Integer.valueOf(0), proposal.getDryRunResult().getPriorityAfterInversionCount());
        assertEquals(Integer.valueOf(2), proposal.getDryRunResult().getPriorityMovedTargetCount());
        assertEquals(Integer.valueOf(4), proposal.getDryRunResult().getAfterVolunteerTotal());
        assertEquals(java.util.Arrays.asList("v2", "v4", "v1", "v3"),
                proposal.getSolverResult().getOrderedEntityIds());
    }

    @Test
    void shouldPersistAlreadySatisfiedPriorityThroughReadyProposal() {
        PlanningStateDTO state = state(12);
        CandidateItemDTO shanghai = candidate("v1", "上海学校", "法学", "法学", 90D);
        shanghai.setProvinceName("上海");
        CandidateItemDTO other = candidate("v2", "北京学校", "数学", "理学", 89D);
        other.setProvinceName("北京");
        state.getCandidatePoolState().getItems().addAll(java.util.Arrays.asList(shanghai, other));
        state.getOrderedPlanState().getItems().add(orderedWithTier("v1", "上海学校", "法学", "稳"));
        state.getOrderedPlanState().getItems().add(orderedWithTier("v2", "北京学校", "数学", "稳"));
        UserGoalFixProposalReq req = new UserGoalFixProposalReq();
        req.setGoalType("prioritize_within_tier");
        req.setSourceVersionGuard(12);
        req.getPriorityRules().add(priorityRule("region", "province", "上海"));

        FixProposalDTO proposal = UserGoalProposalBuilder.build(state, req).getProposals().get(0);

        assertEquals("ready", proposal.getStatus());
        assertTrue(proposal.getActions().isEmpty());
        assertTrue(proposal.getSummary().contains("已经"));
        assertEquals(Integer.valueOf(0), proposal.getDryRunResult().getPriorityBeforeInversionCount());
    }

    @Test
    void shouldBlockPriorityWhenPinnedPositionWouldMove() {
        PlanningStateDTO state = state(12);
        CandidateItemDTO other = candidate("v1", "北京学校", "数学", "理学", 90D);
        other.setProvinceName("北京");
        CandidateItemDTO shanghai = candidate("v2", "上海学校", "法学", "法学", 89D);
        shanghai.setProvinceName("上海");
        state.getCandidatePoolState().getItems().addAll(java.util.Arrays.asList(other, shanghai));
        OrderedItemDTO pinned = orderedWithTier("v1", "北京学校", "数学", "稳");
        pinned.setPinned(true);
        pinned.setPinnedPosition(1);
        state.getOrderedPlanState().getItems().add(pinned);
        state.getOrderedPlanState().getItems().add(orderedWithTier("v2", "上海学校", "法学", "稳"));
        UserGoalFixProposalReq req = new UserGoalFixProposalReq();
        req.setGoalType("prioritize_within_tier");
        req.setSourceVersionGuard(12);
        req.getPriorityRules().add(priorityRule("region", "province", "上海"));

        FixProposalDTO proposal = UserGoalProposalBuilder.build(state, req).getProposals().get(0);

        assertEquals("blocked", proposal.getStatus());
        assertEquals("priority_pinned_position_conflict", proposal.getBlockingReasonCodes().get(0));
        assertTrue(proposal.getActions().isEmpty());
    }

    @Test
    void shouldBlockPriorityWhenCurrentPlanHasNoMatchingTarget() {
        PlanningStateDTO state = state(12);
        CandidateItemDTO other = candidate("v1", "北京学校", "数学", "理学", 90D);
        other.setProvinceName("北京");
        state.getCandidatePoolState().getItems().add(other);
        state.getOrderedPlanState().getItems().add(orderedWithTier("v1", "北京学校", "数学", "稳"));
        UserGoalFixProposalReq req = new UserGoalFixProposalReq();
        req.setGoalType("prioritize_within_tier");
        req.setSourceVersionGuard(12);
        req.getPriorityRules().add(priorityRule("region", "province", "上海"));

        FixProposalDTO proposal = UserGoalProposalBuilder.build(state, req).getProposals().get(0);

        assertEquals("blocked", proposal.getStatus());
        assertEquals("priority_target_not_in_plan", proposal.getBlockingReasonCodes().get(0));
        assertTrue(proposal.getBlockingReason().contains("不会自动增加"));
    }

    @Test
    void shouldBlockPriorityWhenTierDataIsMissing() {
        PlanningStateDTO state = state(12);
        CandidateItemDTO shanghai = candidate("v1", "上海学校", "法学", "法学", 90D);
        shanghai.setProvinceName("上海");
        state.getCandidatePoolState().getItems().add(shanghai);
        state.getOrderedPlanState().getItems().add(ordered("v1", "上海学校", "法学", false));
        UserGoalFixProposalReq req = new UserGoalFixProposalReq();
        req.setGoalType("prioritize_within_tier");
        req.setSourceVersionGuard(12);
        req.getPriorityRules().add(priorityRule("region", "province", "上海"));

        FixProposalDTO proposal = UserGoalProposalBuilder.build(state, req).getProposals().get(0);

        assertEquals("blocked", proposal.getStatus());
        assertEquals("priority_tier_unavailable", proposal.getBlockingReasonCodes().get(0));
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

    private UserGoalFixProposalReq.RequirementDTO requirement(String kind,
                                                              String domain,
                                                              String key,
                                                              String value) {
        UserGoalFixProposalReq.RequirementDTO requirement = new UserGoalFixProposalReq.RequirementDTO();
        requirement.setKind(kind);
        requirement.setDomain(domain);
        requirement.setKey(key);
        requirement.setValues(java.util.Arrays.asList(value));
        return requirement;
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

    private OrderedItemDTO orderedWithTier(String volunteerId,
                                           String schoolName,
                                           String majorName,
                                           String tier) {
        OrderedItemDTO item = ordered(volunteerId, schoolName, majorName, false);
        item.setTier(tier);
        return item;
    }

    private PriorityRuleDTO priorityRule(String domain, String key, String value) {
        PriorityRuleDTO rule = new PriorityRuleDTO();
        rule.setDomain(domain);
        rule.setKey(key);
        rule.setValues(java.util.Arrays.asList(value));
        rule.setOrderingTarget("rank_before");
        rule.setScope("within_tier");
        return rule;
    }

    private TierQuotaGoalRequestDTO tierQuota(int sprint, int stable, int protect) {
        TierQuotaGoalRequestDTO goal = new TierQuotaGoalRequestDTO();
        goal.setType("exact_counts");
        goal.setSprintCount(sprint);
        goal.setStableCount(stable);
        goal.setProtectCount(protect);
        return goal;
    }

    private TierQuotaGoalDTO quotaGoal(int sprint, int stable, int protect) {
        TierQuotaGoalDTO goal = new TierQuotaGoalDTO();
        goal.setType("exact_counts");
        goal.setSprintCount(sprint);
        goal.setStableCount(stable);
        goal.setProtectCount(protect);
        return goal;
    }

    private TierQuotaGoalRequestDTO ratio(int sprint, int stable, int protect) {
        TierQuotaGoalRequestDTO goal = new TierQuotaGoalRequestDTO();
        goal.setType("ratios");
        goal.setUpdateMode("replace");
        goal.setSprintWeight(sprint);
        goal.setStableWeight(stable);
        goal.setProtectWeight(protect);
        return goal;
    }

    private UserGoalFixProposalReq fillRequest(int targetCount) {
        UserGoalFixProposalReq request = new UserGoalFixProposalReq();
        request.setGoalType("fill_to_count");
        request.setTargetCount(targetCount);
        request.setSourceVersionGuard(12);
        return request;
    }

    private UserGoalFixProposalReq fillWithSprintRange(String updateMode,
                                                       Integer minimum,
                                                       Integer maximum) {
        UserGoalFixProposalReq request = fillRequest(4);
        TierQuotaGoalRequestDTO goal = new TierQuotaGoalRequestDTO();
        goal.setType("count_ranges");
        goal.setUpdateMode(updateMode);
        goal.setSprint(bound(minimum, maximum));
        request.setTierQuotaGoal(goal);
        return request;
    }

    private TierQuotaGoalDTO rangeGoal(TierCountRangeDTO sprint,
                                       TierCountRangeDTO stable,
                                       TierCountRangeDTO protect) {
        TierQuotaGoalDTO goal = new TierQuotaGoalDTO();
        goal.setType("count_ranges");
        goal.setSprint(sprint);
        goal.setStable(stable);
        goal.setProtect(protect);
        return goal;
    }

    private TierCountRangeDTO bound(Integer minimum, Integer maximum) {
        TierCountRangeDTO result = new TierCountRangeDTO();
        result.setMinCount(minimum);
        result.setMaxCount(maximum);
        return result;
    }

    private PlanningStateDTO stateWithTierCounts(int sprint, int stable, int protect) {
        PlanningStateDTO state = state(12);
        state.getCandidatePoolState().setVolunteerModel("major");
        int index = 0;
        for (int count = 0; count < sprint; count++) {
            addTierVolunteer(state, "v" + index++, "冲");
        }
        for (int count = 0; count < stable; count++) {
            addTierVolunteer(state, "v" + index++, "稳");
        }
        for (int count = 0; count < protect; count++) {
            addTierVolunteer(state, "v" + index++, "保");
        }
        state.getConstraintState().getHardPlanningObjectives()
                .setSelectionTargetCount(sprint + stable + protect);
        return state;
    }

    private void addTierVolunteer(PlanningStateDTO state, String volunteerId, String tier) {
        CandidateItemDTO item = candidate(
                volunteerId, "学校" + volunteerId, "专业" + volunteerId, "类别", 80D);
        item.setTier(tier);
        state.getCandidatePoolState().getItems().add(item);
        state.getOrderedPlanState().getItems().add(
                orderedWithTier(volunteerId, item.getSchoolName(), item.getMajorName(), tier));
    }

    private PlanningUnitMajorDTO unitMajor(String volunteerId, String majorName) {
        PlanningUnitMajorDTO major = new PlanningUnitMajorDTO();
        major.setVolunteerId(volunteerId);
        major.setMajorName(majorName);
        return major;
    }
}
