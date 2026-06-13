package com.ytell.zhiyuan.service.biz;

import com.google.common.base.Strings;
import com.google.common.collect.Lists;
import com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO;
import com.ytell.zhiyuan.model.dto.planning.CompensationActionDTO;
import com.ytell.zhiyuan.model.dto.planning.DraftItemDTO;
import com.ytell.zhiyuan.model.dto.planning.DraftPlanStateDTO;
import com.ytell.zhiyuan.model.dto.planning.FixProposalActionDTO;
import com.ytell.zhiyuan.model.dto.planning.FixProposalDTO;
import com.ytell.zhiyuan.model.dto.planning.OperationLogDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;

import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;
import java.util.stream.Collectors;

final class RepairApplyMutationBuilder {

    private RepairApplyMutationBuilder() {
    }

    static MutationResult applyFixProposalCompensationActions(PlanningStateDTO state,
                                                              List<CandidateItemDTO> candidates,
                                                              FixProposalDTO proposal) {
        List<CompensationActionDTO> actions = defaultFixProposalActions(proposal == null ? null : proposal.getActions()).stream()
                .map(RepairApplyMutationBuilder::toCompensationAction)
                .collect(Collectors.toList());
        return applyCompensationActions(state, candidates, actions);
    }

    static MutationResult applyRemoveRiskItems(PlanningStateDTO state,
                                               List<CandidateItemDTO> candidates,
                                               FixProposalDTO proposal) {
        MutationResult result = new MutationResult();
        DraftPlanStateDTO draft = state == null ? null : state.getWorkingPlanState();
        if (draft == null || proposal == null) {
            return result;
        }
        Set<String> removeIds = new LinkedHashSet<String>(defaultList(proposal.getAffectedVolunteerIds()));
        for (FixProposalActionDTO action : defaultFixProposalActions(proposal.getActions())) {
            if (RepairProposalTaxonomy.ActionType.REMOVE_VOLUNTEERS.equals(
                    RepairProposalTaxonomy.normalizeActionType(action.getActionType()))) {
                removeIds.addAll(defaultList(action.getVolunteerIds()));
            }
        }
        if (removeIds.isEmpty()) {
            return result;
        }

        List<String> removedVolunteerIds = defaultDraftItems(draft.getItems()).stream()
                .map(DraftItemDTO::getVolunteerId)
                .filter(removeIds::contains)
                .filter(value -> !Strings.isNullOrEmpty(value))
                .collect(Collectors.toList());
        draft.setItems(defaultDraftItems(draft.getItems()).stream()
                .filter(item -> !removeIds.contains(item.getVolunteerId()))
                .collect(Collectors.toList()));
        result.getRemovedVolunteerIds().addAll(removedVolunteerIds);

        List<CompensationActionDTO> addActions = defaultFixProposalActions(proposal.getActions()).stream()
                .filter(action -> RepairProposalTaxonomy.ActionType.FILL_TOTAL_COUNT.equals(
                        RepairProposalTaxonomy.normalizeActionType(action.getActionType())))
                .map(RepairApplyMutationBuilder::toCompensationAction)
                .collect(Collectors.toList());
        MutationResult compensationResult = applyCompensationActions(state, candidates, addActions);
        result.merge(compensationResult);
        syncWorkingPlan(state, candidates);
        if (!removedVolunteerIds.isEmpty()) {
            OperationLogDTO logItem = buildOperationLog(
                    "fix_remove_risk_items",
                    "remove_risk_items:" + proposal.getTitle(),
                    removedVolunteerIds);
            appendOperationLog(state, logItem);
            result.getOperationLogs().add(logItem);
        }
        return result;
    }

