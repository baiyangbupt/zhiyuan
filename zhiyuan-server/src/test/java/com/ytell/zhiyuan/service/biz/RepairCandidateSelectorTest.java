package com.ytell.zhiyuan.service.biz;

import com.google.common.collect.Lists;
import com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO;
import com.ytell.zhiyuan.model.dto.planning.DraftItemDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedItemDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedUnitDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningUnitDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningUnitMajorDTO;
import org.junit.jupiter.api.Test;

import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

public class RepairCandidateSelectorTest {

    @Test
    void shouldPreferShortageTierAndLocalProtectWhenSelectingTotalCountVolunteerAdditions() {
        PlanningStateDTO state = baseState("major");
        state.getCandidatePoolState().setRequiredCount(3);
        state.getCandidatePoolState().setSourceProvinceName("天津");
        state.getCandidatePoolState().setRequiredTierCounts(tierCounts(1, 1, 1));
        state.getOrderedPlanState().getItems().add(orderedItem("sprint_1", "冲", false));
        state.getOrderedPlanState().getItems().add(orderedItem("safe_1", "稳", false));

        CandidateItemDTO nonLocalProtect = candidate("protect_non_local", "保", "河北", 99D, 80D, 10D);
        CandidateItemDTO localProtect = candidate("protect_local", "保", "天津", 70D, 76D, 20D);
        CandidateItemDTO safe = candidate("safe_2", "稳", "天津", 100D, 55D, 30D);

        RepairCandidateSelector.Selection selection = RepairCandidateSelector.selectTotalCountVolunteerAdditions(
                state, Arrays.asList(nonLocalProtect, localProtect, safe));

        assertEquals(Arrays.asList("protect_local"), selection.getCandidateVolunteerIds());
    }

    @Test
    void shouldSelectProtectRatioUnitAdditionsByUnitPriority() {
        PlanningStateDTO state = baseState("majorGroup");
        state.getCandidatePoolState().setSourceProvinceName("天津");
        state.getCandidatePoolState().setRequiredTierCounts(tierCounts(1, 1, 2));
        state.getOrderedPlanState().getUnits().add(orderedUnit("unit_sprint", "冲", "北京", 30D, 92D, false));
        state.getOrderedPlanState().getUnits().add(orderedUnit("unit_safe", "稳", "北京", 55D, 88D, false));

        PlanningUnitDTO nonLocalProtect = planningUnit("unit_non_local", "保", "河北", 82D, 99D, "non_local_major");
        PlanningUnitDTO localProtect = planningUnit("unit_local", "保", "天津", 78D, 70D, "local_major");

        RepairCandidateSelector.Selection selection = RepairCandidateSelector.selectProtectRatioUnitAdditions(
                state, Arrays.asList(nonLocalProtect, localProtect));

        assertEquals(Arrays.asList("unit_local", "unit_non_local"), selection.getCandidateUnitIds());
        assertEquals(Arrays.asList("local_major", "non_local_major"), selection.getCandidateVolunteerIds());
    }

    @Test
    void shouldFilterConfirmedHardExcludedMajorByAllMajorsWhenUnitHasNoSelectedMajors() {
        PlanningStateDTO state = baseState("majorGroup");
        state.getCandidatePoolState().setRequiredCount(2);
        state.getConstraintState().getHardConstraints().getMustExcludeMajors().add("会计");

        PlanningUnitDTO excluded = planningUnit("unit_accounting", "保", "天津", 80D, 90D, "accounting_major");
        excluded.setSelectedMajors(Lists.newArrayList());
        excluded.setAllMajors(Lists.newArrayList(planningUnitMajor("accounting_major", "会计学")));
        PlanningUnitDTO allowed = planningUnit("unit_law", "保", "天津", 78D, 80D, "law_major");
        allowed.getSelectedMajors().get(0).setMajorName("法学");

        RepairCandidateSelector.Selection selection = RepairCandidateSelector.selectTotalCountUnitAdditions(
                state, Arrays.asList(excluded, allowed));

        assertEquals(Arrays.asList("unit_law"), selection.getCandidateUnitIds());
        assertEquals(Arrays.asList("law_major"), selection.getCandidateVolunteerIds());
    }

