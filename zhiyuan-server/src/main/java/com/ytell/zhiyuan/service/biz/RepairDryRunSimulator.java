package com.ytell.zhiyuan.service.biz;

import com.google.common.base.Strings;
import com.google.common.collect.Lists;
import com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO;
import com.ytell.zhiyuan.model.dto.planning.CandidatePoolStateDTO;
import com.ytell.zhiyuan.model.dto.planning.ConstraintStateDTO;
import com.ytell.zhiyuan.model.dto.planning.DraftItemDTO;
import com.ytell.zhiyuan.model.dto.planning.DraftUnitDTO;
import com.ytell.zhiyuan.model.dto.planning.FixProposalActionDTO;
import com.ytell.zhiyuan.model.dto.planning.FixProposalDTO;
import com.ytell.zhiyuan.model.dto.planning.FixProposalDryRunResultDTO;
import com.ytell.zhiyuan.model.dto.planning.HardConstraintsDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedItemDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedUnitDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import com.ytell.zhiyuan.model.dto.planning.ReviewCheckDTO;
import com.ytell.zhiyuan.model.dto.planning.ReviewRuleMetadataDTO;
import com.ytell.zhiyuan.model.dto.planning.ReplacementPairDTO;
import com.ytell.zhiyuan.model.dto.planning.SoftPreferencesDTO;

import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import java.util.function.Function;
import java.util.stream.Collectors;

final class RepairDryRunSimulator {

    private static final int MAX_DRY_RUN_WARNING_COUNT = 8;
    private static final double PROBABILITY_GAP_THRESHOLD = 8D;

    private RepairDryRunSimulator() {
    }

    static void populate(PlanningStateDTO state, FixProposalDTO proposal, ReviewCheckDTO check) {
        if (proposal == null) {
            return;
        }
        if (proposal.getDryRunResult() == null) {
            proposal.setDryRunResult(new FixProposalDryRunResultDTO());
        }
        FixProposalDryRunResultDTO dryRun = proposal.getDryRunResult();
        dryRun.setAffectedUnitCount(defaultList(check == null ? null : check.getAffectedUnitIds()).size());
        dryRun.setAffectedVolunteerCount(defaultList(check == null ? null : check.getAffectedVolunteerIds()).size());

        ActionCount count = countActions(proposal.getActions());
        dryRun.setAddUnitCount(count.addUnitCount);
        dryRun.setAddVolunteerCount(count.addVolunteerCount);
        dryRun.setRemoveUnitCount(count.removeUnitCount);
        dryRun.setRemoveVolunteerCount(count.removeVolunteerCount);
        populateSnapshot(state, proposal);
        populateStatus(proposal, dryRun);
        populateObjectiveValidation(state, proposal, check, dryRun);
        populateWarnings(state, proposal, dryRun);
    }

    private static ActionCount countActions(List<FixProposalActionDTO> actions) {
        ActionCount count = new ActionCount();
        for (FixProposalActionDTO action : defaultList(actions)) {
            String actionType = RepairProposalTaxonomy.normalizeActionType(action.getActionType());
            if (RepairProposalTaxonomy.ActionType.REMOVE_VOLUNTEERS.equals(actionType)) {
                count.removeUnitCount += defaultList(action.getUnitIds()).size();
                count.removeVolunteerCount += defaultList(action.getVolunteerIds()).size();
            } else if (RepairProposalTaxonomy.ActionType.REPLACE_VOLUNTEERS.equals(actionType)) {
                Set<String> removeVolunteerIds = new LinkedHashSet<String>();
                Set<String> removeUnitIds = new LinkedHashSet<String>();
                Set<String> candidateVolunteerIds = new LinkedHashSet<String>();
                Set<String> candidateUnitIds = new LinkedHashSet<String>();
                collectRemovedIds(action, removeVolunteerIds, removeUnitIds);
                collectAddedIds(action, candidateVolunteerIds, candidateUnitIds);
                count.removeUnitCount += removeUnitIds.size();
                count.removeVolunteerCount += removeVolunteerIds.size();
                count.addUnitCount += candidateUnitIds.size();
                count.addVolunteerCount += candidateVolunteerIds.size();
            } else if (RepairProposalTaxonomy.ActionType.ADJUST_MAJOR_GROUP_INNER_SAFETY.equals(actionType)) {
                count.removeVolunteerCount += defaultList(action.getRemoveVolunteerIds()).size();
                count.addVolunteerCount += !defaultList(action.getCandidateVolunteerIds()).isEmpty()
                        ? defaultList(action.getCandidateVolunteerIds()).size()
                        : defaultList(action.getVolunteerIds()).size();
            } else {
                count.addUnitCount += defaultList(action.getUnitIds()).size();
                count.addVolunteerCount += defaultList(action.getVolunteerIds()).size();
            }
        }
        return count;
    }

    private static void populateStatus(FixProposalDTO proposal, FixProposalDryRunResultDTO dryRun) {
        if (RepairProposalTaxonomy.isCannotSatisfyStrategy(proposal.getStrategy())) {
            dryRun.setStatus(RepairProposalTaxonomy.Status.BLOCKED);
            dryRun.setMessage(Strings.isNullOrEmpty(proposal.getBlockingReason())
                    ? "当前候选不足或缺少可执行动作，暂时不能自动修复该风险。"
                    : proposal.getBlockingReason());
            dryRun.getWarnings().add("需要放宽约束、补充候选，或改为人工调整。");
        } else if (RepairProposalTaxonomy.isBlockedStatus(proposal.getStatus())) {
            dryRun.setStatus(RepairProposalTaxonomy.Status.BLOCKED);
            dryRun.setMessage(Strings.isNullOrEmpty(proposal.getBlockingReason())
                    ? "当前风险缺少可执行动作，暂时不能自动修复。" : proposal.getBlockingReason());
        } else if (RepairProposalTaxonomy.isNoOpStrategy(proposal.getStrategy())) {
            dryRun.setStatus(RepairProposalTaxonomy.Status.INFO);
            dryRun.setMessage("该问题默认只提醒，不需要生成方案调整动作。");
        } else if (RepairProposalTaxonomy.isPreviewOnlyStatus(proposal.getStatus())) {
            dryRun.setStatus(RepairProposalTaxonomy.Status.PREVIEW_ONLY);
            dryRun.setMessage("已生成修复方向预览，但该策略暂不支持自动应用。");
        } else {
            dryRun.setStatus(RepairProposalTaxonomy.Status.READY);
            dryRun.setMessage("已生成可预览的修复方案，应用前仍需要用户确认。");
        }
    }

    private static void populateSnapshot(PlanningStateDTO state, FixProposalDTO proposal) {
        if (state == null || proposal.getDryRunResult() == null) {
            return;
        }
        List<CandidateItemDTO> candidates = defaultCandidates(state.getCandidatePoolState() == null
                ? null : state.getCandidatePoolState().getItems());
        DryRunPlanSnapshot before = buildSnapshot(state, candidates);
        DryRunPlanSnapshot after = copySnapshot(before);
        for (FixProposalActionDTO action : defaultList(proposal.getActions())) {
            applyAction(after, action, candidates);
        }
        applyStrategySimulation(after, proposal, state, candidates);

        FixProposalDryRunResultDTO dryRun = proposal.getDryRunResult();
        dryRun.setBeforeVolunteerTotal(before.volunteerTierById.size());
        dryRun.setAfterVolunteerTotal(after.volunteerTierById.size());
        dryRun.setBeforeUnitTotal(before.unitTierById.size());
        dryRun.setAfterUnitTotal(after.unitTierById.size());
        dryRun.setBeforeVolunteerTierCounts(countTierValues(before.volunteerTierById.values()));
        dryRun.setAfterVolunteerTierCounts(countTierValues(after.volunteerTierById.values()));
        dryRun.setBeforeUnitTierCounts(countTierValues(before.unitTierById.values()));
        dryRun.setAfterUnitTierCounts(countTierValues(after.unitTierById.values()));
        dryRun.setBeforeVolunteerIds(new LinkedHashSet<String>(before.volunteerTierById.keySet()));
        dryRun.setAfterVolunteerIds(new LinkedHashSet<String>(after.volunteerTierById.keySet()));
        dryRun.setBeforeUnitIds(new LinkedHashSet<String>(before.unitTierById.keySet()));
        dryRun.setAfterUnitIds(new LinkedHashSet<String>(after.unitTierById.keySet()));
        populateQualityMetrics(dryRun, before, after, candidates);
        populateQualityWarnings(dryRun);
    }

