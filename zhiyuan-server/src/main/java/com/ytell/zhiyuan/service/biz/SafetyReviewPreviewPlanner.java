package com.ytell.zhiyuan.service.biz;

import com.alibaba.fastjson.JSON;
import com.google.common.base.Strings;
import com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO;
import com.ytell.zhiyuan.model.dto.planning.CanonicalPlanningObjectiveSetDTO;
import com.ytell.zhiyuan.model.dto.planning.CandidateSnapshotDTO;
import com.ytell.zhiyuan.model.dto.planning.DraftItemDTO;
import com.ytell.zhiyuan.model.dto.planning.DraftPlanStateDTO;
import com.ytell.zhiyuan.model.dto.planning.EvaluationFindingDTO;
import com.ytell.zhiyuan.model.dto.planning.FindingPostconditionDTO;
import com.ytell.zhiyuan.model.dto.planning.FixProposalActionDTO;
import com.ytell.zhiyuan.model.dto.planning.FixProposalDTO;
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
        // 与 Search 切片同一 fail-closed 口径：专业组、unit 列表、优先规则与锁定/固定项
        // 都留给后续切片，避免把保底结构修复缩水成纯加条。
        if ("majorGroup".equalsIgnoreCase(state.getCandidatePoolState().getVolunteerModel())
                || !safeList(state.getWorkingPlanState().getUnits()).isEmpty()
                || !safeList(state.getOrderedPlanState().getUnits()).isEmpty()
                || !PriorityRuleSupport.confirmedRules(state).isEmpty()) {
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
