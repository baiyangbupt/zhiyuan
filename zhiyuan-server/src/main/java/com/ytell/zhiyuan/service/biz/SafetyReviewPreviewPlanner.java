package com.ytell.zhiyuan.service.biz;

import com.alibaba.fastjson.JSON;
import com.google.common.base.Strings;
import com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO;
import com.ytell.zhiyuan.model.dto.planning.CanonicalPlanningObjectiveSetDTO;
import com.ytell.zhiyuan.model.dto.planning.CandidateSnapshotDTO;
import com.ytell.zhiyuan.model.dto.planning.DraftItemDTO;
import com.ytell.zhiyuan.model.dto.planning.DraftPlanStateDTO;
import com.ytell.zhiyuan.model.dto.planning.DraftUnitDTO;
import com.ytell.zhiyuan.model.dto.planning.EvaluationFindingDTO;
import com.ytell.zhiyuan.model.dto.planning.FindingPostconditionDTO;
import com.ytell.zhiyuan.model.dto.planning.FixProposalActionDTO;
import com.ytell.zhiyuan.model.dto.planning.FixProposalDTO;
import com.ytell.zhiyuan.model.dto.planning.FixProposalDryRunResultDTO;
import com.ytell.zhiyuan.model.dto.planning.FrozenReviewPlanDTO;
import com.ytell.zhiyuan.model.dto.planning.MutationPolicyDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedItemDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedPlanStateDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedUnitDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanCommandDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanSolverResultDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import com.ytell.zhiyuan.model.dto.planning.ReviewStateDTO;
import com.ytell.zhiyuan.model.dto.planning.StructureTargetDTO;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.function.Function;

/**
 * Safety 型审查修复切片：普通专业模式下复用 staged solver 补齐本省保底。
 *
 * <p>{@code safety_guard} fail 且命令为 {@code add_safety_items}、
 * {@code safetyMinLocalProtect > 0}、目标数 > 0 时，直接把命令里的保底下限
 * patch 到 enriched objective 的 {@link StructureTargetDTO} 上，用
 * {@link StagedDeterministicPlanSolver} 选出一份冻结方案；后置条件仍按原始
 * {@code safety_guard} 探针校验。</p>
 *
 * <p>保底下限不是 user-goal 目标，因此不走 {@code UserGoalProposalBuilder}：
 * proposal 元数据里的 canonical digest 保持 {@code compileConfirmed} 的旧口径，
 * apply 回放只写冻结方案，不落任何保底目标持久化字段。</p>
 *
 * <p>只有成功产出冻结方案且后置条件通过的路径才返回 proposal；其余情况
 * （模式不支持、选择集不完整、求解/物化失败、后置条件不满足等）一律返回
 * {@code null}，与 Safety 切片上线前的提案集保持一致，避免阻塞型占位提案
 * 抢在 Direct 提案之前改变既有预览顺序。</p>
 */
final class SafetyReviewPreviewPlanner {
    private static final String SAFETY_GUARD = "safety_guard";
    private static final String STRATEGY = RepairProposalTaxonomy.Strategy.FILL_MISSING_COUNT;
    private static final String SOURCE_STRATEGY = RepairProposalTaxonomy.Strategy.ADD_SAFETY_ITEMS;
    private static final String POLICY_ACTION = "FILL";
    private static final String VOLUNTEER = "volunteer";

    private final FindingPostconditionEvaluator postconditionEvaluator = new FindingPostconditionEvaluator();

