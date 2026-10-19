package com.ytell.zhiyuan.service.biz;

import com.alibaba.fastjson.JSON;
import com.google.common.base.Strings;
import com.google.common.collect.Lists;
import com.ytell.zhiyuan.common.exception.BusinessException;
import com.ytell.zhiyuan.model.dto.planning.CandidateFactDTO;
import com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO;
import com.ytell.zhiyuan.model.dto.planning.CandidateSnapshotDTO;
import com.ytell.zhiyuan.model.dto.planning.CanonicalPlanningObjectiveSetDTO;
import com.ytell.zhiyuan.model.dto.planning.MutationPolicyDTO;
import com.ytell.zhiyuan.model.dto.planning.DraftItemDTO;
import com.ytell.zhiyuan.model.dto.planning.DraftPlanStateDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedItemDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedUnitDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanSolverResultDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningUnitMajorDTO;
import com.ytell.zhiyuan.model.dto.planning.PriorityRuleDTO;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.stream.Collectors;

final class CanonicalPlanningRuntime {

    private static final StagedDeterministicPlanSolver STAGED_SOLVER = new StagedDeterministicPlanSolver();
    private static final Logger LOG = LoggerFactory.getLogger(CanonicalPlanningRuntime.class);

    private CanonicalPlanningRuntime() {
    }

    static boolean hasSelectionObjectives(PlanningStateDTO state) {
        CanonicalPlanningObjectiveSetDTO objectives = PlanningObjectiveCompiler.compileConfirmed(state);
        return hasSelectionObjectives(state, objectives);
    }

    static PlanSolverResultDTO enforceSelection(PlanningStateDTO state,
                                                List<CandidateItemDTO> effectiveCandidates) {
        CanonicalPlanningObjectiveSetDTO objectives = PlanningObjectiveCompiler.compileConfirmed(state);
        if (!hasSelectionObjectives(state, objectives)) {
            return noChange(objectives);
        }
        DraftPlanStateDTO draft = state == null ? null : state.getWorkingPlanState();
        if (draft == null) {
            throw new BusinessException(409, "canonical_selection_state_missing: 当前工作方案不可用");
        }
        boolean unitMode = "unit".equals(objectives.getCountMode());
        List<CandidateItemDTO> candidateFacts = mergedCandidateFacts(state, effectiveCandidates);
        List<Entity> current = currentEntities(draft, candidateFacts, unitMode);
        List<Entity> available = availableEntities(draft, candidateFacts, unitMode);
        objectives = copyWithTarget(objectives, resolvedSelectionTarget(state, objectives, current));
        if (objectives.getTierAllocationConstraint() != null
                && concat(current, available).stream().anyMatch(Entity::hasConflictingTier)) {
            throw new BusinessException(409, "tier_fact_conflict: 同一专业组存在多个冲稳保档位");
        }
        // 快照必须与 applySelection 的可加入集合同源：apply 只从 available 里解读
        // addEntityIds，且 available 已过滤 banned/compensation-safe。否则 solver
        // 可能选中 apply 解析不到的实体，直接 409 solver_candidate_missing。
        CandidateSnapshotDTO snapshot = CandidateSnapshotBuilder.build(
                state, candidateFacts, CandidateSnapshotBuilder.CurrentSource.WORKING);
        MutationPolicyDTO policy = new MutationPolicyDTO();
        policy.setAction("INITIAL");
        policy.setLockExisting(false);
        policy.setCountAsChurn(true);
        policy.setRequireCompensationSafe(true);
        Set<String> availableIds = available.stream()
                .map(entity -> entity.entityId)
                .collect(Collectors.toCollection(LinkedHashSet::new));
        for (CandidateFactDTO fact : snapshot.getFacts()) {
            if (!Boolean.TRUE.equals(fact.getCurrent())
                    && !availableIds.contains(fact.getEntityId())) {
                fact.setEligible(false);
            }
        }
        // 用副本 enrich，保留原 objectives 的旧 digest 供后置校验/旧口径使用。
        CanonicalPlanningObjectiveSetDTO stagedObjectives = JSON.parseObject(
                JSON.toJSONString(objectives), CanonicalPlanningObjectiveSetDTO.class);
        PlanningObjectiveCompiler.enrichV2(state, stagedObjectives, policy);
        PlanSolverResultDTO solved = STAGED_SOLVER.solve(snapshot, stagedObjectives, policy).solverResult;
        LOG.info("staged initial selection: session={} status={} selected={} remove={} add={} candidates={}",
                state.getSessionId(), solved.getStatus(),
                defaultList(solved.getSelectedEntityIds()).size(),
                defaultList(solved.getRemoveEntityIds()).size(),
                defaultList(solved.getAddEntityIds()).size(),
                solved.getCandidateCount());
        ensureReady(solved);
        applySelection(state, effectiveCandidates, current, available, solved);
        return solved;
    }

