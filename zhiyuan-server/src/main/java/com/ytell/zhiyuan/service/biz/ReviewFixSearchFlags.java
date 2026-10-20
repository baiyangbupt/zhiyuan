package com.ytell.zhiyuan.service.biz;

import java.util.Arrays;
import java.util.LinkedHashSet;
import java.util.Locale;
import java.util.Set;

/**
 * J5.5c：Search 类审查修复的独立灰度开关。
 *
 * <p>Direct 倒挂只做显式重排，风险最低；count/coverage/safety/ratio/risk
 * 都要经过 staged solver 选集合，因此单独放量。总开关
 * {@link ReviewFixCommandFlags} 关闭时所有确认链都不可用；总开关打开但本开关
 * 关闭时，只保留 Direct 倒挂，Search/Safety/Ratio/Risk 提案不生成、不可
 * prepare/apply。</p>
 */
public final class ReviewFixSearchFlags {

    static final String PROPERTY = "review.fix.search.enabled";
    static final String ENV = "REVIEW_FIX_SEARCH_ENABLED";
    static final String STRATEGIES_PROPERTY = "review.fix.search.strategies";
    static final String STRATEGIES_ENV = "REVIEW_FIX_SEARCH_STRATEGIES";

    private ReviewFixSearchFlags() {
    }

    public static boolean enabled() {
        String value = System.getProperty(PROPERTY);
        if (value == null || value.trim().isEmpty()) {
            value = System.getenv(ENV);
        }
        return value != null && Boolean.parseBoolean(value.trim());
    }

    /**
     * 某个 finding 是否允许走 Search 修复。
     *
     * <p>允许集合为空或包含 {@code all} 时表示全部开放，保持只开总开关的
     * 兼容行为；否则按 count/coverage/safety/ratio/risk 分类过滤。</p>
     */
    public static boolean allows(String findingCode) {
        if (!enabled()) {
            return false;
        }
        Set<String> allowed = configuredStrategies();
        if (allowed.isEmpty() || allowed.contains("all")) {
            return true;
        }
        String category = categoryOf(findingCode);
        return category != null && allowed.contains(category);
    }

    static String categoryOf(String findingCode) {
        String code = findingCode == null ? "" : findingCode.trim().toLowerCase(Locale.ROOT);
        if (code.startsWith("coverage")) {
            return "coverage";
        }
        if ("count_target".equals(code) || "count_validation_hard".equals(code)
                || "count_validation".equals(code)) {
            return "count";
        }
        if ("safety_guard".equals(code)) {
            return "safety";
        }
        if ("ratio_distribution".equals(code)) {
            return "ratio";
        }
        if ("high_tuition".equals(code) || "cooperative_program".equals(code)
                || "admission_limit".equals(code) || "special_enrollment".equals(code)) {
            return "risk";
        }
        return null;
    }

    private static Set<String> configuredStrategies() {
        String value = System.getProperty(STRATEGIES_PROPERTY);
        if (value == null || value.trim().isEmpty()) {
            value = System.getenv(STRATEGIES_ENV);
        }
        if (value == null || value.trim().isEmpty()) {
            return new LinkedHashSet<String>();
        }
        Set<String> strategies = new LinkedHashSet<String>();
        for (String item : Arrays.asList(value.split(","))) {
            String normalized = item == null ? "" : item.trim().toLowerCase(Locale.ROOT);
            if (!normalized.isEmpty()) {
                strategies.add(normalized);
            }
        }
        return strategies;
    }
}