    FixProposalDTO plan(PlanningStateDTO state, List<CandidateItemDTO> candidates,
                        EvaluationFindingDTO finding,
                        Function<PlanningStateDTO, ReviewStateDTO> reevaluate,
                        boolean confirmable) {
        PlanCommandDTO command = finding == null ? null : finding.getSuggestedCommand();
        if (finding == null || command == null || !SAFETY_GUARD.equals(finding.getCode())
                || !"fail".equals(finding.getResultStatus())
                || !SOURCE_STRATEGY.equals(RepairProposalTaxonomy.normalizeStrategy(command.getStrategy()))
                || command.getSafetyMinLocalProtect() == null || command.getSafetyMinLocalProtect() <= 0
                || command.getTargetCount() == null || command.getTargetCount() <= 0) {
            return null;
        }
        FixProposalDTO proposal = proposal(state, finding, command);
        if (state == null || state.getCandidatePoolState() == null
                || state.getWorkingPlanState() == null || state.getOrderedPlanState() == null
                || reevaluate == null
                || Strings.isNullOrEmpty(command.getEvaluationVersion())
                || Strings.isNullOrEmpty(command.getCommandDigest())) {
            return null;
        }
        // 与 Search 切片同一 fail-closed 口径：优先规则与锁定/固定项留给确认链校验；
        // 组模式（专业组/专业单元）走 planUnits，普通专业模式保持原有路径。
        boolean unitMode = "majorGroup".equalsIgnoreCase(
                state.getCandidatePoolState().getVolunteerModel())
                || !safeList(state.getWorkingPlanState().getUnits()).isEmpty()
                || !safeList(state.getOrderedPlanState().getUnits()).isEmpty();
        if (unitMode) {
            return planUnits(proposal, state, candidates, finding, command, reevaluate, confirmable);
        }
        if (!PriorityRuleSupport.confirmedRules(state).isEmpty()) {
            return null;
        }
        List<DraftItemDTO> workingItems = safeList(state.getWorkingPlanState().getItems());
        List<OrderedItemDTO> ordered = new ArrayList<OrderedItemDTO>(safeList(
                state.getOrderedPlanState().getItems()));
        Map<String, OrderedItemDTO> orderedById = new LinkedHashMap<String, OrderedItemDTO>();
        Set<String> selectedIds = new LinkedHashSet<String>();
        if (workingItems.isEmpty() || ordered.isEmpty() || ordered.size() != workingItems.size()) {
            return null;
        }
        ordered.sort(Comparator.comparing(item -> item.getPosition() == null
                ? Integer.MAX_VALUE : item.getPosition()));
        for (DraftItemDTO item : workingItems) {
            if (item == null || Strings.isNullOrEmpty(item.getVolunteerId())
                    || Boolean.TRUE.equals(item.getLocked()) || !selectedIds.add(item.getVolunteerId())) {
                return null;
            }
        }
        for (int index = 0; index < ordered.size(); index++) {
            OrderedItemDTO item = ordered.get(index);
            if (item == null || Strings.isNullOrEmpty(item.getVolunteerId())
                    || item.getPosition() == null || item.getPosition() != index + 1
                    || Boolean.TRUE.equals(item.getLocked())
                    || Boolean.TRUE.equals(item.getPinned()) || item.getPinnedPosition() != null
                    || orderedById.put(item.getVolunteerId(), item) != null) {
                return null;
            }
        }
        if (!selectedIds.equals(orderedById.keySet())) {
            return null;
        }

        // 保底下限不是用户目标：canonical digest 保持 compileConfirmed 的旧口径，
        // 只在 solver 使用的副本上 patch StructureTarget。
        CanonicalPlanningObjectiveSetDTO canonical = PlanningObjectiveCompiler.compileConfirmed(state);
        CanonicalPlanningObjectiveSetDTO objectives = copy(canonical, CanonicalPlanningObjectiveSetDTO.class);
        MutationPolicyDTO policy = new MutationPolicyDTO();
        policy.setAction(POLICY_ACTION);
        policy.setLockExisting(false);
        policy.setCountAsChurn(true);
        policy.setRequireCompensationSafe(true);
        PlanningObjectiveCompiler.enrichV2(state, objectives, policy);
        StructureTargetDTO structureTarget = objectives.getStructureTarget();
        if (structureTarget == null) {
            structureTarget = new StructureTargetDTO();
            objectives.setStructureTarget(structureTarget);
        }
        structureTarget.setMinLocalProtect(command.getSafetyMinLocalProtect());
        structureTarget.setSafetyFloorMode("applicable");

        CandidateSnapshotDTO snapshot = CandidateSnapshotBuilder.build(
                state, candidates, CandidateSnapshotBuilder.CurrentSource.ORDERED_FIRST);
        PlanSolverResultDTO solverResult;
        try {
            solverResult = new StagedDeterministicPlanSolver()
                    .solve(snapshot, objectives, policy).solverResult;
        } catch (RuntimeException unavailable) {
            return null;
        }
        if (solverResult == null || !"ready".equals(solverResult.getStatus())) {
            return null;
        }

        Map<String, CandidateItemDTO> candidatesById = new LinkedHashMap<String, CandidateItemDTO>();
        for (CandidateItemDTO candidate : safeList(candidates)) {
            if (candidate != null && !Strings.isNullOrEmpty(candidate.getVolunteerId())) {
                candidatesById.putIfAbsent(candidate.getVolunteerId(), candidate);
            }
        }
        List<String> selectedEntityIds = new ArrayList<String>(safeList(solverResult.getSelectedEntityIds()));
        List<String> orderedEntityIds = new ArrayList<String>(safeList(solverResult.getOrderedEntityIds()));
        String factsDigest = DirectReviewPreviewPlanner.factsDigestForEntities(
                selectedEntityIds, candidates);
        if (factsDigest == null) {
            return null;
        }
        List<CandidateItemDTO> selectedFacts = new ArrayList<CandidateItemDTO>();
        for (String identity : selectedEntityIds) {
            selectedFacts.add(copy(candidatesById.get(identity), CandidateItemDTO.class));
        }

        PlanningStateDTO after = copy(state, PlanningStateDTO.class);
        try {
            CanonicalPlanningRuntime.applyFrozenSelection(after, candidates, solverResult);
        } catch (RuntimeException unavailable) {
            return null;
        }
        after.getOrderedPlanState().setUnits(new ArrayList<OrderedUnitDTO>());
        after.getOrderedPlanState().setItems(SearchReviewPreviewPlanner.orderedItemsFromSolver(
                orderedEntityIds, orderedById, candidatesById));
        if (after.getWorkingPlanState().getItems() == null
                || after.getWorkingPlanState().getItems().size() != selectedEntityIds.size()) {
            return null;
        }

        ReviewStateDTO afterReview;
        try {
            afterReview = reevaluate.apply(copy(after, PlanningStateDTO.class));
        } catch (RuntimeException unavailable) {
            return null;
        }
        FindingPostconditionDTO postcondition = postconditionEvaluator.evaluate(SAFETY_GUARD, afterReview);
        proposal.setFindingPostcondition(postcondition);
        if (!Boolean.TRUE.equals(postcondition.getSatisfied())) {
            return null;
        }

        FrozenReviewPlanDTO frozen = new FrozenReviewPlanDTO();
        frozen.setWorkingPlan(copy(after.getWorkingPlanState(), DraftPlanStateDTO.class));
        frozen.setOrderedPlan(copy(after.getOrderedPlanState(), OrderedPlanStateDTO.class));
        frozen.setSelectedEntityIds(selectedEntityIds);
        frozen.setOrderedEntityIds(orderedEntityIds);
        frozen.setSelectedFacts(selectedFacts);
        frozen.setFactsDigest(factsDigest);
        proposal.setFrozenReviewPlan(frozen);
        adapt(proposal, solverResult, command, state, canonical, workingItems.size());
        proposal.setPlanContentDigest(DirectReviewPreviewPlanner.planContentDigest(state));
        // 摘要必须在“提升为 ready”之前算：prepare 用确认模式重算时若把
        // dryRunResult.status 的差异算进去，合法的确认会被判 409。
        proposal.getDryRunResult().setStatus("preview_only");
        proposal.setProposalId("fp_" + DirectReviewPreviewPlanner.digestJson(Arrays.asList(
                command.getEvaluationVersion(), proposal.getPlanContentDigest(),
                command.getCommandDigest(), proposal.getActions())).substring(0, 16));
        proposal.setPreviewDigest(DirectReviewPreviewPlanner.digestJson(Arrays.asList(
                proposal.getProposalId(), command.getEvaluationVersion(),
                proposal.getPlanContentDigest(), proposal.getCanonicalObjectiveDigest(), frozen,
                proposal.getActions(), proposal.getDryRunResult(), postcondition)));
        if (confirmable) {
            proposal.setStatus("ready");
            proposal.setRequiresConfirmation(true);
            proposal.setSourceVersionGuard(state.getVersion());
            command.setExecutable(true);
            proposal.getDryRunResult().setStatus("ready");
        } else {
            proposal.setBlockingReason("review_fix_prepare_unavailable");
            proposal.getBlockingReasonCodes().add("review_fix_prepare_unavailable");
        }
        return proposal;
    }

