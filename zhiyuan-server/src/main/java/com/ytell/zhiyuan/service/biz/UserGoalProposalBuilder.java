package com.ytell.zhiyuan.service.biz;

import com.google.common.base.Strings;
import com.google.common.collect.Lists;
import com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO;
import com.ytell.zhiyuan.model.dto.planning.CandidatePoolStateDTO;
import com.ytell.zhiyuan.model.dto.planning.CandidateShortageDTO;
import com.ytell.zhiyuan.model.dto.planning.CanonicalPlanningObjectiveSetDTO;
import com.ytell.zhiyuan.model.dto.planning.CoverageRequirementDTO;
import com.ytell.zhiyuan.model.dto.planning.DraftItemDTO;
import com.ytell.zhiyuan.model.dto.planning.DraftUnitDTO;
import com.ytell.zhiyuan.model.dto.planning.FixProposalActionDTO;
import com.ytell.zhiyuan.model.dto.planning.FixProposalDTO;
import com.ytell.zhiyuan.model.dto.planning.FixProposalStateDTO;
import com.ytell.zhiyuan.model.dto.planning.HardConstraintsDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedItemDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedUnitDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningUnitMajorDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanSolverInputDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanSolverResultDTO;
import com.ytell.zhiyuan.model.dto.planning.PriorityRuleDTO;
import com.ytell.zhiyuan.model.dto.planning.ReplacementPairDTO;
import com.ytell.zhiyuan.model.dto.planning.TierAllocationResolutionDTO;
import com.ytell.zhiyuan.model.dto.planning.TierCountRangeDTO;
import com.ytell.zhiyuan.model.dto.planning.TierCountsDTO;
import com.ytell.zhiyuan.model.dto.planning.TierQuotaChangeDTO;
import com.ytell.zhiyuan.model.dto.planning.TierQuotaGoalDTO;
import com.ytell.zhiyuan.model.dto.planning.TierQuotaGoalRequestDTO;
import com.ytell.zhiyuan.model.dto.planning.UserGoalFixProposalReq;
import org.springframework.beans.BeanUtils;

import java.nio.charset.StandardCharsets;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import java.util.UUID;
import java.util.stream.Collectors;

final class UserGoalProposalBuilder {

    private static final String REASON_ENGINE_NOT_READY = "user_goal_proposal_engine_not_ready";
    private static final String REASON_SOURCE_VERSION_MISMATCH = "source_version_mismatch";
    private static final String REASON_GOAL_UNCLEAR = "user_goal_unclear";
    private static final String REASON_TARGET_NOT_FOUND = "user_goal_target_not_found";
    private static final String REASON_ENTITY_NEEDS_CLARIFICATION = "user_goal_entity_needs_clarification";
    private static final String REASON_CANDIDATE_POOL_INSUFFICIENT = "candidate_pool_insufficient";
    private static final String REASON_HARD_CONSTRAINTS_INSUFFICIENT = "hard_constraints_candidate_insufficient";
    private static final String REASON_PROJECTED_REQUIREMENTS_INVALID = "projected_requirements_invalid";
    private static final String REASON_PROJECTED_REQUIREMENTS_LOCKED = "projected_requirements_locked_item";
    private static final String REASON_COVERAGE_INSUFFICIENT = "coverage_requirement_insufficient";
    private static final String REASON_COVERAGE_REPLACEMENT_LOCKED = "coverage_replacement_locked_item";
    private static final String REASON_SOLVER_COMPLEXITY_LIMIT = "solver_complexity_limit";
    private static final String REASON_FILL_CANNOT_TRIM = "fill_to_count_cannot_trim_compliant_items";
    private static final String REASON_PRIORITY_INVALID = "priority_rule_invalid";
    private static final String REASON_PRIORITY_TARGET_NOT_IN_PLAN = "priority_target_not_in_plan";
    private static final String REASON_PRIORITY_PINNED_CONFLICT = "priority_pinned_position_conflict";
    private static final String REASON_PRIORITY_TIER_UNAVAILABLE = "priority_tier_unavailable";
    private static final String REASON_PRIORITY_COMPOSITE_NOT_SUPPORTED = "priority_composite_not_supported";
    private static final String REASON_TIER_QUOTA_INVALID = "tier_quota_invalid";
    private static final String REASON_TIER_QUOTA_COMPOSITE_NOT_SUPPORTED = "tier_quota_composite_not_supported";
    private static final String REASON_PRESERVE_COUNT_REQUIRES_INCLUDE = "preserve_count_requires_include";
    private static final String REASON_PRESERVE_COUNT_MISMATCH = "preserve_count_mismatch";
    private static final DeterministicPlanSolver PLAN_SOLVER = new OjalgoDeterministicPlanSolver();
    private UserGoalProposalBuilder() {
    }

    static FixProposalStateDTO build(PlanningStateDTO state, UserGoalFixProposalReq req) {
        FixProposalStateDTO proposalState = RepairProposalStateBuilder.newUserGoalState(state);
        FixProposalDTO proposal = buildProposal(state, req);
        proposalState.getProposals().add(proposal);
        proposalState.setTotal(proposalState.getProposals().size());
        proposalState.setStatus(RepairProposalStateBuilder.resolveStateStatus(proposalState.getProposals()));
        return proposalState;
    }

    private static void attachSolverMetadata(FixProposalDTO proposal,
                                             CanonicalPlanningObjectiveSetDTO objectiveSet,
                                             PlanSolverResultDTO solverResult) {
        if (proposal == null || objectiveSet == null || solverResult == null) {
            return;
        }
        proposal.setCanonicalObjectiveDigest(objectiveSet.getObjectiveDigest());
        proposal.setSolverVersion(solverResult.getSolverVersion());
        proposal.setSolverInputDigest(solverResult.getInputDigest());
        proposal.setSolverResult(solverResult);
    }

    private static TierQuotaChangeDTO buildTierQuotaChange(PlanningStateDTO state,
                                                            TierQuotaGoalRequestDTO requested,
                                                            Integer targetCount) {
        TierAllocationSupport.CompiledTierAllocation compiled =
                TierAllocationSupport.compile(state, requested, targetCount);
        TierQuotaChangeDTO result = new TierQuotaChangeDTO();
        result.setBeforeGoal(TierAllocationSupport.copyGoal(
                TierAllocationSupport.confirmedGoal(state)));
        result.setRequestedGoal(copyTierQuotaRequest(requested));
        result.setEffectiveGoal(TierAllocationSupport.copyGoal(compiled.getEffectiveSourceGoal()));
        result.setResolution(TierAllocationSupport.copyResolution(compiled.getResolution()));
        result.setStateChanged(compiled.isStateChanged());
        return result;
    }

    private static TierQuotaGoalRequestDTO copyTierQuotaRequest(TierQuotaGoalRequestDTO source) {
        if (source == null) {
            return null;
        }
        TierQuotaGoalDTO copied = TierAllocationSupport.copyGoal(source);
        TierQuotaGoalRequestDTO result = new TierQuotaGoalRequestDTO();
        BeanUtils.copyProperties(copied, result);
        result.setUpdateMode(source.getUpdateMode());
        return result;
    }

    private static void populateTierQuotaResolution(FixProposalDTO proposal,
                                                    PlanSolverResultDTO solverResult) {
        if (proposal == null || proposal.getTierQuotaChange() == null
                || proposal.getTierQuotaChange().getResolution() == null
                || solverResult == null || solverResult.getResolvedTierCounts() == null) {
            return;
        }
        proposal.getTierQuotaChange().getResolution().setResolvedCounts(
                TierAllocationSupport.copyCounts(solverResult.getResolvedTierCounts()));
    }

    private static String proposalReasonCode(
            TierQuotaGoalRequestDTO requested,
            PlanningObjectiveCompiler.CompilationException error) {
        if (requested != null
                && TierAllocationSupport.TYPE_EXACT_COUNTS.equalsIgnoreCase(requested.getType())
                && error.getReasonCode() != null && error.getReasonCode().startsWith("tier_exact_")) {
            return REASON_TIER_QUOTA_INVALID;
        }
        return error.getReasonCode();
    }

    private static String summarizeTierAllocation(TierQuotaGoalDTO goal,
                                                  TierAllocationResolutionDTO resolution) {
        if (goal == null) {
            return "";
        }
        String type = Strings.nullToEmpty(goal.getType()).trim().toLowerCase(Locale.ROOT);
        if (TierAllocationSupport.TYPE_EXACT_COUNTS.equals(type)) {
            return "冲稳保精确配额：" + TierQuotaSupport.summarize(goal);
        }
        if (TierAllocationSupport.TYPE_RATIOS.equals(type)) {
            TierCountsDTO resolved = resolution == null ? null : resolution.getResolvedCounts();
            return "冲稳保比例：" + goal.getSprintWeight() + ":" + goal.getStableWeight()
                    + ":" + goal.getProtectWeight() + (resolved == null ? ""
                    : "，解析为冲" + resolved.getSprintCount() + "个、稳"
                    + resolved.getStableCount() + "个、保" + resolved.getProtectCount() + "个");
        }
        return "冲稳保数量范围：冲" + summarizeBound(goal.getSprint())
                + "、稳" + summarizeBound(goal.getStable())
                + "、保" + summarizeBound(goal.getProtect());
    }

    private static String summarizeBound(TierCountRangeDTO bound) {
        if (bound == null) {
            return "不限";
        }
        if (bound.getMinCount() != null && bound.getMaxCount() != null) {
            return bound.getMinCount() + "-" + bound.getMaxCount() + "个";
        }
        return bound.getMinCount() != null ? "至少" + bound.getMinCount() + "个"
                : "最多" + bound.getMaxCount() + "个";
    }

    private static FixProposalDTO buildProposal(PlanningStateDTO state, UserGoalFixProposalReq req) {
        String goalType = normalizeGoalType(req == null ? null : req.getGoalType());
        String guardReason = resolveGuardReasonCode(state, req, goalType);
        if (!Strings.isNullOrEmpty(guardReason)) {
            return buildBlockedProposal(state, req, goalType, guardReason);
        }
        if (req != null && req.getTierQuotaGoal() != null
                && !RepairProposalTaxonomy.Strategy.FILL_MISSING_COUNT.equals(goalType)) {
            return buildScopeBlockedProposal(state, req, goalType, REASON_TIER_QUOTA_INVALID,
                    "冲稳保精确配额只支持 fill_to_count 方案目标，不能附加到其他 Proposal。");
        }
        if (RepairProposalTaxonomy.Strategy.ONLY_KEEP_SCOPE.equals(goalType)
                || RepairProposalTaxonomy.Strategy.MUST_INCLUDE_SCOPE.equals(goalType)
                || RepairProposalTaxonomy.Strategy.EXCLUDE_SCOPE.equals(goalType)) {
            return buildScopeProposal(state, req, goalType);
        }
        if (RepairProposalTaxonomy.Strategy.TUITION_BUDGET_SCOPE.equals(goalType)) {
            return buildTuitionBudgetProposal(state, req);
        }
        if (RepairProposalTaxonomy.Strategy.FILL_MISSING_COUNT.equals(goalType)) {
            return buildFillToCountProposal(state, req);
        }
        if (RepairProposalTaxonomy.Strategy.PRIORITIZE_WITHIN_TIER.equals(goalType)) {
            return buildPriorityProposal(state, req);
        }
        return buildBlockedProposal(state, req, goalType, REASON_ENGINE_NOT_READY);
    }

