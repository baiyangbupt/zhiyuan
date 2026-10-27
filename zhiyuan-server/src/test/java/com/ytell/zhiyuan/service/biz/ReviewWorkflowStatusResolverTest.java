package com.ytell.zhiyuan.service.biz;

import com.google.common.collect.Lists;
import com.ytell.zhiyuan.model.dto.planning.FixProposalDTO;
import com.ytell.zhiyuan.model.dto.planning.FixProposalStateDTO;
import com.ytell.zhiyuan.model.dto.planning.ReviewStateDTO;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;

public class ReviewWorkflowStatusResolverTest {

    @Test
    void shouldResolveReviewFailedWhenReviewIsNotCompleted() {
        ReviewStateDTO reviewState = new ReviewStateDTO();
        reviewState.setStatus("running");

        assertEquals("review_failed",
                ReviewWorkflowStatusResolver.resolveRunStatus(reviewState, readyProposalState()));
        assertEquals("review_failed",
                ReviewWorkflowStatusResolver.resolveRunStatus(null, readyProposalState()));
    }

    @Test
    void shouldResolvePausedBeforeNoFix() {
        ReviewStateDTO reviewState = ReviewPolicy.pausedProjection();

        assertEquals("review_paused",
                ReviewWorkflowStatusResolver.resolveRunStatus(reviewState, new FixProposalStateDTO()));
    }

    @Test
    void shouldResolveNoFixWhenThereAreNoProposals() {
        ReviewStateDTO reviewState = completedReview();

        assertEquals("review_passed_or_no_fix",
                ReviewWorkflowStatusResolver.resolveRunStatus(reviewState, null));
        assertEquals("review_passed_or_no_fix",
                ReviewWorkflowStatusResolver.resolveRunStatus(reviewState, new FixProposalStateDTO()));
    }

    @Test
    void shouldPreferReadyOverPreviewOnly() {
        FixProposalStateDTO proposalState = new FixProposalStateDTO();
        proposalState.setProposals(Lists.newArrayList(proposal("preview_only"), proposal("ready")));

        assertEquals("ready_to_confirm",
                ReviewWorkflowStatusResolver.resolveRunStatus(completedReview(), proposalState));
    }

    @Test
    void shouldResolvePreviewOnlyWhenNoReadyProposalExists() {
        FixProposalStateDTO proposalState = new FixProposalStateDTO();
        proposalState.setProposals(Lists.newArrayList(proposal("blocked"), proposal("preview_only")));

        assertEquals("preview_only",
                ReviewWorkflowStatusResolver.resolveRunStatus(completedReview(), proposalState));
    }

    @Test
    void shouldResolveBlockedOrInfoWhenNoReadyOrPreviewProposalExists() {
        FixProposalStateDTO proposalState = new FixProposalStateDTO();
        proposalState.setProposals(Lists.newArrayList(proposal("blocked"), proposal("info")));

        assertEquals("blocked_or_info",
                ReviewWorkflowStatusResolver.resolveRunStatus(completedReview(), proposalState));
    }

    private ReviewStateDTO completedReview() {
        ReviewStateDTO reviewState = new ReviewStateDTO();
        reviewState.setStatus("completed");
        return reviewState;
    }

    private FixProposalStateDTO readyProposalState() {
        FixProposalStateDTO proposalState = new FixProposalStateDTO();
        proposalState.setProposals(Lists.newArrayList(proposal("ready")));
        return proposalState;
    }

    private FixProposalDTO proposal(String status) {
        FixProposalDTO proposal = new FixProposalDTO();
        proposal.setStatus(status);
        return proposal;
    }
}
