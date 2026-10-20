package com.ytell.zhiyuan.service.biz;

import com.ytell.zhiyuan.common.exception.BusinessException;
import com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO;
import com.ytell.zhiyuan.model.dto.planning.CoverageRequirementDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedItemDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedUnitDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanSolverResultDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningUnitMajorDTO;
import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;

import java.util.Arrays;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.stream.Collectors;

import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

class PlanningIntegrityRuntimeTest {

    @Test
    void initialFallbackMustNotIgnoreConfirmedCount() {
        PlanningStateDTO state = majorState();
        state.getConstraintState().getHardPlanningObjectives().setSelectionTargetCount(2);
        CandidateItemDTO current = candidate("current", "u1", 90D);
        state.getCandidatePoolState().getItems().add(current);
        state.getWorkingPlanState().getItems().add(
                WorkingPlanMutationSupport.buildWorkingPlanItem(current, "initial_auto", false));

        assertThrows(BusinessException.class, () -> CanonicalPlanningRuntime.enforceSelection(
                state, state.getCandidatePoolState().getItems(), null, true));
        assertEquals(1, state.getWorkingPlanState().getItems().size());
    }

    @Test
    void initialFallbackMustNotIgnoreConfirmedCoverage() {
        PlanningStateDTO state = majorState();
        CandidateItemDTO current = candidate("current", "u1", 90D);
        current.setMajorName("数学");
        CandidateItemDTO risky = candidate("risky", "u2", 80D);
        risky.setMajorName("法学");
        risky.setRiskFlags(Collections.singletonList("special_enrollment"));
        state.getCandidatePoolState().setItems(Arrays.asList(current, risky));
        state.getWorkingPlanState().getItems().add(
                WorkingPlanMutationSupport.buildWorkingPlanItem(current, "initial_auto", false));
        CoverageRequirementDTO requirement = new CoverageRequirementDTO();
        requirement.setDomain("major");
        requirement.setKey("major");
        requirement.setValues(Collections.singletonList("法学"));
        requirement.setMinCount(1);
        state.getConstraintState().getHardPlanningObjectives().getCoverageRequirements().add(requirement);

        assertThrows(BusinessException.class, () -> CanonicalPlanningRuntime.enforceSelection(
                state, state.getCandidatePoolState().getItems(), null, true));
        assertEquals("current", state.getWorkingPlanState().getItems().get(0).getVolunteerId());
    }

    @Test
    void optionalInitialOptimizationMayStillFallBack() {
        PlanningStateDTO state = majorState();
        CandidateItemDTO current = candidate("current", "u1", 90D);
        state.getCandidatePoolState().getItems().add(current);
        state.getWorkingPlanState().getItems().add(
                WorkingPlanMutationSupport.buildWorkingPlanItem(current, "initial_auto", false));

        PlanSolverResultDTO result = CanonicalPlanningRuntime.enforceSelection(
                state, state.getCandidatePoolState().getItems(), 2, true);

        assertEquals("no_change", result.getStatus());
        assertEquals(1, state.getWorkingPlanState().getItems().size());
    }

    @Test
    void frozenReplayUsesDeclaredMajorEvenWhenCurrentRatiosPreferAnother() {
        PlanningStateDTO state = groupState();
        CandidateItemDTO declared = candidate("v1", "u1", 70D);
        CandidateItemDTO alternative = candidate("v2", "u1", 95D);
        state.getCandidatePoolState().setItems(Arrays.asList(declared, alternative));
        PlanSolverResultDTO frozen = frozenMajor("v1");

        CanonicalPlanningRuntime.applyFrozenSelection(state, state.getCandidatePoolState().getItems(), frozen);

        assertEquals(1, state.getWorkingPlanState().getItems().size());
        assertEquals("v1", state.getWorkingPlanState().getItems().get(0).getVolunteerId());
        CanonicalPlanningRuntime.verifyFrozenWorkingSelection(state,
                state.getCandidatePoolState().getItems(), frozen);
    }