    private static int resolvedSelectionTarget(PlanningStateDTO state,
                                               CanonicalPlanningObjectiveSetDTO objectives,
                                               List<Entity> current) {
        if (objectives.getTierAllocationConstraint() != null) {
            return objectives.getTargetCount();
        }
        Integer confirmedTarget = state == null || state.getConstraintState() == null
                || state.getConstraintState().getHardPlanningObjectives() == null ? null
                : state.getConstraintState().getHardPlanningObjectives().getSelectionTargetCount();
        if (confirmedTarget != null && confirmedTarget > 0) {
            return confirmedTarget;
        }
        if (!current.isEmpty()) {
            return current.size();
        }
        Integer target = objectives == null ? null : objectives.getTargetCount();
        return target == null ? 0 : Math.max(0, target);
    }

    static PlanSolverResultDTO enforceOrdering(PlanningStateDTO state,
                                               List<CandidateItemDTO> effectiveCandidates) {
        return enforceOrdering(state, effectiveCandidates, true);
    }

    /**
     * @param failOnPriorityMiss true：显式应用「同档前置」排序（用户动作，如修复建议应用）——存量优先规则
     *                           零命中时响亮 409，不静默吞掉用户意图
     *                           false：方案重生成路径（学费/范围等约束应用连带重排）——存量优先规则只是
     *                           顺带生效的排序偏好，零命中不应阻塞无关动作，降级为不改序（no_change）
     */
    static PlanSolverResultDTO enforceOrdering(PlanningStateDTO state,
                                               List<CandidateItemDTO> effectiveCandidates,
                                               boolean failOnPriorityMiss) {
        CanonicalPlanningObjectiveSetDTO compiled = PlanningObjectiveCompiler.compileConfirmed(state);
        List<PriorityRuleDTO> priorities = defaultList(compiled.getOrderingConstraints());
        if (priorities.isEmpty()) {
            return noChange(compiled);
        }
        boolean unitMode = "unit".equals(compiled.getCountMode());
        List<Entity> ordered = orderedEntities(state, effectiveCandidates, unitMode);
        if (ordered.isEmpty()) {
            if (!failOnPriorityMiss) {
                return noChange(compiled);
            }
            throw new BusinessException(409, "priority_target_not_in_plan: 当前没有正式方案");
        }
        if (ordered.stream().anyMatch(entity -> Strings.isNullOrEmpty(
                TierAllocationSupport.canonicalTierKey(entity.tier())))) {
            throw new BusinessException(409, "priority_tier_unavailable: 当前方案存在未标注档位的项目");
        }
        if (ordered.stream().noneMatch(entity -> entity.priorityMatched)) {
            if (!failOnPriorityMiss) {
                return noChange(compiled);
            }
            throw new BusinessException(409, "priority_target_not_in_plan: 当前方案没有命中优先目标");
        }
        List<PlanOrderingEngine.OrderEntry> entries = ordered.stream()
                .map(entity -> new PlanOrderingEngine.OrderEntry(
                        entity.entityId, entity.tier(), entity.priorityMatched, entity.pinned))
                .collect(Collectors.toList());
        PlanOrderingEngine.OrderResult orderResult = PlanOrderingEngine.order(entries, true);
        if (orderResult.pinnedConflict) {
            throw new BusinessException(409,
                    "pinned_conflict: 同档优先排序会改变 pinned 项目所在档位的位置。");
        }
        PlanSolverResultDTO solved = new PlanSolverResultDTO();
        solved.setSelectedEntityIds(orderResult.selectedIds);
        solved.setOrderedEntityIds(orderResult.orderedIds);
        solved.setStatus(orderResult.changed() ? "ready" : "no_change");
        solved.setSolverVersion(StagedDeterministicPlanSolver.SOLVER_VERSION);
        solved.setInputDigest(orderingDigest(orderResult.selectedIds, priorities));
        PlanSolverResultDTO.ObjectiveResultDTO priority = new PlanSolverResultDTO.ObjectiveResultDTO();
        priority.setObjectiveId("priority:0");
        priority.setObjectiveType("priority_within_tier");
        priority.setRequiredMin(0);
        priority.setRequiredMax(0);
        priority.setActualCount(orderResult.inversionCount);
        priority.setSatisfied(orderResult.inversionCount == 0);
        solved.getObjectiveResults().add(priority);
        applyOrdering(state, orderResult.orderedIds, unitMode);
        return solved;
    }

