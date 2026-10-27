package com.ytell.zhiyuan.service.biz;

import com.alibaba.fastjson.JSON;
import com.ytell.zhiyuan.model.dto.inner.PendingConfirmationRes;
import com.ytell.zhiyuan.model.dto.planning.CandidatePoolStateDTO;
import com.ytell.zhiyuan.model.dto.planning.ConversationEvidenceDTO;
import com.ytell.zhiyuan.model.dto.planning.ConversationJourneyDTO;
import com.ytell.zhiyuan.model.dto.planning.ConversationTurnSnapshotDTO;
import com.ytell.zhiyuan.model.dto.planning.DataFreshnessStateDTO;
import com.ytell.zhiyuan.model.dto.planning.DraftItemDTO;
import com.ytell.zhiyuan.model.dto.planning.DraftPlanStateDTO;
import com.ytell.zhiyuan.model.dto.planning.DraftUnitDTO;
import com.ytell.zhiyuan.model.dto.planning.ExplicitProfileDTO;
import com.ytell.zhiyuan.model.dto.planning.HardConstraintsDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedItemDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedPlanStateDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedUnitDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningWorkspaceStateRes;
import com.ytell.zhiyuan.model.dto.planning.ProfileStateDTO;
import com.ytell.zhiyuan.model.dto.planning.ReviewStateDTO;
import com.ytell.zhiyuan.model.dto.planning.SoftPreferencesDTO;
import com.ytell.zhiyuan.model.dto.planning.StaleFlagsDTO;
import com.ytell.zhiyuan.model.dto.planning.StudentPlanningSummaryDTO;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.Date;
import java.util.List;
import java.util.Map;

@Service
public class ConversationSnapshotService {

    @Autowired
    private PlanningStateService planningStateService;

    @Autowired
    private PendingConfirmationBizService pendingConfirmationBizService;

    @Autowired
    private EvidenceLedgerService evidenceLedgerService;

    public ConversationTurnSnapshotDTO getTurnSnapshot(Long tenantId, Long chatSessionId) {
        if (tenantId == null || chatSessionId == null) {
            throw new IllegalArgumentException("tenantId and chatSessionId are required");
        }
        PlanningWorkspaceStateRes workspace = planningStateService.getPlanningWorkspaceState(tenantId, chatSessionId);
        if (workspace == null || !chatSessionId.equals(workspace.getSessionId())) {
            throw new IllegalStateException("snapshot_session_mismatch");
        }

        ConversationTurnSnapshotDTO snapshot = new ConversationTurnSnapshotDTO();
        snapshot.setSnapshotVersion(workspace.getVersion() == null ? 0 : workspace.getVersion());
        snapshot.setSessionId(chatSessionId);
        snapshot.setAdmissionMode(canonicalAdmissionMode(workspace));
        snapshot.setPlanningStage(defaultString(workspace.getPhase()));
        fillScoreContext(snapshot.getScoreContext(), workspace.getStudentSummary());
        fillProfileAndConstraints(snapshot, workspace);
        fillMissingFacts(snapshot.getMissingFacts(), workspace.getStudentSummary());
        // 同一次只读记录同时提供给 activeProposal 与 journey.pendingStatus：
        // 避免同一快照一边展示 active 卡、一边声称 applying。
        PendingConfirmationRes pending =
                pendingConfirmationBizService.getActiveOrApplying(tenantId, chatSessionId);
        fillActiveProposal(snapshot, pending);
        fillJourney(snapshot, workspace, pending);
        fillCapabilities(snapshot.getAllowedCapabilities());
        fillEvidence(snapshot.getEvidence(), tenantId, chatSessionId);
        return snapshot;
    }

    private String canonicalAdmissionMode(PlanningWorkspaceStateRes workspace) {
        String raw = workspace.getCandidatePoolState() == null
                ? null : workspace.getCandidatePoolState().getVolunteerModel();
        if (raw == null || raw.trim().isEmpty() || "major".equalsIgnoreCase(raw)) {
            return "major";
        }
        if ("majorGroup".equalsIgnoreCase(raw) || "major_group".equalsIgnoreCase(raw)) {
            return "major_group";
        }
        throw new IllegalStateException("unsupported_admission_mode");
    }

