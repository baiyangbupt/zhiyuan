package com.ytell.zhiyuan.service.biz;

import com.alibaba.fastjson.JSON;
import com.google.common.base.Strings;
import com.ytell.zhiyuan.model.dto.planning.CanonicalPlanningObjectiveSetDTO;
import com.ytell.zhiyuan.model.dto.planning.CoverageRequirementDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanSolverInputDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanSolverResultDTO;
import com.ytell.zhiyuan.model.dto.planning.TierAllocationConstraintDTO;
import com.ytell.zhiyuan.model.dto.planning.TierCountRangeDTO;
import com.ytell.zhiyuan.model.dto.planning.TierCountsDTO;
import org.ojalgo.optimisation.Expression;
import org.ojalgo.optimisation.ExpressionsBasedModel;
import org.ojalgo.optimisation.Optimisation;
import org.ojalgo.optimisation.Variable;

import java.math.BigDecimal;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.stream.Collectors;

final class OjalgoDeterministicPlanSolver implements DeterministicPlanSolver {

    static final String SOLVER_VERSION = "ojalgo-48.4.2-m2";
    static final int MAX_CANDIDATES = 600;
    static final int MAX_COVERAGE_CONSTRAINTS = 64;
    static final long TIME_ABORT_MS = 2_000L;
    private static final int ITERATION_ABORT = 100_000;
    private static final long CHURN_WEIGHT = 1_000_000_000_000L;
    private static final long STRUCTURE_DEVIATION_WEIGHT = 1_000_000L;
    private static final List<String> TIERS = Arrays.asList("sprint", "stable", "protect");

