package com.ytell.zhiyuan.service.biz;

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

    private ReviewFixSearchFlags() {
    }

    public static boolean enabled() {
        String value = System.getProperty(PROPERTY);
        if (value == null || value.trim().isEmpty()) {
            value = System.getenv(ENV);
        }
        return value != null && Boolean.parseBoolean(value.trim());
    }
}