    private void fillScoreContext(Map<String, Object> target, StudentPlanningSummaryDTO summary) {
        if (summary == null) {
            return;
        }
        putIfPresent(target, "province", summary.getProvinceName());
        putIfPresent(target, "examYear", summary.getExamYear());
        putIfPresent(target, "score", summary.getScore());
        putIfPresent(target, "rank", summary.getRank());
        putIfPresent(target, "batch", summary.getBatchName());
        putIfPresent(target, "batchScore", summary.getBatchScore());
        if (summary.getSubjects() != null && !summary.getSubjects().isEmpty()) {
            target.put("subjects", new ArrayList<String>(summary.getSubjects()));
        }
        if (summary.getStrengthSubjects() != null && !summary.getStrengthSubjects().isEmpty()) {
            target.put("strengthSubjects", new ArrayList<String>(summary.getStrengthSubjects()));
        }
    }

    private void fillProfileAndConstraints(ConversationTurnSnapshotDTO snapshot,
                                           PlanningWorkspaceStateRes workspace) {
        ProfileStateDTO profile = workspace.getProfileState();
        if (profile != null && profile.getExplicitProfile() != null) {
            ExplicitProfileDTO explicit = profile.getExplicitProfile();
            putIfPresent(snapshot.getPreferences(), "major", explicit.getPositiveMajors());
            putIfPresent(snapshot.getPreferences(), "school", explicit.getPositiveSchools());
            putIfPresent(snapshot.getPreferences(), "region", explicit.getPositiveRegions());
            putIfPresent(snapshot.getConfirmedConstraints(), "excludedMajors", explicit.getNegativeMajors());
            putIfPresent(snapshot.getConfirmedConstraints(), "excludedSchools", explicit.getNegativeSchools());
            putIfPresent(snapshot.getConfirmedConstraints(), "excludedRegions", explicit.getNegativeRegions());
        }
        StudentPlanningSummaryDTO student = workspace.getStudentSummary();
        if (student != null && student.getSpecialPlan() != null) {
            snapshot.getConfirmedConstraints().put("specialPlan", student.getSpecialPlan());
            snapshot.getConfirmedConstraints().put("specialPlanLabel",
                    student.getSpecialPlan() ? "有专项资格（类别待核验）" : "无专项资格");
        }
        if (workspace.getConstraintState() != null) {
            HardConstraintsDTO hard = workspace.getConstraintState().getHardConstraints();
            SoftPreferencesDTO soft = workspace.getConstraintState().getSoftPreferences();
            if (hard != null) {
                snapshot.getConfirmedConstraints().put("hard", hard);
            }
            if (soft != null) {
                snapshot.getPreferences().put("soft", soft);
            }
            // 已确认的规划目标（同档前置 priorityRules / 覆盖要求 / 冲稳保数量）必须对模型可见
            // （2026-10-07 review §五-21-C）：缺了它们，模型读到的约束与真实生效的目标不一致，
            // 会把"已确认的规则"当成用户从未说过。它属于硬性规划目标，落在 confirmedConstraints。
            if (workspace.getConstraintState().getHardPlanningObjectives() != null) {
                snapshot.getConfirmedConstraints().put("hardPlanningObjectives",
                        workspace.getConstraintState().getHardPlanningObjectives());
            }
        }
        if (workspace.getStaleFlags() != null) {
            snapshot.getConfirmedConstraints().put("staleFlags", workspace.getStaleFlags());
        }
        if (workspace.getCandidatePoolState() != null
                && workspace.getCandidatePoolState().getSummary() != null) {
            snapshot.getPreferences().put("candidateSummary", workspace.getCandidatePoolState().getSummary());
        }
        ReviewStateDTO reviewState = workspace.getReviewState();
        if (reviewState != null && reviewState.getAvailability() != null) {
            snapshot.getPreferences().put("reviewAvailability", reviewState.getAvailability());
        }
        if (!ReviewPolicy.isPaused(reviewState)) {
            // 历史 summary/hardFeasible 只在 active 且确有审查时注入；paused 的空投影
            // 不能被旧消费者误读成“0 风险/已通过”。
            if (reviewState != null && reviewState.getSummary() != null) {
                snapshot.getPreferences().put("reviewSummary", reviewState.getSummary());
            }
            if (reviewState != null) {
                // J5.2：统一评价的几个紧凑信号。只给派生值，不把 15 条 findings 塞进快照。
                if (reviewState.getEvaluationStatus() != null) {
                    snapshot.getPreferences().put("reviewEvaluationStatus",
                            reviewState.getEvaluationStatus());
                }
                if (reviewState.getEvaluationVersion() != null) {
                    snapshot.getPreferences().put("reviewEvaluationVersion",
                            reviewState.getEvaluationVersion());
                }
                if (reviewState.getHardFeasible() != null) {
                    snapshot.getPreferences().put("reviewHardFeasible",
                            reviewState.getHardFeasible());
                }
            }
        }
        if (workspace.getWorkflowStatus() != null) {
            snapshot.getPreferences().put("workflow", workspace.getWorkflowStatus());
        }
    }

