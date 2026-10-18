package com.ytell.zhiyuan.service.biz;

import com.google.common.base.Strings;
import com.ytell.zhiyuan.common.exception.BusinessException;
import com.ytell.zhiyuan.model.dto.planning.FixProposalApplyReq;
import com.ytell.zhiyuan.model.dto.planning.FixProposalDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import com.ytell.zhiyuan.model.dto.planning.ReviewStateDTO;

final class RepairProposalApplyPolicy {

    private RepairProposalApplyPolicy() {
    }

    static FixProposalApplyReq safeRequest(FixProposalApplyReq req) {
        return req == null ? new FixProposalApplyReq() : req;
    }

    static void validateRequest(FixProposalApplyReq req) {
        if (req == null || Strings.isNullOrEmpty(req.getProposalId())) {
            throw new BusinessException(400, "缺少修复建议ID");
        }
    }

    static void validateStateVersionGuard(FixProposalApplyReq req, PlanningStateDTO state) {
        Integer sourceVersionGuard = req == null ? null : req.getSourceVersionGuard();
        if (sourceVersionGuard == null || state == null || !sourceVersionGuard.equals(state.getVersion())) {
            throw new BusinessException(409, "当前方案已变化，请重新生成修复建议");
        }
    }

    static void ensureReviewReady(PlanningStateDTO state) {
        ReviewStateDTO reviewState = state == null ? null : state.getReviewState();
        if (state == null || reviewState == null || reviewState.getChecks() == null || reviewState.getChecks().isEmpty()
                || Boolean.TRUE.equals(state.getStaleFlags().getReview())) {
            throw new BusinessException(409, "当前审查结果已过期，请重新生成修复建议");
        }
    }

    static void validateProposalForApply(FixProposalApplyReq req, FixProposalDTO proposal) {
        if (!RepairProposalTaxonomy.isReviewCheckSource(proposal.getProposalSource())
                && !RepairProposalTaxonomy.isUserGoalSource(proposal.getProposalSource())) {
            throw new BusinessException(400, "当前处理建议暂不支持在此入口应用");
        }
        if (RepairProposalTaxonomy.isUserGoalSource(proposal.getProposalSource())) {
            validateUserGoalProposalForApply(req, proposal);
            return;
        }
        if (RepairProposalTaxonomy.isPreviewOnlyStatus(proposal.getStatus())
                && !isSupportedStrategy(proposal.getStrategy())) {
            throw new BusinessException(400, "当前修复建议暂不支持自动应用");
        }
        if (!RepairProposalTaxonomy.isReadyStatus(proposal.getStatus())) {
            throw new BusinessException(400, "当前修复建议不可应用");
        }
        Integer sourceVersionGuard = req == null ? null : req.getSourceVersionGuard();
        if (sourceVersionGuard == null || !sourceVersionGuard.equals(proposal.getSourceVersionGuard())) {
            throw new BusinessException(409, "修复建议版本已变化，请重新确认");
        }
        if (!isSupportedStrategy(proposal.getStrategy())) {
            throw new BusinessException(400, "当前修复建议暂不支持自动应用");
        }
    }

    private static void validateUserGoalProposalForApply(FixProposalApplyReq req, FixProposalDTO proposal) {
        if (req == null || req.getUserGoalRequest() == null) {
            throw new BusinessException(400, "缺少用户目标调整请求");
        }
        if (!RepairProposalTaxonomy.isReadyStatus(proposal.getStatus())) {
            throw new BusinessException(400, "当前调整预览不可应用");
        }
        Integer sourceVersionGuard = req.getSourceVersionGuard();
        if (sourceVersionGuard == null || !sourceVersionGuard.equals(proposal.getSourceVersionGuard())) {
            throw new BusinessException(409, "调整预览版本已变化，请重新确认");
        }
        if (!RepairProposalTaxonomy.isUserGoalApplyableStrategy(proposal.getStrategy())) {
            throw new BusinessException(400, "当前调整预览暂不支持自动应用");
        }
        validateCanonicalMetadata(req, proposal);
    }

    static boolean hasCanonicalMetadata(FixProposalApplyReq req) {
        return req != null && (!Strings.isNullOrEmpty(req.getCanonicalObjectiveDigest())
                || !Strings.isNullOrEmpty(req.getSolverVersion())
                || !Strings.isNullOrEmpty(req.getSolverInputDigest()));
    }

