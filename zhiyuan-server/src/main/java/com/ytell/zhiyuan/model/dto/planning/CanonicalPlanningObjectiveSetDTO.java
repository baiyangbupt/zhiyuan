package com.ytell.zhiyuan.model.dto.planning;

import com.google.common.collect.Lists;
import lombok.Data;

import java.util.List;

@Data
public class CanonicalPlanningObjectiveSetDTO {
    private String schemaVersion = "4.1.0-m2";
    private Integer sourceVersion;
    private String countMode;
    private Integer targetCount;
    private HardConstraintsDTO eligibilityConstraints = new HardConstraintsDTO();
    private List<CoverageRequirementDTO> coverageConstraints = Lists.newArrayList();
    private TierQuotaGoalDTO tierAllocationGoal;
    private TierAllocationConstraintDTO tierAllocationConstraint;
    private TierAllocationResolutionDTO tierAllocationResolution;
    private Boolean tierAllocationStateChanged = false;
    private List<PriorityRuleDTO> orderingConstraints = Lists.newArrayList();
    private String objectiveDigest;

    // J5.3（v2 编译时写入；旧路径保持 null）
    private StructureTargetDTO structureTarget;
    private UtilityModelDTO utilityModel;
    private MutationPolicyDTO mutationPolicy;
    /** J5.3 P4：默认 null（等同 off）；enrichV2 不填写，测试/调用方可显式设置。 */
    private DiversityPolicyDTO diversityPolicy;
    private String hardObjectiveVersion;
    private String solverObjectiveVersion;
}