    static void applyFrozenSelection(PlanningStateDTO state,
                                     List<CandidateItemDTO> effectiveCandidates,
                                     PlanSolverResultDTO frozen) {
        validateFrozenResult(frozen);
        CanonicalPlanningObjectiveSetDTO objectives = PlanningObjectiveCompiler.compileConfirmed(state);
        DraftPlanStateDTO draft = state == null ? null : state.getWorkingPlanState();
        if (draft == null) {
            throw new BusinessException(409, "canonical_selection_state_missing: 当前工作方案不可用");
        }
        boolean unitMode = "unit".equals(objectives.getCountMode());
        List<CandidateItemDTO> candidateFacts = mergedCandidateFacts(state, effectiveCandidates);
        List<Entity> current = currentEntities(draft, candidateFacts, unitMode);
        List<Entity> available = availableEntities(draft, candidateFacts, unitMode);
        List<String> currentIds = current.stream().map(entity -> entity.entityId).collect(Collectors.toList());
        List<String> selectedIds = defaultList(frozen.getSelectedEntityIds());
        Set<String> knownIds = concat(current, available).stream()
                .map(entity -> entity.entityId)
                .collect(Collectors.toCollection(LinkedHashSet::new));
        if (!knownIds.containsAll(selectedIds)) {
            throw new BusinessException(409, "solver_frozen_candidate_missing");
        }
        List<String> expectedRemoved = currentIds.stream()
                .filter(id -> !selectedIds.contains(id)).collect(Collectors.toList());
        List<String> expectedAdded = selectedIds.stream()
                .filter(id -> !currentIds.contains(id)).collect(Collectors.toList());
        PlanSolverResultDTO mutation = new PlanSolverResultDTO();
        mutation.setRemoveEntityIds(expectedRemoved);
        mutation.setAddEntityIds(expectedAdded);
        applySelection(state, candidateFacts, current, available, mutation);
        List<String> appliedIds = currentEntities(state.getWorkingPlanState(), candidateFacts, unitMode)
                .stream().map(entity -> entity.entityId).collect(Collectors.toList());
        if (!sameIdentitySet(selectedIds, appliedIds)) {
            throw new BusinessException(409, "solver_frozen_selection_mismatch");
        }
    }

    static void applyFrozenOrdering(PlanningStateDTO state, PlanSolverResultDTO frozen) {
        validateFrozenResult(frozen);
        boolean unitMode = isUnitMode(state);
        List<String> before = orderedEntityIds(state, unitMode);
        if (!new LinkedHashSet<String>(defaultList(frozen.getSelectedEntityIds()))
                .equals(new LinkedHashSet<String>(before))) {
            throw new BusinessException(409, "solver_frozen_selection_mismatch");
        }
        applyOrdering(state, frozen.getOrderedEntityIds(), unitMode);
        if (!defaultList(frozen.getOrderedEntityIds()).equals(orderedEntityIds(state, unitMode))) {
            throw new BusinessException(409, "solver_frozen_order_mismatch");
        }
    }

    static void verifyFrozenWorkingSelection(PlanningStateDTO state,
                                             List<CandidateItemDTO> effectiveCandidates,
                                             PlanSolverResultDTO frozen) {
        validateFrozenResult(frozen);
        CanonicalPlanningObjectiveSetDTO objectives = PlanningObjectiveCompiler.compileConfirmed(state);
        boolean unitMode = "unit".equals(objectives.getCountMode());
        List<CandidateItemDTO> candidateFacts = mergedCandidateFacts(state, effectiveCandidates);
        List<String> actual = currentEntities(
                state == null ? null : state.getWorkingPlanState(), candidateFacts, unitMode)
                .stream().map(entity -> entity.entityId).collect(Collectors.toList());
        if (!sameIdentitySet(defaultList(frozen.getSelectedEntityIds()), actual)) {
            throw new BusinessException(409, "solver_frozen_selection_mismatch");
        }
    }

    private static boolean sameIdentitySet(List<String> expected, List<String> actual) {
        return expected.size() == actual.size()
                && new LinkedHashSet<String>(expected).equals(new LinkedHashSet<String>(actual));
    }

    static void verifyFrozenState(PlanningStateDTO state, PlanSolverResultDTO frozen) {
        validateFrozenResult(frozen);
        boolean unitMode = isUnitMode(state);
        List<String> actualOrdered = orderedEntityIds(state, unitMode);
        if (!new LinkedHashSet<String>(defaultList(frozen.getSelectedEntityIds()))
                .equals(new LinkedHashSet<String>(actualOrdered))) {
            throw new BusinessException(409, "solver_frozen_selection_mismatch");
        }
        if (!defaultList(frozen.getOrderedEntityIds()).equals(actualOrdered)) {
            throw new BusinessException(409, "solver_frozen_order_mismatch");
        }
    }

    private static void validateFrozenResult(PlanSolverResultDTO frozen) {
        if (frozen == null || (!("ready".equals(frozen.getStatus()))
                && !("no_change".equals(frozen.getStatus())))
                || Strings.isNullOrEmpty(frozen.getSolverVersion())
                || Strings.isNullOrEmpty(frozen.getInputDigest())) {
            throw new BusinessException(409, "solver_frozen_result_invalid");
        }
        List<String> selected = defaultList(frozen.getSelectedEntityIds());
        List<String> ordered = defaultList(frozen.getOrderedEntityIds());
        if (selected.isEmpty() || selected.stream().anyMatch(Strings::isNullOrEmpty)
                || ordered.stream().anyMatch(Strings::isNullOrEmpty)
                || new LinkedHashSet<String>(selected).size() != selected.size()
                || new LinkedHashSet<String>(ordered).size() != ordered.size()
                || !new LinkedHashSet<String>(selected).equals(new LinkedHashSet<String>(ordered))) {
            throw new BusinessException(409, "solver_frozen_identity_invalid");
        }
    }

