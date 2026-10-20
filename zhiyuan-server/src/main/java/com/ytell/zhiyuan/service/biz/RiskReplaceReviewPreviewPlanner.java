package com.ytell.zhiyuan.service.biz;

import com.alibaba.fastjson.JSON;
import com.google.common.base.Strings;
import com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO;
import com.ytell.zhiyuan.model.dto.planning.CanonicalPlanningObjectiveSetDTO;
import com.ytell.zhiyuan.model.dto.planning.CandidateSnapshotDTO;
import com.ytell.zhiyuan.model.dto.planning.DraftItemDTO;
import com.ytell.zhiyuan.model.dto.planning.DraftPlanStateDTO;
import com.ytell.zhiyuan.model.dto.planning.EvaluationEntryRefDTO;
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
import com.ytell.zhiyuan.model.dto.planning.PlanningUnitMajorDTO;
import com.ytell.zhiyuan.model.dto.planning.ReviewStateDTO;

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
 * 风险条目（高收费/中外合作/限报/特殊类型）审查修复切片。
 *
 * <p>{@code high_tuition}/{@code cooperative_program}/{@code admission_limit}/
 * {@code special_enrollment} fail，且命令策略为 {@code replace_risk_items} 或
 * {@code remove_risk_items}、携带非空 {@code forcedRemoveTargets} 时，直接把
 * 强制移出实体写进 {@link MutationPolicyDTO#getForcedRemoveEntityIds()}，用
 * {@link StagedDeterministicPlanSolver} 按 FILL 口径从候选池等量补入替代条目，
 * 再把 solver 结果冻结成可供 prepare/apply 回放的方案。</p>
 *
 * <p>目标数优先取命令里的 {@code targetCount}；移除类命令没有目标数时按当前
 * 工作草案条数保持总数不变。风险条目本身不是用户目标，canonical digest 保持
 * {@code compileConfirmed} 的旧口径，apply 回放不落任何持久化目标字段。</p>
 *
 * <p>只有成功产出冻结方案且原探针后置条件通过的路径才返回 proposal；其余情况
 * （模式不支持、引用不完整、求解/物化失败、后置条件不满足等）一律返回
 * {@code null}，与 Direct/Search/Safety/Ratio 切片一致。</p>
 */
final class RiskReplaceReviewPreviewPlanner {
    private static final String HIGH_TUITION = "high_tuition";
    private static final String COOPERATIVE_PROGRAM = "cooperative_program";
    private static final String ADMISSION_LIMIT = "admission_limit";
    private static final String SPECIAL_ENROLLMENT = "special_enrollment";
    private static final Set<String> FINDING_CODES = new LinkedHashSet<String>(Arrays.asList(
            HIGH_TUITION, COOPERATIVE_PROGRAM, ADMISSION_LIMIT, SPECIAL_ENROLLMENT));
    private static final String STRATEGY = RepairProposalTaxonomy.Strategy.FILL_MISSING_COUNT;
    private static final String POLICY_ACTION = "FILL";
    private static final String VOLUNTEER = "volunteer";
    private static final String UNIT = "unit";

    private final FindingPostconditionEvaluator postconditionEvaluator = new FindingPostconditionEvaluator();

    static boolean isRiskFinding(String findingCode) {
        return FINDING_CODES.contains(findingCode);
    }

    FixProposalDTO plan(PlanningStateDTO state, List<CandidateItemDTO> candidates,
                        EvaluationFindingDTO finding,
                        Function<PlanningStateDTO, ReviewStateDTO> reevaluate,
                        boolean confirmable) {
        PlanCommandDTO command = finding == null ? null : finding.getSuggestedCommand();
        if (finding == null || command == null || !FINDING_CODES.contains(finding.getCode())
                || !"fail".equals(finding.getResultStatus())) {
            return null;
        }
        String commandStrategy = RepairProposalTaxonomy.normalizeStrategy(command.getStrategy());
        boolean replace = RepairProposalTaxonomy.Strategy.REPLACE_RISK_ITEMS.equals(commandStrategy);
        boolean remove = RepairProposalTaxonomy.Strategy.REMOVE_RISK_ITEMS.equals(commandStrategy);
        if (!replace && !remove) {
            return null;
        }
        List<EvaluationEntryRefDTO> forcedRefs = safeList(command.getForcedRemoveTargets());
        if (forcedRefs.isEmpty()) {
            return null;
        }
        if (state == null || state.getCandidatePoolState() == null
                || state.getWorkingPlanState() == null || state.getOrderedPlanState() == null
                || reevaluate == null
                || Strings.isNullOrEmpty(command.getEvaluationVersion())
                || Strings.isNullOrEmpty(command.getCommandDigest())) {
            return null;
        }
        if (ReviewProtectionSupport.hasProtection(state)) {
            return null;
        }
        // 组模式（专业组/专业单元）走 planUnits；普通专业模式保持原有路径。
        // 与 Search/Safety/Ratio 切片同一 fail-closed 口径：优先规则留给确认链校验。
        boolean unitMode = "majorGroup".equalsIgnoreCase(
                state.getCandidatePoolState().getVolunteerModel())
                || !safeList(state.getWorkingPlanState().getUnits()).isEmpty()
                || !safeList(state.getOrderedPlanState().getUnits()).isEmpty();
        if (unitMode) {
            return planUnits(state, candidates, finding, command, reevaluate, confirmable);
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
                    || !selectedIds.add(item.getVolunteerId())) {
                return null;
            }
        }
        for (int index = 0; index < ordered.size(); index++) {
            OrderedItemDTO item = ordered.get(index);
            if (item == null || Strings.isNullOrEmpty(item.getVolunteerId())
                    || item.getPosition() == null || item.getPosition() != index + 1
                    || orderedById.put(item.getVolunteerId(), item) != null) {
                return null;
            }
        }
        if (!selectedIds.equals(orderedById.keySet())) {
            return null;
        }

        Map<String, CandidateItemDTO> candidatesById = new LinkedHashMap<String, CandidateItemDTO>();
        for (CandidateItemDTO candidate : safeList(candidates)) {
            if (candidate != null && !Strings.isNullOrEmpty(candidate.getVolunteerId())) {
                candidatesById.putIfAbsent(candidate.getVolunteerId(), candidate);
            }
        }
        // forcedRemove 引用必须是普通志愿粒度、存在于候选池且仍在当前选择里；
        // 否则 forced remove 要么空转，要么把结构修复缩水成纯加条。
        Set<String> targets = new LinkedHashSet<String>();
        for (EvaluationEntryRefDTO ref : forcedRefs) {
            if (ref == null || !VOLUNTEER.equals(ref.getLevel())
                    || Strings.isNullOrEmpty(ref.getId())
                    || !targets.add(ref.getId())
                    || !candidatesById.containsKey(ref.getId())
                    || !selectedIds.contains(ref.getId())) {
                return null;
            }
        }
        int currentCount = workingItems.size();
        Integer requestedTarget = command.getTargetCount();
        int targetCount = requestedTarget != null ? requestedTarget : currentCount;
        if (targetCount <= 0 || candidatesById.size() < targetCount) {
            return null;
        }

        // 风险条目不是用户目标：canonical digest 保持 compileConfirmed 的旧口径，
        // 只在 solver 使用的副本上设置目标数并写入 forcedRemove 策略。
        CanonicalPlanningObjectiveSetDTO canonical = PlanningObjectiveCompiler.compileConfirmed(state);
        CanonicalPlanningObjectiveSetDTO objectives = copy(canonical, CanonicalPlanningObjectiveSetDTO.class);
        objectives.setTargetCount(targetCount);
        MutationPolicyDTO policy = new MutationPolicyDTO();
        policy.setAction(POLICY_ACTION);
        policy.setRequiredMajorCount(state.getCandidatePoolState().getRequiredMajorCount());
        policy.setLockExisting(false);
        policy.setCountAsChurn(true);
        policy.setRequireCompensationSafe(true);
        policy.setForcedRemoveEntityIds(new LinkedHashSet<String>(targets));
        PlanningObjectiveCompiler.enrichV2(state, objectives, policy);

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
        List<String> selectedEntityIds = new ArrayList<String>(safeList(solverResult.getSelectedEntityIds()));
        List<String> orderedEntityIds = new ArrayList<String>(safeList(solverResult.getOrderedEntityIds()));
        List<String> removedEntityIds = new ArrayList<String>(safeList(solverResult.getRemoveEntityIds()));
        if (selectedEntityIds.size() != targetCount || !removedEntityIds.containsAll(targets)) {
            return null;
        }

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
                postconditionEvaluator.evaluate(finding.getCode(), afterReview);
        if (!Boolean.TRUE.equals(postcondition.getSatisfied())) {
            return null;
        }
        // 原探针通过即代表方案里不再有命中该风险标签的条目；这里再按物化后的
        // 排序态做一次显式确认，避免评价输入口径漂移时静默放过。
        for (OrderedItemDTO item : safeList(after.getOrderedPlanState().getItems())) {
            if (item != null && targets.contains(item.getVolunteerId())) {
                return null;
            }
        }

        FixProposalDTO proposal = proposal(state, finding, command, remove);
        proposal.setFindingPostcondition(postcondition);
        FrozenReviewPlanDTO frozen = new FrozenReviewPlanDTO();
        frozen.setWorkingPlan(copy(after.getWorkingPlanState(), DraftPlanStateDTO.class));
        frozen.setOrderedPlan(copy(after.getOrderedPlanState(), OrderedPlanStateDTO.class));
        frozen.setSelectedEntityIds(selectedEntityIds);
        frozen.setOrderedEntityIds(orderedEntityIds);
        frozen.setSelectedFacts(selectedFacts);
        frozen.setFactsDigest(factsDigest);
        proposal.setFrozenReviewPlan(frozen);
        adapt(proposal, solverResult, command, state, canonical, workingItems.size(), remove);
        proposal.setPlanContentDigest(DirectReviewPreviewPlanner.planContentDigest(state));
        // 摘要必须在“提升为 ready”之前算：prepare 用确认模式重算时若把
        // dryRunResult.status 的差异算进去，合法的确认会被判 409。
        proposal.getDryRunResult().setStatus("preview_only");
        proposal.setProposalId("fp_" + DirectReviewPreviewPlanner.digestJson(Arrays.asList(
                command.getEvaluationVersion(), proposal.getPlanContentDigest(),
                command.getCommandDigest(), proposal.getActions())).substring(0, 16));
        proposal.setPreviewDigest(DirectReviewPreviewPlanner.digestJson(Arrays.asList(
                proposal.getProposalId(), command.getEvaluationVersion(),
                proposal.getPlanContentDigest(), proposal.getCanonicalObjectiveDigest(),
                proposal.getSolverObjectiveDigest(), frozen,
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
     * 组模式（专业组/专业单元）的风险条目替换/移除：forcedRemoveTargets 按 unit
     * 粒度命中，目标数按 unit 计；复用 staged solver 的 unit 口径选替代组，
     * 再按 Search/Ratio 组模式同一套逻辑物化 units/items 与 unit facts。
     *
     * <p>固定/锁定、优先规则、稀疏但非严格递增的 unit 位置，以及引用不完整
     * 一律 fail closed，保持与普通专业模式相同的“无法冻结就返回 null”口径。</p>
     */
    private FixProposalDTO planUnits(PlanningStateDTO state,
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
            if (unit == null || Strings.isNullOrEmpty(unit.getUnitId()) || unit.getPosition() == null
                    || (previousPosition != null && unit.getPosition() <= previousPosition)
                    || orderedById.put(unit.getUnitId(), unit) != null) {
                return null;
            }
            previousPosition = unit.getPosition();
        }

        Map<String, List<CandidateItemDTO>> candidatesByUnit =
                new LinkedHashMap<String, List<CandidateItemDTO>>();
        for (CandidateItemDTO candidate : safeList(candidates)) {
            if (candidate == null || Strings.isNullOrEmpty(candidate.getPlanSchoolDataId())) {
                continue;
            }
            List<CandidateItemDTO> unitCandidates = candidatesByUnit.get(candidate.getPlanSchoolDataId());
            if (unitCandidates == null) {
                unitCandidates = new ArrayList<CandidateItemDTO>();
                candidatesByUnit.put(candidate.getPlanSchoolDataId(), unitCandidates);
            }
            unitCandidates.add(candidate);
        }
        Set<String> targets = new LinkedHashSet<String>();
        for (EvaluationEntryRefDTO ref : safeList(command.getForcedRemoveTargets())) {
            if (ref == null || !UNIT.equals(ref.getLevel())
                    || Strings.isNullOrEmpty(ref.getId())
                    || !targets.add(ref.getId())
                    || !orderedById.containsKey(ref.getId())
                    || !candidatesByUnit.containsKey(ref.getId())) {
                return null;
            }
        }
        int targetCount = command.getTargetCount() != null
                ? command.getTargetCount() : currentOrdered.size();
        if (targetCount <= 0 || candidatesByUnit.size() < targetCount) {
            return null;
        }

        PlanningStateDTO copy = copy(state, PlanningStateDTO.class);
        SearchReviewPreviewPlanner.normalizeGroupMode(copy);
        CanonicalPlanningObjectiveSetDTO canonical = PlanningObjectiveCompiler.compileConfirmed(copy);
        CanonicalPlanningObjectiveSetDTO objectives = copy(canonical, CanonicalPlanningObjectiveSetDTO.class);
        objectives.setTargetCount(targetCount);
        MutationPolicyDTO policy = new MutationPolicyDTO();
        policy.setAction(POLICY_ACTION);
        policy.setRequiredMajorCount(state.getCandidatePoolState().getRequiredMajorCount());
        policy.setLockExisting(false);
        policy.setCountAsChurn(true);
        policy.setRequireCompensationSafe(true);
        policy.setForcedRemoveEntityIds(new LinkedHashSet<String>(targets));
        PlanningObjectiveCompiler.enrichV2(copy, objectives, policy);

        CandidateSnapshotDTO snapshot = CandidateSnapshotBuilder.build(
                copy, candidates, CandidateSnapshotBuilder.CurrentSource.ORDERED_FIRST);
        if (snapshot == null || !"unit".equals(snapshot.getCountMode())) {
            return null;
        }
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
        List<String> removedEntityIds = new ArrayList<String>(
                safeList(solverResult.getRemoveEntityIds()));
        if (selectedEntityIds.size() != targetCount || orderedEntityIds.size() != targetCount
                || new LinkedHashSet<String>(selectedEntityIds).size() != selectedEntityIds.size()
                || new LinkedHashSet<String>(orderedEntityIds).size() != orderedEntityIds.size()
                || !new LinkedHashSet<String>(selectedEntityIds)
                .equals(new LinkedHashSet<String>(orderedEntityIds))
                || !removedEntityIds.containsAll(targets)
                || !java.util.Collections.disjoint(selectedEntityIds, targets)) {
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
        FindingPostconditionDTO postcondition =
                postconditionEvaluator.evaluate(finding.getCode(), afterReview);
        if (!Boolean.TRUE.equals(postcondition.getSatisfied())) {
            return null;
        }
        for (OrderedUnitDTO unit : orderedUnits) {
            if (unit != null && targets.contains(unit.getUnitId())) {
                return null;
            }
        }

        FixProposalDTO proposal = proposal(state, finding, command, removeStrategy(command));
        proposal.setFindingPostcondition(postcondition);
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
        proposal.getDryRunResult().setStatus("preview_only");
        proposal.setProposalId("fp_" + DirectReviewPreviewPlanner.digestJson(Arrays.asList(
                command.getEvaluationVersion(), proposal.getPlanContentDigest(),
                command.getCommandDigest(), proposal.getActions())).substring(0, 16));
        proposal.setPreviewDigest(DirectReviewPreviewPlanner.digestJson(Arrays.asList(
                proposal.getProposalId(), command.getEvaluationVersion(),
                proposal.getPlanContentDigest(), proposal.getCanonicalObjectiveDigest(),
                proposal.getSolverObjectiveDigest(), frozen,
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

    private boolean removeStrategy(PlanCommandDTO command) {
        return RepairProposalTaxonomy.Strategy.REMOVE_RISK_ITEMS.equals(
                RepairProposalTaxonomy.normalizeStrategy(command.getStrategy()));
    }

    /**
     * 组模式 Risk 提案元数据与 unit 级动作：add/remove/reorder 全部以 unit 计，
     * dryRun 同时给出 unit 与志愿者总量，口径与 Search/Safety/Ratio 组模式一致。
     */
    private void adaptUnits(FixProposalDTO proposal, PlanSolverResultDTO solverResult,
                            PlanCommandDTO command, PlanningStateDTO state,
                            CanonicalPlanningObjectiveSetDTO canonical,
                            List<OrderedUnitDTO> currentOrdered,
                            List<OrderedUnitDTO> orderedUnits,
                            List<OrderedItemDTO> orderedItems) {
        String findingCode = proposal.getFindingCode();
        boolean remove = removeStrategy(command);
        proposal.setProposalSource(RepairProposalTaxonomy.ProposalSource.REVIEW_CHECK);
        proposal.setSourceVersion(state.getVersion());
        proposal.setStrategy(STRATEGY);
        proposal.setSourceStrategy(command.getSourceStrategy());
        proposal.setFindingCode(findingCode);
        proposal.setEvaluationVersion(command.getEvaluationVersion());
        proposal.setCommandDigest(command.getCommandDigest());
        proposal.setTitle(remove ? "风险条目移除预览" : "风险条目替换预览");
        proposal.setSummary(remove
                ? "移出命中的风险专业组，并从当前候选池补足数量；确认后按冻结方案原样回放。"
                : "从当前候选池等量替换命中的风险专业组；确认后按冻结方案原样回放。");
        proposal.setImpact("只写回工作草案与排序态；风险标签仍由候选数据派生，不新增持久化目标。");
        proposal.setCanonicalObjectiveDigest(canonical.getObjectiveDigest());
        proposal.setSolverObjectiveDigest(solverResult.getSolverObjectiveDigest());
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
            removeAction.setLevel(UNIT);
            removeAction.setSourceCheckCode(findingCode);
            removeAction.setSummary("移出 " + removed.size() + " 个命中的风险专业组");
            removeAction.setUnitIds(new ArrayList<String>(removed));
            removeAction.setRemoveUnitIds(new ArrayList<String>(removed));
            removeAction.setVolunteerIds(new ArrayList<String>(removedVolunteers));
            removeAction.setRemoveVolunteerIds(new ArrayList<String>(removedVolunteers));
            removeAction.setTotalUnitCount(removed.size());
            removeAction.setTotalVolunteerCount(removedVolunteers.size());
            proposal.getActions().add(removeAction);
        }
        if (!added.isEmpty()) {
            FixProposalActionDTO addAction = new FixProposalActionDTO();
            addAction.setActionType(RepairProposalTaxonomy.ActionType.FILL_TOTAL_COUNT);
            addAction.setLevel(UNIT);
            addAction.setSourceCheckCode(findingCode);
            addAction.setSummary("从当前候选池补入 " + added.size() + " 个替代专业组");
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
            reorderAction.setLevel(UNIT);
            reorderAction.setSourceCheckCode(findingCode);
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
            for (PlanningUnitMajorDTO major : safeList(unit.getMajorItems())) {
                if (major != null && !Strings.isNullOrEmpty(major.getVolunteerId())) {
                    result.add(major.getVolunteerId());
                }
            }
        }
        return result;
    }

    private void adapt(FixProposalDTO proposal, PlanSolverResultDTO solverResult,
                       PlanCommandDTO command, PlanningStateDTO state,
                       CanonicalPlanningObjectiveSetDTO canonical, int beforeCount,
                       boolean remove) {
        String findingCode = proposal.getFindingCode();
        String title = remove ? "风险条目移除预览" : "风险条目替换预览";
        proposal.setProposalSource(RepairProposalTaxonomy.ProposalSource.REVIEW_CHECK);
        proposal.setSourceVersion(state.getVersion());
        proposal.setStrategy(STRATEGY);
        proposal.setSourceStrategy(command.getStrategy());
        proposal.setFindingCode(findingCode);
        proposal.setEvaluationVersion(command.getEvaluationVersion());
        proposal.setCommandDigest(command.getCommandDigest());
        proposal.setTitle(title);
        proposal.setSummary(remove
                ? "移出命中的风险志愿，并从当前候选池补足数量；确认后按冻结方案原样回放。"
                : "从当前候选池等量替换命中的风险志愿；确认后按冻结方案原样回放。");
        proposal.setImpact("只写回工作草案与排序态；风险标签仍由候选数据派生，不新增持久化目标。");
        // 预 enrich 的旧口径：与 apply 侧 compileConfirmed 重算保持逐字一致。
        proposal.setCanonicalObjectiveDigest(canonical.getObjectiveDigest());
        proposal.setSolverObjectiveDigest(solverResult.getSolverObjectiveDigest());
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
            removeAction.setSourceCheckCode(findingCode);
            removeAction.setSummary("移出 " + removed.size() + " 条命中的风险志愿");
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
            addAction.setSourceCheckCode(findingCode);
            addAction.setSummary("从当前候选池补入 " + added.size() + " 条替代志愿");
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
            reorderAction.setSourceCheckCode(findingCode);
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
                                    PlanCommandDTO command, boolean remove) {
        FixProposalDTO proposal = new FixProposalDTO();
        proposal.setStatus("preview_only");
        proposal.setRequiresConfirmation(false);
        proposal.setProposalSource(RepairProposalTaxonomy.ProposalSource.REVIEW_CHECK);
        proposal.setSourceVersion(state == null ? null : state.getVersion());
        proposal.setStrategy(STRATEGY);
        proposal.setSourceStrategy(command.getStrategy());
        proposal.setFindingCode(finding.getCode());
        proposal.setEvaluationVersion(command.getEvaluationVersion());
        proposal.setCommandDigest(command.getCommandDigest());
        proposal.setTitle(remove ? "风险条目移除预览" : "风险条目替换预览");
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
