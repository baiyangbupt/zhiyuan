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
        if (!RepairProposalTaxonomy.isReviewCheckSource(proposal.getProposalSource())) {
            throw new BusinessException(400, "当前处理建议暂不支持在此入口应用");
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

    static boolean isSupportedStrategy(String strategy) {
        return RepairProposalTaxonomy.isApplyableStrategy(strategy);
    }
}
