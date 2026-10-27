package com.ytell.zhiyuan.service.biz;

import com.ytell.zhiyuan.common.exception.BusinessException;
import com.ytell.zhiyuan.model.dto.planning.PendingPlanningCommandReq;
import com.ytell.zhiyuan.model.dto.planning.ReviewFixPrepareReq;
import com.ytell.zhiyuan.model.dto.planning.ReviewStateDTO;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

class PlanningStateServiceReviewPausedTest {

    private String originalMode;

    @BeforeEach
    void setUp() {
        originalMode = System.getProperty(ReviewPolicy.PROPERTY);
        System.setProperty(ReviewPolicy.PROPERTY, "paused");
    }

    @AfterEach
    void tearDown() {
        if (originalMode == null) {
            System.clearProperty(ReviewPolicy.PROPERTY);
        } else {
            System.setProperty(ReviewPolicy.PROPERTY, originalMode);
        }
    }

    @Test
    void runReviewReturnsPausedWithoutTouchingState() {
        PlanningStateService service = new PlanningStateService();

        ReviewStateDTO review = service.runReview(1L, 101L);

        assertEquals("paused", review.getStatus());
        assertEquals("unavailable", review.getEvaluationStatus());
        assertNull(review.getSummary());
        assertNull(review.getHardFeasible());
        assertTrue(review.getChecks().isEmpty());
        assertEquals("review_paused", review.getAvailability().getReasonCode());
    }

    @Test
    void prepareReviewFixProposalIsRejectedBeforeAnyWrite() {
        PlanningStateService service = new PlanningStateService();

        BusinessException failure = assertThrows(BusinessException.class,
                () -> service.prepareReviewFixProposal(1L, 101L, "req", "digest", new ReviewFixPrepareReq()));

        assertEquals(409, failure.getStatus());
        assertEquals("review_paused", failure.getMessage());
    }

    @Test
    void claimedReviewExecutionIsRejected() {
        PlanningStateService service = new PlanningStateService();

        BusinessException failure = assertThrows(BusinessException.class,
                () -> service.applyClaimedReviewFixProposal(1L, 101L, new PendingPlanningCommandReq()));

        assertEquals(409, failure.getStatus());
        assertEquals("review_paused", failure.getMessage());
    }
}