    @Test
    void frozenWorkingVerificationRejectsDifferentMajorInTheSameUnit() {
        PlanningStateDTO state = groupState();
        CandidateItemDTO declared = candidate("v1", "u1", 70D);
        CandidateItemDTO actual = candidate("v2", "u1", 95D);
        state.getCandidatePoolState().setItems(Arrays.asList(declared, actual));
        state.getWorkingPlanState().getItems().add(
                WorkingPlanMutationSupport.buildWorkingPlanItem(actual, "user", true));

        assertThrows(BusinessException.class, () -> CanonicalPlanningRuntime.verifyFrozenWorkingSelection(
                state, state.getCandidatePoolState().getItems(), frozenMajor("v1")));
    }

    @Test
    void frozenOrderedVerificationRejectsDifferentMajorInTheSameUnit() {
        PlanningStateDTO state = groupState();
        OrderedUnitDTO unit = new OrderedUnitDTO();
        unit.setUnitId("u1");
        unit.setPosition(1);
        PlanningUnitMajorDTO major = new PlanningUnitMajorDTO();
        major.setVolunteerId("v2");
        unit.getMajorItems().add(major);
        state.getOrderedPlanState().getUnits().add(unit);
        OrderedItemDTO item = new OrderedItemDTO();
        item.setVolunteerId("v2");
        item.setPosition(1);
        state.getOrderedPlanState().getItems().add(item);

        assertThrows(BusinessException.class,
                () -> CanonicalPlanningRuntime.verifyFrozenState(state, frozenMajor("v1")));
    }

    @Test
    void frozenReplayAcceptsRetainedMajorsInADifferentOrder() {
        PlanningStateDTO state = groupState();
        CandidateItemDTO high = candidate("high", "u1", 90D);
        CandidateItemDTO low = candidate("low", "u1", 70D);
        state.getCandidatePoolState().setItems(Arrays.asList(high, low));
        state.getWorkingPlanState().getItems().add(
                WorkingPlanMutationSupport.buildWorkingPlanItem(high, "user", false));
        state.getWorkingPlanState().getItems().add(
                WorkingPlanMutationSupport.buildWorkingPlanItem(low, "user", false));
        PlanSolverResultDTO frozen = frozenMajor("low");
        frozen.getSelectedMajorIdsByUnit().put("u1", Arrays.asList("low", "high"));

        assertDoesNotThrow(() -> CanonicalPlanningRuntime.applyFrozenSelection(
                state, state.getCandidatePoolState().getItems(), frozen));

        assertEquals(Arrays.asList("high", "low"), state.getWorkingPlanState().getItems().stream()
                .map(item -> item.getVolunteerId()).collect(Collectors.toList()));
        CanonicalPlanningRuntime.verifyFrozenWorkingSelection(
                state, state.getCandidatePoolState().getItems(), frozen);
    }

    @Test
    void frozenVerificationAcceptsTheRealMaterializersDisplayOrder() {
        PlanningStateDTO state = groupState();
        CandidateItemDTO high = candidate("u1_high", "u1", 90D);
        CandidateItemDTO low = candidate("u1_low", "u1", 70D);
        state.getCandidatePoolState().setItems(Arrays.asList(high, low));
        PlanSolverResultDTO frozen = frozenMajor("u1_high");
        frozen.getSelectedMajorIdsByUnit().put("u1", Arrays.asList("u1_high", "u1_low"));
        CanonicalPlanningRuntime.applyFrozenSelection(
                state, state.getCandidatePoolState().getItems(), frozen);
        PlanningStateService service = new PlanningStateService();
        List<OrderedItemDTO> items = ReflectionTestUtils.invokeMethod(service,
                "buildOrderedItemsFromWorkingPlan", state.getWorkingPlanState(),
                state.getCandidatePoolState(), state.getCandidatePoolState().getItems(),
                new LinkedHashMap<String, OrderedItemDTO>(), true);
        List<OrderedUnitDTO> units = ReflectionTestUtils.invokeMethod(service,
                "buildOrderedUnitsFromOrderedItems", items, state.getWorkingPlanState(),
                state.getCandidatePoolState().getItems());
        state.getOrderedPlanState().setItems(items);
        state.getOrderedPlanState().setUnits(units);
        CanonicalPlanningRuntime.applyFrozenOrdering(state, frozen);

        assertEquals(Arrays.asList("u1_low", "u1_high"), units.get(0).getMajorItems().stream()
                .map(PlanningUnitMajorDTO::getVolunteerId).collect(Collectors.toList()));
        assertDoesNotThrow(() -> CanonicalPlanningRuntime.verifyFrozenState(state, frozen));
    }