    private static void populateQualityMetrics(FixProposalDryRunResultDTO dryRun,
                                               DryRunPlanSnapshot before,
                                               DryRunPlanSnapshot after,
                                               List<CandidateItemDTO> candidates) {
        Map<String, CandidateItemDTO> candidateMap = defaultCandidates(candidates).stream()
                .filter(candidate -> candidate != null && !Strings.isNullOrEmpty(candidate.getVolunteerId()))
                .collect(Collectors.toMap(CandidateItemDTO::getVolunteerId, candidate -> candidate, (left, right) -> left, LinkedHashMap::new));
        dryRun.setBeforeAverageFinalScore(averageMetric(before.volunteerTierById.keySet(), candidateMap, CandidateItemDTO::getFinalScore));
        dryRun.setAfterAverageFinalScore(averageMetric(after.volunteerTierById.keySet(), candidateMap, CandidateItemDTO::getFinalScore));
        dryRun.setBeforeAverageHotIndex(averageMetric(before.volunteerTierById.keySet(), candidateMap, CandidateItemDTO::getHotIndex));
        dryRun.setAfterAverageHotIndex(averageMetric(after.volunteerTierById.keySet(), candidateMap, CandidateItemDTO::getHotIndex));
        dryRun.setBeforeAverageSchoolRank(averageMetric(before.volunteerTierById.keySet(), candidateMap,
                candidate -> candidate.getSchoolRank() == null ? null : candidate.getSchoolRank().doubleValue()));
        dryRun.setAfterAverageSchoolRank(averageMetric(after.volunteerTierById.keySet(), candidateMap,
                candidate -> candidate.getSchoolRank() == null ? null : candidate.getSchoolRank().doubleValue()));
    }

    private static void populateQualityWarnings(FixProposalDryRunResultDTO dryRun) {
        addMetricDropWarning(dryRun, "平均推荐系数", dryRun.getBeforeAverageFinalScore(), dryRun.getAfterAverageFinalScore(), 3D, false);
        addMetricDropWarning(dryRun, "平均专业热度", dryRun.getBeforeAverageHotIndex(), dryRun.getAfterAverageHotIndex(), 5D, false);
        addMetricDropWarning(dryRun, "平均院校排名", dryRun.getBeforeAverageSchoolRank(), dryRun.getAfterAverageSchoolRank(), 20D, true);
    }

    private static void populateWarnings(PlanningStateDTO state,
                                         FixProposalDTO proposal,
                                         FixProposalDryRunResultDTO dryRun) {
        if (state == null || proposal == null || dryRun == null || state.getConstraintState() == null) {
            return;
        }
        ConstraintStateDTO constraintState = state.getConstraintState();
        HardConstraintsDTO hard = constraintState.getHardConstraints();
        SoftPreferencesDTO soft = constraintState.getSoftPreferences();
        List<CandidateItemDTO> candidates = defaultCandidates(state.getCandidatePoolState() == null
                ? null : state.getCandidatePoolState().getItems());
        List<CandidateItemDTO> addedCandidates = resolveActionCandidates(proposal.getActions(), candidates, true);
        List<CandidateItemDTO> removedCandidates = resolveActionCandidates(proposal.getActions(), candidates, false);

        for (CandidateItemDTO candidate : addedCandidates) {
            String hardIssue = hardConstraintIssueForAdded(candidate, hard);
            if (!Strings.isNullOrEmpty(hardIssue)) {
                addDryRunWarning(dryRun, "新增项可能不符合已确认的报考条件：" + formatCandidateBrief(candidate) + "（" + hardIssue + "）");
            }
            String softIssue = softAvoidIssue(candidate, soft);
            if (!Strings.isNullOrEmpty(softIssue)) {
                addDryRunWarning(dryRun, "新增项命中不优先方向：" + formatCandidateBrief(candidate) + "（" + softIssue + "）");
            }
            String riskIssue = riskIssuesForAdded(candidate).stream()
                    .distinct()
                    .collect(Collectors.joining("；"));
            if (!Strings.isNullOrEmpty(riskIssue)) {
                addDryRunWarning(dryRun, "新增项需要额外确认：" + formatCandidateBrief(candidate) + "（" + riskIssue + "）");
            }
        }

        for (CandidateItemDTO candidate : removedCandidates) {
            String hardHit = hardIncludeHit(candidate, hard);
            if (!Strings.isNullOrEmpty(hardHit)) {
                addDryRunWarning(dryRun, "本次会移除已确认报考条件命中的志愿：" + formatCandidateBrief(candidate) + "（" + hardHit + "）");
            }
            String softHit = softPreferHit(candidate, soft);
            if (!Strings.isNullOrEmpty(softHit)) {
                addDryRunWarning(dryRun, "本次会移除偏好命中项：" + formatCandidateBrief(candidate) + "（" + softHit + "）");
            }
        }
    }

    private static void populateObjectiveValidation(PlanningStateDTO state,
                                                    FixProposalDTO proposal,
                                                    ReviewCheckDTO check,
                                                    FixProposalDryRunResultDTO dryRun) {
        ObjectiveValidation validation = validateObjectiveImprovement(state, proposal, check, dryRun);
        if (validation == null || validation.improved || Strings.isNullOrEmpty(validation.message)) {
            return;
        }
        addDryRunWarning(dryRun, validation.message);
        if (RepairProposalTaxonomy.isReadyStatus(proposal.getStatus())
                && RepairProposalTaxonomy.isReadyStatus(dryRun.getStatus())) {
            RepairProposalStateBuilder.markBlocked(proposal, validation.message, "objective_validation_not_improved");
            dryRun.setStatus(RepairProposalTaxonomy.Status.BLOCKED);
            dryRun.setMessage(validation.message);
        }
    }

    private static ObjectiveValidation validateObjectiveImprovement(PlanningStateDTO state,
                                                                    FixProposalDTO proposal,
                                                                    ReviewCheckDTO check,
                                                                    FixProposalDryRunResultDTO dryRun) {
        if (state == null || proposal == null || check == null || dryRun == null) {
            return null;
        }
        String strategy = RepairProposalTaxonomy.normalizeStrategy(proposal.getStrategy());
        if (RepairProposalTaxonomy.Strategy.FILL_MISSING_COUNT.equals(strategy) || "count_validation".equals(check.getCode())) {
            return validateCountObjective(state.getCandidatePoolState(), dryRun);
        }
        if (RepairProposalTaxonomy.Strategy.REPLACE_RISK_ITEMS.equals(strategy)) {
            return validateRiskReplacementObjective(state, check, dryRun);
        }
        if (RepairProposalTaxonomy.Strategy.REMOVE_RISK_ITEMS.equals(strategy) || "item".equals(check.getScopeKind())) {
            return validateAffectedItemRemoval(check, dryRun);
        }
        if (RepairProposalTaxonomy.Strategy.ADJUST_MAJOR_GROUP_INNER_SAFETY.equals(strategy)
                || "group_inner_safety_guard".equals(check.getCode())
                || "major_group_safety_intent_alignment".equals(check.getCode())) {
            return validateMajorGroupInnerSafetyObjective(state, check, dryRun);
        }
        if (RepairProposalTaxonomy.Strategy.REBALANCE_TIER_RATIO.equals(strategy) || "ratio_distribution".equals(check.getCode())) {
            return validateTierRatioObjective(state.getCandidatePoolState(), dryRun);
        }
        if (RepairProposalTaxonomy.Strategy.FILL_PROBABILITY_GAP.equals(strategy) || "probability_gap".equals(check.getCode())) {
            return validateProbabilityGapObjective(state, dryRun);
        }
        if (RepairProposalTaxonomy.Strategy.SORT_BY_PROBABILITY.equals(strategy) || "probability_inversion".equals(check.getCode())) {
            return validateProbabilityInversionObjective(state, dryRun);
        }
        return null;
    }

