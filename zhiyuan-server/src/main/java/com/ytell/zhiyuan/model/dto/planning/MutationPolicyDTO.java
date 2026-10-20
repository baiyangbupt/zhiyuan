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
}
