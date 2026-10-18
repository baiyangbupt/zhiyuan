package com.ytell.zhiyuan.service.biz;

import com.google.common.collect.Lists;
import com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO;
import com.ytell.zhiyuan.model.dto.planning.EvaluationContextDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedItemDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedUnitDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningUnitMajorDTO;
import com.ytell.zhiyuan.model.dto.planning.ReviewStateDTO;
import com.ytell.zhiyuan.model.dto.planning.TierAllocationConstraintDTO;
import com.ytell.zhiyuan.model.dto.planning.TierQuotaGoalDTO;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;

class EvaluationContextBuilderTest {

    private final EvaluationContextBuilder builder = new EvaluationContextBuilder();

    @Test
    void buildsMajorModeEntriesAndCarriesTargets() {
        PlanningStateDTO state = new PlanningStateDTO();
        state.setVersion(9);
        state.getCandidatePoolState().setVolunteerModel("major");
        state.getCandidatePoolState().setRequiredCount(45);
        state.getCandidatePoolState().setSourceVersion(7);
        state.getCandidatePoolState().setSourceProvinceName("广东");
        state.getCandidatePoolState().setUserScore(600);
        state.getConstraintState().getHardPlanningObjectives().setSelectionTargetCount(50);
        state.getDataFreshnessState().setDataVersion("data-v1");

        CandidateItemDTO candidate = new CandidateItemDTO();
        candidate.setVolunteerId("v1");
        candidate.setSchoolEnrollRatio(40D);
        candidate.setAdmissionRatio(35D);
        candidate.setTuitionPerYear(6000);
        candidate.setRiskFlags(Lists.newArrayList("cooperative_program"));
        state.getCandidatePoolState().getItems().add(candidate);

        OrderedItemDTO item = new OrderedItemDTO();
        item.setVolunteerId("v1");
        item.setPosition(1);
        item.setTier("冲");
        item.setSchoolName("A大学");
        item.setMajorName("计算机");
        state.getOrderedPlanState().getItems().add(item);

        ReviewStateDTO review = new ReviewStateDTO();
        review.setSourceVersion(8);

        EvaluationContextDTO context = builder.build(state, null, review);

        assertEquals(1, context.getEntries().size());
        assertEquals("volunteer", context.getEntries().get(0).getLevel());
        assertEquals(40D, context.getEntries().get(0).getSchoolRatio());
        assertEquals(35D, context.getEntries().get(0).getMajorRatio());
        assertEquals(6000, context.getEntries().get(0).getTuitionPerYear());
        assertEquals(Lists.newArrayList("cooperative_program"),
                context.getEntries().get(0).getRiskFlags());
        assertEquals(Integer.valueOf(50), context.getSelectionTargetCount());
        assertEquals(Integer.valueOf(45), context.getRequiredCount());
        assertEquals("major", context.getAdmissionMode());
        assertEquals(Integer.valueOf(8), context.getEvaluatedStateVersion());
        assertEquals("data-v1", context.getDataVersion());
        assertNotNull(context.getPlanContentDigest());
        assertEquals("applicable", context.getSafetyFloorMode());
        assertEquals(Integer.valueOf(0), context.getSafetyMinLocalProtect());
        assertEquals("score_ge_580", context.getSafetyReasonCode());
        assertNull(context.getTierConstraint());
    }

    @Test
    void carriesSafetyFloorAndConfirmedTierConstraint() {
        PlanningStateDTO state = new PlanningStateDTO();
        state.getCandidatePoolState().setVolunteerModel("major");
        state.getCandidatePoolState().setSourceProvinceName("广东");
        state.getCandidatePoolState().setUserScore(600);
        state.getConstraintState().getHardPlanningObjectives().setSelectionTargetCount(3);
        TierQuotaGoalDTO goal = new TierQuotaGoalDTO();
        goal.setType("exact_counts");
        goal.setSprintCount(1);
        goal.setStableCount(1);
        goal.setProtectCount(1);
        state.getConstraintState().getHardPlanningObjectives().setTierQuotaGoal(goal);

        EvaluationContextDTO context = builder.build(state, null, new ReviewStateDTO());

        assertEquals("applicable", context.getSafetyFloorMode());
        assertEquals(Integer.valueOf(0), context.getSafetyMinLocalProtect());
        assertEquals("score_ge_580", context.getSafetyReasonCode());
        TierAllocationConstraintDTO constraint = context.getTierConstraint();
        assertNotNull(constraint);
        assertEquals("exact_counts", constraint.getType());
        assertEquals("exact_counts", constraint.getSourceType());
        assertEquals(Integer.valueOf(1), constraint.getSprint().getMinCount());
        assertEquals(Integer.valueOf(1), constraint.getSprint().getMaxCount());
        assertEquals(Integer.valueOf(1), constraint.getProtect().getMinCount());
    }

