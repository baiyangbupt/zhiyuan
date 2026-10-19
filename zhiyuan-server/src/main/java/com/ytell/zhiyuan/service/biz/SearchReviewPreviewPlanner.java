package com.ytell.zhiyuan.service.biz;

import com.alibaba.fastjson.JSON;
import com.google.common.base.Strings;
import com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO;
import com.ytell.zhiyuan.model.dto.planning.CoverageRequirementDTO;
import com.ytell.zhiyuan.model.dto.planning.DraftItemDTO;
import com.ytell.zhiyuan.model.dto.planning.DraftPlanStateDTO;
import com.ytell.zhiyuan.model.dto.planning.DraftUnitDTO;
import com.ytell.zhiyuan.model.dto.planning.EvaluationFindingDTO;
import com.ytell.zhiyuan.model.dto.planning.FindingPostconditionDTO;
import com.ytell.zhiyuan.model.dto.planning.FixProposalActionDTO;
import com.ytell.zhiyuan.model.dto.planning.FixProposalDTO;
import com.ytell.zhiyuan.model.dto.planning.FixProposalDryRunResultDTO;
import com.ytell.zhiyuan.model.dto.planning.FixProposalStateDTO;
import com.ytell.zhiyuan.model.dto.planning.FrozenReviewPlanDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedItemDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedPlanStateDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedUnitDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanCommandDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanSolverResultDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningUnitMajorDTO;
import com.ytell.zhiyuan.model.dto.planning.ReviewStateDTO;
import com.ytell.zhiyuan.model.dto.planning.UserGoalFixProposalReq;

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
 * Search 型审查修复切片：普通专业模式下复用 {@code UserGoalProposalBuilder} 的
 * staged solver，把 solverResult 冻结成与 Direct 倒挂修复同构的 frozenReviewPlan。
 *
 * <p>支持两类 finding：</p>
 * <ul>
 *   <li>{@code count_target} fail → {@code fill_missing_count}（按目标数补齐）；</li>
 *   <li>{@code coverage:<i>} fail → {@code fill_missing_count}（以命令里的覆盖要求
 *   作为 include 要求，保持在目标数内等量补齐/替换）。</li>
 * </ul>
 *
 * <p>不新增目标编译器：prepare/apply 仍走同一条冻结回放与后置校验链路；
 * 后置条件始终使用原始 finding code。</p>
 */
final class SearchReviewPreviewPlanner {
    private static final String COUNT_TARGET = "count_target";
    private static final String COVERAGE_PREFIX = "coverage:";
    private static final String COVERAGE_CHECK = "coverage";
    private static final String STRATEGY = RepairProposalTaxonomy.Strategy.FILL_MISSING_COUNT;
    private static final String MUST_INCLUDE_SCOPE = RepairProposalTaxonomy.Strategy.MUST_INCLUDE_SCOPE;
    private static final String GOAL_TYPE = "fill_to_count";
    private static final String INCLUDE = ProjectedHardRequirementSupport.KIND_INCLUDE;

    private final FindingPostconditionEvaluator postconditionEvaluator = new FindingPostconditionEvaluator();

