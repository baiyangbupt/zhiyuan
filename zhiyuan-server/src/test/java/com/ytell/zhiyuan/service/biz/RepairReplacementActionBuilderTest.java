package com.ytell.zhiyuan.service.biz;

import com.google.common.collect.Lists;
import com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO;
import com.ytell.zhiyuan.model.dto.planning.CompensationActionDTO;
import com.ytell.zhiyuan.model.dto.planning.FixProposalActionDTO;
import com.ytell.zhiyuan.model.dto.planning.FixProposalDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedItemDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedUnitDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import com.ytell.zhiyuan.model.dto.planning.ReplacementPairDTO;
import com.ytell.zhiyuan.model.dto.planning.ReviewCheckDTO;
import org.junit.jupiter.api.Test;

import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

public class RepairReplacementActionBuilderTest {

    @Test
    void shouldConvertFullPlanStructuralAddActionToReplacementAction() {
        PlanningStateDTO state = fullMajorPlanState(false);
        FixProposalDTO proposal = structuralProposal("rebalance_tier_ratio", "rebalance_protect_ratio", "protect_1");

        RepairReplacementActionBuilder.populateStructuralReplacementActions(
                state, reviewCheck("ratio_distribution"), proposal,
                Lists.newArrayList(compensationAction("rebalance_protect_ratio", "protect_1")));

        assertEquals("ready", proposal.getStatus());
        assertEquals(1, proposal.getActions().size());
        FixProposalActionDTO action = proposal.getActions().get(0);
        assertEquals("replace_volunteers", action.getActionType());
        assertEquals(Lists.newArrayList("protect_1"), action.getCandidateVolunteerIds());
        assertEquals(1, action.getReplacementPairs().size());
        assertTrue(action.getDetail().contains("只是结构调整预览"));
        assertTrue(action.getDetail().contains("具体预览"));
        assertTrue(action.getDetail().contains("学校protect_1-专业protect_1"));
        assertTrue(action.getDetail().contains("录取率+"));
        assertTrue(action.getDetail().contains("推荐+"));
        ReplacementPairDTO pair = action.getReplacementPairs().get(0);
        assertEquals("protect_1", pair.getToVolunteerId());
        assertTrue(action.getRemoveVolunteerIds().contains(pair.getFromVolunteerId()));
        assertTrue(pair.getReasonCodes().contains("ratio_distribution"));
        assertTrue(pair.getReasonCodes().contains("rebalance_protect_ratio"));
    }

    @Test
    void shouldKeepAllStructuralReplacementPairsBeyondFive() {
        PlanningStateDTO state = fullMajorPlanStateWithManyReplacements(6);
        FixProposalDTO proposal = structuralProposal("rebalance_tier_ratio", "rebalance_protect_ratio",
                "protect_1", "protect_2", "protect_3", "protect_4", "protect_5", "protect_6");

        RepairReplacementActionBuilder.populateStructuralReplacementActions(
                state, reviewCheck("ratio_distribution"), proposal,
                Lists.newArrayList(compensationAction("rebalance_protect_ratio",
                        "protect_1", "protect_2", "protect_3", "protect_4", "protect_5", "protect_6")));

        assertEquals("ready", proposal.getStatus());
        assertEquals(1, proposal.getActions().size());
        FixProposalActionDTO action = proposal.getActions().get(0);
        assertEquals(6, action.getReplacementPairs().size());
        assertEquals(Integer.valueOf(6), action.getTotalReplacementPairCount());
        assertEquals(Integer.valueOf(6), action.getTotalVolunteerCount());
        assertTrue(action.getDetail().contains("另有 3 组配对未展开"));
    }

    @Test
    void shouldBlockFullPlanStructuralAddActionWhenReplacementSourceIsLocked() {
        PlanningStateDTO state = fullMajorPlanState(true);
        FixProposalDTO proposal = structuralProposal("rebalance_tier_ratio", "rebalance_protect_ratio", "protect_1");

        RepairReplacementActionBuilder.populateStructuralReplacementActions(
                state, reviewCheck("ratio_distribution"), proposal,
                Lists.newArrayList(compensationAction("rebalance_protect_ratio", "protect_1")));

        assertEquals("blocked", proposal.getStatus());
        assertFalse(Boolean.TRUE.equals(proposal.getRequiresConfirmation()));
        assertEquals(0, proposal.getActions().size());
        assertTrue(proposal.getBlockingReason().contains("不能只追加候选"));
        assertEquals(Lists.newArrayList("replacement_pair_missing"), proposal.getBlockingReasonCodes());
    }