    private static ObjectiveValidation validateCountObjective(CandidatePoolStateDTO candidatePoolState,
                                                              FixProposalDryRunResultDTO dryRun) {
        Integer requiredCount = candidatePoolState == null ? null : candidatePoolState.getRequiredCount();
        if (requiredCount == null || requiredCount <= 0) {
            return null;
        }
        boolean majorGroupMode = isMajorGroupMode(candidatePoolState);
        Integer before = majorGroupMode ? dryRun.getBeforeUnitTotal() : dryRun.getBeforeVolunteerTotal();
        Integer after = majorGroupMode ? dryRun.getAfterUnitTotal() : dryRun.getAfterVolunteerTotal();
        if (before == null || after == null || before.equals(requiredCount)) {
            return null;
        }
        boolean movesTowardRequired = Math.abs(after - requiredCount) < Math.abs(before - requiredCount);
        boolean followsDirection = before < requiredCount ? after > before : after < before;
        return ObjectiveValidation.of(movesTowardRequired && followsDirection,
                "修复预览没有让志愿数量更接近官方要求，暂不允许确认应用。");
    }

    private static ObjectiveValidation validateTierRatioObjective(CandidatePoolStateDTO candidatePoolState,
                                                                  FixProposalDryRunResultDTO dryRun) {
        if (candidatePoolState == null || dryRun == null
                || candidatePoolState.getRequiredTierCounts() == null
                || candidatePoolState.getRequiredTierCounts().isEmpty()) {
            return null;
        }
        boolean hasPositiveTarget = candidatePoolState.getRequiredTierCounts().values().stream()
                .anyMatch(value -> value != null && value > 0);
        if (!hasPositiveTarget) {
            return null;
        }
        boolean majorGroupMode = isMajorGroupMode(candidatePoolState);
        Map<String, Integer> beforeCounts = majorGroupMode ? dryRun.getBeforeUnitTierCounts() : dryRun.getBeforeVolunteerTierCounts();
        Map<String, Integer> afterCounts = majorGroupMode ? dryRun.getAfterUnitTierCounts() : dryRun.getAfterVolunteerTierCounts();
        int beforeDistance = tierCountDistance(beforeCounts, candidatePoolState.getRequiredTierCounts());
        int afterDistance = tierCountDistance(afterCounts, candidatePoolState.getRequiredTierCounts());
        if (beforeDistance <= 0) {
            return null;
        }
        return ObjectiveValidation.of(afterDistance < beforeDistance,
                "修复预览没有让冲稳保配比更接近目标，暂不允许确认应用。");
    }

    private static int tierCountDistance(Map<String, Integer> actualCounts, Map<String, Integer> targetCounts) {
        int distance = 0;
        for (String tier : Lists.newArrayList("冲", "稳", "保")) {
            Integer target = targetCounts == null ? null : targetCounts.get(tier);
            if (target == null || target <= 0) {
                continue;
            }
            int actual = actualCounts == null || actualCounts.get(tier) == null ? 0 : actualCounts.get(tier);
            distance += Math.abs(actual - target);
        }
        return distance;
    }

    private static ObjectiveValidation validateAffectedItemRemoval(ReviewCheckDTO check,
                                                                   FixProposalDryRunResultDTO dryRun) {
        int beforeAffectedVolunteers = countPresent(defaultList(check.getAffectedVolunteerIds()),
                dryRun.getBeforeVolunteerIds());
        int afterAffectedVolunteers = countPresent(defaultList(check.getAffectedVolunteerIds()),
                dryRun.getAfterVolunteerIds());
        int beforeAffectedUnits = countPresent(defaultList(check.getAffectedUnitIds()), dryRun.getBeforeUnitIds());
        int afterAffectedUnits = countPresent(defaultList(check.getAffectedUnitIds()), dryRun.getAfterUnitIds());
        if (beforeAffectedVolunteers == 0 && beforeAffectedUnits == 0) {
            return null;
        }
        return ObjectiveValidation.of(
                afterAffectedVolunteers < beforeAffectedVolunteers || afterAffectedUnits < beforeAffectedUnits,
                "修复预览没有减少本次审查命中的风险志愿，暂不允许确认应用。");
    }

    private static ObjectiveValidation validateRiskReplacementObjective(PlanningStateDTO state,
                                                                        ReviewCheckDTO check,
                                                                        FixProposalDryRunResultDTO dryRun) {
        int beforeAffectedVolunteers = countPresent(defaultList(check.getAffectedVolunteerIds()),
                dryRun.getBeforeVolunteerIds());
        int afterAffectedVolunteers = countPresent(defaultList(check.getAffectedVolunteerIds()),
                dryRun.getAfterVolunteerIds());
        if (beforeAffectedVolunteers == 0) {
            return null;
        }
        if (afterAffectedVolunteers > 0) {
            return ObjectiveValidation.of(false,
                    "替换预览没有覆盖全部风险志愿，暂不允许确认应用。");
        }
        if (!Objects.equals(dryRun.getBeforeVolunteerTotal(), dryRun.getAfterVolunteerTotal())) {
            return ObjectiveValidation.of(false,
                    "替换预览没有保持志愿数量不变，暂不允许确认应用。");
        }
        if (isMajorGroupMode(state == null ? null : state.getCandidatePoolState())
                && !Objects.equals(dryRun.getBeforeUnitTotal(), dryRun.getAfterUnitTotal())) {
            return ObjectiveValidation.of(false,
                    "替换预览会改变专业组数量，暂不允许确认应用。");
        }
        return ObjectiveValidation.of(true, null);
    }

    private static ObjectiveValidation validateMajorGroupInnerSafetyObjective(PlanningStateDTO state,
                                                                             ReviewCheckDTO check,
                                                                             FixProposalDryRunResultDTO dryRun) {
        if (state == null || !isMajorGroupMode(state.getCandidatePoolState())) {
            return null;
        }
        List<CandidateItemDTO> candidates = defaultCandidates(state.getCandidatePoolState().getItems());
        Set<String> targetUnitIds = resolveTargetUnitIds(check, candidates);
        if (targetUnitIds.isEmpty()) {
            return null;
        }
        Map<String, CandidateItemDTO> candidateMap = candidateMapByVolunteerId(candidates);
        boolean allTargetsSafeAfter = true;
        boolean atLeastOneTargetImproved = false;
        for (String unitId : targetUnitIds) {
            boolean beforeSafe = hasSafetyMajor(dryRun.getBeforeVolunteerIds(), unitId, candidateMap);
            boolean afterSafe = hasSafetyMajor(dryRun.getAfterVolunteerIds(), unitId, candidateMap);
            if (!afterSafe) {
                allTargetsSafeAfter = false;
            }
            if (!beforeSafe && afterSafe) {
                atLeastOneTargetImproved = true;
            }
        }
        return ObjectiveValidation.of(allTargetsSafeAfter && atLeastOneTargetImproved,
                "修复预览没有为目标专业组补足组内安全垫专业，暂不允许确认应用。");
    }

    private static ObjectiveValidation validateProbabilityGapObjective(PlanningStateDTO state,
                                                                       FixProposalDryRunResultDTO dryRun) {
        if (state == null || dryRun == null || state.getCandidatePoolState() == null) {
            return null;
        }
        List<CandidateItemDTO> candidates = defaultCandidates(state.getCandidatePoolState().getItems());
        boolean majorGroupMode = isMajorGroupMode(state.getCandidatePoolState());
        ProbabilityGapMetrics before = majorGroupMode
                ? unitProbabilityGapMetrics(dryRun.getBeforeUnitIds(), candidates)
                : volunteerProbabilityGapMetrics(dryRun.getBeforeVolunteerIds(), candidates);
        if (before.gapCount <= 0) {
            return null;
        }
        ProbabilityGapMetrics after = majorGroupMode
                ? unitProbabilityGapMetrics(dryRun.getAfterUnitIds(), candidates)
                : volunteerProbabilityGapMetrics(dryRun.getAfterVolunteerIds(), candidates);
        boolean improved = after.gapCount < before.gapCount || after.maxGap < before.maxGap;
        return ObjectiveValidation.of(improved,
                "修复预览没有缩小录取率梯度断层，暂不允许确认应用。");
    }

