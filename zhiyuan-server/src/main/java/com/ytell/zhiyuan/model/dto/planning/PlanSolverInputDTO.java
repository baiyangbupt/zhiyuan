package com.ytell.zhiyuan.model.dto.planning;

import com.google.common.collect.Lists;
import lombok.Data;

import java.util.List;

@Data
public class PlanSolverInputDTO {
    private CanonicalPlanningObjectiveSetDTO objectiveSet;
    private List<CandidateDTO> candidates = Lists.newArrayList();

    @Data
    public static class CandidateDTO {
        private String entityId;
        private List<String> volunteerIds = Lists.newArrayList();
        private Integer stableOrder;
        private Boolean current = false;
        private Boolean locked = false;
        private Boolean pinned = false;
        private Boolean eligible = true;
        private String tier;
        private List<String> coverageObjectiveIds = Lists.newArrayList();
        private Boolean priorityMatched = false;
    }
}
