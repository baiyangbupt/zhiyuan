package com.ytell.zhiyuan.service.biz;

import com.ytell.zhiyuan.model.dto.planning.CandidateFactDTO;
import com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO;
import org.junit.jupiter.api.Test;

import java.util.Arrays;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;

class InnerMajorPlanBuilderTest {

    @Test
    void buildsCappedPlanPerUnitAndKeepsSmallUnitsWhole() {
        CandidateFactDTO large = fact("u1", 8);
        CandidateFactDTO small = fact("u2", 3);

        Map<String, List<String>> plan = InnerMajorPlanBuilder.build(
                Arrays.asList(large, small), 6);

        assertEquals(6, plan.get("u1").size());
        assertEquals(3, plan.get("u2").size());
    }

    @Test
    void noRequiredCountKeepsAllMajors() {
        Map<String, List<String>> plan = InnerMajorPlanBuilder.build(
                Arrays.asList(fact("u1", 8)), null);
        assertEquals(8, plan.get("u1").size());
    }

    @Test
    void reusesStageOnePlanWithoutReselectingOrRequiringPolicyCount() {
        CandidateFactDTO fact = fact("u1", 4);
        fact.setPlannedCandidates(Arrays.asList(
                fact.getRawCandidates().get(1), fact.getRawCandidates().get(0)));

        assertEquals(Arrays.asList("u1-v2", "u1-v1"),
                InnerMajorPlanBuilder.build(Arrays.asList(fact), null).get("u1"));
        assertEquals(Arrays.asList("u1-v2", "u1-v1"),
                InnerMajorPlanBuilder.build(Arrays.asList(fact), 1).get("u1"));
    }

    private CandidateFactDTO fact(String unitId, int majors) {
        CandidateFactDTO fact = new CandidateFactDTO();
        fact.setEntityId(unitId);
        for (int index = 1; index <= majors; index++) {
            CandidateItemDTO candidate = new CandidateItemDTO();
            candidate.setVolunteerId(unitId + "-v" + index);
            candidate.setPlanSchoolDataId(unitId);
            candidate.setSchoolEnrollRatio(60D);
            candidate.setAdmissionRatio(50D + index);
            candidate.setIntentScore(50D);
            candidate.setFinalScore(50D);
            fact.getRawCandidates().add(candidate);
        }
        return fact;
    }
}