    private static FixProposalDTO buildFillToCountProposal(PlanningStateDTO state,
                                                            UserGoalFixProposalReq req) {
        Integer targetCount = req == null ? null : req.getTargetCount();
        boolean preserveCurrentCount = req != null && Boolean.FALSE.equals(req.getPersistTargetCount());
        if (targetCount == null || targetCount <= 0) {
            return buildScopeBlockedProposal(state, req, RepairProposalTaxonomy.Strategy.FILL_MISSING_COUNT,
                    REASON_GOAL_UNCLEAR, "补齐目标数量必须是大于 0 的整数。");
        }

        String requirementError = ProjectedHardRequirementSupport.validate(
                req == null ? null : req.getRequirements());
        if (!Strings.isNullOrEmpty(requirementError)) {
            return buildScopeBlockedProposal(state, req, RepairProposalTaxonomy.Strategy.FILL_MISSING_COUNT,
                    REASON_PROJECTED_REQUIREMENTS_INVALID, requirementError);
        }
        String priorityError = PriorityRuleSupport.validate(req == null ? null : req.getPriorityRules());
        if (!Strings.isNullOrEmpty(priorityError)) {
            return buildScopeBlockedProposal(state, req, RepairProposalTaxonomy.Strategy.FILL_MISSING_COUNT,
                    REASON_PRIORITY_INVALID, priorityError);
        }
        PriorityRuleDTO priorityRule = req == null || defaultList(req.getPriorityRules()).isEmpty()
                ? null : req.getPriorityRules().get(0);
        TierQuotaGoalRequestDTO tierQuotaGoal = req == null ? null : req.getTierQuotaGoal();
        if (tierQuotaGoal != null && (!defaultList(req.getRequirements()).isEmpty()
                || !defaultList(req.getPriorityRules()).isEmpty())) {
            return buildScopeBlockedProposal(state, req, RepairProposalTaxonomy.Strategy.FILL_MISSING_COUNT,
                    REASON_TIER_QUOTA_COMPOSITE_NOT_SUPPORTED,
                    "冲稳保精确配额暂不能与本轮普通要求或优先排序规则混合执行。请先单独确认精确配额。");
        }
        if (preserveCurrentCount && tierQuotaGoal == null
                && (defaultList(req.getRequirements()).isEmpty()
                || defaultList(req.getRequirements()).stream().anyMatch(requirement -> requirement == null
                || !ProjectedHardRequirementSupport.KIND_INCLUDE.equalsIgnoreCase(requirement.getKind())))) {
            return buildScopeBlockedProposal(state, req, RepairProposalTaxonomy.Strategy.FILL_MISSING_COUNT,
                    REASON_PRESERVE_COUNT_REQUIRES_INCLUDE,
                    "保持方案总数的覆盖调整必须包含明确数量的 include 要求，不能混入排除或只保留条件。");
        }

        boolean majorGroupMode = isMajorGroupMode(state);
        int currentCount = majorGroupMode ? currentPlanUnitCount(state) : currentPlanVolunteerCount(state);
        if (preserveCurrentCount && targetCount != currentCount) {
            return buildScopeBlockedProposal(state, req, RepairProposalTaxonomy.Strategy.FILL_MISSING_COUNT,
                    REASON_PRESERVE_COUNT_MISMATCH,
                    "保持方案总数的冻结数量与当前正式方案不一致，请基于最新方案重新生成预览。");
        }
        CanonicalPlanningObjectiveSetDTO objectiveSet;
        try {
            objectiveSet = PlanningObjectiveCompiler.compile(state, req);
        } catch (PlanningObjectiveCompiler.CompilationException ex) {
            return buildScopeBlockedProposal(state, req, RepairProposalTaxonomy.Strategy.FILL_MISSING_COUNT,
                    proposalReasonCode(tierQuotaGoal, ex), ex.getMessage());
        }
        List<CandidateItemDTO> poolCandidates = candidates(state);
        List<PlanVolunteer> current = currentPlanVolunteers(state, poolCandidates);
        HardConstraintsDTO projectedRequirements = ProjectedHardRequirementSupport.project(
                null, req == null ? null : req.getRequirements());
        HardConstraintsDTO projectedHardConstraints = ProjectedHardRequirementSupport.project(
                state, req == null ? null : req.getRequirements());
        FillCurrentProjection currentProjection = projectCurrentPlan(
                current, projectedRequirements, majorGroupMode);
        int retainedCount = currentProjection.retainedCount;
        boolean hasProjectedRequirements = req != null && req.getRequirements() != null
                && !req.getRequirements().isEmpty();
        boolean hasPriorityRule = priorityRule != null;
        boolean hasTierQuota = objectiveSet.getTierAllocationConstraint() != null;
        String projectedRequirementSummary = ProjectedHardRequirementSupport.summarize(
                req == null ? null : req.getRequirements());
        List<String> objectiveSummaries = Lists.newArrayList();
        if (!Strings.isNullOrEmpty(projectedRequirementSummary)) {
            objectiveSummaries.add(projectedRequirementSummary);
        }
        if (priorityRule != null) {
            objectiveSummaries.add(PriorityRuleSupport.summarize(priorityRule));
        }
        if (hasTierQuota) {
            objectiveSummaries.add(summarizeTierAllocation(
                    objectiveSet.getTierAllocationGoal(), objectiveSet.getTierAllocationResolution()));
        }
        String combinedObjectiveSummary = String.join("；", objectiveSummaries);
        FixProposalDTO proposal = buildUserGoalPreviewBase(state, req,
                RepairProposalTaxonomy.Strategy.FILL_MISSING_COUNT,
                preserveCurrentCount
                        ? "保持当前 " + targetCount + (majorGroupMode ? " 个专业组" : " 个志愿")
                        + (tierQuotaGoal == null ? "并落实覆盖数量的调整预览" : "并落实冲稳保精确配额的调整预览")
                        : "补齐到 " + targetCount + (majorGroupMode ? " 个专业组" : " 个志愿") + "的调整预览");
        if (hasTierQuota) {
            proposal.setTierQuotaChange(buildTierQuotaChange(state, tierQuotaGoal, targetCount));
        }
        if (currentProjection.lockedViolation) {
            String message = "当前方案中有锁定项不满足本轮硬要求，不能在不解除锁定的情况下生成原子调整预览。";
            return buildScopeBlockedProposal(state, req, RepairProposalTaxonomy.Strategy.FILL_MISSING_COUNT,
                    REASON_PROJECTED_REQUIREMENTS_LOCKED, message);
        }
        if (!hasProjectedRequirements && !hasPriorityRule && !hasTierQuota && currentCount >= targetCount) {
            CanonicalPlanningObjectiveSetDTO solverObjectiveSet = objectiveSet;
            if (currentCount > targetCount) {
                solverObjectiveSet = new CanonicalPlanningObjectiveSetDTO();
                BeanUtils.copyProperties(objectiveSet, solverObjectiveSet);
                solverObjectiveSet.setTargetCount(currentCount);
            }
            List<CoverageEntity> retained = buildRetainedCoverageEntities(
                    current, currentProjection, majorGroupMode);
            PlanSolverResultDTO solverResult = PLAN_SOLVER.solve(buildSolverInput(
                    solverObjectiveSet, retained, Lists.newArrayList(), majorGroupMode, null));
            attachSolverMetadata(proposal, objectiveSet, solverResult);
            proposal.setStatus(RepairProposalTaxonomy.Status.INFO);
            proposal.setSummary("当前方案已有 " + currentCount + (majorGroupMode ? " 个专业组" : " 个志愿")
                    + "，已经达到补齐目标 " + targetCount + "，本轮不需要新增。");
            proposal.setImpact(currentCount > targetCount
                    ? "补齐目标不会自动删减现有方案；如需精简，请单独提出移出或缩减目标。"
                    : "当前方案数量与目标一致。");
            proposal.setRequiresConfirmation(false);
            populateFillDryRun(proposal, state, currentCount, currentCount, 0, 0, 0, 0,
                    "当前方案已经达到补齐目标。");
            return proposal;
        }
        if (retainedCount > targetCount) {
            String message = "应用本轮硬要求后仍有 " + retainedCount + (majorGroupMode ? " 个专业组" : " 个志愿")
                    + "，高于补齐目标 " + targetCount + "；fill_to_count 不会额外删除符合要求的项目。";
            return buildScopeBlockedProposal(state, req, RepairProposalTaxonomy.Strategy.FILL_MISSING_COUNT,
                    REASON_FILL_CANNOT_TRIM, message);
        }

        int gap = targetCount - retainedCount;
        Set<String> selectedVolunteerIds = current.stream()
                .map(PlanVolunteer::getVolunteerId)
                .filter(value -> !Strings.isNullOrEmpty(value))
                .collect(Collectors.toCollection(LinkedHashSet::new));
        selectedVolunteerIds.removeAll(currentProjection.removeVolunteerIds);
        Set<String> selectedUnitIds = current.stream()
                .map(PlanVolunteer::getUnitId)
                .filter(value -> !Strings.isNullOrEmpty(value))
                .collect(Collectors.toCollection(LinkedHashSet::new));
        selectedUnitIds.removeAll(currentProjection.removeUnitIds);

        FillSelection selection = selectFillCandidates(projectedHardConstraints, poolCandidates,
                selectedVolunteerIds, selectedUnitIds, targetCount, majorGroupMode,
                current, currentProjection, objectiveSet, priorityRule);
        attachSolverMetadata(proposal, objectiveSet, selection.solverResult);
        populateTierQuotaResolution(proposal, selection.solverResult);
        if (!Strings.isNullOrEmpty(selection.blockingReason)) {
            String reasonCode = selection.blockingReasonCode;
            String message = selection.blockingReason;
            proposal.setStatus(RepairProposalTaxonomy.Status.BLOCKED);
            proposal.setSummary(message);
            proposal.setBlockingReason(message);
            proposal.getBlockingReasonCodes().add(reasonCode);
            CandidateShortageDTO shortage = buildBoundaryShortage(
                    RepairProposalTaxonomy.Strategy.FILL_MISSING_COUNT, reasonCode, message);
            shortage.setScope("coverage_requirement");
            if (hasTierQuota) {
                shortage.setScope("tier_quota");
            }
            shortage.setRequiredCount(targetCount);
            shortage.setCurrentCount(retainedCount);
            shortage.setShortageCount(selection.coverageShortageCount);
            shortage.setAvailableCount(selection.availableWithHardConstraints);
            proposal.getCandidateShortages().add(shortage);
            proposal.getDryRunResult().setStatus(RepairProposalTaxonomy.Status.BLOCKED);
            proposal.getDryRunResult().setMessage(message);
            proposal.setRequiresConfirmation(false);
            populateFillDryRun(proposal, state, currentCount, currentCount, 0, 0, 0, 0, message);
            return proposal;
        }
        int adjustedGap = gap + selection.replacementCount();
        if (selection.selectedCount() < adjustedGap) {
            String reasonCode = selection.availableWithoutHardConstraints >= adjustedGap
                    && selection.availableWithHardConstraints < adjustedGap
                    ? REASON_HARD_CONSTRAINTS_INSUFFICIENT : REASON_CANDIDATE_POOL_INSUFFICIENT;
            String domain = majorGroupMode ? "专业组" : "志愿";
            String message = "应用本轮要求后方案保留 " + retainedCount + " 个" + domain + "，补齐到 " + targetCount
                    + " 并满足覆盖要求还需要补入 " + adjustedGap + " 个；按本轮及已确认要求过滤后仅有 "
                    + selection.availableWithHardConstraints + " 个可补入，不能生成部分执行预览。";
            proposal.setStatus(RepairProposalTaxonomy.Status.BLOCKED);
            proposal.setSummary(message);
            proposal.setBlockingReason(message);
            proposal.getBlockingReasonCodes().add(reasonCode);
            CandidateShortageDTO shortage = buildBoundaryShortage(
                    RepairProposalTaxonomy.Strategy.FILL_MISSING_COUNT, reasonCode, message);
            shortage.setScope(REASON_HARD_CONSTRAINTS_INSUFFICIENT.equals(reasonCode)
                    ? "hard_constraints" : "candidate_pool");
            shortage.setRequiredCount(targetCount);
            shortage.setCurrentCount(retainedCount);
            shortage.setShortageCount(adjustedGap - selection.availableWithHardConstraints);
            shortage.setAvailableCount(selection.availableWithHardConstraints);
            proposal.getCandidateShortages().add(shortage);
            proposal.getDryRunResult().setStatus(RepairProposalTaxonomy.Status.BLOCKED);
            proposal.getDryRunResult().setMessage(message);
            proposal.setRequiresConfirmation(false);
            populateFillDryRun(proposal, state, currentCount, currentCount, 0, 0, 0, 0, message);
            return proposal;
        }

        List<String> removeVolunteerIds = Lists.newArrayList(currentProjection.removeVolunteerIds);
        selection.removeVolunteerIds.stream()
                .filter(value -> !removeVolunteerIds.contains(value))
                .forEach(removeVolunteerIds::add);
        List<String> removeUnitIds = Lists.newArrayList(currentProjection.removeUnitIds);
        selection.removeUnitIds.stream()
                .filter(value -> !removeUnitIds.contains(value))
                .forEach(removeUnitIds::add);
        PriorityRuleSupport.Analysis priorityAnalysis = priorityRule == null ? null
                : analyzeProjectedPriority(current, poolCandidates, removeVolunteerIds,
                removeUnitIds, selection, majorGroupMode, priorityRule);
        if (priorityAnalysis != null && priorityAnalysis.getMatchedCount() == 0) {
            return buildScopeBlockedProposal(state, req, RepairProposalTaxonomy.Strategy.FILL_MISSING_COUNT,
                    REASON_PRIORITY_TARGET_NOT_IN_PLAN,
                    "按本轮数量和筛选要求投影后的最终方案没有命中优先目标；同档前置不会自动增加目标项目。");
        }
        if (priorityAnalysis != null && priorityAnalysis.hasMissingTier()) {
            return buildScopeBlockedProposal(state, req, RepairProposalTaxonomy.Strategy.FILL_MISSING_COUNT,
                    REASON_PRIORITY_TIER_UNAVAILABLE,
                    "按本轮要求投影后的最终方案存在未标注冲稳保档位的项目，不能可靠执行同档前置。");
        }
        if (priorityAnalysis != null && priorityAnalysis.hasPinnedConflict()) {
            return buildScopeBlockedProposal(state, req, RepairProposalTaxonomy.Strategy.FILL_MISSING_COUNT,
                    REASON_PRIORITY_PINNED_CONFLICT,
                    "按本轮要求执行同档前置会影响已固定位置的志愿，不能生成组合执行预览。");
        }
        if (!removeVolunteerIds.isEmpty()) {
            FixProposalActionDTO removeAction = new FixProposalActionDTO();
            removeAction.setActionType(RepairProposalTaxonomy.ActionType.REMOVE_VOLUNTEERS);
            removeAction.setLevel(majorGroupMode ? "unit" : "volunteer");
            removeAction.setSummary("移出不满足本轮硬要求的 "
                    + (majorGroupMode ? removeUnitIds.size() + " 个专业组"
                    : removeVolunteerIds.size() + " 个志愿"));
            removeAction.setDetail(selection.replacementCount() > 0
                    ? hasTierQuota
                    ? "其中包含为满足冲稳保精确配额而进行的等量替换。"
                    : "其中包含为满足非排他覆盖要求而进行的等量替换。"
                    : "这些项目不满足本轮要求。");
            removeAction.setUnitIds(removeUnitIds);
            removeAction.setRemoveUnitIds(removeUnitIds);
            removeAction.setVolunteerIds(removeVolunteerIds);
            removeAction.setRemoveVolunteerIds(removeVolunteerIds);
            proposal.getActions().add(removeAction);
        }
        if (adjustedGap > 0) {
            FixProposalActionDTO action = new FixProposalActionDTO();
            action.setActionType(RepairProposalTaxonomy.ActionType.FILL_TOTAL_COUNT);
            action.setLevel(majorGroupMode ? "unit" : "volunteer");
            action.setSummary("从当前候选池补入 " + adjustedGap + (majorGroupMode ? " 个专业组" : " 个志愿"));
            action.setDetail(selection.replacementCount() > 0
                    ? "其中 " + selection.replacementCount() + " 个用于"
                    + (hasTierQuota ? "冲稳保精确配额" : "覆盖要求")
                    + "的等量替换；最终数量精确达到 " + targetCount + "。"
                    : "补入后方案数量将从 " + retainedCount + " 精确达到 " + targetCount + "。");
            action.setUnitIds(selection.unitIds);
            action.setVolunteerIds(selection.volunteerIds);
            action.setCandidateUnitIds(selection.unitIds);
            action.setCandidateVolunteerIds(selection.volunteerIds);
            proposal.getActions().add(action);
        }
        if (priorityAnalysis != null && priorityAnalysis.getInversionCount() > 0) {
            FixProposalActionDTO action = new FixProposalActionDTO();
            action.setActionType(RepairProposalTaxonomy.ActionType.REORDER_VOLUNTEERS);
            action.setLevel(majorGroupMode ? "unit" : "volunteer");
            action.setSummary("在最终方案各档内前置目标项目");
            action.setDetail(PriorityRuleSupport.summarize(priorityRule));
            if (majorGroupMode) {
                action.setUnitIds(priorityAnalysis.getMatchedIds());
            } else {
                action.setVolunteerIds(priorityAnalysis.getMatchedIds());
            }
            proposal.getActions().add(action);
        }
        boolean planChanged = selection.solverResult != null
                && RepairProposalTaxonomy.Status.READY.equals(selection.solverResult.getStatus());
        boolean objectiveChanged = Boolean.TRUE.equals(objectiveSet.getTierAllocationStateChanged());
        if (!planChanged && !objectiveChanged && !hasProjectedRequirements && !hasPriorityRule) {
            proposal.setStatus(RepairProposalTaxonomy.Status.INFO);
            proposal.setRequiresConfirmation(false);
            proposal.setSummary("当前方案和已确认冲稳保目标都已满足，本轮无需更新。");
            proposal.setImpact("方案项目和已确认硬目标均保持不变。");
            populateFillDryRun(proposal, state, currentCount, currentCount,
                    0, 0, 0, 0, "当前方案和冲稳保目标均无变化。");
            populateTierQuotaDryRun(proposal, current, majorGroupMode, selection.solverResult);
            return proposal;
        }
        proposal.setStatus(RepairProposalTaxonomy.Status.READY);
        int removeCount = majorGroupMode
                ? removeUnitIds.size() : removeVolunteerIds.size();
        String prioritySummary = priorityAnalysis == null ? ""
                : priorityAnalysis.getInversionCount() == 0
                ? "；同档前置目标当前已满足，确认后会保存并持续执行这条规则"
                : "；同时将 " + priorityAnalysis.getMovedTargetCount() + " 个目标项目在各自档位内前移，消除 "
                + priorityAnalysis.getInversionCount() + " 处同档逆序";
        if (!hasProjectedRequirements && !hasPriorityRule && !hasTierQuota) {
            proposal.setSummary("当前方案有 " + currentCount + (majorGroupMode ? " 个专业组" : " 个志愿")
                    + "；本次将从符合已确认要求的候选中补入 " + gap + " 个，达到 " + targetCount + " 个。");
            proposal.setImpact("确认前不会改动方案；确认后只应用这份预览中的候选，并重新生成和审查方案。");
        } else if (removeCount == 0 && gap == 0) {
            proposal.setSummary("当前方案项目不变；本轮要求：" + combinedObjectiveSummary
                    + prioritySummary + "。确认后只保存冲稳保硬目标并刷新方案。");
            proposal.setImpact("确认前不会改动方案；确认后会在同一事务中持久化本轮要求、执行同档硬序并重新审查方案。");
        } else {
            String objectiveSummary = Strings.isNullOrEmpty(combinedObjectiveSummary)
                    ? "补齐数量" : combinedObjectiveSummary;
            proposal.setSummary("当前方案有 " + currentCount + (majorGroupMode ? " 个专业组" : " 个志愿")
                    + "；本轮要求：" + objectiveSummary + "。本次先移出 " + removeCount
                    + " 个不符合或需等量替换的项目，再补入 " + adjustedGap
                    + " 个符合本轮及已确认要求的候选，最终达到 " + targetCount + " 个" + prioritySummary + "。");
            proposal.setImpact("确认前不会改动方案；确认后会在同一事务中持久化本轮要求、应用最终集合、执行同档硬序并重新审查方案。");
        }
        proposal.setRequiresConfirmation(true);
        populateFillDryRun(proposal, state, currentCount, targetCount,
                selection.unitIds.size(), selection.volunteerIds.size(),
                removeUnitIds.size(), removeVolunteerIds.size(),
                preserveCurrentCount
                        ? hasTierQuota
                        ? "已生成保持方案总数的冲稳保精确配额调整预览，等待确认后执行。"
                        : "已生成保持方案总数的覆盖调整预览，等待确认后执行。"
                        : "已生成精确补齐预览，等待确认后执行。");
        populateTierQuotaDryRun(proposal, current, majorGroupMode, selection.solverResult);
        populatePriorityDryRun(proposal, priorityAnalysis);
        return proposal;
    }