    /**
     * 组模式（专业组/专业单元）的本省保底补齐：目标数与当前数都按 unit 计，
     * 直接从 staged solver 拿一份“含本省保底”的 unit 选择集，再按 Search 组模式
     * 同一套物化逻辑重建 working/ordered units 与 ordered items。
     *
     * <p>选择集从 ordered units 派生（工作台可能只存 draft items、不存 working units）；
     * ordered units 允许稀疏但必须严格递增且唯一，锁定/置顶、优先规则与不自洽的
     * unit 列表一律 fail closed，保持与普通专业模式相同的“无法冻结就返回 null”口径。</p>
     */
    private FixProposalDTO planUnits(FixProposalDTO proposal, PlanningStateDTO state,
                                     List<CandidateItemDTO> candidates,
                                     EvaluationFindingDTO finding, PlanCommandDTO command,
                                     Function<PlanningStateDTO, ReviewStateDTO> reevaluate,
                                     boolean confirmable) {
        if (!PriorityRuleSupport.confirmedRules(state).isEmpty()) {
            return null;
        }
        List<OrderedUnitDTO> currentOrdered = new ArrayList<OrderedUnitDTO>(
                safeList(state.getOrderedPlanState().getUnits()));
        if (currentOrdered.isEmpty()) {
            return null;
        }
        currentOrdered.sort(Comparator.comparing(unit -> unit == null || unit.getPosition() == null
                ? Integer.MAX_VALUE : unit.getPosition()));
        Map<String, OrderedUnitDTO> orderedById = new LinkedHashMap<String, OrderedUnitDTO>();
        Integer previousPosition = null;
        for (OrderedUnitDTO unit : currentOrdered) {
            // 线上 group 方案的位置可能稀疏（1,2,8,9...），只要求严格递增且唯一；
            // 物化时会统一重排为 1..n。
            if (unit == null || Strings.isNullOrEmpty(unit.getUnitId()) || unit.getPosition() == null
                    || (previousPosition != null && unit.getPosition() <= previousPosition)
                    || orderedById.put(unit.getUnitId(), unit) != null) {
                return null;
            }
            if (Boolean.TRUE.equals(unit.getLocked()) || Boolean.TRUE.equals(unit.getPinned())
                    || unit.getPinnedPosition() != null) {
                return null;
            }
            previousPosition = unit.getPosition();
        }

        // volunteerModel 缺失但存在 units 时，副本显式归一为 majorGroup：objectives、
        // snapshot 与 applyFrozenSelection 必须同源按 unit 口径，否则会把 unit 身份
        // 误当志愿者身份。
        PlanningStateDTO copy = copy(state, PlanningStateDTO.class);
        SearchReviewPreviewPlanner.normalizeGroupMode(copy);
        CanonicalPlanningObjectiveSetDTO canonical = PlanningObjectiveCompiler.compileConfirmed(copy);
        CanonicalPlanningObjectiveSetDTO objectives = copy(canonical, CanonicalPlanningObjectiveSetDTO.class);
        MutationPolicyDTO policy = new MutationPolicyDTO();
        policy.setAction(POLICY_ACTION);
        policy.setLockExisting(false);
        policy.setCountAsChurn(true);
        policy.setRequireCompensationSafe(true);
        PlanningObjectiveCompiler.enrichV2(copy, objectives, policy);
        StructureTargetDTO structureTarget = objectives.getStructureTarget();
        if (structureTarget == null) {
            structureTarget = new StructureTargetDTO();
            objectives.setStructureTarget(structureTarget);
        }
        structureTarget.setMinLocalProtect(command.getSafetyMinLocalProtect());
        structureTarget.setSafetyFloorMode("applicable");

        CandidateSnapshotDTO snapshot = CandidateSnapshotBuilder.build(
                copy, candidates, CandidateSnapshotBuilder.CurrentSource.ORDERED_FIRST);
        PlanSolverResultDTO solverResult;
        try {
            solverResult = new StagedDeterministicPlanSolver()
                    .solve(snapshot, objectives, policy).solverResult;
        } catch (RuntimeException unavailable) {
            return null;
        }
        if (solverResult == null || !"ready".equals(solverResult.getStatus())) {
            return null;
        }
        List<String> selectedEntityIds = new ArrayList<String>(
                safeList(solverResult.getSelectedEntityIds()));
        List<String> orderedEntityIds = new ArrayList<String>(
                safeList(solverResult.getOrderedEntityIds()));
        if (selectedEntityIds.isEmpty() || orderedEntityIds.isEmpty()
                || new LinkedHashSet<String>(selectedEntityIds).size() != selectedEntityIds.size()
                || new LinkedHashSet<String>(orderedEntityIds).size() != orderedEntityIds.size()
                || !new LinkedHashSet<String>(selectedEntityIds)
                .equals(new LinkedHashSet<String>(orderedEntityIds))) {
            return null;
        }

        Map<String, CandidateItemDTO> candidatesById =
                SearchReviewPreviewPlanner.candidatesById(candidates);
        PlanningStateDTO after = copy(state, PlanningStateDTO.class);
        SearchReviewPreviewPlanner.normalizeGroupMode(after);
        try {
            CanonicalPlanningRuntime.applyFrozenSelection(after, candidates, solverResult);
        } catch (RuntimeException unavailable) {
            return null;
        }
        Map<String, DraftItemDTO> workingItemsById = new LinkedHashMap<String, DraftItemDTO>();
        for (DraftItemDTO item : safeList(after.getWorkingPlanState().getItems())) {
            if (item != null && !Strings.isNullOrEmpty(item.getVolunteerId())) {
                workingItemsById.put(item.getVolunteerId(), item);
            }
        }
        List<OrderedUnitDTO> orderedUnits = SearchReviewPreviewPlanner.orderedUnitsFromSolver(
                orderedEntityIds, orderedById,
                safeList(after.getWorkingPlanState().getUnits()), candidatesById);
        if (orderedUnits == null) {
            return null;
        }
        Map<String, OrderedItemDTO> existingOrderedItemsById = new LinkedHashMap<String, OrderedItemDTO>();
        for (OrderedItemDTO item : safeList(state.getOrderedPlanState().getItems())) {
            if (item != null && !Strings.isNullOrEmpty(item.getVolunteerId())) {
                existingOrderedItemsById.put(item.getVolunteerId(), item);
            }
        }
        List<OrderedItemDTO> orderedItems = SearchReviewPreviewPlanner.orderedItemsFromUnits(
                orderedUnits, existingOrderedItemsById, workingItemsById, candidatesById);
        if (orderedItems == null) {
            return null;
        }
        after.getOrderedPlanState().setUnits(orderedUnits);
        after.getOrderedPlanState().setItems(orderedItems);

        // 组模式事实摘要按 unit→major 顺序；apply 侧用冻结 units 重算同一口径。
        List<CandidateItemDTO> unitFacts = DirectReviewPreviewPlanner.factsForUnits(
                selectedEntityIds, orderedUnits, candidates);
        if (unitFacts == null) {
            return null;
        }
        String factsDigest = DirectReviewPreviewPlanner.digestJson(unitFacts);
        List<CandidateItemDTO> selectedFacts = new ArrayList<CandidateItemDTO>();
        for (CandidateItemDTO fact : unitFacts) {
            selectedFacts.add(copy(fact, CandidateItemDTO.class));
        }

        ReviewStateDTO afterReview;
        try {
            afterReview = reevaluate.apply(copy(after, PlanningStateDTO.class));
        } catch (RuntimeException unavailable) {
            return null;
        }
        FindingPostconditionDTO postcondition = postconditionEvaluator.evaluate(SAFETY_GUARD, afterReview);
        proposal.setFindingPostcondition(postcondition);
        if (!Boolean.TRUE.equals(postcondition.getSatisfied())) {
            return null;
        }

        FrozenReviewPlanDTO frozen = new FrozenReviewPlanDTO();
        frozen.setWorkingPlan(copy(after.getWorkingPlanState(), DraftPlanStateDTO.class));
        frozen.setOrderedPlan(copy(after.getOrderedPlanState(), OrderedPlanStateDTO.class));
        frozen.setSelectedEntityIds(selectedEntityIds);
        frozen.setOrderedEntityIds(orderedEntityIds);
        frozen.setSelectedFacts(selectedFacts);
        frozen.setFactsDigest(factsDigest);
        proposal.setFrozenReviewPlan(frozen);
        adaptUnits(proposal, solverResult, command, state, canonical,
                currentOrdered, orderedUnits, orderedItems);
        proposal.setPlanContentDigest(DirectReviewPreviewPlanner.planContentDigest(state));
        // 摘要必须在“提升为 ready”之前算，确认模式重算不得把 status 差异算进去。
        proposal.getDryRunResult().setStatus("preview_only");
        proposal.setProposalId("fp_" + DirectReviewPreviewPlanner.digestJson(Arrays.asList(
                command.getEvaluationVersion(), proposal.getPlanContentDigest(),
                command.getCommandDigest(), proposal.getActions())).substring(0, 16));
        proposal.setPreviewDigest(DirectReviewPreviewPlanner.digestJson(Arrays.asList(
                proposal.getProposalId(), command.getEvaluationVersion(),
                proposal.getPlanContentDigest(), proposal.getCanonicalObjectiveDigest(), frozen,
                proposal.getActions(), proposal.getDryRunResult(), postcondition)));
        if (confirmable) {
            proposal.setStatus("ready");
            proposal.setRequiresConfirmation(true);
            proposal.setSourceVersionGuard(state.getVersion());
            command.setExecutable(true);
            proposal.getDryRunResult().setStatus("ready");
        } else {
            proposal.setBlockingReason("review_fix_prepare_unavailable");
            proposal.getBlockingReasonCodes().add("review_fix_prepare_unavailable");
        }
        return proposal;
    }

