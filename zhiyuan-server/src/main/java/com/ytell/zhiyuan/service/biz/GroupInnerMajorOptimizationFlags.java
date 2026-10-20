package com.ytell.zhiyuan.service.biz;

/**
 * 两阶段组内专业优化灰度。
 *
 * <p>{@code planning.group-inner.major-optimization.enabled}：
 * off（默认）| shadow | on。</p>
 */
public final class GroupInnerMajorOptimizationFlags {

    static final String PROPERTY = "planning.group-inner.major-optimization.enabled";
    static final String ENV = "PLANNING_GROUP_INNER_MAJOR_OPTIMIZATION_ENABLED";

    private GroupInnerMajorOptimizationFlags() {
    }

    public static String mode() {
        String value = System.getProperty(PROPERTY);
        if (value == null || value.trim().isEmpty()) {
            value = System.getenv(ENV);
        }
        if (value == null || value.trim().isEmpty()) {
            return "off";
        }
        String normalized = value.trim().toLowerCase();
        if ("on".equals(normalized) || "true".equals(normalized) || "1".equals(normalized)) {
            return "on";
        }
        if ("shadow".equals(normalized)) {
            return "shadow";
        }
        return "off";
    }

    public static boolean enabled() {
        return "on".equals(mode());
    }

    public static boolean shadow() {
        return "shadow".equals(mode());
    }
}