    private static FixProposalDTO buildPriorityProposal(PlanningStateDTO state,
                                                        UserGoalFixProposalReq req) {
        if (req != null && ((req.getRequirements() != null && !req.getRequirements().isEmpty())
                || req.getTargetCount() != null)) {
            return buildScopeBlockedProposal(state, req,
                    RepairProposalTaxonomy.Strategy.PRIORITIZE_WITHIN_TIER,
                    REASON_PRIORITY_COMPOSITE_NOT_SUPPORTED,
                    "同档前置首个纵切只接受 priorityRules；数量和筛选要求不能拆开或部分执行。" );
        }
        if (req == null || req.getPriorityRules() == null || req.getPriorityRules().isEmpty()) {
            return buildScopeBlockedProposal(state, req,
                    RepairProposalTaxonomy.Strategy.PRIORITIZE_WITHIN_TIER,
                    REASON_PRIORITY_INVALID, "同档前置必须包含一条明确的 priority rule。" );
        }
        String validationError = PriorityRuleSupport.validate(req == null ? null : req.getPriorityRules());
        if (!Strings.isNullOrEmpty(validationError)) {
            return buildScopeBlockedProposal(state, req,
                    RepairProposalTaxonomy.Strategy.PRIORITIZE_WITHIN_TIER,
                    REASON_PRIORITY_INVALID, validationError);
        }
        PriorityRuleDTO rule = req.getPriorityRules().get(0);
        List<CandidateItemDTO> poolCandidates = candidates(state);
        PriorityRuleSupport.Analysis analysis = PriorityRuleSupport.analyze(state, poolCandidates, rule);
        if (analysis.getEntityCount() == 0) {
            return buildScopeBlockedProposal(state, req,
                    RepairProposalTaxonomy.Strategy.PRIORITIZE_WITHIN_TIER,
                    REASON_TARGET_NOT_FOUND, "当前还没有正式方案，不能生成同档前置预览。" );
        }
        if (analysis.getMatchedCount() == 0) {
            return buildScopeBlockedProposal(state, req,
                    RepairProposalTaxonomy.Strategy.PRIORITIZE_WITHIN_TIER,
                    REASON_PRIORITY_TARGET_NOT_IN_PLAN,
                    "当前方案没有命中“" + String.join("、", rule.getValues())
                            + "”的项目；同档前置只重排现有方案，不会自动增加新项目。" );
        }
        if (analysis.hasMissingTier()) {
            return buildScopeBlockedProposal(state, req,
                    RepairProposalTaxonomy.Strategy.PRIORITIZE_WITHIN_TIER,
                    REASON_PRIORITY_TIER_UNAVAILABLE,
                    "当前方案存在未标注冲稳保档位的项目，不能生成可靠的同档前置预览。" );
        }
        if (analysis.hasPinnedConflict()) {
            return buildScopeBlockedProposal(state, req,
                    RepairProposalTaxonomy.Strategy.PRIORITIZE_WITHIN_TIER,
                    REASON_PRIORITY_PINNED_CONFLICT,
                    "执行同档前置会影响已固定位置的志愿；本轮不能同时保持固定位置并完成前置目标。" );
        }

        CanonicalPlanningObjectiveSetDTO objectiveSet;
        try {
            objectiveSet = PlanningObjectiveCompiler.compile(state, req);
        } catch (PlanningObjectiveCompiler.CompilationException ex) {
            return buildScopeBlockedProposal(state, req,
                    RepairProposalTaxonomy.Strategy.PRIORITIZE_WITHIN_TIER,
                    ex.getReasonCode(), ex.getMessage());
        }
        List<PlanVolunteer> current = currentPlanVolunteers(state, poolCandidates);
        FillCurrentProjection projection = new FillCurrentProjection();
        List<CoverageEntity> retained = buildRetainedCoverageEntities(
                current, projection, analysis.isUnitMode());
        CanonicalPlanningObjectiveSetDTO solverObjectiveSet = new CanonicalPlanningObjectiveSetDTO();
        BeanUtils.copyProperties(objectiveSet, solverObjectiveSet);
        solverObjectiveSet.setTargetCount(retained.size());
        PlanSolverResultDTO solverResult = PLAN_SOLVER.solve(buildSolverInput(
                solverObjectiveSet, retained, Lists.newArrayList(), analysis.isUnitMode(), rule));
        if (RepairProposalTaxonomy.Status.BLOCKED.equals(solverResult.getStatus())) {
            PlanSolverResultDTO.DiagnosticDTO diagnostic = solverResult.getDiagnostics().isEmpty()
                    ? null : solverResult.getDiagnostics().get(0);
            return buildScopeBlockedProposal(state, req,
                    RepairProposalTaxonomy.Strategy.PRIORITIZE_WITHIN_TIER,
                    diagnostic == null ? REASON_PRIORITY_INVALID : diagnostic.getReasonCode(),
                    diagnostic == null ? "当前方案无法形成 canonical priority 预览。" : diagnostic.getMessage());
        }

        FixProposalDTO proposal = buildUserGoalPreviewBase(state, req,
                RepairProposalTaxonomy.Strategy.PRIORITIZE_WITHIN_TIER,
                "同档优先靠前的方案调整预览");
        attachSolverMetadata(proposal, objectiveSet, solverResult);
        proposal.setStatus(RepairProposalTaxonomy.Status.READY);
        proposal.setRequiresConfirmation(true);
        String domain = analysis.isUnitMode() ? "专业组" : "志愿";
        if (analysis.getInversionCount() == 0) {
            proposal.setSummary("当前方案中的 " + analysis.getMatchedCount() + " 个目标" + domain
                    + "已经在各自冲稳保档内优先靠前；确认后会保存并持续执行这条规则。");
            proposal.setImpact("志愿集合、冲稳保档位和固定位置保持不变；后续重新生成方案仍会校验同档前置目标。");
        } else {
            proposal.setSummary("当前方案命中 " + analysis.getMatchedCount() + " 个目标" + domain
                    + "；确认后将其中 " + analysis.getMovedTargetCount()
                    + " 个在各自冲稳保档内前移，消除 " + analysis.getInversionCount() + " 处同档逆序。");
            proposal.setImpact("只在同一冲稳保档内稳定前置匹配项；志愿集合、档位和固定位置保持不变。");
            FixProposalActionDTO action = new FixProposalActionDTO();
            action.setActionType(RepairProposalTaxonomy.ActionType.REORDER_VOLUNTEERS);
            action.setLevel(analysis.isUnitMode() ? "unit" : "volunteer");
            action.setSummary("按硬优先规则在同档内前置目标项目");
            action.setDetail(PriorityRuleSupport.summarize(rule));
            if (analysis.isUnitMode()) {
                action.setUnitIds(analysis.getMatchedIds());
            } else {
                action.setVolunteerIds(analysis.getMatchedIds());
            }
            proposal.getActions().add(action);
        }
        proposal.getDryRunResult().setStatus(RepairProposalTaxonomy.Status.READY);
        proposal.getDryRunResult().setMessage("确认后同档逆序数必须降为 0。");
        proposal.getDryRunResult().setBeforeUnitTotal(currentPlanUnitCount(state));
        proposal.getDryRunResult().setAfterUnitTotal(currentPlanUnitCount(state));
        proposal.getDryRunResult().setBeforeVolunteerTotal(currentPlanVolunteerCount(state));
        proposal.getDryRunResult().setAfterVolunteerTotal(currentPlanVolunteerCount(state));
        populatePriorityDryRun(proposal, analysis);
        return proposal;
    }

    private static PriorityRuleSupport.Analysis analyzeProjectedPriority(
            List<PlanVolunteer> current,
            List<CandidateItemDTO> poolCandidates,
            List<String> removeVolunteerIds,
            List<String> removeUnitIds,
            FillSelection selection,
            boolean unitMode,
            PriorityRuleDTO rule) {
        PlanningStateDTO projected = new PlanningStateDTO();
        projected.getCandidatePoolState().setVolunteerModel(unitMode ? "majorGroup" : "major");
        Map<String, CandidateItemDTO> candidateViews = new LinkedHashMap<String, CandidateItemDTO>();
        for (PlanVolunteer volunteer : defaultList(current)) {
            if (volunteer != null && volunteer.getCandidate() != null
                    && !Strings.isNullOrEmpty(volunteer.getVolunteerId())) {
                candidateViews.put(volunteer.getVolunteerId(), volunteer.asCandidate());
            }
        }
        for (CandidateItemDTO candidate : defaultList(poolCandidates)) {
            if (candidate != null && !Strings.isNullOrEmpty(candidate.getVolunteerId())) {
                candidateViews.putIfAbsent(candidate.getVolunteerId(), candidate);
            }
        }
        projected.getCandidatePoolState().setItems(Lists.newArrayList(candidateViews.values()));
        Set<String> removedVolunteers = new LinkedHashSet<String>(defaultList(removeVolunteerIds));
        Set<String> removedUnits = new LinkedHashSet<String>(defaultList(removeUnitIds));
        if (unitMode) {
            Map<String, List<PlanVolunteer>> retainedByUnit = defaultList(current).stream()
                    .filter(Objects::nonNull)
                    .filter(item -> !removedVolunteers.contains(item.getVolunteerId()))
                    .filter(item -> !removedUnits.contains(item.getUnitId()))
                    .collect(Collectors.groupingBy(
                            item -> firstNonEmpty(item.getUnitId(), item.getVolunteerId()),
                            LinkedHashMap::new, Collectors.toList()));
            for (Map.Entry<String, List<PlanVolunteer>> entry : retainedByUnit.entrySet()) {
                projected.getOrderedPlanState().getUnits().add(
                        projectedUnit(entry.getKey(), entry.getValue()));
            }
            Map<String, List<CandidateItemDTO>> selectedByUnit = defaultList(selection.volunteerIds).stream()
                    .map(candidateViews::get)
                    .filter(Objects::nonNull)
                    .collect(Collectors.groupingBy(
                            candidate -> firstNonEmpty(
                                    RepairCandidateSelector.resolveInitialRecommendationUnitId(candidate),
                                    candidate.getVolunteerId()),
                            LinkedHashMap::new, Collectors.toList()));
            for (Map.Entry<String, List<CandidateItemDTO>> entry : selectedByUnit.entrySet()) {
                projected.getOrderedPlanState().getUnits().add(
                        projectedUnit(entry.getKey(), entry.getValue(), false));
            }
        } else {
            for (PlanVolunteer volunteer : defaultList(current)) {
                if (volunteer == null || removedVolunteers.contains(volunteer.getVolunteerId())
                        || removedUnits.contains(volunteer.getUnitId())) {
                    continue;
                }
                projected.getOrderedPlanState().getItems().add(projectedItem(
                        volunteer.getVolunteerId(), volunteer.asCandidate(), volunteer.isPinned()));
            }
            for (String volunteerId : defaultList(selection.volunteerIds)) {
                CandidateItemDTO candidate = candidateViews.get(volunteerId);
                if (candidate != null) {
                    projected.getOrderedPlanState().getItems().add(
                            projectedItem(volunteerId, candidate, false));
                }
            }
        }
        return PriorityRuleSupport.analyze(projected, projected.getCandidatePoolState().getItems(), rule);
    }

    private static OrderedItemDTO projectedItem(String volunteerId,
                                                CandidateItemDTO candidate,
                                                boolean pinned) {
        OrderedItemDTO item = new OrderedItemDTO();
        item.setVolunteerId(volunteerId);
        item.setTier(candidate == null ? null : candidate.getTier());
        item.setSchoolName(candidate == null ? null : candidate.getSchoolName());
        item.setMajorName(candidate == null ? null : candidate.getMajorName());
        item.setPinned(pinned);
        return item;
    }

    private static OrderedUnitDTO projectedUnit(String unitId, List<PlanVolunteer> volunteers) {
        List<CandidateItemDTO> candidates = defaultList(volunteers).stream()
                .filter(Objects::nonNull)
                .map(PlanVolunteer::asCandidate)
                .filter(Objects::nonNull)
                .collect(Collectors.toList());
        boolean pinned = defaultList(volunteers).stream()
                .anyMatch(item -> item != null && item.isPinned());
        return projectedUnit(unitId, candidates, pinned);
    }

    private static OrderedUnitDTO projectedUnit(String unitId,
                                                List<CandidateItemDTO> candidates,
                                                boolean pinned) {
        CandidateItemDTO representative = defaultList(candidates).stream()
                .filter(Objects::nonNull)
                .findFirst()
                .orElse(new CandidateItemDTO());
        OrderedUnitDTO unit = new OrderedUnitDTO();
        unit.setUnitId(unitId);
        unit.setTier(representative.getTier());
        unit.setSchoolName(representative.getSchoolName());
        unit.setProvinceName(representative.getProvinceName());
        unit.setCityName(representative.getCityName());
        unit.setSchoolLevel(representative.getSchoolLevel());
        unit.setSchoolNature(representative.getSchoolNature());
        unit.setSchoolCategory(representative.getSchoolCategory());
        unit.setPinned(pinned);
        for (CandidateItemDTO candidate : defaultList(candidates)) {
            if (candidate == null || Strings.isNullOrEmpty(candidate.getVolunteerId())) {
                continue;
            }
            PlanningUnitMajorDTO major = new PlanningUnitMajorDTO();
            major.setVolunteerId(candidate.getVolunteerId());
            major.setMajorName(candidate.getMajorName());
            major.setMajorCategoryId(candidate.getMajorCategoryId());
            major.setMajorSubCategoryId(candidate.getMajorSubCategoryId());
            major.setMajorPlanTags(defaultList(candidate.getMajorPlanTags()));
            unit.getMajorItems().add(major);
        }
        return unit;
    }

    private static void populatePriorityDryRun(FixProposalDTO proposal,
                                               PriorityRuleSupport.Analysis analysis) {
        if (proposal == null || analysis == null) {
            return;
        }
        proposal.getDryRunResult().setPriorityMatchedCount(analysis.getMatchedCount());
        proposal.getDryRunResult().setPriorityBeforeInversionCount(analysis.getInversionCount());
        proposal.getDryRunResult().setPriorityAfterInversionCount(0);
        proposal.getDryRunResult().setPriorityMovedTargetCount(analysis.getMovedTargetCount());
        Integer affectedUnitCount = proposal.getDryRunResult().getAffectedUnitCount();
        Integer affectedVolunteerCount = proposal.getDryRunResult().getAffectedVolunteerCount();
        if (analysis.isUnitMode() && (affectedUnitCount == null || affectedUnitCount == 0)) {
            proposal.getDryRunResult().setAffectedUnitCount(analysis.getMovedTargetCount());
        }
        if (!analysis.isUnitMode() && (affectedVolunteerCount == null || affectedVolunteerCount == 0)) {
            proposal.getDryRunResult().setAffectedVolunteerCount(analysis.getMovedTargetCount());
        }
    }

    private static FillSelection selectFillCandidates(HardConstraintsDTO projectedHardConstraints,
                                                      List<CandidateItemDTO> poolCandidates,
                                                      Set<String> selectedVolunteerIds,
                                                      Set<String> selectedUnitIds,
                                                      int targetCount,
                                                      boolean unitMode,
                                                      List<PlanVolunteer> current,
                                                      FillCurrentProjection currentProjection,
                                                      CanonicalPlanningObjectiveSetDTO objectiveSet,
                                                      PriorityRuleDTO priorityRule) {
        List<FillOption> available = buildFillOptions(poolCandidates, selectedVolunteerIds, selectedUnitIds, unitMode);
        List<FillOption> eligible = available.stream()
                .map(option -> option.retainAllowed(projectedHardConstraints))
                .filter(Objects::nonNull)
                .collect(Collectors.toList());
        FillSelection selection = new FillSelection();
        selection.unitMode = unitMode;
        selection.availableWithoutHardConstraints = available.size();
        selection.availableWithHardConstraints = eligible.size();

        List<CoverageEntity> retained = buildRetainedCoverageEntities(
                current, currentProjection, unitMode);
        PlanSolverInputDTO solverInput = buildSolverInput(
                objectiveSet, retained, eligible, unitMode, priorityRule);
        selection.solverResult = PLAN_SOLVER.solve(solverInput);
        if (RepairProposalTaxonomy.Status.BLOCKED.equals(selection.solverResult.getStatus())) {
            PlanSolverResultDTO.DiagnosticDTO diagnostic = selection.solverResult.getDiagnostics().isEmpty()
                    ? null : selection.solverResult.getDiagnostics().get(0);
            String solverReason = diagnostic == null ? null : diagnostic.getReasonCode();
            if ("candidate_shortage".equals(solverReason)) {
                return selection;
            }
            boolean tierDiagnostic = objectiveSet.getTierAllocationConstraint() != null
                    && !Strings.isNullOrEmpty(solverReason)
                    && (solverReason.startsWith("tier_") || "locked_conflict".equals(solverReason));
            String reasonCode = tierDiagnostic ? solverReason
                    : "solver_complexity_limit".equals(solverReason)
                    ? REASON_SOLVER_COMPLEXITY_LIMIT
                    : "locked_conflict".equals(solverReason) || "pinned_conflict".equals(solverReason)
                    ? REASON_COVERAGE_REPLACEMENT_LOCKED
                    : "candidate_shortage".equals(solverReason)
                    ? selection.availableWithoutHardConstraints >= targetCount - retained.size()
                    ? REASON_HARD_CONSTRAINTS_INSUFFICIENT : REASON_CANDIDATE_POOL_INSUFFICIENT
                    : REASON_COVERAGE_INSUFFICIENT;
            int shortage = diagnostic == null || diagnostic.getRequiredCount() == null
                    || diagnostic.getAvailableCount() == null ? 1
                    : Math.max(0, diagnostic.getRequiredCount() - diagnostic.getAvailableCount());
            String message = diagnostic == null || Strings.isNullOrEmpty(diagnostic.getMessage())
                    ? "当前候选事实无法同时满足全部 canonical 目标。" : diagnostic.getMessage();
            selection.block(reasonCode, message, shortage);
            return selection;
        }

        Map<String, FillOption> additions = eligible.stream().collect(Collectors.toMap(
                option -> option.entityId(unitMode), option -> option,
                (left, right) -> left, LinkedHashMap::new));
        Map<String, CoverageEntity> removals = retained.stream().collect(Collectors.toMap(
                entity -> entity.entityId(unitMode), entity -> entity,
                (left, right) -> left, LinkedHashMap::new));
        for (String entityId : selection.solverResult.getRemoveEntityIds()) {
            CoverageEntity entity = removals.get(entityId);
            if (entity != null) {
                selection.removeUnitIds.addAll(entity.unitIds);
                selection.removeVolunteerIds.addAll(entity.volunteerIds);
            }
        }
        for (String entityId : selection.solverResult.getAddEntityIds()) {
            selection.add(additions.get(entityId));
        }
        return selection;
    }

    private static PlanSolverInputDTO buildSolverInput(CanonicalPlanningObjectiveSetDTO objectiveSet,
                                                       List<CoverageEntity> retained,
                                                       List<FillOption> available,
                                                       boolean unitMode,
                                                       PriorityRuleDTO priorityRule) {
        PlanSolverInputDTO result = new PlanSolverInputDTO();
        result.setObjectiveSet(objectiveSet);
        int stableOrder = 0;
        for (CoverageEntity entity : defaultList(retained)) {
            result.getCandidates().add(entity.asSolverCandidate(
                    unitMode, stableOrder++, objectiveSet.getCoverageConstraints(), priorityRule));
        }
        for (FillOption option : defaultList(available)) {
            result.getCandidates().add(option.asSolverCandidate(
                    unitMode, stableOrder++, objectiveSet.getCoverageConstraints(), priorityRule));
        }
        return result;
    }

    private static List<String> matchedCoverageIds(List<CandidateItemDTO> candidates,
                                                   List<CoverageRequirementDTO> coverage) {
        List<String> result = Lists.newArrayList();
        for (int index = 0; index < defaultList(coverage).size(); index++) {
            CoverageRequirementDTO objective = coverage.get(index);
            if (defaultList(candidates).stream()
                    .anyMatch(candidate -> CoverageRequirementSupport.matches(candidate, objective))) {
                result.add("coverage:" + index);
            }
        }
        return result;
    }

    private static List<FillOption> buildFillOptions(List<CandidateItemDTO> poolCandidates,
                                                     Set<String> selectedVolunteerIds,
                                                     Set<String> selectedUnitIds,
                                                     boolean unitMode) {
        if (!unitMode) {
            return defaultList(poolCandidates).stream()
                    .filter(candidate -> candidate != null && !Strings.isNullOrEmpty(candidate.getVolunteerId()))
                    .filter(candidate -> !selectedVolunteerIds.contains(candidate.getVolunteerId()))
                    .filter(RepairCandidateSelector::isCompensationSafeCandidate)
                    .sorted(buildCandidatePreviewComparator())
                    .map(FillOption::new)
                    .collect(Collectors.toList());
        }
        Map<String, List<CandidateItemDTO>> grouped = new LinkedHashMap<String, List<CandidateItemDTO>>();
        defaultList(poolCandidates).stream()
                .filter(candidate -> candidate != null && !Strings.isNullOrEmpty(candidate.getVolunteerId()))
                .forEach(candidate -> {
                    String unitId = RepairCandidateSelector.resolveInitialRecommendationUnitId(candidate);
                    if (!Strings.isNullOrEmpty(unitId) && !selectedUnitIds.contains(unitId)) {
                        grouped.computeIfAbsent(unitId, ignored -> Lists.newArrayList()).add(candidate);
                    }
                });
        return grouped.entrySet().stream()
                .map(entry -> new FillOption(entry.getKey(), entry.getValue()))
                .filter(option -> option.candidates.stream().allMatch(RepairCandidateSelector::isCompensationSafeCandidate))
                .sorted((left, right) -> buildCandidatePreviewComparator().compare(left.representative, right.representative))
                .collect(Collectors.toList());
    }