    /**
     * 组模式 Safety 提案元数据与 unit 级动作：add/remove/reorder 全部以 unit 计，
     * dryRun 同时给出 unit 与志愿者总量，口径与 Search 组模式补齐一致。
     */
    private void adaptUnits(FixProposalDTO proposal, PlanSolverResultDTO solverResult,
                            PlanCommandDTO command, PlanningStateDTO state,
                            CanonicalPlanningObjectiveSetDTO canonical,
                            List<OrderedUnitDTO> currentOrdered,
                            List<OrderedUnitDTO> orderedUnits,
                            List<OrderedItemDTO> orderedItems) {
        proposal.setProposalSource(RepairProposalTaxonomy.ProposalSource.REVIEW_CHECK);
        proposal.setSourceVersion(state.getVersion());
        proposal.setStrategy(STRATEGY);
        proposal.setSourceStrategy(command.getSourceStrategy());
        proposal.setFindingCode(SAFETY_GUARD);
        proposal.setEvaluationVersion(command.getEvaluationVersion());
        proposal.setCommandDigest(command.getCommandDigest());
        proposal.setTitle("本省保底补齐预览");
        proposal.setSummary("从当前候选池补入本省保底专业组；确认后按冻结方案原样回放。");
        proposal.setImpact("只写回工作草案与排序态；本省保底要求仍由当前状态派生，不新增持久化目标。");
        // 预 enrich 的旧口径：与 apply 侧 compileConfirmed 重算保持逐字一致。
        proposal.setCanonicalObjectiveDigest(canonical.getObjectiveDigest());
        proposal.setSolverVersion(solverResult.getSolverVersion());
        proposal.setSolverInputDigest(solverResult.getInputDigest());
        proposal.setHardObjectiveVersion(solverResult.getHardObjectiveVersion());
        proposal.setSolverResult(copy(solverResult, PlanSolverResultDTO.class));

        List<String> removed = new ArrayList<String>(safeList(solverResult.getRemoveEntityIds()));
        List<String> added = new ArrayList<String>(safeList(solverResult.getAddEntityIds()));
        List<String> orderedIds = new ArrayList<String>(safeList(solverResult.getOrderedEntityIds()));
        List<String> beforeOrderedIds = new ArrayList<String>();
        Map<String, OrderedUnitDTO> beforeById = new LinkedHashMap<String, OrderedUnitDTO>();
        for (OrderedUnitDTO unit : currentOrdered) {
            beforeOrderedIds.add(unit.getUnitId());
            beforeById.put(unit.getUnitId(), unit);
        }
        Map<String, OrderedUnitDTO> afterById = new LinkedHashMap<String, OrderedUnitDTO>();
        for (OrderedUnitDTO unit : orderedUnits) {
            afterById.put(unit.getUnitId(), unit);
        }
        Set<String> removedVolunteers = volunteerIdsForUnits(removed, beforeById);
        Set<String> addedVolunteers = volunteerIdsForUnits(added, afterById);
        Set<String> affectedUnits = new LinkedHashSet<String>();
        affectedUnits.addAll(removed);
        affectedUnits.addAll(added);
        Set<String> affectedVolunteers = new LinkedHashSet<String>();
        affectedVolunteers.addAll(removedVolunteers);
        affectedVolunteers.addAll(addedVolunteers);
        proposal.setAffectedUnitIds(new ArrayList<String>(affectedUnits));
        proposal.setAffectedVolunteerIds(new ArrayList<String>(affectedVolunteers));

        proposal.setTargetCountBefore(currentOrdered.size());
        proposal.setTargetCountAfter(orderedUnits.size());
        proposal.setAddedCount(addedVolunteers.size());
        proposal.setAddedUnitCount(added.size());
        proposal.setRemovedCount(removed.size());

        if (!removed.isEmpty()) {
            FixProposalActionDTO removeAction = new FixProposalActionDTO();
            removeAction.setActionType(RepairProposalTaxonomy.ActionType.REMOVE_VOLUNTEERS);
            removeAction.setLevel("unit");
            removeAction.setSourceCheckCode(SAFETY_GUARD);
            removeAction.setSummary("移出 " + removed.size() + " 个现有专业组，为本省保底让位");
            removeAction.setUnitIds(new ArrayList<String>(removed));
            removeAction.setRemoveUnitIds(new ArrayList<String>(removed));
            removeAction.setVolunteerIds(new ArrayList<String>(removedVolunteers));
            removeAction.setRemoveVolunteerIds(new ArrayList<String>(removedVolunteers));
            removeAction.setTotalUnitCount(removed.size());
            removeAction.setTotalVolunteerCount(removedVolunteers.size());
            proposal.getActions().add(removeAction);
        }
        if (!added.isEmpty()) {
            // 与 fill 链路一致：add 侧使用 fill_total_count。
            FixProposalActionDTO addAction = new FixProposalActionDTO();
            addAction.setActionType(RepairProposalTaxonomy.ActionType.FILL_TOTAL_COUNT);
            addAction.setLevel("unit");
            addAction.setSourceCheckCode(SAFETY_GUARD);
            addAction.setSummary("从当前候选池补入 " + added.size() + " 个本省保底专业组");
            addAction.setUnitIds(new ArrayList<String>(added));
            addAction.setCandidateUnitIds(new ArrayList<String>(added));
            addAction.setVolunteerIds(new ArrayList<String>(addedVolunteers));
            addAction.setCandidateVolunteerIds(new ArrayList<String>(addedVolunteers));
            addAction.setTotalUnitCount(added.size());
            addAction.setTotalVolunteerCount(addedVolunteers.size());
            proposal.getActions().add(addAction);
        }
        if (!orderedIds.isEmpty() && !orderedIds.equals(beforeOrderedIds)) {
            FixProposalActionDTO reorderAction = new FixProposalActionDTO();
            reorderAction.setActionType(RepairProposalTaxonomy.ActionType.REORDER_VOLUNTEERS);
            reorderAction.setLevel("unit");
            reorderAction.setSourceCheckCode(SAFETY_GUARD);
            reorderAction.setSummary("按冻结后的顺序写回 " + orderedIds.size() + " 个专业组");
            reorderAction.setUnitIds(new ArrayList<String>(orderedIds));
            reorderAction.setTotalUnitCount(orderedIds.size());
            proposal.getActions().add(reorderAction);
        }

        Set<String> beforeVolunteerIds = volunteerIdsForUnits(beforeOrderedIds, beforeById);
        Set<String> afterVolunteerIds = new LinkedHashSet<String>();
        for (OrderedItemDTO item : orderedItems) {
            afterVolunteerIds.add(item.getVolunteerId());
        }
        FixProposalDryRunResultDTO dryRun = proposal.getDryRunResult();
        dryRun.setBeforeUnitTotal(currentOrdered.size());
        dryRun.setAfterUnitTotal(orderedUnits.size());
        dryRun.setBeforeUnitIds(new LinkedHashSet<String>(beforeOrderedIds));
        dryRun.setAfterUnitIds(new LinkedHashSet<String>(orderedIds));
        dryRun.setBeforeVolunteerTotal(beforeVolunteerIds.size());
        dryRun.setAfterVolunteerTotal(afterVolunteerIds.size());
        dryRun.setBeforeVolunteerIds(beforeVolunteerIds);
        dryRun.setAfterVolunteerIds(afterVolunteerIds);
        dryRun.setAddUnitCount(added.size());
        dryRun.setAddVolunteerCount(addedVolunteers.size());
        dryRun.setRemoveUnitCount(removed.size());
        dryRun.setRemoveVolunteerCount(removedVolunteers.size());
        dryRun.setAffectedUnitCount(affectedUnits.size());
        dryRun.setAffectedVolunteerCount(affectedVolunteers.size());
    }

