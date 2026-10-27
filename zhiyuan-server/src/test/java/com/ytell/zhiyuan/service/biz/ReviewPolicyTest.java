package com.ytell.zhiyuan.service.biz;

import com.ytell.zhiyuan.model.dto.planning.ReviewAvailabilityDTO;
import com.ytell.zhiyuan.model.dto.planning.ReviewStateDTO;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

class ReviewPolicyTest {

    private String originalMode;

    @BeforeEach
    void setUp() {
        originalMode = System.getProperty(ReviewPolicy.PROPERTY);
        System.clearProperty(ReviewPolicy.PROPERTY);
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
    void defaultsToActive() {
        assertEquals("active", ReviewPolicy.mode());
        assertFalse(ReviewPolicy.paused());
    }

    @Test
    void pausedProjectionDropsOldEndorsementAndAddsAvailability() {
        System.setProperty(ReviewPolicy.PROPERTY, "paused");

        ReviewStateDTO review = ReviewPolicy.pausedProjection();

        assertEquals("paused", review.getStatus());
        assertEquals("unavailable", review.getEvaluationStatus());
        assertNull(review.getSummary());
        assertNull(review.getHardFeasible());
        assertNull(review.getReviewedAt());
        assertEquals(0, review.getProbesRun());
        assertTrue(review.getChecks().isEmpty());
        assertTrue(review.getFindings().isEmpty());
        ReviewAvailabilityDTO availability = review.getAvailability();
        assertEquals("paused", availability.getMode());
        assertEquals("review_paused", availability.getReasonCode());
        assertEquals(ReviewPolicy.POLICY_VERSION, availability.getPolicyVersion());
    }

    @Test
    void invalidModeFailsClosedInsteadOfFallingBackToActive() {
        System.setProperty(ReviewPolicy.PROPERTY, "sometimes");

        assertThrows(IllegalStateException.class, ReviewPolicy::mode);
    }
}