    private static ObjectiveValidation validateProbabilityInversionObjective(PlanningStateDTO state,
                                                                            FixProposalDryRunResultDTO dryRun) {
        if (state == null || dryRun == null || state.getCandidatePoolState() == null) {
            return null;
        }
        List<CandidateItemDTO> candidates = defaultCandidates(state.getCandidatePoolState().getItems());
        boolean majorGroupMode = isMajorGroupMode(state.getCandidatePoolState());
        int beforeInversions = majorGroupMode
                ? countUnitProbabilityInversions(dryRun.getBeforeUnitIds(), candidates)
                : countVolunteerProbabilityInversions(dryRun.getBeforeVolunteerIds(), candidates);
        if (beforeInversions <= 0) {
            return null;
        }
        int afterInversions = majorGroupMode
                ? countUnitProbabilityInversions(dryRun.getAfterUnitIds(), candidates)
                : countVolunteerProbabilityInversions(dryRun.getAfterVolunteerIds(), candidates);
        return ObjectiveValidation.of(afterInversions < beforeInversions,
                "排序预览没有减少录取率倒挂，暂不允许确认应用。");
    }

    private static int countPresent(List<String> targetIds, Set<String> actualIds) {
        int count = 0;
        for (String targetId : defaultList(targetIds)) {
            if (!Strings.isNullOrEmpty(targetId) && actualIds != null && actualIds.contains(targetId)) {
                count++;
            }
        }
        return count;
    }

    private static Set<String> resolveTargetUnitIds(ReviewCheckDTO check, List<CandidateItemDTO> candidates) {
        Set<String> unitIds = defaultList(check == null ? null : check.getAffectedUnitIds()).stream()
                .filter(value -> !Strings.isNullOrEmpty(value))
                .collect(Collectors.toCollection(LinkedHashSet::new));
        if (!unitIds.isEmpty()) {
            return unitIds;
        }
        Map<String, CandidateItemDTO> candidateMap = candidateMapByVolunteerId(candidates);
        for (String volunteerId : defaultList(check == null ? null : check.getAffectedVolunteerIds())) {
            CandidateItemDTO candidate = candidateMap.get(volunteerId);
            String unitId = RepairCandidateSelector.resolveInitialRecommendationUnitId(candidate);
            if (!Strings.isNullOrEmpty(unitId)) {
                unitIds.add(unitId);
            }
        }
        return unitIds;
    }

    private static boolean hasSafetyMajor(Set<String> volunteerIds,
                                          String unitId,
                                          Map<String, CandidateItemDTO> candidateMap) {
        for (String volunteerId : defaultSet(volunteerIds)) {
            CandidateItemDTO candidate = candidateMap == null ? null : candidateMap.get(volunteerId);
            if (candidate == null || !Objects.equals(unitId, RepairCandidateSelector.resolveInitialRecommendationUnitId(candidate))) {
                continue;
            }
            if (isSafetyMajorRatio(candidate.getAdmissionRatio(), candidate.getSchoolEnrollRatio())) {
                return true;
            }
        }
        return false;
    }

    private static boolean isSafetyMajorRatio(Double majorAdmissionRatio, Double unitEnrollRatio) {
        return majorAdmissionRatio != null
                && unitEnrollRatio != null
                && majorAdmissionRatio >= unitEnrollRatio;
    }

    private static Map<String, CandidateItemDTO> candidateMapByVolunteerId(List<CandidateItemDTO> candidates) {
        return defaultCandidates(candidates).stream()
                .filter(candidate -> candidate != null && !Strings.isNullOrEmpty(candidate.getVolunteerId()))
                .collect(Collectors.toMap(CandidateItemDTO::getVolunteerId, candidate -> candidate,
                        (left, right) -> left, LinkedHashMap::new));
    }

    private static Double averageMetric(Set<String> volunteerIds,
                                        Map<String, CandidateItemDTO> candidateMap,
                                        Function<CandidateItemDTO, Double> metricGetter) {
        double sum = 0D;
        int count = 0;
        for (String volunteerId : defaultSet(volunteerIds)) {
            CandidateItemDTO candidate = candidateMap.get(volunteerId);
            if (candidate == null) {
                continue;
            }
            Double value = metricGetter.apply(candidate);
            if (value == null) {
                continue;
            }
            sum += value;
            count++;
        }
        return count == 0 ? null : sum / count;
    }

    private static void addMetricDropWarning(FixProposalDryRunResultDTO dryRun,
                                             String label,
                                             Double before,
                                             Double after,
                                             Double threshold,
                                             boolean largerIsWorse) {
        if (dryRun == null || before == null || after == null || threshold == null) {
            return;
        }
        boolean worse = largerIsWorse ? after - before > threshold : before - after > threshold;
        if (worse) {
            addDryRunWarning(dryRun, label + "可能下降：" + formatMetric(before) + " -> " + formatMetric(after));
        }
    }

    private static String formatMetric(Double value) {
        if (value == null) {
            return "";
        }
        return String.format(Locale.ROOT, "%.1f", value);
    }

    private static List<CandidateItemDTO> resolveActionCandidates(List<FixProposalActionDTO> actions,
                                                                  List<CandidateItemDTO> candidates,
                                                                  boolean addedSide) {
        Set<String> volunteerIds = new LinkedHashSet<String>();
        Set<String> unitIds = new LinkedHashSet<String>();
        for (FixProposalActionDTO action : defaultList(actions)) {
            if (action == null) {
                continue;
            }
            if (addedSide) {
                collectAddedIds(action, volunteerIds, unitIds);
            } else {
                collectRemovedIds(action, volunteerIds, unitIds);
            }
        }
        List<CandidateItemDTO> result = Lists.newArrayList();
        Set<String> seenVolunteerIds = new LinkedHashSet<String>();
        for (CandidateItemDTO candidate : defaultCandidates(candidates)) {
            if (candidate == null) {
                continue;
            }
            String volunteerId = Strings.nullToEmpty(candidate.getVolunteerId());
            String unitId = RepairCandidateSelector.resolveInitialRecommendationUnitId(candidate);
            if ((volunteerIds.contains(volunteerId) || unitIds.contains(unitId)) && seenVolunteerIds.add(volunteerId)) {
                result.add(candidate);
            }
        }
        return result;
    }

    private static void collectAddedIds(FixProposalActionDTO action, Set<String> volunteerIds, Set<String> unitIds) {
        collectAddedIds(action, volunteerIds, unitIds, shouldUseUnitScopeForReplace(action));
    }

    private static void collectAddedIds(FixProposalActionDTO action,
                                        Set<String> volunteerIds,
                                        Set<String> unitIds,
                                        boolean includeReplaceUnitScope) {
        String actionType = RepairProposalTaxonomy.normalizeActionType(action.getActionType());
        if (RepairProposalTaxonomy.ActionType.REMOVE_VOLUNTEERS.equals(actionType)) {
            return;
        }
        if (RepairProposalTaxonomy.ActionType.REPLACE_VOLUNTEERS.equals(actionType)) {
            addAllNonBlank(volunteerIds, action.getCandidateVolunteerIds());
            if (includeReplaceUnitScope) {
                addAllNonBlank(unitIds, action.getCandidateUnitIds());
            }
            for (ReplacementPairDTO pair : defaultList(action.getReplacementPairs())) {
                if (pair == null) {
                    continue;
                }
                addNonBlank(volunteerIds, pair.getToVolunteerId());
                if (includeReplaceUnitScope) {
                    addNonBlank(unitIds, pair.getToUnitId());
                }
            }
            return;
        }
        if (RepairProposalTaxonomy.ActionType.ADJUST_MAJOR_GROUP_INNER_SAFETY.equals(actionType)) {
            List<String> candidateVolunteerIds = defaultList(action.getCandidateVolunteerIds());
            addAllNonBlank(volunteerIds, candidateVolunteerIds.isEmpty() ? action.getVolunteerIds() : candidateVolunteerIds);
            addAllNonBlank(unitIds, action.getCandidateUnitIds());
            return;
        }
        addAllNonBlank(volunteerIds, action.getVolunteerIds());
        addAllNonBlank(unitIds, action.getUnitIds());
    }

    private static void collectRemovedIds(FixProposalActionDTO action, Set<String> volunteerIds, Set<String> unitIds) {
        collectRemovedIds(action, volunteerIds, unitIds, shouldUseUnitScopeForReplace(action));
    }

