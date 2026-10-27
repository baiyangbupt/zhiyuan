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
import com.ytell.zhiyuan.model.dto.planning.StructureQualityPolicyDTO;
import com.ytell.zhiyuan.model.dto.planning.TierAllocationConstraintDTO;
import com.ytell.zhiyuan.model.dto.planning.TierCountRangeDTO;
import com.ytell.zhiyuan.model.dto.planning.TierCountsDTO;
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
        return enforceSelection(state, effectiveCandidates, null, false);
    }

    static PlanSolverResultDTO enforceSelection(PlanningStateDTO state,
                                                List<CandidateItemDTO> effectiveCandidates,
                                                Integer initialSelectionTargetCount) {
        return enforceSelection(state, effectiveCandidates, initialSelectionTargetCount, false);
    }

    /**
     * @param initialSelectionTargetCount 非空时视为 initial 场景的显式目标：
     *        即使没有 durable selectionTarget/coverage/tier，也允许 solver
     *        以该目标选集合；仅作为本次求解输入，不写入 state。
     * @param initialContentGuard 初始方案专用：solver 结果不得引入新的风险标签、
     *        不得让计划条目数膨胀、不得丢失既有 preferred 专业；违反时回退启发式。
     */
    static PlanSolverResultDTO enforceSelection(PlanningStateDTO state,
                                                List<CandidateItemDTO> effectiveCandidates,
                                                Integer initialSelectionTargetCount,
                                                boolean initialContentGuard) {
        return enforceSelection(state, effectiveCandidates, initialSelectionTargetCount,
                initialContentGuard, false);
    }

    static PlanSolverResultDTO enforceSelection(PlanningStateDTO state,
                                                List<CandidateItemDTO> effectiveCandidates,
                                                Integer initialSelectionTargetCount,
                                                boolean initialContentGuard,
                                                boolean allowExistingSpecialPlanConflicts) {
        CanonicalPlanningObjectiveSetDTO objectives = PlanningObjectiveCompiler.compileConfirmed(state);
        boolean allowInitialFallback = initialContentGuard && !hasSelectionObjectives(state, objectives);
        boolean explicitInitialTarget = initialSelectionTargetCount != null
                && initialSelectionTargetCount > 0;
        if (!hasSelectionObjectives(state, objectives) && !explicitInitialTarget) {
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
        objectives = copyWithTarget(objectives, explicitInitialTarget
                ? initialSelectionTargetCount
                : resolvedSelectionTarget(state, objectives, current));
        // 初始方案若没有 durable 配额目标，沿用推荐池的 requiredTierCounts
        // 投影到本次目标数，避免默认 solver 把 45 条全排成冲/稳、没有保底。
        if (explicitInitialTarget && objectives.getTierAllocationConstraint() == null) {
            TierAllocationConstraintDTO initialTiers = projectInitialTierAllocation(
                    state, objectives.getTargetCount(), concat(current, available));
            if (initialTiers != null) {
                objectives.setTierAllocationConstraint(initialTiers);
            }
        }
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
        policy.setAction(allowExistingSpecialPlanConflicts ? "REMOVE" : "INITIAL");
        policy.setAllowAdd(!allowExistingSpecialPlanConflicts);
        policy.setLockExisting(allowExistingSpecialPlanConflicts);
        // 初始方案不是“用户已确认方案”的增量修订：结构质量开启时不再优先保留
        // 上一版自动方案，否则 churn 会固定住 42/45 条，梯度/多样性只能最多换 3 条。
        // 普通补齐/替换仍保留 churn 语义。
        boolean structureQualityActive = !"off".equals(SolverFeatureFlags.structureQualityMode());
        policy.setCountAsChurn(!(initialContentGuard && structureQualityActive));
        policy.setRequireCompensationSafe(true);
        policy.setInitialContentGuard(initialContentGuard);
        policy.setPrioritySelection(SolverFeatureFlags.prioritySelectionEnabled());
        policy.setOrderingPolicyVersion(allowExistingSpecialPlanConflicts
                ? StagedDeterministicPlanSolver.ORDERING_PRESERVE_CURRENT
                : initialContentGuard
                ? StagedDeterministicPlanSolver.ORDERING_INITIAL_TIER_STRICT
                : StagedDeterministicPlanSolver.ORDERING_INITIAL_TIER);
        policy.setAllowExistingSpecialPlanConflicts(allowExistingSpecialPlanConflicts);
        policy.setRequiredMajorCount(state.getCandidatePoolState() == null
                ? null : state.getCandidatePoolState().getRequiredMajorCount());
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
        logStructureQualityShadow(state, snapshot, stagedObjectives, policy, solved);
        if (allowInitialFallback && "blocked".equals(solved.getStatus())) {
            PlanSolverResultDTO.DiagnosticDTO source = solved.getDiagnostics().isEmpty()
                    ? null : solved.getDiagnostics().get(0);
            String reason = source == null ? "solver_blocked" : source.getReasonCode();
            String objective = source == null ? null : source.getObjectiveId();
            String detail = source == null ? null : source.getMessage();
            LOG.warn("initial solver blocked, fallback heuristic: session={} reason={} objective={} detail={}",
                    state.getSessionId(), reason, objective, detail);
            PlanSolverResultDTO fallback = noChange(objectives);
            PlanSolverResultDTO.DiagnosticDTO diagnostic = new PlanSolverResultDTO.DiagnosticDTO();
            diagnostic.setReasonCode("initial_content_guard");
            diagnostic.setObjectiveId("initial");
            diagnostic.setMessage("initial solver blocked: reason=" + reason
                    + ", objective=" + objective + ", detail=" + detail);
            fallback.getDiagnostics().add(diagnostic);
            return fallback;
        }
        ensureReady(solved);
        if (initialContentGuard) {
            String violation = initialContentGuardViolation(snapshot.getFacts(), solved, unitMode);
            if (!Strings.isNullOrEmpty(violation)) {
                if (!allowInitialFallback) {
                    throw new BusinessException(409, "initial_content_guard: " + violation);
                }
                LOG.warn("initial content guard rejected solver: session={} violation={}",
                        state.getSessionId(), violation);
                PlanSolverResultDTO fallback = noChange(objectives);
                PlanSolverResultDTO.DiagnosticDTO diagnostic = new PlanSolverResultDTO.DiagnosticDTO();
                diagnostic.setReasonCode("initial_content_guard");
                diagnostic.setObjectiveId("initial");
                diagnostic.setMessage(violation);
                fallback.getDiagnostics().add(diagnostic);
                return fallback;
            }
        }
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
        mutation.setSelectedMajorIdsByUnit(frozen.getSelectedMajorIdsByUnit());
        verifyRetainedMajors(current, frozen);
        applySelection(state, candidateFacts, current, available, mutation);
        List<String> appliedIds = currentEntities(state.getWorkingPlanState(), candidateFacts, unitMode)
                .stream().map(entity -> entity.entityId).collect(Collectors.toList());
        if (!sameIdentitySet(selectedIds, appliedIds)) {
            throw new BusinessException(409, "solver_frozen_selection_mismatch");
        }
        verifyFrozenWorkingSelection(state, candidateFacts, frozen);
    }

    static void applyFrozenOrdering(PlanningStateDTO state, PlanSolverResultDTO frozen) {
        applyFrozenOrdering(state, frozen, isUnitMode(state));
    }

    /**
     * 显式指定 unit/item 载体：Direct 组模式修复允许在 volunteerModel 缺失时
     * 依据 orderedPlanState.units 判定 unit；其它调用方仍沿用 volunteerModel。
     */
    static void applyFrozenOrdering(PlanningStateDTO state, PlanSolverResultDTO frozen, boolean unitMode) {
        validateFrozenResult(frozen);
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
        List<Entity> current = currentEntities(
                state == null ? null : state.getWorkingPlanState(), candidateFacts, unitMode);
        List<String> actual = current.stream().map(entity -> entity.entityId).collect(Collectors.toList());
        if (!sameIdentitySet(defaultList(frozen.getSelectedEntityIds()), actual)) {
            throw new BusinessException(409, "solver_frozen_selection_mismatch");
        }
        verifyRetainedMajors(current, frozen);
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
        Map<String, List<String>> planned = frozen.getSelectedMajorIdsByUnit();
        if (planned != null && !planned.isEmpty()) {
            List<String> flattened = new ArrayList<String>();
            for (OrderedUnitDTO unit : defaultList(state.getOrderedPlanState().getUnits())) {
                List<String> actualMajors = defaultList(unit.getMajorItems()).stream()
                        .map(PlanningUnitMajorDTO::getVolunteerId).collect(Collectors.toList());
                List<String> expectedMajors = planned.get(unit.getUnitId());
                if (expectedMajors == null || !sameIdentitySet(expectedMajors, actualMajors)) {
                    throw new BusinessException(409, "solver_frozen_major_selection_mismatch");
                }
                flattened.addAll(actualMajors);
            }
            List<String> actualItems = defaultList(state.getOrderedPlanState().getItems()).stream()
                    .map(OrderedItemDTO::getVolunteerId).collect(Collectors.toList());
            if (!flattened.equals(actualItems)) {
                throw new BusinessException(409, "solver_frozen_major_selection_mismatch");
            }
        }
    }

    private static void verifyRetainedMajors(List<Entity> current, PlanSolverResultDTO frozen) {
        Map<String, List<String>> planned = frozen.getSelectedMajorIdsByUnit();
        if (planned == null || planned.isEmpty()) {
            return;
        }
        for (Entity entity : current) {
            List<String> expected = planned.get(entity.entityId);
            if (expected == null) {
                continue;
            }
            List<String> actual = entity.candidates.stream().map(CandidateItemDTO::getVolunteerId)
                    .collect(Collectors.toList());
            if (!sameIdentitySet(expected, actual)) {
                throw new BusinessException(409, "solver_frozen_major_selection_mismatch");
            }
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
        Map<String, List<String>> planned = frozen.getSelectedMajorIdsByUnit();
        if (planned != null && !planned.isEmpty()) {
            if (!new LinkedHashSet<String>(selected).equals(planned.keySet())) {
                throw new BusinessException(409, "solver_frozen_major_selection_mismatch");
            }
            Set<String> selectedMajors = new LinkedHashSet<String>();
            for (List<String> majors : planned.values()) {
                if (majors == null || majors.isEmpty()) {
                    throw new BusinessException(409, "solver_frozen_major_selection_mismatch");
                }
                for (String volunteerId : majors) {
                    if (Strings.isNullOrEmpty(volunteerId) || !selectedMajors.add(volunteerId)) {
                        throw new BusinessException(409, "solver_frozen_major_selection_mismatch");
                    }
                }
            }
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
        boolean unitMode = state.getCandidatePoolState() != null
                && "majorGroup".equalsIgnoreCase(state.getCandidatePoolState().getVolunteerModel());
        Integer requiredMajorCount = state.getCandidatePoolState() == null
                ? null : state.getCandidatePoolState().getRequiredMajorCount();
        for (String entityId : solved.getAddEntityIds()) {
            Entity entity = availableById.get(entityId);
            if (entity == null) {
                throw new BusinessException(409, "solver_candidate_missing: " + entityId);
            }
            List<CandidateItemDTO> candidatesToAdd = entity.candidates;
            List<String> plannedMajorIds = solved.getSelectedMajorIdsByUnit() == null
                    ? null : solved.getSelectedMajorIdsByUnit().get(entityId);
            if (unitMode && plannedMajorIds != null && !plannedMajorIds.isEmpty()) {
                Map<String, CandidateItemDTO> byVolunteer = new LinkedHashMap<String, CandidateItemDTO>();
                for (CandidateItemDTO candidate : entity.candidates) {
                    if (candidate != null && !Strings.isNullOrEmpty(candidate.getVolunteerId())) {
                        byVolunteer.put(candidate.getVolunteerId(), candidate);
                    }
                }
                List<CandidateItemDTO> planned = new ArrayList<CandidateItemDTO>();
                for (String volunteerId : plannedMajorIds) {
                    CandidateItemDTO candidate = byVolunteer.get(volunteerId);
                    if (candidate == null) {
                        throw new BusinessException(409,
                                "solver_major_candidate_missing: " + volunteerId);
                    }
                    planned.add(candidate);
                }
                candidatesToAdd = planned;
            } else if (unitMode && GroupInnerMajorCapFlags.enabled()) {
                Double unitEnrollRatio = null;
                for (CandidateItemDTO candidate : entity.candidates) {
                    if (candidate != null && candidate.getSchoolEnrollRatio() != null) {
                        unitEnrollRatio = candidate.getSchoolEnrollRatio();
                        break;
                    }
                }
                List<CandidateItemDTO> capped = GroupInnerMajorPlanner.plan(
                        entity.candidates, requiredMajorCount, unitEnrollRatio);
                if (!capped.isEmpty()) {
                    candidatesToAdd = capped;
                }
            }
            for (CandidateItemDTO candidate : candidatesToAdd) {
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

    static void applyOrdering(PlanningStateDTO state,
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

    /**
     * 初始方案内容护栏：solver 只按目标/效用选集合，可能引入启发式没有的
     * 专项/中外合作/高收费/限报，或把单个超大组带进来导致条目膨胀，或丢掉
     * 用户 preferred 专业。任一发生则回退启发式初始方案。
     */
    private static String initialContentGuardViolation(List<CandidateFactDTO> facts,
                                                       PlanSolverResultDTO solved,
                                                       boolean unitMode) {
        Map<String, CandidateFactDTO> byId = new LinkedHashMap<String, CandidateFactDTO>();
        List<CandidateFactDTO> baseline = new ArrayList<CandidateFactDTO>();
        for (CandidateFactDTO fact : defaultList(facts)) {
            if (fact == null) {
                continue;
            }
            byId.put(fact.getEntityId(), fact);
            if (Boolean.TRUE.equals(fact.getCurrent())) {
                baseline.add(fact);
            }
        }
        List<CandidateFactDTO> selected = new ArrayList<CandidateFactDTO>();
        for (String entityId : defaultList(solved.getSelectedEntityIds())) {
            CandidateFactDTO fact = byId.get(entityId);
            if (fact != null) {
                selected.add(fact);
            }
        }
        Map<String, Integer> baselineRisk = InitialContentPolicySupport.riskCounts(baseline);
        Map<String, Integer> selectedRisk = InitialContentPolicySupport.riskCounts(selected);
        for (String code : InitialContentPolicySupport.RISK_CODES) {
            int before = baselineRisk.getOrDefault(code, 0);
            int after = selectedRisk.getOrDefault(code, 0);
            if (after > before) {
                return code + " increased: " + before + " -> " + after;
            }
        }
        int baselineItems = InitialContentPolicySupport.itemCount(baseline, unitMode);
        int selectedItems = InitialContentPolicySupport.itemCount(selected, unitMode);
        int allowance = InitialContentPolicySupport.itemAllowance(baselineItems);
        if (selectedItems > baselineItems + allowance) {
            return "item_count grew: " + baselineItems + " -> " + selectedItems
                    + " (allowance " + allowance + ")";
        }
        int baselinePreferred = InitialContentPolicySupport.preferredCount(baseline);
        int selectedPreferred = InitialContentPolicySupport.preferredCount(selected);
        if (selectedPreferred < baselinePreferred) {
            return "preferred majors lost: " + baselinePreferred + " -> " + selectedPreferred;
        }
        return null;
    }

    /**
     * Phase 2 影子：正常选择不变，额外用 soft 结构策略求解一次并打印分布。
     * 只用于本地/灰度验证，不写 state、不影响用户方案。
     */
    private static void logStructureQualityShadow(PlanningStateDTO state,
                                                  CandidateSnapshotDTO snapshot,
                                                  CanonicalPlanningObjectiveSetDTO objectives,
                                                  MutationPolicyDTO policy,
                                                  PlanSolverResultDTO base) {
        if (!SolverFeatureFlags.structureQualityShadowEnabled()
                || base == null || !"ready".equals(base.getStatus())
                || objectives == null) {
            return;
        }
        StructureQualityPolicyDTO configured = objectives.getStructureQualityPolicy();
        if (configured != null && !"off".equalsIgnoreCase(configured.getMode())) {
            return;
        }
        try {
            CanonicalPlanningObjectiveSetDTO shadowObjectives = JSON.parseObject(
                    JSON.toJSONString(objectives), CanonicalPlanningObjectiveSetDTO.class);
            StructureQualityPolicyDTO shadowPolicy = new StructureQualityPolicyDTO();
            shadowPolicy.setMode("soft");
            shadowObjectives.setStructureQualityPolicy(shadowPolicy);
            PlanSolverResultDTO shadow = new StagedDeterministicPlanSolver()
                    .solve(snapshot, shadowObjectives, policy).solverResult;
            LOG.info("structure-quality shadow: session={} base={}/{} shadow={}/{} base={} shadow={} diff={}",
                    state == null ? null : state.getSessionId(),
                    base.getStatus(), defaultList(base.getSelectedEntityIds()).size(),
                    shadow.getStatus(), defaultList(shadow.getSelectedEntityIds()).size(),
                    structureProfile(snapshot, base.getSelectedEntityIds()),
                    structureProfile(snapshot, shadow.getSelectedEntityIds()),
                    idDiff(base.getSelectedEntityIds(), shadow.getSelectedEntityIds()));
            logFreshStructureShadow(state, snapshot, objectives, policy);
            logRelaxedChurnShadow(state, snapshot, objectives, policy, base);
        } catch (RuntimeException ex) {
            LOG.warn("structure-quality shadow failed: session={} error={}",
                    state == null ? null : state.getSessionId(), ex.getMessage());
        }
    }

    /**
     * 初始方案候选策略：保留 current/guard，只把 churn 从最高优先级拿掉，
     * 让结构质量可以在候选池里换组。仍只打日志。
     */
    private static void logRelaxedChurnShadow(PlanningStateDTO state,
                                              CandidateSnapshotDTO snapshot,
                                              CanonicalPlanningObjectiveSetDTO objectives,
                                              MutationPolicyDTO policy,
                                              PlanSolverResultDTO base) {
        CanonicalPlanningObjectiveSetDTO softObjectives = JSON.parseObject(
                JSON.toJSONString(objectives), CanonicalPlanningObjectiveSetDTO.class);
        StructureQualityPolicyDTO softPolicy = new StructureQualityPolicyDTO();
        softPolicy.setMode("soft");
        softObjectives.setStructureQualityPolicy(softPolicy);
        MutationPolicyDTO relaxedPolicy = JSON.parseObject(
                JSON.toJSONString(policy), MutationPolicyDTO.class);
        relaxedPolicy.setCountAsChurn(false);
        PlanSolverResultDTO relaxed = new StagedDeterministicPlanSolver()
                .solve(snapshot, softObjectives, relaxedPolicy).solverResult;
        LOG.info("structure-quality relaxed shadow: session={} base={}/{} relaxed={}/{} "
                        + "relaxed={} diff={}",
                state == null ? null : state.getSessionId(),
                base.getStatus(), defaultList(base.getSelectedEntityIds()).size(),
                relaxed.getStatus(), defaultList(relaxed.getSelectedEntityIds()).size(),
                structureProfile(snapshot, relaxed.getSelectedEntityIds()),
                idDiff(base.getSelectedEntityIds(), relaxed.getSelectedEntityIds()));
    }

    /**
     * 诊断 churn 锁定对结构优化的影响：忽略现有方案（current=false、不算 churn），
     * 分别跑 fresh base / fresh soft。只打日志，不写 state。
     */
    private static void logFreshStructureShadow(PlanningStateDTO state,
                                                CandidateSnapshotDTO snapshot,
                                                CanonicalPlanningObjectiveSetDTO objectives,
                                                MutationPolicyDTO policy) {
        CandidateSnapshotDTO fresh = JSON.parseObject(
                JSON.toJSONString(snapshot), CandidateSnapshotDTO.class);
        for (CandidateFactDTO fact : defaultList(fresh.getFacts())) {
            fact.setCurrent(false);
            fact.setLocked(false);
            fact.setPinned(false);
            fact.setCurrentPosition(null);
            // ratioBucket 是 @JSONField(serialize=false)，clone 后要按同一可见口径重建。
            Double visibleRatio = fact.getSchoolEnrollRatio() != null
                    ? fact.getSchoolEnrollRatio() : fact.getAdmissionRatio();
            fact.setRatioConfidence(AdmissionRatioBucketSupport.confidence(visibleRatio));
            fact.setRatioBucket(AdmissionRatioBucketSupport.bucket(fact.getTier(), visibleRatio));
            fact.setRatioBucketIndex(AdmissionRatioBucketSupport.bucketIndex(fact.getRatioBucket()));
        }
        MutationPolicyDTO freshPolicy = JSON.parseObject(
                JSON.toJSONString(policy), MutationPolicyDTO.class);
        freshPolicy.setAction("FILL");
        freshPolicy.setAllowAdd(true);
        freshPolicy.setLockExisting(false);
        freshPolicy.setCountAsChurn(false);
        freshPolicy.setInitialContentGuard(false);
        freshPolicy.setForcedAddEntityIds(new LinkedHashSet<String>());
        freshPolicy.setForcedRemoveEntityIds(new LinkedHashSet<String>());

        CanonicalPlanningObjectiveSetDTO baseObjectives = JSON.parseObject(
                JSON.toJSONString(objectives), CanonicalPlanningObjectiveSetDTO.class);
        baseObjectives.setStructureQualityPolicy(null);
        PlanSolverResultDTO freshBase = new StagedDeterministicPlanSolver()
                .solve(fresh, baseObjectives, freshPolicy).solverResult;

        CanonicalPlanningObjectiveSetDTO softObjectives = JSON.parseObject(
                JSON.toJSONString(objectives), CanonicalPlanningObjectiveSetDTO.class);
        StructureQualityPolicyDTO softPolicy = new StructureQualityPolicyDTO();
        softPolicy.setMode("soft");
        softObjectives.setStructureQualityPolicy(softPolicy);
        PlanSolverResultDTO freshSoft = new StagedDeterministicPlanSolver()
                .solve(fresh, softObjectives, freshPolicy).solverResult;
        String guard = initialContentGuardViolation(snapshot.getFacts(), freshSoft,
                "unit".equals(fresh.getCountMode()));
        LOG.info("structure-quality fresh shadow: session={} base={}/{} soft={}/{} base={} soft={} "
                        + "diff={} guard={}",
                state == null ? null : state.getSessionId(),
                freshBase.getStatus(), defaultList(freshBase.getSelectedEntityIds()).size(),
                freshSoft.getStatus(), defaultList(freshSoft.getSelectedEntityIds()).size(),
                structureProfile(fresh, freshBase.getSelectedEntityIds()),
                structureProfile(fresh, freshSoft.getSelectedEntityIds()),
                idDiff(freshBase.getSelectedEntityIds(), freshSoft.getSelectedEntityIds()),
                guard);
    }

    private static String idDiff(List<String> baseIds, List<String> shadowIds) {
        Set<String> baseSet = new LinkedHashSet<String>(defaultList(baseIds));
        Set<String> shadowSet = new LinkedHashSet<String>(defaultList(shadowIds));
        int onlyBase = 0;
        for (String id : baseSet) {
            if (!shadowSet.contains(id)) {
                onlyBase++;
            }
        }
        int onlyShadow = 0;
        for (String id : shadowSet) {
            if (!baseSet.contains(id)) {
                onlyShadow++;
            }
        }
        return onlyBase + "/" + onlyShadow;
    }

    private static String structureProfile(CandidateSnapshotDTO snapshot, List<String> selectedIds) {
        Map<String, CandidateFactDTO> byId = new LinkedHashMap<String, CandidateFactDTO>();
        for (CandidateFactDTO fact : defaultList(snapshot == null ? null : snapshot.getFacts())) {
            if (fact != null && fact.getEntityId() != null) {
                byId.put(fact.getEntityId(), fact);
            }
        }
        Map<String, Map<String, Integer>> tierBuckets = new LinkedHashMap<String, Map<String, Integer>>();
        Map<String, Integer> provinces = new LinkedHashMap<String, Integer>();
        Map<String, Integer> natures = new LinkedHashMap<String, Integer>();
        for (String tier : Lists.newArrayList("sprint", "stable", "protect")) {
            tierBuckets.put(tier, new LinkedHashMap<String, Integer>());
        }
        for (String id : defaultList(selectedIds)) {
            CandidateFactDTO fact = byId.get(id);
            if (fact == null) {
                continue;
            }
            String tier = fact.getTier();
            Map<String, Integer> buckets = tierBuckets.get(tier);
            if (buckets == null) {
                buckets = new LinkedHashMap<String, Integer>();
                tierBuckets.put(tier, buckets);
            }
            String bucket = fact.getRatioBucket();
            if (bucket == null) {
                bucket = AdmissionRatioBucketSupport.bucket(tier, fact.getAdmissionRatio());
            }
            buckets.put(bucket, buckets.getOrDefault(bucket, 0) + 1);
            String province = Strings.nullToEmpty(fact.getProvinceName()).trim();
            provinces.put(province, provinces.getOrDefault(province, 0) + 1);
            String nature = Strings.nullToEmpty(fact.getSchoolNature()).trim();
            natures.put(nature, natures.getOrDefault(nature, 0) + 1);
        }
        StringBuilder profile = new StringBuilder("tiers=");
        for (Map.Entry<String, Map<String, Integer>> entry : tierBuckets.entrySet()) {
            profile.append(entry.getKey()).append(entry.getValue()).append(';');
        }
        profile.append(" provinceTop=").append(topCounts(provinces, 3));
        profile.append(" nature=").append(natures);
        return profile.toString();
    }

    private static List<Map.Entry<String, Integer>> topCounts(Map<String, Integer> counts, int limit) {
        List<Map.Entry<String, Integer>> entries = new ArrayList<Map.Entry<String, Integer>>(counts.entrySet());
        entries.sort((left, right) -> Integer.compare(right.getValue(), left.getValue()));
        return entries.size() <= limit ? entries : new ArrayList<Map.Entry<String, Integer>>(
                entries.subList(0, limit));
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

    /**
     * 把推荐池的 requiredTierCounts 按目标数等比投影成精确档位配额。
     * 没有推荐配额、目标为空或投影不可行时返回 null，保持原求解口径。
     */
    private static TierAllocationConstraintDTO projectInitialTierAllocation(
            PlanningStateDTO state, Integer targetCount, List<Entity> selectable) {
        if (state == null || state.getCandidatePoolState() == null
                || targetCount == null || targetCount <= 0) {
            return null;
        }
        Map<String, Integer> requiredTierCounts = null;
        if (state.getInitialRecommendationState() != null
                && state.getInitialRecommendationState().getSummary() != null) {
            requiredTierCounts = state.getInitialRecommendationState()
                    .getSummary().getTierCounts();
        }
        if (requiredTierCounts == null || requiredTierCounts.isEmpty()) {
            requiredTierCounts = state.getCandidatePoolState().getRequiredTierCounts();
        }
        if (requiredTierCounts == null || requiredTierCounts.isEmpty()) {
            return null;
        }
        int sprintAvailable = 0;
        int stableAvailable = 0;
        int protectAvailable = 0;
        for (Entity entity : defaultList(selectable)) {
            String tier = TierAllocationSupport.canonicalTierKey(entity.tier());
            if ("sprint".equals(tier)) {
                sprintAvailable++;
            } else if ("stable".equals(tier)) {
                stableAvailable++;
            } else if ("protect".equals(tier)) {
                protectAvailable++;
            }
        }
        // 用可用单元数做上限，避免推荐池缺少某一档时把初始 solver 直接逼到不可行。
        TierAllocationConstraintDTO bounds = new TierAllocationConstraintDTO();
        bounds.setSprint(range(0, sprintAvailable));
        bounds.setStable(range(0, stableAvailable));
        bounds.setProtect(range(0, protectAvailable));
        TierCountsDTO current = new TierCountsDTO();
        for (Map.Entry<String, Integer> entry : requiredTierCounts.entrySet()) {
            String tier = TierAllocationSupport.canonicalTierKey(entry.getKey());
            int count = entry.getValue() == null ? 0 : Math.max(0, entry.getValue());
            if ("sprint".equals(tier)) {
                current.setSprintCount(defaultInt(current.getSprintCount()) + count);
            } else if ("stable".equals(tier)) {
                current.setStableCount(defaultInt(current.getStableCount()) + count);
            } else if ("protect".equals(tier)) {
                current.setProtectCount(defaultInt(current.getProtectCount()) + count);
            }
        }
        TierCountsDTO projected = TierStructureProjection.project(current, targetCount, bounds);
        if (projected == null) {
            return null;
        }
        TierAllocationConstraintDTO allocation = new TierAllocationConstraintDTO();
        allocation.setType("exact_counts");
        allocation.setSprintCount(projected.getSprintCount());
        allocation.setStableCount(projected.getStableCount());
        allocation.setProtectCount(projected.getProtectCount());
        allocation.setSprint(range(projected.getSprintCount()));
        allocation.setStable(range(projected.getStableCount()));
        allocation.setProtect(range(projected.getProtectCount()));
        return allocation;
    }

    private static TierCountRangeDTO range(int min, int max) {
        TierCountRangeDTO range = new TierCountRangeDTO();
        range.setMinCount(Math.max(0, min));
        range.setMaxCount(Math.max(min, max));
        return range;
    }

    private static TierCountRangeDTO range(Integer count) {
        int value = count == null ? 0 : Math.max(0, count);
        TierCountRangeDTO range = new TierCountRangeDTO();
        range.setMinCount(value);
        range.setMaxCount(value);
        return range;
    }

    private static int defaultInt(Integer value) {
        return value == null ? 0 : value;
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