    @Test
    void fallsBackToRequiredCountForTierConstraint() {
        PlanningStateDTO state = new PlanningStateDTO();
        state.getCandidatePoolState().setRequiredCount(3);
        TierQuotaGoalDTO goal = new TierQuotaGoalDTO();
        goal.setType("exact_counts");
        goal.setSprintCount(1);
        goal.setStableCount(1);
        goal.setProtectCount(1);
        state.getConstraintState().getHardPlanningObjectives().setTierQuotaGoal(goal);

        EvaluationContextDTO context = builder.build(state, null, new ReviewStateDTO());

        assertNotNull(context.getTierConstraint());
        assertEquals(Integer.valueOf(1), context.getTierConstraint().getStable().getMaxCount());
    }

    @Test
    void buildsCoverageMatchesFromConfirmedRequirements() {
        PlanningStateDTO state = new PlanningStateDTO();
        state.getCandidatePoolState().setVolunteerModel("major");
        CandidateItemDTO candidate = new CandidateItemDTO();
        candidate.setVolunteerId("v1");
        candidate.setProvinceName("广东");
        candidate.setMajorName("计算机");
        state.getCandidatePoolState().getItems().add(candidate);
        OrderedItemDTO item = new OrderedItemDTO();
        item.setVolunteerId("v1");
        item.setTier("冲");
        state.getOrderedPlanState().getItems().add(item);
        com.ytell.zhiyuan.model.dto.planning.CoverageRequirementDTO region =
                new com.ytell.zhiyuan.model.dto.planning.CoverageRequirementDTO();
        region.setDomain("region");
        region.setKey("province");
        region.setValues(Lists.newArrayList("广东"));
        region.setMinCount(1);
        com.ytell.zhiyuan.model.dto.planning.CoverageRequirementDTO major =
                new com.ytell.zhiyuan.model.dto.planning.CoverageRequirementDTO();
        major.setDomain("major");
        major.setKey("major");
        major.setValues(Lists.newArrayList("计算机"));
        major.setMinCount(1);
        state.getConstraintState().getHardPlanningObjectives().setCoverageRequirements(
                Lists.newArrayList(region, major));

        EvaluationContextDTO context = builder.build(state, null, new ReviewStateDTO());

        assertEquals(2, context.getCoverageRequirements().size());
        assertEquals(Lists.newArrayList("coverage:0", "coverage:1"),
                context.getEntries().get(0).getMatchedCoverageIds());
    }

    @Test
    void buildsUnitEntriesWithMaxTuitionAndUnionFlags() {
        PlanningStateDTO state = new PlanningStateDTO();
        state.getCandidatePoolState().setVolunteerModel("majorGroup");

        CandidateItemDTO first = new CandidateItemDTO();
        first.setVolunteerId("v1");
        first.setTuitionPerYear(5000);
        first.setRiskFlags(Lists.newArrayList("cooperative_program"));
        CandidateItemDTO second = new CandidateItemDTO();
        second.setVolunteerId("v2");
        second.setTuitionPerYear(8000);
        second.setRiskFlags(Lists.newArrayList("special_enrollment"));
        state.getCandidatePoolState().getItems().add(first);
        state.getCandidatePoolState().getItems().add(second);

        OrderedUnitDTO unit = new OrderedUnitDTO();
        unit.setUnitId("u1");
        unit.setPosition(1);
        unit.setTier("稳");
        unit.setSchoolName("A大学第01组");
        unit.setSchoolEnrollRatio(60D);
        unit.setAdmissionRatio(58D);
        unit.getMajorItems().add(major("v1"));
        unit.getMajorItems().add(major("v2"));
        state.getOrderedPlanState().getUnits().add(unit);

        EvaluationContextDTO context = builder.build(state, null, new ReviewStateDTO());

        assertEquals(1, context.getEntries().size());
        assertEquals("unit", context.getEntries().get(0).getLevel());
        assertEquals(Integer.valueOf(8000), context.getEntries().get(0).getTuitionPerYear());
        assertEquals(Lists.newArrayList("cooperative_program", "special_enrollment"),
                context.getEntries().get(0).getRiskFlags());
        assertEquals("major_group", context.getAdmissionMode());
    }

    @Test
    void planContentDigestIsDeterministicForSamePlan() {
        PlanningStateDTO state = new PlanningStateDTO();
        OrderedItemDTO item = new OrderedItemDTO();
        item.setVolunteerId("v1");
        item.setPosition(1);
        item.setTier("冲");
        state.getOrderedPlanState().getItems().add(item);

        String first = builder.build(state, null, new ReviewStateDTO()).getPlanContentDigest();
        String second = builder.build(state, null, new ReviewStateDTO()).getPlanContentDigest();

        assertEquals(first, second);
    }

    private PlanningUnitMajorDTO major(String volunteerId) {
        PlanningUnitMajorDTO major = new PlanningUnitMajorDTO();
        major.setVolunteerId(volunteerId);
        return major;
    }
}