    private static void collectRemovedIds(FixProposalActionDTO action,
                                          Set<String> volunteerIds,
                                          Set<String> unitIds,
                                          boolean includeReplaceUnitScope) {
        String actionType = RepairProposalTaxonomy.normalizeActionType(action.getActionType());
        if (RepairProposalTaxonomy.ActionType.REPLACE_VOLUNTEERS.equals(actionType)) {
            addAllNonBlank(volunteerIds, action.getRemoveVolunteerIds());
            if (includeReplaceUnitScope) {
                addAllNonBlank(unitIds, action.getRemoveUnitIds());
            }
            for (ReplacementPairDTO pair : defaultList(action.getReplacementPairs())) {
                if (pair == null) {
                    continue;
                }
                addNonBlank(volunteerIds, pair.getFromVolunteerId());
                if (includeReplaceUnitScope) {
                    addNonBlank(unitIds, pair.getFromUnitId());
                }
            }
            return;
        }
        if (RepairProposalTaxonomy.ActionType.REMOVE_VOLUNTEERS.equals(actionType)) {
            addAllNonBlank(volunteerIds, action.getVolunteerIds());
            addAllNonBlank(unitIds, action.getUnitIds());
            return;
        }
        if (RepairProposalTaxonomy.ActionType.ADJUST_MAJOR_GROUP_INNER_SAFETY.equals(actionType)) {
            addAllNonBlank(volunteerIds, action.getRemoveVolunteerIds());
            addAllNonBlank(unitIds, action.getRemoveUnitIds());
        }
    }

    private static boolean shouldUseUnitScopeForReplace(FixProposalActionDTO action) {
        if (action == null
                || !RepairProposalTaxonomy.ActionType.REPLACE_VOLUNTEERS.equals(
                RepairProposalTaxonomy.normalizeActionType(action.getActionType()))) {
            return true;
        }
        if (!defaultList(action.getRemoveVolunteerIds()).isEmpty()
                || !defaultList(action.getCandidateVolunteerIds()).isEmpty()) {
            return false;
        }
        ReviewRuleMetadataDTO metadata = ReviewRuleRegistry.get(action.getSourceCheckCode());
        return metadata == null || !"item".equals(metadata.getScopeKind());
    }

    private static void addAllNonBlank(Set<String> target, List<String> values) {
        for (String value : defaultList(values)) {
            addNonBlank(target, value);
        }
    }

    private static void addNonBlank(Set<String> target, String value) {
        if (target != null && !Strings.isNullOrEmpty(value)) {
            target.add(value);
        }
    }

    private static String hardConstraintIssueForAdded(CandidateItemDTO candidate, HardConstraintsDTO hard) {
        if (hard == null || candidate == null) {
            return "";
        }
        String excluded = firstNonBlank(
                matchedRegionLabel(candidate, hard.getMustExcludeRegions(), "排除地区"),
                matchedSchoolLabel(candidate, hard.getMustExcludeSchools(), "排除院校"),
                matchedMajorLabel(candidate, hard.getMustExcludeMajors(), "排除专业")
        );
        if (!Strings.isNullOrEmpty(excluded)) {
            return excluded;
        }
        return firstNonBlank(
                missedRegionLabel(candidate, hard.getMustIncludeRegions(), "限定地区"),
                missedSchoolLabel(candidate, hard.getMustIncludeSchools(), "限定院校"),
                missedMajorLabel(candidate, hard.getMustIncludeMajors(), "限定专业")
        );
    }

    private static String hardIncludeHit(CandidateItemDTO candidate, HardConstraintsDTO hard) {
        if (hard == null || candidate == null) {
            return "";
        }
        return firstNonBlank(
                matchedRegionLabel(candidate, hard.getMustIncludeRegions(), "限定地区"),
                matchedSchoolLabel(candidate, hard.getMustIncludeSchools(), "限定院校"),
                matchedMajorLabel(candidate, hard.getMustIncludeMajors(), "限定专业")
        );
    }

    private static String softAvoidIssue(CandidateItemDTO candidate, SoftPreferencesDTO soft) {
        if (soft == null || candidate == null) {
            return "";
        }
        return firstNonBlank(
                matchedRegionLabel(candidate, soft.getAvoidRegions(), "不优先地区"),
                matchedSchoolLabel(candidate, soft.getAvoidSchools(), "不优先院校"),
                matchedMajorLabel(candidate, soft.getAvoidMajors(), "不优先专业")
        );
    }

    private static String softPreferHit(CandidateItemDTO candidate, SoftPreferencesDTO soft) {
        if (soft == null || candidate == null) {
            return "";
        }
        return firstNonBlank(
                matchedRegionLabel(candidate, soft.getPreferRegions(), "偏好地区"),
                matchedSchoolLabel(candidate, soft.getPreferSchools(), "偏好院校"),
                matchedMajorLabel(candidate, soft.getPreferMajors(), "偏好专业")
        );
    }

    private static List<String> riskIssuesForAdded(CandidateItemDTO candidate) {
        List<String> issues = Lists.newArrayList();
        if (candidate == null) {
            return issues;
        }
        List<String> explicitRiskFlags = defaultList(candidate.getRiskFlags()).stream()
                .filter(RepairCandidateSelector::isBlockingRiskFlag)
                .collect(Collectors.toList());
        if (candidate.getTuitionPerYear() != null && candidate.getTuitionPerYear() > 20000) {
            issues.add("高收费，学费约" + candidate.getTuitionPerYear() + "元/年");
        }
        String admissionLimitTag = firstMatchingTag(
                mergeTextTags(candidate.getReasonCodes(), explicitRiskFlags, candidate.getMustSubjects()),
                "色盲", "色弱", "单科", "性别", "语种", "limited", "limit"
        );
        if (!Strings.isNullOrEmpty(admissionLimitTag)) {
            issues.add("可能有限报要求:" + admissionLimitTag);
        }
        if (containsAny(candidate.getSchoolName(), "中外合作")
                || containsAny(candidate.getMajorName(), "中外合作")
                || !Strings.isNullOrEmpty(firstMatchingTag(mergeTextTags(candidate.getReasonCodes(), explicitRiskFlags),
                "中外合作", "foreign", "cooperative"))) {
            issues.add("中外合作项目");
        }
        String specialTag = firstMatchingTag(
                mergeTextTags(candidate.getReasonCodes(), explicitRiskFlags),
                "专项", "公费", "定向", "免费医学生", "强基", "国家计划", "地方专项", "高校专项", "special"
        );
        if (!Strings.isNullOrEmpty(specialTag)) {
            issues.add("特殊类型招生:" + specialTag);
        }
        return issues;
    }

    private static String matchedRegionLabel(CandidateItemDTO candidate, List<String> values, String label) {
        String value = firstMatch(values, candidate.getProvinceName(), candidate.getCityName());
        return Strings.isNullOrEmpty(value) ? "" : label + ":" + value;
    }

    private static String matchedSchoolLabel(CandidateItemDTO candidate, List<String> values, String label) {
        String value = firstMatch(values, candidate.getSchoolName());
        return Strings.isNullOrEmpty(value) ? "" : label + ":" + value;
    }

    private static String matchedMajorLabel(CandidateItemDTO candidate, List<String> values, String label) {
        String value = firstMatch(values, candidate.getMajorName(), candidate.getMajorCategory(), candidate.getMajorDiscipline());
        return Strings.isNullOrEmpty(value) ? "" : label + ":" + value;
    }

    private static String missedRegionLabel(CandidateItemDTO candidate, List<String> values, String label) {
        return defaultList(values).isEmpty() || !Strings.isNullOrEmpty(matchedRegionLabel(candidate, values, label))
                ? "" : label + ":" + joinFirstValues(values);
    }

    private static String missedSchoolLabel(CandidateItemDTO candidate, List<String> values, String label) {
        return defaultList(values).isEmpty() || !Strings.isNullOrEmpty(matchedSchoolLabel(candidate, values, label))
                ? "" : label + ":" + joinFirstValues(values);
    }

    private static String missedMajorLabel(CandidateItemDTO candidate, List<String> values, String label) {
        return defaultList(values).isEmpty() || !Strings.isNullOrEmpty(matchedMajorLabel(candidate, values, label))
                ? "" : label + ":" + joinFirstValues(values);
    }