    private static boolean isUnitMode(PlanningStateDTO state) {
        return state != null && state.getCandidatePoolState() != null
                && "majorGroup".equalsIgnoreCase(state.getCandidatePoolState().getVolunteerModel());
    }

    private static List<String> orderedEntityIds(PlanningStateDTO state, boolean unitMode) {
        if (state == null || state.getOrderedPlanState() == null) {
            return Lists.newArrayList();
        }
        if (unitMode) {
            return defaultList(state.getOrderedPlanState().getUnits()).stream()
                    .map(OrderedUnitDTO::getUnitId).collect(Collectors.toList());
        }
        return defaultList(state.getOrderedPlanState().getItems()).stream()
                .map(OrderedItemDTO::getVolunteerId).collect(Collectors.toList());
    }

    private static List<CandidateItemDTO> mergedCandidateFacts(
            PlanningStateDTO state,
            List<CandidateItemDTO> effectiveCandidates) {
        Map<String, CandidateItemDTO> byId = new LinkedHashMap<String, CandidateItemDTO>();
        List<CandidateItemDTO> pool = state == null || state.getCandidatePoolState() == null
                ? Lists.newArrayList() : defaultList(state.getCandidatePoolState().getItems());
        for (CandidateItemDTO candidate : pool) {
            if (candidate != null && !Strings.isNullOrEmpty(candidate.getVolunteerId())) {
                byId.put(candidate.getVolunteerId(), candidate);
            }
        }
        for (CandidateItemDTO candidate : defaultList(effectiveCandidates)) {
            if (candidate != null && !Strings.isNullOrEmpty(candidate.getVolunteerId())) {
                byId.put(candidate.getVolunteerId(), candidate);
            }
        }
        return Lists.newArrayList(byId.values());
    }

    private static void applySelection(PlanningStateDTO state,
                                       List<CandidateItemDTO> effectiveCandidates,
                                       List<Entity> current,
                                       List<Entity> available,
                                       PlanSolverResultDTO solved) {
        DraftPlanStateDTO draft = state.getWorkingPlanState();
        Map<String, Entity> currentById = byId(current);
        Set<String> removeVolunteerIds = new LinkedHashSet<String>();
        for (String entityId : solved.getRemoveEntityIds()) {
            Entity entity = currentById.get(entityId);
            if (entity != null) {
                removeVolunteerIds.addAll(entity.volunteerIds);
            }
        }
        if (!removeVolunteerIds.isEmpty()) {
            draft.setItems(defaultList(draft.getItems()).stream()
                    .filter(item -> !removeVolunteerIds.contains(item.getVolunteerId()))
                    .collect(Collectors.toList()));
        }
        Map<String, Entity> availableById = byId(available);
        for (String entityId : solved.getAddEntityIds()) {
            Entity entity = availableById.get(entityId);
            if (entity == null) {
                throw new BusinessException(409, "solver_candidate_missing: " + entityId);
            }
            for (CandidateItemDTO candidate : entity.candidates) {
                if (!WorkingPlanMutationSupport.addWorkingPlanItemIfAllowed(
                        draft, candidate, "canonical_objective")) {
                    throw new BusinessException(409, "solver_candidate_apply_failed: " + candidate.getVolunteerId());
                }
            }
        }
        WorkingPlanMutationSupport.syncWorkingPlanUnitsWithItems(
                draft, effectiveCandidates, state.getCandidatePoolState());
        WorkingPlanMutationSupport.recalculateWorkingPlanSummary(
                draft, state.getCandidatePoolState());
    }

    private static void applyOrdering(PlanningStateDTO state,
                                      List<String> orderedEntityIds,
                                      boolean unitMode) {
        if (state == null || state.getOrderedPlanState() == null) {
            return;
        }
        if (!unitMode) {
            List<OrderedItemDTO> before = defaultList(state.getOrderedPlanState().getItems());
            Map<String, Integer> beforePositions = positions(before, OrderedItemDTO::getVolunteerId);
            Map<String, OrderedItemDTO> byId = before.stream().collect(Collectors.toMap(
                    OrderedItemDTO::getVolunteerId, item -> item,
                    (left, right) -> left, LinkedHashMap::new));
            List<OrderedItemDTO> reordered = orderedEntityIds.stream()
                    .map(byId::get).filter(item -> item != null).collect(Collectors.toList());
            if (reordered.size() != before.size()) {
                throw new BusinessException(409, "solver_order_identity_mismatch");
            }
            for (int index = 0; index < reordered.size(); index++) {
                OrderedItemDTO item = reordered.get(index);
                item.setPosition(index + 1);
                if (!Integer.valueOf(index + 1).equals(beforePositions.get(item.getVolunteerId()))) {
                    item.setOrderedBy("system");
                    item.setOrderReason("hard_priority_rank_before");
                }
            }
            state.getOrderedPlanState().setItems(reordered);
            return;
        }
        List<OrderedUnitDTO> before = defaultList(state.getOrderedPlanState().getUnits());
        Map<String, Integer> beforePositions = positions(before, OrderedUnitDTO::getUnitId);
        Map<String, OrderedUnitDTO> byId = before.stream().collect(Collectors.toMap(
                OrderedUnitDTO::getUnitId, unit -> unit,
                (left, right) -> left, LinkedHashMap::new));
        List<OrderedUnitDTO> reordered = orderedEntityIds.stream()
                .map(byId::get).filter(unit -> unit != null).collect(Collectors.toList());
        if (reordered.size() != before.size()) {
            throw new BusinessException(409, "solver_order_identity_mismatch");
        }
        for (int index = 0; index < reordered.size(); index++) {
            OrderedUnitDTO unit = reordered.get(index);
            unit.setPosition(index + 1);
            if (!Integer.valueOf(index + 1).equals(beforePositions.get(unit.getUnitId()))) {
                unit.setOrderedBy("system");
                unit.setOrderReason("hard_priority_rank_before");
            }
        }
        state.getOrderedPlanState().setUnits(reordered);
        state.getOrderedPlanState().setItems(flattenItems(
                state.getOrderedPlanState().getItems(), reordered));
    }