    @Test
    void shouldPreferSelectedMajorsWhenFilteringConfirmedHardExcludedMajorForUnit() {
        PlanningStateDTO state = baseState("majorGroup");
        state.getCandidatePoolState().setRequiredCount(1);
        state.getConstraintState().getHardConstraints().getMustExcludeMajors().add("会计");

        PlanningUnitDTO unit = planningUnit("unit_mixed", "保", "天津", 80D, 90D, "law_major");
        unit.getSelectedMajors().get(0).setMajorName("法学");
        unit.setAllMajors(Lists.newArrayList(
                planningUnitMajor("law_major", "法学"),
                planningUnitMajor("accounting_major", "会计学")));

        RepairCandidateSelector.Selection selection = RepairCandidateSelector.selectTotalCountUnitAdditions(
                state, Arrays.asList(unit));

        assertEquals(Arrays.asList("unit_mixed"), selection.getCandidateUnitIds());
        assertEquals(Arrays.asList("law_major"), selection.getCandidateVolunteerIds());
    }

    @Test
    void shouldSelectProbabilityGapVolunteerAdditionsInsideGapRange() {
        PlanningStateDTO state = baseState("major");
        state.getOrderedPlanState().getItems().add(orderedItem("selected_low", "冲", false));
        state.getOrderedPlanState().getItems().add(orderedItem("selected_high", "稳", false));

        CandidateItemDTO low = candidate("selected_low", "冲", "北京", 90D, 20D, 10D);
        CandidateItemDTO high = candidate("selected_high", "稳", "北京", 88D, 50D, 10D);
        CandidateItemDTO filler = candidate("gap_filler", "稳", "北京", 86D, 35D, 10D);
        CandidateItemDTO outside = candidate("outside", "保", "北京", 84D, 75D, 10D);

        RepairCandidateSelector.Selection selection = RepairCandidateSelector.selectProbabilityGapVolunteerAdditions(
                state, Arrays.asList(low, high), Arrays.asList(filler, outside));

        assertEquals(Arrays.asList("gap_filler"), selection.getCandidateVolunteerIds());
        assertEquals(Double.valueOf(20D), selection.getRangeMin());
        assertEquals(Double.valueOf(50D), selection.getRangeMax());
    }

    @Test
    void shouldUseQualityTieBreakersWhenSelectingProbabilityGapVolunteerAdditions() {
        PlanningStateDTO state = baseState("major");
        state.getOrderedPlanState().getItems().add(orderedItem("selected_low", "冲", false));
        state.getOrderedPlanState().getItems().add(orderedItem("selected_high", "稳", false));

        CandidateItemDTO low = candidate("selected_low", "冲", "北京", 90D, 20D, 10D);
        CandidateItemDTO high = candidate("selected_high", "稳", "北京", 88D, 50D, 10D);
        CandidateItemDTO lowerQuality = candidate("gap_lower_quality", "稳", "北京", 70D, 34D, 60D);
        lowerQuality.setSchoolRank(80);
        CandidateItemDTO betterQuality = candidate("gap_better_quality", "稳", "北京", 90D, 36D, 80D);
        betterQuality.setSchoolRank(120);

        RepairCandidateSelector.Selection selection = RepairCandidateSelector.selectProbabilityGapVolunteerAdditions(
                state, Arrays.asList(low, high), Arrays.asList(lowerQuality, betterQuality));

        assertEquals(Arrays.asList("gap_better_quality", "gap_lower_quality"), selection.getCandidateVolunteerIds());
    }

    @Test
    void shouldUseSchoolRankTieBreakerWhenProbabilityGapQualityTies() {
        PlanningStateDTO state = baseState("major");
        state.getOrderedPlanState().getItems().add(orderedItem("selected_low", "冲", false));
        state.getOrderedPlanState().getItems().add(orderedItem("selected_high", "稳", false));

        CandidateItemDTO low = candidate("selected_low", "冲", "北京", 90D, 20D, 10D);
        CandidateItemDTO high = candidate("selected_high", "稳", "北京", 88D, 50D, 10D);
        CandidateItemDTO weakerSchool = candidate("gap_weaker_school", "稳", "北京", 90D, 34D, 80D);
        weakerSchool.setSchoolRank(180);
        CandidateItemDTO betterSchool = candidate("gap_better_school", "稳", "北京", 90D, 36D, 80D);
        betterSchool.setSchoolRank(80);

        RepairCandidateSelector.Selection selection = RepairCandidateSelector.selectProbabilityGapVolunteerAdditions(
                state, Arrays.asList(low, high), Arrays.asList(weakerSchool, betterSchool));

        assertEquals(Arrays.asList("gap_better_school", "gap_weaker_school"), selection.getCandidateVolunteerIds());
    }

