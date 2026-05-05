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
    private PlanGenerationStateDTO planGenerationState = new PlanGenerationStateDTO();
    private CandidatePoolStateDTO candidatePoolState = new CandidatePoolStateDTO();
    private CandidateViewStateDTO candidateViewState;
    private DraftPlanStateDTO draftPlanState = new DraftPlanStateDTO();
    private OrderedPlanStateDTO orderedPlanState = new OrderedPlanStateDTO();
    private ReviewStateDTO reviewState = new ReviewStateDTO();
    private List<CompensationActionDTO> pendingActions = Lists.newArrayList();
    private List<OperationLogDTO> operationLogs = Lists.newArrayList();
}
