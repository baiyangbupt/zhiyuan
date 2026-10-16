package com.ytell.zhiyuan.service.biz;

import com.google.common.base.Strings;
import com.ytell.zhiyuan.common.exception.BusinessException;
import com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO;
import com.ytell.zhiyuan.model.dto.planning.CanonicalPlanningObjectiveSetDTO;
import com.ytell.zhiyuan.model.dto.planning.DraftItemDTO;
import com.ytell.zhiyuan.model.dto.planning.FixProposalApplyReq;
import com.ytell.zhiyuan.model.dto.planning.FixProposalApplyRes;
import com.ytell.zhiyuan.model.dto.planning.FixProposalDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedItemDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedUnitDTO;
import com.ytell.zhiyuan.model.dto.planning.PendingPlanningCommandReq;
import com.ytell.zhiyuan.model.dto.planning.PlanChangePostconditionReportDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanSolverResultDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningUnitDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningUnitMajorDTO;
import com.ytell.zhiyuan.model.dto.planning.PriorityRuleDTO;
import com.ytell.zhiyuan.model.dto.planning.RepairReportDTO;
import com.ytell.zhiyuan.model.dto.planning.TierAllocationConstraintDTO;
import com.ytell.zhiyuan.model.dto.planning.TierAllocationResolutionDTO;
import com.ytell.zhiyuan.model.dto.planning.TierCountRangeDTO;
import com.ytell.zhiyuan.model.dto.planning.TierCountsDTO;
import com.ytell.zhiyuan.model.dto.planning.TierQuotaChangeDTO;
import com.ytell.zhiyuan.model.dto.planning.TierQuotaGoalDTO;
import com.ytell.zhiyuan.model.dto.planning.UserGoalFixProposalReq;
import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.List;
import java.util.Objects;

@Component
class UnifiedPlanPostconditionValidator {

    /**
     * 空方案不算"已满足" ✓（2026-09-26 裁决落地 ✓）：三类约束的共同前提是**得有对象可比** ✓。
     *
     * <p>数违反条目这条路（`validateConstraintApply` ✓）在空方案上是**零违反** ✗ →
     * `satisfied=true` ✗；报告路（`populateRequirements` ✓）的排除类判据 `noneMatch` 同样恒真 ✗。
     * 两条路都会把"方案没了"读成"约束已满足" ✗——命令侧 `40906` 只护着"约束刚落地"那一条 ✗，
     * 而满足度报告是**长期可读的证据** ✓，口径不一致时排查的人会先信它 ✗。
     */
    static final String EMPTY_PLAN_VACUOUS_REASON = "plan_empty_vacuous";

    PlanChangePostconditionReportDTO validate(PendingPlanningCommandReq req,
                                              PlanningStateDTO state,
                                              FixProposalApplyRes applyRes) {
        FixProposalApplyReq applyReq = req == null ? null : req.getProposalApply();
        UserGoalFixProposalReq userGoal = applyReq == null ? null : applyReq.getUserGoalRequest();
        if (userGoal == null) {
            return verifyReviewFixPostcondition(req, applyRes);
        }
        FixProposalDTO authoritativeProposal = applyRes == null ? null : applyRes.getProposal();
        PlanSolverResultDTO frozenResult = validateCanonicalFrozenResult(
                applyReq, state, authoritativeProposal);
        boolean countRequired = RepairProposalTaxonomy.Strategy.FILL_MISSING_COUNT.equals(
                RepairProposalTaxonomy.normalizeStrategy(userGoal.getGoalType()));
        Integer targetCount = userGoal.getTargetCount();
        boolean majorGroupMode = state != null && state.getCandidatePoolState() != null
                && "majorGroup".equalsIgnoreCase(state.getCandidatePoolState().getVolunteerModel());
        int actualCount = actualCount(state, majorGroupMode);
        Integer persistedTarget = state == null || state.getCandidatePoolState() == null
                ? null : state.getCandidatePoolState().getRequiredCount();
        boolean persistTargetCount = !Boolean.FALSE.equals(userGoal.getPersistTargetCount());

        PlanChangePostconditionReportDTO report = new PlanChangePostconditionReportDTO();
        report.setGoalType(userGoal.getGoalType());
        report.setCanonicalObjectiveDigest(frozenResult == null
                ? applyReq.getCanonicalObjectiveDigest() : authoritativeProposal.getCanonicalObjectiveDigest());
        report.setSolverVersion(frozenResult == null
                ? applyReq.getSolverVersion() : frozenResult.getSolverVersion());
        report.setSolverInputDigest(frozenResult == null
                ? applyReq.getSolverInputDigest() : frozenResult.getInputDigest());
        report.setCountMode(majorGroupMode ? "unit" : "volunteer");
        report.setTargetCount(targetCount);
        report.setActualCount(actualCount);

        List<CandidateItemDTO> planCandidates = postconditionPlanCandidates(state, majorGroupMode);
        int satisfiedRequirements = populateRequirements(
                report, state, userGoal, planCandidates, majorGroupMode);
        boolean requirementsSatisfied = satisfiedRequirements == report.getRequirementResults().size();
        int satisfiedPriorityRules = populatePriorityRules(report, state, userGoal);
        boolean priorityRulesSatisfied = satisfiedPriorityRules == report.getPriorityRuleResults().size();
        boolean tierQuotaSatisfied = populateTierQuota(
                report, state, userGoal, authoritativeProposal, planCandidates, majorGroupMode);

        boolean countSatisfied = !countRequired || (targetCount != null
                && actualCount == targetCount
                && (!persistTargetCount || targetCount.equals(persistedTarget)));
        populateCanonicalObjectiveResults(report, countRequired, countSatisfied);
        validateCanonicalObjectiveResults(report, frozenResult);
        report.setSatisfied(countSatisfied && requirementsSatisfied
                && priorityRulesSatisfied && tierQuotaSatisfied);
        if (!Boolean.TRUE.equals(report.getSatisfied())) {
            throw new BusinessException(PendingPlanningCommandBizService.POSTCONDITION_FAILED_CODE,
                    "plan change postcondition failed: target=" + targetCount
                            + " actual=" + actualCount + " persistedTarget=" + persistedTarget
                            + " requirements=" + satisfiedRequirements + "/" + report.getRequirementCount()
                            + " priorityRules=" + satisfiedPriorityRules + "/" + report.getPriorityRuleCount()
                            + " tierQuota=" + tierQuotaSatisfied);
        }
        return report;
    }

