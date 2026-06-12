package com.ytell.zhiyuan.model.dto.planning;

import com.google.common.collect.Lists;
import lombok.Data;

import java.util.List;

@Data
public class PlanningWorkspaceStateRes {
    private Long sessionId;
    private Integer version;
    private String phase;
    private StaleFlagsDTO staleFlags = new StaleFlagsDTO();
    private ConstraintStateDTO constraintState = new ConstraintStateDTO();
    private DataFreshnessStateDTO dataFreshnessState = new DataFreshnessStateDTO();
    private PlanGenerationStateDTO planGenerationState = new PlanGenerationStateDTO();
    private InitialRecommendationStateDTO initialRecommendationState = new InitialRecommendationStateDTO();
    private CandidatePoolStateDTO candidatePoolState = new CandidatePoolStateDTO();
    private CandidateViewStateDTO candidateViewState;
    private PlanningWorkflowStatusDTO workflowStatus = new PlanningWorkflowStatusDTO();
    private DraftPlanStateDTO workingPlanState = new DraftPlanStateDTO();
    private OrderedPlanStateDTO orderedPlanState = new OrderedPlanStateDTO();
    private ReviewStateDTO reviewState = new ReviewStateDTO();
    private List<CompensationActionDTO> pendingActions = Lists.newArrayList();
    private List<OperationLogDTO> operationLogs = Lists.newArrayList();

    /**
     * Backward-compatible alias for older agent/frontend callers.
     * New code should use workingPlanState.
     */
    @Deprecated
    public DraftPlanStateDTO getDraftPlanState() {
        return workingPlanState;
    }

    /**
     * Backward-compatible alias for older agent/frontend callers.
     * New code should use workingPlanState.
     */
    @Deprecated
    public void setDraftPlanState(DraftPlanStateDTO draftPlanState) {
        if (draftPlanState != null || this.workingPlanState == null) {
            this.workingPlanState = draftPlanState;
        }
    }
}