    private Set<String> volunteerIdsForUnits(List<String> unitIds,
                                             Map<String, OrderedUnitDTO> unitsById) {
        Set<String> result = new LinkedHashSet<String>();
        for (String unitId : safeList(unitIds)) {
            OrderedUnitDTO unit = unitsById.get(unitId);
            if (unit == null) {
                continue;
            }
            for (com.ytell.zhiyuan.model.dto.planning.PlanningUnitMajorDTO major
                    : safeList(unit.getMajorItems())) {
                if (major != null && !Strings.isNullOrEmpty(major.getVolunteerId())) {
                    result.add(major.getVolunteerId());
                }
            }
        }
        return result;
    }

    private void adapt(FixProposalDTO proposal, PlanSolverResultDTO solverResult,
                       PlanCommandDTO command, PlanningStateDTO state,
                       CanonicalPlanningObjectiveSetDTO canonical, int beforeCount) {
        proposal.setProposalSource(RepairProposalTaxonomy.ProposalSource.REVIEW_CHECK);
        proposal.setSourceVersion(state.getVersion());
        proposal.setStrategy(STRATEGY);
        proposal.setSourceStrategy(command.getSourceStrategy());
        proposal.setFindingCode(SAFETY_GUARD);
        proposal.setEvaluationVersion(command.getEvaluationVersion());
        proposal.setCommandDigest(command.getCommandDigest());
        proposal.setTitle("本省保底补齐预览");
        proposal.setSummary("从当前候选池补入本省保底志愿；确认后按冻结方案原样回放。");
        proposal.setImpact("只写回工作草案与排序态；本省保底要求仍由当前状态派生，不新增持久化目标。");
        // 预 enrich 的旧口径：与 apply 侧 compileConfirmed 重算保持逐字一致。
        proposal.setCanonicalObjectiveDigest(canonical.getObjectiveDigest());
        proposal.setSolverVersion(solverResult.getSolverVersion());
        proposal.setSolverInputDigest(solverResult.getInputDigest());
        proposal.setHardObjectiveVersion(solverResult.getHardObjectiveVersion());
        proposal.setSolverResult(copy(solverResult, PlanSolverResultDTO.class));
        proposal.setTargetCountBefore(beforeCount);
        proposal.setTargetCountAfter(defaultList(solverResult.getSelectedEntityIds()).size());
        proposal.setAddedCount(defaultList(solverResult.getAddEntityIds()).size());
        proposal.setAddedUnitCount(0);
        proposal.setRemovedCount(defaultList(solverResult.getRemoveEntityIds()).size());

        List<String> removed = new ArrayList<String>(safeList(solverResult.getRemoveEntityIds()));
        List<String> added = new ArrayList<String>(safeList(solverResult.getAddEntityIds()));
        List<String> orderedIds = new ArrayList<String>(safeList(solverResult.getOrderedEntityIds()));
        Set<String> affected = new LinkedHashSet<String>();
        affected.addAll(removed);
        affected.addAll(added);
        proposal.setAffectedVolunteerIds(new ArrayList<String>(affected));

        if (!removed.isEmpty()) {
            FixProposalActionDTO removeAction = new FixProposalActionDTO();
            removeAction.setActionType(RepairProposalTaxonomy.ActionType.REMOVE_VOLUNTEERS);
            removeAction.setLevel(VOLUNTEER);
            removeAction.setSourceCheckCode(SAFETY_GUARD);
            removeAction.setSummary("移出 " + removed.size() + " 条现有志愿，为本省保底让位");
            removeAction.setVolunteerIds(new ArrayList<String>(removed));
            removeAction.setRemoveVolunteerIds(new ArrayList<String>(removed));
            removeAction.setTotalVolunteerCount(removed.size());
            proposal.getActions().add(removeAction);
        }
        if (!added.isEmpty()) {
            // 与 fill 链路一致：add 侧使用 fill_total_count。
            FixProposalActionDTO addAction = new FixProposalActionDTO();
            addAction.setActionType(RepairProposalTaxonomy.ActionType.FILL_TOTAL_COUNT);
            addAction.setLevel(VOLUNTEER);
            addAction.setSourceCheckCode(SAFETY_GUARD);
            addAction.setSummary("从当前候选池补入 " + added.size() + " 条本省保底志愿");
            addAction.setVolunteerIds(new ArrayList<String>(added));
            addAction.setCandidateVolunteerIds(new ArrayList<String>(added));
            addAction.setTotalVolunteerCount(added.size());
            proposal.getActions().add(addAction);
        }
        List<OrderedItemDTO> beforeOrdered = new ArrayList<OrderedItemDTO>(safeList(
                state.getOrderedPlanState().getItems()));
        beforeOrdered.sort(Comparator.comparing(item -> item == null || item.getPosition() == null
                ? Integer.MAX_VALUE : item.getPosition()));
        List<String> beforeOrderedIds = new ArrayList<String>();
        for (OrderedItemDTO item : beforeOrdered) {
            if (item != null && !Strings.isNullOrEmpty(item.getVolunteerId())) {
                beforeOrderedIds.add(item.getVolunteerId());
            }
        }
        if (!orderedIds.isEmpty() && !orderedIds.equals(beforeOrderedIds)) {
            FixProposalActionDTO reorderAction = new FixProposalActionDTO();
            reorderAction.setActionType(RepairProposalTaxonomy.ActionType.REORDER_VOLUNTEERS);
            reorderAction.setLevel(VOLUNTEER);
            reorderAction.setSourceCheckCode(SAFETY_GUARD);
            reorderAction.setSummary("按冻结后的顺序写回 " + orderedIds.size() + " 条志愿");
            reorderAction.setVolunteerIds(new ArrayList<String>(orderedIds));
            reorderAction.setTotalVolunteerCount(orderedIds.size());
            proposal.getActions().add(reorderAction);
        }

        proposal.getDryRunResult().setBeforeVolunteerTotal(beforeCount);
        proposal.getDryRunResult().setAfterVolunteerTotal(
                defaultList(solverResult.getSelectedEntityIds()).size());
        proposal.getDryRunResult().setBeforeVolunteerIds(new LinkedHashSet<String>(beforeOrderedIds));
        proposal.getDryRunResult().setAfterVolunteerIds(
                new LinkedHashSet<String>(safeList(solverResult.getSelectedEntityIds())));
        proposal.getDryRunResult().setAddVolunteerCount(added.size());
        proposal.getDryRunResult().setRemoveVolunteerCount(removed.size());
        proposal.getDryRunResult().setAffectedVolunteerCount(affected.size());
    }

