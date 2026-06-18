package com.ytell.zhiyuan.service.biz;

import com.ytell.zhiyuan.model.enums.SessionStatus;

import java.util.Date;

public final class DataFreshnessSchedulePolicy {
    public static final int RECENT_INTERVAL_MINUTES = 120;
    public static final int ACTIVE_INTERVAL_MINUTES = 180;
    public static final int MAX_INTERVAL_MINUTES = 300;

    private static final long HOUR_MS = 60L * 60L * 1000L;
    private static final long DAY_MS = 24L * HOUR_MS;

    private DataFreshnessSchedulePolicy() {
    }

    public static boolean isSupportedPrepareType(String prepareType) {
        String normalized = trim(prepareType);
        return "VOLUNTEER".equalsIgnoreCase(normalized);
    }

    public static boolean isBackgroundEligible(String prepareType, String sessionStatus) {
        if (!isSupportedPrepareType(prepareType)) {
            return false;
        }
        String status = trim(sessionStatus);
        return SessionStatus.GOING.name().equalsIgnoreCase(status) || SessionStatus.WAIT.name().equalsIgnoreCase(status);
    }

    public static int calculateIntervalMinutes(Date sessionCreateTime, Date lastAccessedAt, String sessionStatus, Date now) {
        Date safeNow = now == null ? new Date() : now;
        Date newestActivityAt = max(sessionCreateTime, lastAccessedAt);
        if (newestActivityAt != null && safeNow.getTime() - newestActivityAt.getTime() <= DAY_MS) {
            return RECENT_INTERVAL_MINUTES;
        }
        if (sessionCreateTime != null
                && safeNow.getTime() - sessionCreateTime.getTime() <= 7L * DAY_MS
                && SessionStatus.GOING.name().equalsIgnoreCase(trim(sessionStatus))) {
            return ACTIVE_INTERVAL_MINUTES;
        }
        return MAX_INTERVAL_MINUTES;
    }

    public static Date calculateNextCheckAt(Date lastCheckedAt, int intervalMinutes, Date now) {
        Date base = lastCheckedAt == null ? (now == null ? new Date() : now) : lastCheckedAt;
        int safeInterval = Math.min(Math.max(intervalMinutes, 1), MAX_INTERVAL_MINUTES);
        return new Date(base.getTime() + safeInterval * 60L * 1000L);
    }

    public static boolean isOverdue(Date lastCheckedAt, Date nextCheckAt, Date now) {
        Date safeNow = now == null ? new Date() : now;
        if (lastCheckedAt == null) {
            return true;
        }
        if (nextCheckAt != null && !nextCheckAt.after(safeNow)) {
            return true;
        }
        return safeNow.getTime() - lastCheckedAt.getTime() >= MAX_INTERVAL_MINUTES * 60L * 1000L;
    }

    private static Date max(Date left, Date right) {
        if (left == null) {
            return right;
        }
        if (right == null) {
            return left;
        }
        return left.after(right) ? left : right;
    }

    private static String trim(String value) {
        return value == null ? "" : value.trim();
    }
}
