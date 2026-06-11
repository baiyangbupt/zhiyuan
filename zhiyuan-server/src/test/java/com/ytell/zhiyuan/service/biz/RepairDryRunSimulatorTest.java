package com.ytell.zhiyuan.service.biz;

import com.google.common.collect.Lists;
import com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO;
import com.ytell.zhiyuan.model.dto.planning.FixProposalActionDTO;
import com.ytell.zhiyuan.model.dto.planning.FixProposalDTO;
import com.ytell.zhiyuan.model.dto.planning.FixProposalDryRunResultDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedItemDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedUnitDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import com.ytell.zhiyuan.model.dto.planning.ReviewCheckDTO;
import com.ytell.zhiyuan.model.dto.planning.ReplacementPairDTO;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

public class RepairDryRunSimulatorTest {

    @Test
    void shouldPopulateReplacementSnapshotForProfessionalPlan() {
        PlanningStateDTO state = baseState("major");
        state.getCandidatePoolState().getItems().add(candidate("old_major", "冲", "old_unit"));
        state.getCandidatePoolState().getItems().add(candidate("new_major", "保", "new_unit"));
        state.getOrderedPlanState().getItems().add(orderedItem("old_major", "冲"));

        FixProposalDTO proposal = new FixProposalDTO();
        proposal.setStrategy("rebalance_tier_ratio");
        FixProposalActionDTO action = new FixProposalActionDTO();
        action.setActionType("replace_volunteers");
        action.setRemoveVolunteerIds(Lists.newArrayList("old_major"));
        action.setCandidateVolunteerIds(Lists.newArrayList("new_major"));
        proposal.getActions().add(action);

        ReviewCheckDTO check = new ReviewCheckDTO();
        check.setAffectedVolunteerIds(Lists.newArrayList("old_major"));

        RepairDryRunSimulator.populate(state, proposal, check);

        FixProposalDryRunResultDTO dryRun = proposal.getDryRunResult();
        assertEquals("ready", dryRun.getStatus());
        assertEquals(Integer.valueOf(1), dryRun.getAffectedVolunteerCount());
        assertEquals(Integer.valueOf(1), dryRun.getAddVolunteerCount());
        assertEquals(Integer.valueOf(1), dryRun.getRemoveVolunteerCount());
        assertEquals(Integer.valueOf(1), dryRun.getBeforeVolunteerTotal());
        assertEquals(Integer.valueOf(1), dryRun.getAfterVolunteerTotal());
        assertEquals(Integer.valueOf(1), dryRun.getBeforeVolunteerTierCounts().get("冲"));
        assertEquals(Integer.valueOf(1), dryRun.getAfterVolunteerTierCounts().get("保"));
        assertEquals(Integer.valueOf(1), dryRun.getBeforeUnitTotal());
        assertEquals(Integer.valueOf(1), dryRun.getAfterUnitTotal());
    }

    @Test
    void shouldPopulateReplacementSnapshotFromReplacementPairsOnlyForProfessionalPlan() {
        PlanningStateDTO state = baseState("major");
        state.getCandidatePoolState().getItems().add(candidate("old_major", "冲", "old_unit"));
        state.getCandidatePoolState().getItems().add(candidate("new_major", "保", "new_unit"));
        state.getOrderedPlanState().getItems().add(orderedItem("old_major", "冲"));

        FixProposalDTO proposal = new FixProposalDTO();
        proposal.setStrategy("rebalance_tier_ratio");
        FixProposalActionDTO action = new FixProposalActionDTO();
        action.setActionType("replace_volunteers");
        ReplacementPairDTO pair = new ReplacementPairDTO();
        pair.setFromVolunteerId("old_major");
        pair.setToVolunteerId("new_major");
        action.getReplacementPairs().add(pair);
        proposal.getActions().add(action);

        RepairDryRunSimulator.populate(state, proposal, new ReviewCheckDTO());

        FixProposalDryRunResultDTO dryRun = proposal.getDryRunResult();
        assertEquals("ready", dryRun.getStatus());
        assertEquals(Integer.valueOf(1), dryRun.getAddVolunteerCount());
        assertEquals(Integer.valueOf(1), dryRun.getRemoveVolunteerCount());
        assertEquals(Lists.newArrayList("old_major"), Lists.newArrayList(dryRun.getBeforeVolunteerIds()));
        assertEquals(Lists.newArrayList("new_major"), Lists.newArrayList(dryRun.getAfterVolunteerIds()));
        assertEquals(Integer.valueOf(1), dryRun.getBeforeVolunteerTierCounts().get("冲"));
        assertEquals(Integer.valueOf(1), dryRun.getAfterVolunteerTierCounts().get("保"));
    }