    private FixProposalDTO proposal(PlanningStateDTO state, EvaluationFindingDTO finding,
                                    PlanCommandDTO command) {
        FixProposalDTO proposal = new FixProposalDTO();
        proposal.setStatus("preview_only");
        proposal.setRequiresConfirmation(false);
        proposal.setProposalSource(RepairProposalTaxonomy.ProposalSource.REVIEW_CHECK);
        proposal.setSourceVersion(state == null ? null : state.getVersion());
        proposal.setStrategy(STRATEGY);
        proposal.setSourceStrategy(command.getSourceStrategy());
        proposal.setFindingCode(finding.getCode());
        proposal.setEvaluationVersion(command.getEvaluationVersion());
        proposal.setCommandDigest(command.getCommandDigest());
        proposal.setTitle("本省保底补齐预览");
        proposal.setSummary("只读冻结预览；确认执行入口尚未启用。");
        proposal.getSourceCheckCodes().add(finding.getCode());
        return proposal;
    }

    private <Value> Value copy(Value value, Class<Value> type) {
        return value == null ? null : JSON.parseObject(JSON.toJSONString(value), type);
    }

    private <Value> List<Value> defaultList(List<Value> values) {
        return values == null ? new ArrayList<Value>() : values;
    }

    private <Value> List<Value> safeList(List<Value> values) {
        return values == null ? new ArrayList<Value>() : values;
    }
}
