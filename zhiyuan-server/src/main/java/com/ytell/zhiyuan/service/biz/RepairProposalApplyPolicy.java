package com.ytell.zhiyuan.service.biz;

import com.google.common.base.Strings;
import com.ytell.zhiyuan.common.exception.BusinessException;
import com.ytell.zhiyuan.model.dto.planning.FixProposalApplyReq;
import com.ytell.zhiyuan.model.dto.planning.FixProposalDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanSolverResultDTO;
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

    /**
     * canonical 目标元数据是否存在（判据在提案侧）。
     *
     * <p>staged solver 是唯一框架：新提案一律带 canonical 元数据（objective digest、
     * 硬目标契约版本以及承载 canonical objective 的冻结 solverResult）；scope-only 提案
     * （按范围/学费筛选等）按设计没有 canonical objective 元数据，因此跳过 canonical 校验。
     * 只带冻结结果却缺 digest/hardObjectiveVersion 的畸形提案视为 canonical 并 fail closed。
     */
    static boolean hasCanonicalMetadata(FixProposalDTO proposal) {
        return proposal != null && (!Strings.isNullOrEmpty(proposal.getCanonicalObjectiveDigest())
                || !Strings.isNullOrEmpty(proposal.getHardObjectiveVersion())
                || proposal.getSolverResult() != null);
    }

    /**
     * canonical 提案的唯一判据：apply 前（本类）与 apply 后
     * （`UnifiedPlanPostconditionValidator`）共用，保证两侧完全一致。
     *
     * <p>fail closed：请求与提案的 canonicalObjectiveDigest、hardObjectiveVersion 必须非空；
     * 提案必须携带冻结 solverResult，且提案的 solverVersion/solverInputDigest 与之一致；
     * 两侧 hardObjectiveVersion major 相同；两侧 objective digest 相同。
     *
     * <p>solverVersion/solverInputDigest 不再做请求↔提案的精确比对：staged solver 下
     * 跨部署/回滚的差异按硬目标契约 major 兼容，绑定校验只保留在提案与冻结结果之间。
     * hardObjectiveVersion 对 canonical 提案是强制的，缺失即失败（无 legacy 回退）。
     */
    static boolean canonicalMetadataMatches(FixProposalApplyReq req, FixProposalDTO proposal) {
        if (req == null || proposal == null
                || Strings.isNullOrEmpty(req.getCanonicalObjectiveDigest())
                || Strings.isNullOrEmpty(req.getHardObjectiveVersion())
                || Strings.isNullOrEmpty(proposal.getCanonicalObjectiveDigest())
                || Strings.isNullOrEmpty(proposal.getHardObjectiveVersion())) {
            return false;
        }
        PlanSolverResultDTO frozen = proposal.getSolverResult();
        // 提案↔冻结求解结果绑定：两侧都非空且逐字相等。
        if (frozen == null
                || Strings.isNullOrEmpty(proposal.getSolverVersion())
                || Strings.isNullOrEmpty(proposal.getSolverInputDigest())
                || !proposal.getSolverVersion().equals(frozen.getSolverVersion())
                || !proposal.getSolverInputDigest().equals(frozen.getInputDigest())) {
            return false;
        }
        return hardObjectiveMajor(req.getHardObjectiveVersion())
                .equals(hardObjectiveMajor(proposal.getHardObjectiveVersion()))
                && req.getCanonicalObjectiveDigest().equals(proposal.getCanonicalObjectiveDigest());
    }

    private static void validateCanonicalMetadata(FixProposalApplyReq req, FixProposalDTO proposal) {
        if (!hasCanonicalMetadata(proposal)) {
            // scope-only 提案：没有 canonical objective 元数据，保持兼容跳过。
            return;
        }
        if (!canonicalMetadataMatches(req, proposal)) {
            throw new BusinessException(409, "canonical Proposal 元数据不匹配，请重新生成调整预览");
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