    /**
     * 约束变更（`apply_constraint_and_regenerate`）的满足度：**方案里每一条都不违反已确认硬约束**。
     *
     * <p>这条路以前**没有任何满足度信号** ✗：命令层只记"步骤跑完了"（`completedSteps`），
     * `PendingPlanningCommandRes` 里更没有 `status` 字段，于是网关侧 `_status()` 只能落到兜底
     * 的 `failed`——"成功"报不出来、"失败"也不是判出来的（2026-09-25 真栈实测 ✓）。
     *
     * <p>这里把信号补上，并且**不满足就抛 40905 让事务回滚**：约束没生效，就别改用户的方案。
     * 判据与筛选同源（`RepairCandidateEligibility` ✓）：组模式下按**单元**判（组内任一专业命中即可 ✓），
     * 与"筛选时怎么算合格"逐字一致，避免出现"筛的时候合格、验的时候不合格"这种自相矛盾 ✓。
     */
    PlanChangePostconditionReportDTO validateConstraintApply(String commandType, PlanningStateDTO state) {
        boolean majorGroupMode = state != null && state.getCandidatePoolState() != null
                && "majorGroup".equalsIgnoreCase(state.getCandidatePoolState().getVolunteerModel());
        List<OrderedUnitDTO> units = state == null || state.getOrderedPlanState() == null
                ? new ArrayList<OrderedUnitDTO>() : defaultList(state.getOrderedPlanState().getUnits());
        List<CandidateItemDTO> planCandidates = postconditionPlanCandidates(state, majorGroupMode);
        int total = majorGroupMode ? units.size() : planCandidates.size();
        int violating = 0;
        if (majorGroupMode) {
            for (OrderedUnitDTO unit : units) {
                if (!RepairCandidateEligibility.isEligibleForConfirmedHardConstraints(
                        asPlanningUnit(unit), state)) {
                    violating++;
                }
            }
        } else {
            for (CandidateItemDTO candidate : planCandidates) {
                if (!RepairCandidateEligibility.isEligibleForConfirmedHardConstraints(candidate, state)) {
                    violating++;
                }
            }
        }
        PlanChangePostconditionReportDTO report = new PlanChangePostconditionReportDTO();
        report.setGoalType(commandType);
        report.setCountMode(majorGroupMode ? "unit" : "volunteer");
        report.setTargetCount(state == null || state.getCandidatePoolState() == null
                ? null : state.getCandidatePoolState().getRequiredCount());
        report.setActualCount(actualCount(state, majorGroupMode));
        // 空方案 = **零违反** ✗，但那是"没有可比对象" ✗，不是"约束满足" ✓——
        // 只有**已确认约束**存在时才这么判 ✓（没有约束时"零违反"本来就是对的 ✓）。
        boolean vacuousEmpty = total == 0 && RepairCandidateEligibility.hasConfirmedHardConstraints(state);
        report.setSatisfied(violating == 0 && !vacuousEmpty);
        if (!Boolean.TRUE.equals(report.getSatisfied())) {
            report.setReasonCode(vacuousEmpty ? EMPTY_PLAN_VACUOUS_REASON : null);
            throw new BusinessException(PendingPlanningCommandBizService.POSTCONDITION_FAILED_CODE,
                    vacuousEmpty
                            ? "constraint apply postcondition failed: " + EMPTY_PLAN_VACUOUS_REASON
                            + "（方案里没有可比对象（0 条），不算满足）"
                            : "constraint apply postcondition failed: violating=" + violating + "/" + total);
        }
        return report;
    }

