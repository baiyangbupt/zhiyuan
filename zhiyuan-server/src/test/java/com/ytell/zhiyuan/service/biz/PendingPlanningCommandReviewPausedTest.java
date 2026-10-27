package com.ytell.zhiyuan.service.biz;

import com.ytell.zhiyuan.model.dto.planning.ReviewStateDTO;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;

import java.util.ArrayList;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;

class PendingPlanningCommandReviewPausedTest {

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
    void rerunReviewRecordsSkippedPausedWithoutCallingBackend() {
        PendingPlanningCommandBizService service = new PendingPlanningCommandBizService();
        List<String> steps = new ArrayList<String>();

        ReviewStateDTO review = ReflectionTestUtils.invokeMethod(service,
                "rerunReviewAfterMutation", 1L, 101L, true, steps);

        assertNotNull(review);
        assertEquals("paused", review.getStatus());
        assertEquals("unavailable", review.getEvaluationStatus());
        assertEquals(java.util.Collections.singletonList("review_skipped_paused"), steps);
    }
}
