package com.ytell.zhiyuan.service.biz;

import com.ytell.zhiyuan.common.exception.BusinessException;
import com.ytell.zhiyuan.model.dto.planning.CandidateFactDTO;
import com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO;
import com.ytell.zhiyuan.model.dto.planning.CanonicalPlanningObjectiveSetDTO;
import com.ytell.zhiyuan.model.dto.planning.CoverageRequirementDTO;
import com.ytell.zhiyuan.model.dto.planning.DraftItemDTO;
import com.ytell.zhiyuan.model.dto.planning.DraftUnitDTO;
import com.ytell.zhiyuan.model.dto.planning.FixProposalDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedUnitDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanSolverResultDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningUnitMajorDTO;
import com.ytell.zhiyuan.model.dto.planning.TierAllocationConstraintDTO;
import com.ytell.zhiyuan.model.dto.planning.TierCountRangeDTO;

import java.util.ArrayList;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import java.util.stream.Collectors;

final class ReviewSolverContract {
    private ReviewSolverContract() {
    }

    static void validateObjectives(PlanningStateDTO state, Map<String, Object> pending, FixProposalDTO proposal) {
        PlanSolverResultDTO frozen = proposal.getSolverResult();
        if (frozen == null) {
            if (!isDirectInversion(proposal)) {
                throw new BusinessException(409, "review_fix_not_confirmable");
            }
            return;
        }
        String canonical = PlanningObjectiveCompiler.compileConfirmed(state).getObjectiveDigest();
        if (empty(proposal.getCanonicalObjectiveDigest())
                || !Objects.equals(canonical, proposal.getCanonicalObjectiveDigest())
                || !Objects.equals(canonical, pending.get("canonicalObjectiveDigest"))
                || !Objects.equals(proposal.getSolverObjectiveDigest(), frozen.getSolverObjectiveDigest())
                || !Objects.equals(proposal.getSolverObjectiveDigest(), pending.get("solverObjectiveDigest"))
                || !Objects.equals(proposal.getSolverVersion(), frozen.getSolverVersion())
                || !Objects.equals(proposal.getSolverInputDigest(), frozen.getInputDigest())
                || empty(proposal.getHardObjectiveVersion()) || empty(frozen.getHardObjectiveVersion())
                || !Objects.equals(proposal.getHardObjectiveVersion(), pending.get("hardObjectiveVersion"))
                || !RepairProposalApplyPolicy.hardObjectiveMajor(proposal.getHardObjectiveVersion()).equals(
                        RepairProposalApplyPolicy.hardObjectiveMajor(frozen.getHardObjectiveVersion()))
                || !RepairProposalApplyPolicy.hardObjectiveMajor(frozen.getHardObjectiveVersion()).equals(
                        RepairProposalApplyPolicy.hardObjectiveMajor(StagedDeterministicPlanSolver.HARD_OBJECTIVE_VERSION))) {
            throw new BusinessException(409, "review_fix_objectives_changed");
        }
    }

    static void validateFinalState(PlanningStateDTO state, List<CandidateItemDTO> candidates, FixProposalDTO proposal) {
        if (proposal.getSolverResult() == null) {
            if (!isDirectInversion(proposal)) {
                throw new BusinessException(PendingPlanningCommandBizService.POSTCONDITION_FAILED_CODE,
                        "review_fix_postcondition_failed");
            }
            return;
        }
        try {
            verifyFinalState(state, candidates, proposal.getSolverResult());
        } catch (RuntimeException invalid) {
            throw new BusinessException(PendingPlanningCommandBizService.POSTCONDITION_FAILED_CODE,
                    "review_fix_postcondition_failed");
        }
    }