    @Override
    public PlanSolverResultDTO solve(PlanSolverInputDTO input) {
        long started = System.nanoTime();
        CanonicalPlanningObjectiveSetDTO objectives = input == null ? null : input.getObjectiveSet();
        List<PlanSolverInputDTO.CandidateDTO> candidates = canonicalCandidates(
                input == null ? null : input.getCandidates());
        PlanSolverResultDTO result = baseResult(objectives, candidates);

        if (objectives == null || objectives.getTargetCount() == null || objectives.getTargetCount() < 0) {
            return blocked(result, started, "solver_input_invalid", null,
                    "canonical objective set 和非负 targetCount 必须存在。", null, null);
        }
        if (candidates.size() > MAX_CANDIDATES
                || defaultList(objectives.getCoverageConstraints()).size() > MAX_COVERAGE_CONSTRAINTS) {
            return blocked(result, started, "solver_complexity_limit", null,
                    "canonical solver 输入超过 M1 受控复杂度上限。",
                    Math.max(candidates.size(), defaultList(objectives.getCoverageConstraints()).size()),
                    Math.max(MAX_CANDIDATES, MAX_COVERAGE_CONSTRAINTS));
        }
        if (hasInvalidCandidateFacts(candidates)) {
            return blocked(result, started, "candidate_fact_invalid", null,
                    "候选 entityId、stableOrder 或 identity 不完整。", null, null);
        }
        boolean tierFactsRequired = objectives.getTierAllocationConstraint() != null
                || !defaultList(objectives.getOrderingConstraints()).isEmpty();
        if (tierFactsRequired && candidates.stream().anyMatch(candidate -> Strings.isNullOrEmpty(tier(candidate)))) {
            return blocked(result, started, "candidate_tier_invalid", null,
                    "冲稳保配额或同档优先目标需要完整且受支持的档位事实。", null, null);
        }

        int targetCount = objectives.getTargetCount();
        TierAllocationConstraintDTO tierConstraint = canonicalTierConstraint(
                objectives.getTierAllocationConstraint(), targetCount);
        TierCountsDTO historicalAnchor = tierConstraint == null ? null
                : TierStructureProjection.project(currentTierCounts(candidates), targetCount, tierConstraint);
        result.setHistoricalTierAnchor(historicalAnchor);
        result.setInputDigest(inputDigest(objectives, candidates, historicalAnchor));
        List<PlanSolverInputDTO.CandidateDTO> eligible = candidates.stream()
                .filter(candidate -> Boolean.TRUE.equals(candidate.getEligible()))
                .collect(Collectors.toList());
        List<PlanSolverInputDTO.CandidateDTO> locked = candidates.stream()
                .filter(candidate -> Boolean.TRUE.equals(candidate.getLocked()))
                .collect(Collectors.toList());
        if (locked.stream().anyMatch(candidate -> !Boolean.TRUE.equals(candidate.getEligible()))
                || locked.size() > targetCount) {
            return blocked(result, started, "locked_conflict", null,
                    "锁定项目与 eligibility 或目标总数冲突。", targetCount, locked.size());
        }
        if (eligible.size() < targetCount) {
            return blocked(result, started, "candidate_shortage", "selection_target",
                    "符合硬要求的候选不足，无法达到目标总数。", targetCount, eligible.size());
        }
        PlanSolverResultDTO precheck = precheckObjectiveCapacity(
                result, objectives, tierConstraint, eligible, locked, started);
        if (precheck != null) {
            return precheck;
        }

        ExpressionsBasedModel model = new ExpressionsBasedModel();
        model.options.time_abort = TIME_ABORT_MS;
        model.options.iterations_abort = ITERATION_ABORT;
        List<Variable> variables = new ArrayList<Variable>();
        for (int index = 0; index < candidates.size(); index++) {
            PlanSolverInputDTO.CandidateDTO candidate = candidates.get(index);
            long stableWeight = Math.max(0, candidate.getStableOrder()) + 1L;
            long weight = Boolean.TRUE.equals(candidate.getCurrent())
                    ? -CHURN_WEIGHT + stableWeight : CHURN_WEIGHT + stableWeight;
            Variable variable = Variable.makeBinary("entity_" + index)
                    .weight(BigDecimal.valueOf(weight));
            if (!Boolean.TRUE.equals(candidate.getEligible())) {
                variable.upper(0);
            }
            if (Boolean.TRUE.equals(candidate.getLocked())) {
                variable.lower(1).upper(1);
            }
            model.addVariable(variable);
            variables.add(variable);
        }

        Expression target = model.addExpression("selection_target").level(targetCount);
        for (Variable variable : variables) {
            target.set(variable, 1);
        }
        List<CoverageRequirementDTO> coverage = defaultList(objectives.getCoverageConstraints());
        for (int objectiveIndex = 0; objectiveIndex < coverage.size(); objectiveIndex++) {
            CoverageRequirementDTO objective = coverage.get(objectiveIndex);
            String objectiveId = coverageId(objectiveIndex);
            Expression expression = model.addExpression(objectiveId)
                    .lower(CoverageRequirementSupport.minCount(objective));
            for (int candidateIndex = 0; candidateIndex < candidates.size(); candidateIndex++) {
                if (matchesCoverage(candidates.get(candidateIndex), objectiveId)) {
                    expression.set(variables.get(candidateIndex), 1);
                }
            }
        }
        if (tierConstraint != null) {
            addTierExpression(model, variables, candidates, "sprint", tierConstraint.getSprint());
            addTierExpression(model, variables, candidates, "stable", tierConstraint.getStable());
            addTierExpression(model, variables, candidates, "protect", tierConstraint.getProtect());
            addStructureDeviation(model, variables, candidates, historicalAnchor, targetCount);
        }

        Optimisation.Result solved = model.minimise();
        result.setSolverState(solved.getState().toString());
        if (!solved.getState().isFeasible()) {
            String reason = solved.getState() == Optimisation.State.INFEASIBLE
                    ? tierConstraint != null ? exactAllocation(tierConstraint)
                    ? "tier_exact_infeasible" : "tier_range_infeasible"
                    : coverage.isEmpty() ? "objective_set_infeasible" : "coverage_infeasible"
                    : "solver_complexity_limit";
            return blocked(result, started, reason, null,
                    "canonical objective set 在当前候选事实中不可行，solverState=" + solved.getState(),
                    targetCount, eligible.size());
        }

        List<PlanSolverInputDTO.CandidateDTO> selected = new ArrayList<PlanSolverInputDTO.CandidateDTO>();
        for (int index = 0; index < candidates.size(); index++) {
            if (solved.doubleValue(index) > 0.5D) {
                selected.add(candidates.get(index));
            }
        }
        populateSelection(result, candidates, selected);
        List<PlanSolverInputDTO.CandidateDTO> ordered = applyPriorityOrdering(selected,
                !defaultList(objectives.getOrderingConstraints()).isEmpty());
        if (hasPinnedOrderingConflict(selected, ordered)) {
            return blocked(result, started, "pinned_conflict", "priority:0",
                    "同档优先排序会改变 pinned 项目所在档位的位置。", null, null);
        }
        result.setOrderedEntityIds(ids(ordered));
        result.setResolvedTierCounts(tierConstraint == null ? null : tierCounts(selected));
        populateObjectiveResults(result, objectives, selected, ordered);
        boolean selectionChanged = !result.getSelectedEntityIds().equals(ids(candidates.stream()
                .filter(candidate -> Boolean.TRUE.equals(candidate.getCurrent()))
                .collect(Collectors.toList())));
        boolean orderChanged = !result.getOrderedEntityIds().equals(result.getSelectedEntityIds());
        result.setStatus(selectionChanged || orderChanged ? "ready" : "no_change");
        result.setDurationMs(elapsedMillis(started));
        return result;
    }