    @Test
    void shouldFilterConfirmedHardExcludedRegionWhenSelectingAdditions() {
        PlanningStateDTO state = baseState("major");
        state.getCandidatePoolState().setRequiredCount(3);
        state.getCandidatePoolState().setRequiredTierCounts(tierCounts(1, 1, 1));
        state.getConstraintState().getHardConstraints().getMustExcludeRegions().add("河北");
        state.getOrderedPlanState().getItems().add(orderedItem("sprint_1", "冲", false));
        state.getOrderedPlanState().getItems().add(orderedItem("safe_1", "稳", false));

        CandidateItemDTO excluded = candidate("protect_hebei", "保", "河北", 99D, 90D, 99D);
        CandidateItemDTO allowed = candidate("protect_tianjin", "保", "天津", 80D, 80D, 80D);

        RepairCandidateSelector.Selection selection = RepairCandidateSelector.selectTotalCountVolunteerAdditions(
                state, Arrays.asList(excluded, allowed));

        assertEquals(Arrays.asList("protect_tianjin"), selection.getCandidateVolunteerIds());
    }

    @Test
    void shouldExposeSelectionDiagnosticsWhenConfirmedHardConstraintsCauseShortage() {
        PlanningStateDTO state = baseState("major");
        state.getCandidatePoolState().setRequiredCount(4);
        state.getCandidatePoolState().setRequiredTierCounts(tierCounts(1, 1, 2));
        state.getConstraintState().getHardConstraints().getMustExcludeRegions().add("河北");
        state.getOrderedPlanState().getItems().add(orderedItem("sprint_1", "冲", false));
        state.getOrderedPlanState().getItems().add(orderedItem("safe_1", "稳", false));

        CandidateItemDTO excludedA = candidate("protect_hebei_a", "保", "河北", 99D, 90D, 99D);
        CandidateItemDTO excludedB = candidate("protect_hebei_b", "保", "河北", 98D, 88D, 98D);

        RepairCandidateSelector.Selection selection = RepairCandidateSelector.selectTotalCountVolunteerAdditions(
                state, Arrays.asList(excludedA, excludedB));

        assertTrue(selection.getCandidateVolunteerIds().isEmpty());
        assertEquals("保", selection.getTargetTier());
        assertEquals(Integer.valueOf(2), selection.getRequiredCount());
        assertEquals(Integer.valueOf(0), selection.getSelectedCount());
        assertEquals(Integer.valueOf(2), selection.getShortageCount());
        assertEquals(Integer.valueOf(0), selection.getAvailableCount());
        assertEquals(Integer.valueOf(2), selection.getAvailableCountWithoutHardConstraints());
        assertEquals(Boolean.TRUE, selection.getShortageCausedByConfirmedHardConstraints());
    }

    @Test
    void shouldNotFilterSoftAvoidWhenSelectingAdditions() {
        PlanningStateDTO state = baseState("major");
        state.getCandidatePoolState().setRequiredCount(3);
        state.getCandidatePoolState().setRequiredTierCounts(tierCounts(1, 1, 1));
        state.getConstraintState().getSoftPreferences().getAvoidRegions().add("河北");
        state.getOrderedPlanState().getItems().add(orderedItem("sprint_1", "冲", false));
        state.getOrderedPlanState().getItems().add(orderedItem("safe_1", "稳", false));

        CandidateItemDTO softAvoid = candidate("protect_hebei", "保", "河北", 99D, 90D, 99D);
        CandidateItemDTO lower = candidate("protect_tianjin", "保", "天津", 80D, 80D, 80D);

        RepairCandidateSelector.Selection selection = RepairCandidateSelector.selectTotalCountVolunteerAdditions(
                state, Arrays.asList(softAvoid, lower));

        assertEquals(Arrays.asList("protect_hebei"), selection.getCandidateVolunteerIds());
        assertEquals(Integer.valueOf(1), selection.getRequiredCount());
        assertEquals(Integer.valueOf(1), selection.getSelectedCount());
        assertEquals(Integer.valueOf(2), selection.getAvailableCount());
        assertEquals(Integer.valueOf(2), selection.getAvailableCountWithoutHardConstraints());
        assertFalse(Boolean.TRUE.equals(selection.getShortageCausedByConfirmedHardConstraints()));
    }