    @Test
    void shouldBuildMajorGroupProbabilityGapReplacementWhenCompensationOnlyHasVolunteerIds() {
        PlanningStateDTO state = fullMajorGroupGapState();
        FixProposalDTO proposal = structuralProposal("fill_probability_gap", "fill_probability_gap", "unit_mid_major");
        ReviewCheckDTO check = reviewCheck("probability_gap");
        check.getAffectedUnitIds().addAll(Lists.newArrayList("unit_low", "unit_high"));

        RepairReplacementActionBuilder.populateStructuralReplacementActions(
                state, check, proposal,
                Lists.newArrayList(compensationAction("fill_probability_gap", "unit_mid_major")));

        assertEquals("ready", proposal.getStatus());
        assertEquals(1, proposal.getActions().size());
        FixProposalActionDTO action = proposal.getActions().get(0);
        assertEquals("replace_volunteers", action.getActionType());
        assertEquals(Lists.newArrayList("unit_mid"), action.getCandidateUnitIds());
        assertEquals(Lists.newArrayList("unit_mid_major"), action.getCandidateVolunteerIds());
        assertEquals(1, action.getReplacementPairs().size());
        assertEquals("unit_mid", action.getReplacementPairs().get(0).getToUnitId());
        assertEquals("unit_mid_major", action.getReplacementPairs().get(0).getToVolunteerId());
        assertTrue(action.getDetail().contains("只是结构调整预览"));
    }

    private PlanningStateDTO fullMajorPlanState(boolean lockSprintItems) {
        PlanningStateDTO state = new PlanningStateDTO();
        state.getCandidatePoolState().setVolunteerModel("major");
        state.getCandidatePoolState().setRequiredCount(3);
        state.getCandidatePoolState().setRequiredTierCounts(tierCounts(1, 1, 1));
        state.getOrderedPlanState().getItems().add(orderedItem("sprint_1", "冲", lockSprintItems));
        state.getOrderedPlanState().getItems().add(orderedItem("sprint_2", "冲", lockSprintItems));
        state.getOrderedPlanState().getItems().add(orderedItem("safe_1", "稳", false));
        state.getCandidatePoolState().setItems(Arrays.asList(
                candidate("sprint_1", "冲", 60D, 25D),
                candidate("sprint_2", "冲", 55D, 30D),
                candidate("safe_1", "稳", 80D, 60D),
                candidate("protect_1", "保", 90D, 85D)));
        return state;
    }

    private PlanningStateDTO fullMajorGroupGapState() {
        PlanningStateDTO state = new PlanningStateDTO();
        state.getCandidatePoolState().setVolunteerModel("majorGroup");
        state.getCandidatePoolState().setRequiredCount(3);
        state.getOrderedPlanState().getUnits().add(orderedUnit("unit_low", "冲", 20D, 80D, false));
        state.getOrderedPlanState().getUnits().add(orderedUnit("unit_high", "稳", 55D, 70D, false));
        state.getOrderedPlanState().getUnits().add(orderedUnit("unit_safe", "保", 85D, 90D, false));
        state.getOrderedPlanState().getItems().add(orderedItem("unit_low_major", "冲", false));
        state.getOrderedPlanState().getItems().add(orderedItem("unit_high_major", "稳", false));
        state.getOrderedPlanState().getItems().add(orderedItem("unit_safe_major", "保", false));
        state.getCandidatePoolState().setItems(Arrays.asList(
                candidate("unit_low_major", "冲", "unit_low", 80D, 20D),
                candidate("unit_high_major", "稳", "unit_high", 70D, 55D),
                candidate("unit_safe_major", "保", "unit_safe", 90D, 85D),
                candidate("unit_mid_major", "稳", "unit_mid", 88D, 38D)));
        return state;
    }