    private static List<CoverageEntity> buildRetainedCoverageEntities(List<PlanVolunteer> current,
                                                                       FillCurrentProjection projection,
                                                                       boolean unitMode) {
        List<PlanVolunteer> retained = defaultList(current).stream()
                .filter(item -> unitMode
                        ? !projection.removeUnitIds.contains(item.getUnitId())
                        : !projection.removeVolunteerIds.contains(item.getVolunteerId()))
                .collect(Collectors.toList());
        if (!unitMode) {
            return retained.stream().map(CoverageEntity::new).collect(Collectors.toList());
        }
        Map<String, List<PlanVolunteer>> grouped = retained.stream().collect(Collectors.groupingBy(
                item -> firstNonEmpty(item.getUnitId(), item.getVolunteerId()),
                LinkedHashMap::new,
                Collectors.toList()));
        return grouped.entrySet().stream()
                .map(entry -> new CoverageEntity(entry.getKey(), entry.getValue()))
                .collect(Collectors.toList());
    }

    private static void populateFillDryRun(FixProposalDTO proposal,
                                           PlanningStateDTO state,
                                           int beforeTargetDomainCount,
                                           int afterTargetDomainCount,
                                           int addUnitCount,
                                           int addVolunteerCount,
                                           int removeUnitCount,
                                           int removeVolunteerCount,
                                           String message) {
        boolean majorGroupMode = isMajorGroupMode(state);
        int beforeUnitCount = currentPlanUnitCount(state);
        int beforeVolunteerCount = currentPlanVolunteerCount(state);
        proposal.getDryRunResult().setStatus(proposal.getStatus());
        proposal.getDryRunResult().setMessage(message);
        proposal.getDryRunResult().setBeforeUnitTotal(beforeUnitCount);
        proposal.getDryRunResult().setBeforeVolunteerTotal(beforeVolunteerCount);
        proposal.getDryRunResult().setAfterUnitTotal(majorGroupMode
                ? afterTargetDomainCount : beforeUnitCount - removeUnitCount + addUnitCount);
        proposal.getDryRunResult().setAfterVolunteerTotal(majorGroupMode
                ? beforeVolunteerCount - removeVolunteerCount + addVolunteerCount : afterTargetDomainCount);
        proposal.getDryRunResult().setAffectedUnitCount(addUnitCount + removeUnitCount);
        proposal.getDryRunResult().setAffectedVolunteerCount(addVolunteerCount + removeVolunteerCount);
        proposal.getDryRunResult().setAddUnitCount(addUnitCount);
        proposal.getDryRunResult().setAddVolunteerCount(addVolunteerCount);
        proposal.getDryRunResult().setRemoveUnitCount(removeUnitCount);
        proposal.getDryRunResult().setRemoveVolunteerCount(removeVolunteerCount);
    }

    private static void populateTierQuotaDryRun(FixProposalDTO proposal,
                                                List<PlanVolunteer> current,
                                                boolean majorGroupMode,
                                                PlanSolverResultDTO solverResult) {
        TierCountsDTO resolved = solverResult == null ? null : solverResult.getResolvedTierCounts();
        if (proposal == null || resolved == null) {
            return;
        }
        List<CoverageEntity> currentEntities = buildRetainedCoverageEntities(
                current, new FillCurrentProjection(), majorGroupMode);
        Map<String, Integer> before = new LinkedHashMap<String, Integer>();
        before.put("冲", (int) currentEntities.stream()
                .filter(entity -> entity.matchesTier("sprint")).count());
        before.put("稳", (int) currentEntities.stream()
                .filter(entity -> entity.matchesTier("stable")).count());
        before.put("保", (int) currentEntities.stream()
                .filter(entity -> entity.matchesTier("protect")).count());
        Map<String, Integer> after = new LinkedHashMap<String, Integer>();
        after.put("冲", resolved.getSprintCount());
        after.put("稳", resolved.getStableCount());
        after.put("保", resolved.getProtectCount());
        if (majorGroupMode) {
            proposal.getDryRunResult().setBeforeUnitTierCounts(before);
            proposal.getDryRunResult().setAfterUnitTierCounts(after);
        } else {
            proposal.getDryRunResult().setBeforeVolunteerTierCounts(before);
            proposal.getDryRunResult().setAfterVolunteerTierCounts(after);
        }
    }

    private static FixProposalDTO buildBlockedProposal(PlanningStateDTO state,
                                                       UserGoalFixProposalReq req,
                                                       String goalType,
                                                       String reasonCode) {
        String message = buildMessage(goalType, reasonCode);

        FixProposalDTO proposal = new FixProposalDTO();
        proposal.setProposalId(buildProposalId(state, req, reasonCode));
        proposal.setProposalSource(RepairProposalTaxonomy.ProposalSource.USER_GOAL);
        proposal.setSourceVersion(state == null ? null : state.getVersion());
        proposal.setSourceVersionGuard(state == null ? null : state.getVersion());
        proposal.setStatus(RepairProposalTaxonomy.Status.BLOCKED);
        proposal.setStrategy(RepairProposalTaxonomy.Strategy.CANNOT_SATISFY);
        proposal.setTitle(buildTitle(goalType));
        proposal.setSummary(message);
        proposal.setBlockingReason(message);
        proposal.setRequiresConfirmation(false);
        proposal.getBlockingReasonCodes().add(reasonCode);
        proposal.getCandidateShortages().add(buildBoundaryShortage(reasonCode, message));
        proposal.getDryRunResult().setStatus(RepairProposalTaxonomy.Status.BLOCKED);
        proposal.getDryRunResult().setMessage(message);
        if (REASON_ENGINE_NOT_READY.equals(reasonCode)) {
            proposal.getDryRunResult().getWarnings().add("当前只建立了复合目标提案协议，还没有生成可执行的方案调整动作。");
        }
        return proposal;
    }

    private static String resolveGuardReasonCode(PlanningStateDTO state, UserGoalFixProposalReq req, String goalType) {
        Integer guard = req == null ? null : req.getSourceVersionGuard();
        if (guard != null && state != null && state.getVersion() != null && !guard.equals(state.getVersion())) {
            return REASON_SOURCE_VERSION_MISMATCH;
        }
        if (Strings.isNullOrEmpty(goalType)) {
            return REASON_GOAL_UNCLEAR;
        }
        return null;
    }

    private static FixProposalDTO buildScopeProposal(PlanningStateDTO state,
                                                     UserGoalFixProposalReq req,
                                                     String goalType) {
        List<ScopeMatcher> scopes = buildScopeMatchers(scopesForGoal(req, goalType));
        if (scopes.isEmpty()) {
            return buildBlockedProposal(state, req, goalType, REASON_GOAL_UNCLEAR);
        }
        ScopeMatcher ambiguousScope = scopes.stream()
                .filter(ScopeMatcher::needsClarification)
                .findFirst()
                .orElse(null);
        if (ambiguousScope != null) {
            return buildScopeBlockedProposal(state, req, goalType, REASON_ENTITY_NEEDS_CLARIFICATION,
                    "“" + ambiguousScope.getValue() + "”还没有对应到明确范围，需要先确认后再生成调整预览。");
        }

        List<CandidateItemDTO> candidates = candidates(state);
        List<PlanVolunteer> current = currentPlanVolunteers(state, candidates);
        Set<String> selectedVolunteerIds = current.stream()
                .map(PlanVolunteer::getVolunteerId)
                .filter(value -> !Strings.isNullOrEmpty(value))
                .collect(Collectors.toCollection(LinkedHashSet::new));
        Set<String> selectedUnitIds = current.stream()
                .map(PlanVolunteer::getUnitId)
                .filter(value -> !Strings.isNullOrEmpty(value))
                .collect(Collectors.toCollection(LinkedHashSet::new));
        String scopeLabel = scopeLabel(scopes);
        List<PlanVolunteer> currentMatches = current.stream()
                .filter(item -> matchesAny(item, scopes))
                .collect(Collectors.toList());
        List<CandidateItemDTO> candidateMatches = candidates.stream()
                .filter(candidate -> candidate != null && !Strings.isNullOrEmpty(candidate.getVolunteerId()))
                .filter(candidate -> !selectedVolunteerIds.contains(candidate.getVolunteerId()))
                .filter(candidate -> matchesAny(candidate, scopes))
                .filter(RepairCandidateSelector::isCompensationSafeCandidate)
                .filter(candidate -> RepairCandidateEligibility.isEligibleForConfirmedHardConstraints(candidate, state))
                .sorted(buildCandidatePreviewComparator())
                .collect(Collectors.toList());
        List<CandidateItemDTO> candidateNonMatches = candidates.stream()
                .filter(candidate -> candidate != null && !Strings.isNullOrEmpty(candidate.getVolunteerId()))
                .filter(candidate -> !selectedVolunteerIds.contains(candidate.getVolunteerId()))
                .filter(candidate -> !matchesAny(candidate, scopes))
                .filter(RepairCandidateSelector::isCompensationSafeCandidate)
                .filter(candidate -> RepairCandidateEligibility.isEligibleForConfirmedHardConstraints(candidate, state))
                .sorted(buildCandidatePreviewComparator())
                .collect(Collectors.toList());

        if (RepairProposalTaxonomy.Strategy.ONLY_KEEP_SCOPE.equals(goalType)) {
            return buildOnlyKeepProposal(state, req, scopeLabel, scopes, current, currentMatches, candidateMatches, selectedUnitIds);
        }
        if (RepairProposalTaxonomy.Strategy.MUST_INCLUDE_SCOPE.equals(goalType)) {
            return buildMustIncludeProposal(state, req, scopeLabel, current, currentMatches, candidateMatches, selectedUnitIds);
        }
        return buildExcludeProposal(state, req, scopeLabel, current, currentMatches, candidateNonMatches, selectedUnitIds);
    }

    private static FixProposalDTO buildOnlyKeepProposal(PlanningStateDTO state,
                                                        UserGoalFixProposalReq req,
                                                        String scopeLabel,
                                                        List<ScopeMatcher> scopes,
                                                        List<PlanVolunteer> current,
                                                        List<PlanVolunteer> currentMatches,
                                                        List<CandidateItemDTO> candidateMatches,
                                                        Set<String> selectedUnitIds) {
        if (currentMatches.isEmpty() && candidateMatches.isEmpty()) {
            return buildScopeBlockedProposal(state, req, RepairProposalTaxonomy.Strategy.ONLY_KEEP_SCOPE,
                    REASON_TARGET_NOT_FOUND, "当前方案和候选池里暂时都没有找到“" + scopeLabel + "”相关选择，不能直接生成只保留这个方向的调整预览。");
        }
        List<PlanVolunteer> removable = current.stream()
                .filter(item -> !matchesAny(item, scopes))
                .filter(item -> !item.isLocked())
                .collect(Collectors.toList());
        FixProposalDTO proposal = buildUserGoalPreviewBase(state, req, RepairProposalTaxonomy.Strategy.ONLY_KEEP_SCOPE,
                "只保留“" + scopeLabel + "”的调整预览");
        if (removable.isEmpty()) {
            proposal.setStatus(RepairProposalTaxonomy.Status.INFO);
            proposal.setSummary("当前方案已经都在“" + scopeLabel + "”范围内，本轮不需要为了这个目标调整方案。");
            proposal.setImpact("如果还想继续提高这个方向的质量，可以再要求我按院校层次、录取率或地域偏好做进一步优化。");
            proposal.setRequiresConfirmation(false);
            fillDryRun(proposal, current.size(), 0, 0, "当前方案已经符合这个保留方向。");
            return proposal;
        }
        boolean majorGroupMode = isMajorGroupMode(state);
        List<ReplacementPreviewPair> pairs = buildReplacementPreviewPairs(
                removable, candidateMatches, selectedUnitIds, majorGroupMode,
                Math.min(removable.size(), candidateMatches.size()),
                RepairProposalTaxonomy.Strategy.ONLY_KEEP_SCOPE);
        List<PlanVolunteer> remainingRemovable = remainingSources(removable, pairs);
        proposal.setSummary("当前方案中有 " + currentMatches.size() + " 条符合“" + scopeLabel + "”；如果只保留这个方向，另有 "
                + removable.size() + " 条需要处理。本次能替换 " + pairs.size() + " 条。");
        proposal.setImpact(remainingRemovable.isEmpty()
                ? "确认前不会改动当前方案；确认后会按这次预览处理，并同步刷新方案。"
                : "还有 " + remainingRemovable.size() + " 条暂时没有合适补位；本次会处理能替换或移出的部分，剩余部分需要放宽条件或后续再补。");
        if (!pairs.isEmpty()) {
            proposal.getActions().add(replaceAction("用保留范围内的候选替换其他志愿", pairs, majorGroupMode));
        }
        if (!remainingRemovable.isEmpty()) {
            proposal.getActions().add(removeAction("不在保留范围内且暂未找到补位的志愿", remainingRemovable));
        }
        markReadyIfActionable(proposal);
        fillDryRun(proposal, current.size(), removable.size(), pairs.size(), "已生成调整预览，等待确认后再执行。");
        return proposal;
    }

    private static FixProposalDTO buildTuitionBudgetProposal(PlanningStateDTO state,
                                                             UserGoalFixProposalReq req) {
        Integer maxTuition = maxTuitionFromRequest(req);
        if (maxTuition == null || maxTuition <= 0) {
            return buildScopeBlockedProposal(state, req, RepairProposalTaxonomy.Strategy.TUITION_BUDGET_SCOPE,
                    REASON_GOAL_UNCLEAR, "这次学费上限还不够明确，需要先确认每年最多能接受多少学费。");
        }

        List<CandidateItemDTO> candidates = candidates(state);
        List<PlanVolunteer> current = currentPlanVolunteers(state, candidates);
        Set<String> selectedVolunteerIds = current.stream()
                .map(PlanVolunteer::getVolunteerId)
                .filter(value -> !Strings.isNullOrEmpty(value))
                .collect(Collectors.toCollection(LinkedHashSet::new));
        Set<String> selectedUnitIds = current.stream()
                .map(PlanVolunteer::getUnitId)
                .filter(value -> !Strings.isNullOrEmpty(value))
                .collect(Collectors.toCollection(LinkedHashSet::new));

        List<PlanVolunteer> overBudget = current.stream()
                .filter(item -> {
                    Integer tuition = tuitionOf(item);
                    return tuition != null && tuition > maxTuition;
                })
                .filter(item -> !item.isLocked())
                .collect(Collectors.toList());
        FixProposalDTO proposal = buildUserGoalPreviewBase(state, req, RepairProposalTaxonomy.Strategy.TUITION_BUDGET_SCOPE,
                "控制学费上限的调整预览");
        if (overBudget.isEmpty()) {
            proposal.setStatus(RepairProposalTaxonomy.Status.INFO);
            proposal.setSummary("当前方案里没有发现学费超过 " + maxTuition + " 元/年的志愿，本轮不需要为了这个预算调整方案。");
            proposal.setImpact("这条预算可以作为后续报考参考，后续看候选和方案时会继续留意学费。");
            proposal.setRequiresConfirmation(false);
            fillDryRun(proposal, current.size(), 0, 0, "当前方案没有命中超过预算的志愿。");
            return proposal;
        }

        List<CandidateItemDTO> affordableCandidates = candidates.stream()
                .filter(candidate -> candidate != null && !Strings.isNullOrEmpty(candidate.getVolunteerId()))
                .filter(candidate -> !selectedVolunteerIds.contains(candidate.getVolunteerId()))
                .filter(candidate -> {
                    Integer tuition = tuitionOf(candidate);
                    return tuition == null || tuition <= maxTuition;
                })
                .filter(RepairCandidateSelector::isCompensationSafeCandidate)
                .filter(candidate -> RepairCandidateEligibility.isEligibleForConfirmedHardConstraints(candidate, state))
                .sorted(buildCandidatePreviewComparator())
                .collect(Collectors.toList());

        boolean majorGroupMode = isMajorGroupMode(state);
        List<ReplacementPreviewPair> pairs = buildReplacementPreviewPairs(
                overBudget, affordableCandidates, selectedUnitIds, majorGroupMode,
                Math.min(overBudget.size(), affordableCandidates.size()),
                RepairProposalTaxonomy.Strategy.TUITION_BUDGET_SCOPE);
        List<PlanVolunteer> remaining = remainingSources(overBudget, pairs);
        proposal.setSummary("当前方案里有 " + overBudget.size() + " 条学费超过 " + maxTuition + " 元/年；本次能替换 "
                + pairs.size() + " 条。");
        proposal.setImpact(remaining.isEmpty()
                ? "确认前不会改动当前方案；确认后会按这次预览处理，并同步刷新方案。"
                : "还有 " + remaining.size() + " 条暂时没有合适补位；本次会处理能替换或移出的部分，剩余部分需要放宽预算或后续再补。");
        if (!pairs.isEmpty()) {
            proposal.getActions().add(replaceAction("用不超过预算的候选替换超预算志愿", pairs, majorGroupMode));
        }
        if (!remaining.isEmpty()) {
            proposal.getActions().add(removeAction("学费超过预算且暂未找到补位的志愿", remaining));
        }
        markReadyIfActionable(proposal);
        fillDryRun(proposal, current.size(), overBudget.size(), pairs.size(), "已生成调整预览，等待确认后再执行。");
        return proposal;
    }