    private PlanningUnitDTO asPlanningUnit(OrderedUnitDTO unit) {
        PlanningUnitDTO result = new PlanningUnitDTO();
        if (unit == null) {
            return result;
        }
        result.setUnitId(unit.getUnitId());
        result.setPlanSchoolDataId(unit.getPlanSchoolDataId());
        result.setSchoolId(unit.getSchoolId());
        result.setSchoolName(unit.getSchoolName());
        result.setProvinceName(unit.getProvinceName());
        result.setCityName(unit.getCityName());
        result.setProvinceId(unit.getProvinceId());
        result.setCityId(unit.getCityId());
        result.setSchoolLevel(unit.getSchoolLevel());
        result.setSchoolNature(unit.getSchoolNature());
        result.setSchoolCategory(unit.getSchoolCategory());
        result.setTier(unit.getTier());
        result.setSelectedMajors(unit.getMajorItems());
        return result;
    }

    private int actualCount(PlanningStateDTO state, boolean majorGroupMode) {
        if (majorGroupMode) {
            return state != null && state.getOrderedPlanState() != null
                    && !defaultList(state.getOrderedPlanState().getUnits()).isEmpty()
                    ? state.getOrderedPlanState().getUnits().size()
                    : state != null && state.getWorkingPlanState() != null
                    ? defaultList(state.getWorkingPlanState().getUnits()).size() : 0;
        }
        return state != null && state.getOrderedPlanState() != null
                && !defaultList(state.getOrderedPlanState().getItems()).isEmpty()
                ? state.getOrderedPlanState().getItems().size()
                : state != null && state.getWorkingPlanState() != null
                ? defaultList(state.getWorkingPlanState().getItems()).size() : 0;
    }

    private int populateRequirements(PlanChangePostconditionReportDTO report,
                                     PlanningStateDTO state,
                                     UserGoalFixProposalReq userGoal,
                                     List<CandidateItemDTO> planCandidates,
                                     boolean majorGroupMode) {
        int satisfiedRequirements = 0;
        for (UserGoalFixProposalReq.RequirementDTO requirement : defaultList(userGoal.getRequirements())) {
            PlanChangePostconditionReportDTO.RequirementResultDTO result =
                    new PlanChangePostconditionReportDTO.RequirementResultDTO();
            result.setKind(requirement.getKind());
            result.setDomain(requirement.getDomain());
            result.setKey(requirement.getKey());
            result.setValues(defaultList(requirement.getValues()));
            if (ProjectedHardRequirementSupport.KIND_INCLUDE.equalsIgnoreCase(requirement.getKind())) {
                result.setMinCount(CoverageRequirementSupport.minCount(requirement));
            }
            int matchedCount = postconditionRequirementMatchedCount(
                    state, majorGroupMode, planCandidates, requirement);
            result.setMatchedCount(matchedCount);
            boolean planSatisfied;
            if (planCandidates.isEmpty()) {
                // **三类约束的共同前提：得有对象可比** ✓（2026-09-26 裁决落地 ✓）。
                // 排除类 `noneMatch` ✗ 与包含类 `minCount=0` ✗ 在空方案上都**恒真** ✓——
                // "方案一条不剩"被读成"约束已满足" ✗，是最会误导人的那种自相矛盾 ✗。
                result.setReasonCode(EMPTY_PLAN_VACUOUS_REASON);
                planSatisfied = false;
            } else if (ProjectedHardRequirementSupport.KIND_EXCLUDE.equalsIgnoreCase(requirement.getKind())) {
                planSatisfied = planCandidates.stream()
                        .noneMatch(candidate -> ProjectedHardRequirementSupport.matches(candidate, requirement));
            } else if (ProjectedHardRequirementSupport.KIND_ONLY_KEEP.equalsIgnoreCase(requirement.getKind())) {
                planSatisfied = planCandidates.stream()
                        .allMatch(candidate -> ProjectedHardRequirementSupport.matches(candidate, requirement));
            } else if (ProjectedHardRequirementSupport.KIND_INCLUDE.equalsIgnoreCase(requirement.getKind())) {
                planSatisfied = matchedCount >= CoverageRequirementSupport.minCount(requirement);
            } else {
                planSatisfied = false;
            }
            boolean persisted = ProjectedHardRequirementSupport.isPersisted(state, requirement);
            boolean satisfied = planSatisfied && persisted;
            result.setPlanSatisfied(planSatisfied);
            result.setPersisted(persisted);
            result.setSatisfied(satisfied);
            report.getRequirementResults().add(result);
            if (satisfied) {
                satisfiedRequirements++;
            }
        }
        report.setRequirementCount(report.getRequirementResults().size());
        report.setSatisfiedRequirementCount(satisfiedRequirements);
        return satisfiedRequirements;
    }