    private PlanSolverResultDTO precheckObjectiveCapacity(PlanSolverResultDTO result,
                                                           CanonicalPlanningObjectiveSetDTO objectives,
                                                           TierAllocationConstraintDTO tierConstraint,
                                                           List<PlanSolverInputDTO.CandidateDTO> eligible,
                                                           List<PlanSolverInputDTO.CandidateDTO> locked,
                                                           long started) {
        List<CoverageRequirementDTO> coverage = defaultList(objectives.getCoverageConstraints());
        for (int index = 0; index < coverage.size(); index++) {
            int required = CoverageRequirementSupport.minCount(coverage.get(index));
            String objectiveId = coverageId(index);
            int available = countCoverage(eligible, objectiveId);
            if (required > objectives.getTargetCount() || available < required) {
                return blocked(result, started, "coverage_infeasible", objectiveId,
                        "coverage 最低数量超过目标总数或可用候选数量。", required, available);
            }
            int lockedMatches = countCoverage(locked, objectiveId);
            int unlockedMatches = countCoverage(eligible.stream()
                    .filter(candidate -> !Boolean.TRUE.equals(candidate.getLocked()))
                    .collect(Collectors.toList()), objectiveId);
            int remainingSlots = Math.max(0, objectives.getTargetCount() - locked.size());
            int reachableMatches = lockedMatches + Math.min(remainingSlots, unlockedMatches);
            if (reachableMatches < required) {
                return blocked(result, started, "locked_conflict", objectiveId,
                        "锁定项目占用目标槽位，无法达到 coverage 最低数量。", required, reachableMatches);
            }
        }
        if (tierConstraint == null) {
            return null;
        }
        boolean exact = exactAllocation(tierConstraint);
        int reachableCapacity = 0;
        int requiredAdditions = 0;
        for (String tier : TIERS) {
            TierCountRangeDTO bound = tierBound(tierConstraint, tier);
            int minimum = bound.getMinCount();
            int maximum = bound.getMaxCount();
            int available = (int) eligible.stream().filter(candidate -> tier.equals(tier(candidate))).count();
            int fixed = (int) locked.stream().filter(candidate -> tier.equals(tier(candidate))).count();
            if (available < minimum) {
                return blocked(result, started, exact ? "tier_exact_infeasible" : "tier_min_infeasible",
                        "tier:" + tier, "指定档位的可用候选不足，无法满足最低数量。",
                        minimum, available);
            }
            if (fixed > maximum) {
                return blocked(result, started, "locked_conflict", "tier:" + tier,
                        "锁定项目数量超过指定档位最高数量。", maximum, fixed);
            }
            reachableCapacity += Math.min(available, maximum);
            requiredAdditions += Math.max(0, minimum - fixed);
        }
        if (reachableCapacity < objectives.getTargetCount()) {
            return blocked(result, started, exact ? "tier_exact_infeasible" : "tier_max_infeasible",
                    "tier_allocation", "各档位最高可达数量不足以容纳目标总数。",
                    objectives.getTargetCount(), reachableCapacity);
        }
        int remainingSlots = objectives.getTargetCount() - locked.size();
        if (requiredAdditions > remainingSlots) {
            return blocked(result, started, "locked_conflict", "tier_allocation",
                    "锁定项目占用目标槽位，无法满足各档位最低数量。",
                    requiredAdditions, remainingSlots);
        }
        return null;
    }

    private void addTierExpression(ExpressionsBasedModel model,
                                   List<Variable> variables,
                                   List<PlanSolverInputDTO.CandidateDTO> candidates,
                                   String tier,
                                   TierCountRangeDTO bound) {
        Expression expression = model.addExpression("tier:" + tier);
        if (bound.getMinCount() != null) {
            expression.lower(bound.getMinCount());
        }
        if (bound.getMaxCount() != null) {
            expression.upper(bound.getMaxCount());
        }
        for (int index = 0; index < candidates.size(); index++) {
            if (tier.equals(tier(candidates.get(index)))) {
                expression.set(variables.get(index), 1);
            }
        }
    }

