package com.ytell.zhiyuan.service.biz;

import com.google.common.base.Strings;
import com.google.common.collect.Lists;
import com.ytell.zhiyuan.model.dto.planning.CandidateFactDTO;
import com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO;
import com.ytell.zhiyuan.model.dto.planning.CandidatePoolStateDTO;
import com.ytell.zhiyuan.model.dto.planning.CandidateShortageDTO;
import com.ytell.zhiyuan.model.dto.planning.CandidateSnapshotDTO;
import com.ytell.zhiyuan.model.dto.planning.MutationPolicyDTO;
import com.ytell.zhiyuan.model.dto.planning.CanonicalPlanningObjectiveSetDTO;
import com.ytell.zhiyuan.model.dto.planning.CoverageRequirementDTO;
import com.ytell.zhiyuan.model.dto.planning.DraftItemDTO;
import com.ytell.zhiyuan.model.dto.planning.DraftUnitDTO;
import com.ytell.zhiyuan.model.dto.planning.FixProposalActionDTO;
import com.ytell.zhiyuan.model.dto.planning.FixProposalAffectedItemDTO;
import com.ytell.zhiyuan.model.dto.planning.FixProposalDTO;
import com.ytell.zhiyuan.model.dto.planning.FixProposalStateDTO;
import com.ytell.zhiyuan.model.dto.planning.HardConstraintsDTO;
import com.ytell.zhiyuan.model.dto.planning.HardPlanningObjectivesDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedItemDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedPlanStateDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedUnitDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningUnitMajorDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanSolverResultDTO;
import com.ytell.zhiyuan.model.dto.planning.PriorityRuleDTO;
import com.ytell.zhiyuan.model.dto.planning.ReplacementPairDTO;
import com.ytell.zhiyuan.model.dto.planning.TierAllocationConstraintDTO;
import com.ytell.zhiyuan.model.dto.planning.TierAllocationResolutionDTO;
import com.ytell.zhiyuan.model.dto.planning.TierCountRangeDTO;
import com.ytell.zhiyuan.model.dto.planning.TierCountsDTO;
import com.ytell.zhiyuan.model.dto.planning.TierQuotaChangeDTO;
import com.ytell.zhiyuan.model.dto.planning.TierQuotaGoalDTO;
import com.ytell.zhiyuan.model.dto.planning.TierQuotaGoalRequestDTO;
import com.ytell.zhiyuan.model.dto.planning.UserGoalFixProposalReq;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.BeanUtils;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.ArrayList;
import java.util.Collections;
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
    /** 明细预览：≤5 条全列；>5 条只列前 3 条并注明余量（2026-10-16 口径）。 */
    private static final int ENTRY_PREVIEW_FULL_LIST_LIMIT = 5;
    private static final int ENTRY_PREVIEW_HEAD_COUNT = 3;
    private static final StagedDeterministicPlanSolver STAGED_SOLVER = new StagedDeterministicPlanSolver();
    private static final Logger LOG = LoggerFactory.getLogger(UserGoalProposalBuilder.class);
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
        // S4：从冻结求解结果透传硬目标契约版本；legacy solver 为 null。
        proposal.setHardObjectiveVersion(solverResult.getHardObjectiveVersion());
        proposal.setSolverResult(solverResult);
    }

    private static TierQuotaChangeDTO buildTierQuotaChange(PlanningStateDTO state,
                                                            TierQuotaGoalRequestDTO requested,
                                                            Integer targetCount,
                                                            CanonicalPlanningObjectiveSetDTO objectiveSet) {
        TierAllocationSupport.CompiledTierAllocation compiled =
                TierAllocationSupport.compile(state, requested, targetCount);
        TierQuotaChangeDTO result = new TierQuotaChangeDTO();
        result.setBeforeGoal(TierAllocationSupport.copyGoal(
                TierAllocationSupport.confirmedGoal(state)));
        result.setRequestedGoal(TierAllocationSupport.copyRequest(compiled.getRequestedGoal()));
        result.setEffectiveGoal(TierAllocationSupport.copyGoal(compiled.getEffectiveSourceGoal()));
        result.setResolution(TierAllocationSupport.copyResolution(
                objectiveSet == null ? compiled.getResolution() : objectiveSet.getTierAllocationResolution()));
        result.setStateChanged(compiled.isStateChanged());
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
            return "冲稳保精确配额：" + TierAllocationSupport.summarize(goal);
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

    private static String tierAllocationLabel(TierQuotaGoalRequestDTO goal) {
        String type = goal == null ? ""
                : Strings.nullToEmpty(goal.getType()).trim().toLowerCase(Locale.ROOT);
        if (TierAllocationSupport.TYPE_EXACT_COUNTS.equals(type)) {
            return "冲稳保精确配额";
        }
        if (TierAllocationSupport.TYPE_COUNT_RANGES.equals(type)) {
            return "冲稳保数量范围";
        }
        if (TierAllocationSupport.TYPE_RATIOS.equals(type)) {
            return "冲稳保比例";
        }
        return "冲稳保硬目标";
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
                    tierAllocationLabel(req.getTierQuotaGoal())
                            + "只支持 fill_to_count 方案目标，不能附加到其他 Proposal。");
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
        if (RepairProposalTaxonomy.Strategy.ADD_UNITS_BY_SCOPE.equals(goalType)) {
            return buildAddUnitsByScopeProposal(state, req);
        }
        if (RepairProposalTaxonomy.Strategy.ADD_UNITS.equals(goalType)) {
            return buildAddUnitsProposal(state, req);
        }
        if (RepairProposalTaxonomy.Strategy.REMOVE_UNITS.equals(goalType)) {
            return buildRemoveUnitsProposal(state, req);
        }
        if (RepairProposalTaxonomy.Strategy.MOVE_UNITS.equals(goalType)) {
            return buildMoveUnitsProposal(state, req);
        }
        return buildBlockedProposal(state, req, goalType, REASON_ENGINE_NOT_READY);
    }

    // ── 按范围加入（add_units_by_scope）：范围/学费筛选 + 固定新增数，纯加入、零删除 ──

    private static final String REASON_ADD_BY_SCOPE_COUNT = "add_units_by_scope_count_invalid";
    private static final String REASON_ADD_BY_SCOPE_INSUFFICIENT = "add_units_by_scope_insufficient";

    /**
     * 用户在“再加 N 条，范围内/学费内”这类诉求下，由服务端从候选池确定性选条目：
     * 筛选条件只作用于**本次新增**，不改写整个方案；解析不出 N 条就如实阻断。
     */
    private static FixProposalDTO buildAddUnitsByScopeProposal(PlanningStateDTO state,
                                                               UserGoalFixProposalReq req) {
        int addCount = req.getAddCount() == null ? 0 : req.getAddCount();
        if (addCount <= 0) {
            return buildScopeBlockedProposal(state, req,
                    RepairProposalTaxonomy.Strategy.ADD_UNITS_BY_SCOPE,
                    REASON_ADD_BY_SCOPE_COUNT, "需要先明确本次要新增几条（数量必须大于 0）。");
        }
        List<CandidateItemDTO> pool = candidates(state);
        boolean majorGroupMode = isMajorGroupMode(state);
        List<PlanVolunteer> current = currentPlanVolunteers(state, pool);
        if (current.isEmpty()) {
            return buildScopeBlockedProposal(state, req,
                    RepairProposalTaxonomy.Strategy.ADD_UNITS_BY_SCOPE,
                    REASON_ADD_UNITS_NO_PLAN, "当前没有正式方案，先补方案再加入；按范围加入只往已有方案里加。");
        }
        if (pool.isEmpty()) {
            return buildScopeBlockedProposal(state, req,
                    RepairProposalTaxonomy.Strategy.ADD_UNITS_BY_SCOPE,
                    REASON_ADD_UNITS_SOURCE_UNAVAILABLE,
                    "当前会话的候选来源不可用（候选池为空或尚未生成），暂时不能按范围加入。");
        }
        HardPlanningObjectivesDTO hard = state.getConstraintState() == null
                ? null : state.getConstraintState().getHardPlanningObjectives();
        if (hard != null && hard.getTierQuotaGoal() != null) {
            return buildScopeBlockedProposal(state, req,
                    RepairProposalTaxonomy.Strategy.ADD_UNITS_BY_SCOPE,
                    REASON_ADD_UNITS_TIER_QUOTA,
                    "加入会改变已确认的冲稳保配额；请先调整配额或改用替换动作。");
        }
        Set<String> poolVolunteerIds = pool.stream()
                .map(CandidateItemDTO::getVolunteerId)
                .filter(value -> !Strings.isNullOrEmpty(value))
                .collect(Collectors.toCollection(LinkedHashSet::new));
        int stalePlanItems = 0;
        for (PlanVolunteer volunteer : current) {
            if (!poolVolunteerIds.contains(volunteer.getVolunteerId())) {
                stalePlanItems++;
            }
        }
        if (stalePlanItems > 0) {
            return buildScopeBlockedProposal(state, req,
                    RepairProposalTaxonomy.Strategy.ADD_UNITS_BY_SCOPE,
                    REASON_ADD_UNITS_STALE_PLAN_ITEM,
                    "当前方案里有 " + stalePlanItems + " 条已不在有效候选池中；先处理这些条目再加入，"
                            + "否则重生成可能删掉它们。");
        }

        List<ScopeMatcher> scopes = buildScopeMatchers(defaultList(req.getTargetScopes()));
        List<ScopeMatcher> negatives = buildScopeMatchers(defaultList(req.getNegativeScopes()));
        ScopeMatcher ambiguous = scopes.stream().filter(ScopeMatcher::needsClarification)
                .findFirst().orElse(null);
        if (ambiguous != null) {
            return buildScopeBlockedProposal(state, req,
                    RepairProposalTaxonomy.Strategy.ADD_UNITS_BY_SCOPE,
                    REASON_GOAL_UNCLEAR,
                    "“" + ambiguous.getValue() + "”还没有对应到明确范围，需要先确认后再生成加入预览。");
        }
        Set<String> currentVolunteerIds = current.stream()
                .map(PlanVolunteer::getVolunteerId)
                .filter(value -> !Strings.isNullOrEmpty(value))
                .collect(Collectors.toCollection(LinkedHashSet::new));
        Set<String> currentUnitIds = current.stream()
                .map(UserGoalProposalBuilder::planUnitKey)
                .filter(value -> !Strings.isNullOrEmpty(value))
                .collect(Collectors.toCollection(LinkedHashSet::new));
        Set<String> banned = state.getWorkingPlanState() == null
                ? new LinkedHashSet<String>()
                : new LinkedHashSet<String>(defaultList(state.getWorkingPlanState().getBannedVolunteerIds()));
        Integer maxTuition = maxTuitionFromRequest(req);
        Integer minTuition = req.getContext() == null ? null
                : intFromObject(req.getContext().get("minTuitionPerYear"));
        List<CandidateItemDTO> filtered = pool.stream()
                .filter(candidate -> candidate != null && !Strings.isNullOrEmpty(candidate.getVolunteerId()))
                .filter(candidate -> !currentVolunteerIds.contains(candidate.getVolunteerId()))
                .filter(candidate -> !banned.contains(candidate.getVolunteerId()))
                .filter(RepairCandidateSelector::isCompensationSafeCandidate)
                .filter(candidate -> RepairCandidateEligibility.isEligibleForConfirmedHardConstraints(candidate, state))
                .filter(candidate -> scopes.isEmpty() || matchesAny(candidate, scopes))
                .filter(candidate -> negatives.isEmpty() || !matchesAny(candidate, negatives))
                .filter(candidate -> {
                    Integer tuition = tuitionOf(candidate);
                    if (tuition == null) {
                        return true;
                    }
                    if (maxTuition != null && tuition > maxTuition) {
                        return false;
                    }
                    return minTuition == null || tuition >= minTuition;
                })
                .sorted(buildCandidatePreviewComparator())
                .collect(Collectors.toList());

        List<CandidateItemDTO> resolved = Lists.newArrayList();
        Set<String> resolvedUnitIds = new LinkedHashSet<String>();
        for (CandidateItemDTO candidate : filtered) {
            if (resolved.size() >= addCount) {
                break;
            }
            if (majorGroupMode) {
                String unitKey = candidateUnitKey(candidate);
                if (Strings.isNullOrEmpty(unitKey) || currentUnitIds.contains(unitKey)
                        || !resolvedUnitIds.add(unitKey)) {
                    continue;
                }
            }
            resolved.add(candidate);
        }
        if (resolved.size() < addCount) {
            String scopeText = scopes.isEmpty() ? "" : "“" + scopeLabel(scopes) + "”内";
            String tuitionText = maxTuition == null ? "" : "、学费不超过 " + maxTuition + " 元/年";
            return buildScopeBlockedProposal(state, req,
                    RepairProposalTaxonomy.Strategy.ADD_UNITS_BY_SCOPE,
                    REASON_ADD_BY_SCOPE_INSUFFICIENT,
                    "符合" + scopeText + "条件" + tuitionText + "且可加入的候选只有 "
                            + resolved.size() + " 个，不够本次要新增的 " + addCount + " 个；"
                            + "请放宽范围/学费，或点名补充。");
        }

        int currentCount = majorGroupMode ? currentUnitIds.size() : currentVolunteerIds.size();
        Integer confirmedTarget = hard == null ? null : hard.getSelectionTargetCount();
        if (confirmedTarget != null && confirmedTarget != currentCount) {
            return buildScopeBlockedProposal(state, req,
                    RepairProposalTaxonomy.Strategy.ADD_UNITS_BY_SCOPE,
                    REASON_ADD_UNITS_COUNT_MISMATCH,
                    "当前方案实际 " + currentCount + (majorGroupMode ? " 个专业组" : " 条")
                            + "，与已确认目标 " + confirmedTarget + " 不一致；请先补齐/调整目标，再加入。");
        }
        int addedEntryCount = resolved.size();
        Set<String> addedUnitIds = resolved.stream()
                .map(UserGoalProposalBuilder::candidateUnitKey)
                .filter(value -> !Strings.isNullOrEmpty(value))
                .collect(Collectors.toCollection(LinkedHashSet::new));
        int addedUnitCount = addedUnitIds.size();
        int addedCountForMode = majorGroupMode ? addedUnitCount : addedEntryCount;
        int targetAfter = currentCount + addedCountForMode;
        Integer targetCountOverride = confirmedTarget == null ? null : targetAfter;

        AddUnitsDryRun dryRun = dryRunAddUnits(state, current, resolved, targetAfter, majorGroupMode, "scope");
        if (!dryRun.ok) {
            return buildScopeBlockedProposal(state, req,
                    RepairProposalTaxonomy.Strategy.ADD_UNITS_BY_SCOPE,
                    dryRun.reason, dryRun.message);
        }

        FixProposalDTO proposal = buildUserGoalPreviewBase(state, req,
                RepairProposalTaxonomy.Strategy.ADD_UNITS_BY_SCOPE, "按范围加入志愿预览");
        proposal.setStatus(RepairProposalTaxonomy.Status.READY);
        proposal.setRequiresConfirmation(true);
        proposal.setAffectedVolunteerIds(resolved.stream()
                .map(CandidateItemDTO::getVolunteerId)
                .filter(value -> !Strings.isNullOrEmpty(value))
                .distinct().collect(Collectors.toList()));
        proposal.setAffectedUnitIds(Lists.newArrayList(addedUnitIds));
        proposal.setAffectedItems(resolved.stream().map(UserGoalProposalBuilder::toAffectedItem)
                .collect(Collectors.toList()));
        proposal.setAddedCount(addedEntryCount);
        proposal.setAddedUnitCount(addedUnitCount);
        proposal.setRemovedCount(0);
        proposal.setTargetCountBefore(confirmedTarget == null ? currentCount : confirmedTarget);
        proposal.setTargetCountAfter(targetAfter);
        proposal.setTargetCountOverride(targetCountOverride);
        List<String> labelList = candidateEntryLabels(resolved, majorGroupMode);
        String labels = String.join("、", labelList);
        List<String> conditionParts = Lists.newArrayList();
        if (!scopes.isEmpty()) {
            conditionParts.add("范围：" + scopeLabel(scopes));
        }
        if (!negatives.isEmpty()) {
            conditionParts.add("避开：" + scopeLabel(negatives));
        }
        if (maxTuition != null) {
            conditionParts.add("学费不超过 " + maxTuition + " 元/年");
        }
        String conditions = conditionParts.isEmpty() ? "无额外范围条件" : String.join("；", conditionParts);
        proposal.setSummary("按范围加入 " + formatEntryCount(addedEntryCount, majorGroupMode)
                + (labels.isEmpty() ? "" : "：" + labels)
                + "（" + conditions + "）；总数 " + proposal.getTargetCountBefore() + "→" + targetAfter
                + "；不删除任何现有条目。");
        proposal.setImpact("确认后只加入这些条目，不删除/替换现有志愿；范围/学费条件只用于本次筛选，"
                + "不会改写整个方案。");
        FixProposalActionDTO action = addExactAction(resolved, majorGroupMode, labelList);
        action.setSummary("加入符合范围条件的候选");
        proposal.getActions().add(action);
        populateFillDryRun(proposal, state, currentCount, targetAfter,
                addedUnitCount, addedEntryCount, 0, 0, "已生成加入预览，等待确认后再执行。");
        markReadyIfActionable(proposal);
        return proposal;
    }

    // ── 点名加入（add_units）：精确学校+专业，纯加入、零删除 ──────────────────

    private static final String REASON_ADD_UNITS_NO_PLAN = "add_units_no_plan";
    private static final String REASON_ADD_UNITS_SOURCE_UNAVAILABLE = "add_units_candidate_source_unavailable";
    private static final String REASON_ADD_UNITS_TARGET_NOT_FOUND = "add_units_target_not_found";
    private static final String REASON_ADD_UNITS_TARGET_AMBIGUOUS = "add_units_target_ambiguous";
    private static final String REASON_ADD_UNITS_TARGET_MISMATCH = "add_units_target_mismatch";
    private static final String REASON_ADD_UNITS_TARGET_BANNED = "add_units_target_banned";
    private static final String REASON_ADD_UNITS_STALE_PLAN_ITEM = "add_units_stale_working_plan_item";
    private static final String REASON_ADD_UNITS_COUNT_MISMATCH = "add_units_target_count_mismatch";
    private static final String REASON_ADD_UNITS_TIER_QUOTA = "add_units_tier_quota_unsupported";
    private static final String REASON_ADD_UNITS_DRY_RUN = "add_units_dry_run_failed";
    private static final String REASON_ADD_UNITS_DRY_RUN_UNAVAILABLE = "add_units_dry_run_unavailable";
    private static final String REASON_REPLACE_UNITS_INSUFFICIENT = "replace_units_insufficient_removable";
    private static final String REASON_REMOVE_UNITS_NO_PLAN = "remove_units_no_plan";
    private static final String REASON_REMOVE_UNITS_TARGET_NOT_FOUND = "remove_units_target_not_found";
    private static final String REASON_REMOVE_UNITS_TARGET_AMBIGUOUS = "remove_units_target_ambiguous";
    private static final String REASON_REMOVE_UNITS_TARGET_LOCKED = "remove_units_target_locked";
    private static final String REASON_REMOVE_UNITS_COUNT_MISMATCH = "remove_units_target_count_mismatch";
    private static final String REASON_REMOVE_UNITS_TIER_QUOTA = "remove_units_tier_quota_unsupported";
    private static final String REASON_REMOVE_UNITS_DRY_RUN = "remove_units_dry_run_failed";
    private static final String REASON_REMOVE_UNITS_DRY_RUN_UNAVAILABLE = "remove_units_dry_run_unavailable";
    private static final String REASON_REMOVE_UNITS_WOULD_EMPTY = "remove_units_would_empty_plan";
    private static final String REASON_MOVE_UNITS_NO_ORDERED = "move_units_no_ordered_plan";
    private static final String REASON_MOVE_UNITS_TARGET = "move_units_target_invalid";
    private static final String REASON_MOVE_UNITS_POSITION = "move_units_position_invalid";
    private static final String REASON_MOVE_UNITS_ANCHOR = "move_units_anchor_invalid";

    private static FixProposalDTO buildAddUnitsProposal(PlanningStateDTO state,
                                                        UserGoalFixProposalReq req) {
        List<CandidateItemDTO> pool = candidates(state);
        boolean majorGroupMode = isMajorGroupMode(state);
        boolean replacePolicy = isReplacePolicy(req);
        List<PlanVolunteer> current = currentPlanVolunteers(state, pool);
        if (current.isEmpty()) {
            return buildScopeBlockedProposal(state, req, RepairProposalTaxonomy.Strategy.ADD_UNITS,
                    REASON_ADD_UNITS_NO_PLAN, "当前没有正式方案，先补方案再加入；点名加入只往已有方案里加。");
        }
        if (pool.isEmpty()) {
            return buildScopeBlockedProposal(state, req, RepairProposalTaxonomy.Strategy.ADD_UNITS,
                    REASON_ADD_UNITS_SOURCE_UNAVAILABLE,
                    "当前会话的候选来源不可用（候选池为空或尚未生成），暂时不能核验点名的院校/专业。");
        }
        HardPlanningObjectivesDTO hard = state == null || state.getConstraintState() == null
                ? null : state.getConstraintState().getHardPlanningObjectives();
        if (hard != null && hard.getTierQuotaGoal() != null) {
            return buildScopeBlockedProposal(state, req, RepairProposalTaxonomy.Strategy.ADD_UNITS,
                    REASON_ADD_UNITS_TIER_QUOTA,
                    replacePolicy
                            ? "替换也会改变已确认的冲稳保配额；请先调整配额，再生成替换预览。"
                            : "加入会改变已确认的冲稳保配额；请先调整配额或改用替换动作，不自动改配额。");
        }

        Set<String> currentVolunteerIds = current.stream()
                .map(PlanVolunteer::getVolunteerId)
                .filter(value -> !Strings.isNullOrEmpty(value))
                .collect(Collectors.toCollection(LinkedHashSet::new));
        Set<String> poolVolunteerIds = pool.stream()
                .map(CandidateItemDTO::getVolunteerId)
                .filter(value -> !Strings.isNullOrEmpty(value))
                .collect(Collectors.toCollection(LinkedHashSet::new));
        // 纯加入的前提：当前方案里的每一条仍在有效候选池里；否则 generateOrderedPlan
        // 的 sync 可能把它剔除，和“零删除”冲突。prepare 阶段直接阻断，不等到执行。
        int stalePlanItems = 0;
        for (PlanVolunteer volunteer : current) {
            if (!poolVolunteerIds.contains(volunteer.getVolunteerId())) {
                stalePlanItems++;
            }
        }
        if (stalePlanItems > 0) {
            return buildScopeBlockedProposal(state, req, RepairProposalTaxonomy.Strategy.ADD_UNITS,
                    REASON_ADD_UNITS_STALE_PLAN_ITEM,
                    "当前方案里有 " + stalePlanItems + " 条已不在有效候选池中；先处理这些条目再加入，"
                            + "否则重生成可能删掉它们。");
        }

        Set<String> banned = state.getWorkingPlanState() == null
                ? new LinkedHashSet<String>()
                : new LinkedHashSet<String>(defaultList(state.getWorkingPlanState().getBannedVolunteerIds()));
        List<UserGoalFixProposalReq.ExactTargetDTO> targets = defaultList(req == null ? null : req.getExactTargets());
        if (targets.isEmpty()) {
            return buildScopeBlockedProposal(state, req, RepairProposalTaxonomy.Strategy.ADD_UNITS,
                    REASON_ADD_UNITS_TARGET_NOT_FOUND, "没有收到要点名加入的院校+专业。");
        }
        List<CandidateItemDTO> resolved = Lists.newArrayList();
        Set<String> resolvedIds = new LinkedHashSet<String>();
        int alreadySelected = 0;
        List<String> problemMessages = Lists.newArrayList();
        String problemReason = null;
        for (UserGoalFixProposalReq.ExactTargetDTO target : targets) {
            ExactTargetResolution resolution = resolveExactTarget(pool, currentVolunteerIds, target);
            if (resolution.reason != null && !"already_selected".equals(resolution.reason)) {
                problemReason = resolution.reason;
                problemMessages.add(resolution.message);
                continue;
            }
            if ("already_selected".equals(resolution.reason)) {
                alreadySelected++;
                continue;
            }
            if (resolution.candidate != null && !Strings.isNullOrEmpty(resolution.candidate.getVolunteerId())
                    && resolvedIds.add(resolution.candidate.getVolunteerId())) {
                if (banned.contains(resolution.candidate.getVolunteerId())) {
                    problemReason = REASON_ADD_UNITS_TARGET_BANNED;
                    problemMessages.add(candidateDisplay(resolution.candidate) + " 已被屏蔽，不能加入。");
                } else {
                    resolved.add(resolution.candidate);
                }
            }
        }
        if (problemReason != null) {
            return buildScopeBlockedProposal(state, req, RepairProposalTaxonomy.Strategy.ADD_UNITS,
                    problemReason, String.join("；", problemMessages));
        }
        if (resolved.isEmpty()) {
            FixProposalDTO info = buildUserGoalPreviewBase(state, req,
                    RepairProposalTaxonomy.Strategy.ADD_UNITS, "加入志愿预览");
            info.setStatus(RepairProposalTaxonomy.Status.INFO);
            info.setSummary("点名的条目已经在当前方案中，不需要重复加入。");
            info.setImpact("方案不变；如需调整顺序或替换，请明确新的动作。");
            info.setRequiresConfirmation(false);
            info.setRemovedCount(0);
            info.setAddedCount(0);
            info.setAddedUnitCount(0);
            return info;
        }

        Set<String> currentUnitIds = current.stream()
                .map(UserGoalProposalBuilder::planUnitKey)
                .filter(value -> !Strings.isNullOrEmpty(value))
                .collect(Collectors.toCollection(LinkedHashSet::new));
        int currentCount = majorGroupMode ? currentUnitIds.size() : currentVolunteerIds.size();
        Set<String> addedUnitIds = new LinkedHashSet<String>();
        for (CandidateItemDTO candidate : resolved) {
            String unitId = candidateUnitKey(candidate);
            if (!Strings.isNullOrEmpty(unitId)) {
                addedUnitIds.add(unitId);
            }
        }
        int addedEntryCount = resolved.size();
        int addedUnitCount = addedUnitIds.size();
        // Q14：换入专业若落在已有专业组里，不增加单元数（单元模式的总数口径是单元数）。
        // 纯加入与替换都按“新增单元数”算；addedUnitCount 仅作“涉及多少个组”的展示。
        int newUnitCount = (int) addedUnitIds.stream()
                .filter(unitId -> !currentUnitIds.contains(unitId)).count();
        int addedCountForMode = majorGroupMode ? newUnitCount : addedEntryCount;
        // 替换的移出量同样按“新增单元数”算，否则会把总数压少。
        int replaceCountForMode = majorGroupMode ? newUnitCount : addedEntryCount;
        Integer confirmedTarget = hard == null ? null : hard.getSelectionTargetCount();
        if (confirmedTarget != null && confirmedTarget != currentCount) {
            return buildScopeBlockedProposal(state, req, RepairProposalTaxonomy.Strategy.ADD_UNITS,
                    REASON_ADD_UNITS_COUNT_MISMATCH,
                    "当前方案实际 " + currentCount + (majorGroupMode ? " 个专业组" : " 条")
                            + "，与已确认目标 " + confirmedTarget + " 不一致；请先补齐/调整目标，再加入。");
        }
        ReplaceRemoval removal = null;
        if (replacePolicy) {
            removal = selectReplaceRemovals(current, resolved, majorGroupMode, replaceCountForMode);
            if (removal == null || removal.countInMode(majorGroupMode) < replaceCountForMode) {
                return buildScopeBlockedProposal(state, req, RepairProposalTaxonomy.Strategy.ADD_UNITS,
                        REASON_REPLACE_UNITS_INSUFFICIENT,
                        "当前方案里未锁定/未置顶的可替换" + (majorGroupMode ? "专业组" : "条目")
                                + "不足 " + replaceCountForMode + " 个；请先解锁或减少替换数量。");
            }
        }
        int targetAfter = replacePolicy ? currentCount : currentCount + addedCountForMode;
        Integer targetCountOverride = replacePolicy ? null
                : (confirmedTarget == null ? null : targetAfter);

        AddUnitsDryRun dryRun = replacePolicy
                ? dryRunReplaceUnits(state, current, removal, resolved, targetAfter, majorGroupMode)
                : dryRunAddUnits(state, current, resolved, targetAfter, majorGroupMode, "add");
        if (!dryRun.ok) {
            return buildScopeBlockedProposal(state, req, RepairProposalTaxonomy.Strategy.ADD_UNITS,
                    dryRun.reason, dryRun.message);
        }

        FixProposalDTO proposal = buildUserGoalPreviewBase(state, req,
                RepairProposalTaxonomy.Strategy.ADD_UNITS,
                replacePolicy ? "替换志愿预览" : "加入志愿预览");
        proposal.setStatus(RepairProposalTaxonomy.Status.READY);
        proposal.setRequiresConfirmation(true);
        proposal.setAffectedVolunteerIds(resolved.stream()
                .map(CandidateItemDTO::getVolunteerId)
                .filter(value -> !Strings.isNullOrEmpty(value))
                .distinct().collect(Collectors.toList()));
        proposal.setAffectedUnitIds(Lists.newArrayList(addedUnitIds));
        proposal.setAffectedItems(resolved.stream().map(UserGoalProposalBuilder::toAffectedItem)
                .collect(Collectors.toList()));
        proposal.setAddedCount(addedEntryCount);
        proposal.setAddedUnitCount(addedUnitCount);
        proposal.setRemovedCount(replacePolicy ? removal.countInMode(majorGroupMode) : 0);
        proposal.setTargetCountBefore(confirmedTarget == null ? currentCount : confirmedTarget);
        proposal.setTargetCountAfter(targetAfter);
        proposal.setTargetCountOverride(targetCountOverride);
        List<String> labelList = candidateEntryLabels(resolved, majorGroupMode);
        String labels = String.join("、", labelList);
        if (replacePolicy) {
            List<String> removedLabels = planEntryLabels(removal.volunteers, majorGroupMode);
            String removedText = String.join("、", removedLabels);
            proposal.setSummary("将换出 " + formatEntryCount(removal.countInMode(majorGroupMode), majorGroupMode)
                    + (removedText.isEmpty() ? "" : "：" + removedText)
                    + "，换入 " + formatEntryCount(addedEntryCount, majorGroupMode)
                    + (labels.isEmpty() ? "" : "：" + labels)
                    + "；总数保持 " + targetAfter + "。"
                    + (alreadySelected > 0 ? "另有 " + alreadySelected + " 条已在方案中，不重复加入。" : ""));
            proposal.setImpact("确认后只移出下列条目并加入新条目，其他志愿不动；总数保持不变。");
            proposal.getActions().add(replaceExactAction(
                    resolved, removal, majorGroupMode, labelList, removedLabels));
            populateFillDryRun(proposal, state, currentCount, targetAfter,
                    addedUnitCount, addedEntryCount,
                    removal.unitIds.size(), removal.volunteerIds.size(),
                    "换出 " + formatEntryCount(removal.countInMode(majorGroupMode), majorGroupMode)
                            + "，换入 " + formatEntryCount(addedEntryCount, majorGroupMode) + "；总数不变。");
        } else {
            proposal.setSummary("将加入 " + formatEntryCount(addedEntryCount, majorGroupMode)
                    + (labels.isEmpty() ? "" : "：" + labels)
                    + "；总数 " + proposal.getTargetCountBefore() + "→" + targetAfter
                    + "；不删除任何现有条目。"
                    + (alreadySelected > 0 ? "另有 " + alreadySelected + " 条已在方案中，不重复加入。" : ""));
            proposal.setImpact("确认后只加入这些条目，不删除/替换现有志愿；总数按当前方案实际数量 + 新增数量更新。");
            proposal.getActions().add(addExactAction(resolved, majorGroupMode, labelList));
            populateFillDryRun(proposal, state, currentCount, targetAfter,
                    addedUnitCount, addedEntryCount, 0, 0,
                    "加入 " + formatEntryCount(addedEntryCount, majorGroupMode) + "；零删除。");
        }
        if (dryRun.solverResult != null) {
            attachSolverMetadata(proposal, dryRun.objectiveSet, dryRun.solverResult);
        }
        return proposal;
    }

    private static boolean isReplacePolicy(UserGoalFixProposalReq req) {
        return req != null && "replace".equalsIgnoreCase(
                Strings.nullToEmpty(req.getAddPolicy()).trim());
    }

    /**
     * 替换的移出集合：从方案尾部（低优先）挑未锁定/未置顶的条目，优先同档位。
     * 专业组模式以“组”为原子，组内任一条锁定/置顶则整组不可移出。
     * 返回 null 表示可用条目不足。
     */
    private static ReplaceRemoval selectReplaceRemovals(List<PlanVolunteer> current,
                                                        List<CandidateItemDTO> resolved,
                                                        boolean majorGroupMode,
                                                        int requiredCount) {
        Set<String> addedTiers = defaultList(resolved).stream()
                .map(candidate -> candidate == null ? null : candidate.getTier())
                .filter(value -> !Strings.isNullOrEmpty(value))
                .collect(Collectors.toCollection(LinkedHashSet::new));
        Set<String> addedUnitKeys = defaultList(resolved).stream()
                .map(UserGoalProposalBuilder::candidateUnitKey)
                .filter(value -> !Strings.isNullOrEmpty(value))
                .collect(Collectors.toCollection(LinkedHashSet::new));
        ReplaceRemoval removal = new ReplaceRemoval();
        if (majorGroupMode) {
            Map<String, List<PlanVolunteer>> byUnit = new LinkedHashMap<String, List<PlanVolunteer>>();
            for (PlanVolunteer volunteer : defaultList(current)) {
                String unitId = firstNonEmpty(volunteer.getUnitId(), volunteer.getVolunteerId());
                if (!Strings.isNullOrEmpty(unitId)) {
                    byUnit.computeIfAbsent(unitId, ignored -> Lists.newArrayList()).add(volunteer);
                }
            }
            List<Map.Entry<String, List<PlanVolunteer>>> units =
                    new ArrayList<Map.Entry<String, List<PlanVolunteer>>>(byUnit.entrySet());
            Collections.reverse(units);
            Set<String> chosenUnits = new LinkedHashSet<String>();
            collectReplaceUnits(units, addedTiers, addedUnitKeys, requiredCount, true, chosenUnits);
            if (chosenUnits.size() < requiredCount) {
                collectReplaceUnits(units, addedTiers, addedUnitKeys, requiredCount, false, chosenUnits);
            }
            if (chosenUnits.size() < requiredCount) {
                return null;
            }
            for (Map.Entry<String, List<PlanVolunteer>> entry : units) {
                if (!chosenUnits.contains(entry.getKey())) {
                    continue;
                }
                removal.unitIds.add(entry.getKey());
                for (PlanVolunteer volunteer : entry.getValue()) {
                    removal.volunteers.add(volunteer);
                    if (!Strings.isNullOrEmpty(volunteer.getVolunteerId())) {
                        removal.volunteerIds.add(volunteer.getVolunteerId());
                    }
                }
            }
            return removal;
        }
        List<PlanVolunteer> tail = new ArrayList<PlanVolunteer>(defaultList(current));
        Collections.reverse(tail);
        for (int pass = 0; pass < 2 && removal.volunteerIds.size() < requiredCount; pass++) {
            for (PlanVolunteer volunteer : tail) {
                if (volunteer.isLocked() || volunteer.isPinned()
                        || Strings.isNullOrEmpty(volunteer.getVolunteerId())
                        || removal.volunteerIds.contains(volunteer.getVolunteerId())) {
                    continue;
                }
                String tier = volunteer.getCandidate() == null ? null : volunteer.getCandidate().getTier();
                boolean sameTier = !Strings.isNullOrEmpty(tier) && addedTiers.contains(tier);
                if (pass == 0 && !sameTier) {
                    continue;
                }
                if (pass == 1 && sameTier) {
                    continue;
                }
                removal.volunteers.add(volunteer);
                removal.volunteerIds.add(volunteer.getVolunteerId());
                if (removal.volunteerIds.size() >= requiredCount) {
                    break;
                }
            }
        }
        return removal.volunteerIds.size() < requiredCount ? null : removal;
    }

    private static void collectReplaceUnits(List<Map.Entry<String, List<PlanVolunteer>>> units,
                                            Set<String> addedTiers,
                                            Set<String> addedUnitKeys,
                                            int requiredCount,
                                            boolean sameTierOnly,
                                            Set<String> chosenUnits) {
        for (Map.Entry<String, List<PlanVolunteer>> entry : units) {
            if (chosenUnits.size() >= requiredCount) {
                return;
            }
            if (chosenUnits.contains(entry.getKey()) || entry.getValue().isEmpty()
                    || addedUnitKeys.contains(entry.getKey())) {
                // 整组移出会把即将换入该组的新专业一起删掉；该组不能作为移出对象。
                continue;
            }
            boolean protectedUnit = entry.getValue().stream()
                    .anyMatch(volunteer -> volunteer.isLocked() || volunteer.isPinned());
            if (protectedUnit) {
                continue;
            }
            String tier = entry.getValue().get(0).getCandidate() == null
                    ? null : entry.getValue().get(0).getCandidate().getTier();
            boolean sameTier = !Strings.isNullOrEmpty(tier) && addedTiers.contains(tier);
            if (sameTier != sameTierOnly) {
                continue;
            }
            chosenUnits.add(entry.getKey());
        }
    }

    private static FixProposalActionDTO replaceExactAction(List<CandidateItemDTO> resolved,
                                                           ReplaceRemoval removal,
                                                           boolean majorGroupMode,
                                                           List<String> addedLabels,
                                                           List<String> removedLabels) {
        FixProposalActionDTO action = new FixProposalActionDTO();
        action.setActionType(RepairProposalTaxonomy.ActionType.REPLACE_VOLUNTEERS);
        action.setLevel("volunteer");
        action.setSummary("替换点名的院校+专业");
        List<String> detailLines = Lists.newArrayList();
        if (!removedLabels.isEmpty()) {
            detailLines.add("移出：" + String.join("、", removedLabels));
        }
        if (!addedLabels.isEmpty()) {
            detailLines.add("加入：" + String.join("、", addedLabels));
        }
        action.setDetail(appendEntryPreviewDetail(
                "预计移出 " + formatEntryCount(removal.countInMode(majorGroupMode), majorGroupMode)
                        + "，加入 " + formatEntryCount(resolved.size(), majorGroupMode) + "。",
                detailLines));
        List<String> volunteerIds = resolved.stream().map(CandidateItemDTO::getVolunteerId)
                .filter(value -> !Strings.isNullOrEmpty(value)).distinct().collect(Collectors.toList());
        List<String> unitIds = resolved.stream().map(UserGoalProposalBuilder::candidateUnitKey)
                .filter(value -> !Strings.isNullOrEmpty(value)).distinct().collect(Collectors.toList());
        action.setVolunteerIds(volunteerIds);
        action.setUnitIds(unitIds);
        action.setCandidateVolunteerIds(volunteerIds);
        action.setCandidateUnitIds(unitIds);
        action.setRemoveVolunteerIds(Lists.newArrayList(removal.volunteerIds));
        action.setRemoveUnitIds(Lists.newArrayList(removal.unitIds));
        populateActionTotals(action);
        return action;
    }

    private static final class ReplaceRemoval {
        private final List<PlanVolunteer> volunteers = Lists.newArrayList();
        private final Set<String> volunteerIds = new LinkedHashSet<String>();
        private final Set<String> unitIds = new LinkedHashSet<String>();

        private int countInMode(boolean majorGroupMode) {
            return majorGroupMode ? unitIds.size() : volunteerIds.size();
        }
    }

    // ── 移除（remove_units）：精确移除集合，其他条目不动 ─────────────────────

    private static FixProposalDTO buildRemoveUnitsProposal(PlanningStateDTO state,
                                                           UserGoalFixProposalReq req) {
        boolean unitMode = isMajorGroupMode(state);
        List<PlanVolunteer> current = currentPlanVolunteers(state, candidates(state));
        if (current.isEmpty()) {
            return buildScopeBlockedProposal(state, req, RepairProposalTaxonomy.Strategy.REMOVE_UNITS,
                    REASON_REMOVE_UNITS_NO_PLAN, "当前没有正式方案，没有可移除的条目。");
        }
        HardPlanningObjectivesDTO hard = state == null || state.getConstraintState() == null
                ? null : state.getConstraintState().getHardPlanningObjectives();
        if (hard != null && hard.getTierQuotaGoal() != null) {
            return buildScopeBlockedProposal(state, req, RepairProposalTaxonomy.Strategy.REMOVE_UNITS,
                    REASON_REMOVE_UNITS_TIER_QUOTA,
                    "移除会改变已确认的冲稳保配额；请先调整配额，再生成移除预览。");
        }
        Set<String> currentVolunteerIds = current.stream().map(PlanVolunteer::getVolunteerId)
                .filter(value -> !Strings.isNullOrEmpty(value))
                .collect(Collectors.toCollection(LinkedHashSet::new));
        Set<String> currentUnitIds = current.stream().map(UserGoalProposalBuilder::planUnitKey)
                .filter(value -> !Strings.isNullOrEmpty(value))
                .collect(Collectors.toCollection(LinkedHashSet::new));
        int currentCount = unitMode ? currentUnitIds.size() : currentVolunteerIds.size();
        List<UserGoalFixProposalReq.ExactTargetDTO> targets =
                defaultList(req == null ? null : req.getExactTargets());
        if (targets.isEmpty()) {
            return buildScopeBlockedProposal(state, req, RepairProposalTaxonomy.Strategy.REMOVE_UNITS,
                    REASON_REMOVE_UNITS_TARGET_NOT_FOUND, "没有收到要移除的院校+专业。");
        }
        ReplaceRemoval removal = new ReplaceRemoval();
        String problemReason = null;
        String problemMessage = null;
        for (UserGoalFixProposalReq.ExactTargetDTO target : targets) {
            PlanTargetResolution resolution = resolvePlanTarget(current, target);
            if (resolution.reason != null) {
                problemReason = resolution.reason;
                problemMessage = resolution.message;
                break;
            }
            PlanVolunteer matched = resolution.volunteer;
            if (unitMode) {
                String unitId = planUnitKey(matched);
                if (Strings.isNullOrEmpty(unitId)) {
                    problemReason = REASON_REMOVE_UNITS_TARGET_NOT_FOUND;
                    problemMessage = "这条志愿没有可识别的专业组，暂时不能整组移除。";
                    break;
                }
                if (!removal.unitIds.add(unitId)) {
                    continue;
                }
                for (PlanVolunteer member : current) {
                    if (!unitId.equals(planUnitKey(member))) {
                        continue;
                    }
                    if (member.isLocked()) {
                        problemReason = REASON_REMOVE_UNITS_TARGET_LOCKED;
                        problemMessage = "“" + member.getSchoolName() + "·" + member.getMajorName()
                                + "”已锁定；请先解锁再移除。";
                        break;
                    }
                    removal.volunteers.add(member);
                    if (!Strings.isNullOrEmpty(member.getVolunteerId())) {
                        removal.volunteerIds.add(member.getVolunteerId());
                    }
                }
                if (problemReason != null) {
                    break;
                }
            } else {
                if (matched.isLocked()) {
                    problemReason = REASON_REMOVE_UNITS_TARGET_LOCKED;
                    problemMessage = "“" + matched.getSchoolName() + "·" + matched.getMajorName()
                            + "”已锁定；请先解锁再移除。";
                    break;
                }
                if (removal.volunteerIds.add(matched.getVolunteerId())) {
                    removal.volunteers.add(matched);
                }
            }
        }
        if (problemReason != null) {
            return buildScopeBlockedProposal(state, req, RepairProposalTaxonomy.Strategy.REMOVE_UNITS,
                    problemReason, problemMessage);
        }
        int removedCountMode = removal.countInMode(unitMode);
        if (removedCountMode <= 0) {
            return buildScopeBlockedProposal(state, req, RepairProposalTaxonomy.Strategy.REMOVE_UNITS,
                    REASON_REMOVE_UNITS_TARGET_NOT_FOUND, "没有解析出可移除的条目。");
        }
        int targetAfter = currentCount - removedCountMode;
        if (targetAfter <= 0) {
            return buildScopeBlockedProposal(state, req, RepairProposalTaxonomy.Strategy.REMOVE_UNITS,
                    REASON_REMOVE_UNITS_WOULD_EMPTY, "这次会移除全部方案条目；请保留至少一条，或改用重新生成。");
        }
        Integer confirmedTarget = hard == null ? null : hard.getSelectionTargetCount();
        if (confirmedTarget != null && confirmedTarget != currentCount) {
            return buildScopeBlockedProposal(state, req, RepairProposalTaxonomy.Strategy.REMOVE_UNITS,
                    REASON_REMOVE_UNITS_COUNT_MISMATCH,
                    "当前方案实际 " + currentCount + (unitMode ? " 个专业组" : " 条")
                            + "，与已确认目标 " + confirmedTarget + " 不一致；请先补齐/调整目标，再移除。");
        }
        Integer targetCountOverride = confirmedTarget == null ? null : targetAfter;
        AddUnitsDryRun dryRun = dryRunRemoveUnits(state, current, removal, targetAfter, unitMode);
        if (!dryRun.ok) {
            return buildScopeBlockedProposal(state, req, RepairProposalTaxonomy.Strategy.REMOVE_UNITS,
                    dryRun.reason, dryRun.message);
        }

        FixProposalDTO proposal = buildUserGoalPreviewBase(state, req,
                RepairProposalTaxonomy.Strategy.REMOVE_UNITS, "移除志愿预览");
        proposal.setStatus(RepairProposalTaxonomy.Status.READY);
        proposal.setRequiresConfirmation(true);
        proposal.setAffectedVolunteerIds(Lists.newArrayList(removal.volunteerIds));
        proposal.setAffectedUnitIds(Lists.newArrayList(removal.unitIds));
        proposal.setAffectedItems(removal.volunteers.stream()
                .map(UserGoalProposalBuilder::toAffectedItem).collect(Collectors.toList()));
        proposal.setAddedCount(0);
        proposal.setAddedUnitCount(0);
        proposal.setRemovedCount(removedCountMode);
        proposal.setTargetCountBefore(confirmedTarget == null ? currentCount : confirmedTarget);
        proposal.setTargetCountAfter(targetAfter);
        proposal.setTargetCountOverride(targetCountOverride);
        List<String> labels = planEntryLabels(removal.volunteers, unitMode);
        proposal.setSummary("将移除 " + formatEntryCount(removedCountMode, unitMode)
                + (labels.isEmpty() ? "" : "：" + String.join("、", labels))
                + "；总数 " + proposal.getTargetCountBefore() + "→" + targetAfter
                + "；其他条目不动。");
        proposal.setImpact("确认后只移出这些条目，其他志愿不动；总数按移除后的实际数量更新。");
        proposal.getActions().add(removeExactAction(removal, unitMode, labels));
        populateFillDryRun(proposal, state, currentCount, targetAfter,
                0, 0, removal.unitIds.size(), removal.volunteerIds.size(),
                "移除 " + formatEntryCount(removedCountMode, unitMode) + "；其他条目不动。");
        if (dryRun.solverResult != null) {
            attachSolverMetadata(proposal, dryRun.objectiveSet, dryRun.solverResult);
        }
        return proposal;
    }

    private static FixProposalActionDTO removeExactAction(ReplaceRemoval removal,
                                                          boolean unitMode,
                                                          List<String> labels) {
        FixProposalActionDTO action = new FixProposalActionDTO();
        action.setActionType(RepairProposalTaxonomy.ActionType.REMOVE_VOLUNTEERS);
        action.setLevel("volunteer");
        action.setSummary("移除点名的院校+专业");
        action.setDetail(appendEntryPreviewDetail(
                "预计移出 " + formatEntryCount(removal.countInMode(unitMode), unitMode) + "。", labels));
        action.setVolunteerIds(Lists.newArrayList(removal.volunteerIds));
        action.setUnitIds(Lists.newArrayList(removal.unitIds));
        action.setRemoveVolunteerIds(Lists.newArrayList(removal.volunteerIds));
        action.setRemoveUnitIds(Lists.newArrayList(removal.unitIds));
        action.setCandidateVolunteerIds(Lists.newArrayList());
        action.setCandidateUnitIds(Lists.newArrayList());
        populateActionTotals(action);
        return action;
    }

    private static AddUnitsDryRun dryRunRemoveUnits(PlanningStateDTO state,
                                                    List<PlanVolunteer> current,
                                                    ReplaceRemoval removal,
                                                    int targetAfter,
                                                    boolean unitMode) {
        AddUnitsDryRun result = new AddUnitsDryRun();
        if (!CanonicalPlanningRuntime.hasSelectionObjectives(state)) {
            result.ok = true;
            return result;
        }
        try {
            CanonicalPlanningObjectiveSetDTO objectiveSet = PlanningObjectiveCompiler.compileConfirmed(state);
            CanonicalPlanningObjectiveSetDTO solverObjectiveSet = copyObjectiveSet(objectiveSet);
            solverObjectiveSet.setTargetCount(targetAfter);
            FillCurrentProjection projection = new FillCurrentProjection();
            projection.removeUnitIds.addAll(removal.unitIds);
            projection.removeVolunteerIds.addAll(removal.volunteerIds);
            List<CoverageEntity> retained = buildRetainedCoverageEntities(current, projection, unitMode);
            MutationPolicyDTO policy = new MutationPolicyDTO();
            policy.setAction("REMOVE");
            policy.setLockExisting(true);
            policy.setCountAsChurn(false);
            policy.getForcedRemoveEntityIds().addAll(unitMode
                    ? removal.unitIds : removal.volunteerIds);
            CandidateSnapshotDTO snapshot = CandidateSnapshotBuilder.build(
                    state, snapshotCandidates(state, Lists.<CandidateItemDTO>newArrayList()),
                    CandidateSnapshotBuilder.CurrentSource.ORDERED_FIRST);
            PlanningObjectiveCompiler.enrichV2(state, solverObjectiveSet, policy);
            PlanSolverResultDTO solved = STAGED_SOLVER.solve(
                    snapshot, solverObjectiveSet, policy).solverResult;
            LOG.info("staged dry-run remove: session={} status={} selected={} remove={}",
                    state.getSessionId(), solved.getStatus(),
                    defaultList(solved.getSelectedEntityIds()).size(),
                    defaultList(solved.getRemoveEntityIds()).size());
            result.objectiveSet = objectiveSet;
            result.solverResult = solved;
            if (RepairProposalTaxonomy.Status.BLOCKED.equals(solved.getStatus())) {
                PlanSolverResultDTO.DiagnosticDTO diagnostic = solved.getDiagnostics().isEmpty()
                        ? null : solved.getDiagnostics().get(0);
                result.ok = false;
                result.reason = REASON_REMOVE_UNITS_DRY_RUN;
                result.message = diagnostic == null || Strings.isNullOrEmpty(diagnostic.getMessage())
                        ? "移除后的方案无法同时满足已确认目标/约束，已在预览阶段阻断。"
                        : diagnostic.getMessage();
                return result;
            }
            Set<String> selected = new LinkedHashSet<String>(defaultList(solved.getSelectedEntityIds()));
            Set<String> retainedIds = retained.stream().map(entity -> entity.entityId(unitMode))
                    .filter(value -> !Strings.isNullOrEmpty(value)).collect(Collectors.toCollection(LinkedHashSet::new));
            if (!selected.containsAll(retainedIds)) {
                result.ok = false;
                result.reason = REASON_REMOVE_UNITS_DRY_RUN;
                result.message = "移除后的求解结果会顺带删掉未确认的条目，已在预览阶段阻断。";
                return result;
            }
            Set<String> plannedRemoved = unitMode
                    ? new LinkedHashSet<String>(removal.unitIds)
                    : new LinkedHashSet<String>(removal.volunteerIds);
            if (selected.stream().anyMatch(plannedRemoved::contains)) {
                result.ok = false;
                result.reason = REASON_REMOVE_UNITS_DRY_RUN;
                result.message = "移除后的求解结果仍会保留这次要移出的条目，已在预览阶段阻断。";
                return result;
            }
            if (selected.size() != targetAfter) {
                result.ok = false;
                result.reason = REASON_REMOVE_UNITS_DRY_RUN;
                result.message = "移除后的求解数量与目标 " + targetAfter + " 不一致，已在预览阶段阻断。";
                return result;
            }
            result.ok = true;
            return result;
        } catch (Exception ex) {
            result.ok = false;
            result.reason = REASON_REMOVE_UNITS_DRY_RUN_UNAVAILABLE;
            result.message = "当前环境无法完成移除前的只读校验（dry-run），为避免确认后失败，本次不生成可确认卡。";
            return result;
        }
    }

    // ── 移动（move_units）：只改单条/单组位置，集合不变 ───────────────────────

    private static FixProposalDTO buildMoveUnitsProposal(PlanningStateDTO state,
                                                         UserGoalFixProposalReq req) {
        boolean unitMode = isMajorGroupMode(state);
        List<PlanVolunteer> current = currentPlanVolunteers(state, candidates(state));
        List<String> sequence = orderedSequence(state, unitMode);
        if (current.isEmpty() || sequence.isEmpty()) {
            return buildScopeBlockedProposal(state, req, RepairProposalTaxonomy.Strategy.MOVE_UNITS,
                    REASON_MOVE_UNITS_NO_ORDERED, "当前还没有正式排序方案；先排出一版 ordered 方案，再调整顺序。");
        }
        List<UserGoalFixProposalReq.ExactTargetDTO> targets =
                defaultList(req == null ? null : req.getExactTargets());
        if (targets.size() != 1) {
            return buildScopeBlockedProposal(state, req, RepairProposalTaxonomy.Strategy.MOVE_UNITS,
                    REASON_MOVE_UNITS_TARGET, "一次只能移动一条志愿（或一个专业组）；请指定唯一目标。");
        }
        PlanTargetResolution targetResolution = resolvePlanTarget(current, targets.get(0));
        if (targetResolution.reason != null) {
            return buildScopeBlockedProposal(state, req, RepairProposalTaxonomy.Strategy.MOVE_UNITS,
                    REASON_MOVE_UNITS_TARGET, targetResolution.message);
        }
        PlanVolunteer target = targetResolution.volunteer;
        String targetKey = unitMode ? planUnitKey(target) : target.getVolunteerId();
        if (Strings.isNullOrEmpty(targetKey)) {
            return buildScopeBlockedProposal(state, req, RepairProposalTaxonomy.Strategy.MOVE_UNITS,
                    REASON_MOVE_UNITS_TARGET, "这条志愿没有可识别的移动单元。");
        }
        int fromIndex = sequence.indexOf(targetKey);
        if (fromIndex < 0) {
            return buildScopeBlockedProposal(state, req, RepairProposalTaxonomy.Strategy.MOVE_UNITS,
                    REASON_MOVE_UNITS_NO_ORDERED, "目标不在当前 ordered 方案中，请先重生成正式方案。");
        }
        String position = normalizeMovePosition(req == null ? null : req.getMovePosition());
        if (position == null) {
            return buildScopeBlockedProposal(state, req, RepairProposalTaxonomy.Strategy.MOVE_UNITS,
                    REASON_MOVE_UNITS_POSITION, "请说明要移到哪里（置顶 / 置底 / 某条之前 / 某条之后）。");
        }
        PlanVolunteer anchor = null;
        if ("before".equals(position) || "after".equals(position)) {
            if (req == null || req.getMoveAnchor() == null) {
                return buildScopeBlockedProposal(state, req, RepairProposalTaxonomy.Strategy.MOVE_UNITS,
                        REASON_MOVE_UNITS_ANCHOR, "移到某条之前/之后需要给出锚点条目。");
            }
            PlanTargetResolution anchorResolution = resolvePlanTarget(current, req.getMoveAnchor());
            if (anchorResolution.reason != null) {
                return buildScopeBlockedProposal(state, req, RepairProposalTaxonomy.Strategy.MOVE_UNITS,
                        REASON_MOVE_UNITS_ANCHOR, anchorResolution.message);
            }
            anchor = anchorResolution.volunteer;
        }
        List<String> reduced = new ArrayList<String>(sequence);
        reduced.remove(targetKey);
        int insertIndex;
        if ("top".equals(position)) {
            insertIndex = 0;
        } else if ("bottom".equals(position)) {
            insertIndex = reduced.size();
        } else {
            String anchorKey = unitMode ? planUnitKey(anchor) : anchor.getVolunteerId();
            int anchorIndex = reduced.indexOf(anchorKey);
            if (anchorIndex < 0) {
                return buildScopeBlockedProposal(state, req, RepairProposalTaxonomy.Strategy.MOVE_UNITS,
                        REASON_MOVE_UNITS_ANCHOR, "锚点不在当前 ordered 方案中，请先重生成正式方案。");
            }
            insertIndex = "before".equals(position) ? anchorIndex : anchorIndex + 1;
        }
        int toPosition = insertIndex + 1;
        int fromPosition = fromIndex + 1;
        if (toPosition == fromPosition) {
            FixProposalDTO info = buildUserGoalPreviewBase(state, req,
                    RepairProposalTaxonomy.Strategy.MOVE_UNITS, "移动志愿预览");
            info.setStatus(RepairProposalTaxonomy.Status.INFO);
            info.setSummary("这条志愿已经在目标位置，不需要移动。");
            info.setImpact("方案不变。");
            info.setRequiresConfirmation(false);
            info.setRemovedCount(0);
            info.setAddedCount(0);
            info.setAddedUnitCount(0);
            return info;
        }

        List<String> labels = planEntryLabels(Lists.newArrayList(target), unitMode);
        String label = labels.isEmpty() ? "目标志愿" : labels.get(0);
        FixProposalDTO proposal = buildUserGoalPreviewBase(state, req,
                RepairProposalTaxonomy.Strategy.MOVE_UNITS, "移动志愿预览");
        proposal.setStatus(RepairProposalTaxonomy.Status.READY);
        proposal.setRequiresConfirmation(true);
        proposal.setAffectedVolunteerIds(unitMode
                ? current.stream().filter(member -> targetKey.equals(planUnitKey(member)))
                .map(PlanVolunteer::getVolunteerId).filter(value -> !Strings.isNullOrEmpty(value))
                .collect(Collectors.toList())
                : Lists.newArrayList(target.getVolunteerId()));
        proposal.setAffectedUnitIds(unitMode ? Lists.newArrayList(targetKey) : Lists.newArrayList());
        proposal.setAffectedItems(Lists.newArrayList(toAffectedItem(target)));
        proposal.setAddedCount(0);
        proposal.setAddedUnitCount(0);
        proposal.setRemovedCount(0);
        int currentCount = sequence.size();
        proposal.setTargetCountBefore(currentCount);
        proposal.setTargetCountAfter(currentCount);
        proposal.setMoveTargetVolunteerId(unitMode ? null : target.getVolunteerId());
        proposal.setMoveTargetUnitId(unitMode ? targetKey : null);
        proposal.setMoveFromPosition(fromPosition);
        proposal.setMoveToPosition(toPosition);
        proposal.setSummary("将「" + label + "」从第 " + fromPosition + " 位移到第 "
                + toPosition + " 位；其他条目顺序不变。");
        proposal.setImpact("确认后只调整这一条的位置，不增删任何志愿。");
        proposal.getActions().add(moveExactAction(target, unitMode, fromPosition, toPosition, label));
        populateFillDryRun(proposal, state, currentCount, currentCount, 0, 0, 0, 0,
                "仅调整顺序；条目集合不变。");
        return proposal;
    }

    private static FixProposalActionDTO moveExactAction(PlanVolunteer target,
                                                        boolean unitMode,
                                                        int fromPosition,
                                                        int toPosition,
                                                        String label) {
        FixProposalActionDTO action = new FixProposalActionDTO();
        action.setActionType(RepairProposalTaxonomy.ActionType.REORDER_VOLUNTEERS);
        action.setLevel("volunteer");
        action.setSummary("调整志愿顺序");
        action.setDetail("将「" + label + "」从第 " + fromPosition + " 位移到第 " + toPosition + " 位。");
        List<String> volunteerIds = unitMode ? Lists.newArrayList() : Lists.newArrayList(target.getVolunteerId());
        List<String> unitIds = unitMode ? Lists.newArrayList(planUnitKey(target)) : Lists.newArrayList();
        action.setVolunteerIds(volunteerIds);
        action.setUnitIds(unitIds);
        action.setCandidateVolunteerIds(Lists.newArrayList());
        action.setCandidateUnitIds(Lists.newArrayList());
        populateActionTotals(action);
        return action;
    }

    private static String normalizeMovePosition(String value) {
        String text = Strings.nullToEmpty(value).trim().toLowerCase(Locale.ROOT);
        if ("top".equals(text) || "first".equals(text) || "start".equals(text)) {
            return "top";
        }
        if ("bottom".equals(text) || "last".equals(text) || "end".equals(text)) {
            return "bottom";
        }
        if ("before".equals(text)) {
            return "before";
        }
        if ("after".equals(text)) {
            return "after";
        }
        return null;
    }

    private static List<String> orderedSequence(PlanningStateDTO state, boolean unitMode) {
        List<String> result = Lists.newArrayList();
        OrderedPlanStateDTO ordered = state == null ? null : state.getOrderedPlanState();
        if (ordered == null) {
            return result;
        }
        if (unitMode) {
            for (OrderedUnitDTO unit : defaultList(ordered.getUnits())) {
                if (unit != null && !Strings.isNullOrEmpty(unit.getUnitId())
                        && !result.contains(unit.getUnitId())) {
                    result.add(unit.getUnitId());
                }
            }
            if (!result.isEmpty()) {
                return result;
            }
            List<CandidateItemDTO> pool = candidates(state);
            for (OrderedItemDTO item : defaultList(ordered.getItems())) {
                String unitId = item == null ? null
                        : RepairCandidateSelector.resolveUnitId(item.getVolunteerId(), pool);
                if (!Strings.isNullOrEmpty(unitId) && !result.contains(unitId)) {
                    result.add(unitId);
                }
            }
            return result;
        }
        for (OrderedItemDTO item : defaultList(ordered.getItems())) {
            if (item != null && !Strings.isNullOrEmpty(item.getVolunteerId())
                    && !result.contains(item.getVolunteerId())) {
                result.add(item.getVolunteerId());
            }
        }
        return result;
    }

    private static PlanTargetResolution resolvePlanTarget(List<PlanVolunteer> current,
                                                          UserGoalFixProposalReq.ExactTargetDTO target) {
        PlanTargetResolution result = new PlanTargetResolution();
        if (target == null) {
            result.reason = REASON_REMOVE_UNITS_TARGET_NOT_FOUND;
            result.message = "缺少目标志愿。";
            return result;
        }
        String targetId = normalizeText(target.getVolunteerId());
        if (!Strings.isNullOrEmpty(targetId)) {
            for (PlanVolunteer volunteer : defaultList(current)) {
                if (!targetId.equals(normalizeText(volunteer.getVolunteerId()))) {
                    continue;
                }
                String targetSchool = normalizeText(target.getSchoolName());
                String targetMajor = normalizeText(target.getMajorName());
                if ((!targetSchool.isEmpty() && !planSchoolMatches(volunteer, targetSchool))
                        || (!targetMajor.isEmpty()
                        && !targetMajor.equals(normalizeText(volunteer.getMajorName())))) {
                    result.reason = REASON_REMOVE_UNITS_TARGET_NOT_FOUND;
                    result.message = "名称与志愿 ID 对应的对象不一致；请重新从方案里选择。";
                    return result;
                }
                result.volunteer = volunteer;
                return result;
            }
            result.reason = REASON_REMOVE_UNITS_TARGET_NOT_FOUND;
            result.message = "当前方案里没有这个志愿：" + targetId;
            return result;
        }
        String targetSchool = normalizeText(target.getSchoolName());
        String targetMajor = normalizeText(target.getMajorName());
        if (targetSchool.isEmpty() || targetMajor.isEmpty()) {
            result.reason = REASON_REMOVE_UNITS_TARGET_NOT_FOUND;
            result.message = "请同时给出学校名和专业名（或志愿 ID）。";
            return result;
        }
        List<PlanVolunteer> exact = defaultList(current).stream()
                .filter(volunteer -> planSchoolMatches(volunteer, targetSchool)
                        && targetMajor.equals(normalizeText(volunteer.getMajorName())))
                .collect(Collectors.toList());
        if (exact.isEmpty()) {
            List<PlanVolunteer> loose = defaultList(current).stream()
                    .filter(volunteer -> planSchoolMatchesLoose(volunteer, targetSchool)
                            && containsLoose(volunteer.getMajorName(), targetMajor))
                    .collect(Collectors.toList());
            if (loose.size() == 1) {
                exact = loose;
            } else if (loose.size() > 1) {
                result.reason = REASON_REMOVE_UNITS_TARGET_AMBIGUOUS;
                result.message = "“" + target.getSchoolName() + "·" + target.getMajorName()
                        + "”在当前方案里匹配到多条，请写清具体专业/方向。";
                return result;
            }
        }
        if (exact.isEmpty()) {
            result.reason = REASON_REMOVE_UNITS_TARGET_NOT_FOUND;
            result.message = "当前方案里没有“" + target.getSchoolName() + "·" + target.getMajorName() + "”。";
            return result;
        }
        if (exact.size() > 1) {
            result.reason = REASON_REMOVE_UNITS_TARGET_AMBIGUOUS;
            result.message = "“" + target.getSchoolName() + "·" + target.getMajorName()
                    + "”在当前方案里匹配到多条，请写清具体专业/方向。";
            return result;
        }
        result.volunteer = exact.get(0);
        return result;
    }

    private static boolean planSchoolMatches(PlanVolunteer volunteer, String normalizedTarget) {
        return volunteer != null && normalizedTarget.equals(normalizeText(volunteer.getSchoolName()));
    }

    private static boolean planSchoolMatchesLoose(PlanVolunteer volunteer, String target) {
        return volunteer != null && (containsLoose(volunteer.getSchoolName(), target)
                || containsLoose(target, volunteer.getSchoolName()));
    }

    private static FixProposalAffectedItemDTO toAffectedItem(PlanVolunteer volunteer) {
        FixProposalAffectedItemDTO item = new FixProposalAffectedItemDTO();
        if (volunteer == null) {
            return item;
        }
        item.setVolunteerId(volunteer.getVolunteerId());
        item.setUnitId(volunteer.getUnitId());
        item.setSchoolName(volunteer.getSchoolName());
        item.setMajorName(volunteer.getMajorName());
        CandidateItemDTO candidate = volunteer.getCandidate();
        if (candidate != null) {
            item.setTier(candidate.getTier());
            item.setPlanNum(candidate.getPlanNum());
            item.setTuitionPerYear(candidate.getTuitionPerYear());
        }
        return item;
    }

    private static final class PlanTargetResolution {
        private PlanVolunteer volunteer;
        private String reason;
        private String message;
    }

    private static FixProposalActionDTO addExactAction(List<CandidateItemDTO> resolved,
                                                       boolean majorGroupMode,
                                                       List<String> labels) {
        FixProposalActionDTO action = new FixProposalActionDTO();
        action.setActionType(RepairProposalTaxonomy.ActionType.ADD_VOLUNTEERS);
        action.setLevel("volunteer");
        action.setSummary("加入点名的院校+专业");
        action.setDetail(appendEntryPreviewDetail(
                "预计加入 " + formatEntryCount(resolved.size(), majorGroupMode) + "。", labels));
        List<String> volunteerIds = resolved.stream().map(CandidateItemDTO::getVolunteerId)
                .filter(value -> !Strings.isNullOrEmpty(value)).distinct().collect(Collectors.toList());
        List<String> unitIds = resolved.stream().map(UserGoalProposalBuilder::candidateUnitKey)
                .filter(value -> !Strings.isNullOrEmpty(value)).distinct().collect(Collectors.toList());
        action.setVolunteerIds(volunteerIds);
        action.setUnitIds(unitIds);
        action.setCandidateVolunteerIds(volunteerIds);
        action.setCandidateUnitIds(unitIds);
        action.setRemoveVolunteerIds(Lists.newArrayList());
        action.setRemoveUnitIds(Lists.newArrayList());
        populateActionTotals(action);
        return action;
    }

    private static FixProposalAffectedItemDTO toAffectedItem(CandidateItemDTO candidate) {
        FixProposalAffectedItemDTO item = new FixProposalAffectedItemDTO();
        item.setVolunteerId(candidate == null ? null : candidate.getVolunteerId());
        item.setUnitId(candidate == null ? null : candidateUnitKey(candidate));
        item.setSchoolName(candidate == null ? null : firstNonEmpty(
                candidate.getDisplaySchoolName(), candidate.getSchoolName()));
        item.setMajorName(candidate == null ? null : candidate.getMajorName());
        item.setTier(candidate == null ? null : candidate.getTier());
        item.setPlanNum(candidate == null ? null : candidate.getPlanNum());
        item.setTuitionPerYear(candidate == null ? null : candidate.getTuitionPerYear());
        return item;
    }

    private static String candidateDisplay(CandidateItemDTO candidate) {
        if (candidate == null) {
            return "该目标";
        }
        return firstNonEmpty(candidate.getDisplaySchoolName(), candidate.getSchoolName(), "")
                + "·" + Strings.nullToEmpty(candidate.getMajorName()).trim();
    }

    private static ExactTargetResolution resolveExactTarget(List<CandidateItemDTO> pool,
                                                            Set<String> currentVolunteerIds,
                                                            UserGoalFixProposalReq.ExactTargetDTO target) {
        ExactTargetResolution result = new ExactTargetResolution();
        String targetId = normalizeText(target == null ? null : target.getVolunteerId());
        String targetSchool = normalizeText(target == null ? null : target.getSchoolName());
        String targetMajor = normalizeText(target == null ? null : target.getMajorName());
        if (!Strings.isNullOrEmpty(targetId)) {
            CandidateItemDTO byId = pool.stream()
                    .filter(candidate -> targetId.equals(normalizeText(candidate.getVolunteerId())))
                    .findFirst().orElse(null);
            if (byId == null) {
                result.reason = REASON_ADD_UNITS_TARGET_NOT_FOUND;
                result.message = "候选池里没有找到这个志愿 ID：" + targetId;
                return result;
            }
            if (!targetSchool.isEmpty() && !targetMajor.isEmpty()
                    && !(schoolNameMatches(byId, targetSchool) && targetMajor.equals(normalizeText(byId.getMajorName())))) {
                result.reason = REASON_ADD_UNITS_TARGET_MISMATCH;
                result.message = "名称与志愿 ID 对应的对象不一致；请重新从候选里选择：" + targetId;
                return result;
            }
            result.candidate = byId;
            if (currentVolunteerIds.contains(byId.getVolunteerId())) {
                result.reason = "already_selected";
            }
            return result;
        }
        if (targetSchool.isEmpty() || targetMajor.isEmpty()) {
            result.reason = REASON_ADD_UNITS_TARGET_NOT_FOUND;
            result.message = "点名加入需要同时给出学校名和专业名（或志愿 ID）。";
            return result;
        }
        List<CandidateItemDTO> exact = pool.stream()
                .filter(candidate -> schoolNameMatches(candidate, targetSchool)
                        && targetMajor.equals(normalizeText(candidate.getMajorName())))
                .collect(Collectors.toList());
        if (exact.isEmpty()) {
            List<CandidateItemDTO> loose = pool.stream()
                    .filter(candidate -> containsLoose(candidate.getMajorName(), targetMajor)
                            && (containsLoose(candidate.getSchoolName(), targetSchool)
                            || containsLoose(candidate.getDisplaySchoolName(), targetSchool)))
                    .collect(Collectors.toList());
            if (loose.size() == 1) {
                exact = loose;
            } else if (loose.size() > 1) {
                result.reason = REASON_ADD_UNITS_TARGET_AMBIGUOUS;
                result.message = "“" + target.getSchoolName() + "·" + target.getMajorName()
                        + "”匹配到多个候选：" + loose.stream().limit(5)
                        .map(UserGoalProposalBuilder::candidateDisplay).collect(Collectors.joining("、"))
                        + "；请写清具体专业（含方向/校区）。";
                return result;
            }
        }
        if (exact.isEmpty()) {
            result.reason = REASON_ADD_UNITS_TARGET_NOT_FOUND;
            result.message = "候选池里没有找到“" + target.getSchoolName() + "·" + target.getMajorName() + "”。";
            return result;
        }
        Set<String> ids = exact.stream().map(CandidateItemDTO::getVolunteerId)
                .filter(value -> !Strings.isNullOrEmpty(value)).collect(Collectors.toCollection(LinkedHashSet::new));
        if (exact.size() > 1 || ids.size() > 1) {
            result.reason = REASON_ADD_UNITS_TARGET_AMBIGUOUS;
            result.message = "“" + target.getSchoolName() + "·" + target.getMajorName()
                    + "”匹配到多个候选：" + exact.stream().limit(5)
                    .map(UserGoalProposalBuilder::candidateDisplay).collect(Collectors.joining("、"))
                    + "；请写清具体专业（含方向/校区）。";
            return result;
        }
        result.candidate = exact.get(0);
        if (currentVolunteerIds.contains(result.candidate.getVolunteerId())) {
            result.reason = "already_selected";
        }
        return result;
    }

    private static boolean schoolNameMatches(CandidateItemDTO candidate, String normalizedTarget) {
        return normalizedTarget.equals(normalizeText(candidate.getSchoolName()))
                || normalizedTarget.equals(normalizeText(candidate.getDisplaySchoolName()));
    }

    private static AddUnitsDryRun dryRunAddUnits(PlanningStateDTO state,
                                                 List<PlanVolunteer> current,
                                                 List<CandidateItemDTO> resolved,
                                                 int targetAfter,
                                                 boolean unitMode,
                                                 String solverPath) {
        AddUnitsDryRun result = new AddUnitsDryRun();
        if (!CanonicalPlanningRuntime.hasSelectionObjectives(state)) {
            result.ok = true;
            return result;
        }
        try {
            CanonicalPlanningObjectiveSetDTO objectiveSet = PlanningObjectiveCompiler.compileConfirmed(state);
            CanonicalPlanningObjectiveSetDTO solverObjectiveSet = copyObjectiveSet(objectiveSet);
            solverObjectiveSet.setTargetCount(targetAfter);
            List<CoverageEntity> retained = buildRetainedCoverageEntities(
                    current, new FillCurrentProjection(), unitMode);
            List<FillOption> available = excludeRetainedOptions(
                    buildAddFillOptions(resolved, unitMode), retained, unitMode);
            MutationPolicyDTO policy = new MutationPolicyDTO();
            policy.setAction("ADD");
            policy.setLockExisting(true);
            policy.setCountAsChurn(false);
            policy.setRequireCompensationSafe("scope".equals(solverPath));
            for (FillOption option : available) {
                String entityId = option.entityId(unitMode);
                if (!Strings.isNullOrEmpty(entityId)) {
                    policy.getFrozenRequiredEntityIds().add(entityId);
                }
            }
            CandidateSnapshotDTO snapshot = CandidateSnapshotBuilder.build(
                    state, snapshotCandidates(state, resolved),
                    CandidateSnapshotBuilder.CurrentSource.ORDERED_FIRST);
            PlanningObjectiveCompiler.enrichV2(state, solverObjectiveSet, policy);
            PlanSolverResultDTO solved = STAGED_SOLVER.solve(
                    snapshot, solverObjectiveSet, policy).solverResult;
            LOG.info("staged dry-run {}: session={} status={} selected={} remove={} add={}",
                    solverPath, state.getSessionId(), solved.getStatus(),
                    defaultList(solved.getSelectedEntityIds()).size(),
                    defaultList(solved.getRemoveEntityIds()).size(),
                    defaultList(solved.getAddEntityIds()).size());
            result.objectiveSet = objectiveSet;
            result.solverResult = solved;
            if (RepairProposalTaxonomy.Status.BLOCKED.equals(solved.getStatus())) {
                PlanSolverResultDTO.DiagnosticDTO diagnostic = solved.getDiagnostics().isEmpty()
                        ? null : solved.getDiagnostics().get(0);
                result.ok = false;
                result.reason = REASON_ADD_UNITS_DRY_RUN;
                result.message = diagnostic == null || Strings.isNullOrEmpty(diagnostic.getMessage())
                        ? "加入后的方案无法同时满足已确认目标/约束，已在预览阶段阻断。"
                        : diagnostic.getMessage();
                return result;
            }
            Set<String> selected = new LinkedHashSet<String>(defaultList(solved.getSelectedEntityIds()));
            Set<String> requiredCurrent = retained.stream().map(entity -> entity.entityId(unitMode))
                    .filter(value -> !Strings.isNullOrEmpty(value)).collect(Collectors.toCollection(LinkedHashSet::new));
            Set<String> requiredAdded = available.stream().map(option -> option.entityId(unitMode))
                    .filter(value -> !Strings.isNullOrEmpty(value)).collect(Collectors.toCollection(LinkedHashSet::new));
            if (!selected.containsAll(requiredCurrent) || !selected.containsAll(requiredAdded)) {
                result.ok = false;
                result.reason = REASON_ADD_UNITS_DRY_RUN;
                result.message = "加入后的求解结果会删掉/替换现有条目或漏掉新增条目，已在预览阶段阻断。";
                return result;
            }
            Set<String> removed = new LinkedHashSet<String>(defaultList(solved.getRemoveEntityIds()));
            removed.retainAll(requiredCurrent);
            if (!removed.isEmpty()) {
                result.ok = false;
                result.reason = REASON_ADD_UNITS_DRY_RUN;
                result.message = "加入后的求解结果会删除 " + removed.size() + " 条现有条目，已在预览阶段阻断。";
                return result;
            }
            if (selected.size() != targetAfter) {
                result.ok = false;
                result.reason = REASON_ADD_UNITS_DRY_RUN;
                result.message = "加入后的求解数量与目标 " + targetAfter + " 不一致，已在预览阶段阻断。";
                return result;
            }
            result.ok = true;
            return result;
        } catch (Exception ex) {
            result.ok = false;
            result.reason = REASON_ADD_UNITS_DRY_RUN_UNAVAILABLE;
            result.message = "当前环境无法完成加入前的只读校验（dry-run），为避免确认后失败，本次不生成可确认卡。";
            return result;
        }
    }

    /**
     * 替换的只读预检：固定总数 = 当前数，保留集合 = 当前 - 计划移出，可选集合 = 换入。
     * 解必须同时满足“保留全在、换入全在、计划移出全不在、总数不变”，否则预览阻断。
     */
    private static AddUnitsDryRun dryRunReplaceUnits(PlanningStateDTO state,
                                                     List<PlanVolunteer> current,
                                                     ReplaceRemoval removal,
                                                     List<CandidateItemDTO> resolved,
                                                     int targetCount,
                                                     boolean unitMode) {
        AddUnitsDryRun result = new AddUnitsDryRun();
        if (removal == null) {
            result.ok = false;
            result.reason = REASON_REPLACE_UNITS_INSUFFICIENT;
            result.message = "替换缺少可移出的条目。";
            return result;
        }
        if (!CanonicalPlanningRuntime.hasSelectionObjectives(state)) {
            result.ok = true;
            return result;
        }
        try {
            CanonicalPlanningObjectiveSetDTO objectiveSet = PlanningObjectiveCompiler.compileConfirmed(state);
            CanonicalPlanningObjectiveSetDTO solverObjectiveSet = copyObjectiveSet(objectiveSet);
            solverObjectiveSet.setTargetCount(targetCount);
            FillCurrentProjection projection = new FillCurrentProjection();
            projection.removeUnitIds.addAll(removal.unitIds);
            projection.removeVolunteerIds.addAll(removal.volunteerIds);
            List<CoverageEntity> retained = buildRetainedCoverageEntities(current, projection, unitMode);
            List<FillOption> available = excludeRetainedOptions(
                    buildAddFillOptions(resolved, unitMode), retained, unitMode);
            MutationPolicyDTO policy = new MutationPolicyDTO();
            policy.setAction("REPLACE");
            policy.setLockExisting(true);
            policy.setCountAsChurn(false);
            policy.getForcedRemoveEntityIds().addAll(unitMode
                    ? removal.unitIds : removal.volunteerIds);
            for (FillOption option : available) {
                String entityId = option.entityId(unitMode);
                if (!Strings.isNullOrEmpty(entityId)) {
                    policy.getForcedAddEntityIds().add(entityId);
                }
            }
            CandidateSnapshotDTO snapshot = CandidateSnapshotBuilder.build(
                    state, snapshotCandidates(state, resolved),
                    CandidateSnapshotBuilder.CurrentSource.ORDERED_FIRST);
            PlanningObjectiveCompiler.enrichV2(state, solverObjectiveSet, policy);
            PlanSolverResultDTO solved = STAGED_SOLVER.solve(
                    snapshot, solverObjectiveSet, policy).solverResult;
            LOG.info("staged dry-run replace: session={} status={} selected={} remove={} add={}",
                    state.getSessionId(), solved.getStatus(),
                    defaultList(solved.getSelectedEntityIds()).size(),
                    defaultList(solved.getRemoveEntityIds()).size(),
                    defaultList(solved.getAddEntityIds()).size());
            result.objectiveSet = objectiveSet;
            result.solverResult = solved;
            if (RepairProposalTaxonomy.Status.BLOCKED.equals(solved.getStatus())) {
                PlanSolverResultDTO.DiagnosticDTO diagnostic = solved.getDiagnostics().isEmpty()
                        ? null : solved.getDiagnostics().get(0);
                result.ok = false;
                result.reason = REASON_ADD_UNITS_DRY_RUN;
                result.message = diagnostic == null || Strings.isNullOrEmpty(diagnostic.getMessage())
                        ? "替换后的方案无法同时满足已确认目标/约束，已在预览阶段阻断。"
                        : diagnostic.getMessage();
                return result;
            }
            Set<String> selected = new LinkedHashSet<String>(defaultList(solved.getSelectedEntityIds()));
            Set<String> retainedIds = retained.stream().map(entity -> entity.entityId(unitMode))
                    .filter(value -> !Strings.isNullOrEmpty(value)).collect(Collectors.toCollection(LinkedHashSet::new));
            Set<String> addedIds = available.stream().map(option -> option.entityId(unitMode))
                    .filter(value -> !Strings.isNullOrEmpty(value)).collect(Collectors.toCollection(LinkedHashSet::new));
            if (!selected.containsAll(retainedIds) || !selected.containsAll(addedIds)) {
                result.ok = false;
                result.reason = REASON_ADD_UNITS_DRY_RUN;
                result.message = "替换后的求解结果会漏掉保留条目或换入条目，已在预览阶段阻断。";
                return result;
            }
            Set<String> plannedRemoved = unitMode
                    ? new LinkedHashSet<String>(removal.unitIds)
                    : new LinkedHashSet<String>(removal.volunteerIds);
            if (selected.stream().anyMatch(plannedRemoved::contains)) {
                result.ok = false;
                result.reason = REASON_ADD_UNITS_DRY_RUN;
                result.message = "替换后的求解结果仍会保留这次要换出的条目，已在预览阶段阻断。";
                return result;
            }
            if (selected.size() != targetCount) {
                result.ok = false;
                result.reason = REASON_ADD_UNITS_DRY_RUN;
                result.message = "替换后的求解数量与目标 " + targetCount + " 不一致，已在预览阶段阻断。";
                return result;
            }
            result.ok = true;
            return result;
        } catch (Exception ex) {
            result.ok = false;
            result.reason = REASON_ADD_UNITS_DRY_RUN_UNAVAILABLE;
            result.message = "当前环境无法完成替换前的只读校验（dry-run），为避免确认后失败，本次不生成可确认卡。";
            return result;
        }
    }

    /**
     * Q14：换入专业落在已有组时，该组已作为 retained 进入 solver；若 available
     * 再保留同一个 entityId，旧 solver 的 candidate_fact_invalid（重复 id）会把
     * 整个点名加入/替换 preview 阻断。available 只放真正新增的实体。
     */
    private static List<FillOption> excludeRetainedOptions(List<FillOption> options,
                                                           List<CoverageEntity> retained,
                                                           boolean unitMode) {
        Set<String> retainedIds = defaultList(retained).stream()
                .map(entity -> entity.entityId(unitMode))
                .filter(value -> !Strings.isNullOrEmpty(value))
                .collect(Collectors.toCollection(LinkedHashSet::new));
        if (retainedIds.isEmpty()) {
            return options;
        }
        return defaultList(options).stream()
                .filter(option -> !retainedIds.contains(option.entityId(unitMode)))
                .collect(Collectors.toList());
    }

    private static List<FillOption> buildAddFillOptions(List<CandidateItemDTO> resolved, boolean unitMode) {
        if (!unitMode) {
            return defaultList(resolved).stream().map(FillOption::new).collect(Collectors.toList());
        }
        Map<String, List<CandidateItemDTO>> grouped = new LinkedHashMap<String, List<CandidateItemDTO>>();
        for (CandidateItemDTO candidate : defaultList(resolved)) {
            String unitId = candidateUnitKey(candidate);
            if (!Strings.isNullOrEmpty(unitId)) {
                grouped.computeIfAbsent(unitId, ignored -> Lists.newArrayList()).add(candidate);
            }
        }
        return grouped.entrySet().stream()
                .map(entry -> new FillOption(entry.getKey(), entry.getValue()))
                .collect(Collectors.toList());
    }

    private static final class ExactTargetResolution {
        private CandidateItemDTO candidate;
        private String reason;
        private String message;
    }

    private static final class AddUnitsDryRun {
        private boolean ok;
        private String reason;
        private String message;
        private CanonicalPlanningObjectiveSetDTO objectiveSet;
        private PlanSolverResultDTO solverResult;
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
                    tierAllocationLabel(tierQuotaGoal)
                            + "暂不能与本轮普通要求或优先排序规则混合执行。请先单独确认这项冲稳保硬目标。");
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
        boolean allowStructuralReplacement = tierQuotaGoal != null
                || defaultList(req.getRequirements()).stream().anyMatch(requirement -> requirement != null
                && ProjectedHardRequirementSupport.KIND_INCLUDE.equalsIgnoreCase(requirement.getKind()));
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
                        + (tierQuotaGoal == null ? "并落实覆盖数量的调整预览"
                        : "并落实" + tierAllocationLabel(tierQuotaGoal) + "的调整预览")
                        : "补齐到 " + targetCount + (majorGroupMode ? " 个专业组" : " 个志愿") + "的调整预览");
        if (hasTierQuota) {
            proposal.setTierQuotaChange(buildTierQuotaChange(
                    state, tierQuotaGoal, targetCount, objectiveSet));
        }
        if (currentProjection.lockedViolation) {
            String message = "当前方案中有锁定项不满足本轮硬要求，不能在不解除锁定的情况下生成原子调整预览。";
            return buildScopeBlockedProposal(state, req, RepairProposalTaxonomy.Strategy.FILL_MISSING_COUNT,
                    REASON_PROJECTED_REQUIREMENTS_LOCKED, message);
        }
        if (!hasProjectedRequirements && !hasPriorityRule && !hasTierQuota && currentCount >= targetCount) {
            // 无变更预览仍走 staged（FILL 口径，目标数 = 当前数），只为把 canonical 元数据
            // （solverVersion/inputDigest/objectiveResults）挂到提案上；集合保持不变。
            CanonicalPlanningObjectiveSetDTO stagedObjectives = copyObjectiveSet(objectiveSet);
            stagedObjectives.setTargetCount(currentCount);
            List<CandidateItemDTO> currentCandidates = current.stream()
                    .map(PlanVolunteer::asCandidate)
                    .filter(Objects::nonNull)
                    .collect(Collectors.toList());
            CandidateSnapshotDTO snapshot = CandidateSnapshotBuilder.build(
                    state, currentCandidates, CandidateSnapshotBuilder.CurrentSource.ORDERED_FIRST);
            MutationPolicyDTO policy = fillMutationPolicy(state, stagedObjectives, snapshot, false);
            PlanningObjectiveCompiler.enrichV2(state, stagedObjectives, policy);
            PlanSolverResultDTO solverResult = STAGED_SOLVER.solve(
                    snapshot, stagedObjectives, policy).solverResult;
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

        FillSelection selection = selectFillCandidates(state, projectedHardConstraints, poolCandidates,
                selectedVolunteerIds, selectedUnitIds, targetCount, majorGroupMode,
                current, currentProjection, objectiveSet, allowStructuralReplacement);
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
            removeAction.setDetail(appendEntryPreviewDetail(selection.replacementCount() > 0
                    ? hasTierQuota
                    ? "其中包含为满足" + tierAllocationLabel(tierQuotaGoal) + "而进行的等量替换。"
                    : "其中包含为满足非排他覆盖要求而进行的等量替换。"
                    : "这些项目不满足本轮要求。",
                    planEntryLabels(current, majorGroupMode, removeVolunteerIds, removeUnitIds)));
            removeAction.setUnitIds(removeUnitIds);
            removeAction.setRemoveUnitIds(removeUnitIds);
            removeAction.setVolunteerIds(removeVolunteerIds);
            removeAction.setRemoveVolunteerIds(removeVolunteerIds);
            populateActionTotals(removeAction);
            proposal.getActions().add(removeAction);
        }
        if (adjustedGap > 0) {
            FixProposalActionDTO action = new FixProposalActionDTO();
            action.setActionType(RepairProposalTaxonomy.ActionType.FILL_TOTAL_COUNT);
            action.setLevel(majorGroupMode ? "unit" : "volunteer");
            action.setSummary("从当前候选池补入 " + adjustedGap + (majorGroupMode ? " 个专业组" : " 个志愿"));
            action.setDetail(appendEntryPreviewDetail(selection.replacementCount() > 0
                    ? "其中 " + selection.replacementCount() + " 个用于"
                    + (hasTierQuota ? tierAllocationLabel(tierQuotaGoal) : "覆盖要求")
                    + "的等量替换；最终数量精确达到 " + targetCount + "。"
                    : "补入后方案数量将从 " + retainedCount + " 精确达到 " + targetCount + "。",
                    candidateEntryLabels(poolCandidates, majorGroupMode,
                            selection.volunteerIds, selection.unitIds)));
            action.setUnitIds(selection.unitIds);
            action.setVolunteerIds(selection.volunteerIds);
            action.setCandidateUnitIds(selection.unitIds);
            action.setCandidateVolunteerIds(selection.volunteerIds);
            populateActionTotals(action);
            proposal.getActions().add(action);
        }
        if (priorityAnalysis != null && priorityAnalysis.getInversionCount() > 0) {
            FixProposalActionDTO action = new FixProposalActionDTO();
            action.setActionType(RepairProposalTaxonomy.ActionType.REORDER_VOLUNTEERS);
            action.setLevel(majorGroupMode ? "unit" : "volunteer");
            action.setSummary("把目标项目在各自档位内前移");
            String reorderLabelsText = summarizeMatchedLabels(
                    matchedPlanVolunteerLabels(current, priorityAnalysis, majorGroupMode));
            action.setDetail(PriorityRuleSupport.summarize(priorityRule)
                    + (reorderLabelsText.isEmpty() ? "" : "；涉及：" + reorderLabelsText));
            if (majorGroupMode) {
                action.setUnitIds(priorityAnalysis.getMatchedIds());
            } else {
                action.setVolunteerIds(priorityAnalysis.getMatchedIds());
            }
            populateActionTotals(action);
            proposal.getActions().add(action);
        }
        // staged solver 恒返回 ready，这里按实际增删集合判定"方案是否变化"，
        // 与旧 solver 的 no_change 语义保持一致（纯持久化/已满足走 INFO）。
        boolean planChanged = selection.solverResult != null
                && (!selection.unitIds.isEmpty() || !selection.volunteerIds.isEmpty()
                || !selection.removeUnitIds.isEmpty() || !selection.removeVolunteerIds.isEmpty());
        boolean objectiveChanged = Boolean.TRUE.equals(objectiveSet.getTierAllocationStateChanged());
        if (!planChanged && !objectiveChanged && !hasProjectedRequirements && !hasPriorityRule) {
            proposal.setStatus(RepairProposalTaxonomy.Status.INFO);
            proposal.setRequiresConfirmation(false);
            proposal.setSummary("当前方案和已确认冲稳保目标都已满足，本轮无需更新。");
            proposal.setImpact("方案项目和已确认硬目标均保持不变。");
            proposal.setAddedCount(0);
            proposal.setAddedUnitCount(0);
            proposal.setRemovedCount(0);
            proposal.setTargetCountBefore(currentCount);
            proposal.setTargetCountAfter(currentCount);
            populateFillDryRun(proposal, state, currentCount, currentCount,
                    0, 0, 0, 0, "当前方案和冲稳保目标均无变化。");
            populateTierQuotaDryRun(proposal, current, majorGroupMode, selection.solverResult);
            return proposal;
        }
        proposal.setStatus(RepairProposalTaxonomy.Status.READY);
        int removeCount = majorGroupMode
                ? removeUnitIds.size() : removeVolunteerIds.size();
        proposal.setAddedCount(selection.volunteerIds.size());
        proposal.setAddedUnitCount(selection.unitIds.size());
        proposal.setRemovedCount(removeCount);
        proposal.setTargetCountBefore(currentCount);
        proposal.setTargetCountAfter(targetCount);
        String prioritySummary = priorityAnalysis == null ? ""
                : priorityAnalysis.getInversionCount() == 0
                ? "；同档前置目标当前已满足，确认后会保存并持续执行这条规则"
                : "；同时会把 " + priorityAnalysis.getMovedTargetCount() + " 个"
                + (priorityRule == null ? "" : String.join("、", defaultList(priorityRule.getValues())))
                + (majorGroupMode ? "院校专业组" : "志愿") + "在所在档位内前移";
        if (!hasProjectedRequirements && !hasPriorityRule && !hasTierQuota) {
            proposal.setSummary("当前方案有 " + currentCount + (majorGroupMode ? " 个专业组" : " 个志愿")
                    + "；本次将从符合已确认要求的候选中补入 " + gap + " 个，达到 " + targetCount + " 个。");
            proposal.setImpact("确认前不会改动方案；确认后只应用这份预览中的候选，并重新生成和审查方案。");
        } else if (removeCount == 0 && gap == 0) {
            if (hasTierQuota && !hasProjectedRequirements && !hasPriorityRule) {
                proposal.setSummary("当前方案有 " + currentCount
                        + (majorGroupMode ? " 个专业组" : " 个志愿")
                        + "，方案项目不变；本轮要求：" + combinedObjectiveSummary
                        + "。确认后只保存冲稳保硬目标并刷新方案。");
            } else {
                proposal.setSummary("当前方案有 " + currentCount
                        + (majorGroupMode ? " 个专业组" : " 个志愿")
                        + "，数量和集合已经满足目标；本轮要求：" + combinedObjectiveSummary
                        + prioritySummary + "。确认后会采纳并刷新方案。");
            }
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
                        ? "已生成保持方案总数的" + tierAllocationLabel(tierQuotaGoal)
                        + "调整预览，等待确认后执行。"
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
        // 同档前置只重排现有方案，不再交给求解器：直接由 PlanOrderingEngine 产出
        // 稳定排序结果，并组装一个与旧 solver 同形的 PlanSolverResultDTO。
        List<PlanOrderingEngine.OrderEntry> orderEntries =
                new ArrayList<PlanOrderingEngine.OrderEntry>();
        for (CoverageEntity entity : retained) {
            boolean priorityMatched = rule != null && entity.candidates.stream()
                    .anyMatch(candidate -> PriorityRuleSupport.matches(candidate, rule));
            orderEntries.add(new PlanOrderingEngine.OrderEntry(
                    entity.entityId(analysis.isUnitMode()),
                    entity.candidates.isEmpty() ? null : entity.candidates.get(0).getTier(),
                    priorityMatched,
                    entity.pinned));
        }
        PlanOrderingEngine.OrderResult ordering = PlanOrderingEngine.order(orderEntries, true);
        PlanSolverResultDTO solverResult = priorityOrderingResult(objectiveSet, ordering);
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
        // 卡面说人话（review §五-20）：不用"命中/同档逆序"这类引擎口径，直接讲"把几组谁在档位内前移"，
        // 并带上具体院校/专业名；命中实体同时落到提案级 affectedUnitIds/affectedVolunteerIds。
        String domain = analysis.isUnitMode() ? "院校专业组" : "志愿";
        String ruleLabel = String.join("、", defaultList(rule.getValues()));
        String matchedLabelsText = summarizeMatchedLabels(
                matchedEntityLabels(state, poolCandidates, analysis));
        if (analysis.isUnitMode()) {
            proposal.setAffectedUnitIds(Lists.newArrayList(analysis.getMatchedIds()));
        } else {
            proposal.setAffectedVolunteerIds(Lists.newArrayList(analysis.getMatchedIds()));
        }
        if (analysis.getInversionCount() == 0) {
            proposal.setSummary("当前方案中的 " + analysis.getMatchedCount() + " 个" + ruleLabel + domain
                    + (matchedLabelsText.isEmpty() ? "" : "（" + matchedLabelsText + "）")
                    + "已经排在各自冲稳保档位内最前面；确认后会保存这条规则并持续生效。");
            proposal.setImpact("志愿集合、冲稳保档位和固定位置保持不变；后续重新生成方案仍会校验同档前置目标。");
        } else {
            proposal.setSummary("确认后会把 " + analysis.getMovedTargetCount() + " 个" + ruleLabel + domain
                    + "在所在档位内前移" + (matchedLabelsText.isEmpty() ? "" : "：" + matchedLabelsText)
                    + "，让它们排得更靠前。");
            proposal.setImpact("只调整先后顺序；志愿集合、冲稳保档位和固定位置保持不变。");
            FixProposalActionDTO action = new FixProposalActionDTO();
            action.setActionType(RepairProposalTaxonomy.ActionType.REORDER_VOLUNTEERS);
            action.setLevel(analysis.isUnitMode() ? "unit" : "volunteer");
            action.setSummary("把目标项目在各自档位内前移");
            action.setDetail(PriorityRuleSupport.summarize(rule)
                    + (matchedLabelsText.isEmpty() ? "" : "；涉及：" + matchedLabelsText));
            if (analysis.isUnitMode()) {
                action.setUnitIds(analysis.getMatchedIds());
            } else {
                action.setVolunteerIds(analysis.getMatchedIds());
            }
            proposal.getActions().add(action);
        }
        proposal.getDryRunResult().setStatus(RepairProposalTaxonomy.Status.READY);
        proposal.getDryRunResult().setMessage("确认后这些目标项目会排在各自档位内更靠前的位置。");
        proposal.getDryRunResult().setBeforeUnitTotal(currentPlanUnitCount(state));
        proposal.getDryRunResult().setAfterUnitTotal(currentPlanUnitCount(state));
        proposal.getDryRunResult().setBeforeVolunteerTotal(currentPlanVolunteerCount(state));
        proposal.getDryRunResult().setAfterVolunteerTotal(currentPlanVolunteerCount(state));
        populatePriorityDryRun(proposal, analysis);
        return proposal;
    }

    private static PlanSolverResultDTO priorityOrderingResult(
            CanonicalPlanningObjectiveSetDTO objectiveSet,
            PlanOrderingEngine.OrderResult ordering) {
        PlanSolverResultDTO result = new PlanSolverResultDTO();
        result.setSelectedEntityIds(Lists.newArrayList(ordering.selectedIds));
        result.setOrderedEntityIds(Lists.newArrayList(ordering.orderedIds));
        result.setStatus(ordering.pinnedConflict
                ? RepairProposalTaxonomy.Status.BLOCKED
                : ordering.changed() ? RepairProposalTaxonomy.Status.READY : "no_change");
        result.setSolverVersion(StagedDeterministicPlanSolver.SOLVER_VERSION);
        result.setHardObjectiveVersion(StagedDeterministicPlanSolver.HARD_OBJECTIVE_VERSION);
        result.setInputDigest(orderingInputDigest(objectiveSet, ordering));
        PlanSolverResultDTO.ObjectiveResultDTO priority = new PlanSolverResultDTO.ObjectiveResultDTO();
        priority.setObjectiveId("priority:0");
        priority.setObjectiveType("priority_within_tier");
        priority.setRequiredMin(0);
        priority.setRequiredMax(0);
        priority.setActualCount(ordering.inversionCount);
        priority.setSatisfied(ordering.inversionCount == 0);
        result.getObjectiveResults().add(priority);
        if (ordering.pinnedConflict) {
            PlanSolverResultDTO.DiagnosticDTO diagnostic = new PlanSolverResultDTO.DiagnosticDTO();
            diagnostic.setReasonCode("pinned_conflict");
            diagnostic.setObjectiveId("priority:0");
            diagnostic.setMessage("同档优先排序会改变 pinned 项目所在档位的位置。");
            result.getDiagnostics().add(diagnostic);
        }
        return result;
    }

    private static String orderingInputDigest(CanonicalPlanningObjectiveSetDTO objectiveSet,
                                              PlanOrderingEngine.OrderResult ordering) {
        Map<String, Object> payload = new LinkedHashMap<String, Object>();
        payload.put("objective", objectiveSet == null ? null : objectiveSet.getObjectiveDigest());
        payload.put("selected", ordering.selectedIds);
        payload.put("ordered", ordering.orderedIds);
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            byte[] hash = digest.digest(com.alibaba.fastjson.JSON.toJSONString(payload)
                    .getBytes(StandardCharsets.UTF_8));
            StringBuilder hex = new StringBuilder(hash.length * 2);
            for (byte value : hash) {
                hex.append(String.format("%02x", value & 0xff));
            }
            return hex.toString();
        } catch (NoSuchAlgorithmException ex) {
            throw new IllegalStateException("SHA-256 is unavailable", ex);
        }
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
        // 区域 ID 一路带上来 ✓（组模式的区域判定按 ID 优先 ✓，缺 ID 时回退名字 ✓）
        unit.setProvinceId(representative.getProvinceId());
        unit.setCityId(representative.getCityId());
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
            // 分类名随候选带上 ✓（投影/单元侧的专业筛选与执行侧同一条判据要用 ✓）。
            major.setMajorCategory(candidate.getMajorCategory());
            major.setMajorDiscipline(candidate.getMajorDiscipline());
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

    private static FillSelection selectFillCandidates(PlanningStateDTO state,
                                                      HardConstraintsDTO projectedHardConstraints,
                                                      List<CandidateItemDTO> poolCandidates,
                                                      Set<String> selectedVolunteerIds,
                                                      Set<String> selectedUnitIds,
                                                      int targetCount,
                                                      boolean unitMode,
                                                      List<PlanVolunteer> current,
                                                      FillCurrentProjection currentProjection,
                                                      CanonicalPlanningObjectiveSetDTO objectiveSet,
                                                      boolean allowStructuralReplacement) {
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
        // 快照必须与下面 additions 映射使用同一批候选：映射表来自 eligible，
        // 若快照用别的池，solver 选中映射表外的实体时会被静默丢弃。
        Set<String> snapshotEntityIds = new LinkedHashSet<String>();
        for (FillOption option : eligible) {
            String entityId = option.entityId(unitMode);
            if (!Strings.isNullOrEmpty(entityId)) {
                snapshotEntityIds.add(entityId);
            }
        }
        for (CoverageEntity entity : retained) {
            String entityId = entity.entityId(unitMode);
            if (!Strings.isNullOrEmpty(entityId)) {
                snapshotEntityIds.add(entityId);
            }
        }
        List<CandidateItemDTO> snapshotPool = defaultList(poolCandidates).stream()
                .filter(candidate -> snapshotEntityIds.contains(
                        candidateEntityId(candidate, unitMode)))
                .collect(Collectors.toList());
        CandidateSnapshotDTO snapshot = CandidateSnapshotBuilder.build(state, snapshotPool,
                CandidateSnapshotBuilder.CurrentSource.ORDERED_FIRST);
        // 被本轮投影要求移出的存量项不能回到候选集：CandidateSnapshotBuilder 会把
        // ordered plan 里的项补成 current（churn=0），若留着会被 staged 优先保留，
        // 导致"应移出"的项被选中、补入项落空。移出名单由 currentProjection 另行落账。
        //
        // 单元模式下一个专业组可能只移出部分专业（组仍保留）：除整条 fact 外，
        // 还要把被移出的专业从 rawCandidates 中剔除，否则 staged 的
        // eligibilityConstraints（如"排除医学"）会因残留专业把整组判为不合格。
        Set<String> removalEntityIds = unitMode
                ? new LinkedHashSet<String>(defaultList(currentProjection.removeUnitIds))
                : new LinkedHashSet<String>(defaultList(currentProjection.removeVolunteerIds));
        if (!removalEntityIds.isEmpty()) {
            List<CandidateFactDTO> keptFacts = new ArrayList<CandidateFactDTO>();
            for (CandidateFactDTO fact : defaultList(snapshot.getFacts())) {
                if (removalEntityIds.contains(fact.getEntityId())) {
                    continue;
                }
                // 池内候选与方案项的 volunteerId 口径可能不同，按投影硬要求判据
                // 剔除被移出的专业，而不是比对 ID。
                defaultList(fact.getRawCandidates()).removeIf(candidate ->
                        !ProjectedHardRequirementSupport.isAllowed(
                                candidate, projectedHardConstraints));
                if (fact.getRawCandidates() == null || fact.getRawCandidates().isEmpty()) {
                    continue;
                }
                keptFacts.add(fact);
            }
            snapshot.setFacts(keptFacts);
        }
        // 快照默认只读 state 里已确认的优先规则；组合请求（fill + 本轮新增优先规则）
        // 的规则还没落库，必须用 objectiveSet 里的本轮 orderingConstraints 覆盖命中标记，
        // 否则 staged 排序不会把命中项前置。
        List<PriorityRuleDTO> orderingRules = defaultList(objectiveSet.getOrderingConstraints());
        if (!orderingRules.isEmpty()) {
            for (CandidateFactDTO fact : defaultList(snapshot.getFacts())) {
                fact.setPriorityMatched(defaultList(fact.getRawCandidates()).stream()
                        .anyMatch(candidate -> orderingRules.stream()
                                .anyMatch(rule -> PriorityRuleSupport.matches(candidate, rule))));
            }
        }
        MutationPolicyDTO policy = fillMutationPolicy(state, objectiveSet, snapshot, allowStructuralReplacement);
        policy.setRequireCompensationSafe(true);
        // 用副本 enrich：proposal 的 canonicalObjectiveDigest 仍保持原口径，
        // 避免 apply 后置校验用 compileConfirmed 重算时 40905。
        CanonicalPlanningObjectiveSetDTO stagedObjectives = copyObjectiveSet(objectiveSet);
        PlanningObjectiveCompiler.enrichV2(state, stagedObjectives, policy);
        selection.solverResult = STAGED_SOLVER.solve(snapshot, stagedObjectives, policy).solverResult;
        if (RepairProposalTaxonomy.Status.BLOCKED.equals(selection.solverResult.getStatus())) {
            PlanSolverResultDTO.DiagnosticDTO diagnostic = selection.solverResult.getDiagnostics().isEmpty()
                    ? null : selection.solverResult.getDiagnostics().get(0);
            String solverReason = diagnostic == null ? null : diagnostic.getReasonCode();
            if ("candidate_shortage".equals(solverReason)) {
                return selection;
            }
            // staged solver 对 LP 不可行统一给 objective_set_infeasible；
            // 这里按目标/锁定事实还原既有的可操作原因（tier_*/locked_conflict）。
            String refinedReason = isStagedInfeasible(solverReason)
                    ? resolveStagedInfeasibleReason(objectiveSet, retained, eligible) : null;
            String effectiveReason = Strings.isNullOrEmpty(refinedReason) ? solverReason : refinedReason;
            boolean tierDiagnostic = objectiveSet.getTierAllocationConstraint() != null
                    && !Strings.isNullOrEmpty(effectiveReason)
                    && (effectiveReason.startsWith("tier_") || "locked_conflict".equals(effectiveReason));
            String reasonCode = tierDiagnostic ? effectiveReason
                    : "solver_complexity_limit".equals(effectiveReason)
                    ? REASON_SOLVER_COMPLEXITY_LIMIT
                    : "locked_conflict".equals(effectiveReason)
                    || "pinned_conflict".equals(effectiveReason)
                    ? REASON_COVERAGE_REPLACEMENT_LOCKED
                    : "candidate_shortage".equals(effectiveReason)
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

    private static MutationPolicyDTO fillMutationPolicy(PlanningStateDTO state,
                                                         CanonicalPlanningObjectiveSetDTO objectives,
                                                         CandidateSnapshotDTO snapshot,
                                                         boolean allowStructuralReplacement) {
        MutationPolicyDTO policy = new MutationPolicyDTO();
        policy.setAction("FILL");
        policy.setLockExisting(false);
        policy.setCountAsChurn(true);
        policy.setRequiredMajorCount(state == null || state.getCandidatePoolState() == null
                ? null : state.getCandidatePoolState().getRequiredMajorCount());
        if (!allowStructuralReplacement) {
            for (CandidateFactDTO fact : defaultList(snapshot.getFacts())) {
                if (Boolean.TRUE.equals(fact.getCurrent()) && Boolean.TRUE.equals(fact.getEligible())
                        && InitialContentPolicySupport.candidatesForSelection(fact).stream()
                        .allMatch(candidate -> ProjectedHardRequirementSupport.isAllowed(
                                candidate, objectives.getEligibilityConstraints()))) {
                    policy.getFrozenRequiredEntityIds().add(fact.getEntityId());
                }
            }
        }
        return policy;
    }

    private static boolean isStagedInfeasible(String reasonCode) {
        return "objective_set_infeasible".equals(reasonCode)
                || "solver_infeasible_after_cap".equals(reasonCode)
                || "solver_witness_broken".equals(reasonCode);
    }

    /**
     * 把 staged solver 的通用不可行原因细化为既有诊断口径：
     * 覆盖不足 → coverage_infeasible；锁定项挤占槽位 / 锁定项超档 → locked_conflict；
     * 档位最低数量不足 → tier_min_infeasible / tier_exact_infeasible。
     */
    private static String resolveStagedInfeasibleReason(
            CanonicalPlanningObjectiveSetDTO objectiveSet,
            List<CoverageEntity> retained,
            List<FillOption> eligible) {
        if (objectiveSet == null) {
            return null;
        }
        int targetCount = objectiveSet.getTargetCount() == null ? 0 : objectiveSet.getTargetCount();
        List<CoverageEntity> locked = retained.stream()
                .filter(entity -> entity.locked)
                .collect(Collectors.toList());
        for (CoverageRequirementDTO requirement : defaultList(objectiveSet.getCoverageConstraints())) {
            int required = CoverageRequirementSupport.minCount(requirement);
            int available = countCoverage(retained, eligible, requirement);
            if (required > targetCount || available < required) {
                return "coverage_infeasible";
            }
            int lockedMatches = countCoverage(locked, Lists.<FillOption>newArrayList(), requirement);
            int unlockedMatches = available - lockedMatches;
            int remainingSlots = Math.max(0, targetCount - locked.size());
            if (lockedMatches + Math.min(remainingSlots, unlockedMatches) < required) {
                return "locked_conflict";
            }
        }
        TierAllocationConstraintDTO constraint = objectiveSet.getTierAllocationConstraint();
        if (constraint == null) {
            return null;
        }
        boolean exact = TierAllocationSupport.TYPE_EXACT_COUNTS.equalsIgnoreCase(
                Strings.nullToEmpty(constraint.getSourceType()).trim())
                || TierAllocationSupport.TYPE_RATIOS.equalsIgnoreCase(
                Strings.nullToEmpty(constraint.getSourceType()).trim());
        for (String tier : new String[]{"sprint", "stable", "protect"}) {
            TierCountRangeDTO bound = tierBound(constraint, tier);
            if (bound == null || bound.getMinCount() == null) {
                continue;
            }
            int available = countTier(retained, eligible, tier);
            int fixed = countTier(locked, Lists.<FillOption>newArrayList(), tier);
            if (available < bound.getMinCount()) {
                return exact ? "tier_exact_infeasible" : "tier_min_infeasible";
            }
            if (bound.getMaxCount() != null && fixed > bound.getMaxCount()) {
                return "locked_conflict";
            }
        }
        return null;
    }

    private static TierCountRangeDTO tierBound(TierAllocationConstraintDTO constraint, String tier) {
        if ("sprint".equals(tier)) {
            return constraint.getSprint();
        }
        if ("stable".equals(tier)) {
            return constraint.getStable();
        }
        return constraint.getProtect();
    }

    private static int countCoverage(List<CoverageEntity> entities,
                                     List<FillOption> options,
                                     CoverageRequirementDTO requirement) {
        int count = 0;
        for (CoverageEntity entity : defaultList(entities)) {
            if (entity.candidates.stream()
                    .anyMatch(candidate -> CoverageRequirementSupport.matches(candidate, requirement))) {
                count++;
            }
        }
        for (FillOption option : defaultList(options)) {
            if (option.candidates.stream()
                    .anyMatch(candidate -> CoverageRequirementSupport.matches(candidate, requirement))) {
                count++;
            }
        }
        return count;
    }

    private static int countTier(List<CoverageEntity> entities,
                                 List<FillOption> options,
                                 String tier) {
        int count = 0;
        for (CoverageEntity entity : defaultList(entities)) {
            if (entity.matchesTier(tier)) {
                count++;
            }
        }
        for (FillOption option : defaultList(options)) {
            String optionTier = option.representative == null ? null
                    : TierAllocationSupport.canonicalTierKey(option.representative.getTier());
            if (tier.equals(optionTier)) {
                count++;
            }
        }
        return count;
    }

    /**
     * enrichV2 会改写 objectiveDigest，并且 freezeDigest 会落回
     * TierAllocationResolutionDTO。BeanUtils.copyProperties 是浅拷贝，会把
     * 原 objectiveSet 的 resolution 一起改写，导致后续持久化/比对拿到 v2 digest。
     * 这里统一做 JSON 深拷贝，staged 分支只动副本。
     */
    private static CanonicalPlanningObjectiveSetDTO copyObjectiveSet(
            CanonicalPlanningObjectiveSetDTO source) {
        if (source == null) {
            return null;
        }
        return com.alibaba.fastjson.JSON.parseObject(
                com.alibaba.fastjson.JSON.toJSONString(source),
                CanonicalPlanningObjectiveSetDTO.class);
    }

    private static String candidateEntityId(CandidateItemDTO candidate, boolean unitMode) {
        if (candidate == null) {
            return null;
        }
        return unitMode
                ? RepairCandidateSelector.resolveInitialRecommendationUnitId(candidate)
                : candidate.getVolunteerId();
    }

    private static List<CandidateItemDTO> snapshotCandidates(PlanningStateDTO state,
                                                              List<CandidateItemDTO> extra) {
        Map<String, CandidateItemDTO> byId = new LinkedHashMap<String, CandidateItemDTO>();
        if (state != null && state.getCandidatePoolState() != null) {
            for (CandidateItemDTO candidate : defaultList(state.getCandidatePoolState().getItems())) {
                if (candidate != null && !Strings.isNullOrEmpty(candidate.getVolunteerId())) {
                    byId.put(candidate.getVolunteerId(), candidate);
                }
            }
        }
        for (CandidateItemDTO candidate : defaultList(extra)) {
            if (candidate != null && !Strings.isNullOrEmpty(candidate.getVolunteerId())) {
                byId.put(candidate.getVolunteerId(), candidate);
            }
        }
        return Lists.newArrayList(byId.values());
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
                .map(UserGoalProposalBuilder::planUnitKey)
                .filter(value -> !Strings.isNullOrEmpty(value))
                .collect(Collectors.toCollection(LinkedHashSet::new));
        String scopeLabel = scopeLabel(scopes);
        // 反问**只在该值任何一级都匹配不上时**发生 ✓（2026-09-25 用户裁决）：
        // "只看北京" 这类意图是明确的 ✓，层级由系统定 ✓（`matchesRegion` 的层级兜底 ✓）；
        // 但"银河系"这种谁也匹配不上的值 ✓，指向它的应当是"范围需要先确认" ✓，
        // 而不是"方案和候选池里都没有找到相关选择" ✗（那句把用户引向"没有数据" ✗）。
        // 所以这里判的是**结果**（有没有匹配）而不是**状态词** ✓——状态词由模型给、口径各异 ✗。
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

        if (currentMatches.isEmpty() && candidateMatches.isEmpty()
                && scopes.stream().anyMatch(ScopeMatcher::isUnresolvedRegionScope)) {
            return buildScopeBlockedProposal(state, req, goalType, REASON_ENTITY_NEEDS_CLARIFICATION,
                    "“" + scopeLabel + "”还没有对应到明确范围，需要先确认后再生成调整预览。");
        }
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
        boolean majorGroupMode = isMajorGroupMode(state);
        FixProposalDTO proposal = buildUserGoalPreviewBase(state, req, RepairProposalTaxonomy.Strategy.ONLY_KEEP_SCOPE,
                "只保留“" + scopeLabel + "”的调整预览");
        if (removable.isEmpty()) {
            proposal.setStatus(RepairProposalTaxonomy.Status.INFO);
            proposal.setSummary("当前方案已经都在“" + scopeLabel + "”范围内，本轮不需要为了这个目标调整方案。");
            proposal.setImpact("如果还想继续提高这个方向的质量，可以再要求我按院校层次、录取率或地域偏好做进一步优化。"
                    + "这条保留要求尚未写入报考要求，后续重新生成不会自动只保留这个方向。");
            proposal.setRequiresConfirmation(false);
            fillDryRun(proposal, countPlanEntries(current, majorGroupMode), 0, 0, "当前方案已经符合这个保留方向。");
            return proposal;
        }
        List<ReplacementPreviewPair> pairs = buildReplacementPreviewPairs(
                removable, candidateMatches, selectedUnitIds, majorGroupMode,
                Math.min(countPlanEntries(removable, majorGroupMode), countCandidateEntries(candidateMatches, majorGroupMode)),
                RepairProposalTaxonomy.Strategy.ONLY_KEEP_SCOPE);
        List<PlanVolunteer> remainingRemovable = remainingSources(removable, pairs, majorGroupMode);
        int currentMatchCount = countPlanEntries(currentMatches, majorGroupMode);
        int removableCount = countPlanEntries(removable, majorGroupMode);
        int pairCount = countReplacementPairs(pairs, majorGroupMode);
        int remainingCount = countPlanEntries(remainingRemovable, majorGroupMode);
        proposal.setSummary("当前方案中有 " + formatEntryCount(currentMatchCount, majorGroupMode)
                + "符合“" + scopeLabel + "”；如果只保留这个方向，另有 "
                + formatEntryCount(removableCount, majorGroupMode) + "需要处理。本次能替换 "
                + formatEntryCount(pairCount, majorGroupMode) + "。");
        proposal.setImpact(remainingRemovable.isEmpty()
                ? "确认前不会改动当前方案；确认后这条范围要求会写入本会话的报考要求，并按它重新生成、刷新方案。"
                : "确认后这条范围要求会写入本会话的报考要求，并重新生成方案；还有 "
                + formatEntryCount(remainingCount, majorGroupMode)
                + "暂时没有合适补位，剩余部分需要放宽条件或后续再补。");
        if (!pairs.isEmpty()) {
            proposal.getActions().add(replaceAction("用保留范围内的候选替换其他志愿",
                    pairs, majorGroupMode, current, candidateMatches));
        }
        if (!remainingRemovable.isEmpty()) {
            proposal.getActions().add(removeAction("不在保留范围内且暂未找到补位的志愿",
                    remainingRemovable, majorGroupMode, current));
        }
        markReadyIfActionable(proposal);
        fillDryRun(proposal, countPlanEntries(current, majorGroupMode), removableCount, pairCount, "已生成调整预览，等待确认后再执行。");
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
        boolean majorGroupMode = isMajorGroupMode(state);
        Set<String> selectedVolunteerIds = current.stream()
                .map(PlanVolunteer::getVolunteerId)
                .filter(value -> !Strings.isNullOrEmpty(value))
                .collect(Collectors.toCollection(LinkedHashSet::new));
        Set<String> selectedUnitIds = current.stream()
                .map(UserGoalProposalBuilder::planUnitKey)
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
            proposal.setImpact("当前方案不需要调整；这条学费预算尚未写入报考要求，后续规划不会自动按它过滤。");
            proposal.setRequiresConfirmation(false);
            fillDryRun(proposal, countPlanEntries(current, majorGroupMode), 0, 0, "当前方案没有命中超过预算的志愿。");
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

        List<ReplacementPreviewPair> pairs = buildReplacementPreviewPairs(
                overBudget, affordableCandidates, selectedUnitIds, majorGroupMode,
                Math.min(countPlanEntries(overBudget, majorGroupMode), countCandidateEntries(affordableCandidates, majorGroupMode)),
                RepairProposalTaxonomy.Strategy.TUITION_BUDGET_SCOPE);
        List<PlanVolunteer> remaining = remainingSources(overBudget, pairs, majorGroupMode);
        int overBudgetCount = countPlanEntries(overBudget, majorGroupMode);
        int pairCount = countReplacementPairs(pairs, majorGroupMode);
        int remainingCount = countPlanEntries(remaining, majorGroupMode);
        proposal.setSummary("当前方案里有 " + formatEntryCount(overBudgetCount, majorGroupMode)
                + "学费超过 " + maxTuition + " 元/年；本次能替换 "
                + formatEntryCount(pairCount, majorGroupMode) + "。");
        proposal.setImpact(remaining.isEmpty()
                ? "确认前不会改动当前方案；确认后学费上限会写入本会话的报考要求，并按它重新生成、刷新方案。"
                : "确认后学费上限会写入本会话的报考要求，并重新生成方案；还有 "
                + formatEntryCount(remainingCount, majorGroupMode)
                + "暂时没有合适补位，剩余部分需要放宽预算或后续再补。");
        if (!pairs.isEmpty()) {
            proposal.getActions().add(replaceAction("用不超过预算的候选替换超预算志愿",
                    pairs, majorGroupMode, current, affordableCandidates));
        }
        if (!remaining.isEmpty()) {
            proposal.getActions().add(removeAction("学费超过预算且暂未找到补位的志愿",
                    remaining, majorGroupMode, current));
        }
        markReadyIfActionable(proposal);
        fillDryRun(proposal, countPlanEntries(current, majorGroupMode), overBudgetCount, pairCount, "已生成调整预览，等待确认后再执行。");
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
            boolean majorGroupMode = isMajorGroupMode(state);
            proposal.setStatus(RepairProposalTaxonomy.Status.INFO);
            proposal.setSummary("当前方案里已经有 " + formatEntryCount(countPlanEntries(currentMatches, majorGroupMode), majorGroupMode)
                    + "“" + scopeLabel + "”相关选择，本轮不需要为了这个目标调整方案。");
            proposal.setImpact("如果还想提高这个方向的优先级，可以继续要求我生成更偏这个方向的调整预览。"
                    + "这条要求尚未写入报考要求，后续重新生成不会自动保留这个方向。");
            proposal.setRequiresConfirmation(false);
            fillDryRun(proposal, countPlanEntries(current, majorGroupMode), 0, 0, "当前方案已覆盖这个方向。");
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
                proposal.setImpact("确认前不会改动当前方案；确认后这条范围要求会写入本会话的报考要求，"
                        + "并先替换一条低优先级选择、重新生成方案。");
                proposal.getActions().add(replaceAction("补入这个方向并替换低优先级志愿",
                        pairs, majorGroupMode, current, candidateMatches));
                markReadyIfActionable(proposal);
                fillDryRun(proposal, countPlanEntries(current, majorGroupMode),
                        countReplacementPairs(pairs, majorGroupMode),
                        countReplacementPairs(pairs, majorGroupMode), "已生成调整预览，等待确认后再执行。");
                return proposal;
            }
        }
        proposal.setSummary("当前方案里还没有“" + scopeLabel + "”；候选池里找到可补入的参考选择，已生成补入预览。");
        proposal.setImpact("确认前不会改动当前方案；确认后这条范围要求会写入本会话的报考要求，"
                + "并把该方向补入方案、重新生成方案。");
        proposal.getActions().add(addAction("候选池中可补入的选择",
                Lists.newArrayList(candidateMatches.get(0)), majorGroupMode, candidateMatches));
        markReadyIfActionable(proposal);
        fillDryRun(proposal, countPlanEntries(current, majorGroupMode), 0, 1, "已生成补入预览，等待确认后再执行。");
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
        boolean majorGroupMode = isMajorGroupMode(state);
        if (currentMatches.isEmpty()) {
            proposal.setStatus(RepairProposalTaxonomy.Status.INFO);
            proposal.setSummary("当前方案里没有发现“" + scopeLabel + "”相关选择，本轮不需要为了这个目标移出志愿。");
            proposal.setImpact("当前方案不需要调整；这条避开要求尚未写入报考要求，后续规划不会自动按它过滤。");
            proposal.setRequiresConfirmation(false);
            fillDryRun(proposal, countPlanEntries(current, majorGroupMode), 0, 0, "当前方案没有命中需要避开的范围。");
            return proposal;
        }
        List<PlanVolunteer> removable = currentMatches.stream()
                .filter(item -> !item.isLocked())
                .collect(Collectors.toList());
        if (removable.isEmpty()) {
            return buildScopeBlockedProposal(state, req, RepairProposalTaxonomy.Strategy.EXCLUDE_SCOPE,
                    "user_goal_current_hits_locked", "当前方案里有“" + scopeLabel + "”相关选择，但这些条目暂时不能自动移出，需要人工确认后处理。");
        }
        List<ReplacementPreviewPair> pairs = buildReplacementPreviewPairs(
                removable, candidateNonMatches, selectedUnitIds, majorGroupMode,
                Math.min(countPlanEntries(removable, majorGroupMode), countCandidateEntries(candidateNonMatches, majorGroupMode)),
                RepairProposalTaxonomy.Strategy.EXCLUDE_SCOPE);
        List<PlanVolunteer> remainingRemovable = remainingSources(removable, pairs, majorGroupMode);
        int currentMatchCount = countPlanEntries(currentMatches, majorGroupMode);
        int removableCount = countPlanEntries(removable, majorGroupMode);
        int pairCount = countReplacementPairs(pairs, majorGroupMode);
        int remainingCount = countPlanEntries(remainingRemovable, majorGroupMode);
        proposal.setSummary("当前方案里有 " + formatEntryCount(currentMatchCount, majorGroupMode)
                + "命中“" + scopeLabel + "”；本次能替换 "
                + formatEntryCount(pairCount, majorGroupMode) + "。");
        proposal.setImpact(remainingRemovable.isEmpty()
                ? "确认前不会改动当前方案；确认后这条避开要求会写入本会话的报考要求，并按它重新生成、刷新方案。"
                : "确认后这条避开要求会写入本会话的报考要求，并重新生成方案；还有 "
                + formatEntryCount(remainingCount, majorGroupMode)
                + "暂时没有合适补位，剩余部分需要放宽条件或后续再补。");
        if (!pairs.isEmpty()) {
            proposal.getActions().add(replaceAction("用其他候选替换需要避开的志愿",
                    pairs, majorGroupMode, current, candidateNonMatches));
        }
        if (!remainingRemovable.isEmpty()) {
            proposal.getActions().add(removeAction("命中避开范围且暂未找到补位的志愿",
                    remainingRemovable, majorGroupMode, current));
        }
        markReadyIfActionable(proposal);
        fillDryRun(proposal, countPlanEntries(current, majorGroupMode), removableCount, pairCount, "已生成调整预览，等待确认后再执行。");
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

    private static FixProposalActionDTO removeAction(String summary,
                                                     List<PlanVolunteer> volunteers,
                                                     boolean majorGroupMode,
                                                     List<PlanVolunteer> current) {
        FixProposalActionDTO action = new FixProposalActionDTO();
        action.setActionType(RepairProposalTaxonomy.ActionType.REMOVE_VOLUNTEERS);
        action.setLevel("volunteer");
        action.setSummary(summary);
        action.setDetail(appendEntryPreviewDetail(
                "预计移出 " + formatEntryCount(countPlanEntries(volunteers, majorGroupMode), majorGroupMode) + "。",
                planEntryLabels(volunteers, majorGroupMode)));
        action.setUnitIds(volunteers.stream()
                .map(UserGoalProposalBuilder::planUnitKey)
                .filter(value -> !Strings.isNullOrEmpty(value))
                .distinct()
                .collect(Collectors.toList()));
        List<PlanVolunteer> volunteerScope = majorGroupMode
                ? planVolunteersForUnits(current, action.getUnitIds()) : volunteers;
        action.setVolunteerIds(volunteerScope.stream()
                .map(PlanVolunteer::getVolunteerId)
                .filter(value -> !Strings.isNullOrEmpty(value))
                .distinct()
                .collect(Collectors.toList()));
        action.setRemoveVolunteerIds(action.getVolunteerIds());
        action.setRemoveUnitIds(action.getUnitIds());
        action.setCandidateVolunteerIds(Lists.newArrayList());
        action.setCandidateUnitIds(Lists.newArrayList());
        populateActionTotals(action);
        return action;
    }

    private static FixProposalActionDTO addAction(String summary,
                                                  List<CandidateItemDTO> candidates,
                                                  boolean majorGroupMode,
                                                  List<CandidateItemDTO> eligibleCandidates) {
        FixProposalActionDTO action = new FixProposalActionDTO();
        action.setActionType(RepairProposalTaxonomy.ActionType.ADD_VOLUNTEERS);
        action.setLevel("volunteer");
        action.setSummary(summary);
        List<CandidateItemDTO> selectedCandidates = majorGroupMode
                ? candidatesForUnits(eligibleCandidates, candidateUnitIds(candidates)) : candidates;
        action.setDetail(appendEntryPreviewDetail(
                "找到 " + formatEntryCount(countCandidateEntries(selectedCandidates, majorGroupMode), majorGroupMode) + "可参考选择。",
                candidateEntryLabels(selectedCandidates, majorGroupMode)));
        action.setVolunteerIds(selectedCandidates.stream()
                .map(CandidateItemDTO::getVolunteerId)
                .filter(value -> !Strings.isNullOrEmpty(value))
                .distinct()
                .collect(Collectors.toList()));
        action.setUnitIds(selectedCandidates.stream()
                .map(UserGoalProposalBuilder::candidateUnitKey)
                .filter(value -> !Strings.isNullOrEmpty(value))
                .distinct()
                .collect(Collectors.toList()));
        action.setCandidateVolunteerIds(action.getVolunteerIds());
        action.setCandidateUnitIds(action.getUnitIds());
        action.setRemoveVolunteerIds(Lists.newArrayList());
        action.setRemoveUnitIds(Lists.newArrayList());
        populateActionTotals(action);
        return action;
    }

    private static FixProposalActionDTO replaceAction(String summary,
                                                      List<ReplacementPreviewPair> pairs,
                                                      boolean majorGroupMode,
                                                      List<PlanVolunteer> current,
                                                      List<CandidateItemDTO> eligibleCandidates) {
        FixProposalActionDTO action = new FixProposalActionDTO();
        action.setActionType(RepairProposalTaxonomy.ActionType.REPLACE_VOLUNTEERS);
        action.setLevel("volunteer");
        action.setSummary(summary);
        action.setDetail(buildReplacementActionDetail(pairs));
        if (majorGroupMode) {
            action.setRemoveUnitIds(pairs.stream()
                    .map(pair -> planUnitKey(pair.source))
                    .filter(value -> !Strings.isNullOrEmpty(value))
                    .distinct()
                    .collect(Collectors.toList()));
            action.setCandidateUnitIds(pairs.stream()
                    .map(pair -> candidateUnitKey(pair.candidate))
                    .filter(value -> !Strings.isNullOrEmpty(value))
                    .distinct()
                    .collect(Collectors.toList()));
            action.setRemoveVolunteerIds(planVolunteerIdsForUnits(current, action.getRemoveUnitIds()));
            action.setCandidateVolunteerIds(candidateVolunteerIdsForUnits(eligibleCandidates, action.getCandidateUnitIds()));
        } else {
            action.setRemoveVolunteerIds(pairs.stream()
                    .map(pair -> pair.source.getVolunteerId())
                    .filter(value -> !Strings.isNullOrEmpty(value))
                    .collect(Collectors.toList()));
            action.setCandidateVolunteerIds(pairs.stream()
                    .map(pair -> pair.candidate.getVolunteerId())
                    .filter(value -> !Strings.isNullOrEmpty(value))
                    .collect(Collectors.toList()));
        }
        action.setVolunteerIds(action.getRemoveVolunteerIds());
        action.setUnitIds(action.getRemoveUnitIds());
        for (ReplacementPreviewPair pair : pairs) {
            action.getReplacementPairs().add(buildReplacementPair(pair, majorGroupMode));
        }
        populateActionTotals(action);
        return action;
    }

    private static String buildReplacementActionDetail(List<ReplacementPreviewPair> pairs) {
        int totalCount = defaultList(pairs).size();
        int shownLimit = totalCount <= ENTRY_PREVIEW_FULL_LIST_LIMIT
                ? totalCount : ENTRY_PREVIEW_HEAD_COUNT;
        List<String> previews = defaultList(pairs).stream()
                .limit(shownLimit)
                .map(UserGoalProposalBuilder::formatReplacementPreviewPair)
                .filter(value -> !Strings.isNullOrEmpty(value))
                .collect(Collectors.toList());
        String base = "预计替换 " + totalCount + " 组。";
        if (previews.isEmpty()) {
            return base;
        }
        int remainingCount = totalCount - previews.size();
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

    /**
     * 把 {@link PriorityRuleSupport.Analysis} 命中的实体 ID 换成可读名字（review §五-20）：
     * 组模式给院校名，志愿模式给“学校-专业”；拿不到名字时退回原 ID（绝不编造）。
     * 卡面摘要与动作明细共用，模型和用户都能直接对上号。
     */
    private static List<String> matchedEntityLabels(PlanningStateDTO state,
                                                    List<CandidateItemDTO> candidates,
                                                    PriorityRuleSupport.Analysis analysis) {
        Map<String, CandidateItemDTO> candidatesById = new LinkedHashMap<String, CandidateItemDTO>();
        for (CandidateItemDTO candidate : defaultList(candidates)) {
            if (candidate != null && !Strings.isNullOrEmpty(candidate.getVolunteerId())) {
                candidatesById.put(candidate.getVolunteerId(), candidate);
            }
        }
        Map<String, OrderedUnitDTO> unitsById = new LinkedHashMap<String, OrderedUnitDTO>();
        for (OrderedUnitDTO unit : defaultList(state == null || state.getOrderedPlanState() == null
                ? null : state.getOrderedPlanState().getUnits())) {
            if (unit != null && !Strings.isNullOrEmpty(unit.getUnitId())) {
                unitsById.put(unit.getUnitId(), unit);
            }
        }
        Map<String, OrderedItemDTO> itemsById = new LinkedHashMap<String, OrderedItemDTO>();
        for (OrderedItemDTO item : defaultList(state == null || state.getOrderedPlanState() == null
                ? null : state.getOrderedPlanState().getItems())) {
            if (item != null && !Strings.isNullOrEmpty(item.getVolunteerId())) {
                itemsById.put(item.getVolunteerId(), item);
            }
        }
        List<String> labels = Lists.newArrayList();
        for (String id : defaultList(analysis == null ? null : analysis.getMatchedIds())) {
            String label = "";
            if (analysis.isUnitMode()) {
                OrderedUnitDTO unit = unitsById.get(id);
                label = unit == null ? "" : Strings.nullToEmpty(unit.getSchoolName()).trim();
            } else {
                CandidateItemDTO candidate = candidatesById.get(id);
                label = candidate == null ? ""
                        : buildSchoolMajorLabel(candidate.getSchoolName(), candidate.getMajorName());
                if (Strings.isNullOrEmpty(label)) {
                    OrderedItemDTO item = itemsById.get(id);
                    label = item == null ? ""
                            : buildSchoolMajorLabel(item.getSchoolName(), item.getMajorName());
                }
            }
            if (Strings.isNullOrEmpty(label)) {
                label = Strings.nullToEmpty(id).trim();
            }
            if (!label.isEmpty() && !labels.contains(label)) {
                labels.add(label);
            }
        }
        return labels;
    }

    /** 填充预览路径（还没落成 ordered 方案）的命中实体 → 可读名字：从当前方案志愿上取学校/专业。 */
    private static List<String> matchedPlanVolunteerLabels(List<PlanVolunteer> current,
                                                           PriorityRuleSupport.Analysis analysis,
                                                           boolean majorGroupMode) {
        Map<String, PlanVolunteer> byVolunteerId = new LinkedHashMap<String, PlanVolunteer>();
        Map<String, PlanVolunteer> byUnitId = new LinkedHashMap<String, PlanVolunteer>();
        for (PlanVolunteer volunteer : defaultList(current)) {
            if (volunteer == null) {
                continue;
            }
            if (!Strings.isNullOrEmpty(volunteer.getVolunteerId())) {
                byVolunteerId.put(volunteer.getVolunteerId(), volunteer);
            }
            if (!Strings.isNullOrEmpty(volunteer.getUnitId())) {
                byUnitId.putIfAbsent(volunteer.getUnitId(), volunteer);
            }
        }
        List<String> labels = Lists.newArrayList();
        for (String id : defaultList(analysis == null ? null : analysis.getMatchedIds())) {
            PlanVolunteer volunteer = majorGroupMode ? byUnitId.get(id) : byVolunteerId.get(id);
            String label = volunteer == null ? ""
                    : buildSchoolMajorLabel(volunteer.getSchoolName(), volunteer.getMajorName());
            if (Strings.isNullOrEmpty(label)) {
                label = Strings.nullToEmpty(id).trim();
            }
            if (!label.isEmpty() && !labels.contains(label)) {
                labels.add(label);
            }
        }
        return labels;
    }

    /** 摘要用的人名列表：最多展开 3 个，其余折叠成“等 N 个”。 */
    private static String summarizeMatchedLabels(List<String> labels) {
        if (defaultList(labels).isEmpty()) {
            return "";
        }
        List<String> shown = labels.stream().limit(3).collect(Collectors.toList());
        String text = String.join("、", shown);
        return labels.size() > shown.size() ? text + " 等 " + labels.size() + " 个" : text;
    }

    /**
     * 详情里的具体条目预览（2026-10-16 口径）：≤5 条全列；>5 条只列前 3 条并注明
     * “另有 N−3 组未展开”——沿用替换预览的“具体预览”风格。名字缺失的条目不出现在预览里。
     */
    private static String appendEntryPreviewDetail(String baseDetail, List<String> entryLabels) {
        List<String> labels = defaultList(entryLabels).stream()
                .filter(value -> !Strings.isNullOrEmpty(value))
                .collect(Collectors.toList());
        if (labels.isEmpty()) {
            return baseDetail;
        }
        int shownCount = labels.size() <= ENTRY_PREVIEW_FULL_LIST_LIMIT
                ? labels.size() : ENTRY_PREVIEW_HEAD_COUNT;
        String suffix = labels.size() > shownCount
                ? "；另有 " + (labels.size() - shownCount) + " 组未展开" : "";
        return Strings.nullToEmpty(baseDetail).trim() + " 具体预览："
                + String.join("；", labels.subList(0, shownCount)) + suffix + "。";
    }

    /** 移出条目标签=「院校-专业（档位）」；拿不到名字时退回 ID（绝不编造）。 */
    private static String formatPlanVolunteerEntryLabel(PlanVolunteer volunteer) {
        if (volunteer == null) {
            return "";
        }
        String label = buildSchoolMajorLabel(volunteer.getSchoolName(), volunteer.getMajorName());
        if (Strings.isNullOrEmpty(label)) {
            label = firstNonEmpty(volunteer.getUnitId(), volunteer.getVolunteerId());
        }
        return label + formatEntryTags(volunteer.getCandidate() == null
                ? null : volunteer.getCandidate().getTier());
    }

    /** 补入条目标签=「院校-专业（档位/省）」；拿不到名字时退回 ID（绝不编造）。 */
    private static String formatCandidateEntryLabel(CandidateItemDTO candidate) {
        if (candidate == null) {
            return "";
        }
        String label = buildSchoolMajorLabel(candidate.getSchoolName(), candidate.getMajorName());
        if (Strings.isNullOrEmpty(label)) {
            label = firstNonEmpty(
                    RepairCandidateSelector.resolveInitialRecommendationUnitId(candidate),
                    candidate.getVolunteerId());
        }
        return label + formatEntryTags(candidate.getTier(), candidate.getProvinceName());
    }

    private static String formatEntryTags(String... values) {
        String tags = Lists.newArrayList(values).stream()
                .map(value -> Strings.nullToEmpty(value).trim())
                .filter(value -> !value.isEmpty())
                .collect(Collectors.joining("/"));
        return tags.isEmpty() ? "" : "（" + tags + "）";
    }

    /** 移出明细：按移除 ID 顺序取可读名（组模式按组去重）。 */
    private static List<String> planEntryLabels(List<PlanVolunteer> current,
                                                boolean majorGroupMode,
                                                List<String> removeVolunteerIds,
                                                List<String> removeUnitIds) {
        Map<String, PlanVolunteer> byVolunteerId = new LinkedHashMap<String, PlanVolunteer>();
        Map<String, PlanVolunteer> byUnitId = new LinkedHashMap<String, PlanVolunteer>();
        for (PlanVolunteer volunteer : defaultList(current)) {
            if (volunteer == null) {
                continue;
            }
            if (!Strings.isNullOrEmpty(volunteer.getVolunteerId())) {
                byVolunteerId.putIfAbsent(volunteer.getVolunteerId(), volunteer);
            }
            String unitId = planUnitKey(volunteer);
            if (!Strings.isNullOrEmpty(unitId)) {
                byUnitId.putIfAbsent(unitId, volunteer);
            }
        }
        List<String> labels = Lists.newArrayList();
        Set<String> seenKeys = new LinkedHashSet<String>();
        if (majorGroupMode) {
            for (String unitId : defaultList(removeUnitIds)) {
                if (Strings.isNullOrEmpty(unitId) || !seenKeys.add(unitId)) {
                    continue;
                }
                addPlanEntryLabel(labels, byUnitId.get(unitId));
            }
        }
        for (String volunteerId : defaultList(removeVolunteerIds)) {
            PlanVolunteer volunteer = byVolunteerId.get(volunteerId);
            String key = majorGroupMode ? planUnitKey(volunteer) : volunteerId;
            if (Strings.isNullOrEmpty(key) || !seenKeys.add(key)) {
                continue;
            }
            addPlanEntryLabel(labels, volunteer);
        }
        if (!majorGroupMode && labels.isEmpty()) {
            for (String unitId : defaultList(removeUnitIds)) {
                if (Strings.isNullOrEmpty(unitId) || !seenKeys.add(unitId)) {
                    continue;
                }
                addPlanEntryLabel(labels, byUnitId.get(unitId));
            }
        }
        return labels;
    }

    /** 移出明细（给定条目列表，组模式按组去重）。 */
    private static List<String> planEntryLabels(List<PlanVolunteer> volunteers, boolean majorGroupMode) {
        List<String> labels = Lists.newArrayList();
        Set<String> seenKeys = new LinkedHashSet<String>();
        for (PlanVolunteer volunteer : defaultList(volunteers)) {
            if (volunteer == null) {
                continue;
            }
            String key = majorGroupMode ? planUnitKey(volunteer) : volunteer.getVolunteerId();
            if (Strings.isNullOrEmpty(key) || !seenKeys.add(key)) {
                continue;
            }
            addPlanEntryLabel(labels, volunteer);
        }
        return labels;
    }

    private static void addPlanEntryLabel(List<String> labels, PlanVolunteer volunteer) {
        String label = formatPlanVolunteerEntryLabel(volunteer);
        if (!Strings.isNullOrEmpty(label)) {
            labels.add(label);
        }
    }

    /** 补入明细：按候选 ID 顺序取可读名（组模式按组去重，取该组代表候选）。 */
    private static List<String> candidateEntryLabels(List<CandidateItemDTO> candidates,
                                                     boolean majorGroupMode,
                                                     List<String> candidateVolunteerIds,
                                                     List<String> candidateUnitIds) {
        Map<String, CandidateItemDTO> byVolunteerId = new LinkedHashMap<String, CandidateItemDTO>();
        for (CandidateItemDTO candidate : defaultList(candidates)) {
            if (candidate != null && !Strings.isNullOrEmpty(candidate.getVolunteerId())) {
                byVolunteerId.putIfAbsent(candidate.getVolunteerId(), candidate);
            }
        }
        List<String> labels = Lists.newArrayList();
        Set<String> seenKeys = new LinkedHashSet<String>();
        if (majorGroupMode) {
            for (String unitId : defaultList(candidateUnitIds)) {
                if (Strings.isNullOrEmpty(unitId) || !seenKeys.add(unitId)) {
                    continue;
                }
                addCandidateEntryLabel(labels, firstCandidateOfUnit(candidates, unitId));
            }
        }
        for (String volunteerId : defaultList(candidateVolunteerIds)) {
            CandidateItemDTO candidate = byVolunteerId.get(volunteerId);
            String key = majorGroupMode ? candidateUnitKey(candidate) : volunteerId;
            if (Strings.isNullOrEmpty(key) || !seenKeys.add(key)) {
                continue;
            }
            addCandidateEntryLabel(labels, candidate);
        }
        return labels;
    }

    /** 补入明细（给定候选列表，组模式按组去重）。 */
    private static List<String> candidateEntryLabels(List<CandidateItemDTO> candidates, boolean majorGroupMode) {
        List<String> labels = Lists.newArrayList();
        Set<String> seenKeys = new LinkedHashSet<String>();
        for (CandidateItemDTO candidate : defaultList(candidates)) {
            if (candidate == null) {
                continue;
            }
            String key = majorGroupMode ? candidateUnitKey(candidate) : candidate.getVolunteerId();
            if (Strings.isNullOrEmpty(key) || !seenKeys.add(key)) {
                continue;
            }
            addCandidateEntryLabel(labels, candidate);
        }
        return labels;
    }

    private static CandidateItemDTO firstCandidateOfUnit(List<CandidateItemDTO> candidates, String unitId) {
        for (CandidateItemDTO candidate : defaultList(candidates)) {
            if (candidate != null && unitId.equals(candidateUnitKey(candidate))) {
                return candidate;
            }
        }
        return null;
    }

    private static void addCandidateEntryLabel(List<String> labels, CandidateItemDTO candidate) {
        String label = formatCandidateEntryLabel(candidate);
        if (!Strings.isNullOrEmpty(label)) {
            labels.add(label);
        }
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
            pair.setFromUnitId(planUnitKey(previewPair.source));
            pair.setToUnitId(candidateUnitKey(previewPair.candidate));
        }
        pair.getReasonCodes().add(previewPair.reasonCode);
        return pair;
    }

    private static void populateActionTotals(FixProposalActionDTO action) {
        if (action == null) {
            return;
        }
        action.setTotalUnitCount(Math.max(defaultList(action.getRemoveUnitIds()).size(),
                Math.max(defaultList(action.getCandidateUnitIds()).size(), defaultList(action.getUnitIds()).size())));
        action.setTotalVolunteerCount(Math.max(defaultList(action.getRemoveVolunteerIds()).size(),
                Math.max(defaultList(action.getCandidateVolunteerIds()).size(), defaultList(action.getVolunteerIds()).size())));
        action.setTotalReplacementPairCount(defaultList(action.getReplacementPairs()).size());
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
        orderedSources = distinctReplacementSources(orderedSources, majorGroupMode);
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
                            candidate, planUnitKey(source), currentUnitIds, usedCandidateUnitIds))
                    .min((left, right) -> compareUserGoalReplacementTradeoff(source.getCandidate(), left, right))
                    .orElse(null);
            if (best == null) {
                continue;
            }
            pairs.add(new ReplacementPreviewPair(source, best, reasonCode));
            usedCandidateVolunteerIds.add(best.getVolunteerId());
            String candidateUnitId = candidateUnitKey(best);
            if (!Strings.isNullOrEmpty(candidateUnitId)) {
                usedCandidateUnitIds.add(candidateUnitId);
            }
            remainingCandidates.remove(best);
        }
        return pairs;
    }

    private static List<PlanVolunteer> distinctReplacementSources(List<PlanVolunteer> sources,
                                                                  boolean majorGroupMode) {
        if (!majorGroupMode) {
            return defaultList(sources);
        }
        Set<String> seenKeys = new LinkedHashSet<String>();
        List<PlanVolunteer> result = Lists.newArrayList();
        for (PlanVolunteer source : defaultList(sources)) {
            String key = planUnitKey(source);
            if (Strings.isNullOrEmpty(key) || !seenKeys.add(key)) {
                continue;
            }
            result.add(source);
        }
        return result;
    }

    private static List<CandidateItemDTO> distinctReplacementCandidates(List<CandidateItemDTO> candidates,
                                                                        boolean majorGroupMode) {
        Set<String> seenKeys = new LinkedHashSet<String>();
        List<CandidateItemDTO> result = Lists.newArrayList();
        for (CandidateItemDTO candidate : defaultList(candidates)) {
            if (candidate == null || Strings.isNullOrEmpty(candidate.getVolunteerId())) {
                continue;
            }
            String key = majorGroupMode ? candidateUnitKey(candidate) : candidate.getVolunteerId();
            if (seenKeys.add(key)) {
                result.add(candidate);
            }
        }
        return result;
    }

    private static int countPlanEntries(List<PlanVolunteer> volunteers, boolean majorGroupMode) {
        if (!majorGroupMode) {
            return defaultList(volunteers).size();
        }
        return (int) defaultList(volunteers).stream()
                .map(UserGoalProposalBuilder::planUnitKey)
                .filter(value -> !Strings.isNullOrEmpty(value))
                .distinct()
                .count();
    }

    private static int countCandidateEntries(List<CandidateItemDTO> candidates, boolean majorGroupMode) {
        if (!majorGroupMode) {
            return defaultList(candidates).size();
        }
        return (int) defaultList(candidates).stream()
                .map(UserGoalProposalBuilder::candidateUnitKey)
                .filter(value -> !Strings.isNullOrEmpty(value))
                .distinct()
                .count();
    }

    private static int countReplacementPairs(List<ReplacementPreviewPair> pairs, boolean majorGroupMode) {
        if (!majorGroupMode) {
            return defaultList(pairs).size();
        }
        return (int) defaultList(pairs).stream()
                .map(pair -> planUnitKey(pair.source))
                .filter(value -> !Strings.isNullOrEmpty(value))
                .distinct()
                .count();
    }

    private static String formatEntryCount(int count, boolean majorGroupMode) {
        return count + (majorGroupMode ? " 个专业组" : " 条");
    }

    private static List<PlanVolunteer> planVolunteersForUnits(List<PlanVolunteer> volunteers, List<String> unitIds) {
        Set<String> unitIdSet = new LinkedHashSet<String>(defaultList(unitIds));
        return defaultList(volunteers).stream()
                .filter(volunteer -> unitIdSet.contains(planUnitKey(volunteer)))
                .collect(Collectors.toList());
    }

    private static List<String> planVolunteerIdsForUnits(List<PlanVolunteer> volunteers, List<String> unitIds) {
        return planVolunteersForUnits(volunteers, unitIds).stream()
                .map(PlanVolunteer::getVolunteerId)
                .filter(value -> !Strings.isNullOrEmpty(value))
                .distinct()
                .collect(Collectors.toList());
    }

    private static List<CandidateItemDTO> candidatesForUnits(List<CandidateItemDTO> candidates, List<String> unitIds) {
        Set<String> unitIdSet = new LinkedHashSet<String>(defaultList(unitIds));
        return defaultList(candidates).stream()
                .filter(candidate -> unitIdSet.contains(candidateUnitKey(candidate)))
                .collect(Collectors.toList());
    }

    private static List<String> candidateVolunteerIdsForUnits(List<CandidateItemDTO> candidates, List<String> unitIds) {
        return candidatesForUnits(candidates, unitIds).stream()
                .map(CandidateItemDTO::getVolunteerId)
                .filter(value -> !Strings.isNullOrEmpty(value))
                .distinct()
                .collect(Collectors.toList());
    }

    private static List<String> candidateUnitIds(List<CandidateItemDTO> candidates) {
        return defaultList(candidates).stream()
                .map(UserGoalProposalBuilder::candidateUnitKey)
                .filter(value -> !Strings.isNullOrEmpty(value))
                .distinct()
                .collect(Collectors.toList());
    }

    private static String planUnitKey(PlanVolunteer volunteer) {
        if (volunteer == null) {
            return "";
        }
        return firstNonEmpty(volunteer.getUnitId(), volunteer.getVolunteerId());
    }

    private static String candidateUnitKey(CandidateItemDTO candidate) {
        if (candidate == null) {
            return "";
        }
        return firstNonEmpty(RepairCandidateSelector.resolveInitialRecommendationUnitId(candidate), candidate.getVolunteerId());
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
        String candidateUnitId = candidateUnitKey(candidate);
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
                                                        List<ReplacementPreviewPair> pairs,
                                                        boolean majorGroupMode) {
        Set<String> pairedKeys = defaultList(pairs).stream()
                .map(pair -> majorGroupMode ? planUnitKey(pair.source) : pair.source.getVolunteerId())
                .filter(value -> !Strings.isNullOrEmpty(value))
                .collect(Collectors.toCollection(LinkedHashSet::new));
        return defaultList(sources).stream()
                .filter(source -> source != null)
                .filter(source -> !pairedKeys.contains(majorGroupMode ? planUnitKey(source) : source.getVolunteerId()))
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

    static int currentPlanVolunteerCount(PlanningStateDTO state) {
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

    static int currentPlanUnitCount(PlanningStateDTO state) {
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
        if (RepairProposalTaxonomy.Strategy.ADD_UNITS.equals(
                RepairProposalTaxonomy.normalizeStrategy(goalType))) {
            return "加入志愿预览";
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

        /**
         * 区域范围、且"没映射上"——**只在一条都没匹配上时**才拿去反问 ✓（调用点在算完匹配之后 ✓）。
         * 与 `needsClarification()` 的分工：那个看**状态词**、在匹配之前拦 ✓；
         * 这个看**结果**、在匹配之后兜 ✓。
         */
        boolean isUnresolvedRegionScope() {
            return "region".equals(entityType)
                    && ("unresolved".equals(resolutionStatus) || "unknown".equals(resolutionStatus));
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
                return RegionScopeSupport.sameRegionName(candidate.getProvinceName(), value)
                        || RegionScopeSupport.sameRegionName(candidate.getCityName(), value);
            }
            // **层级是提示、不是硬约束** ✓：值叫到哪一级就匹配哪一级，另一级兜底。
            //
            // 起因（2026-09-25 真栈实测）："只看北京的学校" 被解成 `scopeLevel=city` ✗，
            // 而北京是**直辖市**——表里只有省级实体，市级子项是海淀/朝阳/大兴这些区 ✓，
            // 于是"只看 cityName"一条都不中 ✗，结论写成"方案和候选池里都没有找到'北京'相关选择" ✗
            // （把用户指向"没有数据" ✗）。"只看北京"的意图是明确的 ✓，该由系统定层级 ✓，
            // 不该拿去反问用户 ✓。
            //
            // 兜底是安全的：值若真是市名（如"杭州"）✓，另一级（省）里没有同名项，匹配结果不变 ✓；
            // 只有"值其实是上一级/下一级名字"时才多中 ✓——那正是要修的形态 ✓。
            // 比较用**规范化身份相等** ✓（`sameRegionName`：去后缀/空格/大小写后相等 ✓），
            // 不再用双向子串 ✗——区域这条路径上"身份"必须唯一 ✓，"北京市"="北京" ✓ 由后缀表管 ✓。
            if ("province".equals(scopeLevel)) {
                return RegionScopeSupport.sameRegionName(candidate.getProvinceName(), value)
                        || RegionScopeSupport.sameRegionName(candidate.getCityName(), value);
            }
            if ("city".equals(scopeLevel)) {
                return RegionScopeSupport.sameRegionName(candidate.getCityName(), value)
                        || RegionScopeSupport.sameRegionName(candidate.getProvinceName(), value);
            }
            return RegionScopeSupport.sameRegionName(candidate.getProvinceName(), value)
                    || RegionScopeSupport.sameRegionName(candidate.getCityName(), value);
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
                    TierAllocationSupport.canonicalTierKey(candidate.getTier())));
        }

        private String entityId(boolean unitMode) {
            return unitMode ? unitIds.isEmpty() ? null : unitIds.get(0)
                    : volunteerIds.isEmpty() ? null : volunteerIds.get(0);
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
