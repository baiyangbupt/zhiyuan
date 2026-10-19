package com.ytell.zhiyuan.model.dto.planning;

import com.google.common.collect.Lists;
import lombok.Data;

import java.util.List;

@Data
public class PlanSolverResultDTO {
    private String status;
    private List<String> selectedEntityIds = Lists.newArrayList();
    private List<String> orderedEntityIds = Lists.newArrayList();
    private List<String> removeEntityIds = Lists.newArrayList();
    private List<String> addEntityIds = Lists.newArrayList();
    private List<ObjectiveResultDTO> objectiveResults = Lists.newArrayList();
    /**
     * 字典序各阶段的最优值（safety/churn/tier_anchor/utility/diversity），
     * 仅用于审计/观测；不参与 inputDigest，也不作为冻结回放的正确性判据。
     */
    private List<StageResultDTO> stageResults = Lists.newArrayList();
    private List<DiagnosticDTO> diagnostics = Lists.newArrayList();
    private String solverVersion;
    /**
     * 硬目标契约版本：staged solver 写 {@code HARD_OBJECTIVE_VERSION}；
     * legacy solver 不写，保持 null（S4 兼容判据只在两侧都非空时启用）。
     */
    private String hardObjectiveVersion;
    private String solverState;
    private String inputDigest;
    private Long durationMs = 0L;
    private Integer candidateCount = 0;
    private Integer constraintCount = 0;
    private TierCountsDTO historicalTierAnchor;
    private TierCountsDTO resolvedTierCounts;

    @Data
    public static class ObjectiveResultDTO {
        private String objectiveId;
        private String objectiveType;
        private Integer requiredMin;
        private Integer requiredMax;
        private Integer actualCount;
        private Boolean satisfied = false;
    }

    @Data
    public static class StageResultDTO {
        private String objectiveId;
        private Long value;
        private String unit;
        /**
         * 该阶段求解耗时；仅用于观测，不参与任何 digest 或回放判定。
         */
        private Long durationMs;
    }

    @Data
    public static class DiagnosticDTO {
        private String reasonCode;
        private String objectiveId;
        private String message;
        private Integer requiredCount;
        private Integer availableCount;
    }
}
