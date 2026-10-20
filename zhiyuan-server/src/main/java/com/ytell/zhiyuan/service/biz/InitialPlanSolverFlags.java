package com.ytell.zhiyuan.service.biz;

import java.util.LinkedHashSet;
import java.util.Set;

/**
 * 初始方案生成是否让 staged solver 主导选择。
 *
 * <p>默认关闭：无确认选择目标的会话保持旧启发式初始推荐，仅在已有
 * selectionTarget/coverage/tier 目标时由 enforceSelection 复核。打开后，
 * initial_auto 会把 requiredCount/默认目标作为临时初始目标传给 solver，
 * 让初始选择也走同一套优化器；该目标不写入 durable 用户目标。</p>
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
        return value != null && Boolean.parseBoolean(value.trim());
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