    static boolean isLegacyCanonicalProposal(FixProposalDTO proposal) {
        return proposal != null && Strings.isNullOrEmpty(proposal.getCanonicalObjectiveDigest())
                && Strings.isNullOrEmpty(proposal.getSolverVersion())
                && Strings.isNullOrEmpty(proposal.getSolverInputDigest())
                && proposal.getSolverResult() == null;
    }

    private static void validateCanonicalMetadata(FixProposalApplyReq req, FixProposalDTO proposal) {
        if (!hasCanonicalMetadata(req)) {
            if (!isLegacyCanonicalProposal(proposal)) {
                throw new BusinessException(409, "canonical Proposal 元数据缺失，请重新生成调整预览");
            }
            return;
        }
        if (Strings.isNullOrEmpty(req.getCanonicalObjectiveDigest())
                || Strings.isNullOrEmpty(req.getSolverVersion())
                || Strings.isNullOrEmpty(req.getSolverInputDigest())) {
            throw new BusinessException(409, "canonical Proposal 元数据不完整，请重新生成调整预览");
        }
        // S4：两侧都带 hardObjectiveVersion 时，允许跨部署/回滚造成的 solverVersion 差异。
        // 判据 = 硬目标契约 major 相同 + objective digest 相同 + 提案仍与冻结 solverResult 绑定；
        // 请求侧 solverVersion/solverInputDigest 不再逐一相等（solverInputDigest 只保留在
        // proposal 与 solverResult 之间，防止请求来自不同部署快照时误杀）。
        // major 定义：版本串不含 '.' 时取整串；含 '.' 时取第一个 '.' 之前的前缀
        // （如 "solver-hard-objective-v1.2" 的 major 为 "solver-hard-objective-v1"）。
        // 任一侧缺失 hardObjectiveVersion 时走下面的旧精确三件套比对，语义不变。
        if (!Strings.isNullOrEmpty(req.getHardObjectiveVersion())
                && !Strings.isNullOrEmpty(proposal.getHardObjectiveVersion())) {
            if (!hardObjectiveMajor(req.getHardObjectiveVersion())
                    .equals(hardObjectiveMajor(proposal.getHardObjectiveVersion()))) {
                throw new BusinessException(409, "canonical Proposal 硬目标契约不兼容，请重新生成调整预览");
            }
            if (!req.getCanonicalObjectiveDigest().equals(proposal.getCanonicalObjectiveDigest())) {
                throw new BusinessException(409, "canonical Proposal 已变化，请重新生成调整预览");
            }
            if (proposal.getSolverResult() == null
                    || Strings.isNullOrEmpty(proposal.getSolverVersion())
                    || Strings.isNullOrEmpty(proposal.getSolverInputDigest())
                    || !proposal.getSolverVersion().equals(proposal.getSolverResult().getSolverVersion())
                    || !proposal.getSolverInputDigest().equals(proposal.getSolverResult().getInputDigest())) {
                throw new BusinessException(409, "canonical Proposal 缺少冻结求解结果，请重新生成调整预览");
            }
            return;
        }
        if (!req.getCanonicalObjectiveDigest().equals(proposal.getCanonicalObjectiveDigest())
                || !req.getSolverVersion().equals(proposal.getSolverVersion())
                || !req.getSolverInputDigest().equals(proposal.getSolverInputDigest())) {
            throw new BusinessException(409, "canonical Proposal 已变化，请重新生成调整预览");
        }
        if (proposal.getSolverResult() == null
                || !proposal.getSolverVersion().equals(proposal.getSolverResult().getSolverVersion())
                || !proposal.getSolverInputDigest().equals(proposal.getSolverResult().getInputDigest())) {
            throw new BusinessException(409, "canonical Proposal 缺少冻结求解结果，请重新生成调整预览");
        }
    }

    /**
     * 硬目标契约 major：无 '.' 时整串即 major，否则取第一个 '.' 之前的前缀。
     * 包可见，供 apply 后置校验（`UnifiedPlanPostconditionValidator`）复用同一判据。
     */
    static String hardObjectiveMajor(String version) {
        int dot = version.indexOf('.');
        return dot < 0 ? version : version.substring(0, dot);
    }

    static boolean isSupportedStrategy(String strategy) {
        return RepairProposalTaxonomy.isApplyableStrategy(strategy);
    }
}