    /**
     * 优先规则满足度：**报告口径与生成口径同源** ✓（2026-10-16 40905 定案）。
     *
     * <p>生成侧 `PlanningObjectiveCompiler.compile`（:58-60）在请求不带 `priorityRules` 时**回落
     * state 持久化规则**（`PriorityRuleSupport.confirmedRules` ✓），冻结目标因此带着 `priority:0`；
     * 报告侧以前只遍历请求 ✗ → 请求为空（模型没带规则）时报告里没有这条 objective ⇒
     * `validateCanonicalObjectiveResults` 拿冻结目标找不到对应项 ⇒
     * `40905 frozen objective result mismatch`——"浙江优先"卡（rev15）任何点击必挂 ✗。
     * 修复 = 与生成侧走**同一条回落**：请求里有的规则保留，为空时按 state 已确认规则重建 ✓。
     */
    private int populatePriorityRules(PlanChangePostconditionReportDTO report,
                                      PlanningStateDTO state,
                                      UserGoalFixProposalReq userGoal) {
        int satisfiedPriorityRules = 0;
        List<CandidateItemDTO> candidates = state == null || state.getCandidatePoolState() == null
                ? new ArrayList<CandidateItemDTO>() : defaultList(state.getCandidatePoolState().getItems());
        List<PriorityRuleDTO> effectiveRules = defaultList(userGoal.getPriorityRules());
        if (effectiveRules.isEmpty()) {
            effectiveRules = PriorityRuleSupport.confirmedRules(state);
        }
        for (PriorityRuleDTO rule : effectiveRules) {
            PriorityRuleSupport.Analysis analysis = PriorityRuleSupport.analyze(state, candidates, rule);
            PlanChangePostconditionReportDTO.PriorityRuleResultDTO result =
                    new PlanChangePostconditionReportDTO.PriorityRuleResultDTO();
            result.setDomain(rule.getDomain());
            result.setKey(rule.getKey());
            result.setValues(defaultList(rule.getValues()));
            result.setOrderingTarget(rule.getOrderingTarget());
            result.setScope(rule.getScope());
            result.setMatchedCount(analysis.getMatchedCount());
            result.setInversionCount(analysis.getInversionCount());
            boolean planSatisfied = analysis.getEntityCount() > 0
                    && analysis.getMatchedCount() > 0 && !analysis.hasMissingTier()
                    && analysis.getInversionCount() == 0;
            boolean persisted = PriorityRuleSupport.isPersisted(state, rule);
            boolean satisfied = planSatisfied && persisted;
            result.setPlanSatisfied(planSatisfied);
            result.setPersisted(persisted);
            result.setSatisfied(satisfied);
            report.getPriorityRuleResults().add(result);
            if (satisfied) {
                satisfiedPriorityRules++;
            }
        }
        report.setPriorityRuleCount(report.getPriorityRuleResults().size());
        report.setSatisfiedPriorityRuleCount(satisfiedPriorityRules);
        return satisfiedPriorityRules;
    }

    private boolean populateTierQuota(PlanChangePostconditionReportDTO report,
                                      PlanningStateDTO state,
                                      UserGoalFixProposalReq userGoal,
                                      FixProposalDTO proposal,
                                      List<CandidateItemDTO> planCandidates,
                                      boolean majorGroupMode) {
        TierQuotaChangeDTO change = proposal == null ? null : proposal.getTierQuotaChange();
        boolean legacyRequest = change == null && userGoal.getTierQuotaGoal() != null;
        if (change == null && legacyRequest) {
            TierAllocationSupport.CompiledTierAllocation compiled = TierAllocationSupport.compile(
                    state, userGoal.getTierQuotaGoal(), userGoal.getTargetCount());
            change = new TierQuotaChangeDTO();
            change.setEffectiveGoal(compiled.getEffectiveSourceGoal());
            change.setResolution(compiled.getResolution());
        }
        if (change == null || change.getEffectiveGoal() == null || change.getResolution() == null) {
            return userGoal.getTierQuotaGoal() == null;
        }

        TierCountsDTO actual = counts(
                postconditionTierCount(state, majorGroupMode, planCandidates, "sprint"),
                postconditionTierCount(state, majorGroupMode, planCandidates, "stable"),
                postconditionTierCount(state, majorGroupMode, planCandidates, "protect"));
        TierAllocationConstraintDTO bounds = change.getResolution().getEffectiveBounds();
        boolean planSatisfied = satisfies(actual, bounds);
        boolean persisted = TierAllocationSupport.isPersisted(
                state, change.getEffectiveGoal(), change.getResolution());
        if (!persisted && legacyRequest
                && TierAllocationSupport.TYPE_EXACT_COUNTS.equalsIgnoreCase(
                change.getEffectiveGoal().getType())) {
            persisted = TierAllocationSupport.isLegacyExactPersisted(
                    state, change.getEffectiveGoal());
        }

        PlanChangePostconditionReportDTO.TierQuotaResultDTO result =
                new PlanChangePostconditionReportDTO.TierQuotaResultDTO();
        result.setType(change.getEffectiveGoal().getType());
        TierCountsDTO expected = change.getResolution().getResolvedCounts();
        result.setSprintCount(expected == null
                ? change.getEffectiveGoal().getSprintCount() : expected.getSprintCount());
        result.setStableCount(expected == null
                ? change.getEffectiveGoal().getStableCount() : expected.getStableCount());
        result.setProtectCount(expected == null
                ? change.getEffectiveGoal().getProtectCount() : expected.getProtectCount());
        result.setActualSprintCount(actual.getSprintCount());
        result.setActualStableCount(actual.getStableCount());
        result.setActualProtectCount(actual.getProtectCount());
        result.setEffectiveGoal(TierAllocationSupport.copyGoal(change.getEffectiveGoal()));
        result.setResolution(TierAllocationSupport.copyResolution(change.getResolution()));
        result.setActualCounts(TierAllocationSupport.copyCounts(actual));
        result.setPlanSatisfied(planSatisfied);
        result.setPersisted(persisted);
        result.setSatisfied(planSatisfied && persisted);
        report.setTierQuotaResult(result);
        return Boolean.TRUE.equals(result.getSatisfied());
    }