    private void addStructureDeviation(ExpressionsBasedModel model,
                                       List<Variable> variables,
                                       List<PlanSolverInputDTO.CandidateDTO> candidates,
                                       TierCountsDTO anchor,
                                       int targetCount) {
        if (anchor == null) {
            return;
        }
        for (String tier : TIERS) {
            Variable positive = Variable.make("tier_deviation_positive_" + tier)
                    .integer(true).lower(0).upper(targetCount)
                    .weight(BigDecimal.valueOf(STRUCTURE_DEVIATION_WEIGHT));
            Variable negative = Variable.make("tier_deviation_negative_" + tier)
                    .integer(true).lower(0).upper(targetCount)
                    .weight(BigDecimal.valueOf(STRUCTURE_DEVIATION_WEIGHT));
            model.addVariable(positive);
            model.addVariable(negative);
            Expression expression = model.addExpression("tier_anchor:" + tier)
                    .level(tierCount(anchor, tier));
            for (int index = 0; index < candidates.size(); index++) {
                if (tier.equals(tier(candidates.get(index)))) {
                    expression.set(variables.get(index), 1);
                }
            }
            expression.set(positive, -1);
            expression.set(negative, 1);
        }
    }

    private void populateSelection(PlanSolverResultDTO result,
                                   List<PlanSolverInputDTO.CandidateDTO> candidates,
                                   List<PlanSolverInputDTO.CandidateDTO> selected) {
        Set<String> selectedIds = new LinkedHashSet<String>(ids(selected));
        result.setSelectedEntityIds(ids(selected));
        result.setRemoveEntityIds(candidates.stream()
                .filter(candidate -> Boolean.TRUE.equals(candidate.getCurrent()))
                .map(PlanSolverInputDTO.CandidateDTO::getEntityId)
                .filter(entityId -> !selectedIds.contains(entityId))
                .collect(Collectors.toList()));
        result.setAddEntityIds(selected.stream()
                .filter(candidate -> !Boolean.TRUE.equals(candidate.getCurrent()))
                .map(PlanSolverInputDTO.CandidateDTO::getEntityId)
                .collect(Collectors.toList()));
    }

    private List<PlanSolverInputDTO.CandidateDTO> applyPriorityOrdering(
            List<PlanSolverInputDTO.CandidateDTO> selected,
            boolean priorityEnabled) {
        List<PlanSolverInputDTO.CandidateDTO> result = new ArrayList<PlanSolverInputDTO.CandidateDTO>(selected);
        if (!priorityEnabled) {
            return result;
        }
        Set<String> tiers = selected.stream().map(OjalgoDeterministicPlanSolver::tier)
                .collect(Collectors.toCollection(LinkedHashSet::new));
        for (String currentTier : tiers) {
            List<Integer> indexes = new ArrayList<Integer>();
            List<PlanSolverInputDTO.CandidateDTO> matching = new ArrayList<PlanSolverInputDTO.CandidateDTO>();
            List<PlanSolverInputDTO.CandidateDTO> other = new ArrayList<PlanSolverInputDTO.CandidateDTO>();
            for (int index = 0; index < selected.size(); index++) {
                PlanSolverInputDTO.CandidateDTO candidate = selected.get(index);
                if (!currentTier.equals(tier(candidate))) {
                    continue;
                }
                indexes.add(index);
                (Boolean.TRUE.equals(candidate.getPriorityMatched()) ? matching : other).add(candidate);
            }
            matching.addAll(other);
            for (int index = 0; index < indexes.size(); index++) {
                result.set(indexes.get(index), matching.get(index));
            }
        }
        return result;
    }

    private boolean hasPinnedOrderingConflict(List<PlanSolverInputDTO.CandidateDTO> before,
                                              List<PlanSolverInputDTO.CandidateDTO> after) {
        Map<String, Integer> beforePositions = positions(before);
        Map<String, Integer> afterPositions = positions(after);
        Set<String> changedTiers = before.stream()
                .filter(candidate -> !beforePositions.get(candidate.getEntityId())
                        .equals(afterPositions.get(candidate.getEntityId())))
                .map(OjalgoDeterministicPlanSolver::tier)
                .collect(Collectors.toSet());
        return before.stream().anyMatch(candidate -> Boolean.TRUE.equals(candidate.getPinned())
                && changedTiers.contains(tier(candidate)));
    }

