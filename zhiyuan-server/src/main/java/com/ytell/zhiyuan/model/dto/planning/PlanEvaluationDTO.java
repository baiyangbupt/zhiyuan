package com.ytell.zhiyuan.model.dto.planning;

import com.google.common.collect.Lists;
import lombok.Data;

import java.util.List;

/**
 * 统一方案评价（J5.0 影子）。
 *
 * <p>findings 包含本次跑过的**所有** probe（含 pass）；用户面默认只展示
 * fail/unknown/需动作项。hardFeasible 是派生值，不允许独立判断。</p>
 */
@Data
public class PlanEvaluationDTO {
    /** 评价时的 stateVersion（与 evaluatedStateVersion 同值，保留旧名兼容）。 */
    private Integer planVersion;
    private Integer evaluatedStateVersion;
    private String planContentDigest;
    private Integer candidateSourceVersion;
    private String dataVersion;
    private String objectiveModelVersion;
    private String evaluationVersion;
    private String status = "completed";
    private Integer probesRun = 0;
    private StructureVectorDTO structure = new StructureVectorDTO();
    private List<EvaluationFindingDTO> findings = Lists.newArrayList();
    private Boolean hardFeasible = false;
    private String objectiveDigest;
}