    private void fillMissingFacts(List<String> missing, StudentPlanningSummaryDTO summary) {
        if (summary == null || isBlank(summary.getProvinceName())) {
            missing.add("province");
        }
        if (summary == null || summary.getScore() == null) {
            missing.add("score");
        }
        if (summary == null || summary.getRank() == null) {
            missing.add("rank");
        }
    }

    private void fillActiveProposal(ConversationTurnSnapshotDTO snapshot, PendingConfirmationRes pending) {
        if (pending == null || !"active".equals(pending.getStatus())) {
            return;
        }
        Map<String, Object> proposal = new LinkedHashMap<String, Object>();
        // Keep the Gateway contract flat and explicit.  Consumers should not
        // need to inspect the serialized pending payload to find the identity,
        // revision, source version, or whether confirmation is required.
        proposal.put("proposalRef", pending.getPendingId());
        proposal.put("pendingId", pending.getPendingId());
        proposal.put("revision", pending.getRevision());
        proposal.put("kind", pending.getKind());
        proposal.put("actionFamily", pending.getActionFamily());
        proposal.put("status", pending.getStatus());
        Map<String, Object> dataValue = pending.getDataValue() == null
                ? new LinkedHashMap<String, Object>() : pending.getDataValue();
        boolean reviewPaused = ReviewPolicy.paused()
                && RepairProposalTaxonomy.isReviewCheckSource(
                dataValue.get("proposalSource") == null
                        ? null : String.valueOf(dataValue.get("proposalSource")));
        // 旧 review 卡可以取消，但不能确认；user_goal / 成绩等正常卡不受影响。
        proposal.put("requiresConfirmation", "active".equals(pending.getStatus()) && !reviewPaused);
        if (reviewPaused) {
            proposal.put("reviewPaused", true);
            proposal.put("disabledReason", ReviewPolicy.REASON_PAUSED);
        }
        Object sourceVersion = firstPresent(
                dataValue.get("sourceVersion"),
                dataValue.get("sourceBackendVersion"),
                dataValue.get("planningVersion"));
        if (sourceVersion != null) {
            proposal.put("sourceVersion", sourceVersion);
        }
        proposal.put("data", dataValue);
        snapshot.setActiveProposal(proposal);
    }

    // ── J1 旅程块：只读派生，不落库 ──────────────────────────────────────────