    @Test
    void shouldPopulateReplacementSnapshotFromReplacementPairsOnlyForMajorGroupPlan() {
        PlanningStateDTO state = baseState("majorGroup");
        state.getCandidatePoolState().getItems().add(candidate("old_major", "冲", "old_unit"));
        state.getCandidatePoolState().getItems().add(candidate("new_major", "保", "new_unit"));
        state.getOrderedPlanState().getUnits().add(orderedUnit("old_unit", "冲"));
        state.getOrderedPlanState().getItems().add(orderedItem("old_major", "冲"));

        FixProposalDTO proposal = new FixProposalDTO();
        proposal.setStrategy("rebalance_tier_ratio");
        FixProposalActionDTO action = new FixProposalActionDTO();
        action.setActionType("replace_volunteers");
        ReplacementPairDTO pair = new ReplacementPairDTO();
        pair.setFromUnitId("old_unit");
        pair.setFromVolunteerId("old_major");
        pair.setToUnitId("new_unit");
        pair.setToVolunteerId("new_major");
        action.getReplacementPairs().add(pair);
        proposal.getActions().add(action);

        RepairDryRunSimulator.populate(state, proposal, new ReviewCheckDTO());

        FixProposalDryRunResultDTO dryRun = proposal.getDryRunResult();
        assertEquals("ready", dryRun.getStatus());
        assertEquals(Integer.valueOf(1), dryRun.getAddUnitCount());
        assertEquals(Integer.valueOf(1), dryRun.getRemoveUnitCount());
        assertEquals(Integer.valueOf(1), dryRun.getAddVolunteerCount());
        assertEquals(Integer.valueOf(1), dryRun.getRemoveVolunteerCount());
        assertEquals(Lists.newArrayList("old_unit"), Lists.newArrayList(dryRun.getBeforeUnitIds()));
        assertEquals(Lists.newArrayList("new_unit"), Lists.newArrayList(dryRun.getAfterUnitIds()));
        assertEquals(Lists.newArrayList("old_major"), Lists.newArrayList(dryRun.getBeforeVolunteerIds()));
        assertEquals(Lists.newArrayList("new_major"), Lists.newArrayList(dryRun.getAfterVolunteerIds()));
        assertEquals(Integer.valueOf(1), dryRun.getBeforeUnitTierCounts().get("冲"));
        assertEquals(Integer.valueOf(1), dryRun.getAfterUnitTierCounts().get("保"));
    }

    @Test
    void shouldBlockItemRiskReplacementWhenMajorGroupUnitCountWouldChange() {
        PlanningStateDTO state = baseState("majorGroup");
        state.getCandidatePoolState().getItems().add(candidate("old_major", "稳", "unit_a"));
        state.getCandidatePoolState().getItems().add(candidate("kept_major", "稳", "unit_a"));
        state.getCandidatePoolState().getItems().add(candidate("new_major", "稳", "unit_b"));
        state.getOrderedPlanState().getUnits().add(orderedUnit("unit_a", "稳"));
        state.getOrderedPlanState().getItems().add(orderedItem("old_major", "稳"));
        state.getOrderedPlanState().getItems().add(orderedItem("kept_major", "稳"));

        FixProposalDTO proposal = new FixProposalDTO();
        proposal.setStrategy("replace_risk_items");
        FixProposalActionDTO action = new FixProposalActionDTO();
        action.setActionType("replace_volunteers");
        action.setSourceCheckCode("high_tuition");
        ReplacementPairDTO pair = new ReplacementPairDTO();
        pair.setFromUnitId("unit_a");
        pair.setFromVolunteerId("old_major");
        pair.setToUnitId("unit_b");
        pair.setToVolunteerId("new_major");
        action.getReplacementPairs().add(pair);
        proposal.getActions().add(action);

        ReviewCheckDTO check = new ReviewCheckDTO();
        check.setCode("high_tuition");
        check.setScopeKind("item");
        check.setAffectedUnitIds(Lists.newArrayList("unit_a"));
        check.setAffectedVolunteerIds(Lists.newArrayList("old_major"));

        RepairDryRunSimulator.populate(state, proposal, check);

        FixProposalDryRunResultDTO dryRun = proposal.getDryRunResult();
        assertEquals("blocked", proposal.getStatus());
        assertEquals("blocked", dryRun.getStatus());
        assertTrue(dryRun.getMessage().contains("专业组数量"));
        assertEquals(Integer.valueOf(0), dryRun.getRemoveUnitCount());
        assertEquals(Integer.valueOf(0), dryRun.getAddUnitCount());
        assertEquals(Integer.valueOf(1), dryRun.getBeforeUnitTotal());
        assertEquals(Integer.valueOf(2), dryRun.getAfterUnitTotal());
        assertFalse(dryRun.getAfterVolunteerIds().contains("old_major"));
        assertTrue(dryRun.getAfterVolunteerIds().contains("kept_major"));
        assertTrue(dryRun.getAfterVolunteerIds().contains("new_major"));
    }

    @Test
    void shouldKeepUnitTotalWhenSimulatingMajorGroupInnerSafetyAction() {
        PlanningStateDTO state = baseState("majorGroup");
        CandidateItemDTO oldMajor1 = candidate("old_major_1", "保", "unit_a");
        oldMajor1.setAdmissionRatio(10D);
        oldMajor1.setSchoolEnrollRatio(20D);
        CandidateItemDTO oldMajor2 = candidate("old_major_2", "保", "unit_a");
        oldMajor2.setAdmissionRatio(12D);
        oldMajor2.setSchoolEnrollRatio(20D);
        CandidateItemDTO newMajor1 = candidate("new_major_1", "保", "unit_a");
        newMajor1.setAdmissionRatio(25D);
        newMajor1.setSchoolEnrollRatio(20D);
        state.getCandidatePoolState().getItems().add(oldMajor1);
        state.getCandidatePoolState().getItems().add(oldMajor2);
        state.getCandidatePoolState().getItems().add(newMajor1);
        state.getOrderedPlanState().getUnits().add(orderedUnit("unit_a", "保"));
        state.getOrderedPlanState().getItems().add(orderedItem("old_major_1", "保"));
        state.getOrderedPlanState().getItems().add(orderedItem("old_major_2", "保"));

        FixProposalDTO proposal = new FixProposalDTO();
        proposal.setStrategy("adjust_major_group_inner_safety");
        FixProposalActionDTO action = new FixProposalActionDTO();
        action.setActionType("adjust_major_group_inner_safety");
        action.setRemoveVolunteerIds(Lists.newArrayList("old_major_2"));
        action.setCandidateVolunteerIds(Lists.newArrayList("new_major_1"));
        proposal.getActions().add(action);

        ReviewCheckDTO check = new ReviewCheckDTO();
        check.setAffectedUnitIds(Lists.newArrayList("unit_a"));
        check.setAffectedVolunteerIds(Lists.newArrayList("old_major_2"));

        RepairDryRunSimulator.populate(state, proposal, check);

        FixProposalDryRunResultDTO dryRun = proposal.getDryRunResult();
        assertEquals("ready", dryRun.getStatus());
        assertEquals(Integer.valueOf(1), dryRun.getAffectedUnitCount());
        assertEquals(Integer.valueOf(1), dryRun.getAddVolunteerCount());
        assertEquals(Integer.valueOf(1), dryRun.getRemoveVolunteerCount());
        assertEquals(Integer.valueOf(2), dryRun.getBeforeVolunteerTotal());
        assertEquals(Integer.valueOf(2), dryRun.getAfterVolunteerTotal());
        assertEquals(Integer.valueOf(1), dryRun.getBeforeUnitTotal());
        assertEquals(Integer.valueOf(1), dryRun.getAfterUnitTotal());
        assertEquals(Integer.valueOf(1), dryRun.getBeforeUnitTierCounts().get("保"));
        assertEquals(Integer.valueOf(1), dryRun.getAfterUnitTierCounts().get("保"));
    }