    private boolean satisfies(TierCountsDTO actual, TierAllocationConstraintDTO bounds) {
        return bounds != null
                && within(actual.getSprintCount(), bounds.getSprint())
                && within(actual.getStableCount(), bounds.getStable())
                && within(actual.getProtectCount(), bounds.getProtect());
    }

    private boolean within(Integer actual, TierCountRangeDTO bound) {
        return actual != null && bound != null
                && (bound.getMinCount() == null || actual >= bound.getMinCount())
                && (bound.getMaxCount() == null || actual <= bound.getMaxCount());
    }

    private PlanSolverResultDTO validateCanonicalFrozenResult(FixProposalApplyReq applyReq,
                                                               PlanningStateDTO state,
                                                               FixProposalDTO proposal) {
        if (!RepairProposalApplyPolicy.hasCanonicalMetadata(applyReq)) {
            return null;
        }
        PlanSolverResultDTO frozen = proposal == null ? null : proposal.getSolverResult();
        boolean metadataMatches = proposal != null && frozen != null
                && Objects.equals(applyReq.getCanonicalObjectiveDigest(), proposal.getCanonicalObjectiveDigest())
                && Objects.equals(applyReq.getSolverVersion(), proposal.getSolverVersion())
                && Objects.equals(applyReq.getSolverInputDigest(), proposal.getSolverInputDigest())
                && Objects.equals(proposal.getSolverVersion(), frozen.getSolverVersion())
                && Objects.equals(proposal.getSolverInputDigest(), frozen.getInputDigest());
        if (!metadataMatches) {
            throw failed("canonical frozen result metadata mismatch");
        }
        CanonicalPlanningObjectiveSetDTO persistedObjectives;
        try {
            persistedObjectives = PlanningObjectiveCompiler.compileConfirmed(state);
        } catch (RuntimeException ex) {
            throw failed("persisted canonical objective invalid");
        }
        if (persistedObjectives == null || !Objects.equals(
                proposal.getCanonicalObjectiveDigest(), persistedObjectives.getObjectiveDigest())) {
            throw failed("persisted canonical objective digest mismatch");
        }
        try {
            CanonicalPlanningRuntime.verifyFrozenState(state, frozen);
        } catch (BusinessException ex) {
            throw failed(ex.getMessage());
        }
        return frozen;
    }

