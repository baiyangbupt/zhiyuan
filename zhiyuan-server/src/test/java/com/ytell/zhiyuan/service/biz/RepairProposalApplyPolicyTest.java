package com.ytell.zhiyuan.service.biz;

import com.ytell.zhiyuan.common.exception.BusinessException;
import com.ytell.zhiyuan.model.dto.planning.FixProposalApplyReq;
import com.ytell.zhiyuan.model.dto.planning.FixProposalDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanSolverResultDTO;
import com.ytell.zhiyuan.model.dto.planning.UserGoalFixProposalReq;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

class RepairProposalApplyPolicyTest {

    @Test
    void shouldRejectCanonicalMetadataMismatchForNewPending() {
        FixProposalDTO rebuilt = readyProposal();
        FixProposalApplyReq request = applyRequest();
        request.setCanonicalObjectiveDigest("different-objective");

        BusinessException error = assertThrows(BusinessException.class,
                () -> RepairProposalApplyPolicy.validateProposalForApply(request, rebuilt));

        assertEquals(409, error.getStatus());
    }

    @Test
    void shouldRejectSolverVersionAndInputDigestMismatchForNewPending() {
        FixProposalDTO rebuilt = readyProposal();
        FixProposalApplyReq versionMismatch = applyRequest();
        versionMismatch.setSolverVersion("other-solver");
        assertEquals(409, assertThrows(BusinessException.class,
                () -> RepairProposalApplyPolicy.validateProposalForApply(versionMismatch, rebuilt)).getStatus());

        FixProposalApplyReq inputMismatch = applyRequest();
        inputMismatch.setSolverInputDigest("other-input");
        assertEquals(409, assertThrows(BusinessException.class,
                () -> RepairProposalApplyPolicy.validateProposalForApply(inputMismatch, rebuilt)).getStatus());
    }

    @Test
    void shouldRejectPartialCanonicalMetadata() {
        FixProposalApplyReq request = applyRequest();
        request.setSolverInputDigest(null);

        assertEquals(409, assertThrows(BusinessException.class,
                () -> RepairProposalApplyPolicy.validateProposalForApply(request, readyProposal())).getStatus());
    }

    @Test
    void shouldAllowLegacyPendingOnlyWhenRequestAndProposalMetadataAreBothAbsent() {
        FixProposalDTO rebuilt = readyProposal();
        rebuilt.setCanonicalObjectiveDigest(null);
        rebuilt.setSolverVersion(null);
        rebuilt.setSolverInputDigest(null);
        rebuilt.setSolverResult(null);
        FixProposalApplyReq request = applyRequest();
        request.setCanonicalObjectiveDigest(null);
        request.setSolverVersion(null);
        request.setSolverInputDigest(null);

        assertDoesNotThrow(() -> RepairProposalApplyPolicy.validateProposalForApply(request, rebuilt));
    }

    @Test
    void shouldRejectMetadataLessRequestWhenRebuiltProposalIsCanonical() {
        FixProposalApplyReq request = applyRequest();
        request.setCanonicalObjectiveDigest(null);
        request.setSolverVersion(null);
        request.setSolverInputDigest(null);

        BusinessException error = assertThrows(BusinessException.class,
                () -> RepairProposalApplyPolicy.validateProposalForApply(request, readyProposal()));

        assertEquals(409, error.getStatus());
    }

    @Test
    void shouldRejectCanonicalProposalWithoutFrozenSolverResult() {
        FixProposalDTO rebuilt = readyProposal();
        rebuilt.setSolverResult(null);

        BusinessException error = assertThrows(BusinessException.class,
                () -> RepairProposalApplyPolicy.validateProposalForApply(applyRequest(), rebuilt));

        assertEquals(409, error.getStatus());
    }

    @Test
    void shouldRejectMetadataLessRequestWhenRebuiltProposalMetadataIsPartial() {
        FixProposalDTO rebuilt = readyProposal();
        rebuilt.setSolverInputDigest(null);
        FixProposalApplyReq request = applyRequest();
        request.setCanonicalObjectiveDigest(null);
        request.setSolverVersion(null);
        request.setSolverInputDigest(null);

        BusinessException error = assertThrows(BusinessException.class,
                () -> RepairProposalApplyPolicy.validateProposalForApply(request, rebuilt));

        assertEquals(409, error.getStatus());
    }

    private FixProposalDTO readyProposal() {
        FixProposalDTO proposal = new FixProposalDTO();
        proposal.setProposalId("ugp-fill");
        proposal.setProposalSource("user_goal");
        proposal.setSourceVersionGuard(12);
        proposal.setStatus("ready");
        proposal.setStrategy("fill_missing_count");
        proposal.setCanonicalObjectiveDigest("objective-digest");
        proposal.setSolverVersion("ojalgo-48.4.2-m1");
        proposal.setSolverInputDigest("input-digest");
        PlanSolverResultDTO solverResult = new PlanSolverResultDTO();
        solverResult.setSolverVersion("ojalgo-48.4.2-m1");
        solverResult.setInputDigest("input-digest");
        proposal.setSolverResult(solverResult);
        return proposal;
    }

    private FixProposalApplyReq applyRequest() {
        FixProposalApplyReq request = new FixProposalApplyReq();
        request.setProposalId("ugp-fill");
        request.setProposalSource("user_goal");
        request.setSourceVersionGuard(12);
        request.setCanonicalObjectiveDigest("objective-digest");
        request.setSolverVersion("ojalgo-48.4.2-m1");
        request.setSolverInputDigest("input-digest");
        UserGoalFixProposalReq userGoal = new UserGoalFixProposalReq();
        userGoal.setGoalType("fill_to_count");
        userGoal.setTargetCount(4);
        request.setUserGoalRequest(userGoal);
        return request;
    }
}
