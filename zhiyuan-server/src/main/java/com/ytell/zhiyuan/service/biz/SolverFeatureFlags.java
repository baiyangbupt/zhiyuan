package com.ytell.zhiyuan.service.biz;

/**
 * 求解器运行时特性开关。
 *
 * <p>P4 多样性：`-Dsolver.v2.diversity=true` 或环境变量
 * `SOLVER_V2_DIVERSITY=true` 时，enrichV2 写入 soft 多样性策略；默认关闭。</p>
 */
final class SolverFeatureFlags {

    private SolverFeatureFlags() {
    }

    static boolean diversityEnabled() {
        String value = System.getProperty("solver.v2.diversity");
        if (value == null) {
            value = System.getenv("SOLVER_V2_DIVERSITY");
        }
        return "true".equalsIgnoreCase(value) || "1".equals(value);
    }

    /**
     * J5.4 实验：优先规则作为选择阶段，而不只是排序目标。
     * 默认关闭；关闭时行为与当前完全一致。
     */
    static boolean prioritySelectionEnabled() {
        String value = System.getProperty("planning.priority.selection.enabled");
        if (value == null) {
            value = System.getenv("PLANNING_PRIORITY_SELECTION_ENABLED");
        }
        return "true".equalsIgnoreCase(value) || "1".equals(value);
    }
}