    private void populateCanonicalObjectiveResults(PlanChangePostconditionReportDTO report,
                                                   boolean countRequired,
                                                   boolean countSatisfied) {
        if (countRequired) {
            report.getObjectiveResults().add(objectiveResult(
                    "selection_target", "selection_target", report.getTargetCount(),
                    report.getTargetCount(), report.getActualCount(), countSatisfied));
        }
        int coverageIndex = 0;
        int eligibilityIndex = 0;
        for (PlanChangePostconditionReportDTO.RequirementResultDTO requirement
                : report.getRequirementResults()) {
            boolean coverage = ProjectedHardRequirementSupport.KIND_INCLUDE.equalsIgnoreCase(
                    requirement.getKind());
            report.getObjectiveResults().add(objectiveResult(
                    coverage ? "coverage:" + coverageIndex++ : "eligibility:" + eligibilityIndex++,
                    coverage ? "coverage" : "eligibility",
                    coverage ? requirement.getMinCount() : null,
                    ProjectedHardRequirementSupport.KIND_EXCLUDE.equalsIgnoreCase(requirement.getKind())
                            ? 0 : null,
                    requirement.getMatchedCount(), Boolean.TRUE.equals(requirement.getSatisfied())));
        }
        for (int index = 0; index < report.getPriorityRuleResults().size(); index++) {
            PlanChangePostconditionReportDTO.PriorityRuleResultDTO priority =
                    report.getPriorityRuleResults().get(index);
            report.getObjectiveResults().add(objectiveResult(
                    "priority:" + index, "priority_within_tier", 0, 0,
                    priority.getInversionCount(), Boolean.TRUE.equals(priority.getSatisfied())));
        }
        PlanChangePostconditionReportDTO.TierQuotaResultDTO quota = report.getTierQuotaResult();
        if (quota != null && quota.getResolution() != null
                && quota.getResolution().getEffectiveBounds() != null) {
            TierAllocationConstraintDTO bounds = quota.getResolution().getEffectiveBounds();
            String type = TierAllocationSupport.TYPE_COUNT_RANGES.equalsIgnoreCase(quota.getType())
                    ? "tier_range" : "tier_exact";
            report.getObjectiveResults().add(tierObjective("sprint", type, bounds.getSprint(),
                    quota.getActualSprintCount()));
            report.getObjectiveResults().add(tierObjective("stable", type, bounds.getStable(),
                    quota.getActualStableCount()));
            report.getObjectiveResults().add(tierObjective("protect", type, bounds.getProtect(),
                    quota.getActualProtectCount()));
        }
    }

    private PlanSolverResultDTO.ObjectiveResultDTO tierObjective(String tier,
                                                                 String type,
                                                                 TierCountRangeDTO bound,
                                                                 Integer actual) {
        boolean satisfied = within(actual, bound);
        return objectiveResult("tier:" + tier, type,
                bound == null ? null : bound.getMinCount(),
                bound == null ? null : bound.getMaxCount(), actual, satisfied);
    }

    private void validateCanonicalObjectiveResults(PlanChangePostconditionReportDTO report,
                                                   PlanSolverResultDTO frozen) {
        if (frozen == null) {
            return;
        }
        for (PlanSolverResultDTO.ObjectiveResultDTO expected : defaultList(frozen.getObjectiveResults())) {
            PlanSolverResultDTO.ObjectiveResultDTO actual = report.getObjectiveResults().stream()
                    .filter(item -> item != null && expected != null
                            && Objects.equals(expected.getObjectiveId(), item.getObjectiveId()))
                    .findFirst().orElse(null);
            if (actual == null && expected != null
                    && "selection_target".equals(expected.getObjectiveType())) {
                Integer count = report.getActualCount();
                boolean satisfied = count != null
                        && (expected.getRequiredMin() == null || count >= expected.getRequiredMin())
                        && (expected.getRequiredMax() == null || count <= expected.getRequiredMax());
                actual = objectiveResult(expected.getObjectiveId(), expected.getObjectiveType(),
                        expected.getRequiredMin(), expected.getRequiredMax(), count, satisfied);
            }
            if (expected == null || actual == null
                    || !Objects.equals(expected.getObjectiveType(), actual.getObjectiveType())
                    || !Objects.equals(expected.getRequiredMin(), actual.getRequiredMin())
                    || !Objects.equals(expected.getRequiredMax(), actual.getRequiredMax())
                    || !Objects.equals(expected.getActualCount(), actual.getActualCount())
                    || !Boolean.TRUE.equals(expected.getSatisfied())
                    || !Boolean.TRUE.equals(actual.getSatisfied())) {
                throw failed("frozen objective result mismatch");
            }
        }
        report.setObjectiveResults(new ArrayList<PlanSolverResultDTO.ObjectiveResultDTO>(
                defaultList(frozen.getObjectiveResults())));
    }

    private PlanSolverResultDTO.ObjectiveResultDTO objectiveResult(String id,
                                                                   String type,
                                                                   Integer requiredMin,
                                                                   Integer requiredMax,
                                                                   Integer actual,
                                                                   boolean satisfied) {
        PlanSolverResultDTO.ObjectiveResultDTO result = new PlanSolverResultDTO.ObjectiveResultDTO();
        result.setObjectiveId(id);
        result.setObjectiveType(type);
        result.setRequiredMin(requiredMin);
        result.setRequiredMax(requiredMax);
        result.setActualCount(actual);
        result.setSatisfied(satisfied);
        return result;
    }