    @Test
    void frozenReplayRejectsAnIncompleteMajorMapBeforeMutation() {
        PlanningStateDTO state = groupState();
        CandidateItemDTO first = candidate("v1", "u1", 70D);
        CandidateItemDTO second = candidate("v2", "u2", 95D);
        state.getCandidatePoolState().setItems(Arrays.asList(first, second));
        PlanSolverResultDTO frozen = frozenMajor("v1");
        frozen.setSelectedEntityIds(Arrays.asList("u1", "u2"));
        frozen.setOrderedEntityIds(Arrays.asList("u1", "u2"));

        assertThrows(BusinessException.class, () -> CanonicalPlanningRuntime.applyFrozenSelection(
                state, state.getCandidatePoolState().getItems(), frozen));
        assertEquals(0, state.getWorkingPlanState().getItems().size());
    }

    @Test
    void frozenReplayRejectsDuplicateMajorsBeforeMutation() {
        PlanningStateDTO state = groupState();
        state.getCandidatePoolState().getItems().add(candidate("v1", "u1", 70D));
        PlanSolverResultDTO frozen = frozenMajor("v1");
        frozen.getSelectedMajorIdsByUnit().put("u1", Arrays.asList("v1", "v1"));

        assertThrows(BusinessException.class, () -> CanonicalPlanningRuntime.applyFrozenSelection(
                state, state.getCandidatePoolState().getItems(), frozen));
        assertEquals(0, state.getWorkingPlanState().getItems().size());
    }

    @Test
    void frozenReplayRejectsAnEmptyMajorSelectionBeforeMutation() {
        PlanningStateDTO state = groupState();
        state.getCandidatePoolState().getItems().add(candidate("v1", "u1", 70D));
        PlanSolverResultDTO frozen = frozenMajor("v1");
        frozen.getSelectedMajorIdsByUnit().put("u1", Collections.emptyList());

        assertThrows(BusinessException.class, () -> CanonicalPlanningRuntime.applyFrozenSelection(
                state, state.getCandidatePoolState().getItems(), frozen));
        assertEquals(0, state.getWorkingPlanState().getItems().size());
    }

    private PlanningStateDTO majorState() {
        PlanningStateDTO state = new PlanningStateDTO();
        state.setVersion(7);
        state.getCandidatePoolState().setVolunteerModel("major");
        state.getCandidatePoolState().setRequiredCount(1);
        return state;
    }

    private PlanningStateDTO groupState() {
        PlanningStateDTO state = majorState();
        state.getCandidatePoolState().setVolunteerModel("majorGroup");
        state.getCandidatePoolState().setRequiredMajorCount(1);
        return state;
    }

    private CandidateItemDTO candidate(String identity, String unitId, double ratio) {
        CandidateItemDTO candidate = new CandidateItemDTO();
        candidate.setVolunteerId(identity);
        candidate.setPlanSchoolDataId(unitId);
        candidate.setSchoolName("学校-" + unitId);
        candidate.setMajorName("数学");
        candidate.setTier("stable");
        candidate.setProvinceName("北京");
        candidate.setAdmissionRatio(ratio);
        candidate.setSchoolEnrollRatio(60D);
        candidate.setIntentScore(50D);
        candidate.setFinalScore(50D);
        return candidate;
    }

    private PlanSolverResultDTO frozenMajor(String identity) {
        PlanSolverResultDTO frozen = new PlanSolverResultDTO();
        frozen.setStatus("ready");
        frozen.setSolverVersion("test-frozen");
        frozen.setInputDigest("frozen-major-input");
        frozen.setSelectedEntityIds(Collections.singletonList("u1"));
        frozen.setOrderedEntityIds(Collections.singletonList("u1"));
        frozen.getSelectedMajorIdsByUnit().put("u1", Collections.singletonList(identity));
        return frozen;
    }
}
