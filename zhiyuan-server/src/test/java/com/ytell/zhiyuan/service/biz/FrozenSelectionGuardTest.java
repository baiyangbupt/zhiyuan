package com.ytell.zhiyuan.service.biz;

import com.google.common.collect.Lists;
import com.ytell.zhiyuan.common.exception.BusinessException;
import com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO;
import com.ytell.zhiyuan.model.dto.planning.FixProposalDTO;
import com.ytell.zhiyuan.model.dto.planning.HardConstraintsDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanSolverResultDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import org.junit.jupiter.api.Test;

import java.util.Arrays;

import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

class FrozenSelectionGuardTest {

    @Test
    void selectedFactStillPresentAndEligiblePasses() {
        PlanningStateDTO state = state();
        FixProposalDTO proposal = proposal("a");
        String digest = FrozenSelectionDigest.compute(state, candidates(), proposal);
        assertDoesNotThrow(() -> FrozenSelectionGuard.verify(
                state, candidates(), proposal, digest));
    }

    @Test
    void missingSelectedFactIsRejected() {
        PlanningStateDTO state = state();
        FixProposalDTO proposal = proposal("missing");
        String digest = FrozenSelectionDigest.compute(state, candidates(), proposal);
        BusinessException error = assertThrows(BusinessException.class,
                () -> FrozenSelectionGuard.verify(state, candidates(), proposal, digest));
        assertTrue(error.getMessage().contains("solver_input_stale"));
    }

    @Test
    void selectedFactNoLongerEligibleIsRejected() {
        PlanningStateDTO state = state();
        HardConstraintsDTO hard = new HardConstraintsDTO();
        hard.setMustIncludeRegions(Lists.newArrayList("江苏"));
        state.getConstraintState().setHardConstraints(hard);
        FixProposalDTO proposal = proposal("b");
        String digest = FrozenSelectionDigest.compute(state, candidates(), proposal);

        BusinessException error = assertThrows(BusinessException.class,
                () -> FrozenSelectionGuard.verify(state, candidates(), proposal, digest));
        assertTrue(error.getMessage().contains("solver_input_stale"));
    }

    @Test
    void missingSelectionDigestIsRejected() {
        PlanningStateDTO state = state();
        BusinessException error = assertThrows(BusinessException.class,
                () -> FrozenSelectionGuard.verify(state, candidates(), proposal("a"), null));
        assertTrue(error.getMessage().contains("frozen_digest_missing"));
    }

    @Test
    void requestDigestIgnoresApplyOnlyGuardAndDetectsChangedRequest() {
        com.ytell.zhiyuan.model.dto.planning.UserGoalFixProposalReq request =
                new com.ytell.zhiyuan.model.dto.planning.UserGoalFixProposalReq();
        request.setGoalType("fill_to_count");
        request.setTargetCount(3);
        String first = FrozenSelectionDigest.requestDigest(request);
        request.setSourceVersionGuard(9);
        assertEquals(first, FrozenSelectionDigest.requestDigest(request));
        request.setTargetCount(4);
        org.junit.jupiter.api.Assertions.assertNotEquals(
                first, FrozenSelectionDigest.requestDigest(request));
    }

    private PlanningStateDTO state() {
        PlanningStateDTO state = new PlanningStateDTO();
        state.getCandidatePoolState().setVolunteerModel("major");
        return state;
    }

    private java.util.List<CandidateItemDTO> candidates() {
        return Arrays.asList(candidate("a", "浙江"), candidate("b", "浙江"));
    }

    private CandidateItemDTO candidate(String id, String province) {
        CandidateItemDTO candidate = new CandidateItemDTO();
        candidate.setVolunteerId(id);
        candidate.setSchoolName("学校" + id);
        candidate.setMajorName("专业" + id);
        candidate.setProvinceName(province);
        candidate.setTier("稳");
        return candidate;
    }

    private FixProposalDTO proposal(String selected) {
        PlanSolverResultDTO result = new PlanSolverResultDTO();
        result.setSelectedEntityIds(Lists.newArrayList(selected));
        FixProposalDTO proposal = new FixProposalDTO();
        proposal.setSolverResult(result);
        return proposal;
    }
}