    private PlanChangePostconditionReportDTO verifyReviewFixPostcondition(
            PendingPlanningCommandReq req,
            FixProposalApplyRes applyRes) {
        FixProposalApplyReq applyReq = req == null ? null : req.getProposalApply();
        FixProposalDTO proposal = applyRes == null ? null : applyRes.getProposal();
        RepairReportDTO repairReport = applyRes == null ? null : applyRes.getRepairReport();
        PlanChangePostconditionReportDTO report = new PlanChangePostconditionReportDTO();
        report.setProposalSource(proposal == null ? null : proposal.getProposalSource());
        report.setProposalId(proposal == null ? null : proposal.getProposalId());
        report.setProposalStrategy(proposal == null ? null : proposal.getStrategy());
        report.setGoalType(proposal == null ? null : proposal.getStrategy());
        if (repairReport != null) {
            report.setSourceReviewIssueCodes(defaultList(repairReport.getSourceCheckCodes()));
            report.setPostValidationPassed(repairReport.getPostValidationPassed());
            report.setAppliedActionCount(repairReport.getAppliedActionCount());
            report.setAffectedUnitCount(repairReport.getAffectedUnitCount());
            report.setAddedVolunteerCount(repairReport.getAddedVolunteerCount());
            report.setRemovedVolunteerCount(repairReport.getRemovedVolunteerCount());
        }
        boolean applied = applyRes != null && "applied".equalsIgnoreCase(applyRes.getStatus());
        boolean proposalMatches = proposal != null && applyReq != null
                && Objects.equals(applyReq.getProposalId(), proposal.getProposalId())
                && RepairProposalTaxonomy.normalizeProposalSource(applyReq.getProposalSource()).equals(
                RepairProposalTaxonomy.normalizeProposalSource(proposal.getProposalSource()));
        boolean postValidationPassed = repairReport != null
                && Boolean.TRUE.equals(repairReport.getPostValidationPassed());
        report.setSatisfied(applied && proposalMatches && postValidationPassed);
        if (!Boolean.TRUE.equals(report.getSatisfied())) {
            throw new BusinessException(PendingPlanningCommandBizService.POSTCONDITION_FAILED_CODE,
                    "review fix postcondition failed: applied=" + applied
                            + " proposalMatches=" + proposalMatches
                            + " postValidationPassed=" + postValidationPassed);
        }
        return report;
    }

    private int postconditionTierCount(PlanningStateDTO state,
                                       boolean majorGroupMode,
                                       List<CandidateItemDTO> planCandidates,
                                       String expectedTier) {
        if (majorGroupMode && state != null && state.getOrderedPlanState() != null
                && !defaultList(state.getOrderedPlanState().getUnits()).isEmpty()) {
            return (int) defaultList(state.getOrderedPlanState().getUnits()).stream()
                    .filter(unit -> expectedTier.equals(TierAllocationSupport.canonicalTierKey(
                            unit == null ? null : unit.getTier())))
                    .count();
        }
        return (int) defaultList(planCandidates).stream()
                .filter(candidate -> expectedTier.equals(TierAllocationSupport.canonicalTierKey(
                        candidate == null ? null : candidate.getTier())))
                .count();
    }

    private int postconditionRequirementMatchedCount(
            PlanningStateDTO state,
            boolean majorGroupMode,
            List<CandidateItemDTO> planCandidates,
            UserGoalFixProposalReq.RequirementDTO requirement) {
        if (!majorGroupMode
                || !ProjectedHardRequirementSupport.KIND_INCLUDE.equalsIgnoreCase(requirement.getKind())) {
            return (int) defaultList(planCandidates).stream()
                    .filter(candidate -> ProjectedHardRequirementSupport.matches(candidate, requirement))
                    .count();
        }
        List<CandidateItemDTO> pool = state == null || state.getCandidatePoolState() == null
                ? new ArrayList<CandidateItemDTO>() : defaultList(state.getCandidatePoolState().getItems());
        List<OrderedUnitDTO> units = state == null || state.getOrderedPlanState() == null
                ? new ArrayList<OrderedUnitDTO>() : defaultList(state.getOrderedPlanState().getUnits());
        if (!units.isEmpty()) {
            int matchedUnits = 0;
            for (OrderedUnitDTO unit : units) {
                List<PlanningUnitMajorDTO> majors = defaultList(unit == null ? null : unit.getMajorItems());
                boolean matched = majors.isEmpty()
                        ? ProjectedHardRequirementSupport.matches(postconditionCandidate(unit, null), requirement)
                        : majors.stream().anyMatch(major -> {
                            CandidateItemDTO candidate = RepairCandidateSelector.findCandidate(
                                    pool, major == null ? null : major.getVolunteerId());
                            return ProjectedHardRequirementSupport.matches(
                                    candidate == null ? postconditionCandidate(unit, major) : candidate,
                                    requirement);
                        });
                if (matched) {
                    matchedUnits++;
                }
            }
            return matchedUnits;
        }
        List<String> matchedUnitIds = new ArrayList<String>();
        for (CandidateItemDTO candidate : defaultList(planCandidates)) {
            if (ProjectedHardRequirementSupport.matches(candidate, requirement)) {
                String unitId = RepairCandidateSelector.resolveInitialRecommendationUnitId(candidate);
                if (!Strings.isNullOrEmpty(unitId) && !matchedUnitIds.contains(unitId)) {
                    matchedUnitIds.add(unitId);
                }
            }
        }
        return matchedUnitIds.size();
    }