    @Test
    void shouldKeepCountValidationReadyWhenAddingMissingVolunteer() {
        PlanningStateDTO state = baseState("major");
        state.getCandidatePoolState().setRequiredCount(2);
        state.getCandidatePoolState().getItems().add(candidate("old_major", "稳", "old_unit"));
        state.getCandidatePoolState().getItems().add(candidate("new_major", "稳", "new_unit"));
        state.getOrderedPlanState().getItems().add(orderedItem("old_major", "稳"));

        FixProposalDTO proposal = new FixProposalDTO();
        proposal.setStrategy("fill_missing_count");
        FixProposalActionDTO action = new FixProposalActionDTO();
        action.setActionType("fill_total_count");
        action.setVolunteerIds(Lists.newArrayList("new_major"));
        proposal.getActions().add(action);

        ReviewCheckDTO check = new ReviewCheckDTO();
        check.setCode("count_validation");

        RepairDryRunSimulator.populate(state, proposal, check);

        assertEquals("ready", proposal.getStatus());
        assertEquals("ready", proposal.getDryRunResult().getStatus());
        assertEquals(Integer.valueOf(1), proposal.getDryRunResult().getBeforeVolunteerTotal());
        assertEquals(Integer.valueOf(2), proposal.getDryRunResult().getAfterVolunteerTotal());
    }

    @Test
    void shouldBlockCountValidationWhenPreviewDoesNotMoveTowardRequiredCount() {
        PlanningStateDTO state = baseState("major");
        state.getCandidatePoolState().setRequiredCount(2);
        state.getCandidatePoolState().getItems().add(candidate("old_major", "稳", "old_unit"));
        state.getOrderedPlanState().getItems().add(orderedItem("old_major", "稳"));

        FixProposalDTO proposal = new FixProposalDTO();
        proposal.setStrategy("fill_missing_count");
        ReviewCheckDTO check = new ReviewCheckDTO();
        check.setCode("count_validation");

        RepairDryRunSimulator.populate(state, proposal, check);

        assertEquals("blocked", proposal.getStatus());
        assertEquals("blocked", proposal.getDryRunResult().getStatus());
        assertTrue(proposal.getDryRunResult().getMessage().contains("数量更接近官方要求"));
        assertEquals(Lists.newArrayList("objective_validation_not_improved"), proposal.getBlockingReasonCodes());

        RepairProposalStateBuilder.populateCandidateShortages(state, check, proposal);

        assertEquals(1, proposal.getCandidateShortages().size());
        assertEquals("objective_validation", proposal.getCandidateShortages().get(0).getScope());
        assertEquals("objective_validation_not_improved", proposal.getCandidateShortages().get(0).getReasonCode());
    }

    @Test
    void shouldUseCannotSatisfyBlockingReasonAsDryRunMessage() {
        PlanningStateDTO state = baseState("major");
        FixProposalDTO proposal = new FixProposalDTO();
        proposal.setStrategy("cannot_satisfy");
        proposal.setStatus("blocked");
        proposal.setBlockingReason("当前候选里缺少断层区间的可用志愿，暂时无法补齐录取率梯度。");

        RepairDryRunSimulator.populate(state, proposal, new ReviewCheckDTO());

        assertEquals("blocked", proposal.getDryRunResult().getStatus());
        assertEquals(proposal.getBlockingReason(), proposal.getDryRunResult().getMessage());
        assertTrue(proposal.getDryRunResult().getWarnings().stream()
                .anyMatch(warning -> warning.contains("放宽约束")));
    }

    @Test
    void shouldBlockItemRiskProposalWhenAffectedCandidateStillPresent() {
        PlanningStateDTO state = baseState("major");
        state.getCandidatePoolState().getItems().add(candidate("risk_major", "稳", "risk_unit"));
        state.getCandidatePoolState().getItems().add(candidate("other_major", "稳", "other_unit"));
        state.getOrderedPlanState().getItems().add(orderedItem("risk_major", "稳"));
        state.getOrderedPlanState().getItems().add(orderedItem("other_major", "稳"));

        FixProposalDTO proposal = new FixProposalDTO();
        proposal.setStrategy("remove_risk_items");
        FixProposalActionDTO action = new FixProposalActionDTO();
        action.setActionType("remove_volunteers");
        action.setVolunteerIds(Lists.newArrayList("other_major"));
        proposal.getActions().add(action);

        ReviewCheckDTO check = new ReviewCheckDTO();
        check.setCode("high_tuition");
        check.setScopeKind("item");
        check.setAffectedVolunteerIds(Lists.newArrayList("risk_major"));

        RepairDryRunSimulator.populate(state, proposal, check);

        assertEquals("blocked", proposal.getStatus());
        assertEquals("blocked", proposal.getDryRunResult().getStatus());
        assertTrue(proposal.getBlockingReason().contains("风险志愿"));
    }