    private void fillJourney(ConversationTurnSnapshotDTO snapshot,
                             PlanningWorkspaceStateRes workspace,
                             PendingConfirmationRes pending) {
        ConversationJourneyDTO journey = new ConversationJourneyDTO();
        StudentPlanningSummaryDTO summary = workspace.getStudentSummary();
        List<String> profileMissing = new ArrayList<String>();
        journey.setHasProfile(hasProfile(summary, profileMissing));
        journey.setProfileMissing(profileMissing);

        CandidatePoolStateDTO pool = workspace.getCandidatePoolState();
        int poolTotal = pool == null || pool.getSummary() == null
                ? 0 : valueOrZero(pool.getSummary().getTotal());
        int poolUnitTotal = pool == null || pool.getSummary() == null
                ? 0 : valueOrZero(pool.getSummary().getUnitTotal());
        boolean hasCandidates = poolTotal > 0 || poolUnitTotal > 0;
        boolean groupMode = "major_group".equalsIgnoreCase(snapshot.getAdmissionMode());
        journey.setHasCandidates(hasCandidates);
        journey.setCandidateEntryCount(groupMode ? poolUnitTotal : poolTotal);
        journey.setCandidateSourceVersion(pool == null ? null : pool.getSourceVersion());
        OrderedPlanStateDTO ordered = workspace.getOrderedPlanState();
        DraftPlanStateDTO working = workspace.getWorkingPlanState();
        boolean hasPlan = hasAnyOrderedEntry(ordered) || hasAnyWorkingEntry(working);
        journey.setHasPlan(hasPlan);
        journey.setPlanEntryCount(planEntryCount(ordered, working, groupMode));
        int orderedEntryCount = groupMode
                ? nonNullSize(orderedUnits(ordered))
                : nonNullSize(orderedItems(ordered));
        journey.setOrderedEntryCount(orderedEntryCount);
        journey.setPlanInterpretable(orderedEntryCount > 0);
        journey.setSelectionTargetCount(workspace.getSelectionTargetCount());
        journey.setSelectionCurrentCount(workspace.getSelectionCurrentCount());
        journey.setPlanVersion(snapshot.getSnapshotVersion());
        journey.setPlanContentDigest(planContentDigest(ordered, working));
        journey.setReviewAvailability(workspace.getReviewState() == null
                ? null : workspace.getReviewState().getAvailability());
        journey.setReviewSourceVersion(workspace.getReviewState() == null
                ? null : workspace.getReviewState().getSourceVersion());
        journey.setTierQuotaGoal(hasTierQuotaGoal(workspace));
        journey.setPendingStatus(pendingStatus(pending));

        StaleFlagsDTO flags = workspace.getStaleFlags();
        journey.setStale(isStale(flags));
        journey.setStaleReasonCode(flags == null ? null : blankToNull(flags.getReasonCode()));
        journey.setStaleMessage(truncate(flags == null ? null : blankToNull(flags.getMessage()), 200));
        journey.setReviewStale(!ReviewPolicy.paused()
                && flags != null && Boolean.TRUE.equals(flags.getReview()));
        journey.setPlanAdjustmentStale(flags != null && Boolean.TRUE.equals(flags.getPlanAdjustment()));

        String candidateFreshness = candidateFreshness(
                hasCandidates, flags, workspace.getDataFreshnessState());
        String planFreshness = planFreshness(hasPlan, flags);
        String reviewFreshness = reviewFreshness(workspace.getReviewState(), flags);
        journey.setCandidateFreshness(candidateFreshness);
        journey.setPlanFreshness(planFreshness);
        journey.setReviewFreshness(reviewFreshness);
        journey.setRefreshRequirement(refreshRequirement(
                candidateFreshness, planFreshness, reviewFreshness));

        snapshot.setJourney(journey);
    }

    private boolean hasProfile(StudentPlanningSummaryDTO summary, List<String> missing) {
        boolean province = summary != null && !isBlank(summary.getProvinceName());
        boolean examYear = summary != null && summary.getExamYear() != null;
        boolean batch = summary != null && !isBlank(summary.getBatchName());
        boolean subjectType = summary != null && !isBlank(summary.getSubjectType());
        boolean scoreOrRank = summary != null
                && (summary.getScore() != null || summary.getRank() != null);
        if (!province) {
            missing.add("province");
        }
        if (!examYear) {
            missing.add("examYear");
        }
        if (!batch) {
            missing.add("batch");
        }
        if (!subjectType) {
            missing.add("subjectType");
        }
        if (!scoreOrRank) {
            missing.add("scoreOrRank");
        }
        return province && examYear && batch && subjectType && scoreOrRank;
    }

    private boolean hasAnyOrderedEntry(OrderedPlanStateDTO ordered) {
        return ordered != null
                && (!defaultList(ordered.getItems()).isEmpty()
                || !defaultList(ordered.getUnits()).isEmpty());
    }