    private List<CandidateItemDTO> postconditionPlanCandidates(
            PlanningStateDTO state,
            boolean majorGroupMode) {
        List<CandidateItemDTO> result = new ArrayList<CandidateItemDTO>();
        List<CandidateItemDTO> pool = state == null || state.getCandidatePoolState() == null
                ? new ArrayList<CandidateItemDTO>() : defaultList(state.getCandidatePoolState().getItems());
        if (majorGroupMode && state != null && state.getOrderedPlanState() != null) {
            for (OrderedUnitDTO unit : defaultList(state.getOrderedPlanState().getUnits())) {
                for (PlanningUnitMajorDTO major : defaultList(unit == null ? null : unit.getMajorItems())) {
                    CandidateItemDTO candidate = RepairCandidateSelector.findCandidate(
                            pool, major == null ? null : major.getVolunteerId());
                    result.add(candidate == null ? postconditionCandidate(unit, major) : candidate);
                }
            }
            return result;
        }
        if (state != null && state.getOrderedPlanState() != null
                && !defaultList(state.getOrderedPlanState().getItems()).isEmpty()) {
            for (OrderedItemDTO item : defaultList(state.getOrderedPlanState().getItems())) {
                CandidateItemDTO candidate = RepairCandidateSelector.findCandidate(
                        pool, item == null ? null : item.getVolunteerId());
                if (candidate != null) {
                    result.add(candidate);
                } else {
                    CandidateItemDTO fallback = new CandidateItemDTO();
                    fallback.setVolunteerId(item == null ? null : item.getVolunteerId());
                    fallback.setSchoolName(item == null ? null : item.getSchoolName());
                    fallback.setDisplaySchoolName(item == null ? null : item.getSchoolName());
                    fallback.setMajorName(item == null ? null : item.getMajorName());
                    fallback.setTier(item == null ? null : item.getTier());
                    result.add(fallback);
                }
            }
            return result;
        }
        if (state != null && state.getWorkingPlanState() != null) {
            for (DraftItemDTO item : defaultList(state.getWorkingPlanState().getItems())) {
                CandidateItemDTO candidate = RepairCandidateSelector.findCandidate(
                        pool, item == null ? null : item.getVolunteerId());
                if (candidate != null) {
                    result.add(candidate);
                }
            }
        }
        return result;
    }

    private CandidateItemDTO postconditionCandidate(OrderedUnitDTO unit, PlanningUnitMajorDTO major) {
        CandidateItemDTO candidate = new CandidateItemDTO();
        candidate.setVolunteerId(major == null ? null : major.getVolunteerId());
        candidate.setPlanSchoolDataId(unit == null ? null : unit.getUnitId());
        candidate.setSchoolName(unit == null ? null : unit.getSchoolName());
        candidate.setDisplaySchoolName(unit == null ? null : unit.getSchoolName());
        candidate.setProvinceName(unit == null ? null : unit.getProvinceName());
        candidate.setProvinceId(unit == null ? null : unit.getProvinceId());
        candidate.setCityId(unit == null ? null : unit.getCityId());
        candidate.setCityName(unit == null ? null : unit.getCityName());
        candidate.setSchoolNature(unit == null ? null : unit.getSchoolNature());
        candidate.setSchoolCategory(unit == null ? null : unit.getSchoolCategory());
        candidate.setSchoolLevel(unit == null ? null : unit.getSchoolLevel());
        candidate.setTier(unit == null ? null : unit.getTier());
        candidate.setMajorName(major == null ? null : major.getMajorName());
        candidate.setMajorCategoryId(major == null ? null : major.getMajorCategoryId());
        candidate.setMajorSubCategoryId(major == null ? null : major.getMajorSubCategoryId());
        // 分类名一路带上 ✓：满足度判据与筛选同源（`RepairCandidateEligibility` 按分类名比对 ✓）。
        candidate.setMajorCategory(major == null ? null : major.getMajorCategory());
        candidate.setMajorDiscipline(major == null ? null : major.getMajorDiscipline());
        candidate.setMajorPlanTags(major == null ? new ArrayList<String>() : defaultList(major.getMajorPlanTags()));
        candidate.setReasonCodes(major == null ? new ArrayList<String>() : defaultList(major.getReasonCodes()));
        candidate.setTuitionPerYear(major == null ? null : major.getTuitionPerYear());
        return candidate;
    }

    private TierCountsDTO counts(int sprint, int stable, int protect) {
        TierCountsDTO result = new TierCountsDTO();
        result.setSprintCount(sprint);
        result.setStableCount(stable);
        result.setProtectCount(protect);
        return result;
    }

    private BusinessException failed(String detail) {
        return new BusinessException(PendingPlanningCommandBizService.POSTCONDITION_FAILED_CODE,
                "plan change postcondition failed: " + detail);
    }

    private <T> List<T> defaultList(List<T> values) {
        return values == null ? new ArrayList<T>() : values;
    }
}
