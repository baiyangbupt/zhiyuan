package com.ytell.zhiyuan.service.biz;

/**
 * 专业组新增单元的组内专业帽。
 *
 * <p>默认开启：solver 新增一个专业组时，按 candidatePool.requiredMajorCount
 * 截断组内专业数；组内专业本身不足 requiredMajorCount 时全部保留。
 * 与初始推荐 buildPlanningUnit 的组内选专业口径一致；已有单元不裁剪。
 * 显式设为 false 可回滚为“新增组带入全部专业”。</p>
 */
public final class GroupInnerMajorCapFlags {

    static final String PROPERTY = "planning.group-inner.major-cap.enabled";
    static final String ENV = "PLANNING_GROUP_INNER_MAJOR_CAP_ENABLED";

    private GroupInnerMajorCapFlags() {
    }

    public static boolean enabled() {
        String value = System.getProperty(PROPERTY);
        if (value == null || value.trim().isEmpty()) {
            value = System.getenv(ENV);
        }
        if (value == null || value.trim().isEmpty()) {
            return true;
        }
        String normalized = value.trim().toLowerCase();
        return !("false".equals(normalized) || "0".equals(normalized)
                || "off".equals(normalized) || "no".equals(normalized));
    }
}
