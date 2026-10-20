package com.ytell.zhiyuan.service.biz;

/**
 * 专业组新增单元的组内专业帽。
 *
 * <p>默认关闭：solver 新增一个专业组时沿用旧行为，带入组内全部专业。
 * 打开后按 candidatePool.requiredMajorCount 截断新增单元的专业数，与
 * 初始推荐 buildPlanningUnit 的组内选专业口径一致；已有单元不裁剪。</p>
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
        return value != null && Boolean.parseBoolean(value.trim());
    }
}