    private static FixProposalDTO buildMustIncludeProposal(PlanningStateDTO state,
                                                           UserGoalFixProposalReq req,
                                                           String scopeLabel,
                                                           List<PlanVolunteer> current,
                                                           List<PlanVolunteer> currentMatches,
                                                           List<CandidateItemDTO> candidateMatches,
                                                           Set<String> selectedUnitIds) {
        FixProposalDTO proposal = buildUserGoalPreviewBase(state, req, RepairProposalTaxonomy.Strategy.MUST_INCLUDE_SCOPE,
                "至少保留“" + scopeLabel + "”的调整预览");
        if (!currentMatches.isEmpty()) {
            proposal.setStatus(RepairProposalTaxonomy.Status.INFO);
            proposal.setSummary("当前方案里已经有 " + currentMatches.size() + " 条“" + scopeLabel + "”相关选择，本轮不需要为了这个目标调整方案。");
            proposal.setImpact("如果还想提高这个方向的优先级，可以继续要求我生成更偏这个方向的调整预览。");
            proposal.setRequiresConfirmation(false);
            fillDryRun(proposal, current.size(), 0, 0, "当前方案已覆盖这个方向。");
            return proposal;
        }
        if (candidateMatches.isEmpty()) {
            return buildScopeBlockedProposal(state, req, RepairProposalTaxonomy.Strategy.MUST_INCLUDE_SCOPE,
                    REASON_TARGET_NOT_FOUND, "当前方案里还没有“" + scopeLabel + "”，候选池里也暂时没有找到合适补入选择。");
        }
        boolean majorGroupMode = isMajorGroupMode(state);
        if (isCurrentPlanAtOrAboveTargetCount(state)) {
            List<PlanVolunteer> removable = current.stream()
                    .filter(item -> !item.isLocked())
                    .sorted(buildReplacementSourceComparator())
                    .collect(Collectors.toList());
            List<ReplacementPreviewPair> pairs = buildReplacementPreviewPairs(
                    removable, candidateMatches, selectedUnitIds, majorGroupMode, 1,
                    RepairProposalTaxonomy.Strategy.MUST_INCLUDE_SCOPE);
            if (!pairs.isEmpty()) {
                proposal.setSummary("当前方案里还没有“" + scopeLabel + "”；方案数量已满，已先找到 1 组低优先级项替换预览。");
                proposal.setImpact("确认前不会改动当前方案；确认后会先替换一条低优先级选择，再同步刷新方案。");
                proposal.getActions().add(replaceAction("补入这个方向并替换低优先级志愿", pairs, majorGroupMode));
                markReadyIfActionable(proposal);
                fillDryRun(proposal, current.size(), pairs.size(), pairs.size(), "已生成调整预览，等待确认后再执行。");
                return proposal;
            }
        }
        proposal.setSummary("当前方案里还没有“" + scopeLabel + "”；候选池里找到可参考选择，后续可以生成补入预览。");
        proposal.setImpact("确认前不会改动当前方案；确认后会把这个方向补入方案，并同步刷新方案。");
        proposal.getActions().add(addAction("候选池中可补入的选择", Lists.newArrayList(candidateMatches.get(0))));
        markReadyIfActionable(proposal);
        fillDryRun(proposal, current.size(), 0, 1, "已生成补入预览，等待确认后再执行。");
        return proposal;
    }

    private static FixProposalDTO buildExcludeProposal(PlanningStateDTO state,
                                                       UserGoalFixProposalReq req,
                                                       String scopeLabel,
                                                       List<PlanVolunteer> current,
                                                       List<PlanVolunteer> currentMatches,
                                                       List<CandidateItemDTO> candidateNonMatches,
                                                       Set<String> selectedUnitIds) {
        FixProposalDTO proposal = buildUserGoalPreviewBase(state, req, RepairProposalTaxonomy.Strategy.EXCLUDE_SCOPE,
                "避开“" + scopeLabel + "”的调整预览");
        if (currentMatches.isEmpty()) {
            proposal.setStatus(RepairProposalTaxonomy.Status.INFO);
            proposal.setSummary("当前方案里没有发现“" + scopeLabel + "”相关选择，本轮不需要为了这个目标移出志愿。");
            proposal.setImpact("这条要求仍可作为后续报考参考，后续看候选和方案时会继续避开这个方向。");
            proposal.setRequiresConfirmation(false);
            fillDryRun(proposal, current.size(), 0, 0, "当前方案没有命中需要避开的范围。");
            return proposal;
        }
        List<PlanVolunteer> removable = currentMatches.stream()
                .filter(item -> !item.isLocked())
                .collect(Collectors.toList());
        if (removable.isEmpty()) {
            return buildScopeBlockedProposal(state, req, RepairProposalTaxonomy.Strategy.EXCLUDE_SCOPE,
                    "user_goal_current_hits_locked", "当前方案里有“" + scopeLabel + "”相关选择，但这些条目暂时不能自动移出，需要人工确认后处理。");
        }
        boolean majorGroupMode = isMajorGroupMode(state);
        List<ReplacementPreviewPair> pairs = buildReplacementPreviewPairs(
                removable, candidateNonMatches, selectedUnitIds, majorGroupMode,
                Math.min(removable.size(), candidateNonMatches.size()),
                RepairProposalTaxonomy.Strategy.EXCLUDE_SCOPE);
        List<PlanVolunteer> remainingRemovable = remainingSources(removable, pairs);
        proposal.setSummary("当前方案里有 " + currentMatches.size() + " 条命中“" + scopeLabel + "”；本次能替换 "
                + pairs.size() + " 条。");
        proposal.setImpact(remainingRemovable.isEmpty()
                ? "确认前不会改动当前方案；确认后会按这次预览处理，并同步刷新方案。"
                : "还有 " + remainingRemovable.size() + " 条暂时没有合适补位；本次会处理能替换或移出的部分，剩余部分需要放宽条件或后续再补。");
        if (!pairs.isEmpty()) {
            proposal.getActions().add(replaceAction("用其他候选替换需要避开的志愿", pairs, majorGroupMode));
        }
        if (!remainingRemovable.isEmpty()) {
            proposal.getActions().add(removeAction("命中避开范围且暂未找到补位的志愿", remainingRemovable));
        }
        markReadyIfActionable(proposal);
        fillDryRun(proposal, current.size(), removable.size(), pairs.size(), "已生成调整预览，等待确认后再执行。");
        return proposal;
    }

    private static void markReadyIfActionable(FixProposalDTO proposal) {
        if (proposal == null || defaultList(proposal.getActions()).isEmpty()) {
            return;
        }
        proposal.setStatus(RepairProposalTaxonomy.Status.READY);
        proposal.setRequiresConfirmation(true);
    }

    private static FixProposalDTO buildUserGoalPreviewBase(PlanningStateDTO state,
                                                           UserGoalFixProposalReq req,
                                                           String strategy,
                                                           String title) {
        FixProposalDTO proposal = new FixProposalDTO();
        proposal.setProposalId(buildProposalId(state, req, strategy));
        proposal.setProposalSource(RepairProposalTaxonomy.ProposalSource.USER_GOAL);
        proposal.setSourceVersion(state == null ? null : state.getVersion());
        proposal.setSourceVersionGuard(state == null ? null : state.getVersion());
        proposal.setStatus(RepairProposalTaxonomy.Status.PREVIEW_ONLY);
        proposal.setStrategy(strategy);
        proposal.setTitle(title);
        proposal.setRequiresConfirmation(false);
        return proposal;
    }

    private static FixProposalDTO buildScopeBlockedProposal(PlanningStateDTO state,
                                                            UserGoalFixProposalReq req,
                                                            String strategy,
                                                            String reasonCode,
                                                            String message) {
        FixProposalDTO proposal = buildUserGoalPreviewBase(state, req, strategy, buildTitle(strategy));
        proposal.setStatus(RepairProposalTaxonomy.Status.BLOCKED);
        proposal.setSummary(message);
        proposal.setBlockingReason(message);
        proposal.getBlockingReasonCodes().add(reasonCode);
        proposal.getCandidateShortages().add(buildBoundaryShortage(strategy, reasonCode, message));
        proposal.getDryRunResult().setStatus(RepairProposalTaxonomy.Status.BLOCKED);
        proposal.getDryRunResult().setMessage(message);
        proposal.setRequiresConfirmation(false);
        return proposal;
    }

    private static FixProposalActionDTO removeAction(String summary, List<PlanVolunteer> volunteers) {
        FixProposalActionDTO action = new FixProposalActionDTO();
        action.setActionType(RepairProposalTaxonomy.ActionType.REMOVE_VOLUNTEERS);
        action.setLevel("volunteer");
        action.setSummary(summary);
        action.setDetail("预计移出 " + volunteers.size() + " 条。");
        action.setVolunteerIds(volunteers.stream()
                .map(PlanVolunteer::getVolunteerId)
                .filter(value -> !Strings.isNullOrEmpty(value))
                .collect(Collectors.toList()));
        action.setUnitIds(volunteers.stream()
                .map(PlanVolunteer::getUnitId)
                .filter(value -> !Strings.isNullOrEmpty(value))
                .distinct()
                .collect(Collectors.toList()));
        action.setRemoveVolunteerIds(action.getVolunteerIds());
        action.setRemoveUnitIds(action.getUnitIds());
        action.setCandidateVolunteerIds(Lists.newArrayList());
        action.setCandidateUnitIds(Lists.newArrayList());
        return action;
    }

    private static FixProposalActionDTO addAction(String summary, List<CandidateItemDTO> candidates) {
        FixProposalActionDTO action = new FixProposalActionDTO();
        action.setActionType(RepairProposalTaxonomy.ActionType.ADD_VOLUNTEERS);
        action.setLevel("volunteer");
        action.setSummary(summary);
        action.setDetail("找到 " + candidates.size() + " 条可参考选择。");
        action.setVolunteerIds(candidates.stream()
                .map(CandidateItemDTO::getVolunteerId)
                .filter(value -> !Strings.isNullOrEmpty(value))
                .collect(Collectors.toList()));
        action.setUnitIds(candidates.stream()
                .map(RepairCandidateSelector::resolveInitialRecommendationUnitId)
                .filter(value -> !Strings.isNullOrEmpty(value))
                .distinct()
                .collect(Collectors.toList()));
        action.setCandidateVolunteerIds(action.getVolunteerIds());
        action.setCandidateUnitIds(action.getUnitIds());
        action.setRemoveVolunteerIds(Lists.newArrayList());
        action.setRemoveUnitIds(Lists.newArrayList());
        return action;
    }

    private static FixProposalActionDTO replaceAction(String summary,
                                                      List<ReplacementPreviewPair> pairs,
                                                      boolean majorGroupMode) {
        FixProposalActionDTO action = new FixProposalActionDTO();
        action.setActionType(RepairProposalTaxonomy.ActionType.REPLACE_VOLUNTEERS);
        action.setLevel("volunteer");
        action.setSummary(summary);
        action.setDetail(buildReplacementActionDetail(pairs));
        action.setRemoveVolunteerIds(pairs.stream()
                .map(pair -> pair.source.getVolunteerId())
                .filter(value -> !Strings.isNullOrEmpty(value))
                .collect(Collectors.toList()));
        action.setCandidateVolunteerIds(pairs.stream()
                .map(pair -> pair.candidate.getVolunteerId())
                .filter(value -> !Strings.isNullOrEmpty(value))
                .collect(Collectors.toList()));
        if (majorGroupMode) {
            action.setRemoveUnitIds(pairs.stream()
                    .map(pair -> pair.source.getUnitId())
                    .filter(value -> !Strings.isNullOrEmpty(value))
                    .distinct()
                    .collect(Collectors.toList()));
            action.setCandidateUnitIds(pairs.stream()
                    .map(pair -> RepairCandidateSelector.resolveInitialRecommendationUnitId(pair.candidate))
                    .filter(value -> !Strings.isNullOrEmpty(value))
                    .distinct()
                    .collect(Collectors.toList()));
        }
        action.setVolunteerIds(action.getRemoveVolunteerIds());
        action.setUnitIds(action.getRemoveUnitIds());
        for (ReplacementPreviewPair pair : pairs) {
            action.getReplacementPairs().add(buildReplacementPair(pair, majorGroupMode));
        }
        return action;
    }

    private static String buildReplacementActionDetail(List<ReplacementPreviewPair> pairs) {
        List<String> previews = defaultList(pairs).stream()
                .limit(3)
                .map(UserGoalProposalBuilder::formatReplacementPreviewPair)
                .filter(value -> !Strings.isNullOrEmpty(value))
                .collect(Collectors.toList());
        String base = "预计替换 " + defaultList(pairs).size() + " 组。";
        if (previews.isEmpty()) {
            return base;
        }
        int remainingCount = defaultList(pairs).size() - previews.size();
        String suffix = remainingCount > 0 ? "；另有 " + remainingCount + " 组未展开" : "";
        return base + " 具体预览：" + String.join("；", previews) + suffix + "。";
    }

    private static String formatReplacementPreviewPair(ReplacementPreviewPair pair) {
        if (pair == null) {
            return "";
        }
        String fromText = formatPlanVolunteerBrief(pair.source);
        String toText = formatCandidateBrief(pair.candidate);
        if (Strings.isNullOrEmpty(fromText) || Strings.isNullOrEmpty(toText)) {
            return "";
        }
        String changeText = formatChangeSummary(pair.source == null ? null : pair.source.getCandidate(), pair.candidate);
        return fromText + " -> " + toText + (Strings.isNullOrEmpty(changeText) ? "" : "（" + changeText + "）");
    }

    private static String formatPlanVolunteerBrief(PlanVolunteer volunteer) {
        if (volunteer == null) {
            return "";
        }
        if (volunteer.getCandidate() != null) {
            return formatCandidateBrief(volunteer.getCandidate());
        }
        String label = buildSchoolMajorLabel(volunteer.getSchoolName(), volunteer.getMajorName());
        return Strings.isNullOrEmpty(label) ? firstNonEmpty(volunteer.getUnitId(), volunteer.getVolunteerId()) : label;
    }

    private static String formatCandidateBrief(CandidateItemDTO candidate) {
        if (candidate == null) {
            return "";
        }
        String label = buildSchoolMajorLabel(candidate.getSchoolName(), candidate.getMajorName());
        if (Strings.isNullOrEmpty(label)) {
            label = firstNonEmpty(
                    RepairCandidateSelector.resolveInitialRecommendationUnitId(candidate),
                    candidate.getVolunteerId());
        }
        List<String> tags = Lists.newArrayList(
                candidate.getTier(),
                candidate.getAdmissionRatio() == null ? "" : "录取率" + formatNumber(candidate.getAdmissionRatio()) + "%",
                candidate.getIntentScore() == null ? "" : "匹配" + formatNumber(candidate.getIntentScore()),
                candidate.getFinalScore() == null ? "" : "推荐" + formatNumber(candidate.getFinalScore()),
                candidate.getSchoolRank() == null ? "" : "院校排名" + candidate.getSchoolRank());
        String tagText = tags.stream()
                .filter(value -> !Strings.isNullOrEmpty(value))
                .collect(Collectors.joining("/"));
        return Strings.isNullOrEmpty(tagText) ? label : label + "（" + tagText + "）";
    }

    private static String buildSchoolMajorLabel(String schoolName, String majorName) {
        String school = Strings.nullToEmpty(schoolName).trim();
        String major = Strings.nullToEmpty(majorName).trim();
        if (Strings.isNullOrEmpty(school)) {
            return major;
        }
        if (Strings.isNullOrEmpty(major)) {
            return school;
        }
        return school + "-" + major;
    }

    private static String formatChangeSummary(CandidateItemDTO from, CandidateItemDTO to) {
        if (from == null || to == null) {
            return "";
        }
        List<String> changes = Lists.newArrayList(
                formatDelta("录取率", from.getAdmissionRatio(), to.getAdmissionRatio()),
                formatDelta("匹配", from.getIntentScore(), to.getIntentScore()),
                formatDelta("推荐", from.getFinalScore(), to.getFinalScore()),
                formatRankDelta(from.getSchoolRank(), to.getSchoolRank()));
        return changes.stream()
                .filter(value -> !Strings.isNullOrEmpty(value))
                .collect(Collectors.joining("，"));
    }

    private static String formatDelta(String label, Double from, Double to) {
        if (from == null || to == null) {
            return "";
        }
        double delta = to - from;
        if (Math.abs(delta) < 0.05D) {
            return "";
        }
        return label + (delta > 0 ? "+" : "") + formatNumber(delta);
    }

    private static String formatRankDelta(Integer from, Integer to) {
        if (from == null || from <= 0 || to == null || to <= 0 || from.equals(to)) {
            return "";
        }
        int delta = to - from;
        return delta > 0 ? "院校排名下降" + delta : "院校排名提升" + Math.abs(delta);
    }

    private static String formatNumber(Double value) {
        if (value == null) {
            return "";
        }
        return String.format(Locale.ROOT, "%.1f", value);
    }

    private static ReplacementPairDTO buildReplacementPair(ReplacementPreviewPair previewPair,
                                                           boolean majorGroupMode) {
        ReplacementPairDTO pair = new ReplacementPairDTO();
        pair.setFromVolunteerId(previewPair.source.getVolunteerId());
        pair.setToVolunteerId(previewPair.candidate.getVolunteerId());
        if (majorGroupMode) {
            pair.setFromUnitId(previewPair.source.getUnitId());
            pair.setToUnitId(RepairCandidateSelector.resolveInitialRecommendationUnitId(previewPair.candidate));
        }
        pair.getReasonCodes().add(previewPair.reasonCode);
        return pair;
    }

    private static void fillDryRun(FixProposalDTO proposal,
                                   int beforeCount,
                                   int removeCount,
                                   int addPreviewCount,
                                   String message) {
        proposal.getDryRunResult().setStatus(proposal.getStatus());
        proposal.getDryRunResult().setMessage(message);
        proposal.getDryRunResult().setBeforeVolunteerTotal(beforeCount);
        proposal.getDryRunResult().setAfterVolunteerTotal(Math.max(0, beforeCount - removeCount + addPreviewCount));
        proposal.getDryRunResult().setBeforeUnitTotal(beforeCount);
        proposal.getDryRunResult().setAfterUnitTotal(Math.max(0, beforeCount - removeCount + addPreviewCount));
        proposal.getDryRunResult().setAffectedVolunteerCount(removeCount + addPreviewCount);
        proposal.getDryRunResult().setAffectedUnitCount(removeCount + addPreviewCount);
        proposal.getDryRunResult().setRemoveVolunteerCount(removeCount);
        proposal.getDryRunResult().setRemoveUnitCount(removeCount);
        proposal.getDryRunResult().setAddVolunteerCount(addPreviewCount);
        proposal.getDryRunResult().setAddUnitCount(addPreviewCount);
    }