    private boolean hasAnyWorkingEntry(DraftPlanStateDTO working) {
        return working != null
                && (!defaultList(working.getItems()).isEmpty()
                || !defaultList(working.getUnits()).isEmpty());
    }

    /**
     * 展示用条目数：先取在用的方案（ordered 任一非空 → ordered，否则 working），
     * 再按 mode 优先对应形状、另一形状兜底。
     */
    private int planEntryCount(OrderedPlanStateDTO ordered,
                               DraftPlanStateDTO working,
                               boolean groupMode) {
        List<OrderedItemDTO> orderedItems = defaultList(orderedItems(ordered));
        List<OrderedUnitDTO> orderedUnits = defaultList(orderedUnits(ordered));
        List<DraftItemDTO> workingItems = defaultList(workingItems(working));
        List<DraftUnitDTO> workingUnits = defaultList(workingUnits(working));
        boolean useOrdered = hasAnyOrderedEntry(ordered);
        if (groupMode) {
            if (useOrdered) {
                return !orderedUnits.isEmpty() ? nonNullSize(orderedUnits) : nonNullSize(orderedItems);
            }
            return !workingUnits.isEmpty() ? nonNullSize(workingUnits) : nonNullSize(workingItems);
        }
        if (useOrdered) {
            return !orderedItems.isEmpty() ? nonNullSize(orderedItems) : nonNullSize(orderedUnits);
        }
        return !workingItems.isEmpty() ? nonNullSize(workingItems) : nonNullSize(workingUnits);
    }

    /**
     * 内容指纹：ordered 非空时与 EvaluationContextBuilder 同算法/同输入；
     * working 回退加 "working|" 前缀，避免与评价 digest 混用。
     */
    private String planContentDigest(OrderedPlanStateDTO ordered, DraftPlanStateDTO working) {
        if (hasAnyOrderedEntry(ordered)) {
            return EvaluationVersion.sha256(JSON.toJSONString(ordered));
        }
        if (hasAnyWorkingEntry(working)) {
            return EvaluationVersion.sha256("working|" + JSON.toJSONString(working));
        }
        return null;
    }

    private String candidateFreshness(boolean hasCandidates,
                                      StaleFlagsDTO flags,
                                      DataFreshnessStateDTO freshness) {
        if (!hasCandidates) {
            return "absent";
        }
        boolean stale = flags != null
                && (Boolean.TRUE.equals(flags.getCandidatePool())
                || Boolean.TRUE.equals(flags.getRecommendationOverlay())
                || Boolean.TRUE.equals(flags.getInitialRecommendation()));
        if (!stale && freshness != null
                && Boolean.TRUE.equals(freshness.getRequiresCandidateRefresh())) {
            stale = true;
        }
        return stale ? "stale" : "fresh";
    }

    private String planFreshness(boolean hasPlan, StaleFlagsDTO flags) {
        if (!hasPlan) {
            return "absent";
        }
        // planAdjustment 每次写方案都会置位且 runReview 不清；它不能代表“方案内容
        // 基于旧数据”。只看 orderedPlan；planAdjustment 另给独立信号。
        boolean stale = flags != null && Boolean.TRUE.equals(flags.getOrderedPlan());
        return stale ? "stale" : "fresh";
    }

    private String reviewFreshness(ReviewStateDTO review, StaleFlagsDTO flags) {
        if (ReviewPolicy.isPaused(review)) {
            return "paused";
        }
        if (review == null || review.getSourceVersion() == null
                || "idle".equalsIgnoreCase(String.valueOf(review.getStatus()))) {
            return "absent";
        }
        boolean stale = flags != null && Boolean.TRUE.equals(flags.getReview());
        return stale ? "stale" : "fresh";
    }

    private String refreshRequirement(String candidateFreshness,
                                      String planFreshness,
                                      String reviewFreshness) {
        if (!"fresh".equals(candidateFreshness)) {
            return "candidates";
        }
        if (!"fresh".equals(planFreshness)) {
            return "plan";
        }
        // paused 不要求用户/模型“重新审查”；否则会形成无法完成的循环建议。
        if (!"fresh".equals(reviewFreshness) && !"paused".equals(reviewFreshness)) {
            return "review";
        }
        return "none";
    }

