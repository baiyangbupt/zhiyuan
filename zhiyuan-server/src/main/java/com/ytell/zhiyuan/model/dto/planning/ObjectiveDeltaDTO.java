package com.ytell.zhiyuan.model.dto.planning;

import com.google.common.collect.Lists;
import com.google.common.collect.Maps;
import lombok.Data;

import java.util.List;
import java.util.Map;

/**
 * 审查 → 修复的桥：finding 只带 objectiveDelta，不直接带第二套修复命令。
 * 命令由 PlanCommandCompiler 从 delta 编译，保证预览/冻结/后置条件与普通动作同源。
 */
@Data
public class ObjectiveDeltaDTO {
    private Map<String, Object> constraintPatch = Maps.newLinkedHashMap();
    private Integer targetCountDelta;
    private Integer targetCount;
    private TierAllocationConstraintDTO tierConstraint;
    private Integer safetyMinLocalProtect;
    private List<CoverageRequirementDTO> coverageRequirements = Lists.newArrayList();
    private Map<String, Integer> tierQuotaDelta = Maps.newLinkedHashMap();
    private List<EvaluationEntryRefDTO> addTargets = Lists.newArrayList();
    private List<EvaluationEntryRefDTO> removeTargets = Lists.newArrayList();
    private List<EvaluationEntryRefDTO> reorderTargets = Lists.newArrayList();
    private String reasonCode;
    /** PlanCommandCompiler 的输入：修复策略（与 RepairProposalTaxonomy.Strategy 同名）。 */
    private String strategy;
    /** 该 delta 来自哪个旧 check/probe（审计与 golden 对照）。 */
    private String sourceCheck;
}
