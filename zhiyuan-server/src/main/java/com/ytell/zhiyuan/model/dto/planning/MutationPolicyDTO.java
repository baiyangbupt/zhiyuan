package com.ytell.zhiyuan.model.dto.planning;

import com.google.common.collect.Sets;
import lombok.Data;

import java.util.Set;

/** J5.3 动作变更策略；硬语义，不能只靠 churn 权重表达。 */
@Data
public class MutationPolicyDTO {
    /** GENERATE|FILL|ADD|REPLACE|REFILL|SCOPE|REVIEW_FIX */
    private String action = "GENERATE";
    private Boolean allowAdd = true;
    private Boolean lockExisting = false;
    private Set<String> forcedRemoveEntityIds = Sets.newLinkedHashSet();
    private Set<String> removableEntityIds = Sets.newLinkedHashSet();
    private Set<String> frozenRequiredEntityIds = Sets.newLinkedHashSet();
    private Set<String> forcedAddEntityIds = Sets.newLinkedHashSet();
    private Boolean countAsChurn = true;
    /** FILL/SCOPE/REFILL：候选必须通过补入安全谓词（旧 fill/scope 的过滤口径）。 */
    private Boolean requireCompensationSafe = false;
    /** 初始方案：把风险标签/条目膨胀/preferred 丢失作为 solver 硬约束。 */
    private Boolean initialContentGuard = false;
    /** J5.4 实验：同档优先规则是否作为选择目标（否则只影响排序）。 */
    private Boolean prioritySelection = false;
    /** 两阶段组内选择：当前组内专业数量上限；null/≤0 表示不帽。 */
    private Integer requiredMajorCount;
    /**
     * 排序动作语义：initial_tier_order_v1 / preserve_current_v1 / explicit_move_v1。
     * null 保留旧客户端行为；新链路必须显式写入并随 inputDigest 冻结。
     */
    private String orderingPolicyVersion;
    /**
     * 纯删除等收敛动作允许暂时保留已存在的专项冲突项；新增/补齐/替换/首版必须为 false。
     */
    private Boolean allowExistingSpecialPlanConflicts = false;
}