    static MutationResult applyMajorGroupInnerSafety(PlanningStateDTO state,
                                                     List<CandidateItemDTO> candidates,
                                                     FixProposalDTO proposal) {
        MutationResult result = new MutationResult();
        DraftPlanStateDTO draft = state == null ? null : state.getWorkingPlanState();
        if (draft == null || proposal == null) {
            return result;
        }
        Set<String> removeIds = new LinkedHashSet<String>();
        Set<String> addIds = new LinkedHashSet<String>();
        for (FixProposalActionDTO action : defaultFixProposalActions(proposal.getActions())) {
            if (!RepairProposalTaxonomy.ActionType.ADJUST_MAJOR_GROUP_INNER_SAFETY.equals(
                    RepairProposalTaxonomy.normalizeActionType(action.getActionType()))) {
                continue;
            }
            removeIds.addAll(defaultList(action.getRemoveVolunteerIds()).stream()
                    .filter(value -> !Strings.isNullOrEmpty(value))
                    .collect(Collectors.toList()));
            List<String> candidateIds = !defaultList(action.getCandidateVolunteerIds()).isEmpty()
                    ? action.getCandidateVolunteerIds()
                    : action.getVolunteerIds();
            addIds.addAll(defaultList(candidateIds).stream()
                    .filter(value -> !Strings.isNullOrEmpty(value))
                    .collect(Collectors.toList()));
        }
        if (!removeIds.isEmpty()) {
            List<String> removedVolunteerIds = defaultDraftItems(draft.getItems()).stream()
                    .map(DraftItemDTO::getVolunteerId)
                    .filter(removeIds::contains)
                    .filter(value -> !Strings.isNullOrEmpty(value))
                    .collect(Collectors.toList());
            draft.setItems(defaultDraftItems(draft.getItems()).stream()
                    .filter(item -> !removeIds.contains(item.getVolunteerId()))
                    .collect(Collectors.toList()));
            result.getRemovedVolunteerIds().addAll(removedVolunteerIds);
        }
        for (String volunteerId : addIds) {
            CandidateItemDTO candidate = WorkingPlanMutationSupport.findCandidate(candidates, volunteerId);
            if (!WorkingPlanMutationSupport.addWorkingPlanItemIfAllowed(draft, candidate, "fix_proposal")) {
                continue;
            }
            result.getAddedVolunteerIds().add(candidate.getVolunteerId());
        }
        syncWorkingPlan(state, candidates);
        if (!addIds.isEmpty() || !removeIds.isEmpty()) {
            OperationLogDTO logItem = buildOperationLog(
                    "fix_major_group_inner_safety",
                    "adjust_major_group_inner_safety:" + proposal.getTitle(),
                    Lists.newArrayList(addIds));
            appendOperationLog(state, logItem);
            result.getOperationLogs().add(logItem);
        }
        return result;
    }

    static MutationResult applyReplaceVolunteers(PlanningStateDTO state,
                                                 List<CandidateItemDTO> candidates,
                                                 FixProposalDTO proposal) {
        MutationResult result = new MutationResult();
        DraftPlanStateDTO draft = state == null ? null : state.getWorkingPlanState();
        if (draft == null || proposal == null) {
            return result;
        }
        Set<String> removeIds = new LinkedHashSet<String>();
        Set<String> addIds = new LinkedHashSet<String>();
        for (FixProposalActionDTO action : defaultFixProposalActions(proposal.getActions())) {
            if (!RepairProposalTaxonomy.ActionType.REPLACE_VOLUNTEERS.equals(
                    RepairProposalTaxonomy.normalizeActionType(action.getActionType()))) {
                continue;
            }
            if (hasIncompleteReplacementPair(action)) {
                result.block("替换动作存在不完整配对");
                return result;
            }
            collectReplacementIds(action, removeIds, addIds);
        }
        if (removeIds.isEmpty() && addIds.isEmpty()) {
            return result;
        }
        if (removeIds.isEmpty() || addIds.isEmpty() || removeIds.size() != addIds.size()) {
            result.block("替换动作缺少完整的移除/补入配对");
            return result;
        }

        Set<String> currentVolunteerIds = defaultDraftItems(draft.getItems()).stream()
                .map(DraftItemDTO::getVolunteerId)
                .filter(value -> !Strings.isNullOrEmpty(value))
                .collect(Collectors.toCollection(LinkedHashSet::new));
        List<String> missingRemoveIds = removeIds.stream()
                .filter(value -> !currentVolunteerIds.contains(value))
                .collect(Collectors.toList());
        if (!missingRemoveIds.isEmpty()) {
            result.block("待替换志愿不在当前方案中：" + String.join(",", missingRemoveIds));
            return result;
        }

        DraftPlanStateDTO previewDraft = new DraftPlanStateDTO();
        previewDraft.setItems(defaultDraftItems(draft.getItems()).stream()
                .filter(item -> !removeIds.contains(item.getVolunteerId()))
                .collect(Collectors.toList()));
        previewDraft.setBannedVolunteerIds(defaultList(draft.getBannedVolunteerIds()));
        List<CandidateItemDTO> resolvedAdditions = Lists.newArrayList();
        for (String volunteerId : addIds) {
            CandidateItemDTO candidate = WorkingPlanMutationSupport.findCandidate(candidates, volunteerId);
            if (candidate == null) {
                result.block("替换候选缺少候选明细：" + volunteerId);
                return result;
            }
            if (!WorkingPlanMutationSupport.addWorkingPlanItemIfAllowed(previewDraft, candidate, "fix_proposal")) {
                result.block("替换候选已在方案中或已被禁用：" + volunteerId);
                return result;
            }
            resolvedAdditions.add(candidate);
        }

        List<String> removedVolunteerIds = defaultDraftItems(draft.getItems()).stream()
                .map(DraftItemDTO::getVolunteerId)
                .filter(removeIds::contains)
                .filter(value -> !Strings.isNullOrEmpty(value))
                .collect(Collectors.toList());
        draft.setItems(previewDraft.getItems());
        result.getRemovedVolunteerIds().addAll(removedVolunteerIds);
        result.getAddedVolunteerIds().addAll(resolvedAdditions.stream()
                .map(CandidateItemDTO::getVolunteerId)
                .collect(Collectors.toList()));
        syncWorkingPlan(state, candidates);

        if (!removedVolunteerIds.isEmpty() || !resolvedAdditions.isEmpty()) {
            List<String> logVolunteerIds = Lists.newArrayList();
            logVolunteerIds.addAll(removedVolunteerIds);
            logVolunteerIds.addAll(result.getAddedVolunteerIds());
            OperationLogDTO logItem = buildOperationLog(
                    "fix_replace_volunteers",
                    "replace_volunteers:" + proposal.getTitle(),
                    logVolunteerIds);
            appendOperationLog(state, logItem);
            result.getOperationLogs().add(logItem);
        }
        return result;
    }

