package com.ytell.zhiyuan.service.biz;

import java.util.LinkedHashSet;
import java.util.Set;

/**
 * 初始方案生成是否让 staged solver 主导选择。
 *
 * <p>默认打开：initial_auto 会把 requiredCount 作为临时初始目标传给 solver，
 * 让初始选择也走同一套优化器；该目标不写入 durable 用户目标。显式
 * {@code false} 回滚旧启发式；全局关闭时仍可用
 * {@code planning.initial.solver.sessions} 按会话灰度。</p>
 */
public final class InitialPlanSolverFlags {

    static final String PROPERTY = "planning.initial.solver.enabled";
    static final String ENV = "PLANNING_INITIAL_SOLVER_ENABLED";
    /** 测试环境按会话放量：逗号分隔的 chatSessionId。 */
    static final String SESSIONS_PROPERTY = "planning.initial.solver.sessions";
    static final String SESSIONS_ENV = "PLANNING_INITIAL_SOLVER_SESSIONS";

    private InitialPlanSolverFlags() {
    }

    public static boolean enabled() {
        String value = System.getProperty(PROPERTY);
        if (value == null || value.trim().isEmpty()) {
            value = System.getenv(ENV);
        }
        if (value == null || value.trim().isEmpty()) {
            return true;
        }
        return Boolean.parseBoolean(value.trim());
    }

    public static boolean enabled(Long sessionId) {
        return enabled() || configuredSessions().contains(String.valueOf(sessionId));
    }

    static Set<String> configuredSessions() {
        String value = System.getProperty(SESSIONS_PROPERTY);
        if (value == null || value.trim().isEmpty()) {
            value = System.getenv(SESSIONS_ENV);
        }
        Set<String> sessions = new LinkedHashSet<String>();
        if (value == null || value.trim().isEmpty()) {
            return sessions;
        }
        for (String item : value.split(",")) {
            String normalized = item == null ? "" : item.trim();
            if (!normalized.isEmpty()) {
                sessions.add(normalized);
            }
        }
        return sessions;
    }
}
