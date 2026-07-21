package com.ytell.zhiyuan.model.dto.planning;

import com.google.common.collect.Lists;
import lombok.Data;

import java.util.List;

@Data
public class FixProposalDTO {
    private String proposalId;
    private String proposalSource = "review_check";
    private Integer sourceVersion;
    private Integer sourceReviewVersion;
    private Integer sourceVersionGuard;
    private String status = "ready";
    private String strategy;
    private String title;
    private String summary;
    private String impact;
    private String blockingReason;
    private List<String> blockingReasonCodes = Lists.newArrayList();
    private List<CandidateShortageDTO> candidateShortages = Lists.newArrayList();
    private Boolean requiresConfirmation = true;
    private List<String> sourceCheckCodes = Lists.newArrayList();
    private List<String> affectedUnitIds = Lists.newArrayList();
    private List<String> affectedVolunteerIds = Lists.newArrayList();
    private List<FixProposalActionDTO> actions = Lists.newArrayList();
    private FixProposalDryRunResultDTO dryRunResult = new FixProposalDryRunResultDTO();
    private String canonicalObjectiveDigest;
    private String solverVersion;
    private String solverInputDigest;
    private PlanSolverResultDTO solverResult;
    private TierQuotaChangeDTO tierQuotaChange;
}