    static MutationResult applyCompensationActions(PlanningStateDTO state,
                                                   List<CandidateItemDTO> candidates,
                                                   List<CompensationActionDTO> actions) {
        MutationResult result = new MutationResult();
        DraftPlanStateDTO draft = state == null ? null : state.getWorkingPlanState();
        if (draft == null) {
            return result;
        }
        for (CompensationActionDTO action : defaultCompensationActions(actions)) {
            boolean applied = false;
            for (String volunteerId : defaultList(action.getVolunteerIds())) {
                CandidateItemDTO candidate = WorkingPlanMutationSupport.findCandidate(candidates, volunteerId);
                if (!WorkingPlanMutationSupport.addWorkingPlanItemIfAllowed(draft, candidate, "compensation")) {
                    continue;
                }
                result.getAddedVolunteerIds().add(candidate.getVolunteerId());
                applied = true;
            }
            if (applied) {
                result.getAppliedCompensationActions().add(action);
            }
        }
        syncWorkingPlan(state, candidates);
        appendCompensationOperationLogs(state, result.getAppliedCompensationActions(), result);
        return result;
    }

    private static boolean hasIncompleteReplacementPair(FixProposalActionDTO action) {
        return defaultList(action == null ? null : action.getReplacementPairs()).stream()
                .anyMatch(pair -> pair != null
                        && (Strings.isNullOrEmpty(pair.getFromVolunteerId())
                        || Strings.isNullOrEmpty(pair.getToVolunteerId())));
    }

    private static void collectReplacementIds(FixProposalActionDTO action,
                                              Set<String> removeIds,
                                              Set<String> addIds) {
        removeIds.addAll(defaultList(action.getRemoveVolunteerIds()).stream()
                .filter(value -> !Strings.isNullOrEmpty(value))
                .collect(Collectors.toList()));
        addIds.addAll(defaultList(action.getCandidateVolunteerIds()).stream()
                .filter(value -> !Strings.isNullOrEmpty(value))
                .collect(Collectors.toList()));
        defaultList(action.getReplacementPairs()).forEach(pair -> {
            if (pair == null) {
                return;
            }
            if (!Strings.isNullOrEmpty(pair.getFromVolunteerId())) {
                removeIds.add(pair.getFromVolunteerId());
            }
            if (!Strings.isNullOrEmpty(pair.getToVolunteerId())) {
                addIds.add(pair.getToVolunteerId());
            }
        });
    }