    private static void verifyFinalState(PlanningStateDTO state, List<CandidateItemDTO> candidates,
                                         PlanSolverResultDTO frozen) {
        CanonicalPlanningRuntime.verifyFrozenState(state, frozen);
        CanonicalPlanningObjectiveSetDTO objectives = PlanningObjectiveCompiler.compileConfirmed(state);
        Set<String> ids = new LinkedHashSet<String>(frozen.getSelectedEntityIds());
        List<String> workingIds = "unit".equals(objectives.getCountMode())
                ? state.getWorkingPlanState().getUnits().stream().map(DraftUnitDTO::getUnitId)
                        .collect(Collectors.toList())
                : state.getWorkingPlanState().getItems().stream().map(DraftItemDTO::getVolunteerId)
                        .collect(Collectors.toList());
        require(workingIds.size() == ids.size() && ids.equals(new LinkedHashSet<>(workingIds)));
        if ("unit".equals(objectives.getCountMode())) {
            verifyWorkingMajorSelection(state);
        }
        List<CandidateFactDTO> selected = new ArrayList<CandidateFactDTO>();
        for (CandidateFactDTO fact : CandidateSnapshotBuilder.build(
                state, candidates, CandidateSnapshotBuilder.CurrentSource.ORDERED_FIRST).getFacts()) {
            if (ids.contains(fact.getEntityId())) {
                selected.add(fact);
            }
        }
        require(selected.size() == ids.size());
        Map<String, PlanSolverResultDTO.ObjectiveResultDTO> actual = new LinkedHashMap<>();
        int target = objectives.getTargetCount() == null ? ids.size() : objectives.getTargetCount();
        add(actual, "selection_target", "selection_target", target, target, selected.size());
        List<CoverageRequirementDTO> coverage = objectives.getCoverageConstraints() == null
                ? Collections.emptyList() : objectives.getCoverageConstraints();
        for (int index = 0; index < coverage.size(); index++) {
            CoverageRequirementDTO requirement = coverage.get(index);
            int count = 0;
            for (CandidateFactDTO fact : selected) {
                if (InitialContentPolicySupport.candidatesForSelection(fact).stream()
                        .anyMatch(candidate -> CoverageRequirementSupport.matches(candidate, requirement))) {
                    count++;
                }
            }
            add(actual, "coverage:" + index, "coverage", CoverageRequirementSupport.minCount(requirement), null, count);
        }
        TierAllocationConstraintDTO tiers = objectives.getTierAllocationConstraint();
        if (tiers != null) {
            String source = empty(tiers.getSourceType()) ? tiers.getType() : tiers.getSourceType();
            String type = TierAllocationSupport.TYPE_EXACT_COUNTS.equals(source)
                    || TierAllocationSupport.TYPE_RATIOS.equals(source) ? "tier_exact" : "tier_range";
            addTier(actual, "sprint", type, tiers.getSprint(), tiers.getSprintCount(), target, selected);
            addTier(actual, "stable", type, tiers.getStable(), tiers.getStableCount(), target, selected);
            addTier(actual, "protect", type, tiers.getProtect(), tiers.getProtectCount(), target, selected);
        }
        require(frozen.getObjectiveResults() != null && frozen.getObjectiveResults().size() == actual.size());
        Set<String> seen = new LinkedHashSet<>();
        for (PlanSolverResultDTO.ObjectiveResultDTO expected : frozen.getObjectiveResults()) {
            require(expected != null && seen.add(expected.getObjectiveId()));
            PlanSolverResultDTO.ObjectiveResultDTO observed = actual.get(expected.getObjectiveId());
            require(observed != null
                    && Objects.equals(observed.getObjectiveType(), expected.getObjectiveType())
                    && Objects.equals(observed.getRequiredMin(), expected.getRequiredMin())
                    && Objects.equals(observed.getRequiredMax(), expected.getRequiredMax())
                    && Objects.equals(observed.getActualCount(), expected.getActualCount())
                    && Boolean.TRUE.equals(observed.getSatisfied()) && Boolean.TRUE.equals(expected.getSatisfied()));
        }
    }

    private static void addTier(Map<String, PlanSolverResultDTO.ObjectiveResultDTO> results, String tier,
                                String type, TierCountRangeDTO bounds, Integer exact, int target,
                                List<CandidateFactDTO> selected) {
        Integer min = bounds == null && exact != null ? exact
                : bounds == null || bounds.getMinCount() == null ? 0 : bounds.getMinCount();
        Integer max = bounds == null && exact != null ? exact
                : bounds == null || bounds.getMaxCount() == null ? target : bounds.getMaxCount();
        int count = (int) selected.stream().filter(fact -> tier.equals(fact.getTier())).count();
        add(results, "tier:" + tier, type, min, max, count);
    }

    private static void add(Map<String, PlanSolverResultDTO.ObjectiveResultDTO> results, String id,
                            String type, Integer min, Integer max, int count) {
        PlanSolverResultDTO.ObjectiveResultDTO result = new PlanSolverResultDTO.ObjectiveResultDTO();
        result.setObjectiveId(id);
        result.setObjectiveType(type);
        result.setRequiredMin(min);
        result.setRequiredMax(max);
        result.setActualCount(count);
        result.setSatisfied((min == null || count >= min) && (max == null || count <= max));
        results.put(id, result);
    }

    private static void verifyWorkingMajorSelection(PlanningStateDTO state) {
        Map<String, List<String>> orderedMajors = new LinkedHashMap<>();
        for (OrderedUnitDTO unit : state.getOrderedPlanState().getUnits()) {
            orderedMajors.put(unit.getUnitId(), unit.getMajorItems().stream()
                    .map(PlanningUnitMajorDTO::getVolunteerId).collect(Collectors.toList()));
        }
        List<String> flattened = new ArrayList<>();
        for (DraftUnitDTO unit : state.getWorkingPlanState().getUnits()) {
            List<String> actual = unit.getMajorItems().stream()
                    .map(PlanningUnitMajorDTO::getVolunteerId).collect(Collectors.toList());
            require(actual.equals(orderedMajors.get(unit.getUnitId())));
            flattened.addAll(actual);
        }
        require(flattened.equals(state.getWorkingPlanState().getItems().stream()
                .map(DraftItemDTO::getVolunteerId).collect(Collectors.toList())));
    }

    private static boolean isDirectInversion(FixProposalDTO proposal) {
        return "probability_inversion".equals(proposal.getFindingCode())
                && RepairProposalTaxonomy.Strategy.SORT_BY_PROBABILITY.equals(
                        RepairProposalTaxonomy.normalizeStrategy(proposal.getStrategy()));
    }

    private static boolean empty(String value) {
        return value == null || value.trim().isEmpty();
    }

    private static void require(boolean condition) {
        if (!condition) {
            throw new IllegalStateException("review solver result mismatch");
        }
    }
}
