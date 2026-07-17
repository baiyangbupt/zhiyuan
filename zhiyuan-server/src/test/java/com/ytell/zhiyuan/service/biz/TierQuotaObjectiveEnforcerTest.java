package com.ytell.zhiyuan.service.biz;

import com.ytell.zhiyuan.common.exception.BusinessException;
import com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO;
import com.ytell.zhiyuan.model.dto.planning.DraftItemDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import com.ytell.zhiyuan.model.dto.planning.TierQuotaGoalDTO;
import org.junit.jupiter.api.Test;

import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.stream.Collectors;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

class TierQuotaObjectiveEnforcerTest {

    @Test
    void shouldRestoreExactTierQuotaByEqualReplacement() {
        PlanningStateDTO state = state();
        CandidateItemDTO sprintOne = candidate("v1", "冲", 90D);
        CandidateItemDTO sprintTwo = candidate("v2", "sprint", 89D);
        CandidateItemDTO stable = candidate("v3", "稳", 88D);
        CandidateItemDTO protect = candidate("v4", "保底", 87D);
        state.getCandidatePoolState().getItems().addAll(
                Arrays.asList(sprintOne, sprintTwo, stable, protect));
        state.getWorkingPlanState().getItems().add(draft(sprintOne, false));
        state.getWorkingPlanState().getItems().add(draft(sprintTwo, false));
        state.getWorkingPlanState().getItems().add(draft(stable, false));
        TierQuotaSupport.persist(state, quota(1, 1, 1));

        TierQuotaObjectiveEnforcer.enforce(state, state.getCandidatePoolState().getItems());

        Map<String, CandidateItemDTO> byId = state.getCandidatePoolState().getItems().stream()
                .collect(Collectors.toMap(CandidateItemDTO::getVolunteerId, item -> item));
        Map<String, Integer> counts = new LinkedHashMap<String, Integer>();
        counts.put("冲", 0);
        counts.put("稳", 0);
        counts.put("保", 0);
        for (DraftItemDTO item : state.getWorkingPlanState().getItems()) {
            String tier = byId.get(item.getVolunteerId()).getTier();
            String canonical = "保底".equals(tier) ? "保" : "sprint".equals(tier) ? "冲" : tier;
            counts.put(canonical, counts.get(canonical) + 1);
        }
        assertEquals(Integer.valueOf(1), counts.get("冲"));
        assertEquals(Integer.valueOf(1), counts.get("稳"));
        assertEquals(Integer.valueOf(1), counts.get("保"));
        assertEquals(3, state.getWorkingPlanState().getItems().size());
    }

    @Test
    void shouldFailWhenExactQuotaRequiresRemovingLockedExcessTier() {
        PlanningStateDTO state = state();
        CandidateItemDTO sprint = candidate("v1", "冲", 90D);
        CandidateItemDTO stable = candidate("v2", "稳", 89D);
        CandidateItemDTO protect = candidate("v3", "保", 88D);
        state.getCandidatePoolState().getItems().addAll(Arrays.asList(sprint, stable, protect));
        state.getWorkingPlanState().getItems().add(draft(sprint, true));
        state.getWorkingPlanState().getItems().add(draft(stable, false));
        TierQuotaSupport.persist(state, quota(0, 1, 1));

        BusinessException error = assertThrows(BusinessException.class,
                () -> TierQuotaObjectiveEnforcer.enforce(
                        state, state.getCandidatePoolState().getItems()));

        assertEquals(409, error.getStatus());
        assertTrue(error.getMessage().contains("未锁定"));
    }

    @Test
    void shouldFailWhenOneMajorGroupMatchesMultipleTiers() {
        PlanningStateDTO state = state();
        state.getCandidatePoolState().setVolunteerModel("majorGroup");
        CandidateItemDTO sprint = candidate("v1", "冲", 90D);
        sprint.setPlanSchoolDataId("u1");
        CandidateItemDTO stable = candidate("v2", "稳", 89D);
        stable.setPlanSchoolDataId("u1");
        state.getCandidatePoolState().getItems().addAll(Arrays.asList(sprint, stable));
        state.getWorkingPlanState().getItems().add(draft(sprint, false));
        state.getWorkingPlanState().getItems().add(draft(stable, false));
        TierQuotaSupport.persist(state, quota(1, 0, 0));

        BusinessException error = assertThrows(BusinessException.class,
                () -> TierQuotaObjectiveEnforcer.enforce(
                        state, state.getCandidatePoolState().getItems()));

        assertEquals(409, error.getStatus());
        assertTrue(error.getMessage().contains("互斥且精确"));
    }

    private PlanningStateDTO state() {
        PlanningStateDTO state = new PlanningStateDTO();
        state.getCandidatePoolState().setVolunteerModel("major");
        state.getCandidatePoolState().setRequiredCount(3);
        return state;
    }

    private TierQuotaGoalDTO quota(int sprint, int stable, int protect) {
        TierQuotaGoalDTO goal = new TierQuotaGoalDTO();
        goal.setType("exact_counts");
        goal.setSprintCount(sprint);
        goal.setStableCount(stable);
        goal.setProtectCount(protect);
        return goal;
    }

    private CandidateItemDTO candidate(String volunteerId, String tier, Double score) {
        CandidateItemDTO candidate = new CandidateItemDTO();
        candidate.setVolunteerId(volunteerId);
        candidate.setPlanSchoolDataId("u-" + volunteerId);
        candidate.setSchoolName("学校-" + volunteerId);
        candidate.setMajorName("专业-" + volunteerId);
        candidate.setTier(tier);
        candidate.setIntentScore(score);
        candidate.setFinalScore(score);
        return candidate;
    }

    private DraftItemDTO draft(CandidateItemDTO candidate, boolean locked) {
        return WorkingPlanMutationSupport.buildWorkingPlanItem(candidate, "test", locked);
    }
}