    @Test
    void shouldBlockMajorGroupInnerSafetyWhenAddedMajorIsNotSafety() {
        PlanningStateDTO state = baseState("majorGroup");
        CandidateItemDTO oldMajor = candidate("old_major", "保", "unit_a");
        oldMajor.setAdmissionRatio(10D);
        oldMajor.setSchoolEnrollRatio(20D);
        CandidateItemDTO newMajor = candidate("new_major", "保", "unit_a");
        newMajor.setAdmissionRatio(15D);
        newMajor.setSchoolEnrollRatio(20D);
        state.getCandidatePoolState().getItems().add(oldMajor);
        state.getCandidatePoolState().getItems().add(newMajor);
        state.getOrderedPlanState().getUnits().add(orderedUnit("unit_a", "保"));
        state.getOrderedPlanState().getItems().add(orderedItem("old_major", "保"));

        FixProposalDTO proposal = new FixProposalDTO();
        proposal.setStrategy("adjust_major_group_inner_safety");
        FixProposalActionDTO action = new FixProposalActionDTO();
        action.setActionType("adjust_major_group_inner_safety");
        action.setRemoveVolunteerIds(Lists.newArrayList("old_major"));
        action.setCandidateVolunteerIds(Lists.newArrayList("new_major"));
        proposal.getActions().add(action);

        ReviewCheckDTO check = new ReviewCheckDTO();
        check.setCode("group_inner_safety_guard");
        check.setAffectedUnitIds(Lists.newArrayList("unit_a"));
        check.setAffectedVolunteerIds(Lists.newArrayList("old_major"));

        RepairDryRunSimulator.populate(state, proposal, check);

        assertEquals("blocked", proposal.getStatus());
        assertEquals("blocked", proposal.getDryRunResult().getStatus());
        assertTrue(proposal.getBlockingReason().contains("组内安全垫"));
    }

    @Test
    void shouldWarnWhenAddedCandidateConflictsWithConstraintsAndAvoidPreferences() {
        PlanningStateDTO state = baseState("major");
        state.getConstraintState().getHardConstraints().getMustExcludeRegions().add("江苏");
        state.getConstraintState().getSoftPreferences().getAvoidMajors().add("会计");
        CandidateItemDTO oldCandidate = candidate("old_major", "稳", "old_unit");
        CandidateItemDTO newCandidate = candidate("new_major", "稳", "new_unit");
        newCandidate.setProvinceName("江苏");
        newCandidate.setMajorName("会计学");
        state.getCandidatePoolState().getItems().add(oldCandidate);
        state.getCandidatePoolState().getItems().add(newCandidate);
        state.getOrderedPlanState().getItems().add(orderedItem("old_major", "稳"));

        FixProposalDTO proposal = new FixProposalDTO();
        proposal.setStrategy("rebalance_tier_ratio");
        FixProposalActionDTO action = new FixProposalActionDTO();
        action.setActionType("replace_volunteers");
        action.setRemoveVolunteerIds(Lists.newArrayList("old_major"));
        action.setCandidateVolunteerIds(Lists.newArrayList("new_major"));
        proposal.getActions().add(action);

        RepairDryRunSimulator.populate(state, proposal, new ReviewCheckDTO());

        assertTrue(proposal.getDryRunResult().getWarnings().stream()
                .anyMatch(warning -> warning.contains("硬性要求") && warning.contains("江苏")));
        assertTrue(proposal.getDryRunResult().getWarnings().stream()
                .anyMatch(warning -> warning.contains("不优先方向") && warning.contains("会计")));
    }

    @Test
    void shouldWarnWhenRemovingConstraintOrPreferenceMatchedCandidate() {
        PlanningStateDTO state = baseState("major");
        state.getConstraintState().getHardConstraints().getMustIncludeSchools().add("南京大学");
        state.getConstraintState().getSoftPreferences().getPreferMajors().add("法学");
        CandidateItemDTO oldCandidate = candidate("old_major", "稳", "old_unit");
        oldCandidate.setSchoolName("南京大学");
        oldCandidate.setMajorName("法学");
        CandidateItemDTO newCandidate = candidate("new_major", "稳", "new_unit");
        state.getCandidatePoolState().getItems().add(oldCandidate);
        state.getCandidatePoolState().getItems().add(newCandidate);
        state.getOrderedPlanState().getItems().add(orderedItem("old_major", "稳"));

        FixProposalDTO proposal = new FixProposalDTO();
        proposal.setStrategy("rebalance_tier_ratio");
        FixProposalActionDTO action = new FixProposalActionDTO();
        action.setActionType("replace_volunteers");
        action.setRemoveVolunteerIds(Lists.newArrayList("old_major"));
        action.setCandidateVolunteerIds(Lists.newArrayList("new_major"));
        proposal.getActions().add(action);

        RepairDryRunSimulator.populate(state, proposal, new ReviewCheckDTO());

        assertTrue(proposal.getDryRunResult().getWarnings().stream()
                .anyMatch(warning -> warning.contains("硬性要求命中项") && warning.contains("南京大学")));
        assertTrue(proposal.getDryRunResult().getWarnings().stream()
                .anyMatch(warning -> warning.contains("偏好命中项") && warning.contains("法学")));
    }