    private static String firstMatch(List<String> values, String... fields) {
        for (String value : defaultList(values)) {
            for (String field : fields == null ? new String[0] : fields) {
                if (textMatches(field, value)) {
                    return value;
                }
            }
        }
        return "";
    }

    private static boolean textMatches(String field, String pattern) {
        if (Strings.isNullOrEmpty(field) || Strings.isNullOrEmpty(pattern)) {
            return false;
        }
        String normalizedField = field.trim().toLowerCase(Locale.ROOT);
        String normalizedPattern = pattern.trim().toLowerCase(Locale.ROOT);
        return normalizedField.contains(normalizedPattern) || normalizedPattern.contains(normalizedField);
    }

    @SafeVarargs
    private static List<String> mergeTextTags(List<String>... tagLists) {
        List<String> values = Lists.newArrayList();
        if (tagLists == null) {
            return values;
        }
        for (List<String> tagList : tagLists) {
            values.addAll(defaultList(tagList));
        }
        return values;
    }

    private static String firstMatchingTag(List<String> tags, String... keywords) {
        for (String tag : defaultList(tags)) {
            for (String keyword : keywords == null ? new String[0] : keywords) {
                if (textMatches(tag, keyword)) {
                    return tag;
                }
            }
        }
        return "";
    }

    private static boolean containsAny(String text, String... keywords) {
        for (String keyword : keywords == null ? new String[0] : keywords) {
            if (textMatches(text, keyword)) {
                return true;
            }
        }
        return false;
    }

    private static String firstNonBlank(String... values) {
        for (String value : values == null ? new String[0] : values) {
            if (!Strings.isNullOrEmpty(value)) {
                return value;
            }
        }
        return "";
    }

    private static String joinFirstValues(List<String> values) {
        return defaultList(values).stream()
                .filter(value -> !Strings.isNullOrEmpty(value))
                .limit(3)
                .collect(Collectors.joining("/"));
    }

    private static String formatCandidateBrief(CandidateItemDTO candidate) {
        if (candidate == null) {
            return "";
        }
        String schoolName = Strings.nullToEmpty(candidate.getSchoolName());
        String majorName = Strings.nullToEmpty(candidate.getMajorName());
        String brief = (schoolName + "-" + majorName).replaceAll("^-|-$", "");
        return Strings.isNullOrEmpty(brief) ? Strings.nullToEmpty(candidate.getVolunteerId()) : brief;
    }

    private static void addDryRunWarning(FixProposalDryRunResultDTO dryRun, String warning) {
        if (dryRun == null || Strings.isNullOrEmpty(warning)) {
            return;
        }
        if (dryRun.getWarnings() == null) {
            dryRun.setWarnings(Lists.newArrayList());
        }
        if (dryRun.getWarnings().contains(warning) || dryRun.getWarnings().size() >= MAX_DRY_RUN_WARNING_COUNT) {
            return;
        }
        dryRun.getWarnings().add(warning);
    }

    private static void applyStrategySimulation(DryRunPlanSnapshot snapshot,
                                                FixProposalDTO proposal,
                                                PlanningStateDTO state,
                                                List<CandidateItemDTO> candidates) {
        if (snapshot == null || proposal == null
                || !RepairProposalTaxonomy.Strategy.SORT_BY_PROBABILITY.equals(
                RepairProposalTaxonomy.normalizeStrategy(proposal.getStrategy()))) {
            return;
        }
        if (state != null && isMajorGroupMode(state.getCandidatePoolState())) {
            sortUnitsByAdmissionRatio(snapshot, candidates);
            return;
        }
        sortVolunteersByAdmissionRatio(snapshot, candidates);
    }

    private static void sortVolunteersByAdmissionRatio(DryRunPlanSnapshot snapshot,
                                                       List<CandidateItemDTO> candidates) {
        List<String> currentOrder = Lists.newArrayList(snapshot.volunteerTierById.keySet());
        List<String> sorted = sortByAdmissionRatio(currentOrder,
                volunteerId -> admissionRatioForVolunteer(volunteerId, candidates),
                volunteerId -> schoolGroupKeyForVolunteer(volunteerId, candidates));
        snapshot.volunteerTierById = reorderMap(snapshot.volunteerTierById, sorted);
        snapshot.volunteerUnitById = reorderMap(snapshot.volunteerUnitById, sorted);
        reorderUnitsByVolunteerOrder(snapshot);
    }

    private static void sortUnitsByAdmissionRatio(DryRunPlanSnapshot snapshot,
                                                  List<CandidateItemDTO> candidates) {
        List<String> currentOrder = Lists.newArrayList(snapshot.unitTierById.keySet());
        List<String> sorted = sortByAdmissionRatio(currentOrder,
                unitId -> admissionRatioForUnit(unitId, candidates),
                unitId -> unitSchoolGroupKey(unitId, candidates));
        snapshot.unitTierById = reorderMap(snapshot.unitTierById, sorted);
        reorderVolunteersByUnitOrder(snapshot);
    }

    private static List<String> sortByAdmissionRatio(List<String> currentOrder,
                                                     Function<String, Double> ratioResolver,
                                                     Function<String, String> tieBreaker) {
        return currentOrder.stream()
                .sorted((left, right) -> compareAdmissionRatioSort(left, right, ratioResolver, tieBreaker))
                .collect(Collectors.toList());
    }

    private static int compareAdmissionRatioSort(String left,
                                                 String right,
                                                 Function<String, Double> ratioResolver,
                                                 Function<String, String> tieBreaker) {
        Double leftRatio = ratioResolver.apply(left);
        Double rightRatio = ratioResolver.apply(right);
        boolean leftMissing = leftRatio == null;
        boolean rightMissing = rightRatio == null;
        if (!leftMissing || !rightMissing) {
            if (leftMissing) {
                return 1;
            }
            if (rightMissing) {
                return -1;
            }
            int compared = Double.compare(leftRatio, rightRatio);
            if (compared != 0) {
                return compared;
            }
        }
        return Strings.nullToEmpty(tieBreaker.apply(left)).compareTo(Strings.nullToEmpty(tieBreaker.apply(right)));
    }

    private static <T> Map<String, T> reorderMap(Map<String, T> source, List<String> orderedKeys) {
        Map<String, T> result = new LinkedHashMap<String, T>();
        for (String key : defaultList(orderedKeys)) {
            if (source.containsKey(key)) {
                result.put(key, source.get(key));
            }
        }
        for (Map.Entry<String, T> entry : source.entrySet()) {
            if (!result.containsKey(entry.getKey())) {
                result.put(entry.getKey(), entry.getValue());
            }
        }
        return result;
    }

    private static void reorderUnitsByVolunteerOrder(DryRunPlanSnapshot snapshot) {
        List<String> unitOrder = Lists.newArrayList();
        for (String volunteerId : snapshot.volunteerTierById.keySet()) {
            String unitId = snapshot.volunteerUnitById.get(volunteerId);
            if (!Strings.isNullOrEmpty(unitId) && snapshot.unitTierById.containsKey(unitId) && !unitOrder.contains(unitId)) {
                unitOrder.add(unitId);
            }
        }
        snapshot.unitTierById = reorderMap(snapshot.unitTierById, unitOrder);
    }

    private static void reorderVolunteersByUnitOrder(DryRunPlanSnapshot snapshot) {
        List<String> volunteerOrder = Lists.newArrayList();
        for (String unitId : snapshot.unitTierById.keySet()) {
            for (Map.Entry<String, String> entry : snapshot.volunteerUnitById.entrySet()) {
                if (unitId.equals(entry.getValue()) && !volunteerOrder.contains(entry.getKey())) {
                    volunteerOrder.add(entry.getKey());
                }
            }
        }
        snapshot.volunteerTierById = reorderMap(snapshot.volunteerTierById, volunteerOrder);
        snapshot.volunteerUnitById = reorderMap(snapshot.volunteerUnitById, volunteerOrder);
    }

