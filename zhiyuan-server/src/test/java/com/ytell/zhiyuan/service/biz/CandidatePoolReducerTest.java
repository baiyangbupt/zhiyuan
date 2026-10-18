package com.ytell.zhiyuan.service.biz;

import com.ytell.zhiyuan.model.dto.planning.CandidateFactDTO;
import com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO;
import com.ytell.zhiyuan.model.dto.planning.CandidateSnapshotDTO;
import com.ytell.zhiyuan.model.dto.planning.CanonicalPlanningObjectiveSetDTO;
import com.ytell.zhiyuan.model.dto.planning.CoverageRequirementDTO;
import com.ytell.zhiyuan.model.dto.planning.MutationPolicyDTO;
import org.junit.jupiter.api.Test;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

class CandidatePoolReducerTest {

    @Test
    void keepsMandatoryAndDoesNotExceedCap() {
        CandidateSnapshotDTO snapshot = snapshot(620, "浙江");
        snapshot.getFacts().get(0).setCurrent(true);
        snapshot.getFacts().get(0).setLocked(true);
        MutationPolicyDTO policy = new MutationPolicyDTO();
        policy.setAction("FILL");
        policy.setLockExisting(true);

        CandidatePoolReducer.Reduction reduction = CandidatePoolReducer.reduce(
                snapshot, objectives(2), policy, 600);

        assertFalse(reduction.coreOverLimit);
        assertTrue(reduction.witnessAvailable);
        assertTrue(reduction.candidateCountSolved <= 600);
        assertTrue(reduction.facts.stream()
                .anyMatch(fact -> "f0".equals(fact.getEntityId())));
        assertTrue(reduction.droppedCount > 0);
        assertTrue(reduction.capLimited);
    }

    @Test
    void coreOverLimitIsReportedSeparatelyFromCandidateShortage() {
        CandidateSnapshotDTO snapshot = snapshot(605, "浙江");
        for (CandidateFactDTO fact : snapshot.getFacts()) {
            fact.setLocked(true);
        }

        CandidatePoolReducer.Reduction reduction = CandidatePoolReducer.reduce(
                snapshot, objectives(2), new MutationPolicyDTO(), 600);

        assertTrue(reduction.coreOverLimit);
        assertEquals(605, reduction.mandatorySize);
        assertEquals(605, reduction.facts.size());
    }

    @Test
    void overlappingCoverageKeepsFeasibleWitnessWithinCap() {
        CandidateSnapshotDTO snapshot = snapshot(620, "江苏");
        snapshot.getFacts().get(0).setProvinceName("浙江");
        snapshot.getFacts().get(1).setProvinceName("浙江");
        CanonicalPlanningObjectiveSetDTO objectives = objectives(2);
        CoverageRequirementDTO coverage = new CoverageRequirementDTO();
        coverage.setDomain("region");
        coverage.setKey("province");
        coverage.setValues(Arrays.asList("浙江"));
        coverage.setMinCount(2);
        objectives.setCoverageConstraints(new ArrayList<CoverageRequirementDTO>(
                Arrays.asList(coverage)));
        for (CandidateFactDTO fact : snapshot.getFacts()) {
            CandidateItemDTO raw = new CandidateItemDTO();
            raw.setVolunteerId(fact.getEntityId());
            raw.setProvinceName(fact.getProvinceName());
            fact.setRawCandidates(new ArrayList<CandidateItemDTO>(Arrays.asList(raw)));
        }

        CandidatePoolReducer.Reduction reduction = CandidatePoolReducer.reduce(
                snapshot, objectives, new MutationPolicyDTO(), 600);

        assertFalse(reduction.coreOverLimit);
        assertTrue(reduction.witnessAvailable);
        assertTrue(reduction.candidateCountSolved <= 600);
        assertTrue(reduction.facts.stream()
                .anyMatch(fact -> "f0".equals(fact.getEntityId())));
    }

    @Test
    void currentFactsStayVisibleWhenLockExistingIsFalse() {
        CandidateSnapshotDTO snapshot = snapshot(620, "浙江");
        snapshot.getFacts().get(300).setCurrent(true);
        MutationPolicyDTO policy = new MutationPolicyDTO();
        policy.setAction("FILL");
        policy.setLockExisting(false);
        policy.setCountAsChurn(true);

        CandidatePoolReducer.Reduction reduction = CandidatePoolReducer.reduce(
                snapshot, objectives(2), policy, 600);

        assertFalse(reduction.coreOverLimit);
        assertTrue(reduction.facts.stream()
                .anyMatch(fact -> "f300".equals(fact.getEntityId())),
                "current 行被 reducer 丢掉会让 removeEntityIds 漏报，apply 后总数悄悄变多");
    }

    private CandidateSnapshotDTO snapshot(int count, String province) {
        CandidateSnapshotDTO snapshot = new CandidateSnapshotDTO();
        snapshot.setSourceProvince(province);
        List<CandidateFactDTO> facts = new ArrayList<CandidateFactDTO>();
        for (int index = 0; index < count; index++) {
            CandidateFactDTO fact = new CandidateFactDTO();
            fact.setEntityId("f" + index);
            fact.setTier("stable");
            fact.setProvinceName(province);
            fact.setEligible(true);
            fact.setUtilityScore(100 - (index % 50));
            fact.setUtilityCoverage(100);
            fact.setStableOrder(index);
            fact.setCurrent(false);
            fact.setLocked(false);
            fact.setPinned(false);
            facts.add(fact);
        }
        snapshot.setFacts(facts);
        return snapshot;
    }

    private CanonicalPlanningObjectiveSetDTO objectives(int target) {
        CanonicalPlanningObjectiveSetDTO objectives = new CanonicalPlanningObjectiveSetDTO();
        objectives.setTargetCount(target);
        objectives.setCountMode("volunteer");
        objectives.setObjectiveDigest("reducer-" + target);
        return objectives;
    }
}