    @Test
    void shouldWarnWhenAddedCandidateIntroducesKnownRisks() {
        PlanningStateDTO state = baseState("major");
        CandidateItemDTO oldCandidate = candidate("old_major", "稳", "old_unit");
        oldCandidate.setFinalScore(90D);
        oldCandidate.setHotIndex(80D);
        oldCandidate.setSchoolRank(100);
        CandidateItemDTO newCandidate = candidate("new_major", "稳", "new_unit");
        newCandidate.setMajorName("软件工程(中外合作)");
        newCandidate.setTuitionPerYear(35000);
        newCandidate.setFinalScore(70D);
        newCandidate.setHotIndex(60D);
        newCandidate.setSchoolRank(180);
        newCandidate.getMustSubjects().add("色盲限报");
        newCandidate.getReasonCodes().add("地方专项");
        state.getCandidatePoolState().getItems().add(oldCandidate);
        state.getCandidatePoolState().getItems().add(newCandidate);
        state.getOrderedPlanState().getItems().add(orderedItem("old_major", "稳"));

        FixProposalDTO proposal = new FixProposalDTO();
        proposal.setStrategy("rebalance_tier_ratio");
        FixProposalActionDTO action = new FixProposalActionDTO();
        action.setActionType("replace_volunteers");
        action.setRemoveVolunteerIds(Lists.newArrayList("old_major"));
        action.setCandidateVolunteerIds(Lists.newArrayList("new_major"));
        proposal.getActions().add(action);

        RepairDryRunSimulator.populate(state, proposal, new ReviewCheckDTO());

        FixProposalDryRunResultDTO dryRun = proposal.getDryRunResult();
        assertEquals(Double.valueOf(90D), dryRun.getBeforeAverageFinalScore());
        assertEquals(Double.valueOf(70D), dryRun.getAfterAverageFinalScore());
        assertEquals(Double.valueOf(80D), dryRun.getBeforeAverageHotIndex());
        assertEquals(Double.valueOf(60D), dryRun.getAfterAverageHotIndex());
        assertEquals(Double.valueOf(100D), dryRun.getBeforeAverageSchoolRank());
        assertEquals(Double.valueOf(180D), dryRun.getAfterAverageSchoolRank());
        assertTrue(proposal.getDryRunResult().getWarnings().stream()
                .anyMatch(warning -> warning.contains("新增项需要额外确认")
                        && warning.contains("高收费")
                        && warning.contains("限报")
                        && warning.contains("特殊类型")
                        && warning.contains("中外合作")));
        assertTrue(dryRun.getWarnings().stream()
                .anyMatch(warning -> warning.contains("平均推荐系数可能下降") && warning.contains("90.0 -> 70.0")));
        assertTrue(dryRun.getWarnings().stream()
                .anyMatch(warning -> warning.contains("平均专业热度可能下降") && warning.contains("80.0 -> 60.0")));
        assertTrue(dryRun.getWarnings().stream()
                .anyMatch(warning -> warning.contains("平均院校排名可能下降") && warning.contains("100.0 -> 180.0")));
    }

    @Test
    void shouldNotWarnWhenAddedCandidateOnlyHasScoreRiskFlags() {
        PlanningStateDTO state = baseState("major");
        CandidateItemDTO oldCandidate = candidate("old_major", "稳", "old_unit");
        oldCandidate.setFinalScore(80D);
        oldCandidate.setHotIndex(70D);
        oldCandidate.setSchoolRank(120);
        CandidateItemDTO newCandidate = candidate("new_major", "稳", "new_unit");
        newCandidate.setFinalScore(80D);
        newCandidate.setHotIndex(70D);
        newCandidate.setSchoolRank(120);
        newCandidate.getRiskFlags().add("special_score:0");
        newCandidate.getRiskFlags().add("degree_score:0");
        newCandidate.getRiskFlags().add("evaluate_score:0");
        state.getCandidatePoolState().getItems().add(oldCandidate);
        state.getCandidatePoolState().getItems().add(newCandidate);
        state.getOrderedPlanState().getItems().add(orderedItem("old_major", "稳"));

        FixProposalDTO proposal = new FixProposalDTO();
        proposal.setStrategy("rebalance_tier_ratio");
        FixProposalActionDTO action = new FixProposalActionDTO();
        action.setActionType("replace_volunteers");
        action.setRemoveVolunteerIds(Lists.newArrayList("old_major"));
        action.setCandidateVolunteerIds(Lists.newArrayList("new_major"));
        proposal.getActions().add(action);

        RepairDryRunSimulator.populate(state, proposal, new ReviewCheckDTO());

        assertTrue(proposal.getDryRunResult().getWarnings().stream()
                .noneMatch(warning -> warning.contains("特殊类型招生") || warning.contains("special_score")));
    }

    @Test
    void shouldKeepTierRatioPreviewWhenDryRunMovesTowardRequiredTierCounts() {
        PlanningStateDTO state = baseState("major");
        state.getCandidatePoolState().getRequiredTierCounts().put("冲", 1);
        state.getCandidatePoolState().getRequiredTierCounts().put("稳", 1);
        state.getCandidatePoolState().getRequiredTierCounts().put("保", 1);
        state.getCandidatePoolState().getItems().add(candidate("sprint_1", "冲", "unit_sprint_1"));
        state.getCandidatePoolState().getItems().add(candidate("sprint_2", "冲", "unit_sprint_2"));
        state.getCandidatePoolState().getItems().add(candidate("safe_1", "稳", "unit_safe"));
        state.getCandidatePoolState().getItems().add(candidate("protect_1", "保", "unit_protect"));
        state.getOrderedPlanState().getItems().add(orderedItem("sprint_1", "冲"));
        state.getOrderedPlanState().getItems().add(orderedItem("sprint_2", "冲"));
        state.getOrderedPlanState().getItems().add(orderedItem("safe_1", "稳"));

        FixProposalDTO proposal = new FixProposalDTO();
        proposal.setStrategy("rebalance_tier_ratio");
        proposal.setStatus("preview_only");
        FixProposalActionDTO action = new FixProposalActionDTO();
        action.setActionType("replace_volunteers");
        action.setRemoveVolunteerIds(Lists.newArrayList("sprint_2"));
        action.setCandidateVolunteerIds(Lists.newArrayList("protect_1"));
        proposal.getActions().add(action);
        ReviewCheckDTO check = new ReviewCheckDTO();
        check.setCode("ratio_distribution");

        RepairDryRunSimulator.populate(state, proposal, check);

        assertEquals("preview_only", proposal.getStatus());
        assertEquals("preview_only", proposal.getDryRunResult().getStatus());
        assertEquals(Integer.valueOf(1), proposal.getDryRunResult().getAfterVolunteerTierCounts().get("冲"));
        assertEquals(Integer.valueOf(1), proposal.getDryRunResult().getAfterVolunteerTierCounts().get("稳"));
        assertEquals(Integer.valueOf(1), proposal.getDryRunResult().getAfterVolunteerTierCounts().get("保"));
        assertTrue(proposal.getDryRunResult().getWarnings().stream()
                .noneMatch(warning -> warning.contains("冲稳保配比")));
    }