    FixProposalDTO plan(PlanningStateDTO state, List<CandidateItemDTO> candidates,
                        EvaluationFindingDTO finding,
                        Function<PlanningStateDTO, ReviewStateDTO> reevaluate,
                        boolean confirmable) {
        PlanCommandDTO command = finding == null ? null : finding.getSuggestedCommand();
        if (finding == null || command == null || !"fail".equals(finding.getResultStatus())) {
            return null;
        }
        String findingCode = finding.getCode();
        boolean countTarget = COUNT_TARGET.equals(findingCode)
                && STRATEGY.equals(RepairProposalTaxonomy.normalizeStrategy(command.getStrategy()));
        boolean coverage = findingCode != null && findingCode.startsWith(COVERAGE_PREFIX)
                && (MUST_INCLUDE_SCOPE.equals(RepairProposalTaxonomy.normalizeStrategy(command.getStrategy()))
                || STRATEGY.equals(RepairProposalTaxonomy.normalizeStrategy(command.getApplyStrategy())))
                && command.getTargetCount() != null && command.getTargetCount() > 0;
        if (!countTarget && !coverage) {
            return null;
        }
        FixProposalDTO proposal = proposal(state, finding, command);
        if (state == null || state.getCandidatePoolState() == null
                || state.getWorkingPlanState() == null || state.getOrderedPlanState() == null
                || reevaluate == null
                || Strings.isNullOrEmpty(command.getEvaluationVersion())
                || Strings.isNullOrEmpty(command.getCommandDigest())) {
            return blocked(proposal, "review_fix_evaluation_unavailable");
        }

        Integer targetCount = command.getTargetCount();
        // 组模式（专业组/专业单元）与普通专业模式共用同一份 UserGoalProposalBuilder
        // 补齐能力，但计数、物化与冻结载体都换成 unit；只有 count_target 的
        // fill_missing_count 走这条分支，coverage 等结构修复仍留待后续切片。
        boolean unitMode = "majorGroup".equalsIgnoreCase(state.getCandidatePoolState().getVolunteerModel())
                || !safeList(state.getWorkingPlanState().getUnits()).isEmpty()
                || !safeList(state.getOrderedPlanState().getUnits()).isEmpty();
        if (unitMode) {
            if (!countTarget) {
                return blocked(proposal, "review_fix_search_unsupported");
            }
            return planUnits(proposal, state, candidates, finding, command, reevaluate, confirmable);
        }
        List<DraftItemDTO> workingItems = safeList(state.getWorkingPlanState().getItems());
        // count_target 必须真正增加条数；coverage 允许在相同目标数下等量替换，
        // 因此只要求命令带正目标数（模式判定里已校验）。
        if (countTarget && (targetCount == null || targetCount <= 0
                || targetCount <= workingItems.size())) {
            return blocked(proposal, "review_fix_search_no_change");
        }
        // 普通专业模式的 Search 切片仍不接受优先规则与锁定/固定项；
        // 组模式由 planUnits 单独校验。
        if (!PriorityRuleSupport.confirmedRules(state).isEmpty()) {
            return blocked(proposal, "review_fix_search_unsupported");
        }
        List<OrderedItemDTO> ordered = new ArrayList<OrderedItemDTO>(safeList(
                state.getOrderedPlanState().getItems()));
        Map<String, OrderedItemDTO> orderedById = new LinkedHashMap<String, OrderedItemDTO>();
        Set<String> selectedIds = new LinkedHashSet<String>();
        if (workingItems.isEmpty() || ordered.isEmpty() || ordered.size() != workingItems.size()) {
            return blocked(proposal, "review_fix_selection_incomplete");
        }
        ordered.sort(Comparator.comparing(item -> item.getPosition() == null
                ? Integer.MAX_VALUE : item.getPosition()));
        for (DraftItemDTO item : workingItems) {
            if (item == null || Strings.isNullOrEmpty(item.getVolunteerId())
                    || Boolean.TRUE.equals(item.getLocked()) || !selectedIds.add(item.getVolunteerId())) {
                return blocked(proposal, "review_fix_selection_incomplete");
            }
        }
        for (int index = 0; index < ordered.size(); index++) {
            OrderedItemDTO item = ordered.get(index);
            if (item == null || Strings.isNullOrEmpty(item.getVolunteerId())
                    || item.getPosition() == null || item.getPosition() != index + 1
                    || Boolean.TRUE.equals(item.getLocked())
                    || Boolean.TRUE.equals(item.getPinned()) || item.getPinnedPosition() != null
                    || orderedById.put(item.getVolunteerId(), item) != null) {
                return blocked(proposal, "review_fix_selection_incomplete");
            }
        }
        if (!selectedIds.equals(orderedById.keySet())) {
            return blocked(proposal, "review_fix_selection_incomplete");
        }

        // 复用 user-goal 的 staged solver：把同一份 effective candidates 放进副本，
        // 保证 build 看到的候选池与下面 applyFrozenSelection/factsDigest 的口径一致。
        PlanningStateDTO copy = copy(state, PlanningStateDTO.class);
        copy.getCandidatePoolState().setItems(copyList(candidates, CandidateItemDTO.class));
        UserGoalFixProposalReq req = new UserGoalFixProposalReq();
        req.setGoalType(GOAL_TYPE);
        req.setTargetCount(targetCount);
        req.setSourceVersionGuard(state.getVersion());
        // 注意：UserGoalProposalBuilder 把 persistTargetCount=false 解释为
        // “保持当前数量”，会要求 targetCount == 当前数且必须带 include 要求；
        // 本切片是补齐语义（80→82），因此必须走默认的 fill（true）。
        // review_check 的冻结回放链路本身不会持久化目标数量。
        req.setPersistTargetCount(true);
        if (coverage) {
            List<UserGoalFixProposalReq.RequirementDTO> requirements =
                    coverageRequirements(command);
            if (requirements.isEmpty()) {
                return blocked(proposal, "review_fix_coverage_unavailable");
            }
            req.setRequirements(requirements);
        }
        FixProposalStateDTO generatedState;
        try {
            generatedState = UserGoalProposalBuilder.build(copy, req);
        } catch (RuntimeException unavailable) {
            return blocked(proposal, "review_fix_solver_unavailable");
        }
        FixProposalDTO generated = generatedState == null || generatedState.getProposals().isEmpty()
                ? null : generatedState.getProposals().get(0);
        PlanSolverResultDTO solverResult = generated == null ? null : generated.getSolverResult();
        if (generated == null || !"ready".equals(generated.getStatus()) || solverResult == null
                || !"ready".equals(solverResult.getStatus())) {
            return blocked(proposal, solverFailureReason(generated));
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
            return blocked(proposal, "review_fix_facts_incomplete");
        }
        List<CandidateItemDTO> selectedFacts = new ArrayList<CandidateItemDTO>();
        for (String identity : selectedEntityIds) {
            selectedFacts.add(copy(candidatesById.get(identity), CandidateItemDTO.class));
        }

        PlanningStateDTO after = copy(state, PlanningStateDTO.class);
        try {
            CanonicalPlanningRuntime.applyFrozenSelection(after, candidates, solverResult);
        } catch (RuntimeException unavailable) {
            return blocked(proposal, "review_fix_solver_unavailable");
        }
        after.getOrderedPlanState().setUnits(new ArrayList<OrderedUnitDTO>());
        after.getOrderedPlanState().setItems(orderedItemsFromSolver(
                orderedEntityIds, orderedById, candidatesById));

        ReviewStateDTO afterReview;
        try {
            afterReview = reevaluate.apply(copy(after, PlanningStateDTO.class));
        } catch (RuntimeException unavailable) {
            return blocked(proposal, "review_fix_evaluation_unavailable");
        }
        FindingPostconditionDTO postcondition = postconditionEvaluator.evaluate(findingCode, afterReview);
        proposal.setFindingPostcondition(postcondition);
        if (!Boolean.TRUE.equals(postcondition.getSatisfied())) {
            return blocked(proposal, Strings.isNullOrEmpty(postcondition.getReasonCode())
                    ? "review_fix_postcondition_failed" : postcondition.getReasonCode());
        }

        FrozenReviewPlanDTO frozen = new FrozenReviewPlanDTO();
        frozen.setWorkingPlan(copy(after.getWorkingPlanState(), DraftPlanStateDTO.class));
        frozen.setOrderedPlan(copy(after.getOrderedPlanState(), OrderedPlanStateDTO.class));
        frozen.setSelectedEntityIds(selectedEntityIds);
        frozen.setOrderedEntityIds(orderedEntityIds);
        frozen.setSelectedFacts(selectedFacts);
        frozen.setFactsDigest(factsDigest);
        proposal.setFrozenReviewPlan(frozen);
        adapt(proposal, generated, solverResult, command, state, findingCode, coverage);
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
     * 组模式（专业组/专业单元）的 count_target 补齐：目标数与当前数都按 unit 计，
     * 复用 user-goal 的 group fill（solverResult 的 entityId 即 unitId），再把
     * 选中结果物化成 working units + ordered units/items。冻结后按原 finding
     * count_target 做后置校验，确认链仍走同一条冻结回放。
     */
    private FixProposalDTO planUnits(FixProposalDTO proposal, PlanningStateDTO state,
                                     List<CandidateItemDTO> candidates,
                                     EvaluationFindingDTO finding, PlanCommandDTO command,
                                     Function<PlanningStateDTO, ReviewStateDTO> reevaluate,
                                     boolean confirmable) {
        Integer targetCount = command.getTargetCount();
        List<OrderedUnitDTO> currentOrdered = new ArrayList<OrderedUnitDTO>(
                safeList(state.getOrderedPlanState().getUnits()));
        if (currentOrdered.isEmpty()) {
            return blocked(proposal, "review_fix_selection_incomplete");
        }
        currentOrdered.sort(Comparator.comparing(unit -> unit == null || unit.getPosition() == null
                ? Integer.MAX_VALUE : unit.getPosition()));
        Map<String, OrderedUnitDTO> existingOrderedById = new LinkedHashMap<String, OrderedUnitDTO>();
        Set<String> currentUnitIds = new LinkedHashSet<String>();
        Integer previousPosition = null;
        for (OrderedUnitDTO unit : currentOrdered) {
            // 线上 group 方案的位置可能稀疏（1,2,8,9...），只要求严格递增且唯一；
            // 物化时会统一重排为 1..n。
            if (unit == null || Strings.isNullOrEmpty(unit.getUnitId()) || unit.getPosition() == null
                    || (previousPosition != null && unit.getPosition() <= previousPosition)
                    || existingOrderedById.put(unit.getUnitId(), unit) != null) {
                return blocked(proposal, "review_fix_selection_incomplete");
            }
            if (Boolean.TRUE.equals(unit.getLocked()) || Boolean.TRUE.equals(unit.getPinned())
                    || unit.getPinnedPosition() != null) {
                return blocked(proposal, "review_fix_order_locked");
            }
            previousPosition = unit.getPosition();
            currentUnitIds.add(unit.getUnitId());
        }
        // count_target 在组模式下的“条数”就是专业组数；不足目标才允许补齐。
        if (targetCount == null || targetCount <= 0 || targetCount <= currentOrdered.size()) {
            return blocked(proposal, "review_fix_search_no_change");
        }
        // 工作台可能只存 draft items、不存 working units；存在时身份必须与 ordered
        // 完全一致，否则 applyFrozenSelection 的当前集合会与冻结口径错位。
        Set<String> workingUnitIds = new LinkedHashSet<String>();
        for (DraftUnitDTO unit : safeList(state.getWorkingPlanState().getUnits())) {
            if (unit == null || Strings.isNullOrEmpty(unit.getUnitId())
                    || !workingUnitIds.add(unit.getUnitId())) {
                return blocked(proposal, "review_fix_selection_incomplete");
            }
            if (Boolean.TRUE.equals(unit.getLocked())) {
                return blocked(proposal, "review_fix_order_locked");
            }
        }
        if (!workingUnitIds.isEmpty() && !workingUnitIds.equals(currentUnitIds)) {
            return blocked(proposal, "review_fix_selection_incomplete");
        }

        // 复用 user-goal 的 group fill：targetCount 按 unit 计，当前数由 ordered units 决定。
        // volunteerModel 缺失但存在 units 时，副本显式归一为 majorGroup，避免 builder
        // 与 applyFrozenSelection 退回志愿口径。
        PlanningStateDTO copy = copy(state, PlanningStateDTO.class);
        normalizeGroupMode(copy);
        copy.getCandidatePoolState().setItems(copyList(candidates, CandidateItemDTO.class));
        UserGoalFixProposalReq req = new UserGoalFixProposalReq();
        req.setGoalType(GOAL_TYPE);
        req.setTargetCount(targetCount);
        req.setSourceVersionGuard(state.getVersion());
        req.setPersistTargetCount(true);
        FixProposalStateDTO generatedState;
        try {
            generatedState = UserGoalProposalBuilder.build(copy, req);
        } catch (RuntimeException unavailable) {
            return blocked(proposal, "review_fix_solver_unavailable");
        }
        FixProposalDTO generated = generatedState == null || generatedState.getProposals().isEmpty()
                ? null : generatedState.getProposals().get(0);
        PlanSolverResultDTO solverResult = generated == null ? null : generated.getSolverResult();
        if (generated == null || !"ready".equals(generated.getStatus()) || solverResult == null
                || !"ready".equals(solverResult.getStatus())) {
            return blocked(proposal, solverFailureReason(generated));
        }
        List<String> selectedEntityIds = new ArrayList<String>(safeList(solverResult.getSelectedEntityIds()));
        List<String> orderedEntityIds = new ArrayList<String>(safeList(solverResult.getOrderedEntityIds()));
        if (selectedEntityIds.isEmpty() || orderedEntityIds.isEmpty()
                || new LinkedHashSet<String>(selectedEntityIds).size() != selectedEntityIds.size()
                || new LinkedHashSet<String>(orderedEntityIds).size() != orderedEntityIds.size()
                || !new LinkedHashSet<String>(selectedEntityIds)
                .equals(new LinkedHashSet<String>(orderedEntityIds))) {
            return blocked(proposal, "review_fix_solver_unavailable");
        }

        Map<String, CandidateItemDTO> candidatesById = candidatesById(candidates);
        PlanningStateDTO after = copy(state, PlanningStateDTO.class);
        normalizeGroupMode(after);
        try {
            // 选中集合先落到 working items（group 口径会按 unit 聚合），再同步 working units。
            CanonicalPlanningRuntime.applyFrozenSelection(after, candidates, solverResult);
        } catch (RuntimeException unavailable) {
            return blocked(proposal, "review_fix_solver_unavailable");
        }
        Map<String, DraftItemDTO> workingItemsById = new LinkedHashMap<String, DraftItemDTO>();
        for (DraftItemDTO item : safeList(after.getWorkingPlanState().getItems())) {
            if (item != null && !Strings.isNullOrEmpty(item.getVolunteerId())) {
                workingItemsById.put(item.getVolunteerId(), item);
            }
        }
        List<OrderedUnitDTO> orderedUnits = orderedUnitsFromSolver(orderedEntityIds,
                existingOrderedById, safeList(after.getWorkingPlanState().getUnits()), candidatesById);
        if (orderedUnits == null) {
            return blocked(proposal, "review_fix_selection_incomplete");
        }
        Map<String, OrderedItemDTO> existingOrderedItemsById = new LinkedHashMap<String, OrderedItemDTO>();
        for (OrderedItemDTO item : safeList(state.getOrderedPlanState().getItems())) {
            if (item != null && !Strings.isNullOrEmpty(item.getVolunteerId())) {
                existingOrderedItemsById.put(item.getVolunteerId(), item);
            }
        }
        List<OrderedItemDTO> orderedItems = orderedItemsFromUnits(orderedUnits,
                existingOrderedItemsById, workingItemsById, candidatesById);
        if (orderedItems == null) {
            return blocked(proposal, "review_fix_selection_incomplete");
        }
        after.getOrderedPlanState().setUnits(orderedUnits);
        after.getOrderedPlanState().setItems(orderedItems);

        List<CandidateItemDTO> unitFacts = DirectReviewPreviewPlanner.factsForUnits(
                selectedEntityIds, orderedUnits, candidates);
        if (unitFacts == null) {
            return blocked(proposal, "review_fix_facts_incomplete");
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
            return blocked(proposal, "review_fix_evaluation_unavailable");
        }
        FindingPostconditionDTO postcondition = postconditionEvaluator.evaluate(COUNT_TARGET, afterReview);
        proposal.setFindingPostcondition(postcondition);
        if (!Boolean.TRUE.equals(postcondition.getSatisfied())) {
            return blocked(proposal, Strings.isNullOrEmpty(postcondition.getReasonCode())
                    ? "review_fix_postcondition_failed" : postcondition.getReasonCode());
        }

        FrozenReviewPlanDTO frozen = new FrozenReviewPlanDTO();
        frozen.setWorkingPlan(copy(after.getWorkingPlanState(), DraftPlanStateDTO.class));
        frozen.setOrderedPlan(copy(after.getOrderedPlanState(), OrderedPlanStateDTO.class));
        frozen.setSelectedEntityIds(selectedEntityIds);
        frozen.setOrderedEntityIds(orderedEntityIds);
        frozen.setSelectedFacts(selectedFacts);
        frozen.setFactsDigest(factsDigest);
        proposal.setFrozenReviewPlan(frozen);
        adaptUnits(proposal, generated, solverResult, command, state,
                currentOrdered, orderedUnits, orderedItems);
        proposal.setPlanContentDigest(DirectReviewPreviewPlanner.planContentDigest(state));
        // 摘要口径与 Search/Direct 完全一致：先按 preview_only 计算，确认模式再提升。
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

    private void adaptUnits(FixProposalDTO proposal, FixProposalDTO generated,
                            PlanSolverResultDTO solverResult, PlanCommandDTO command,
                            PlanningStateDTO state, List<OrderedUnitDTO> currentOrdered,
                            List<OrderedUnitDTO> orderedUnits, List<OrderedItemDTO> orderedItems) {
        proposal.setProposalSource(RepairProposalTaxonomy.ProposalSource.REVIEW_CHECK);
        proposal.setSourceVersion(state.getVersion());
        proposal.setStrategy(STRATEGY);
        proposal.setSourceStrategy(command.getSourceStrategy());
        proposal.setFindingCode(COUNT_TARGET);
        proposal.setEvaluationVersion(command.getEvaluationVersion());
        proposal.setCommandDigest(command.getCommandDigest());
        proposal.setTitle("补齐方案目标数量预览");
        proposal.setSummary(generated.getSummary());
        proposal.setImpact(generated.getImpact());
        proposal.setCanonicalObjectiveDigest(generated.getCanonicalObjectiveDigest());
        proposal.setSolverVersion(generated.getSolverVersion());
        proposal.setSolverInputDigest(generated.getSolverInputDigest());
        proposal.setHardObjectiveVersion(generated.getHardObjectiveVersion());
        proposal.setSolverResult(copy(solverResult, PlanSolverResultDTO.class));
        proposal.setTargetCountBefore(currentOrdered.size());
        proposal.setTargetCountAfter(orderedUnits.size());
        proposal.setAddedCount(generated.getAddedCount());
        proposal.setAddedUnitCount(generated.getAddedUnitCount());
        proposal.setRemovedCount(generated.getRemovedCount());
        Set<String> affectedUnits = new LinkedHashSet<String>();
        List<String> affectedVolunteers = new ArrayList<String>();
        for (FixProposalActionDTO action : safeList(generated.getActions())) {
            if (action == null) {
                continue;
            }
            FixProposalActionDTO copied = copy(action, FixProposalActionDTO.class);
            copied.setLevel("unit");
            copied.setSourceCheckCode(COUNT_TARGET);
            proposal.getActions().add(copied);
            collectIds(action.getCandidateUnitIds(), action.getUnitIds(), action.getRemoveUnitIds(),
                    affectedUnits);
            collectIds(action.getCandidateVolunteerIds(), action.getVolunteerIds(),
                    action.getRemoveVolunteerIds(), affectedVolunteers);
        }
        proposal.setAffectedUnitIds(new ArrayList<String>(affectedUnits));
        proposal.setAffectedVolunteerIds(affectedVolunteers);

        FixProposalDryRunResultDTO dryRun = copy(generated.getDryRunResult(),
                FixProposalDryRunResultDTO.class);
        if (dryRun == null) {
            dryRun = new FixProposalDryRunResultDTO();
        }
        Set<String> beforeUnitIds = new LinkedHashSet<String>();
        Set<String> beforeVolunteerIds = new LinkedHashSet<String>();
        for (OrderedUnitDTO unit : currentOrdered) {
            beforeUnitIds.add(unit.getUnitId());
            for (PlanningUnitMajorDTO major : safeList(unit.getMajorItems())) {
                if (major != null && !Strings.isNullOrEmpty(major.getVolunteerId())) {
                    beforeVolunteerIds.add(major.getVolunteerId());
                }
            }
        }
        Set<String> afterVolunteerIds = new LinkedHashSet<String>();
        for (OrderedItemDTO item : orderedItems) {
            afterVolunteerIds.add(item.getVolunteerId());
        }
        dryRun.setBeforeUnitTotal(beforeUnitIds.size());
        dryRun.setAfterUnitTotal(orderedUnits.size());
        dryRun.setBeforeUnitIds(beforeUnitIds);
        dryRun.setAfterUnitIds(new LinkedHashSet<String>(proposal.getSolverResult()
                .getOrderedEntityIds()));
        dryRun.setBeforeVolunteerTotal(beforeVolunteerIds.size());
        dryRun.setAfterVolunteerTotal(afterVolunteerIds.size());
        dryRun.setBeforeVolunteerIds(beforeVolunteerIds);
        dryRun.setAfterVolunteerIds(afterVolunteerIds);
        proposal.setDryRunResult(dryRun);
    }

    private void collectIds(List<String> primary, List<String> secondary, List<String> tertiary,
                            java.util.Collection<String> target) {
        for (List<String> values : Arrays.asList(primary, secondary, tertiary)) {
            for (String value : safeList(values)) {
                if (!Strings.isNullOrEmpty(value)) {
                    target.add(value);
                }
            }
        }
    }

    static Map<String, CandidateItemDTO> candidatesById(List<CandidateItemDTO> candidates) {
        Map<String, CandidateItemDTO> result = new LinkedHashMap<String, CandidateItemDTO>();
        for (CandidateItemDTO candidate : safeList(candidates)) {
            if (candidate != null && !Strings.isNullOrEmpty(candidate.getVolunteerId())) {
                result.putIfAbsent(candidate.getVolunteerId(), candidate);
            }
        }
        return result;
    }

    /**
     * 按 solver 的 unit 顺序物化 ordered units：已有 ordered unit 原样复用；
     * 新补入的 unit 从 working units（applyFrozenSelection 同步出的组）取载体，
     * 并用候选事实补齐省市/学校 ID 与录取率，保证后续 review 与回放口径一致。
     * 任一 unit 无专业载体或 ID 重复返回 null，由调用方 fail closed。
     */
    static List<OrderedUnitDTO> orderedUnitsFromSolver(
            List<String> orderedEntityIds,
            Map<String, OrderedUnitDTO> existingOrderedById,
            List<DraftUnitDTO> workingUnits,
            Map<String, CandidateItemDTO> candidatesById) {
        Map<String, DraftUnitDTO> workingById = new LinkedHashMap<String, DraftUnitDTO>();
        for (DraftUnitDTO unit : safeList(workingUnits)) {
            if (unit != null && !Strings.isNullOrEmpty(unit.getUnitId())) {
                workingById.put(unit.getUnitId(), unit);
            }
        }
        List<OrderedUnitDTO> result = new ArrayList<OrderedUnitDTO>();
        Set<String> added = new LinkedHashSet<String>();
        for (String unitId : orderedEntityIds) {
            if (Strings.isNullOrEmpty(unitId) || !added.add(unitId)) {
                return null;
            }
            OrderedUnitDTO unit = copy(existingOrderedById.get(unitId), OrderedUnitDTO.class);
            if (unit == null) {
                DraftUnitDTO draft = workingById.get(unitId);
                unit = new OrderedUnitDTO();
                unit.setUnitId(unitId);
                unit.setSource("review_fix");
                unit.setOrderedBy("system");
                unit.setOrderReason("review_fix_fill");
                if (draft != null) {
                    unit.setTier(draft.getTier());
                    unit.setSchoolName(draft.getSchoolName());
                    unit.setSource(draft.getSource());
                    unit.setLocked(draft.getLocked());
                    unit.setMajorItems(copyList(draft.getMajorItems(), PlanningUnitMajorDTO.class));
                }
                if (safeList(unit.getMajorItems()).isEmpty()) {
                    unit.setMajorItems(majorsForUnit(unitId, candidatesById));
                }
                enrichUnitFromCandidate(unit, candidatesById);
            }
            if (safeList(unit.getMajorItems()).isEmpty()) {
                return null;
            }
            unit.setPosition(result.size() + 1);
            result.add(unit);
        }
        return result;
    }

    private static List<PlanningUnitMajorDTO> majorsForUnit(
            String unitId, Map<String, CandidateItemDTO> candidatesById) {
        List<PlanningUnitMajorDTO> majors = new ArrayList<PlanningUnitMajorDTO>();
        for (CandidateItemDTO candidate : candidatesById.values()) {
            if (candidate == null || !unitId.equals(
                    RepairCandidateSelector.resolveInitialRecommendationUnitId(candidate))) {
                continue;
            }
            PlanningUnitMajorDTO major = new PlanningUnitMajorDTO();
            major.setVolunteerId(candidate.getVolunteerId());
            major.setMajorId(candidate.getMajorId());
            major.setMajorName(candidate.getMajorName());
            major.setMajorCode(candidate.getMajorCode());
            major.setMajorCategoryId(candidate.getMajorCategoryId());
            major.setMajorSubCategoryId(candidate.getMajorSubCategoryId());
            major.setMajorCategory(candidate.getMajorCategory());
            major.setMajorDiscipline(candidate.getMajorDiscipline());
            major.setTier(candidate.getTier());
            major.setAdmissionRatio(candidate.getAdmissionRatio());
            major.setFinalScore(candidate.getFinalScore());
            major.setIntentScore(candidate.getIntentScore());
            major.setSelected(true);
            majors.add(major);
        }
        return majors;
    }

    private static void enrichUnitFromCandidate(OrderedUnitDTO unit,
                                                Map<String, CandidateItemDTO> candidatesById) {
        CandidateItemDTO fact = null;
        for (PlanningUnitMajorDTO major : safeList(unit.getMajorItems())) {
            if (major != null && !Strings.isNullOrEmpty(major.getVolunteerId())) {
                fact = candidatesById.get(major.getVolunteerId());
                if (fact != null) {
                    break;
                }
            }
        }
        if (fact == null) {
            return;
        }
        unit.setPlanSchoolDataId(fact.getPlanSchoolDataId());
        unit.setSchoolId(fact.getSchoolId());
        unit.setSchoolUnitCode(fact.getSchoolUnitCode());
        unit.setProvinceName(fact.getProvinceName());
        unit.setCityName(fact.getCityName());
        unit.setProvinceId(fact.getProvinceId());
        unit.setCityId(fact.getCityId());
        unit.setSchoolLevel(fact.getSchoolLevel());
        unit.setSchoolNature(fact.getSchoolNature());
        unit.setSchoolCategory(fact.getSchoolCategory());
        unit.setAdmissionRatio(fact.getAdmissionRatio());
        unit.setSchoolEnrollRatio(fact.getSchoolEnrollRatio());
        unit.setFinalScore(fact.getFinalScore());
        unit.setTotalMajorCount(safeList(unit.getMajorItems()).size());
        if (Strings.isNullOrEmpty(unit.getTier())) {
            unit.setTier(fact.getTier());
        }
        if (Strings.isNullOrEmpty(unit.getSchoolName())) {
            unit.setSchoolName(fact.getSchoolName());
        }
    }

    /**
     * 按 unit→major 顺序重建 ordered items：同一 volunteerId 复用原有序条目，
     * 新补入条目从 draft item / 候选事实生成，位置统一 1..n。
     * volunteerId 重复返回 null（冻结回放无法唯一解析）。
     */
    static List<OrderedItemDTO> orderedItemsFromUnits(
            List<OrderedUnitDTO> units,
            Map<String, OrderedItemDTO> existingById,
            Map<String, DraftItemDTO> workingItemsById,
            Map<String, CandidateItemDTO> candidatesById) {
        List<OrderedItemDTO> items = new ArrayList<OrderedItemDTO>();
        Set<String> added = new LinkedHashSet<String>();
        for (OrderedUnitDTO unit : units) {
            for (PlanningUnitMajorDTO major : safeList(unit.getMajorItems())) {
                String volunteerId = major == null ? null : major.getVolunteerId();
                if (Strings.isNullOrEmpty(volunteerId) || !added.add(volunteerId)) {
                    return null;
                }
                OrderedItemDTO item = copy(existingById.get(volunteerId), OrderedItemDTO.class);
                if (item == null) {
                    item = new OrderedItemDTO();
                    item.setVolunteerId(volunteerId);
                    DraftItemDTO draft = workingItemsById.get(volunteerId);
                    CandidateItemDTO candidate = candidatesById.get(volunteerId);
                    item.setTier(draft != null ? draft.getTier()
                            : candidate == null ? null : candidate.getTier());
                    item.setSchoolName(draft != null ? draft.getSchoolName()
                            : candidate == null ? null : candidate.getSchoolName());
                    item.setMajorName(draft != null ? draft.getMajorName()
                            : candidate == null ? null : candidate.getMajorName());
                    item.setSource("review_fix");
                    item.setOrderedBy("system");
                    item.setOrderReason("review_fix_fill");
                }
                item.setPosition(items.size() + 1);
                items.add(item);
            }
        }
        return items;
    }

    static void normalizeGroupMode(PlanningStateDTO state) {
        if (state != null && state.getCandidatePoolState() != null
                && !"majorGroup".equalsIgnoreCase(
                state.getCandidatePoolState().getVolunteerModel())) {
            state.getCandidatePoolState().setVolunteerModel("majorGroup");
        }
    }

    private void adapt(FixProposalDTO proposal, FixProposalDTO generated,
                       PlanSolverResultDTO solverResult, PlanCommandDTO command,
                       PlanningStateDTO state, String findingCode, boolean coverage) {
        proposal.setProposalSource(RepairProposalTaxonomy.ProposalSource.REVIEW_CHECK);
        proposal.setSourceVersion(state.getVersion());
        proposal.setStrategy(STRATEGY);
        proposal.setSourceStrategy(command.getSourceStrategy());
        proposal.setFindingCode(findingCode);
        if (coverage && !proposal.getSourceCheckCodes().contains(COVERAGE_CHECK)) {
            proposal.getSourceCheckCodes().add(COVERAGE_CHECK);
        }
        proposal.setEvaluationVersion(command.getEvaluationVersion());
        proposal.setCommandDigest(command.getCommandDigest());
        proposal.setTitle(coverage ? "补齐覆盖要求预览" : "补齐方案目标数量预览");
        proposal.setSummary(generated.getSummary());
        proposal.setImpact(generated.getImpact());
        proposal.setCanonicalObjectiveDigest(generated.getCanonicalObjectiveDigest());
        proposal.setSolverVersion(generated.getSolverVersion());
        proposal.setSolverInputDigest(generated.getSolverInputDigest());
        proposal.setHardObjectiveVersion(generated.getHardObjectiveVersion());
        proposal.setSolverResult(copy(solverResult, PlanSolverResultDTO.class));
        proposal.setTargetCountBefore(generated.getTargetCountBefore());
        proposal.setTargetCountAfter(generated.getTargetCountAfter());
        proposal.setAddedCount(generated.getAddedCount());
        proposal.setAddedUnitCount(generated.getAddedUnitCount());
        proposal.setRemovedCount(generated.getRemovedCount());
        List<String> affected = new ArrayList<String>();
        for (FixProposalActionDTO action : safeList(generated.getActions())) {
            if (action != null) {
                for (String identity : safeList(action.getCandidateVolunteerIds())) {
                    if (!Strings.isNullOrEmpty(identity) && !affected.contains(identity)) {
                        affected.add(identity);
                    }
                }
            }
        }
        proposal.setAffectedVolunteerIds(affected);
        proposal.getActions().addAll(copyList(generated.getActions(), FixProposalActionDTO.class));
        proposal.setDryRunResult(copy(generated.getDryRunResult(), FixProposalDryRunResultDTO.class));
    }

    static List<OrderedItemDTO> orderedItemsFromSolver(
            List<String> orderedEntityIds,
            Map<String, OrderedItemDTO> existingById,
            Map<String, CandidateItemDTO> candidatesById) {
        List<OrderedItemDTO> items = new ArrayList<OrderedItemDTO>();
        for (String identity : orderedEntityIds) {
            OrderedItemDTO item = copy(existingById.get(identity), OrderedItemDTO.class);
            if (item == null) {
                CandidateItemDTO candidate = candidatesById.get(identity);
                item = new OrderedItemDTO();
                item.setVolunteerId(identity);
                if (candidate != null) {
                    item.setSchoolName(candidate.getSchoolName());
                    item.setMajorName(candidate.getMajorName());
                    item.setTier(candidate.getTier());
                }
                item.setSource("review_fix");
                item.setOrderedBy("system");
                item.setOrderReason("review_fix_fill");
            }
            item.setPosition(items.size() + 1);
            items.add(item);
        }
        return items;
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
        boolean coverage = finding.getCode() != null && finding.getCode().startsWith(COVERAGE_PREFIX);
        proposal.setTitle(coverage ? "补齐覆盖要求预览" : "补齐方案目标数量预览");
        proposal.setSummary("只读冻结预览；确认执行入口尚未启用。");
        proposal.getSourceCheckCodes().add(finding.getCode());
        if (coverage) {
            proposal.getSourceCheckCodes().add(COVERAGE_CHECK);
        }
        return proposal;
    }

    /**
     * 命令里的覆盖要求 → user-goal include 要求。canonicalize 负责统一 domain/key/values，
     * 并补齐默认 minCount；空列表由调用方 fail closed。
     */
    private List<UserGoalFixProposalReq.RequirementDTO> coverageRequirements(PlanCommandDTO command) {
        List<UserGoalFixProposalReq.RequirementDTO> requirements =
                new ArrayList<UserGoalFixProposalReq.RequirementDTO>();
        for (CoverageRequirementDTO source : safeList(command.getCoverageRequirements())) {
            if (source == null) {
                continue;
            }
            UserGoalFixProposalReq.RequirementDTO requirement = new UserGoalFixProposalReq.RequirementDTO();
            requirement.setKind(INCLUDE);
            requirement.setDomain(source.getDomain());
            requirement.setKey(source.getKey());
            requirement.setValues(new ArrayList<String>(safeList(source.getValues())));
            requirement.setMinCount(source.getMinCount());
            CoverageRequirementDTO canonical = CoverageRequirementSupport.canonicalize(requirement);
            requirement.setDomain(canonical.getDomain());
            requirement.setKey(canonical.getKey());
            requirement.setValues(canonical.getValues());
            requirement.setMinCount(canonical.getMinCount());
            requirements.add(requirement);
        }
        return requirements;
    }

    private FixProposalDTO blocked(FixProposalDTO proposal, String reason) {
        if (!Strings.isNullOrEmpty(reason)) {
            proposal.setBlockingReason(reason);
            proposal.getBlockingReasonCodes().add(reason);
        }
        proposal.getDryRunResult().setStatus("preview_only");
        return proposal;
    }

    private String solverFailureReason(FixProposalDTO generated) {
        if (generated != null && generated.getBlockingReasonCodes() != null) {
            for (String code : generated.getBlockingReasonCodes()) {
                if (!Strings.isNullOrEmpty(code)) {
                    return code;
                }
            }
        }
        return "review_fix_solver_unavailable";
    }

    private static <Value> Value copy(Value value, Class<Value> type) {
        return value == null ? null : JSON.parseObject(JSON.toJSONString(value), type);
    }

    private static <Value> List<Value> copyList(List<Value> values, Class<Value> type) {
        List<Value> result = new ArrayList<Value>();
        for (Value value : safeList(values)) {
            if (value != null) {
                result.add(copy(value, type));
            }
        }
        return result;
    }

    static <Value> List<Value> safeList(List<Value> values) {
        return values == null ? new ArrayList<Value>() : values;
    }
}
