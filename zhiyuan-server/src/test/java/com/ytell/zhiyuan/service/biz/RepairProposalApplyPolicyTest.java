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
    void shouldRejectSolverVersionAndInputDigestMismatchWhenHardObjectiveVersionIsMissing() {
        // 任一侧缺 hardObjectiveVersion → 维持旧的精确三件套比对（fail-closed）。
        FixProposalDTO rebuilt = readyProposal();
        rebuilt.setHardObjectiveVersion(null);
        FixProposalApplyReq versionMismatch = applyRequest();
        versionMismatch.setHardObjectiveVersion(null);
        versionMismatch.setSolverVersion("other-solver");
        assertEquals(409, assertThrows(BusinessException.class,
                () -> RepairProposalApplyPolicy.validateProposalForApply(versionMismatch, rebuilt)).getStatus());

        FixProposalApplyReq inputMismatch = applyRequest();
        inputMismatch.setHardObjectiveVersion(null);
        inputMismatch.setSolverInputDigest("other-input");
        assertEquals(409, assertThrows(BusinessException.class,
                () -> RepairProposalApplyPolicy.validateProposalForApply(inputMismatch, rebuilt)).getStatus());
    }

    @Test
    void shouldAllowSolverVersionDriftWhenHardObjectiveMajorAndObjectiveDigestMatch() {
        // S4：部署/回滚导致请求侧 solverVersion 与 inputDigest 不同，但 major 与
        // objective digest 相同、提案仍与冻结 solverResult 绑定 → 放行。
        FixProposalDTO rebuilt = readyProposal();
        rebuilt.setHardObjectiveVersion("solver-hard-objective-v1.2");
        rebuilt.setSolverVersion("ojalgo-48.4.2-m2");
        rebuilt.getSolverResult().setSolverVersion("ojalgo-48.4.2-m2");

        FixProposalApplyReq request = applyRequest();
        request.setHardObjectiveVersion("solver-hard-objective-v1.9");
        request.setSolverVersion("ojalgo-48.4.2-m1");
        request.setSolverInputDigest("input-digest-from-another-deploy");

        assertDoesNotThrow(() -> RepairProposalApplyPolicy.validateProposalForApply(request, rebuilt));
    }

    @Test
    void shouldRejectDifferentHardObjectiveMajor() {
        FixProposalDTO rebuilt = readyProposal();
        rebuilt.setHardObjectiveVersion("solver-hard-objective-v1.2");
        FixProposalApplyReq request = applyRequest();
        request.setHardObjectiveVersion("solver-hard-objective-v2.0");

        BusinessException error = assertThrows(BusinessException.class,
                () -> RepairProposalApplyPolicy.validateProposalForApply(request, rebuilt));

        assertEquals(409, error.getStatus());
    }

    @Test
    void shouldKeepExactSolverVersionCheckWhenHardObjectiveVersionIsMissingOnEitherSide() {
        // 提案侧缺失
        FixProposalDTO proposalWithoutVersion = readyProposal();
        proposalWithoutVersion.setHardObjectiveVersion(null);
        FixProposalApplyReq requestWithVersion = applyRequest();
        requestWithVersion.setHardObjectiveVersion("solver-hard-objective-v1");
        requestWithVersion.setSolverVersion("other-solver");
        assertEquals(409, assertThrows(BusinessException.class,
                () -> RepairProposalApplyPolicy.validateProposalForApply(
                        requestWithVersion, proposalWithoutVersion)).getStatus());

        // 请求侧缺失
        FixProposalApplyReq requestWithoutVersion = applyRequest();
        requestWithoutVersion.setHardObjectiveVersion(null);
        requestWithoutVersion.setSolverVersion("other-solver");
        assertEquals(409, assertThrows(BusinessException.class,
                () -> RepairProposalApplyPolicy.validateProposalForApply(
                        requestWithoutVersion, readyProposal())).getStatus());
    }

    @Test
    void shouldRejectBrokenProposalSolverResultBindingEvenWithCompatibleHardObjective() {
        FixProposalDTO rebuilt = readyProposal();
        rebuilt.setHardObjectiveVersion("solver-hard-objective-v1.2");
        rebuilt.setSolverVersion("drifted-from-frozen-result");

        BusinessException error = assertThrows(BusinessException.class,
                () -> RepairProposalApplyPolicy.validateProposalForApply(applyRequest(), rebuilt));

        assertEquals(409, error.getStatus());
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
        rebuilt.setHardObjectiveVersion(null);
        rebuilt.setSolverResult(null);
        FixProposalApplyReq request = applyRequest();
        request.setCanonicalObjectiveDigest(null);
        request.setSolverVersion(null);
        request.setSolverInputDigest(null);
        request.setHardObjectiveVersion(null);

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
        proposal.setHardObjectiveVersion("solver-hard-objective-v1.2");
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
        request.setHardObjectiveVersion("solver-hard-objective-v1.2");
        UserGoalFixProposalReq userGoal = new UserGoalFixProposalReq();
        userGoal.setGoalType("fill_to_count");
        userGoal.setTargetCount(4);
        request.setUserGoalRequest(userGoal);
        return request;
    }
}