    private static List<ReplacementPreviewPair> buildReplacementPreviewPairs(List<PlanVolunteer> sources,
                                                                             List<CandidateItemDTO> candidates,
                                                                             Set<String> selectedUnitIds,
                                                                             boolean majorGroupMode,
                                                                             int limit,
                                                                             String reasonCode) {
        List<ReplacementPreviewPair> pairs = Lists.newArrayList();
        if (limit <= 0) {
            return pairs;
        }
        List<PlanVolunteer> orderedSources = defaultList(sources).stream()
                .filter(source -> source != null && !source.isLocked())
                .filter(source -> !Strings.isNullOrEmpty(source.getVolunteerId()))
                .sorted(buildReplacementSourceComparator())
                .collect(Collectors.toList());
        List<CandidateItemDTO> remainingCandidates = distinctReplacementCandidates(candidates, majorGroupMode);
        Set<String> usedCandidateVolunteerIds = new LinkedHashSet<String>();
        Set<String> usedCandidateUnitIds = new LinkedHashSet<String>();
        Set<String> currentUnitIds = selectedUnitIds == null ? new LinkedHashSet<String>() : selectedUnitIds;
        for (PlanVolunteer source : orderedSources) {
            if (pairs.size() >= limit || remainingCandidates.isEmpty()) {
                break;
            }
            CandidateItemDTO best = remainingCandidates.stream()
                    .filter(candidate -> candidate != null && !Strings.isNullOrEmpty(candidate.getVolunteerId()))
                    .filter(candidate -> !source.getVolunteerId().equals(candidate.getVolunteerId()))
                    .filter(candidate -> !usedCandidateVolunteerIds.contains(candidate.getVolunteerId()))
                    .filter(candidate -> !majorGroupMode || isCandidateUnitAvailableForReplacement(
                            candidate, source.getUnitId(), currentUnitIds, usedCandidateUnitIds))
                    .min((left, right) -> compareUserGoalReplacementTradeoff(source.getCandidate(), left, right))
                    .orElse(null);
            if (best == null) {
                continue;
            }
            pairs.add(new ReplacementPreviewPair(source, best, reasonCode));
            usedCandidateVolunteerIds.add(best.getVolunteerId());
            String candidateUnitId = RepairCandidateSelector.resolveInitialRecommendationUnitId(best);
            if (!Strings.isNullOrEmpty(candidateUnitId)) {
                usedCandidateUnitIds.add(candidateUnitId);
            }
            remainingCandidates.remove(best);
        }
        return pairs;
    }

    private static List<CandidateItemDTO> distinctReplacementCandidates(List<CandidateItemDTO> candidates,
                                                                        boolean majorGroupMode) {
        Set<String> seenKeys = new LinkedHashSet<String>();
        List<CandidateItemDTO> result = Lists.newArrayList();
        for (CandidateItemDTO candidate : defaultList(candidates)) {
            if (candidate == null || Strings.isNullOrEmpty(candidate.getVolunteerId())) {
                continue;
            }
            String key = majorGroupMode
                    ? firstNonEmpty(RepairCandidateSelector.resolveInitialRecommendationUnitId(candidate), candidate.getVolunteerId())
                    : candidate.getVolunteerId();
            if (seenKeys.add(key)) {
                result.add(candidate);
            }
        }
        return result;
    }

    private static int compareUserGoalReplacementTradeoff(CandidateItemDTO source,
                                                          CandidateItemDTO left,
                                                          CandidateItemDTO right) {
        int compare = Integer.compare(
                RepairReplacementTradeoffSupport.majorSimilarityLevel(source, left),
                RepairReplacementTradeoffSupport.majorSimilarityLevel(source, right));
        if (compare != 0) {
            return compare;
        }
        compare = Integer.compare(
                RepairReplacementTradeoffSupport.schoolRankDowngradePenalty(source, left),
                RepairReplacementTradeoffSupport.schoolRankDowngradePenalty(source, right));
        if (compare != 0) {
            return compare;
        }
        compare = Double.compare(
                RepairReplacementTradeoffSupport.scoreLossPenalty(source == null ? null : source.getIntentScore(),
                        left == null ? null : left.getIntentScore()),
                RepairReplacementTradeoffSupport.scoreLossPenalty(source == null ? null : source.getIntentScore(),
                        right == null ? null : right.getIntentScore()));
        if (compare != 0) {
            return compare;
        }
        compare = Double.compare(
                RepairReplacementTradeoffSupport.scoreLossPenalty(source == null ? null : source.getFinalScore(),
                        left == null ? null : left.getFinalScore()),
                RepairReplacementTradeoffSupport.scoreLossPenalty(source == null ? null : source.getFinalScore(),
                        right == null ? null : right.getFinalScore()));
        if (compare != 0) {
            return compare;
        }
        compare = compareNullableDoubleDesc(left == null ? null : left.getIntentScore(), right == null ? null : right.getIntentScore());
        if (compare != 0) {
            return compare;
        }
        compare = compareNullableDoubleDesc(left == null ? null : left.getAdmissionRatio(), right == null ? null : right.getAdmissionRatio());
        if (compare != 0) {
            return compare;
        }
        compare = compareNullableDoubleDesc(left == null ? null : left.getFinalScore(), right == null ? null : right.getFinalScore());
        if (compare != 0) {
            return compare;
        }
        compare = compareNullableIntegerAsc(left == null ? null : left.getSchoolRank(), right == null ? null : right.getSchoolRank());
        if (compare != 0) {
            return compare;
        }
        return Strings.nullToEmpty(left == null ? null : left.getVolunteerId())
                .compareTo(Strings.nullToEmpty(right == null ? null : right.getVolunteerId()));
    }

    private static boolean isCandidateUnitAvailableForReplacement(CandidateItemDTO candidate,
                                                                  String sourceUnitId,
                                                                  Set<String> currentUnitIds,
                                                                  Set<String> usedCandidateUnitIds) {
        String candidateUnitId = RepairCandidateSelector.resolveInitialRecommendationUnitId(candidate);
        if (Strings.isNullOrEmpty(candidateUnitId)) {
            return false;
        }
        if (candidateUnitId.equals(sourceUnitId)) {
            return false;
        }
        return !defaultSet(currentUnitIds).contains(candidateUnitId)
                && !defaultSet(usedCandidateUnitIds).contains(candidateUnitId);
    }

    private static List<PlanVolunteer> remainingSources(List<PlanVolunteer> sources,
                                                        List<ReplacementPreviewPair> pairs) {
        Set<String> pairedVolunteerIds = defaultList(pairs).stream()
                .map(pair -> pair.source.getVolunteerId())
                .filter(value -> !Strings.isNullOrEmpty(value))
                .collect(Collectors.toCollection(LinkedHashSet::new));
        return defaultList(sources).stream()
                .filter(source -> source != null && !pairedVolunteerIds.contains(source.getVolunteerId()))
                .collect(Collectors.toList());
    }

    private static Comparator<PlanVolunteer> buildReplacementSourceComparator() {
        return Comparator
                .comparing((PlanVolunteer item) -> metricOf(item, CandidateItemDTO::getAdmissionRatio), Comparator.nullsLast(Double::compareTo))
                .thenComparing(item -> metricOf(item, CandidateItemDTO::getFinalScore), Comparator.nullsLast(Double::compareTo))
                .thenComparing(item -> metricOf(item, CandidateItemDTO::getIntentScore), Comparator.nullsLast(Double::compareTo))
                .thenComparing(item -> metricOf(item, candidate -> candidate.getSchoolRank() == null ? null : candidate.getSchoolRank().doubleValue()),
                        Comparator.nullsLast(Comparator.reverseOrder()))
                .thenComparing(PlanVolunteer::getVolunteerId, Comparator.nullsLast(String::compareTo));
    }

    private static Double metricOf(PlanVolunteer item,
                                   java.util.function.Function<CandidateItemDTO, Double> mapper) {
        if (item == null || item.getCandidate() == null || mapper == null) {
            return null;
        }
        return mapper.apply(item.getCandidate());
    }

    private static Integer tuitionOf(PlanVolunteer item) {
        if (item == null || item.getCandidate() == null) {
            return null;
        }
        return item.getCandidate().getTuitionPerYear();
    }

    private static Integer tuitionOf(CandidateItemDTO item) {
        return item == null ? null : item.getTuitionPerYear();
    }

    private static boolean isMajorGroupMode(PlanningStateDTO state) {
        CandidatePoolStateDTO candidatePoolState = state == null ? null : state.getCandidatePoolState();
        return candidatePoolState != null && "majorGroup".equalsIgnoreCase(candidatePoolState.getVolunteerModel());
    }

    private static boolean isCurrentPlanAtOrAboveTargetCount(PlanningStateDTO state) {
        Integer requiredCount = state == null || state.getCandidatePoolState() == null
                ? null : state.getCandidatePoolState().getRequiredCount();
        if (requiredCount == null || requiredCount <= 0) {
            return false;
        }
        int currentCount = isMajorGroupMode(state)
                ? currentPlanUnitCount(state)
                : currentPlanVolunteerCount(state);
        return currentCount >= requiredCount;
    }

    private static int currentPlanVolunteerCount(PlanningStateDTO state) {
        if (state == null) {
            return 0;
        }
        if (state.getOrderedPlanState() != null && !defaultList(state.getOrderedPlanState().getItems()).isEmpty()) {
            return defaultList(state.getOrderedPlanState().getItems()).size();
        }
        if (state.getWorkingPlanState() != null && !defaultList(state.getWorkingPlanState().getItems()).isEmpty()) {
            return defaultList(state.getWorkingPlanState().getItems()).size();
        }
        if (state.getOrderedPlanState() != null && !defaultList(state.getOrderedPlanState().getUnits()).isEmpty()) {
            return defaultList(state.getOrderedPlanState().getUnits()).stream()
                    .mapToInt(unit -> defaultList(unit == null ? null : unit.getMajorItems()).size())
                    .sum();
        }
        if (state.getWorkingPlanState() != null && !defaultList(state.getWorkingPlanState().getUnits()).isEmpty()) {
            return defaultList(state.getWorkingPlanState().getUnits()).stream()
                    .mapToInt(unit -> defaultList(unit == null ? null : unit.getMajorItems()).size())
                    .sum();
        }
        return 0;
    }

    private static int currentPlanUnitCount(PlanningStateDTO state) {
        if (state == null) {
            return 0;
        }
        if (state.getOrderedPlanState() != null && !defaultList(state.getOrderedPlanState().getUnits()).isEmpty()) {
            return defaultList(state.getOrderedPlanState().getUnits()).size();
        }
        if (state.getWorkingPlanState() != null && !defaultList(state.getWorkingPlanState().getUnits()).isEmpty()) {
            return defaultList(state.getWorkingPlanState().getUnits()).size();
        }
        if (state.getOrderedPlanState() != null && !defaultList(state.getOrderedPlanState().getItems()).isEmpty()) {
            return currentPlanVolunteerCount(state);
        }
        if (state.getWorkingPlanState() != null && !defaultList(state.getWorkingPlanState().getItems()).isEmpty()) {
            return currentPlanVolunteerCount(state);
        }
        return 0;
    }

    private static CandidateShortageDTO buildBoundaryShortage(String reasonCode, String message) {
        return buildBoundaryShortage(RepairProposalTaxonomy.Strategy.CANNOT_SATISFY, reasonCode, message);
    }

    private static CandidateShortageDTO buildBoundaryShortage(String strategy, String reasonCode, String message) {
        CandidateShortageDTO shortage = new CandidateShortageDTO();
        shortage.setStrategy(strategy);
        shortage.setScope("proposal_engine");
        shortage.setReasonCode(reasonCode);
        shortage.setMessage(message);
        return shortage;
    }

    private static String buildTitle(String goalType) {
        if (RepairProposalTaxonomy.Strategy.FILL_MISSING_COUNT.equals(
                RepairProposalTaxonomy.normalizeStrategy(goalType))) {
            return "补齐方案数量的调整预览";
        }
        if (RepairProposalTaxonomy.Strategy.PRIORITIZE_WITHIN_TIER.equals(
                RepairProposalTaxonomy.normalizeStrategy(goalType))) {
            return "同档优先靠前的方案调整预览";
        }
        if ("only_keep_scope".equals(goalType)) {
            return "只保留范围的方案调整暂不自动执行";
        }
        if ("must_include_scope".equals(goalType)) {
            return "至少保留范围的方案调整暂不自动执行";
        }
        if ("exclude_scope".equals(goalType)) {
            return "排除范围的方案调整暂不自动执行";
        }
        if ("mixed_adjustment".equals(goalType)) {
            return "复合方案调整暂不自动执行";
        }
        if ("tuition_budget_scope".equals(goalType)) {
            return "学费预算调整暂不自动执行";
        }
        return "方案调整目标暂不自动执行";
    }

    private static String buildMessage(String goalType, String reasonCode) {
        if (REASON_SOURCE_VERSION_MISMATCH.equals(reasonCode)) {
            return "当前方案已经变化，需要重新读取方案后再生成调整预览。";
        }
        if (REASON_GOAL_UNCLEAR.equals(reasonCode)) {
            return "这次调整目标还不够明确，需要先确认要保留、补入或排除的范围。";
        }
        if (REASON_TARGET_NOT_FOUND.equals(reasonCode)) {
            return "当前方案和候选池里暂时没有找到符合目标范围的选择，不能直接生成调整预览。";
        }
        if (REASON_ENTITY_NEEDS_CLARIFICATION.equals(reasonCode)) {
            return "这次提到的范围还不够明确，需要先确认具体专业、院校或地域后再生成调整预览。";
        }
        if (RepairProposalTaxonomy.Strategy.FILL_MISSING_COUNT.equals(
                RepairProposalTaxonomy.normalizeStrategy(goalType))) {
            return "已识别为补齐方案数量目标，但需要明确目标数量并验证候选是否足够；当前不会自动修改方案。";
        }
        if ("only_keep_scope".equals(goalType)) {
            return "已识别为“只保留某个范围”的复合目标，但还需要先计算当前方案中哪些保留、哪些移出、候选是否能补足，以及调整后的风险变化；当前不会自动修改方案。";
        }
        if ("must_include_scope".equals(goalType)) {
            return "已识别为“至少保留某个范围”的复合目标，但还需要先检查当前方案是否已有命中、候选是否能补入，以及是否需要替换低优先级项；当前不会自动修改方案。";
        }
        if ("exclude_scope".equals(goalType)) {
            return "已识别为“避开某个范围”的复合目标，但还需要先定位当前方案命中项、确认专业/院校/地域粒度，并判断删除或替换后的数量和风险；当前不会自动修改方案。";
        }
        if ("mixed_adjustment".equals(goalType)) {
            return "已识别为多目标方案调整，但需要先拆成可验证的保留、排除、补入、替换或重排动作；当前不会自动修改方案。";
        }
        if ("tuition_budget_scope".equals(goalType)) {
            return "已识别为学费预算调整，但需要先定位当前方案里超过预算的志愿，并判断是否有合适补位；当前不会自动修改方案。";
        }
        return "复合方案调整需要先生成可验证的调整预览；当前不会自动修改方案。";
    }

    private static String normalizeGoalType(String goalType) {
        return RepairProposalTaxonomy.normalizeStrategy(Strings.nullToEmpty(goalType).trim());
    }

    private static Integer maxTuitionFromRequest(UserGoalFixProposalReq req) {
        if (req == null) {
            return null;
        }
        Integer fromContext = intFromObject(req.getContext() == null ? null : req.getContext().get("maxTuitionPerYear"));
        if (fromContext != null) {
            return fromContext;
        }
        for (UserGoalFixProposalReq.ScopeDTO scope : defaultList(req.getTargetScopes())) {
            Integer value = intFromObject(scope == null || scope.getEvidence() == null ? null : scope.getEvidence().get("maxTuitionPerYear"));
            if (value != null) {
                return value;
            }
        }
        return null;
    }

    private static Integer intFromObject(Object value) {
        if (value == null) {
            return null;
        }
        if (value instanceof Number) {
            return ((Number) value).intValue();
        }
        String digits = Strings.nullToEmpty(String.valueOf(value)).replaceAll("[^0-9]", "");
        if (Strings.isNullOrEmpty(digits)) {
            return null;
        }
        try {
            return Integer.parseInt(digits);
        } catch (NumberFormatException ex) {
            return null;
        }
    }

    private static List<UserGoalFixProposalReq.ScopeDTO> scopesForGoal(UserGoalFixProposalReq req, String goalType) {
        if (req == null) {
            return Lists.newArrayList();
        }
        if (RepairProposalTaxonomy.Strategy.EXCLUDE_SCOPE.equals(goalType)) {
            return req.getNegativeScopes() == null || req.getNegativeScopes().isEmpty()
                    ? defaultList(req.getTargetScopes()) : defaultList(req.getNegativeScopes());
        }
        return defaultList(req.getTargetScopes());
    }

    private static List<ScopeMatcher> buildScopeMatchers(List<UserGoalFixProposalReq.ScopeDTO> scopes) {
        return defaultList(scopes).stream()
                .map(ScopeMatcher::from)
                .filter(scope -> !Strings.isNullOrEmpty(scope.getValue()))
                .collect(Collectors.toList());
    }

    private static String scopeLabel(List<ScopeMatcher> scopes) {
        String label = scopes.stream()
                .map(ScopeMatcher::getValue)
                .filter(value -> !Strings.isNullOrEmpty(value))
                .distinct()
                .collect(Collectors.joining("、"));
        return Strings.isNullOrEmpty(label) ? "目标范围" : label;
    }