    @Test
    void shouldSkipLockedVolunteerWhenSelectingTierRatioReplacementSource() {
        PlanningStateDTO state = baseState("major");
        state.getCandidatePoolState().setRequiredTierCounts(tierCounts(1, 1, 1));
        state.getOrderedPlanState().getItems().add(orderedItem("locked_sprint", "冲", true));
        state.getOrderedPlanState().getItems().add(orderedItem("movable_sprint", "冲", false));
        state.getOrderedPlanState().getItems().add(orderedItem("safe_1", "稳", false));

        CandidateItemDTO locked = candidate("locked_sprint", "冲", "北京", 70D, 25D, 60D);
        CandidateItemDTO movable = candidate("movable_sprint", "冲", "北京", 60D, 30D, 50D);
        CandidateItemDTO safe = candidate("safe_1", "稳", "北京", 80D, 50D, 70D);

        RepairCandidateSelector.Selection selection = RepairCandidateSelector.selectTierRatioReplacementSources(
                state, Arrays.asList(locked, movable, safe), "保", 1);

        assertEquals("冲", selection.getRemoveTier());
        assertEquals(Arrays.asList("movable_sprint"), selection.getRemoveVolunteerIds());
    }

    @Test
    void shouldSelectMajorGroupReplacementSourceByUnit() {
        PlanningStateDTO state = baseState("majorGroup");
        state.getCandidatePoolState().setRequiredTierCounts(tierCounts(1, 1, 1));
        state.getOrderedPlanState().getUnits().add(orderedUnit("unit_locked", "冲", "北京", 28D, 70D, true));
        state.getOrderedPlanState().getUnits().add(orderedUnit("unit_movable", "冲", "北京", 32D, 60D, false));
        state.getOrderedPlanState().getUnits().add(orderedUnit("unit_safe", "稳", "北京", 50D, 80D, false));
        state.getOrderedPlanState().getItems().add(orderedItem("locked_major_1", "冲", true));
        state.getOrderedPlanState().getItems().add(orderedItem("movable_major_1", "冲", false));
        state.getOrderedPlanState().getItems().add(orderedItem("movable_major_2", "冲", false));
        state.getOrderedPlanState().getItems().add(orderedItem("safe_major_1", "稳", false));

        CandidateItemDTO locked = candidate("locked_major_1", "冲", "北京", 70D, 28D, 60D);
        locked.setPlanSchoolDataId("unit_locked");
        CandidateItemDTO movable1 = candidate("movable_major_1", "冲", "北京", 60D, 32D, 50D);
        movable1.setPlanSchoolDataId("unit_movable");
        CandidateItemDTO movable2 = candidate("movable_major_2", "冲", "北京", 58D, 34D, 50D);
        movable2.setPlanSchoolDataId("unit_movable");
        CandidateItemDTO safe = candidate("safe_major_1", "稳", "北京", 80D, 50D, 70D);
        safe.setPlanSchoolDataId("unit_safe");

        RepairCandidateSelector.Selection selection = RepairCandidateSelector.selectTierRatioReplacementSources(
                state, Arrays.asList(locked, movable1, movable2, safe), "保", 1);

        assertEquals(Arrays.asList("unit_movable"), selection.getRemoveUnitIds());
        assertEquals(Arrays.asList("movable_major_1", "movable_major_2"), selection.getRemoveVolunteerIds());
    }