    private static List<OrderedItemDTO> flattenItems(List<OrderedItemDTO> current,
                                                     List<OrderedUnitDTO> units) {
        Map<String, OrderedItemDTO> byId = defaultList(current).stream()
                .filter(item -> item != null && !Strings.isNullOrEmpty(item.getVolunteerId()))
                .collect(Collectors.toMap(OrderedItemDTO::getVolunteerId, item -> item,
                        (left, right) -> left, LinkedHashMap::new));
        List<OrderedItemDTO> result = new ArrayList<OrderedItemDTO>();
        Set<String> added = new LinkedHashSet<String>();
        for (OrderedUnitDTO unit : units) {
            for (PlanningUnitMajorDTO major : defaultList(unit == null ? null : unit.getMajorItems())) {
                OrderedItemDTO item = byId.get(major.getVolunteerId());
                if (item != null && added.add(item.getVolunteerId())) {
                    result.add(item);
                }
            }
        }
        for (OrderedItemDTO item : defaultList(current)) {
            if (item != null && added.add(item.getVolunteerId())) {
                result.add(item);
            }
        }
        for (int index = 0; index < result.size(); index++) {
            result.get(index).setPosition(index + 1);
        }
        return result;
    }

    private static List<Entity> currentEntities(DraftPlanStateDTO draft,
                                                List<CandidateItemDTO> candidates,
                                                boolean unitMode) {
        if (!unitMode) {
            List<Entity> result = new ArrayList<Entity>();
            for (DraftItemDTO item : defaultList(draft == null ? null : draft.getItems())) {
                CandidateItemDTO candidate = currentCandidate(item, candidates);
                if (candidate != null) {
                    result.add(new Entity(item.getVolunteerId(), Lists.newArrayList(candidate),
                            Lists.newArrayList(item.getVolunteerId()),
                            Boolean.TRUE.equals(item.getLocked()), false));
                }
            }
            return result;
        }
        Map<String, List<CandidateItemDTO>> groupedCandidates = new LinkedHashMap<String, List<CandidateItemDTO>>();
        Map<String, List<String>> groupedVolunteerIds = new LinkedHashMap<String, List<String>>();
        Map<String, Boolean> groupedLocked = new LinkedHashMap<String, Boolean>();
        for (DraftItemDTO item : defaultList(draft == null ? null : draft.getItems())) {
            CandidateItemDTO candidate = currentCandidate(item, candidates);
            if (candidate == null) {
                continue;
            }
            String unitId = RepairCandidateSelector.resolveInitialRecommendationUnitId(candidate);
            groupedCandidates.computeIfAbsent(unitId, ignored -> Lists.newArrayList()).add(candidate);
            groupedVolunteerIds.computeIfAbsent(unitId, ignored -> Lists.newArrayList())
                    .add(item.getVolunteerId());
            groupedLocked.put(unitId, Boolean.TRUE.equals(groupedLocked.get(unitId))
                    || Boolean.TRUE.equals(item.getLocked()));
        }
        return groupedCandidates.entrySet().stream()
                .map(entry -> new Entity(entry.getKey(), entry.getValue(),
                        groupedVolunteerIds.get(entry.getKey()),
                        Boolean.TRUE.equals(groupedLocked.get(entry.getKey())), false))
                .collect(Collectors.toList());
    }