    private static boolean matchesAny(PlanVolunteer item, List<ScopeMatcher> scopes) {
        return defaultList(scopes).stream().anyMatch(scope -> scope.matches(item));
    }

    private static boolean matchesAny(CandidateItemDTO candidate, List<ScopeMatcher> scopes) {
        return defaultList(scopes).stream().anyMatch(scope -> scope.matches(candidate));
    }

    private static List<CandidateItemDTO> candidates(PlanningStateDTO state) {
        CandidatePoolStateDTO candidatePoolState = state == null ? null : state.getCandidatePoolState();
        return defaultList(candidatePoolState == null ? null : candidatePoolState.getItems());
    }

    private static List<PlanVolunteer> currentPlanVolunteers(PlanningStateDTO state, List<CandidateItemDTO> candidates) {
        List<PlanVolunteer> result = Lists.newArrayList();
        if (state == null) {
            return result;
        }
        boolean majorGroupMode = isMajorGroupMode(state);
        if (state.getOrderedPlanState() != null) {
            if (majorGroupMode) {
                if (appendOrderedUnits(result, state.getOrderedPlanState().getUnits(), candidates)
                        || appendOrderedItems(result, state.getOrderedPlanState().getItems(),
                        state.getOrderedPlanState().getUnits(), candidates)) {
                    return result;
                }
            } else if (appendOrderedItems(result, state.getOrderedPlanState().getItems(),
                    state.getOrderedPlanState().getUnits(), candidates)
                    || appendOrderedUnits(result, state.getOrderedPlanState().getUnits(), candidates)) {
                return result;
            }
        }
        if (state.getWorkingPlanState() != null) {
            if (majorGroupMode) {
                if (appendWorkingUnits(result, state.getWorkingPlanState().getUnits(), candidates)
                        || appendWorkingItems(result, state.getWorkingPlanState().getItems(), candidates)) {
                    return result;
                }
            } else if (appendWorkingItems(result, state.getWorkingPlanState().getItems(), candidates)
                    || appendWorkingUnits(result, state.getWorkingPlanState().getUnits(), candidates)) {
                return result;
            }
        }
        return result;
    }

    private static boolean appendOrderedItems(List<PlanVolunteer> target,
                                              List<OrderedItemDTO> items,
                                              List<OrderedUnitDTO> units,
                                              List<CandidateItemDTO> candidates) {
        int before = target.size();
        for (OrderedItemDTO item : defaultList(items)) {
            if (item != null) {
                OrderedUnitDTO unit = orderedUnitForVolunteer(units, item.getVolunteerId());
                PlanningUnitMajorDTO major = unitMajor(unit, item.getVolunteerId());
                target.add(PlanVolunteer.from(item, unit, major,
                        findCurrentPlanCandidate(candidates, item.getVolunteerId(),
                                unit == null ? null : unit.getUnitId(),
                                firstNonEmpty(item.getSchoolName(), unit == null ? null : unit.getSchoolName()),
                                firstNonEmpty(item.getMajorName(), major == null ? null : major.getMajorName())),
                        candidates));
            }
        }
        return target.size() > before;
    }

    private static OrderedUnitDTO orderedUnitForVolunteer(List<OrderedUnitDTO> units, String volunteerId) {
        if (Strings.isNullOrEmpty(volunteerId)) {
            return null;
        }
        return defaultList(units).stream()
                .filter(Objects::nonNull)
                .filter(unit -> unitMajor(unit, volunteerId) != null)
                .findFirst()
                .orElse(null);
    }

    private static PlanningUnitMajorDTO unitMajor(OrderedUnitDTO unit, String volunteerId) {
        if (unit == null || Strings.isNullOrEmpty(volunteerId)) {
            return null;
        }
        return defaultList(unit.getMajorItems()).stream()
                .filter(Objects::nonNull)
                .filter(major -> volunteerId.equals(major.getVolunteerId()))
                .findFirst()
                .orElse(null);
    }

    private static boolean appendOrderedUnits(List<PlanVolunteer> target,
                                              List<OrderedUnitDTO> units,
                                              List<CandidateItemDTO> candidates) {
        int before = target.size();
        for (OrderedUnitDTO unit : defaultList(units)) {
            if (unit != null) {
                for (PlanningUnitMajorDTO major : defaultList(unit.getMajorItems())) {
                    if (major != null) {
                        target.add(PlanVolunteer.from(unit, major,
                                findCurrentPlanCandidate(candidates, major.getVolunteerId(), unit.getUnitId(),
                                        unit.getSchoolName(), major.getMajorName()), candidates));
                    }
                }
            }
        }
        return target.size() > before;
    }

    private static boolean appendWorkingItems(List<PlanVolunteer> target,
                                              List<DraftItemDTO> items,
                                              List<CandidateItemDTO> candidates) {
        int before = target.size();
        for (DraftItemDTO item : defaultList(items)) {
            if (item != null) {
                target.add(PlanVolunteer.from(item,
                        findCurrentPlanCandidate(candidates, item.getVolunteerId(),
                                unitIdPrefix(item.getVolunteerId()), item.getSchoolName(), item.getMajorName()),
                        candidates));
            }
        }
        return target.size() > before;
    }

    private static boolean appendWorkingUnits(List<PlanVolunteer> target,
                                              List<DraftUnitDTO> units,
                                              List<CandidateItemDTO> candidates) {
        int before = target.size();
        for (DraftUnitDTO unit : defaultList(units)) {
            if (unit != null) {
                for (PlanningUnitMajorDTO major : defaultList(unit.getMajorItems())) {
                    if (major != null) {
                        target.add(PlanVolunteer.from(unit, major,
                                findCurrentPlanCandidate(candidates, major.getVolunteerId(), unit.getUnitId(),
                                        unit.getSchoolName(), major.getMajorName()), candidates));
                    }
                }
            }
        }
        return target.size() > before;
    }

    private static CandidateItemDTO findCurrentPlanCandidate(List<CandidateItemDTO> candidates,
                                                             String volunteerId,
                                                             String unitId,
                                                             String schoolName,
                                                             String majorName) {
        CandidateItemDTO direct = RepairCandidateSelector.findCandidate(candidates, volunteerId);
        if (direct != null) {
            return direct;
        }
        if (Strings.isNullOrEmpty(majorName)) {
            return null;
        }
        List<CandidateItemDTO> matches = defaultList(candidates).stream()
                .filter(Objects::nonNull)
                .filter(candidate -> majorName.equals(candidate.getMajorName()))
                .filter(candidate -> !Strings.isNullOrEmpty(unitId)
                        ? unitId.equals(RepairCandidateSelector.resolveInitialRecommendationUnitId(candidate))
                        : !Strings.isNullOrEmpty(schoolName) && schoolName.equals(candidate.getSchoolName()))
                .limit(2)
                .collect(Collectors.toList());
        return matches.size() == 1 ? matches.get(0) : null;
    }

    private static String unitIdPrefix(String volunteerId) {
        if (Strings.isNullOrEmpty(volunteerId)) {
            return null;
        }
        int split = volunteerId.indexOf('_');
        return split > 0 ? volunteerId.substring(0, split) : null;
    }

    private static Comparator<CandidateItemDTO> buildCandidatePreviewComparator() {
        return Comparator
                .comparing((CandidateItemDTO item) -> item.getIntentScore(), Comparator.nullsLast(Comparator.reverseOrder()))
                .thenComparing(item -> item.getAdmissionRatio(), Comparator.nullsLast(Comparator.reverseOrder()))
                .thenComparing(item -> item.getFinalScore(), Comparator.nullsLast(Comparator.reverseOrder()))
                .thenComparing(item -> item.getSchoolRank(), Comparator.nullsLast(Integer::compareTo))
                .thenComparing(CandidateItemDTO::getVolunteerId, Comparator.nullsLast(String::compareTo));
    }

    private static int compareNullableDoubleDesc(Double left, Double right) {
        if (left == null && right == null) {
            return 0;
        }
        if (left == null) {
            return 1;
        }
        if (right == null) {
            return -1;
        }
        return Double.compare(right, left);
    }

    private static int compareNullableIntegerAsc(Integer left, Integer right) {
        if (left == null && right == null) {
            return 0;
        }
        if (left == null) {
            return 1;
        }
        if (right == null) {
            return -1;
        }
        return Integer.compare(left, right);
    }

    private static String buildProposalId(PlanningStateDTO state, UserGoalFixProposalReq req, String reasonCode) {
        String raw = String.join("|",
                String.valueOf(state == null ? null : state.getSessionId()),
                String.valueOf(state == null ? null : state.getVersion()),
                String.valueOf(req == null ? null : req.getGoalType()),
                String.valueOf(req == null ? null : req.getTargetCount()),
                String.valueOf(req == null ? null : req.getRequirements()),
                String.valueOf(req == null ? null : req.getPriorityRules()),
                String.valueOf(req == null ? null : req.getTierQuotaGoal()),
                String.valueOf(req == null ? null : req.getUserOriginalText()),
                String.valueOf(reasonCode));
        return "ugp_" + UUID.nameUUIDFromBytes(raw.getBytes(StandardCharsets.UTF_8)).toString().replace("-", "").substring(0, 16);
    }

    private static <T> List<T> defaultList(List<T> values) {
        return values == null ? Lists.newArrayList() : values;
    }

    private static <T> Set<T> defaultSet(Set<T> values) {
        return values == null ? new LinkedHashSet<T>() : values;
    }

    private static String firstNonEmpty(String... values) {
        for (String value : values) {
            if (!Strings.isNullOrEmpty(Strings.nullToEmpty(value).trim())) {
                return value.trim();
            }
        }
        return "";
    }

    private static String normalizeText(String text) {
        return Strings.nullToEmpty(text).trim().toLowerCase(Locale.ROOT).replaceAll("\\s+", "");
    }

    private static boolean containsLoose(String text, String value) {
        String normalizedText = normalizeText(text);
        String normalizedValue = normalizeText(value);
        if (Strings.isNullOrEmpty(normalizedText) || Strings.isNullOrEmpty(normalizedValue)) {
            return false;
        }
        return normalizedText.contains(normalizedValue) || normalizedValue.contains(normalizedText);
    }

    private static boolean containsAny(List<String> texts, String value) {
        return defaultList(texts).stream().anyMatch(text -> containsLoose(text, value));
    }

    private static boolean containsAny(String value, String... texts) {
        for (String text : texts) {
            if (containsLoose(text, value)) {
                return true;
            }
        }
        return false;
    }

    private static final class ScopeMatcher {
        private final String entityType;
        private final String value;
        private final String scopeLevel;
        private final String resolutionStatus;

        private ScopeMatcher(String entityType, String value, String scopeLevel, String resolutionStatus) {
            this.entityType = entityType;
            this.value = value;
            this.scopeLevel = scopeLevel;
            this.resolutionStatus = resolutionStatus;
        }

        static ScopeMatcher from(UserGoalFixProposalReq.ScopeDTO scope) {
            if (scope == null) {
                return new ScopeMatcher("", "", "", "");
            }
            String entityType = normalizeEntityType(firstNonEmpty(scope.getEntityType(), scope.getScopeType()));
            String value = firstNonEmpty(scope.getNormalizedName(), scope.getName(), scope.getRawText());
            String scopeLevel = firstNonEmpty(
                    scope.getScopeLevel(),
                    scope.getEvidence() == null ? null : String.valueOf(scope.getEvidence().get("scopeLevel")));
            return new ScopeMatcher(entityType, value, normalizeScopeLevel(scopeLevel),
                    Strings.nullToEmpty(scope.getResolutionStatus()).trim());
        }

        String getValue() {
            return value;
        }

        boolean needsClarification() {
            return !isSupportedEntityType(entityType)
                    || "unknown".equals(resolutionStatus)
                    || "multiple_match".equals(resolutionStatus)
                    || "needs_clarification".equals(resolutionStatus)
                    || "ambiguous".equals(resolutionStatus);
        }

        boolean matches(PlanVolunteer item) {
            if (item == null) {
                return false;
            }
            CandidateItemDTO candidate = item.getCandidate();
            if (candidate != null && matches(candidate)) {
                return true;
            }
            if ("major".equals(entityType)) {
                return containsLoose(item.getMajorName(), value);
            }
            if ("school".equals(entityType)) {
                return containsLoose(item.getSchoolName(), value);
            }
            if ("program_type".equals(entityType)) {
                return matchesProgramType(
                        value,
                        item.getSchoolName(),
                        item.getMajorName(),
                        candidate);
            }
            return false;
        }

        boolean matches(CandidateItemDTO candidate) {
            if (candidate == null) {
                return false;
            }
            if ("major".equals(entityType)) {
                return containsLoose(candidate.getMajorName(), value)
                        || containsLoose(candidate.getMajorCategory(), value)
                        || containsLoose(candidate.getMajorDiscipline(), value)
                        || containsLoose(candidate.getMajorLevel(), value)
                        || containsAny(candidate.getMajorPlanTags(), value)
                        || containsAny(candidate.getMajorRankTags(), value);
            }
            if ("school".equals(entityType)) {
                return containsLoose(candidate.getDisplaySchoolName(), value)
                        || containsLoose(candidate.getSchoolName(), value);
            }
            if ("region".equals(entityType)) {
                return matchesRegion(candidate);
            }
            if ("tag".equals(entityType) || "risk".equals(entityType)) {
                return containsAny(candidate.getReasonCodes(), value)
                        || containsAny(candidate.getRiskFlags(), value)
                        || containsAny(candidate.getSchoolRankTags(), value)
                        || containsAny(candidate.getSchoolBasicTags(), value)
                        || containsAny(candidate.getSchoolPopupTags(), value)
                        || containsAny(candidate.getMajorPlanTags(), value)
                        || containsAny(candidate.getMajorRankTags(), value);
            }
            if ("program_type".equals(entityType)) {
                return matchesProgramType(
                        value,
                        candidate.getSchoolName(),
                        candidate.getDisplaySchoolName(),
                        candidate.getMajorName(),
                        candidate.getSchoolNature(),
                        candidate.getSchoolCategory(),
                        candidate.getSchoolBatch(),
                        candidate.getReasonCodes(),
                        candidate.getRiskFlags(),
                        candidate.getSchoolRankTags(),
                        candidate.getSchoolBasicTags(),
                        candidate.getSchoolPopupTags(),
                        candidate.getMajorPlanTags(),
                        candidate.getMajorRankTags());
            }
            return containsLoose(candidate.getMajorName(), value)
                    || containsLoose(candidate.getSchoolName(), value)
                    || containsLoose(candidate.getProvinceName(), value)
                    || containsLoose(candidate.getCityName(), value);
        }

        private boolean matchesRegion(CandidateItemDTO candidate) {
            if (candidate == null) {
                return false;
            }
            if ("area".equals(scopeLevel)) {
                if (RegionScopeSupport.matchesRegionScope(value, candidate.getProvinceName(), candidate.getCityName())) {
                    return true;
                }
                return containsLoose(candidate.getProvinceName(), value)
                        || containsLoose(candidate.getCityName(), value);
            }
            if ("province".equals(scopeLevel)) {
                return containsLoose(candidate.getProvinceName(), value);
            }
            if ("city".equals(scopeLevel)) {
                return containsLoose(candidate.getCityName(), value);
            }
            return containsLoose(candidate.getProvinceName(), value)
                    || containsLoose(candidate.getCityName(), value);
        }

        private static boolean matchesProgramType(String value, String schoolName, String majorName, CandidateItemDTO candidate) {
            if (candidate == null) {
                return containsAny(value, schoolName, majorName);
            }
            return matchesProgramType(
                    value,
                    schoolName,
                    candidate.getDisplaySchoolName(),
                    majorName,
                    candidate.getSchoolNature(),
                    candidate.getSchoolCategory(),
                    candidate.getSchoolBatch(),
                    candidate.getReasonCodes(),
                    candidate.getRiskFlags(),
                    candidate.getSchoolRankTags(),
                    candidate.getSchoolBasicTags(),
                    candidate.getSchoolPopupTags(),
                    candidate.getMajorPlanTags(),
                    candidate.getMajorRankTags());
        }

        private static boolean matchesProgramType(String value, Object... fields) {
            for (Object field : fields) {
                if (field instanceof String && containsLoose((String) field, value)) {
                    return true;
                }
                if (field instanceof List<?>) {
                    List<String> values = ((List<?>) field).stream()
                            .filter(Objects::nonNull)
                            .map(String::valueOf)
                            .collect(Collectors.toList());
                    if (containsAny(values, value)) {
                        return true;
                    }
                }
            }
            return false;
        }

        private static String normalizeEntityType(String type) {
            String text = Strings.nullToEmpty(type).trim().toLowerCase(Locale.ROOT);
            if ("province".equals(text) || "city".equals(text) || "area".equals(text)
                    || "province_keyword".equals(text)) {
                return "region";
            }
            if ("major_keyword".equals(text) || "source_major".equals(text) || "source_major_name".equals(text)) {
                return "major";
            }
            if ("school_keyword".equals(text)) {
                return "school";
            }
            if ("major_tag".equals(text) || "school_tag".equals(text)) {
                return "tag";
            }
            if ("review_issue".equals(text)) {
                return "risk";
            }
            if ("project_type".equals(text) || "admission_type".equals(text)
                    || "enrollment_type".equals(text) || "program".equals(text)
                    || "project".equals(text)) {
                return "program_type";
            }
            return text;
        }

        private static String normalizeScopeLevel(String level) {
            String text = Strings.nullToEmpty(level).trim().toLowerCase(Locale.ROOT);
            if ("province".equals(text) || "city".equals(text) || "area".equals(text)) {
                return text;
            }
            return "";
        }

        private static boolean isSupportedEntityType(String type) {
            return "major".equals(type)
                    || "school".equals(type)
                    || "region".equals(type)
                    || "tag".equals(type)
                    || "risk".equals(type)
                    || "program_type".equals(type);
        }

        private static String firstNonEmpty(String... values) {
            for (String value : values) {
                if (!Strings.isNullOrEmpty(Strings.nullToEmpty(value).trim())) {
                    return value.trim();
                }
            }
            return "";
        }
    }

