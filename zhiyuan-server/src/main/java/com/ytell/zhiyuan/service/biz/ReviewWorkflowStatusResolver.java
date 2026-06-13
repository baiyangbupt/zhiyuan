package com.ytell.zhiyuan.service.biz;

import com.ytell.zhiyuan.model.dto.planning.FixProposalDTO;
import com.ytell.zhiyuan.model.dto.planning.FixProposalStateDTO;
import com.ytell.zhiyuan.model.dto.planning.ReviewStateDTO;

import java.util.List;

final class ReviewWorkflowStatusResolver {

    private ReviewWorkflowStatusResolver() {
    }

    static String resolveRunStatus(ReviewStateDTO reviewState, FixProposalStateDTO fixProposalState) {
        if (reviewState == null || !"completed".equals(reviewState.getStatus())) {
            return "review_failed";
        }
        List<FixProposalDTO> proposals = fixProposalState == null ? null : fixProposalState.getProposals();
        String proposalStatus = RepairProposalStateBuilder.resolveStateStatus(proposals);
        if (RepairProposalTaxonomy.Status.EMPTY.equals(proposalStatus)) {
            return "review_passed_or_no_fix";
        }
        if (RepairProposalTaxonomy.Status.READY.equals(proposalStatus)) {
            return "ready_to_confirm";
        }
        if (RepairProposalTaxonomy.Status.PREVIEW_ONLY.equals(proposalStatus)) {
            return RepairProposalTaxonomy.Status.PREVIEW_ONLY;
        }
        return "blocked_or_info";
    }
}