    @Test
    void shouldWarnMajorGroupTierRatioPreviewWhenDryRunDoesNotMoveTowardRequiredTierCounts() {
        PlanningStateDTO state = baseState("majorGroup");
        state.getCandidatePoolState().getRequiredTierCounts().put("冲", 1);
        state.getCandidatePoolState().getRequiredTierCounts().put("稳", 1);
        state.getCandidatePoolState().getRequiredTierCounts().put("保", 1);
        state.getCandidatePoolState().getItems().add(candidate("sprint_major", "冲", "unit_sprint"));
        state.getCandidatePoolState().getItems().add(candidate("safe_major", "稳", "unit_safe"));
        state.getCandidatePoolState().getItems().add(candidate("safe_replacement_major", "稳", "unit_safe_replacement"));
        state.getOrderedPlanState().getUnits().add(orderedUnit("unit_sprint", "冲"));
        state.getOrderedPlanState().getUnits().add(orderedUnit("unit_safe", "稳"));
        state.getOrderedPlanState().getItems().add(orderedItem("sprint_major", "冲"));
        state.getOrderedPlanState().getItems().add(orderedItem("safe_major", "稳"));

        FixProposalDTO proposal = new FixProposalDTO();
        proposal.setStrategy("rebalance_tier_ratio");
        proposal.setStatus("preview_only");
        FixProposalActionDTO action = new FixProposalActionDTO();
        action.setActionType("replace_volunteers");
        action.setRemoveUnitIds(Lists.newArrayList("unit_safe"));
        action.setRemoveVolunteerIds(Lists.newArrayList("safe_major"));
        action.setCandidateUnitIds(Lists.newArrayList("unit_safe_replacement"));
        action.setCandidateVolunteerIds(Lists.newArrayList("safe_replacement_major"));
        proposal.getActions().add(action);
        ReviewCheckDTO check = new ReviewCheckDTO();
        check.setCode("ratio_distribution");

        RepairDryRunSimulator.populate(state, proposal, check);

        assertEquals("preview_only", proposal.getStatus());
        assertEquals("preview_only", proposal.getDryRunResult().getStatus());
        assertTrue(proposal.getDryRunResult().getWarnings().stream()
                .anyMatch(warning -> warning.contains("没有让冲稳保配比更接近目标")));
    }

    @Test
    void shouldKeepProbabilityGapPreviewWhenDryRunShrinksGap() {
        PlanningStateDTO state = baseState("major");
        CandidateItemDTO low = candidate("selected_low", "冲", "unit_low");
        low.setAdmissionRatio(20D);
        CandidateItemDTO high = candidate("selected_high", "稳", "unit_high");
        high.setAdmissionRatio(50D);
        CandidateItemDTO filler = candidate("gap_filler", "稳", "unit_filler");
        filler.setAdmissionRatio(35D);
        state.getCandidatePoolState().getItems().add(low);
        state.getCandidatePoolState().getItems().add(high);
        state.getCandidatePoolState().getItems().add(filler);
        state.getOrderedPlanState().getItems().add(orderedItem("selected_low", "冲"));
        state.getOrderedPlanState().getItems().add(orderedItem("selected_high", "稳"));

        FixProposalDTO proposal = new FixProposalDTO();
        proposal.setStrategy("fill_probability_gap");
        proposal.setStatus("preview_only");
        FixProposalActionDTO action = new FixProposalActionDTO();
        action.setActionType("fill_probability_gap");
        action.setVolunteerIds(Lists.newArrayList("gap_filler"));
        proposal.getActions().add(action);
        ReviewCheckDTO check = new ReviewCheckDTO();
        check.setCode("probability_gap");

        RepairDryRunSimulator.populate(state, proposal, check);

        assertEquals("preview_only", proposal.getStatus());
        assertEquals("preview_only", proposal.getDryRunResult().getStatus());
        assertEquals(Lists.newArrayList("selected_low", "selected_high", "gap_filler"),
                Lists.newArrayList(proposal.getDryRunResult().getAfterVolunteerIds()));
        assertTrue(proposal.getDryRunResult().getWarnings().stream()
                .noneMatch(warning -> warning.contains("梯度断层")));
    }