    private Map<String, Integer> positions(List<PlanSolverInputDTO.CandidateDTO> values) {
        Map<String, Integer> result = new LinkedHashMap<String, Integer>();
        for (int index = 0; index < values.size(); index++) {
            result.put(values.get(index).getEntityId(), index);
        }
        return result;
    }

    private void populateObjectiveResults(PlanSolverResultDTO result,
                                          CanonicalPlanningObjectiveSetDTO objectives,
                                          List<PlanSolverInputDTO.CandidateDTO> selected,
                                          List<PlanSolverInputDTO.CandidateDTO> ordered) {
        result.getObjectiveResults().add(objectiveResult(
                "selection_target", "selection_target", objectives.getTargetCount(), objectives.getTargetCount(),
                selected.size()));
        for (int index = 0; index < defaultList(objectives.getCoverageConstraints()).size(); index++) {
            int required = CoverageRequirementSupport.minCount(objectives.getCoverageConstraints().get(index));
            result.getObjectiveResults().add(objectiveResult(coverageId(index), "coverage", required, null,
                    countCoverage(selected, coverageId(index))));
        }
        TierAllocationConstraintDTO constraint = canonicalTierConstraint(
                objectives.getTierAllocationConstraint(), objectives.getTargetCount());
        if (constraint != null) {
            String objectiveType = exactAllocation(constraint) ? "tier_exact" : "tier_range";
            for (String tier : TIERS) {
                TierCountRangeDTO bound = tierBound(constraint, tier);
                int actual = (int) selected.stream().filter(candidate -> tier.equals(tier(candidate))).count();
                result.getObjectiveResults().add(objectiveResult(
                        "tier:" + tier, objectiveType,
                        bound.getMinCount(), bound.getMaxCount(), actual));
            }
        }
        if (!defaultList(objectives.getOrderingConstraints()).isEmpty()) {
            int inversionCount = priorityInversions(ordered);
            result.getObjectiveResults().add(objectiveResult(
                    "priority:0", "priority_within_tier", 0, 0, inversionCount));
        }
    }

    private int priorityInversions(List<PlanSolverInputDTO.CandidateDTO> ordered) {
        Map<String, Integer> unmatched = new LinkedHashMap<String, Integer>();
        int result = 0;
        for (PlanSolverInputDTO.CandidateDTO candidate : ordered) {
            String tier = tier(candidate);
            if (Boolean.TRUE.equals(candidate.getPriorityMatched())) {
                result += unmatched.getOrDefault(tier, 0);
            } else {
                unmatched.put(tier, unmatched.getOrDefault(tier, 0) + 1);
            }
        }
        return result;
    }

    private PlanSolverResultDTO.ObjectiveResultDTO objectiveResult(String id,
                                                                   String type,
                                                                   Integer min,
                                                                   Integer max,
                                                                   int actual) {
        PlanSolverResultDTO.ObjectiveResultDTO result = new PlanSolverResultDTO.ObjectiveResultDTO();
        result.setObjectiveId(id);
        result.setObjectiveType(type);
        result.setRequiredMin(min);
        result.setRequiredMax(max);
        result.setActualCount(actual);
        result.setSatisfied((min == null || actual >= min) && (max == null || actual <= max));
        return result;
    }

    private PlanSolverResultDTO baseResult(CanonicalPlanningObjectiveSetDTO objectives,
                                           List<PlanSolverInputDTO.CandidateDTO> candidates) {
        PlanSolverResultDTO result = new PlanSolverResultDTO();
        result.setSolverVersion(SOLVER_VERSION);
        result.setCandidateCount(candidates.size());
        int coverageCount = objectives == null ? 0 : defaultList(objectives.getCoverageConstraints()).size();
        int tierCount = objectives != null && objectives.getTierAllocationConstraint() != null ? 3 : 0;
        int priorityCount = objectives == null ? 0 : defaultList(objectives.getOrderingConstraints()).size();
        result.setConstraintCount(1 + coverageCount + tierCount + priorityCount);
        result.setInputDigest(inputDigest(objectives, candidates, null));
        return result;
    }