    private static FillCurrentProjection projectCurrentPlan(List<PlanVolunteer> current,
                                                            HardConstraintsDTO projectedRequirements,
                                                            boolean majorGroupMode) {
        FillCurrentProjection result = new FillCurrentProjection();
        if (!majorGroupMode) {
            for (PlanVolunteer volunteer : defaultList(current)) {
                if (ProjectedHardRequirementSupport.isAllowed(volunteer.asCandidate(), projectedRequirements)) {
                    result.retainedCount++;
                    continue;
                }
                result.lockedViolation = result.lockedViolation || volunteer.isLocked();
                if (!Strings.isNullOrEmpty(volunteer.getVolunteerId())) {
                    result.removeVolunteerIds.add(volunteer.getVolunteerId());
                }
                if (!Strings.isNullOrEmpty(volunteer.getUnitId())) {
                    result.removeUnitIds.add(volunteer.getUnitId());
                }
            }
            return result;
        }

        Map<String, List<PlanVolunteer>> grouped = new LinkedHashMap<String, List<PlanVolunteer>>();
        for (PlanVolunteer volunteer : defaultList(current)) {
            String unitId = firstNonEmpty(volunteer.getUnitId(), volunteer.getVolunteerId());
            grouped.computeIfAbsent(unitId, ignored -> Lists.newArrayList()).add(volunteer);
        }
        for (Map.Entry<String, List<PlanVolunteer>> entry : grouped.entrySet()) {
            List<PlanVolunteer> disallowed = entry.getValue().stream()
                    .filter(volunteer -> !ProjectedHardRequirementSupport.isAllowed(
                            volunteer.asCandidate(), projectedRequirements))
                    .collect(Collectors.toList());
            if (disallowed.isEmpty()) {
                result.retainedCount++;
                continue;
            }
            result.lockedViolation = result.lockedViolation
                    || disallowed.stream().anyMatch(PlanVolunteer::isLocked);
            disallowed.stream()
                    .map(PlanVolunteer::getVolunteerId)
                    .filter(value -> !Strings.isNullOrEmpty(value))
                    .filter(value -> !result.removeVolunteerIds.contains(value))
                    .forEach(result.removeVolunteerIds::add);
            if (disallowed.size() < entry.getValue().size()) {
                result.retainedCount++;
                continue;
            }
            if (!Strings.isNullOrEmpty(entry.getKey())) {
                result.removeUnitIds.add(entry.getKey());
            }
        }
        return result;
    }

    private static final class FillCurrentProjection {
        private int retainedCount;
        private boolean lockedViolation;
        private final List<String> removeUnitIds = Lists.newArrayList();
        private final List<String> removeVolunteerIds = Lists.newArrayList();
    }

    private static final class FillSelection {
        private boolean unitMode;
        private int availableWithoutHardConstraints;
        private int availableWithHardConstraints;
        private String blockingReasonCode;
        private String blockingReason;
        private int coverageShortageCount;
        private PlanSolverResultDTO solverResult;
        private final List<String> unitIds = Lists.newArrayList();
        private final List<String> volunteerIds = Lists.newArrayList();
        private final List<String> removeUnitIds = Lists.newArrayList();
        private final List<String> removeVolunteerIds = Lists.newArrayList();

        private int selectedCount() {
            return unitMode ? new LinkedHashSet<String>(unitIds).size() : volunteerIds.size();
        }

        private int replacementCount() {
            return unitMode ? new LinkedHashSet<String>(removeUnitIds).size() : removeVolunteerIds.size();
        }

        private void add(FillOption option) {
            if (option == null) {
                return;
            }
            if (!Strings.isNullOrEmpty(option.unitId) && !unitIds.contains(option.unitId)) {
                unitIds.add(option.unitId);
            }
            option.volunteerIds.stream()
                    .filter(value -> !volunteerIds.contains(value))
                    .forEach(volunteerIds::add);
        }

        private void block(String reasonCode, String reason, int shortageCount) {
            this.blockingReasonCode = reasonCode;
            this.blockingReason = reason;
            this.coverageShortageCount = Math.max(0, shortageCount);
        }
    }

    private static final class FillOption {
        private final String unitId;
        private final List<CandidateItemDTO> candidates;
        private final CandidateItemDTO representative;
        private final List<String> volunteerIds;

        private FillOption(CandidateItemDTO candidate) {
            this(RepairCandidateSelector.resolveInitialRecommendationUnitId(candidate),
                    Lists.newArrayList(candidate));
        }

        private FillOption(String unitId, List<CandidateItemDTO> sourceCandidates) {
            this.unitId = unitId;
            this.candidates = defaultList(sourceCandidates).stream()
                    .filter(Objects::nonNull)
                    .sorted(buildCandidatePreviewComparator())
                    .collect(Collectors.toList());
            this.representative = this.candidates.isEmpty() ? new CandidateItemDTO() : this.candidates.get(0);
            this.volunteerIds = this.candidates.stream()
                    .map(CandidateItemDTO::getVolunteerId)
                    .filter(value -> !Strings.isNullOrEmpty(value))
                    .distinct()
                    .collect(Collectors.toList());
        }

        private FillOption retainAllowed(HardConstraintsDTO projectedHardConstraints) {
            List<CandidateItemDTO> allowed = candidates.stream()
                    .filter(candidate -> ProjectedHardRequirementSupport.isAllowed(
                            candidate, projectedHardConstraints))
                    .collect(Collectors.toList());
            return allowed.isEmpty() ? null : new FillOption(unitId, allowed);
        }

        private String entityId(boolean unitMode) {
            return unitMode ? unitId : volunteerIds.isEmpty() ? null : volunteerIds.get(0);
        }

        private PlanSolverInputDTO.CandidateDTO asSolverCandidate(
                boolean unitMode,
                int stableOrder,
                List<CoverageRequirementDTO> coverage,
                PriorityRuleDTO priorityRule) {
            PlanSolverInputDTO.CandidateDTO result = new PlanSolverInputDTO.CandidateDTO();
            result.setEntityId(entityId(unitMode));
            result.setVolunteerIds(Lists.newArrayList(volunteerIds));
            result.setStableOrder(stableOrder);
            result.setCurrent(false);
            result.setLocked(false);
            result.setPinned(false);
            result.setEligible(true);
            result.setTier(representative == null ? null : representative.getTier());
            result.setCoverageObjectiveIds(matchedCoverageIds(candidates, coverage));
            result.setPriorityMatched(priorityRule != null && candidates.stream()
                    .anyMatch(candidate -> PriorityRuleSupport.matches(candidate, priorityRule)));
            return result;
        }
    }

    private static final class CoverageEntity {
        private final List<String> unitIds = Lists.newArrayList();
        private final List<String> volunteerIds = Lists.newArrayList();
        private final List<CandidateItemDTO> candidates = Lists.newArrayList();
        private final boolean locked;
        private final boolean pinned;

        private CoverageEntity(PlanVolunteer volunteer) {
            if (volunteer != null) {
                if (!Strings.isNullOrEmpty(volunteer.getUnitId())) {
                    unitIds.add(volunteer.getUnitId());
                }
                if (!Strings.isNullOrEmpty(volunteer.getVolunteerId())) {
                    volunteerIds.add(volunteer.getVolunteerId());
                }
                candidates.add(volunteer.asCandidate());
            }
            this.locked = volunteer != null && volunteer.isLocked();
            this.pinned = volunteer != null && volunteer.isPinned();
        }

        private CoverageEntity(String unitId, List<PlanVolunteer> volunteers) {
            if (!Strings.isNullOrEmpty(unitId)) {
                unitIds.add(unitId);
            }
            for (PlanVolunteer volunteer : defaultList(volunteers)) {
                if (volunteer == null) {
                    continue;
                }
                if (!Strings.isNullOrEmpty(volunteer.getVolunteerId())) {
                    volunteerIds.add(volunteer.getVolunteerId());
                }
                candidates.add(volunteer.asCandidate());
            }
            this.locked = defaultList(volunteers).stream().anyMatch(
                    volunteer -> volunteer != null && volunteer.isLocked());
            this.pinned = defaultList(volunteers).stream().anyMatch(
                    volunteer -> volunteer != null && volunteer.isPinned());
        }

        private boolean matchesTier(String expectedTier) {
            return candidates.stream().anyMatch(candidate -> expectedTier.equals(
                    TierQuotaSupport.canonicalTierKey(candidate.getTier())));
        }

        private String entityId(boolean unitMode) {
            return unitMode ? unitIds.isEmpty() ? null : unitIds.get(0)
                    : volunteerIds.isEmpty() ? null : volunteerIds.get(0);
        }

        private PlanSolverInputDTO.CandidateDTO asSolverCandidate(
                boolean unitMode,
                int stableOrder,
                List<CoverageRequirementDTO> coverage,
                PriorityRuleDTO priorityRule) {
            PlanSolverInputDTO.CandidateDTO result = new PlanSolverInputDTO.CandidateDTO();
            result.setEntityId(entityId(unitMode));
            result.setVolunteerIds(Lists.newArrayList(volunteerIds));
            result.setStableOrder(stableOrder);
            result.setCurrent(true);
            result.setLocked(locked);
            result.setPinned(pinned);
            result.setEligible(true);
            result.setTier(candidates.isEmpty() ? null : candidates.get(0).getTier());
            result.setCoverageObjectiveIds(matchedCoverageIds(candidates, coverage));
            result.setPriorityMatched(priorityRule != null && candidates.stream()
                    .anyMatch(candidate -> PriorityRuleSupport.matches(candidate, priorityRule)));
            return result;
        }
    }

    private static final class PlanVolunteer {
        private final String volunteerId;
        private final String unitId;
        private final String schoolName;
        private final String majorName;
        private final boolean locked;
        private final boolean pinned;
        private final CandidateItemDTO candidate;

        private PlanVolunteer(String volunteerId,
                              String unitId,
                              String schoolName,
                              String majorName,
                              boolean locked,
                              boolean pinned,
                              CandidateItemDTO candidate) {
            this.volunteerId = volunteerId;
            this.unitId = unitId;
            this.schoolName = schoolName;
            this.majorName = majorName;
            this.locked = locked;
            this.pinned = pinned;
            this.candidate = candidate;
        }

        static PlanVolunteer from(OrderedItemDTO item,
                                  OrderedUnitDTO unit,
                                  PlanningUnitMajorDTO major,
                                  CandidateItemDTO candidate,
                                  List<CandidateItemDTO> candidates) {
            String unitId = firstNonEmpty(
                    unit == null ? null : unit.getUnitId(),
                    item == null ? null : RepairCandidateSelector.resolveUnitId(item.getVolunteerId(), candidates));
            CandidateItemDTO view = candidateView(candidate,
                    item == null ? null : item.getVolunteerId(), unitId,
                    firstNonEmpty(item == null ? null : item.getSchoolName(), unit == null ? null : unit.getSchoolName()),
                    firstNonEmpty(item == null ? null : item.getMajorName(), major == null ? null : major.getMajorName()),
                    unit == null ? null : unit.getProvinceName(), unit == null ? null : unit.getCityName(),
                    unit == null ? null : unit.getSchoolLevel(), unit == null ? null : unit.getSchoolNature(),
                    unit == null ? null : unit.getSchoolCategory(), major);
            view.setTier(firstNonEmpty(view.getTier(),
                    item == null ? null : item.getTier(), unit == null ? null : unit.getTier()));
            return new PlanVolunteer(
                    item == null ? null : item.getVolunteerId(),
                    unitId,
                    view.getSchoolName(),
                    view.getMajorName(),
                    (item != null && Boolean.TRUE.equals(item.getLocked()))
                            || (unit != null && Boolean.TRUE.equals(unit.getLocked())),
                    (item != null && Boolean.TRUE.equals(item.getPinned()))
                            || (unit != null && Boolean.TRUE.equals(unit.getPinned())),
                    view);
        }

        static PlanVolunteer from(DraftItemDTO item, CandidateItemDTO candidate, List<CandidateItemDTO> candidates) {
            String unitId = item == null ? null : RepairCandidateSelector.resolveUnitId(item.getVolunteerId(), candidates);
            CandidateItemDTO view = candidateView(candidate,
                    item == null ? null : item.getVolunteerId(), unitId,
                    item == null ? null : item.getSchoolName(), item == null ? null : item.getMajorName(),
                    null, null, null, null, null, null);
            view.setTier(firstNonEmpty(view.getTier(), item == null ? null : item.getTier()));
            return new PlanVolunteer(
                    item == null ? null : item.getVolunteerId(),
                    unitId,
                    view.getSchoolName(),
                    view.getMajorName(),
                    item != null && Boolean.TRUE.equals(item.getLocked()),
                    false,
                    view);
        }

        static PlanVolunteer from(OrderedUnitDTO unit,
                                  PlanningUnitMajorDTO major,
                                  CandidateItemDTO candidate,
                                  List<CandidateItemDTO> candidates) {
            String unitId = firstNonEmpty(unit == null ? null : unit.getUnitId(),
                    major == null ? null : RepairCandidateSelector.resolveUnitId(major.getVolunteerId(), candidates));
            CandidateItemDTO view = candidateView(candidate,
                    major == null ? null : major.getVolunteerId(), unitId,
                    unit == null ? null : unit.getSchoolName(), major == null ? null : major.getMajorName(),
                    unit == null ? null : unit.getProvinceName(), unit == null ? null : unit.getCityName(),
                    unit == null ? null : unit.getSchoolLevel(), unit == null ? null : unit.getSchoolNature(),
                    unit == null ? null : unit.getSchoolCategory(), major);
            view.setTier(firstNonEmpty(view.getTier(), unit == null ? null : unit.getTier()));
            return new PlanVolunteer(
                    major == null ? null : major.getVolunteerId(),
                    unitId,
                    view.getSchoolName(),
                    view.getMajorName(),
                    unit != null && Boolean.TRUE.equals(unit.getLocked()),
                    unit != null && Boolean.TRUE.equals(unit.getPinned()),
                    view);
        }

        static PlanVolunteer from(DraftUnitDTO unit,
                                  PlanningUnitMajorDTO major,
                                  CandidateItemDTO candidate,
                                  List<CandidateItemDTO> candidates) {
            String unitId = firstNonEmpty(unit == null ? null : unit.getUnitId(),
                    major == null ? null : RepairCandidateSelector.resolveUnitId(major.getVolunteerId(), candidates));
            CandidateItemDTO view = candidateView(candidate,
                    major == null ? null : major.getVolunteerId(), unitId,
                    unit == null ? null : unit.getSchoolName(), major == null ? null : major.getMajorName(),
                    null, null, null, null, null, major);
            view.setTier(firstNonEmpty(view.getTier(), unit == null ? null : unit.getTier()));
            return new PlanVolunteer(
                    major == null ? null : major.getVolunteerId(),
                    unitId,
                    view.getSchoolName(),
                    view.getMajorName(),
                    unit != null && Boolean.TRUE.equals(unit.getLocked()),
                    false,
                    view);
        }

        String getVolunteerId() {
            return volunteerId;
        }

        String getUnitId() {
            return unitId;
        }

        String getSchoolName() {
            return schoolName;
        }

        String getMajorName() {
            return majorName;
        }

        boolean isLocked() {
            return locked;
        }

        boolean isPinned() {
            return pinned;
        }

        CandidateItemDTO getCandidate() {
            return candidate;
        }

        CandidateItemDTO asCandidate() {
            return candidate;
        }

        private static CandidateItemDTO candidateView(CandidateItemDTO source,
                                                      String volunteerId,
                                                      String unitId,
                                                      String schoolName,
                                                      String majorName,
                                                      String provinceName,
                                                      String cityName,
                                                      String schoolLevel,
                                                      String schoolNature,
                                                      String schoolCategory,
                                                      PlanningUnitMajorDTO major) {
            CandidateItemDTO view = new CandidateItemDTO();
            if (source != null) {
                BeanUtils.copyProperties(source, view);
            }
            view.setVolunteerId(firstNonEmpty(view.getVolunteerId(), volunteerId));
            view.setPlanSchoolDataId(firstNonEmpty(view.getPlanSchoolDataId(), unitId));
            view.setSchoolName(firstNonEmpty(view.getSchoolName(), schoolName));
            view.setDisplaySchoolName(firstNonEmpty(view.getDisplaySchoolName(), view.getSchoolName()));
            view.setMajorName(firstNonEmpty(view.getMajorName(), majorName));
            view.setProvinceName(firstNonEmpty(view.getProvinceName(), provinceName));
            view.setCityName(firstNonEmpty(view.getCityName(), cityName));
            view.setSchoolLevel(firstNonEmpty(view.getSchoolLevel(), schoolLevel));
            view.setSchoolNature(firstNonEmpty(view.getSchoolNature(), schoolNature));
            view.setSchoolCategory(firstNonEmpty(view.getSchoolCategory(), schoolCategory));
            if (major != null) {
                if (view.getTuitionPerYear() == null) {
                    view.setTuitionPerYear(major.getTuitionPerYear());
                }
                if (defaultList(view.getReasonCodes()).isEmpty()) {
                    view.setReasonCodes(Lists.newArrayList(defaultList(major.getReasonCodes())));
                }
                if (defaultList(view.getMajorPlanTags()).isEmpty()) {
                    view.setMajorPlanTags(Lists.newArrayList(defaultList(major.getMajorPlanTags())));
                }
            }
            return view;
        }

        private static String firstNonEmpty(String... values) {
            for (String value : values) {
                if (!Strings.isNullOrEmpty(Strings.nullToEmpty(value).trim())) {
                    return value.trim();
                }
            }
            return "";
        }
    }

    private static final class ReplacementPreviewPair {
        private final PlanVolunteer source;
        private final CandidateItemDTO candidate;
        private final String reasonCode;

        private ReplacementPreviewPair(PlanVolunteer source, CandidateItemDTO candidate, String reasonCode) {
            this.source = source;
            this.candidate = candidate;
            this.reasonCode = reasonCode;
        }
    }
}