    private static DryRunPlanSnapshot buildSnapshot(PlanningStateDTO state, List<CandidateItemDTO> candidates) {
        DryRunPlanSnapshot snapshot = new DryRunPlanSnapshot();
        List<OrderedItemDTO> orderedItems = defaultOrderedItems(state.getOrderedPlanState() == null
                ? null : state.getOrderedPlanState().getItems());
        if (!orderedItems.isEmpty()) {
            for (OrderedItemDTO item : orderedItems) {
                addVolunteer(snapshot, item.getVolunteerId(), item.getTier(), candidates);
            }
        } else {
            for (DraftItemDTO item : defaultDraftItems(state.getDraftPlanState() == null
                    ? null : state.getDraftPlanState().getItems())) {
                addVolunteer(snapshot, item.getVolunteerId(), item.getTier(), candidates);
            }
        }

        List<OrderedUnitDTO> orderedUnits = defaultOrderedUnits(state.getOrderedPlanState() == null
                ? null : state.getOrderedPlanState().getUnits());
        if (!orderedUnits.isEmpty()) {
            for (OrderedUnitDTO unit : orderedUnits) {
                addUnit(snapshot, unit.getUnitId(), unit.getTier(), candidates);
            }
        } else {
            for (DraftUnitDTO unit : defaultDraftUnits(state.getDraftPlanState() == null
                    ? null : state.getDraftPlanState().getUnits())) {
                addUnit(snapshot, unit.getUnitId(), unit.getTier(), candidates);
            }
        }
        ensureUnitsFromVolunteers(snapshot, candidates);
        return snapshot;
    }

    private static DryRunPlanSnapshot copySnapshot(DryRunPlanSnapshot source) {
        DryRunPlanSnapshot target = new DryRunPlanSnapshot();
        target.volunteerTierById.putAll(source.volunteerTierById);
        target.volunteerUnitById.putAll(source.volunteerUnitById);
        target.unitTierById.putAll(source.unitTierById);
        target.explicitUnitIds.addAll(source.explicitUnitIds);
        return target;
    }

    private static void applyAction(DryRunPlanSnapshot snapshot,
                                    FixProposalActionDTO action,
                                    List<CandidateItemDTO> candidates) {
        if (snapshot == null || action == null) {
            return;
        }
        String actionType = RepairProposalTaxonomy.normalizeActionType(action.getActionType());
        if (RepairProposalTaxonomy.ActionType.REMOVE_VOLUNTEERS.equals(actionType)) {
            removeUnits(snapshot, defaultList(action.getUnitIds()));
            removeVolunteers(snapshot, defaultList(action.getVolunteerIds()));
            return;
        }
        if (RepairProposalTaxonomy.ActionType.REPLACE_VOLUNTEERS.equals(actionType)) {
            Set<String> removeVolunteerIds = new LinkedHashSet<String>();
            Set<String> removeUnitIds = new LinkedHashSet<String>();
            Set<String> candidateVolunteerIds = new LinkedHashSet<String>();
            Set<String> candidateUnitIds = new LinkedHashSet<String>();
            collectRemovedIds(action, removeVolunteerIds, removeUnitIds);
            collectAddedIds(action, candidateVolunteerIds, candidateUnitIds);
            removeUnits(snapshot, Lists.newArrayList(removeUnitIds));
            removeVolunteers(snapshot, Lists.newArrayList(removeVolunteerIds));
            addUnits(snapshot, Lists.newArrayList(candidateUnitIds), candidates);
            addVolunteers(snapshot, Lists.newArrayList(candidateVolunteerIds), candidates);
            return;
        }
        if (RepairProposalTaxonomy.ActionType.ADJUST_MAJOR_GROUP_INNER_SAFETY.equals(actionType)) {
            removeVolunteers(snapshot, defaultList(action.getRemoveVolunteerIds()));
            List<String> addVolunteerIds = !defaultList(action.getCandidateVolunteerIds()).isEmpty()
                    ? action.getCandidateVolunteerIds() : action.getVolunteerIds();
            addVolunteers(snapshot, defaultList(addVolunteerIds), candidates);
            ensureUnitsFromVolunteers(snapshot, candidates);
            return;
        }
        addUnits(snapshot, defaultList(action.getUnitIds()), candidates);
        addVolunteers(snapshot, defaultList(action.getVolunteerIds()), candidates);
    }

    private static void addVolunteers(DryRunPlanSnapshot snapshot,
                                      List<String> volunteerIds,
                                      List<CandidateItemDTO> candidates) {
        for (String volunteerId : defaultList(volunteerIds)) {
            addVolunteer(snapshot, volunteerId, null, candidates);
        }
    }

    private static void addUnits(DryRunPlanSnapshot snapshot,
                                 List<String> unitIds,
                                 List<CandidateItemDTO> candidates) {
        for (String unitId : defaultList(unitIds)) {
            addExplicitUnit(snapshot, unitId, null, candidates);
        }
    }

    private static void addVolunteer(DryRunPlanSnapshot snapshot,
                                     String volunteerId,
                                     String fallbackTier,
                                     List<CandidateItemDTO> candidates) {
        if (snapshot == null || Strings.isNullOrEmpty(volunteerId)) {
            return;
        }
        CandidateItemDTO candidate = RepairCandidateSelector.findCandidate(candidates, volunteerId);
        String tier = candidate != null && !Strings.isNullOrEmpty(candidate.getTier()) ? candidate.getTier() : fallbackTier;
        String unitId = candidate == null
                ? RepairCandidateSelector.resolveUnitId(volunteerId, candidates)
                : RepairCandidateSelector.resolveInitialRecommendationUnitId(candidate);
        snapshot.volunteerTierById.put(volunteerId, Strings.isNullOrEmpty(tier) ? "未知" : tier);
        if (!Strings.isNullOrEmpty(unitId)) {
            snapshot.volunteerUnitById.put(volunteerId, unitId);
            addDerivedUnit(snapshot, unitId, tier, candidates);
        }
    }

    private static void addExplicitUnit(DryRunPlanSnapshot snapshot,
                                        String unitId,
                                        String fallbackTier,
                                        List<CandidateItemDTO> candidates) {
        addUnit(snapshot, unitId, fallbackTier, candidates);
        if (snapshot != null && !Strings.isNullOrEmpty(unitId)) {
            snapshot.explicitUnitIds.add(unitId);
        }
    }

    private static void addDerivedUnit(DryRunPlanSnapshot snapshot,
                                       String unitId,
                                       String fallbackTier,
                                       List<CandidateItemDTO> candidates) {
        addUnit(snapshot, unitId, fallbackTier, candidates);
    }

    private static void addUnit(DryRunPlanSnapshot snapshot,
                                String unitId,
                                String fallbackTier,
                                List<CandidateItemDTO> candidates) {
        if (snapshot == null || Strings.isNullOrEmpty(unitId)) {
            return;
        }
        String tier = candidates == null ? null : candidates.stream()
                .filter(Objects::nonNull)
                .filter(candidate -> unitId.equals(RepairCandidateSelector.resolveInitialRecommendationUnitId(candidate)))
                .map(CandidateItemDTO::getTier)
                .filter(value -> !Strings.isNullOrEmpty(value))
                .findFirst()
                .orElse(null);
        snapshot.unitTierById.put(unitId, Strings.isNullOrEmpty(tier)
                ? (Strings.isNullOrEmpty(fallbackTier) ? "未知" : fallbackTier) : tier);
    }

    private static void removeVolunteers(DryRunPlanSnapshot snapshot, List<String> volunteerIds) {
        for (String volunteerId : defaultList(volunteerIds)) {
            if (Strings.isNullOrEmpty(volunteerId)) {
                continue;
            }
            snapshot.volunteerTierById.remove(volunteerId);
            snapshot.volunteerUnitById.remove(volunteerId);
        }
        removeUnreferencedDerivedUnits(snapshot);
    }

    private static void removeUnits(DryRunPlanSnapshot snapshot, List<String> unitIds) {
        Set<String> removeUnitIds = defaultList(unitIds).stream()
                .filter(value -> !Strings.isNullOrEmpty(value))
                .collect(Collectors.toCollection(LinkedHashSet::new));
        if (removeUnitIds.isEmpty()) {
            return;
        }
        snapshot.unitTierById.keySet().removeIf(removeUnitIds::contains);
        snapshot.explicitUnitIds.removeIf(removeUnitIds::contains);
        List<String> removeVolunteerIds = snapshot.volunteerUnitById.entrySet().stream()
                .filter(entry -> removeUnitIds.contains(entry.getValue()))
                .map(Map.Entry::getKey)
                .collect(Collectors.toList());
        removeVolunteers(snapshot, removeVolunteerIds);
    }

