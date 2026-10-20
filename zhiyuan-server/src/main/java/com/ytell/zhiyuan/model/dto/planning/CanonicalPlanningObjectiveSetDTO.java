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
    /**
     * solver-only 隐式档位平衡：只作为求解约束，不进入 canonical objective /
     * solverObjectiveDigest，也不产生冻结的 tier_* objectiveResults。
     * 用于空方案首次补齐时沿用推荐池档位比例。
     */
    private TierAllocationConstraintDTO solverTierBalance;
    private TierAllocationResolutionDTO tierAllocationResolution;
    private Boolean tierAllocationStateChanged = false;
    private List<PriorityRuleDTO> orderingConstraints = Lists.newArrayList();
    private String objectiveDigest;

    // J5.3（v2 编译时写入；旧路径保持 null）
    private StructureTargetDTO structureTarget;
    private UtilityModelDTO utilityModel;
    private MutationPolicyDTO mutationPolicy;
    /** J5.3 P4：默认 null（等同 off）；solver.v2.diversity 开启时 enrichV2 写入 soft。 */
    private DiversityPolicyDTO diversityPolicy;
    private String hardObjectiveVersion;
    private String solverObjectiveVersion;
}