    private PlanSolverResultDTO blocked(PlanSolverResultDTO result,
                                        long started,
                                        String reasonCode,
                                        String objectiveId,
                                        String message,
                                        Integer required,
                                        Integer available) {
        result.setStatus("blocked");
        PlanSolverResultDTO.DiagnosticDTO diagnostic = new PlanSolverResultDTO.DiagnosticDTO();
        diagnostic.setReasonCode(reasonCode);
        diagnostic.setObjectiveId(objectiveId);
        diagnostic.setMessage(message);
        diagnostic.setRequiredCount(required);
        diagnostic.setAvailableCount(available);
        result.getDiagnostics().add(diagnostic);
        result.setDurationMs(elapsedMillis(started));
        return result;
    }

    private boolean hasInvalidCandidateFacts(List<PlanSolverInputDTO.CandidateDTO> candidates) {
        Set<String> ids = new LinkedHashSet<String>();
        for (PlanSolverInputDTO.CandidateDTO candidate : candidates) {
            if (candidate == null || Strings.isNullOrEmpty(Strings.nullToEmpty(candidate.getEntityId()).trim())
                    || candidate.getStableOrder() == null || candidate.getStableOrder() < 0
                    || !ids.add(candidate.getEntityId())) {
                return true;
            }
        }
        return false;
    }

    private List<PlanSolverInputDTO.CandidateDTO> canonicalCandidates(
            List<PlanSolverInputDTO.CandidateDTO> source) {
        List<PlanSolverInputDTO.CandidateDTO> result = new ArrayList<PlanSolverInputDTO.CandidateDTO>(
                defaultList(source));
        Comparator<PlanSolverInputDTO.CandidateDTO> comparator = Comparator
                .comparing(PlanSolverInputDTO.CandidateDTO::getStableOrder,
                        Comparator.nullsLast(Integer::compareTo))
                .thenComparing(PlanSolverInputDTO.CandidateDTO::getEntityId,
                        Comparator.nullsLast(String::compareTo));
        result.sort(Comparator.nullsLast(comparator));
        return result;
    }