    private static List<Entity> availableEntities(DraftPlanStateDTO draft,
                                                  List<CandidateItemDTO> candidates,
                                                  boolean unitMode) {
        Set<String> selectedVolunteerIds = defaultList(draft == null ? null : draft.getItems()).stream()
                .map(DraftItemDTO::getVolunteerId)
                .filter(value -> !Strings.isNullOrEmpty(value))
                .collect(Collectors.toCollection(LinkedHashSet::new));
        defaultList(draft == null ? null : draft.getItems()).stream()
                .map(item -> currentCandidate(item, candidates))
                .filter(candidate -> candidate != null && !Strings.isNullOrEmpty(candidate.getVolunteerId()))
                .map(CandidateItemDTO::getVolunteerId)
                .forEach(selectedVolunteerIds::add);
        Set<String> bannedVolunteerIds = new LinkedHashSet<String>(defaultList(
                draft == null ? null : draft.getBannedVolunteerIds()));
        Set<String> selectedUnitIds = defaultList(draft == null ? null : draft.getItems()).stream()
                .map(item -> currentCandidate(item, candidates))
                .filter(candidate -> candidate != null)
                .map(RepairCandidateSelector::resolveInitialRecommendationUnitId)
                .collect(Collectors.toCollection(LinkedHashSet::new));
        if (!unitMode) {
            return defaultList(candidates).stream()
                    .filter(candidate -> candidate != null && !Strings.isNullOrEmpty(candidate.getVolunteerId()))
                    .filter(candidate -> !selectedVolunteerIds.contains(candidate.getVolunteerId()))
                    .filter(candidate -> !bannedVolunteerIds.contains(candidate.getVolunteerId()))
                    .filter(RepairCandidateSelector::isCompensationSafeCandidate)
                    .sorted(candidateComparator())
                    .map(candidate -> new Entity(candidate, false, false))
                    .collect(Collectors.toList());
        }
        Map<String, List<CandidateItemDTO>> grouped = defaultList(candidates).stream()
                .filter(candidate -> candidate != null && !Strings.isNullOrEmpty(candidate.getVolunteerId()))
                .filter(candidate -> !selectedUnitIds.contains(
                        RepairCandidateSelector.resolveInitialRecommendationUnitId(candidate)))
                .collect(Collectors.groupingBy(
                        RepairCandidateSelector::resolveInitialRecommendationUnitId,
                        LinkedHashMap::new, Collectors.toList()));
        return grouped.entrySet().stream()
                .filter(entry -> !Strings.isNullOrEmpty(entry.getKey()))
                .filter(entry -> entry.getValue().stream().allMatch(candidate ->
                        !selectedVolunteerIds.contains(candidate.getVolunteerId())
                                && !bannedVolunteerIds.contains(candidate.getVolunteerId())
                                && RepairCandidateSelector.isCompensationSafeCandidate(candidate)))
                .map(entry -> new Entity(entry.getKey(), entry.getValue().stream()
                        .sorted(candidateComparator()).collect(Collectors.toList()), false, false))
                .sorted((left, right) -> candidateComparator().compare(
                        left.candidates.get(0), right.candidates.get(0)))
                .collect(Collectors.toList());
    }

    private static CandidateItemDTO currentCandidate(DraftItemDTO item,
                                                     List<CandidateItemDTO> candidates) {
        if (item == null) {
            return null;
        }
        CandidateItemDTO direct = WorkingPlanMutationSupport.findCandidate(
                candidates, item.getVolunteerId());
        if (direct != null) {
            return direct;
        }
        String unitId = workingUnitId(item);
        List<CandidateItemDTO> matches = defaultList(candidates).stream()
                .filter(candidate -> candidate != null
                        && item.getMajorName() != null
                        && item.getMajorName().equals(candidate.getMajorName()))
                .filter(candidate -> !Strings.isNullOrEmpty(unitId)
                        ? unitId.equals(RepairCandidateSelector.resolveInitialRecommendationUnitId(candidate))
                        : item.getSchoolName() != null
                        && item.getSchoolName().equals(candidate.getSchoolName()))
                .limit(2)
                .collect(Collectors.toList());
        return matches.size() == 1 ? matches.get(0) : null;
    }

    private static String workingUnitId(DraftItemDTO item) {
        if (item == null || Strings.isNullOrEmpty(item.getVolunteerId())) {
            return item == null ? null : item.getSchoolName();
        }
        int split = item.getVolunteerId().indexOf('_');
        return split > 0 ? item.getVolunteerId().substring(0, split) : item.getVolunteerId();
    }

    private static List<Entity> orderedEntities(PlanningStateDTO state,
                                                List<CandidateItemDTO> candidates,
                                                boolean unitMode) {
        Map<String, CandidateItemDTO> byVolunteerId = candidateMap(candidates);
        PriorityRuleDTO priority = PriorityRuleSupport.confirmedRules(state).get(0);
        if (!unitMode) {
            List<Entity> result = new ArrayList<Entity>();
            for (OrderedItemDTO item : defaultList(state == null || state.getOrderedPlanState() == null
                    ? null : state.getOrderedPlanState().getItems())) {
                CandidateItemDTO candidate = byVolunteerId.get(item.getVolunteerId());
                if (candidate == null) {
                    candidate = fallbackCandidate(item);
                }
                Entity entity = new Entity(candidate, Boolean.TRUE.equals(item.getLocked()),
                        Boolean.TRUE.equals(item.getPinned()));
                entity.priorityMatched = PriorityRuleSupport.matches(candidate, priority);
                result.add(entity);
            }
            return result;
        }
        List<Entity> result = new ArrayList<Entity>();
        for (OrderedUnitDTO unit : defaultList(state == null || state.getOrderedPlanState() == null
                ? null : state.getOrderedPlanState().getUnits())) {
            List<CandidateItemDTO> unitCandidates = new ArrayList<CandidateItemDTO>();
            for (PlanningUnitMajorDTO major : defaultList(unit == null ? null : unit.getMajorItems())) {
                CandidateItemDTO candidate = byVolunteerId.get(major.getVolunteerId());
                unitCandidates.add(candidate == null ? fallbackCandidate(unit, major) : candidate);
            }
            if (unitCandidates.isEmpty()) {
                unitCandidates.add(fallbackCandidate(unit, null));
            }
            Entity entity = new Entity(unit.getUnitId(), unitCandidates,
                    Boolean.TRUE.equals(unit.getLocked()), Boolean.TRUE.equals(unit.getPinned()));
            entity.priorityMatched = unitCandidates.stream()
                    .anyMatch(candidate -> PriorityRuleSupport.matches(candidate, priority));
            result.add(entity);
        }
        return result;
    }

