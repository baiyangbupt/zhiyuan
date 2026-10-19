package com.ytell.zhiyuan.service.biz;

import com.alibaba.fastjson.JSON;
import com.google.common.base.Strings;
import com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO;
import com.ytell.zhiyuan.model.dto.planning.CoverageRequirementDTO;
import com.ytell.zhiyuan.model.dto.planning.DraftItemDTO;
import com.ytell.zhiyuan.model.dto.planning.DraftPlanStateDTO;
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
        List<DraftItemDTO> workingItems = safeList(state.getWorkingPlanState().getItems());
        // count_target 必须真正增加条数；coverage 允许在相同目标数下等量替换，
        // 因此只要求命令带正目标数（模式判定里已校验）。
        if (countTarget && (targetCount == null || targetCount <= 0
                || targetCount <= workingItems.size())) {
            return blocked(proposal, "review_fix_search_no_change");
        }
        // Search 切片只接受普通专业模式：专业组、unit 列表、优先规则与锁定/固定项
        // 都留给后续切片；这里 fail closed，避免误把结构修复缩水成纯加条。
        if ("majorGroup".equalsIgnoreCase(state.getCandidatePoolState().getVolunteerModel())
                || !safeList(state.getWorkingPlanState().getUnits()).isEmpty()
                || !safeList(state.getOrderedPlanState().getUnits()).isEmpty()
                || !PriorityRuleSupport.confirmedRules(state).isEmpty()) {
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

    private <Value> List<Value> copyList(List<Value> values, Class<Value> type) {
        List<Value> result = new ArrayList<Value>();
        for (Value value : safeList(values)) {
            if (value != null) {
                result.add(copy(value, type));
            }
        }
        return result;
    }

    private <Value> List<Value> safeList(List<Value> values) {
        return values == null ? new ArrayList<Value>() : values;
    }
}
