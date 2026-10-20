package com.ytell.zhiyuan.service.biz;

import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

class ReviewFixSearchFlagsTest {

    @AfterEach
    void tearDown() {
        System.clearProperty(ReviewFixSearchFlags.PROPERTY);
        System.clearProperty(ReviewFixSearchFlags.STRATEGIES_PROPERTY);
    }

    @Test
    void emptyAllowlistMeansAllSearchStrategiesWhenSwitchIsOn() {
        System.setProperty(ReviewFixSearchFlags.PROPERTY, "true");
        for (String code : new String[]{"count_target", "coverage:0", "safety_guard",
                "ratio_distribution", "high_tuition", "cooperative_program",
                "admission_limit", "special_enrollment"}) {
            assertTrue(ReviewFixSearchFlags.allows(code), code);
        }
    }

    @Test
    void allowlistRestrictsFindingCategories() {
        System.setProperty(ReviewFixSearchFlags.PROPERTY, "true");
        System.setProperty(ReviewFixSearchFlags.STRATEGIES_PROPERTY, "count, coverage");

        assertTrue(ReviewFixSearchFlags.allows("count_target"));
        assertTrue(ReviewFixSearchFlags.allows("coverage:0"));
        assertFalse(ReviewFixSearchFlags.allows("safety_guard"));
        assertFalse(ReviewFixSearchFlags.allows("ratio_distribution"));
        assertFalse(ReviewFixSearchFlags.allows("high_tuition"));
        assertFalse(ReviewFixSearchFlags.allows("probability_inversion"));
    }

    @Test
    void switchOffOverridesAnyAllowlist() {
        System.setProperty(ReviewFixSearchFlags.PROPERTY, "false");
        System.setProperty(ReviewFixSearchFlags.STRATEGIES_PROPERTY, "all");
        assertFalse(ReviewFixSearchFlags.allows("count_target"));
    }

    @Test
    void categoryMappingIsExplicitAndUnknownCodesAreRejected() {
        System.setProperty(ReviewFixSearchFlags.PROPERTY, "true");
        System.setProperty(ReviewFixSearchFlags.STRATEGIES_PROPERTY, "risk");

        assertEquals("count", ReviewFixSearchFlags.categoryOf("count_validation_hard"));
        assertEquals("coverage", ReviewFixSearchFlags.categoryOf("coverage:2"));
        assertEquals("risk", ReviewFixSearchFlags.categoryOf("special_enrollment"));
        assertNull(ReviewFixSearchFlags.categoryOf("unknown"));
        assertTrue(ReviewFixSearchFlags.allows("admission_limit"));
        assertFalse(ReviewFixSearchFlags.allows("safety_guard"));
    }
}
