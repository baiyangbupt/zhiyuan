package com.ytell.zhiyuan.service.biz;

/**
 * 求解器运行时特性开关。
 *
 * <p>P4 多样性：`-Dsolver.v2.diversity=true` 或环境变量
 * `SOLVER_V2_DIVERSITY=true` 时，enrichV2 写入 soft 多样性策略；默认关闭。</p>
 *
 * <p>J5.4 优先选择：默认开启；显式设为 false 可回退为“只影响排序”。</p>
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
     * J5.4：优先规则正式作为选择阶段（safety 之后、churn/档位之前）。
     *
     * <p>默认开启；保留显式关闭位，供灰度回滚：
     * {@code -Dplanning.priority.selection.enabled=false} 时行为回到
     * “优先规则只影响排序”。</p>
     */
    static boolean prioritySelectionEnabled() {
        String value = System.getProperty("planning.priority.selection.enabled");
        if (value == null || value.trim().isEmpty()) {
            value = System.getenv("PLANNING_PRIORITY_SELECTION_ENABLED");
        }
        if (value == null || value.trim().isEmpty()) {
            return true;
        }
        String normalized = value.trim().toLowerCase();
        return !("false".equals(normalized) || "0".equals(normalized)
                || "off".equals(normalized) || "no".equals(normalized));
    }
}
