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
    // 点名加入（add_units）的逐条明细与数量口径：由 Java 从候选行生成。
    private List<FixProposalAffectedItemDTO> affectedItems = Lists.newArrayList();
    private Integer addedCount;
    private Integer addedUnitCount;
    private Integer removedCount;
    private Integer targetCountBefore;
    private Integer targetCountAfter;
    /** add_units / remove_units 需要持久化的新目标数；无已确认目标时为空（自然变化）。 */
    private Integer targetCountOverride;
    /** move_units 的移动目标与前后位置（1-based）；其他策略为空。 */
    private String moveTargetVolunteerId;
    private String moveTargetUnitId;
    private Integer moveFromPosition;
    private Integer moveToPosition;
    private FixProposalDryRunResultDTO dryRunResult = new FixProposalDryRunResultDTO();
    private String canonicalObjectiveDigest;
    private String solverVersion;
    private String solverInputDigest;
    private PlanSolverResultDTO solverResult;
    private TierQuotaChangeDTO tierQuotaChange;
}