    private boolean hasTierQuotaGoal(PlanningWorkspaceStateRes workspace) {
        return workspace.getConstraintState() != null
                && workspace.getConstraintState().getHardPlanningObjectives() != null
                && workspace.getConstraintState().getHardPlanningObjectives().getTierQuotaGoal() != null;
    }

    private boolean isStale(StaleFlagsDTO flags) {
        if (flags == null) {
            return false;
        }
        return Boolean.TRUE.equals(flags.getCandidatePool())
                || Boolean.TRUE.equals(flags.getRecommendationOverlay())
                || Boolean.TRUE.equals(flags.getInitialRecommendation())
                || Boolean.TRUE.equals(flags.getOrderedPlan())
                || Boolean.TRUE.equals(flags.getPlanAdjustment())
                || Boolean.TRUE.equals(flags.getReview())
                || !isBlank(flags.getReasonCode())
                || !isBlank(flags.getMessage());
    }

    private String pendingStatus(PendingConfirmationRes pending) {
        if (pending == null) {
            return null;
        }
        String status = pending.getStatus();
        return "active".equals(status) || "applying".equals(status) ? status : null;
    }

    private List<OrderedItemDTO> orderedItems(OrderedPlanStateDTO ordered) {
        return ordered == null ? null : ordered.getItems();
    }

    private List<OrderedUnitDTO> orderedUnits(OrderedPlanStateDTO ordered) {
        return ordered == null ? null : ordered.getUnits();
    }

    private List<DraftItemDTO> workingItems(DraftPlanStateDTO working) {
        return working == null ? null : working.getItems();
    }

    private List<DraftUnitDTO> workingUnits(DraftPlanStateDTO working) {
        return working == null ? null : working.getUnits();
    }

    private <T> List<T> defaultList(List<T> values) {
        return values == null ? new ArrayList<T>() : values;
    }

    private int nonNullSize(List<?> values) {
        int count = 0;
        for (Object value : defaultList(values)) {
            if (value != null) {
                count++;
            }
        }
        return count;
    }

    private int valueOrZero(Integer value) {
        return value == null ? 0 : value;
    }

    private String blankToNull(String value) {
        return isBlank(value) ? null : value;
    }

    private String truncate(String value, int maxLength) {
        if (value == null || value.length() <= maxLength) {
            return value;
        }
        return value.substring(0, maxLength);
    }

    private Object firstPresent(Object... values) {
        for (Object value : values) {
            if (value != null) {
                return value;
            }
        }
        return null;
    }

    private void fillCapabilities(List<String> capabilities) {
        capabilities.add("catalog_read");
        capabilities.add("admission_read");
        // review_read 没有消费者（仅签发、无工具挂载），已删除；需要读评价时
        // 另加有真实消费者的能力/工具，见 2026-10-18 语义权威审查。
    }

    /**
     * 把当前会话仍然有效的权威证据填进快照。
     *
     * <p>空实现曾经"看起来是对的"——注释说工作区 DTO 里没有证据集合，所以不合成。
     * 但结果是快照**永远**不带证据，而 Agent 侧又靠证据判断"这条事实能不能用"，
     * 于是要么全是自铸、要么全是查不到。证据不在工作区里，在**台账**里。
     */
    private void fillEvidence(List<ConversationEvidenceDTO> evidence, Long tenantId, Long chatSessionId) {
        evidence.addAll(evidenceLedgerService.listSessionEvidence(tenantId, chatSessionId, new Date()));
    }

    private void putIfPresent(Map<String, Object> target, String key, Object value) {
        if (value instanceof List && ((List<?>) value).isEmpty()) {
            return;
        }
        if (value != null && !(value instanceof String && isBlank((String) value))) {
            target.put(key, value);
        }
    }

    private String defaultString(String value) {
        return value == null ? "" : value;
    }

    private boolean isBlank(String value) {
        return value == null || value.trim().isEmpty();
    }
}
