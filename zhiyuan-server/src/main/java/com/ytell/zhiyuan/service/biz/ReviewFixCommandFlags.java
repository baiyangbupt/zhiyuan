package com.ytell.zhiyuan.service.biz;

/**
 * J5.5b：审查修复写命令的灰度开关。
 *
 * <p>默认关闭——关闭时 prepare/apply 继续走旧的“每次重新生成”路径，回滚只需关开关。
 * 打开后才允许 read-only 预览 → prepare 冻结 → pending → 冻结回放 → 原探针后置校验。</p>
 */
public final class ReviewFixCommandFlags {

    static final String PROPERTY = "review.fix.command.enabled";
    static final String ENV = "REVIEW_FIX_COMMAND_ENABLED";

    private ReviewFixCommandFlags() {
    }

    public static boolean enabled() {
        String value = System.getProperty(PROPERTY);
        if (value == null || value.trim().isEmpty()) {
            value = System.getenv(ENV);
        }
        return value != null && Boolean.parseBoolean(value.trim());
    }
}