    @Test
    void shouldWarnProbabilityGapPreviewWhenDryRunDoesNotShrinkGap() {
        PlanningStateDTO state = baseState("major");
        CandidateItemDTO low = candidate("selected_low", "冲", "unit_low");
        low.setAdmissionRatio(20D);
        CandidateItemDTO high = candidate("selected_high", "稳", "unit_high");
        high.setAdmissionRatio(50D);
        CandidateItemDTO outside = candidate("outside", "保", "unit_outside");
        outside.setAdmissionRatio(80D);
        state.getCandidatePoolState().getItems().add(low);
        state.getCandidatePoolState().getItems().add(high);
        state.getCandidatePoolState().getItems().add(outside);
        state.getOrderedPlanState().getItems().add(orderedItem("selected_low", "冲"));
        state.getOrderedPlanState().getItems().add(orderedItem("selected_high", "稳"));

        FixProposalDTO proposal = new FixProposalDTO();
        proposal.setStrategy("fill_probability_gap");
        proposal.setStatus("preview_only");
        FixProposalActionDTO action = new FixProposalActionDTO();
        action.setActionType("fill_probability_gap");
        action.setVolunteerIds(Lists.newArrayList("outside"));
        proposal.getActions().add(action);
        ReviewCheckDTO check = new ReviewCheckDTO();
        check.setCode("probability_gap");

        RepairDryRunSimulator.populate(state, proposal, check);

        assertEquals("preview_only", proposal.getStatus());
        assertEquals("preview_only", proposal.getDryRunResult().getStatus());
        assertTrue(proposal.getDryRunResult().getWarnings().stream()
                .anyMatch(warning -> warning.contains("没有缩小录取率梯度断层")));
    }

    @Test
    void shouldKeepMajorGroupProbabilityGapPreviewWhenDryRunShrinksUnitGap() {
        PlanningStateDTO state = baseState("majorGroup");
        CandidateItemDTO low = candidate("low_major", "冲", "unit_low");
        low.setAdmissionRatio(22D);
        low.setSchoolEnrollRatio(20D);
        CandidateItemDTO high = candidate("high_major", "稳", "unit_high");
        high.setAdmissionRatio(48D);
        high.setSchoolEnrollRatio(50D);
        CandidateItemDTO filler = candidate("filler_major", "稳", "unit_filler");
        filler.setAdmissionRatio(34D);
        filler.setSchoolEnrollRatio(35D);
        state.getCandidatePoolState().getItems().add(low);
        state.getCandidatePoolState().getItems().add(high);
        state.getCandidatePoolState().getItems().add(filler);
        state.getOrderedPlanState().getUnits().add(orderedUnit("unit_low", "冲"));
        state.getOrderedPlanState().getUnits().add(orderedUnit("unit_high", "稳"));
        state.getOrderedPlanState().getItems().add(orderedItem("low_major", "冲"));
        state.getOrderedPlanState().getItems().add(orderedItem("high_major", "稳"));

        FixProposalDTO proposal = new FixProposalDTO();
        proposal.setStrategy("fill_probability_gap");
        proposal.setStatus("preview_only");
        FixProposalActionDTO action = new FixProposalActionDTO();
        action.setActionType("fill_probability_gap");
        action.setUnitIds(Lists.newArrayList("unit_filler"));
        action.setVolunteerIds(Lists.newArrayList("filler_major"));
        proposal.getActions().add(action);
        ReviewCheckDTO check = new ReviewCheckDTO();
        check.setCode("probability_gap");

        RepairDryRunSimulator.populate(state, proposal, check);

        assertEquals("preview_only", proposal.getStatus());
        assertEquals("preview_only", proposal.getDryRunResult().getStatus());
        assertEquals(Lists.newArrayList("unit_low", "unit_high", "unit_filler"),
                Lists.newArrayList(proposal.getDryRunResult().getAfterUnitIds()));
        assertTrue(proposal.getDryRunResult().getWarnings().stream()
                .noneMatch(warning -> warning.contains("梯度断层")));
    }

    @Test
    void shouldWarnMajorGroupProbabilityGapPreviewWhenDryRunDoesNotShrinkUnitGap() {
        PlanningStateDTO state = baseState("majorGroup");
        CandidateItemDTO low = candidate("low_major", "冲", "unit_low");
        low.setAdmissionRatio(22D);
        low.setSchoolEnrollRatio(20D);
        CandidateItemDTO high = candidate("high_major", "稳", "unit_high");
        high.setAdmissionRatio(48D);
        high.setSchoolEnrollRatio(50D);
        CandidateItemDTO outside = candidate("outside_major", "保", "unit_outside");
        outside.setAdmissionRatio(78D);
        outside.setSchoolEnrollRatio(80D);
        state.getCandidatePoolState().getItems().add(low);
        state.getCandidatePoolState().getItems().add(high);
        state.getCandidatePoolState().getItems().add(outside);
        state.getOrderedPlanState().getUnits().add(orderedUnit("unit_low", "冲"));
        state.getOrderedPlanState().getUnits().add(orderedUnit("unit_high", "稳"));
        state.getOrderedPlanState().getItems().add(orderedItem("low_major", "冲"));
        state.getOrderedPlanState().getItems().add(orderedItem("high_major", "稳"));

        FixProposalDTO proposal = new FixProposalDTO();
        proposal.setStrategy("fill_probability_gap");
        proposal.setStatus("preview_only");
        FixProposalActionDTO action = new FixProposalActionDTO();
        action.setActionType("fill_probability_gap");
        action.setUnitIds(Lists.newArrayList("unit_outside"));
        action.setVolunteerIds(Lists.newArrayList("outside_major"));
        proposal.getActions().add(action);
        ReviewCheckDTO check = new ReviewCheckDTO();
        check.setCode("probability_gap");

        RepairDryRunSimulator.populate(state, proposal, check);

        assertEquals("preview_only", proposal.getStatus());
        assertEquals("preview_only", proposal.getDryRunResult().getStatus());
        assertTrue(proposal.getDryRunResult().getWarnings().stream()
                .anyMatch(warning -> warning.contains("没有缩小录取率梯度断层")));
    }