    private static void syncWorkingPlan(PlanningStateDTO state, List<CandidateItemDTO> candidates) {
        if (state == null || state.getWorkingPlanState() == null) {
            return;
        }
        WorkingPlanMutationSupport.syncWorkingPlanUnitsWithItems(
                state.getWorkingPlanState(), candidates, state.getCandidatePoolState());
        WorkingPlanMutationSupport.recalculateWorkingPlanSummary(state.getWorkingPlanState(), state.getCandidatePoolState());
    }

    private static CompensationActionDTO toCompensationAction(FixProposalActionDTO action) {
        CompensationActionDTO target = new CompensationActionDTO();
        if (action == null) {
            return target;
        }
        target.setType(action.getActionType());
        target.setLevel(action.getLevel());
        target.setSourceCheckCode(action.getSourceCheckCode());
        target.setSummary(action.getSummary());
        target.setDetail(action.getDetail());
        target.setUnitIds(defaultList(action.getUnitIds()));
        target.setVolunteerIds(defaultList(action.getVolunteerIds()));
        return target;
    }

    private static void appendCompensationOperationLogs(PlanningStateDTO state,
                                                        List<CompensationActionDTO> actions,
                                                        MutationResult result) {
        for (CompensationActionDTO action : actions) {
            OperationLogDTO logItem = buildOperationLog(
                    "compensation_apply",
                    action.getType() + ":" + action.getSummary(),
                    new ArrayList<String>(defaultList(action.getVolunteerIds())));
            appendOperationLog(state, logItem);
            result.getOperationLogs().add(logItem);
        }
    }

    private static OperationLogDTO buildOperationLog(String type, String detail, List<String> volunteerIds) {
        OperationLogDTO logItem = new OperationLogDTO();
        logItem.setType(type);
        logItem.setOperator("system");
        logItem.setCreatedAt(OffsetDateTime.now().toString());
        logItem.setDetail(detail);
        logItem.setVolunteerIds(defaultList(volunteerIds));
        return logItem;
    }

    private static void appendOperationLog(PlanningStateDTO state, OperationLogDTO logItem) {
        if (state == null || logItem == null) {
            return;
        }
        if (state.getOperationLogs() == null) {
            state.setOperationLogs(Lists.newArrayList());
        }
        state.getOperationLogs().add(logItem);
    }

    private static List<FixProposalActionDTO> defaultFixProposalActions(List<FixProposalActionDTO> values) {
        return values == null ? Lists.newArrayList() : values;
    }

    private static List<CompensationActionDTO> defaultCompensationActions(List<CompensationActionDTO> values) {
        return values == null ? Lists.newArrayList() : values;
    }

    private static List<DraftItemDTO> defaultDraftItems(List<DraftItemDTO> values) {
        return values == null ? Lists.newArrayList() : values;
    }

    private static <T> List<T> defaultList(List<T> values) {
        return values == null ? Lists.newArrayList() : values;
    }

    static final class MutationResult {
        private final List<CompensationActionDTO> appliedCompensationActions = Lists.newArrayList();
        private final List<String> removedVolunteerIds = Lists.newArrayList();
        private final List<String> addedVolunteerIds = Lists.newArrayList();
        private final List<OperationLogDTO> operationLogs = Lists.newArrayList();
        private String status = "applied";
        private String blockingReason;

        List<CompensationActionDTO> getAppliedCompensationActions() {
            return appliedCompensationActions;
        }

        List<String> getRemovedVolunteerIds() {
            return removedVolunteerIds;
        }

        List<String> getAddedVolunteerIds() {
            return addedVolunteerIds;
        }

        List<OperationLogDTO> getOperationLogs() {
            return operationLogs;
        }

        String getStatus() {
            return status;
        }

        String getBlockingReason() {
            return blockingReason;
        }

        private void block(String reason) {
            status = RepairProposalTaxonomy.Status.BLOCKED;
            blockingReason = reason;
        }

        private void merge(MutationResult other) {
            if (other == null) {
                return;
            }
            appliedCompensationActions.addAll(other.getAppliedCompensationActions());
            removedVolunteerIds.addAll(other.getRemovedVolunteerIds());
            addedVolunteerIds.addAll(other.getAddedVolunteerIds());
            operationLogs.addAll(other.getOperationLogs());
            if (RepairProposalTaxonomy.isBlockedStatus(other.getStatus())) {
                block(other.getBlockingReason());
            }
        }
    }
}
