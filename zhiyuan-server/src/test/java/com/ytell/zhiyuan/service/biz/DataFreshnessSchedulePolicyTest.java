package com.ytell.zhiyuan.service.biz;

import org.junit.jupiter.api.Test;

import java.util.Date;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

class DataFreshnessSchedulePolicyTest {

    @Test
    void shouldCapScheduleIntervalAtFiveHours() {
        Date now = new Date(10L * 24L * 60L * 60L * 1000L);
        Date oldCreateTime = new Date(now.getTime() - 10L * 24L * 60L * 60L * 1000L);

        int interval = DataFreshnessSchedulePolicy.calculateIntervalMinutes(oldCreateTime, null, "GOING", now);

        assertEquals(DataFreshnessSchedulePolicy.MAX_INTERVAL_MINUTES, interval);
        Date nextCheckAt = DataFreshnessSchedulePolicy.calculateNextCheckAt(now, interval, now);
        assertEquals(now.getTime() + 300L * 60L * 1000L, nextCheckAt.getTime());
    }

    @Test
    void shouldUseShorterIntervalForRecentVolunteerSession() {
        Date now = new Date(10L * 24L * 60L * 60L * 1000L);
        Date recentAccess = new Date(now.getTime() - 2L * 60L * 60L * 1000L);

        int interval = DataFreshnessSchedulePolicy.calculateIntervalMinutes(null, recentAccess, "GOING", now);

        assertEquals(DataFreshnessSchedulePolicy.RECENT_INTERVAL_MINUTES, interval);
    }

    @Test
    void shouldEnableOnlyVolunteerGoingOrWaitSessions() {
        assertTrue(DataFreshnessSchedulePolicy.isBackgroundEligible("VOLUNTEER", "GOING"));
        assertTrue(DataFreshnessSchedulePolicy.isBackgroundEligible("volunteer", "WAIT"));
        assertFalse(DataFreshnessSchedulePolicy.isBackgroundEligible("PREDICT", "GOING"));
        assertFalse(DataFreshnessSchedulePolicy.isBackgroundEligible("predict", "WAIT"));
        assertFalse(DataFreshnessSchedulePolicy.isBackgroundEligible(null, "GOING"));
        assertFalse(DataFreshnessSchedulePolicy.isBackgroundEligible("OTHER", "GOING"));
        assertFalse(DataFreshnessSchedulePolicy.isBackgroundEligible("VOLUNTEER", "FINISHED"));
    }
}