    @Test
    void shouldKeepSortByProbabilityReadyWhenDryRunReducesInversions() {
        PlanningStateDTO state = baseState("major");
        CandidateItemDTO highBeforeLow = candidate("high_before_low", "稳", "unit_high");
        highBeforeLow.setAdmissionRatio(60D);
        CandidateItemDTO low = candidate("low", "冲", "unit_low");
        low.setAdmissionRatio(20D);
        CandidateItemDTO protect = candidate("protect", "保", "unit_protect");
        protect.setAdmissionRatio(80D);
        state.getCandidatePoolState().getItems().add(highBeforeLow);
        state.getCandidatePoolState().getItems().add(low);
        state.getCandidatePoolState().getItems().add(protect);
        state.getOrderedPlanState().getItems().add(orderedItem("high_before_low", "稳"));
        state.getOrderedPlanState().getItems().add(orderedItem("low", "冲"));
        state.getOrderedPlanState().getItems().add(orderedItem("protect", "保"));

        FixProposalDTO proposal = new FixProposalDTO();
        proposal.setStrategy("sort_by_probability");
        ReviewCheckDTO check = new ReviewCheckDTO();
        check.setCode("probability_inversion");

        RepairDryRunSimulator.populate(state, proposal, check);

        assertEquals("ready", proposal.getStatus());
        assertEquals("ready", proposal.getDryRunResult().getStatus());
        assertEquals(Lists.newArrayList("high_before_low", "low", "protect"),
                Lists.newArrayList(proposal.getDryRunResult().getBeforeVolunteerIds()));
        assertEquals(Lists.newArrayList("low", "high_before_low", "protect"),
                Lists.newArrayList(proposal.getDryRunResult().getAfterVolunteerIds()));
    }

    @Test
    void shouldIgnoreHistoricalPinnedItemWhenSimulatingSortByProbability() {
        PlanningStateDTO state = baseState("major");
        CandidateItemDTO pinnedHigh = candidate("pinned_high", "稳", "unit_high");
        pinnedHigh.setAdmissionRatio(60D);
        CandidateItemDTO low = candidate("low", "冲", "unit_low");
        low.setAdmissionRatio(20D);
        state.getCandidatePoolState().getItems().add(pinnedHigh);
        state.getCandidatePoolState().getItems().add(low);
        OrderedItemDTO pinnedItem = orderedItem("pinned_high", "稳");
        pinnedItem.setPinned(true);
        pinnedItem.setPinnedPosition(1);
        state.getOrderedPlanState().getItems().add(pinnedItem);
        state.getOrderedPlanState().getItems().add(orderedItem("low", "冲"));

        FixProposalDTO proposal = new FixProposalDTO();
        proposal.setStrategy("sort_by_probability");
        ReviewCheckDTO check = new ReviewCheckDTO();
        check.setCode("probability_inversion");

        RepairDryRunSimulator.populate(state, proposal, check);

        assertEquals("ready", proposal.getStatus());
        assertEquals("ready", proposal.getDryRunResult().getStatus());
        assertEquals(Lists.newArrayList("low", "pinned_high"),
                Lists.newArrayList(proposal.getDryRunResult().getAfterVolunteerIds()));
    }

    @Test
    void shouldSimulateMajorGroupSortByUnitAdmissionRatio() {
        PlanningStateDTO state = baseState("majorGroup");
        CandidateItemDTO highUnitMajor = candidate("high_unit_major", "稳", "unit_high");
        highUnitMajor.setAdmissionRatio(65D);
        highUnitMajor.setSchoolEnrollRatio(60D);
        CandidateItemDTO lowUnitMajor = candidate("low_unit_major", "冲", "unit_low");
        lowUnitMajor.setAdmissionRatio(25D);
        lowUnitMajor.setSchoolEnrollRatio(20D);
        state.getCandidatePoolState().getItems().add(highUnitMajor);
        state.getCandidatePoolState().getItems().add(lowUnitMajor);
        state.getOrderedPlanState().getUnits().add(orderedUnit("unit_high", "稳"));
        state.getOrderedPlanState().getUnits().add(orderedUnit("unit_low", "冲"));
        state.getOrderedPlanState().getItems().add(orderedItem("high_unit_major", "稳"));
        state.getOrderedPlanState().getItems().add(orderedItem("low_unit_major", "冲"));

        FixProposalDTO proposal = new FixProposalDTO();
        proposal.setStrategy("sort_by_probability");
        ReviewCheckDTO check = new ReviewCheckDTO();
        check.setCode("probability_inversion");

        RepairDryRunSimulator.populate(state, proposal, check);

        assertEquals("ready", proposal.getStatus());
        assertEquals("ready", proposal.getDryRunResult().getStatus());
        assertEquals(Lists.newArrayList("unit_high", "unit_low"),
                Lists.newArrayList(proposal.getDryRunResult().getBeforeUnitIds()));
        assertEquals(Lists.newArrayList("unit_low", "unit_high"),
                Lists.newArrayList(proposal.getDryRunResult().getAfterUnitIds()));
        assertEquals(Lists.newArrayList("low_unit_major", "high_unit_major"),
                Lists.newArrayList(proposal.getDryRunResult().getAfterVolunteerIds()));
    }

    private PlanningStateDTO baseState(String volunteerModel) {
        PlanningStateDTO state = new PlanningStateDTO();
        state.getCandidatePoolState().setVolunteerModel(volunteerModel);
        return state;
    }

    private CandidateItemDTO candidate(String volunteerId, String tier, String unitId) {
        CandidateItemDTO candidate = new CandidateItemDTO();
        candidate.setVolunteerId(volunteerId);
        candidate.setTier(tier);
        candidate.setPlanSchoolDataId(unitId);
        candidate.setSchoolName("学校" + unitId);
        candidate.setMajorName("专业" + volunteerId);
        return candidate;
    }

    private OrderedItemDTO orderedItem(String volunteerId, String tier) {
        OrderedItemDTO item = new OrderedItemDTO();
        item.setVolunteerId(volunteerId);
        item.setTier(tier);
        return item;
    }

    private OrderedUnitDTO orderedUnit(String unitId, String tier) {
        OrderedUnitDTO unit = new OrderedUnitDTO();
        unit.setUnitId(unitId);
        unit.setTier(tier);
        return unit;
    }
}
