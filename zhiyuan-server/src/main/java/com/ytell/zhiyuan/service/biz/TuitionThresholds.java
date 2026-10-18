package com.ytell.zhiyuan.service.biz;

/**
 * J5.4：学费阈值的单一口径。
 *
 * <p>审查 {@code high_tuition} 与 {@link PlanStructureEvaluator} 的
 * {@code highTuitionCount} 共用用户可见的高收费线（超过 20000/年）。
 * 结构向量旧口径 60000/年已退役，不再保留第二套高收费计数。</p>
 */
final class TuitionThresholds {

    /** 用户可见的高收费线：学费超过该值/年视为高收费。 */
    static final int HIGH_TUITION_RISK_PER_YEAR = 20000;

    private TuitionThresholds() {
    }
}
