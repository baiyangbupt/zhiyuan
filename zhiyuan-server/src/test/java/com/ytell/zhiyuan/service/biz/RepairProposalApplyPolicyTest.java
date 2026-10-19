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
    void shouldRejectCanonicalProposalWhenHardObjectiveVersionIsMissingOnEitherSide() {
        // staged solver 是唯一框架：canonical 提案两侧的 hardObjectiveVersion 都是强制的，
        // 任一侧缺失即 fail closed（不再回退精确 solverVersion/solverInputDigest 比对）。
        FixProposalDTO proposalWithoutVersion = readyProposal();
        proposalWithoutVersion.setHardObjectiveVersion(null);
        assertEquals(409, assertThrows(BusinessException.class,
                () -> RepairProposalApplyPolicy.validateProposalForApply(
                        applyRequest(), proposalWithoutVersion)).getStatus());

        FixProposalApplyReq requestWithoutVersion = applyRequest();
        requestWithoutVersion.setHardObjectiveVersion(null);
        assertEquals(409, assertThrows(BusinessException.class,
                () -> RepairProposalApplyPolicy.validateProposalForApply(
                        requestWithoutVersion, readyProposal())).getStatus());
    }

    @Test
    void shouldAllowHardObjectiveMajorDriftAndIgnoreRequestSolverVersion() {
        // 跨部署/回滚：请求侧 solverVersion/solverInputDigest 与提案不同也不再参与比对；
        // 判据 = hardObjectiveVersion major 相同 + objective digest 相同 + 提案仍与冻结
        // solverResult 绑定。
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
    void shouldAllowCanonicalProposalWithoutRequestSolverVersionOrInputDigest() {
        // 新契约不再要求请求携带 solverVersion/solverInputDigest：只有 digest +
        // hardObjectiveVersion 是两侧强制项。
        FixProposalApplyReq request = applyRequest();
        request.setSolverVersion(null);
        request.setSolverInputDigest(null);

        assertDoesNotThrow(() -> RepairProposalApplyPolicy.validateProposalForApply(
                request, readyProposal()));
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
    void shouldRejectBrokenProposalSolverResultBindingEvenWithCompatibleHardObjective() {
        FixProposalDTO rebuilt = readyProposal();
        rebuilt.setHardObjectiveVersion("solver-hard-objective-v1.2");
        rebuilt.setSolverVersion("drifted-from-frozen-result");

        BusinessException error = assertThrows(BusinessException.class,
                () -> RepairProposalApplyPolicy.validateProposalForApply(applyRequest(), rebuilt));

        assertEquals(409, error.getStatus());
    }

    @Test
    void shouldRejectCanonicalProposalWithPartialMetadata() {
        // 提案仍有 hardObjectiveVersion + solverResult（判定为 canonical），但 digest 缺失
        // → 元数据不完整，fail closed。
        FixProposalDTO rebuilt = readyProposal();
        rebuilt.setCanonicalObjectiveDigest(null);

        assertEquals(409, assertThrows(BusinessException.class,
                () -> RepairProposalApplyPolicy.validateProposalForApply(applyRequest(), rebuilt)).getStatus());
    }

    @Test
    void shouldFailClosedWhenProposalOnlyCarriesFrozenResult() {
        // 有冻结 solverResult 但缺 canonical digest/hardObjectiveVersion：不是 scope-only，
        // 视为 canonical 元数据不完整，fail closed。
        FixProposalDTO rebuilt = readyProposal();
        rebuilt.setCanonicalObjectiveDigest(null);
        rebuilt.setHardObjectiveVersion(null);

        assertEquals(409, assertThrows(BusinessException.class,
                () -> RepairProposalApplyPolicy.validateProposalForApply(applyRequest(), rebuilt)).getStatus());
    }

    @Test
    void shouldAllowScopeOnlyProposalWithoutCanonicalMetadata() {
        // scope-only 提案按设计没有 canonical objective 元数据：即使请求也不带，照旧放行。
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