    @Test
    void shouldOrderStructuralReplacementCandidatesByMajorSimilarityAndSchoolRankCost() {
        CandidateItemDTO source = candidate("source_law", "冲", "北京", 90D, 20D, 80D);
        source.setMajorCategory("法学类");
        source.setSchoolRank(90);
        CandidateItemDTO unrelated = candidate("candidate_finance", "保", "北京", 98D, 82D, 95D);
        unrelated.setMajorCategory("金融学类");
        unrelated.setSchoolRank(80);
        CandidateItemDTO similarDowngrade = candidate("candidate_law_downgrade", "保", "北京", 90D, 80D, 80D);
        similarDowngrade.setMajorCategory("法学类");
        similarDowngrade.setSchoolRank(260);
        CandidateItemDTO similarGoodRank = candidate("candidate_law_good", "保", "北京", 85D, 78D, 78D);
        similarGoodRank.setMajorCategory("法学类");
        similarGoodRank.setSchoolRank(120);

        assertEquals(
                "candidate_law_good",
                RepairCandidateSelector.orderStructuralReplacementCandidateVolunteerIds(
                        Arrays.asList("source_law"),
                        Arrays.asList("candidate_finance", "candidate_law_downgrade", "candidate_law_good"),
                        Arrays.asList(source, unrelated, similarDowngrade, similarGoodRank)).get(0));
    }

    @Test
    void shouldSelectRiskItemReplacementBySameTierSafetyAndScore() {
        PlanningStateDTO state = baseState("major");
        state.getWorkingPlanState().getItems().add(workingPlanItem("risk_1", "稳"));

        CandidateItemDTO risk = candidate("risk_1", "稳", "北京", 55D, 80D, 20D);
        risk.setMajorCategory("工商管理类");
        CandidateItemDTO unsafe = candidate("unsafe_1", "稳", "北京", 100D, 20D, 90D);
        unsafe.setMajorCategory("工商管理类");
        unsafe.setTuitionPerYear(30000);
        CandidateItemDTO otherTier = candidate("protect_1", "保", "北京", 99D, 90D, 80D);
        otherTier.setMajorCategory("工商管理类");
        CandidateItemDTO lowerScore = candidate("safe_lower", "稳", "北京", 60D, 30D, 60D);
        lowerScore.setMajorCategory("工商管理类");
        CandidateItemDTO best = candidate("safe_best", "稳", "北京", 70D, 50D, 70D);
        best.setMajorCategory("工商管理类");

        RepairCandidateSelector.RiskReplacementSelection selection = RepairCandidateSelector.selectRiskItemReplacements(
                state,
                Arrays.asList(risk, unsafe, otherTier, lowerScore, best),
                Arrays.asList("risk_1"));

        assertEquals(1, selection.getPairs().size());
        assertEquals("risk_1", selection.getPairs().get(0).getSource().getVolunteerId());
        assertEquals("safe_best", selection.getPairs().get(0).getReplacement().getVolunteerId());
        assertEquals(0, selection.getMissingSourceCount());
        assertEquals(0, selection.getNoReplacementCount());
    }

    @Test
    void shouldPreferHigherAdmissionRatioWhenRiskReplacementScoreTies() {
        PlanningStateDTO state = baseState("major");
        state.getWorkingPlanState().getItems().add(workingPlanItem("risk_1", "稳"));

        CandidateItemDTO risk = candidate("risk_1", "稳", "北京", 55D, 80D, 20D);
        risk.setMajorCategory("工商管理类");
        CandidateItemDTO lowerRatio = candidate("safe_lower_ratio", "稳", "北京", 70D, 30D, 80D);
        lowerRatio.setMajorCategory("工商管理类");
        CandidateItemDTO higherRatio = candidate("safe_higher_ratio", "稳", "北京", 70D, 60D, 60D);
        higherRatio.setMajorCategory("工商管理类");

        RepairCandidateSelector.RiskReplacementSelection selection = RepairCandidateSelector.selectRiskItemReplacements(
                state,
                Arrays.asList(risk, lowerRatio, higherRatio),
                Arrays.asList("risk_1"));

        assertEquals(1, selection.getPairs().size());
        assertEquals("safe_higher_ratio", selection.getPairs().get(0).getReplacement().getVolunteerId());
    }

    @Test
    void shouldRejectRiskReplacementAcrossMajorCategory() {
        PlanningStateDTO state = baseState("major");
        state.getWorkingPlanState().getItems().add(workingPlanItem("risk_1", "稳"));

        CandidateItemDTO risk = candidate("risk_1", "稳", "北京", 55D, 80D, 20D);
        risk.setMajorCategory("工商管理类");
        CandidateItemDTO unrelated = candidate("law_1", "稳", "北京", 95D, 70D, 95D);
        unrelated.setMajorCategory("法学类");

        RepairCandidateSelector.RiskReplacementSelection selection = RepairCandidateSelector.selectRiskItemReplacements(
                state,
                Arrays.asList(risk, unrelated),
                Arrays.asList("risk_1"));

        assertTrue(selection.getPairs().isEmpty());
        assertEquals(1, selection.getNoReplacementCount());
    }

