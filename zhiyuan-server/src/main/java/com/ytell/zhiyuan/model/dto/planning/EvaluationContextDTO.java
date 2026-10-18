package com.ytell.zhiyuan.model.dto.planning;

import com.google.common.collect.Lists;
import com.google.common.collect.Maps;
import lombok.Data;

import java.util.List;
import java.util.Map;

/**
 * 评价输入清单（J5.0 目标态）。
 *
 * <p>只承载**输入**，不承载评价结论；同一份 context + 同一 objectiveModelVersion
 * 才能复算出同一份 PlanEvaluation。缺字段必须显式标 unknown，不能用默认值伪装。</p>
 */
@Data
public class EvaluationContextDTO {
    private List<EvaluationEntryRefDTO> entries = Lists.newArrayList();
    /** 已确认的 include 覆盖要求（顺序即 coverage:index）。 */
    private List<CoverageRequirementDTO> coverageRequirements = Lists.newArrayList();
    /** 用户确认目标（HardPlanningObjectives.selectionTargetCount）。 */
    private Integer selectionTargetCount;
    /** 候选池/摘要目标（requiredCount）。 */
    private Integer requiredCount;
    private Map<String, Integer> requiredTierCounts = Maps.newLinkedHashMap();
    private String admissionMode;
    private String sourceProvince;
    private Integer userScore;
    private Integer candidateSourceVersion;
    /** 评价时的 stateVersion（= ReviewStateDTO.sourceVersion）。 */
    private Integer evaluatedStateVersion;
    private String planContentDigest;
    /** dataFreshnessState.dataVersion（数据新鲜度证据版本）。 */
    private String dataVersion;
}
