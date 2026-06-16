package com.ytell.zhiyuan.model.dto.planning;

import com.google.common.collect.Lists;
import lombok.Data;

import java.util.List;

@Data
public class PlanningStateDTO {
    private Long sessionId;
    private Integer version = 0;
    private String phase = "profile_ready";
    private StaleFlagsDTO staleFlags = new StaleFlagsDTO();
    private ProfileStateDTO profileState = new ProfileStateDTO();
    private ConstraintStateDTO constraintState = new ConstraintStateDTO();
    private DataFreshnessStateDTO dataFreshnessState = new DataFreshnessStateDTO();
    private CandidatePoolStateDTO candidatePoolState = new CandidatePoolStateDTO();
    private CandidateViewStateDTO candidateViewState;
    private InitialRecommendationStateDTO initialRecommendationState = new InitialRecommendationStateDTO();
    private RecommendationOverlayStateDTO recommendationOverlayState = new RecommendationOverlayStateDTO();
    private PlanGenerationStateDTO planGenerationState = new PlanGenerationStateDTO();
    private DraftPlanStateDTO workingPlanState = new DraftPlanStateDTO();
    private OrderedPlanStateDTO orderedPlanState = new OrderedPlanStateDTO();
    private PlanAdjustmentStateDTO planAdjustmentState = new PlanAdjustmentStateDTO();
    private ReviewStateDTO reviewState = new ReviewStateDTO();
    private List<OperationLogDTO> operationLogs = Lists.newArrayList();

    /**
     * Backward-compatible alias for persisted 3.0.x planning state and older agent/frontend callers.
     * New code should use workingPlanState.
     */
    @Deprecated
    public DraftPlanStateDTO getDraftPlanState() {
        return workingPlanState;
    }

    /**
     * Backward-compatible alias for persisted 3.0.x planning state and older agent/frontend callers.
     * New code should use workingPlanState.
     */
    @Deprecated
    public void setDraftPlanState(DraftPlanStateDTO draftPlanState) {
        if (draftPlanState != null || this.workingPlanState == null) {
            this.workingPlanState = draftPlanState;
        }
    }
}
