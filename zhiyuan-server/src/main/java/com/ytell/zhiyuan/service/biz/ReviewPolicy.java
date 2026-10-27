package com.ytell.zhiyuan.service.biz;

import com.google.common.collect.Lists;
import com.ytell.zhiyuan.model.dto.planning.ReviewAvailabilityDTO;
import com.ytell.zhiyuan.model.dto.planning.ReviewStateDTO;

/**
 * 旧经验审查的独立服务端策略。
 *
 * <p>{@code planning.review.mode=active|paused} 与 {@code review.fix.*} 正交：旧的
 * 修复开关只控制写链灰度，paused 则明确表示“本轮不运行旧审查、也不把它当成通过”。
 * 该策略是启动配置，不做热切换；非法值必须让启动失败，不能静默回退 active。</p>
 */
public final class ReviewPolicy {

    static final String PROPERTY = "planning.review.mode";
    static final String ENV = "PLANNING_REVIEW_MODE";
    static final String ACTIVE = "active";
    static final String PAUSED = "paused";
    public static final String POLICY_VERSION = "review-containment-v1";
    public static final String REASON_PAUSED = "review_paused";

    /** Spring 配置值（--planning.review.mode / yml）；显式 JVM 属性与环境变量优先。 */
    private static volatile String springMode;

    private ReviewPolicy() {
    }

    static void configureFromSpring(String value) {
        springMode = value == null || value.trim().isEmpty() ? null : value.trim();
    }

    public static String mode() {
        String value = System.getProperty(PROPERTY);
        if (value == null || value.trim().isEmpty()) {
            value = System.getenv(ENV);
        }
        if (value == null || value.trim().isEmpty()) {
            value = springMode;
        }
        if (value == null || value.trim().isEmpty()) {
            return ACTIVE;
        }
        String normalized = value.trim().toLowerCase(java.util.Locale.ROOT);
        if (!ACTIVE.equals(normalized) && !PAUSED.equals(normalized)) {
            throw new IllegalStateException("invalid " + PROPERTY + ": " + value
                    + " (expected active or paused)");
        }
        return normalized;
    }

    public static void validateConfiguration() {
        mode();
    }

    public static boolean paused() {
        return PAUSED.equals(mode());
    }

    public static boolean isPaused(ReviewStateDTO reviewState) {
        if (reviewState == null) {
            return false;
        }
        if (PAUSED.equalsIgnoreCase(reviewState.getStatus())) {
            return true;
        }
        return reviewState.getAvailability() != null
                && PAUSED.equalsIgnoreCase(reviewState.getAvailability().getMode());
    }

    public static ReviewAvailabilityDTO availability() {
        ReviewAvailabilityDTO availability = new ReviewAvailabilityDTO();
        availability.setMode(mode());
        if (paused()) {
            availability.setReasonCode(REASON_PAUSED);
            availability.setPolicyVersion(POLICY_VERSION);
        }
        return availability;
    }

    /**
     * paused 的对外投影。历史审查行保持不动；这里只构造响应副本。
     *
     * <p>刻意不复制 summary/checks/findings/hardFeasible：null 风险数不是“0 风险”，
     * 所有消费者必须先看 availability/status，不能落进旧的 passed 分支。</p>
     */
    public static ReviewStateDTO pausedProjection() {
        ReviewStateDTO review = new ReviewStateDTO();
        review.setStatus(PAUSED);
        review.setReviewedAt(null);
        review.setSourceVersion(null);
        review.setSummary(null);
        review.setChecks(Lists.newArrayList());
        review.setCompensationPreview(null);
        review.setEvaluationVersion(null);
        review.setObjectiveModelVersion(null);
        review.setEvaluatedStateVersion(null);
        review.setEvaluationStatus("unavailable");
        review.setProbesRun(0);
        review.setHardFeasible(null);
        review.setFindings(Lists.newArrayList());
        review.setAvailability(availability());
        return review;
    }

    /** 只投影响应；存储在 domain 里的旧 reviewState 不改写。 */
    public static void projectForOutput(com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO state) {
        if (paused() && state != null) {
            state.setReviewState(pausedProjection());
        }
    }
}
