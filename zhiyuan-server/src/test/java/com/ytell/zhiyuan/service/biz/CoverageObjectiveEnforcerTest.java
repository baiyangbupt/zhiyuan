package com.ytell.zhiyuan.service.biz;

import com.ytell.zhiyuan.common.exception.BusinessException;
import com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO;
import com.ytell.zhiyuan.model.dto.planning.CoverageRequirementDTO;
import com.ytell.zhiyuan.model.dto.planning.DraftItemDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import org.junit.jupiter.api.Test;

import java.util.Arrays;
import java.util.Set;
import java.util.stream.Collectors;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

class CoverageObjectiveEnforcerTest {

    @Test
    void shouldRestoreMissingCoverageByReplacingUnlockedItem() {
        PlanningStateDTO state = state("major", 2);
        CandidateItemDTO math = candidate("v1", "u1", "数学", 90D);
        CandidateItemDTO finance = candidate("v2", "u2", "金融学", 80D);
        CandidateItemDTO law = candidate("v3", "u3", "法学", 95D);
        state.getCandidatePoolState().getItems().addAll(Arrays.asList(math, finance, law));
        state.getWorkingPlanState().getItems().add(draft(math, false));
        state.getWorkingPlanState().getItems().add(draft(finance, false));
        state.getConstraintState().getHardPlanningObjectives().getCoverageRequirements()
                .add(requirement("major", "major", "法学", 1));

        CoverageObjectiveEnforcer.enforce(state, state.getCandidatePoolState().getItems());

        Set<String> ids = state.getWorkingPlanState().getItems().stream()
                .map(DraftItemDTO::getVolunteerId)
                .collect(Collectors.toSet());
        assertEquals(2, ids.size());
        assertTrue(ids.contains("v3"));
        assertTrue(ids.contains("v1"));
    }

    @Test
    void shouldRestoreCompleteMajorGroupInsteadOfSingleMajor() {
        PlanningStateDTO state = state("majorGroup", 1);
        CandidateItemDTO math = candidate("v1", "u1", "数学", 90D);
        CandidateItemDTO physics = candidate("v2", "u1", "物理学", 85D);
        CandidateItemDTO law = candidate("v3", "u2", "法学", 95D);
        CandidateItemDTO politics = candidate("v4", "u2", "政治学", 80D);
        state.getCandidatePoolState().getItems().addAll(Arrays.asList(math, physics, law, politics));
        state.getWorkingPlanState().getItems().add(draft(math, false));
        state.getWorkingPlanState().getItems().add(draft(physics, false));
        state.getConstraintState().getHardPlanningObjectives().getCoverageRequirements()
                .add(requirement("major", "major", "法学", 1));

        CoverageObjectiveEnforcer.enforce(state, state.getCandidatePoolState().getItems());

        Set<String> ids = state.getWorkingPlanState().getItems().stream()
                .map(DraftItemDTO::getVolunteerId)
                .collect(Collectors.toSet());
        assertEquals(new java.util.HashSet<String>(Arrays.asList("v3", "v4")), ids);
        assertEquals(1, state.getWorkingPlanState().getUnits().size());
        assertEquals("u2", state.getWorkingPlanState().getUnits().get(0).getUnitId());
    }

    @Test
    void shouldFailRegenerationWhenCoverageReplacementWouldRemoveLockedItem() {
        PlanningStateDTO state = state("major", 1);
        CandidateItemDTO math = candidate("v1", "u1", "数学", 90D);
        CandidateItemDTO law = candidate("v2", "u2", "法学", 95D);
        state.getCandidatePoolState().getItems().addAll(Arrays.asList(math, law));
        state.getWorkingPlanState().getItems().add(draft(math, true));
        state.getConstraintState().getHardPlanningObjectives().getCoverageRequirements()
                .add(requirement("major", "major", "法学", 1));

        BusinessException error = assertThrows(BusinessException.class,
                () -> CoverageObjectiveEnforcer.enforce(state, state.getCandidatePoolState().getItems()));

        assertEquals(409, error.getStatus());
        assertTrue(error.getMessage().contains("未锁定"));
    }

    @Test
    void shouldRestorePersistedProtectTierMinimum() {
        PlanningStateDTO state = state("major", 2);
        CandidateItemDTO safeOne = candidate("v1", "u1", "数学", 90D);
        safeOne.setTier("稳");
        CandidateItemDTO safeTwo = candidate("v2", "u2", "金融学", 80D);
        safeTwo.setTier("safe");
        CandidateItemDTO protectOne = candidate("v3", "u3", "法学", 95D);
        protectOne.setTier("保底");
        CandidateItemDTO protectTwo = candidate("v4", "u4", "会计学", 85D);
        protectTwo.setTier("protect");
        state.getCandidatePoolState().getItems().addAll(
                Arrays.asList(safeOne, safeTwo, protectOne, protectTwo));
        state.getWorkingPlanState().getItems().add(draft(safeOne, false));
        state.getWorkingPlanState().getItems().add(draft(safeTwo, false));
        state.getConstraintState().getHardPlanningObjectives().getCoverageRequirements()
                .add(requirement("admission", "tier", "保", 2));

        CoverageObjectiveEnforcer.enforce(state, state.getCandidatePoolState().getItems());

        Set<String> ids = state.getWorkingPlanState().getItems().stream()
                .map(DraftItemDTO::getVolunteerId)
                .collect(Collectors.toSet());
        assertEquals(new java.util.HashSet<String>(Arrays.asList("v3", "v4")), ids);
    }

    private PlanningStateDTO state(String volunteerModel, int requiredCount) {
        PlanningStateDTO state = new PlanningStateDTO();
        state.getCandidatePoolState().setVolunteerModel(volunteerModel);
        state.getCandidatePoolState().setRequiredCount(requiredCount);
        return state;
    }

    private CandidateItemDTO candidate(String volunteerId, String unitId, String majorName, Double score) {
        CandidateItemDTO candidate = new CandidateItemDTO();
        candidate.setVolunteerId(volunteerId);
        candidate.setPlanSchoolDataId(unitId);
        candidate.setSchoolName("学校-" + unitId);
        candidate.setMajorName(majorName);
        candidate.setIntentScore(score);
        candidate.setFinalScore(score);
        return candidate;
    }

    private DraftItemDTO draft(CandidateItemDTO candidate, boolean locked) {
        return WorkingPlanMutationSupport.buildWorkingPlanItem(candidate, "test", locked);
    }

    private CoverageRequirementDTO requirement(String domain,
                                               String key,
                                               String value,
                                               int minCount) {
        CoverageRequirementDTO requirement = new CoverageRequirementDTO();
        requirement.setDomain(domain);
        requirement.setKey(key);
        requirement.setValues(Arrays.asList(value));
        requirement.setMinCount(minCount);
        return requirement;
    }
}