    @Test
    void shouldRejectSevereSchoolRankDowngradeWhenSelectingRiskReplacement() {
        PlanningStateDTO state = baseState("major");
        state.getWorkingPlanState().getItems().add(workingPlanItem("risk_1", "稳"));

        CandidateItemDTO risk = candidate("risk_1", "稳", "北京", 55D, 80D, 20D);
        risk.setMajorCategory("工商管理类");
        risk.setSchoolRank(100);
        CandidateItemDTO severeDowngrade = candidate("severe_downgrade", "稳", "北京", 95D, 70D, 95D);
        severeDowngrade.setMajorCategory("工商管理类");
        severeDowngrade.setSchoolRank(400);
        CandidateItemDTO acceptable = candidate("acceptable", "稳", "北京", 70D, 60D, 70D);
        acceptable.setMajorCategory("工商管理类");
        acceptable.setSchoolRank(180);

        RepairCandidateSelector.RiskReplacementSelection selection = RepairCandidateSelector.selectRiskItemReplacements(
                state,
                Arrays.asList(risk, severeDowngrade, acceptable),
                Arrays.asList("risk_1"));

        assertEquals(1, selection.getPairs().size());
        assertEquals("acceptable", selection.getPairs().get(0).getReplacement().getVolunteerId());
    }

    @Test
    void shouldAvoidCurrentAndUsedUnitsWhenSelectingMajorGroupRiskReplacement() {
        PlanningStateDTO state = baseState("majorGroup");
        state.getWorkingPlanState().getItems().add(workingPlanItem("unitA_m1", "冲"));
        state.getWorkingPlanState().getItems().add(workingPlanItem("unitD_m1", "冲"));
        state.getWorkingPlanState().getItems().add(workingPlanItem("unitB_m1", "稳"));

        CandidateItemDTO sourceA = candidate("unitA_m1", "冲", "北京", 40D, 20D, 20D);
        sourceA.setMajorCategory("工商管理类");
        CandidateItemDTO sourceD = candidate("unitD_m1", "冲", "北京", 42D, 22D, 20D);
        sourceD.setMajorCategory("工商管理类");
        CandidateItemDTO currentUnitSelected = candidate("unitB_m1", "稳", "北京", 30D, 60D, 50D);
        currentUnitSelected.setMajorCategory("工商管理类");
        CandidateItemDTO currentUnitCandidate = candidate("unitB_m2", "冲", "北京", 95D, 35D, 80D);
        currentUnitCandidate.setMajorCategory("工商管理类");
        CandidateItemDTO unitC1 = candidate("unitC_m1", "冲", "北京", 80D, 40D, 70D);
        unitC1.setMajorCategory("工商管理类");
        CandidateItemDTO unitC2 = candidate("unitC_m2", "冲", "北京", 78D, 38D, 70D);
        unitC2.setMajorCategory("工商管理类");

        RepairCandidateSelector.RiskReplacementSelection selection = RepairCandidateSelector.selectRiskItemReplacements(
                state,
                Arrays.asList(sourceA, sourceD, currentUnitSelected, currentUnitCandidate, unitC1, unitC2),
                Arrays.asList("unitA_m1", "unitD_m1"));

        assertEquals(1, selection.getPairs().size());
        assertEquals("unitA_m1", selection.getPairs().get(0).getSource().getVolunteerId());
        assertEquals("unitC_m1", selection.getPairs().get(0).getReplacement().getVolunteerId());
        assertEquals(0, selection.getMissingSourceCount());
        assertEquals(1, selection.getNoReplacementCount());
    }