    private PlanningStateDTO fullMajorPlanStateWithManyReplacements(int count) {
        PlanningStateDTO state = new PlanningStateDTO();
        state.getCandidatePoolState().setVolunteerModel("major");
        state.getCandidatePoolState().setRequiredCount(count);
        state.getCandidatePoolState().setRequiredTierCounts(tierCounts(0, 0, count));
        java.util.List<CandidateItemDTO> candidates = Lists.newArrayList();
        for (int i = 1; i <= count; i++) {
            String sprintId = "sprint_" + i;
            String protectId = "protect_" + i;
            state.getOrderedPlanState().getItems().add(orderedItem(sprintId, "冲", false));
            candidates.add(candidate(sprintId, "冲", 60D - i, 20D + i));
            candidates.add(candidate(protectId, "保", 90D - i, 80D + i));
        }
        state.getCandidatePoolState().setItems(candidates);
        return state;
    }

    private FixProposalDTO structuralProposal(String strategy, String actionType, String volunteerId) {
        return structuralProposal(strategy, actionType, new String[]{volunteerId});
    }

    private FixProposalDTO structuralProposal(String strategy, String actionType, String... volunteerIds) {
        FixProposalDTO proposal = new FixProposalDTO();
        proposal.setStrategy(strategy);
        proposal.setStatus("ready");
        proposal.getActions().add(fixAction(actionType, volunteerIds));
        return proposal;
    }

    private FixProposalActionDTO fixAction(String actionType, String... volunteerIds) {
        FixProposalActionDTO action = new FixProposalActionDTO();
        action.setActionType(actionType);
        action.setCandidateVolunteerIds(Lists.newArrayList(volunteerIds));
        return action;
    }

    private CompensationActionDTO compensationAction(String type, String... volunteerIds) {
        CompensationActionDTO action = new CompensationActionDTO();
        action.setType(type);
        action.setVolunteerIds(Lists.newArrayList(volunteerIds));
        return action;
    }

    private ReviewCheckDTO reviewCheck(String code) {
        ReviewCheckDTO check = new ReviewCheckDTO();
        check.setCode(code);
        check.setLevel("warn");
        return check;
    }

    private Map<String, Integer> tierCounts(int sprint, int safe, int protect) {
        Map<String, Integer> counts = new LinkedHashMap<String, Integer>();
        counts.put("冲", sprint);
        counts.put("稳", safe);
        counts.put("保", protect);
        return counts;
    }

    private OrderedItemDTO orderedItem(String volunteerId, String tier, boolean locked) {
        OrderedItemDTO item = new OrderedItemDTO();
        item.setVolunteerId(volunteerId);
        item.setTier(tier);
        item.setSchoolName("学校" + volunteerId);
        item.setMajorName("专业" + volunteerId);
        item.setLocked(locked);
        return item;
    }

    private OrderedUnitDTO orderedUnit(String unitId,
                                       String tier,
                                       Double admissionRatio,
                                       Double finalScore,
                                       boolean locked) {
        OrderedUnitDTO unit = new OrderedUnitDTO();
        unit.setUnitId(unitId);
        unit.setTier(tier);
        unit.setSchoolName("学校" + unitId);
        unit.setAdmissionRatio(admissionRatio);
        unit.setFinalScore(finalScore);
        unit.setLocked(locked);
        return unit;
    }

    private CandidateItemDTO candidate(String volunteerId, String tier, Double finalScore, Double admissionRatio) {
        return candidate(volunteerId, tier, "unit_" + volunteerId, finalScore, admissionRatio);
    }

    private CandidateItemDTO candidate(String volunteerId,
                                       String tier,
                                       String unitId,
                                       Double finalScore,
                                       Double admissionRatio) {
        CandidateItemDTO candidate = new CandidateItemDTO();
        candidate.setVolunteerId(volunteerId);
        candidate.setTier(tier);
        candidate.setPlanSchoolDataId(unitId);
        candidate.setSchoolName("学校" + volunteerId);
        candidate.setMajorName("专业" + volunteerId);
        candidate.setFinalScore(finalScore);
        candidate.setAdmissionRatio(admissionRatio);
        candidate.setSchoolEnrollRatio(admissionRatio);
        return candidate;
    }
}