    private static CandidateItemDTO fallbackCandidate(OrderedItemDTO item) {
        CandidateItemDTO result = new CandidateItemDTO();
        result.setVolunteerId(item == null ? null : item.getVolunteerId());
        result.setSchoolName(item == null ? null : item.getSchoolName());
        result.setDisplaySchoolName(item == null ? null : item.getSchoolName());
        result.setMajorName(item == null ? null : item.getMajorName());
        result.setTier(item == null ? null : item.getTier());
        return result;
    }

    private static CandidateItemDTO fallbackCandidate(OrderedUnitDTO unit, PlanningUnitMajorDTO major) {
        CandidateItemDTO result = new CandidateItemDTO();
        result.setVolunteerId(major == null ? null : major.getVolunteerId());
        result.setPlanSchoolDataId(unit == null ? null : unit.getUnitId());
        result.setSchoolName(unit == null ? null : unit.getSchoolName());
        result.setDisplaySchoolName(unit == null ? null : unit.getSchoolName());
        result.setProvinceName(unit == null ? null : unit.getProvinceName());
        result.setProvinceId(unit == null ? null : unit.getProvinceId());
        result.setCityId(unit == null ? null : unit.getCityId());
        result.setCityName(unit == null ? null : unit.getCityName());
        result.setSchoolNature(unit == null ? null : unit.getSchoolNature());
        result.setSchoolCategory(unit == null ? null : unit.getSchoolCategory());
        result.setSchoolLevel(unit == null ? null : unit.getSchoolLevel());
        result.setMajorName(major == null ? null : major.getMajorName());
        result.setMajorCategoryId(major == null ? null : major.getMajorCategoryId());
        result.setMajorSubCategoryId(major == null ? null : major.getMajorSubCategoryId());
        result.setMajorPlanTags(major == null ? Lists.newArrayList() : defaultList(major.getMajorPlanTags()));
        result.setTier(unit == null ? null : unit.getTier());
        return result;
    }

    private static PlanSolverResultDTO noChange(CanonicalPlanningObjectiveSetDTO objectives) {
        PlanSolverResultDTO result = new PlanSolverResultDTO();
        result.setStatus("no_change");
        result.setSolverVersion(StagedDeterministicPlanSolver.SOLVER_VERSION);
        Map<String, Object> payload = new LinkedHashMap<String, Object>();
        payload.put("objectiveDigest", objectives == null ? null : objectives.getObjectiveDigest());
        payload.put("countMode", objectives == null ? null : objectives.getCountMode());
        payload.put("targetCount", objectives == null ? null : objectives.getTargetCount());
        result.setInputDigest(sha256(payload));
        return result;
    }

    /** 排序路径输入摘要：原有序 id + 优先规则。 */
    private static String orderingDigest(List<String> orderedEntityIds,
                                         List<PriorityRuleDTO> priorities) {
        Map<String, Object> payload = new LinkedHashMap<String, Object>();
        payload.put("orderedEntityIds", defaultList(orderedEntityIds));
        payload.put("priorityRules", defaultList(priorities));
        return sha256(payload);
    }