    @Test
    void shouldFilterConfirmedHardExcludedMajorWhenSelectingRiskReplacement() {
        PlanningStateDTO state = baseState("major");
        state.getConstraintState().getHardConstraints().getMustExcludeMajors().add("会计");
        state.getWorkingPlanState().getItems().add(workingPlanItem("risk_1", "稳"));

        CandidateItemDTO risk = candidate("risk_1", "稳", "北京", 55D, 80D, 20D);
        risk.setMajorCategory("工商管理类");
        CandidateItemDTO excluded = candidate("accounting_1", "稳", "北京", 99D, 55D, 99D);
        excluded.setMajorName("会计学");
        excluded.setMajorCategory("工商管理类");
        CandidateItemDTO allowed = candidate("law_1", "稳", "北京", 80D, 56D, 80D);
        allowed.setMajorName("财务管理");
        allowed.setMajorCategory("工商管理类");

        RepairCandidateSelector.RiskReplacementSelection selection = RepairCandidateSelector.selectRiskItemReplacements(
                state,
                Arrays.asList(risk, excluded, allowed),
                Arrays.asList("risk_1"));

        assertEquals(1, selection.getPairs().size());
        assertEquals("law_1", selection.getPairs().get(0).getReplacement().getVolunteerId());
    }

    private PlanningStateDTO baseState(String volunteerModel) {
        PlanningStateDTO state = new PlanningStateDTO();
        state.getCandidatePoolState().setVolunteerModel(volunteerModel);
        state.getCandidatePoolState().setRequiredCount(3);
        return state;
    }

    private Map<String, Integer> tierCounts(int sprint, int safe, int protect) {
        Map<String, Integer> counts = new LinkedHashMap<String, Integer>();
        counts.put("冲", sprint);
        counts.put("稳", safe);
        counts.put("保", protect);
        return counts;
    }

    private CandidateItemDTO candidate(String volunteerId,
                                       String tier,
                                       String provinceName,
                                       Double finalScore,
                                       Double admissionRatio,
                                       Double intentScore) {
        CandidateItemDTO candidate = new CandidateItemDTO();
        candidate.setVolunteerId(volunteerId);
        candidate.setTier(tier);
        candidate.setPlanSchoolDataId(unitIdFromVolunteerId(volunteerId));
        candidate.setSchoolName("学校" + volunteerId);
        candidate.setMajorName("专业" + volunteerId);
        candidate.setProvinceName(provinceName);
        candidate.setFinalScore(finalScore);
        candidate.setAdmissionRatio(admissionRatio);
        candidate.setSchoolEnrollRatio(admissionRatio);
        candidate.setIntentScore(intentScore);
        return candidate;
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

    private DraftItemDTO workingPlanItem(String volunteerId, String tier) {
        DraftItemDTO item = new DraftItemDTO();
        item.setVolunteerId(volunteerId);
        item.setTier(tier);
        item.setSchoolName("学校" + volunteerId);
        item.setMajorName("专业" + volunteerId);
        return item;
    }

    private OrderedUnitDTO orderedUnit(String unitId,
                                       String tier,
                                       String provinceName,
                                       Double admissionRatio,
                                       Double finalScore,
                                       boolean locked) {
        OrderedUnitDTO unit = new OrderedUnitDTO();
        unit.setUnitId(unitId);
        unit.setTier(tier);
        unit.setSchoolName("学校" + unitId);
        unit.setProvinceName(provinceName);
        unit.setAdmissionRatio(admissionRatio);
        unit.setFinalScore(finalScore);
        unit.setLocked(locked);
        return unit;
    }

    private PlanningUnitDTO planningUnit(String unitId,
                                         String tier,
                                         String provinceName,
                                         Double admissionRatio,
                                         Double finalScore,
                                         String volunteerId) {
        PlanningUnitDTO unit = new PlanningUnitDTO();
        unit.setUnitId(unitId);
        unit.setTier(tier);
        unit.setSchoolName("学校" + unitId);
        unit.setProvinceName(provinceName);
        unit.setAdmissionRatio(admissionRatio);
        unit.setFinalScore(finalScore);
        PlanningUnitMajorDTO major = new PlanningUnitMajorDTO();
        major.setVolunteerId(volunteerId);
        major.setMajorName("专业" + volunteerId);
        unit.setSelectedMajors(Lists.newArrayList(major));
        return unit;
    }

    private PlanningUnitMajorDTO planningUnitMajor(String volunteerId, String majorName) {
        PlanningUnitMajorDTO major = new PlanningUnitMajorDTO();
        major.setVolunteerId(volunteerId);
        major.setMajorName(majorName);
        return major;
    }

    private String unitIdFromVolunteerId(String volunteerId) {
        int index = volunteerId == null ? -1 : volunteerId.indexOf('_');
        return index <= 0 ? volunteerId : volunteerId.substring(0, index);
    }
}
