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

    /** Phase 2：结构质量策略开关；默认 off，显式 soft/enforced 才注入。 */
    static String structureQualityMode() {
        String value = System.getProperty("solver.v2.structureQuality");
        if (value == null) {
            value = System.getenv("SOLVER_V2_STRUCTURE_QUALITY");
        }
        if (value == null || value.trim().isEmpty()) {
            return "off";
        }
        String normalized = value.trim().toLowerCase();
        return ("soft".equals(normalized) || "enforced".equals(normalized))
                ? normalized : "off";
    }

    /**
     * 结构优化允许的效用损失上限（相对无结构约束最优值），默认 3%。
     * 调参用 {@code -Dsolver.v2.structureQuality.maxUtilityLoss=0.05}。
     */
    static double structureQualityMaxUtilityLossRatio() {
        String value = System.getProperty("solver.v2.structureQuality.maxUtilityLoss");
        if (value == null) {
            value = System.getenv("SOLVER_V2_STRUCTURE_QUALITY_MAX_UTILITY_LOSS");
        }
        if (value == null || value.trim().isEmpty()) {
            return 0.03D;
        }
        try {
            double parsed = Double.parseDouble(value.trim());
            return Math.max(0D, Math.min(0.5D, parsed));
        } catch (NumberFormatException ex) {
            return 0.03D;
        }
    }

    /**
     * 影子对比：当前选择完成后，用 soft 结构策略再解一次，只打日志不落库。
     * 默认关闭；本地验证用 {@code -Dsolver.v2.structureQualityShadow=true}。
     */
    static boolean structureQualityShadowEnabled() {
        String value = System.getProperty("solver.v2.structureQualityShadow");
        if (value == null) {
            value = System.getenv("SOLVER_V2_STRUCTURE_QUALITY_SHADOW");
        }
        return "true".equalsIgnoreCase(value) || "1".equals(value);
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