    private String inputDigest(CanonicalPlanningObjectiveSetDTO objectives,
                               List<PlanSolverInputDTO.CandidateDTO> candidates,
                               TierCountsDTO historicalAnchor) {
        Map<String, Object> payload = new LinkedHashMap<String, Object>();
        payload.put("objectiveDigest", objectives == null ? null : objectives.getObjectiveDigest());
        payload.put("countMode", objectives == null ? null : objectives.getCountMode());
        payload.put("targetCount", objectives == null ? null : objectives.getTargetCount());
        payload.put("historicalTierAnchor", historicalAnchor);
        List<Map<String, Object>> facts = new ArrayList<Map<String, Object>>();
        for (PlanSolverInputDTO.CandidateDTO candidate : candidates) {
            Map<String, Object> fact = new LinkedHashMap<String, Object>();
            fact.put("entityId", candidate == null ? null : candidate.getEntityId());
            fact.put("volunteerIds", sortedValues(candidate == null ? null : candidate.getVolunteerIds()));
            fact.put("stableOrder", candidate == null ? null : candidate.getStableOrder());
            fact.put("current", candidate == null ? null : candidate.getCurrent());
            fact.put("locked", candidate == null ? null : candidate.getLocked());
            fact.put("pinned", candidate == null ? null : candidate.getPinned());
            fact.put("eligible", candidate == null ? null : candidate.getEligible());
            fact.put("tier", candidate == null ? null : tier(candidate));
            fact.put("coverageObjectiveIds", sortedValues(
                    candidate == null ? null : candidate.getCoverageObjectiveIds()));
            fact.put("priorityMatched", candidate == null ? null : candidate.getPriorityMatched());
            facts.add(fact);
        }
        payload.put("candidates", facts);
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            return toHex(digest.digest(JSON.toJSONString(payload).getBytes(StandardCharsets.UTF_8)));
        } catch (NoSuchAlgorithmException ex) {
            throw new IllegalStateException("SHA-256 is unavailable", ex);
        }
    }

    private static boolean matchesCoverage(PlanSolverInputDTO.CandidateDTO candidate, String objectiveId) {
        return defaultList(candidate == null ? null : candidate.getCoverageObjectiveIds()).contains(objectiveId);
    }

    private static int countCoverage(List<PlanSolverInputDTO.CandidateDTO> candidates, String objectiveId) {
        return (int) candidates.stream().filter(candidate -> matchesCoverage(candidate, objectiveId)).count();
    }

    private static int tierCount(TierCountsDTO counts, String tier) {
        if ("sprint".equals(tier)) {
            return counts.getSprintCount() == null ? 0 : counts.getSprintCount();
        }
        if ("stable".equals(tier)) {
            return counts.getStableCount() == null ? 0 : counts.getStableCount();
        }
        return counts.getProtectCount() == null ? 0 : counts.getProtectCount();
    }

    private static TierCountsDTO currentTierCounts(List<PlanSolverInputDTO.CandidateDTO> candidates) {
        return tierCounts(candidates.stream()
                .filter(candidate -> Boolean.TRUE.equals(candidate.getCurrent()))
                .collect(Collectors.toList()));
    }

    private static TierCountsDTO tierCounts(List<PlanSolverInputDTO.CandidateDTO> candidates) {
        TierCountsDTO result = new TierCountsDTO();
        result.setSprintCount(countTier(candidates, "sprint"));
        result.setStableCount(countTier(candidates, "stable"));
        result.setProtectCount(countTier(candidates, "protect"));
        return result;
    }

    private static int countTier(List<PlanSolverInputDTO.CandidateDTO> candidates, String tier) {
        return (int) candidates.stream().filter(candidate -> tier.equals(tier(candidate))).count();
    }

    private static TierAllocationConstraintDTO canonicalTierConstraint(
            TierAllocationConstraintDTO source,
            int targetCount) {
        if (source == null) {
            return null;
        }
        TierAllocationConstraintDTO result = new TierAllocationConstraintDTO();
        result.setType(source.getType());
        result.setSourceType(Strings.isNullOrEmpty(source.getSourceType())
                ? source.getType() : source.getSourceType());
        result.setSprint(effectiveBound(source.getSprint(), source.getSprintCount(), targetCount));
        result.setStable(effectiveBound(source.getStable(), source.getStableCount(), targetCount));
        result.setProtect(effectiveBound(source.getProtect(), source.getProtectCount(), targetCount));
        return result;
    }

    private static TierCountRangeDTO effectiveBound(TierCountRangeDTO source,
                                                    Integer exactCount,
                                                    int targetCount) {
        TierCountRangeDTO result = new TierCountRangeDTO();
        if (source == null && exactCount != null) {
            result.setMinCount(exactCount);
            result.setMaxCount(exactCount);
            return result;
        }
        result.setMinCount(source == null || source.getMinCount() == null ? 0 : source.getMinCount());
        result.setMaxCount(source == null || source.getMaxCount() == null
                ? targetCount : source.getMaxCount());
        return result;
    }

    private static TierCountRangeDTO tierBound(TierAllocationConstraintDTO constraint, String tier) {
        if ("sprint".equals(tier)) {
            return constraint.getSprint();
        }
        if ("stable".equals(tier)) {
            return constraint.getStable();
        }
        return constraint.getProtect();
    }

    private static boolean exactAllocation(TierAllocationConstraintDTO constraint) {
        String sourceType = Strings.nullToEmpty(constraint == null ? null : constraint.getSourceType())
                .trim().toLowerCase();
        return TierAllocationSupport.TYPE_EXACT_COUNTS.equals(sourceType)
                || TierAllocationSupport.TYPE_RATIOS.equals(sourceType);
    }

    private static String tier(PlanSolverInputDTO.CandidateDTO candidate) {
        return TierQuotaSupport.canonicalTierKey(candidate == null ? null : candidate.getTier());
    }

    private static String coverageId(int index) {
        return "coverage:" + index;
    }

    private static List<String> ids(List<PlanSolverInputDTO.CandidateDTO> candidates) {
        return candidates.stream().map(PlanSolverInputDTO.CandidateDTO::getEntityId).collect(Collectors.toList());
    }

    private static List<String> sortedValues(List<String> values) {
        List<String> result = new ArrayList<String>(new LinkedHashSet<String>(defaultList(values)));
        result.sort(Comparator.nullsLast(String::compareTo));
        return result;
    }

    private static String toHex(byte[] values) {
        StringBuilder result = new StringBuilder(values.length * 2);
        for (byte value : values) {
            result.append(String.format("%02x", value & 0xff));
        }
        return result.toString();
    }

    private static long elapsedMillis(long started) {
        return Math.max(0L, (System.nanoTime() - started) / 1_000_000L);
    }

    private static <T> List<T> defaultList(List<T> values) {
        return values == null ? new ArrayList<T>() : values;
    }
}
