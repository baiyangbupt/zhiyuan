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
import com.ytell.zhiyuan.model.dto.planning.TierAllocationConstraintDTO;
import com.ytell.zhiyuan.model.dto.planning.TierCountsDTO;

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
 * 配比（ratio_distribution）审查修复切片：普通专业模式下复用 staged solver
 * 按命令里的冲稳保配额重新配比。
 *
 * <p>{@code ratio_distribution} fail 且命令为 {@code rebalance_tier_ratio}、
 * {@code tierConstraint != null}、目标数 > 0 时，把命令里的配额 patch 到
 * enriched objective 上，并根据当前排序态的档位分布投影出目标锚
 * （{@link TierStructureProjection}），由 {@link StagedDeterministicPlanSolver}
 * 选出一份冻结方案；后置条件仍按原始 {@code ratio_distribution} 探针校验。</p>
 *
 * <p>配额不是 user-goal 目标：proposal 元数据里的 canonical digest 保持
 * {@code compileConfirmed} 的旧口径，apply 回放只写冻结方案，不落任何档位配额
 * 持久化字段（配额已在 state 里确认）。</p>
 *
 * <p>只有成功产出冻结方案且后置条件通过的路径才返回 proposal；其余情况
 * （模式不支持、选择集不完整、求解/物化失败、后置条件不满足等）一律返回
 * {@code null}，与 Direct/Safety 切片一致，避免阻塞型占位提案抢在既有预览
 * 顺序之前改变预览结果。</p>
 */
final class RatioReviewPreviewPlanner {
    private static final String RATIO_DISTRIBUTION = "ratio_distribution";
    private static final String STRATEGY = RepairProposalTaxonomy.Strategy.FILL_MISSING_COUNT;
    private static final String SOURCE_STRATEGY = RepairProposalTaxonomy.Strategy.REBALANCE_TIER_RATIO;
    private static final String POLICY_ACTION = "FILL";
    private static final String VOLUNTEER = "volunteer";

    private final FindingPostconditionEvaluator postconditionEvaluator = new FindingPostconditionEvaluator();

    FixProposalDTO plan(PlanningStateDTO state, List<CandidateItemDTO> candidates,
                        EvaluationFindingDTO finding,
                        Function<PlanningStateDTO, ReviewStateDTO> reevaluate,
                        boolean confirmable) {
        PlanCommandDTO command = finding == null ? null : finding.getSuggestedCommand();
        if (finding == null || command == null || !RATIO_DISTRIBUTION.equals(finding.getCode())
                || !"fail".equals(finding.getResultStatus())
                || !SOURCE_STRATEGY.equals(RepairProposalTaxonomy.normalizeStrategy(command.getStrategy()))
                || command.getTierConstraint() == null
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
        // 与 Search/Safety 切片同一 fail-closed 口径：专业组、unit 列表、优先规则与
        // 锁定/固定项都留给后续切片，避免把配比修复缩水成纯替换。
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

        // 配额不是用户目标：canonical digest 保持 compileConfirmed 的旧口径，
        // 只在 solver 使用的副本上 patch tierConstraint 与档位锚。
        CanonicalPlanningObjectiveSetDTO canonical = PlanningObjectiveCompiler.compileConfirmed(state);
        CanonicalPlanningObjectiveSetDTO objectives = copy(canonical, CanonicalPlanningObjectiveSetDTO.class);
        MutationPolicyDTO policy = new MutationPolicyDTO();
        policy.setAction(POLICY_ACTION);
        policy.setLockExisting(false);
        policy.setCountAsChurn(true);
        policy.setRequireCompensationSafe(true);
        PlanningObjectiveCompiler.enrichV2(state, objectives, policy);
        objectives.setTierAllocationConstraint(copy(command.getTierConstraint(),
                TierAllocationConstraintDTO.class));
        TierCountsDTO anchor = TierStructureProjection.project(
                currentTierCounts(state), command.getTargetCount(), command.getTierConstraint());
        if (anchor == null) {
            return null;
        }
        StructureTargetDTO structureTarget = objectives.getStructureTarget();
        if (structureTarget == null) {
            structureTarget = new StructureTargetDTO();
            objectives.setStructureTarget(structureTarget);
        }
        structureTarget.setTierAnchor(anchor);

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
        FindingPostconditionDTO postcondition =
                postconditionEvaluator.evaluate(RATIO_DISTRIBUTION, afterReview);
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
        proposal.setFindingCode(RATIO_DISTRIBUTION);
        proposal.setEvaluationVersion(command.getEvaluationVersion());
        proposal.setCommandDigest(command.getCommandDigest());
        proposal.setTitle("冲稳保配比调整预览");
        proposal.setSummary("按已确认的冲稳保配额移出超额档位并等量补入缺口档位；确认后按冻结方案原样回放。");
        proposal.setImpact("只写回工作草案与排序态；冲稳保配额仍由当前状态派生，不新增持久化目标。");
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
            removeAction.setSourceCheckCode(RATIO_DISTRIBUTION);
            removeAction.setSummary("移出 " + removed.size() + " 条超出配额的现有志愿");
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
            addAction.setSourceCheckCode(RATIO_DISTRIBUTION);
            addAction.setSummary("从当前候选池补入 " + added.size() + " 条缺口档位志愿");
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
            reorderAction.setSourceCheckCode(RATIO_DISTRIBUTION);
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
        proposal.setTitle("冲稳保配比调整预览");
        proposal.setSummary("只读冻结预览；确认执行入口尚未启用。");
        proposal.getSourceCheckCodes().add(finding.getCode());
        return proposal;
    }

    /**
     * 当前排序态的档位计数；用于把配额投影成 solver 的档位锚。
     * 与 solver/review 共用同一套 canonical tier key（冲/稳/保 与英文等价）。
     */
    private TierCountsDTO currentTierCounts(PlanningStateDTO state) {
        TierCountsDTO counts = new TierCountsDTO();
        counts.setSprintCount(0);
        counts.setStableCount(0);
        counts.setProtectCount(0);
        for (OrderedItemDTO item : safeList(state.getOrderedPlanState().getItems())) {
            String tier = item == null ? null : TierAllocationSupport.canonicalTierKey(item.getTier());
            if ("sprint".equals(tier)) {
                counts.setSprintCount(counts.getSprintCount() + 1);
            } else if ("stable".equals(tier)) {
                counts.setStableCount(counts.getStableCount() + 1);
            } else if ("protect".equals(tier)) {
                counts.setProtectCount(counts.getProtectCount() + 1);
            }
        }
        return counts;
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