    private static String sha256(Object payload) {
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            byte[] bytes = digest.digest(JSON.toJSONString(payload).getBytes(StandardCharsets.UTF_8));
            StringBuilder result = new StringBuilder(bytes.length * 2);
            for (byte value : bytes) {
                result.append(String.format("%02x", value & 0xff));
            }
            return result.toString();
        } catch (NoSuchAlgorithmException ex) {
            throw new IllegalStateException("SHA-256 is unavailable", ex);
        }
    }

    private static CanonicalPlanningObjectiveSetDTO copyWithTarget(
            CanonicalPlanningObjectiveSetDTO source,
            int targetCount) {
        CanonicalPlanningObjectiveSetDTO result = new CanonicalPlanningObjectiveSetDTO();
        result.setSchemaVersion(source.getSchemaVersion());
        result.setSourceVersion(source.getSourceVersion());
        result.setCountMode(source.getCountMode());
        result.setTargetCount(targetCount);
        result.setEligibilityConstraints(source.getEligibilityConstraints());
        result.setCoverageConstraints(source.getCoverageConstraints());
        result.setTierAllocationGoal(source.getTierAllocationGoal());
        result.setTierAllocationConstraint(source.getTierAllocationConstraint());
        result.setTierAllocationResolution(source.getTierAllocationResolution());
        result.setTierAllocationStateChanged(source.getTierAllocationStateChanged());
        result.setOrderingConstraints(source.getOrderingConstraints());
        result.setObjectiveDigest(source.getObjectiveDigest());
        return result;
    }

    private static boolean hasSelectionObjectives(PlanningStateDTO state,
                                                  CanonicalPlanningObjectiveSetDTO objectives) {
        Integer selectionTarget = state == null || state.getConstraintState() == null
                || state.getConstraintState().getHardPlanningObjectives() == null ? null
                : state.getConstraintState().getHardPlanningObjectives().getSelectionTargetCount();
        return objectives != null && (selectionTarget != null
                || !defaultList(objectives.getCoverageConstraints()).isEmpty()
                || objectives.getTierAllocationConstraint() != null);
    }

    private static void ensureReady(PlanSolverResultDTO solved) {
        if (solved == null || !"blocked".equals(solved.getStatus())) {
            return;
        }
        PlanSolverResultDTO.DiagnosticDTO diagnostic = solved.getDiagnostics().isEmpty()
                ? null : solved.getDiagnostics().get(0);
        String reason = diagnostic == null ? "canonical_solver_blocked" : diagnostic.getReasonCode();
        String message = diagnostic == null ? "canonical solver 无法证明目标可行" : diagnostic.getMessage();
        throw new BusinessException(409, reason + ": " + message);
    }

    private static Map<String, CandidateItemDTO> candidateMap(List<CandidateItemDTO> candidates) {
        return defaultList(candidates).stream()
                .filter(candidate -> candidate != null && !Strings.isNullOrEmpty(candidate.getVolunteerId()))
                .collect(Collectors.toMap(CandidateItemDTO::getVolunteerId, candidate -> candidate,
                        (left, right) -> left, LinkedHashMap::new));
    }

    private static Map<String, Entity> byId(List<Entity> entities) {
        return entities.stream().collect(Collectors.toMap(entity -> entity.entityId, entity -> entity,
                (left, right) -> left, LinkedHashMap::new));
    }

    private static List<Entity> concat(List<Entity> left, List<Entity> right) {
        List<Entity> result = new ArrayList<Entity>(left);
        result.addAll(right);
        return result;
    }

    private static Comparator<CandidateItemDTO> candidateComparator() {
        return Comparator
                .comparing((CandidateItemDTO item) -> item.getIntentScore(),
                        Comparator.nullsLast(Comparator.reverseOrder()))
                .thenComparing((CandidateItemDTO item) -> item.getFinalScore(),
                        Comparator.nullsLast(Comparator.reverseOrder()))
                .thenComparing(CandidateItemDTO::getVolunteerId, Comparator.nullsLast(String::compareTo));
    }

    private static <T> Map<String, Integer> positions(List<T> values,
                                                      java.util.function.Function<T, String> id) {
        Map<String, Integer> result = new LinkedHashMap<String, Integer>();
        for (int index = 0; index < values.size(); index++) {
            result.put(id.apply(values.get(index)), index + 1);
        }
        return result;
    }

    private static <T> List<T> defaultList(List<T> values) {
        return values == null ? Lists.newArrayList() : values;
    }

    private static final class Entity {
        private final String entityId;
        private final List<CandidateItemDTO> candidates;
        private final List<String> volunteerIds;
        private final boolean locked;
        private final boolean pinned;
        private boolean priorityMatched;

        private Entity(CandidateItemDTO candidate, boolean locked, boolean pinned) {
            this(candidate == null ? null : candidate.getVolunteerId(),
                    Lists.newArrayList(candidate), locked, pinned);
        }

        private Entity(String entityId,
                       List<CandidateItemDTO> candidates,
                       boolean locked,
                       boolean pinned) {
            this(entityId, candidates, defaultList(candidates).stream()
                    .filter(candidate -> candidate != null)
                    .map(CandidateItemDTO::getVolunteerId)
                    .filter(value -> !Strings.isNullOrEmpty(value))
                    .collect(Collectors.toList()), locked, pinned);
        }

        private Entity(String entityId,
                       List<CandidateItemDTO> candidates,
                       List<String> volunteerIds,
                       boolean locked,
                       boolean pinned) {
            this.entityId = entityId;
            this.candidates = defaultList(candidates).stream()
                    .filter(candidate -> candidate != null)
                    .collect(Collectors.toList());
            this.volunteerIds = defaultList(volunteerIds).stream()
                    .filter(value -> !Strings.isNullOrEmpty(value))
                    .collect(Collectors.toList());
            this.locked = locked;
            this.pinned = pinned;
        }

        private String tier() {
            return candidates.isEmpty() ? "" : Strings.nullToEmpty(candidates.get(0).getTier()).trim();
        }

        private boolean hasConflictingTier() {
            return candidates.stream().map(candidate -> TierAllocationSupport.canonicalTierKey(candidate.getTier()))
                    .filter(value -> !Strings.isNullOrEmpty(value)).distinct().count() > 1;
        }
    }
}