    private static void ensureUnitsFromVolunteers(DryRunPlanSnapshot snapshot, List<CandidateItemDTO> candidates) {
        for (Map.Entry<String, String> entry : Lists.newArrayList(snapshot.volunteerUnitById.entrySet())) {
            if (!snapshot.unitTierById.containsKey(entry.getValue())) {
                addDerivedUnit(snapshot, entry.getValue(), snapshot.volunteerTierById.get(entry.getKey()), candidates);
            }
        }
    }

    private static void removeUnreferencedDerivedUnits(DryRunPlanSnapshot snapshot) {
        if (snapshot == null) {
            return;
        }
        Set<String> referencedUnitIds = snapshot.volunteerUnitById.values().stream()
                .filter(value -> !Strings.isNullOrEmpty(value))
                .collect(Collectors.toSet());
        snapshot.unitTierById.keySet().removeIf(unitId ->
                !snapshot.explicitUnitIds.contains(unitId) && !referencedUnitIds.contains(unitId));
    }

    private static Map<String, Integer> countTierValues(Iterable<String> tiers) {
        Map<String, Integer> result = new LinkedHashMap<String, Integer>();
        for (String tier : Lists.newArrayList("冲", "稳", "保", "未知")) {
            result.put(tier, 0);
        }
        for (String tier : tiers == null ? Lists.<String>newArrayList() : tiers) {
            String key = Strings.isNullOrEmpty(tier) ? "未知" : tier;
            result.put(key, result.getOrDefault(key, 0) + 1);
        }
        result.entrySet().removeIf(entry -> entry.getValue() == 0);
        return result;
    }

    private static ProbabilityGapMetrics volunteerProbabilityGapMetrics(Set<String> volunteerIds,
                                                                        List<CandidateItemDTO> candidates) {
        return probabilityGapMetrics(Lists.newArrayList(defaultSet(volunteerIds)),
                volunteerId -> admissionRatioForVolunteer(volunteerId, candidates));
    }

    private static ProbabilityGapMetrics unitProbabilityGapMetrics(Set<String> unitIds,
                                                                   List<CandidateItemDTO> candidates) {
        return probabilityGapMetrics(Lists.newArrayList(defaultSet(unitIds)),
                unitId -> admissionRatioForUnit(unitId, candidates));
    }

    private static ProbabilityGapMetrics probabilityGapMetrics(List<String> ids,
                                                               Function<String, Double> ratioResolver) {
        List<Double> ratios = defaultList(ids).stream()
                .map(ratioResolver)
                .filter(Objects::nonNull)
                .sorted(Comparator.naturalOrder())
                .collect(Collectors.toList());
        ProbabilityGapMetrics metrics = new ProbabilityGapMetrics();
        for (int i = 1; i < ratios.size(); i++) {
            double gap = Math.abs(ratios.get(i) - ratios.get(i - 1));
            if (gap > PROBABILITY_GAP_THRESHOLD) {
                metrics.gapCount++;
                metrics.maxGap = Math.max(metrics.maxGap, gap);
            }
        }
        return metrics;
    }

    private static int countVolunteerProbabilityInversions(Set<String> volunteerIds,
                                                           List<CandidateItemDTO> candidates) {
        return countProbabilityInversions(Lists.newArrayList(defaultSet(volunteerIds)),
                volunteerId -> admissionRatioForVolunteer(volunteerId, candidates));
    }

    private static int countUnitProbabilityInversions(Set<String> unitIds,
                                                      List<CandidateItemDTO> candidates) {
        return countProbabilityInversions(Lists.newArrayList(defaultSet(unitIds)),
                unitId -> admissionRatioForUnit(unitId, candidates));
    }

    private static int countProbabilityInversions(List<String> orderedIds,
                                                  Function<String, Double> ratioResolver) {
        int count = 0;
        List<String> ids = defaultList(orderedIds);
        for (int i = 1; i < ids.size(); i++) {
            Double previousRatio = ratioResolver.apply(ids.get(i - 1));
            Double currentRatio = ratioResolver.apply(ids.get(i));
            if (previousRatio != null && currentRatio != null && previousRatio > currentRatio) {
                count++;
            }
        }
        return count;
    }

    private static Double admissionRatioForVolunteer(String volunteerId, List<CandidateItemDTO> candidates) {
        CandidateItemDTO candidate = RepairCandidateSelector.findCandidate(candidates, volunteerId);
        return candidate == null ? null : candidate.getAdmissionRatio();
    }

    private static Double admissionRatioForUnit(String unitId, List<CandidateItemDTO> candidates) {
        CandidateItemDTO candidate = defaultCandidates(candidates).stream()
                .filter(item -> unitId.equals(RepairCandidateSelector.resolveInitialRecommendationUnitId(item)))
                .findFirst()
                .orElse(null);
        if (candidate == null) {
            return null;
        }
        return candidate.getSchoolEnrollRatio() == null ? candidate.getAdmissionRatio() : candidate.getSchoolEnrollRatio();
    }

    private static String schoolGroupKeyForVolunteer(String volunteerId, List<CandidateItemDTO> candidates) {
        CandidateItemDTO candidate = RepairCandidateSelector.findCandidate(candidates, volunteerId);
        if (candidate == null) {
            return Strings.nullToEmpty(volunteerId);
        }
        return firstNonBlank(candidate.getPlanSchoolDataId(), candidate.getSchoolId(), candidate.getSchoolName(), volunteerId);
    }

    private static String unitSchoolGroupKey(String unitId, List<CandidateItemDTO> candidates) {
        CandidateItemDTO candidate = defaultCandidates(candidates).stream()
                .filter(item -> unitId.equals(RepairCandidateSelector.resolveInitialRecommendationUnitId(item)))
                .findFirst()
                .orElse(null);
        return candidate == null ? Strings.nullToEmpty(unitId) : firstNonBlank(candidate.getPlanSchoolDataId(),
                candidate.getSchoolId(), candidate.getSchoolName(), unitId);
    }

    private static <T> List<T> defaultList(List<T> values) {
        return values == null ? Lists.newArrayList() : values;
    }

    private static <T> Set<T> defaultSet(Set<T> values) {
        return values == null ? new LinkedHashSet<T>() : values;
    }

    private static List<CandidateItemDTO> defaultCandidates(List<CandidateItemDTO> candidates) {
        return candidates == null ? Lists.newArrayList() : candidates;
    }

    private static boolean isMajorGroupMode(CandidatePoolStateDTO candidatePoolState) {
        return candidatePoolState != null
                && "majorGroup".equalsIgnoreCase(candidatePoolState.getVolunteerModel());
    }

    private static List<DraftItemDTO> defaultDraftItems(List<DraftItemDTO> items) {
        return items == null ? Lists.newArrayList() : items;
    }

    private static List<OrderedItemDTO> defaultOrderedItems(List<OrderedItemDTO> items) {
        return items == null ? Lists.newArrayList() : items;
    }

    private static List<OrderedUnitDTO> defaultOrderedUnits(List<OrderedUnitDTO> units) {
        return units == null ? Lists.newArrayList() : units;
    }

    private static List<DraftUnitDTO> defaultDraftUnits(List<DraftUnitDTO> units) {
        return units == null ? Lists.newArrayList() : units;
    }

    private static class ActionCount {
        private int addUnitCount;
        private int addVolunteerCount;
        private int removeUnitCount;
        private int removeVolunteerCount;
    }

    private static class ProbabilityGapMetrics {
        private int gapCount;
        private double maxGap;
    }

    private static class DryRunPlanSnapshot {
        private Map<String, String> volunteerTierById = new LinkedHashMap<String, String>();
        private Map<String, String> volunteerUnitById = new LinkedHashMap<String, String>();
        private Map<String, String> unitTierById = new LinkedHashMap<String, String>();
        private final Set<String> explicitUnitIds = new LinkedHashSet<String>();
    }

    private static class ObjectiveValidation {
        private final boolean improved;
        private final String message;

        private ObjectiveValidation(boolean improved, String message) {
            this.improved = improved;
            this.message = message;
        }

        private static ObjectiveValidation of(boolean improved, String message) {
            return new ObjectiveValidation(improved, message);
        }
    }
}
