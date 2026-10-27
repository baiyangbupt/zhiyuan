package com.ytell.zhiyuan.service.biz;

import com.google.common.base.Strings;

/**
 * 录取率数值的展示/评价口径。
 *
 * <p>上游的 admissionRatio 不是概率；1.0 在真实候选池中大量同值出现，
 * 更像默认/下限/未计算截断。这里只做桶和置信度归类，不能把它解释成 1%。</p>
 */
final class AdmissionRatioBucketSupport {

    static final String CONFIDENCE_COMPUTED = "computed";
    static final String CONFIDENCE_CLAMPED = "clamped";
    static final String CONFIDENCE_UNKNOWN = "unknown";

    static final String BUCKET_UNKNOWN = "unknown";
    static final String BUCKET_SPRINT_LOW = "sprint_low";
    static final String BUCKET_SPRINT_5_15 = "sprint_5_15";
    static final String BUCKET_SPRINT_15_30 = "sprint_15_30";
    static final String BUCKET_SPRINT_30_50 = "sprint_30_50";
    static final String BUCKET_STABLE_50_60 = "stable_50_60";
    static final String BUCKET_STABLE_60_70 = "stable_60_70";
    static final String BUCKET_PROTECT_70_85 = "protect_70_85";
    static final String BUCKET_PROTECT_85_95 = "protect_85_95";
    static final String BUCKET_PROTECT_95_100 = "protect_95_100";

    private AdmissionRatioBucketSupport() {
    }

    static String confidence(Double ratio) {
        if (ratio == null || ratio.isNaN() || ratio.isInfinite()) {
            return CONFIDENCE_UNKNOWN;
        }
        return ratio <= 1.0D ? CONFIDENCE_CLAMPED : CONFIDENCE_COMPUTED;
    }

    static String bucket(String tier, Double ratio) {
        if (ratio == null || ratio.isNaN() || ratio.isInfinite() || ratio <= 1.0D) {
            return BUCKET_UNKNOWN;
        }
        String normalized = Strings.nullToEmpty(tier).trim().toLowerCase();
        if ("sprint".equals(normalized) || "冲".equals(normalized)) {
            if (ratio <= 5D) return BUCKET_SPRINT_LOW;
            if (ratio <= 15D) return BUCKET_SPRINT_5_15;
            if (ratio <= 30D) return BUCKET_SPRINT_15_30;
            if (ratio <= 50D) return BUCKET_SPRINT_30_50;
            return BUCKET_UNKNOWN;
        }
        if ("stable".equals(normalized) || "稳".equals(normalized)) {
            if (ratio <= 60D) return BUCKET_STABLE_50_60;
            return BUCKET_STABLE_60_70;
        }
        if ("protect".equals(normalized) || "保".equals(normalized)) {
            if (ratio <= 85D) return BUCKET_PROTECT_70_85;
            if (ratio <= 95D) return BUCKET_PROTECT_85_95;
            return BUCKET_PROTECT_95_100;
        }
        return BUCKET_UNKNOWN;
    }

    /** 该档位定义了几个“已知桶”；用于判断 13 条分 2 桶时的 54% 是否只是取整。 */
    static int knownBucketCount(String tier) {
        String normalized = Strings.nullToEmpty(tier).trim().toLowerCase();
        if ("sprint".equals(normalized) || "冲".equals(normalized)) {
            return 4;
        }
        if ("stable".equals(normalized) || "稳".equals(normalized)) {
            return 2;
        }
        if ("protect".equals(normalized) || "保".equals(normalized)) {
            return 3;
        }
        return 0;
    }

    static int bucketIndex(String bucket) {
        if (BUCKET_SPRINT_LOW.equals(bucket)) return 0;
        if (BUCKET_SPRINT_5_15.equals(bucket)) return 1;
        if (BUCKET_SPRINT_15_30.equals(bucket)) return 2;
        if (BUCKET_SPRINT_30_50.equals(bucket)) return 3;
        if (BUCKET_STABLE_50_60.equals(bucket)) return 4;
        if (BUCKET_STABLE_60_70.equals(bucket)) return 5;
        if (BUCKET_PROTECT_70_85.equals(bucket)) return 6;
        if (BUCKET_PROTECT_85_95.equals(bucket)) return 7;
        if (BUCKET_PROTECT_95_100.equals(bucket)) return 8;
        return -1;
    }
}
