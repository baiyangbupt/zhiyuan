package com.ytell.zhiyuan.service.biz;

import com.alibaba.fastjson.JSON;
import com.google.common.base.Strings;
import com.google.common.collect.Lists;
import com.google.common.collect.Maps;
import com.ytell.zhiyuan.model.dto.planning.CandidateFactDTO;
import com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO;
import com.ytell.zhiyuan.model.dto.planning.CandidateSnapshotDTO;
import com.ytell.zhiyuan.model.dto.planning.CanonicalPlanningObjectiveSetDTO;
import com.ytell.zhiyuan.model.dto.planning.CoverageRequirementDTO;
import com.ytell.zhiyuan.model.dto.planning.DiversityPolicyDTO;
import com.ytell.zhiyuan.model.dto.planning.HardConstraintsDTO;
import com.ytell.zhiyuan.model.dto.planning.MutationPolicyDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanSolverResultDTO;
import com.ytell.zhiyuan.model.dto.planning.StructureTargetDTO;
import com.ytell.zhiyuan.model.dto.planning.TierAllocationConstraintDTO;
import com.ytell.zhiyuan.model.dto.planning.TierCountRangeDTO;
import com.ytell.zhiyuan.model.dto.planning.TierCountsDTO;
import org.ojalgo.optimisation.Expression;
import org.ojalgo.optimisation.ExpressionsBasedModel;
import org.ojalgo.optimisation.Optimisation;
import org.ojalgo.optimisation.Variable;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.math.BigDecimal;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.Comparator;
import java.util.IdentityHashMap;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * J5.3 分阶段字典序选择器（shadow 版）。
 *
 * <p>顺序：safety 缺口 → churn + 档位锚 → utility（stable 仅平局）。
 * 本类暂不接运行时，也不实现 diversity/候选帽 reducer；用于 S0a 影子与
 * 单元测试。所有阶段共用同一模型，阶段最优值用纯层表达式固定。</p>
 */
final class StagedDeterministicPlanSolver {

    private static final Logger LOG = LoggerFactory.getLogger(StagedDeterministicPlanSolver.class);

    static final String SOLVER_VERSION = "ojalgo-48.4.2-j53-staged";
    static final String HARD_OBJECTIVE_VERSION = "solver-hard-objective-v1";
    private static final long TIME_BUDGET_MS = 2_000L;
    private static final int ITERATION_BUDGET = 100_000;
    private static final int MAX_CANDIDATES = 600;
    private static final List<String> TIERS = Arrays.asList("sprint", "stable", "protect");
    /** 最近一次 solvePhase 的耗时；阶段值写入 stageResults 时按序取用。 */
    private long lastPhaseDurationMs;
    // 分组截断顺序：(candidateCount ↓, key ↑)，保证同输入同保留集合。
    private static final Comparator<DiversityGroup> DIVERSITY_GROUP_ORDER =
            Comparator.comparingInt((DiversityGroup group) -> group.factIndexes.size())
                    .reversed()
                    .thenComparing(group -> group.key);

    Result solve(CandidateSnapshotDTO snapshot,
                 CanonicalPlanningObjectiveSetDTO objectives,
                 MutationPolicyDTO policy) {
        long started = System.nanoTime();
        CandidateSnapshotDTO safeSnapshot = snapshot == null ? new CandidateSnapshotDTO() : snapshot;
        CanonicalPlanningObjectiveSetDTO safeObjectives = objectives == null
                ? new CanonicalPlanningObjectiveSetDTO() : objectives;
        MutationPolicyDTO safePolicy = policy == null ? new MutationPolicyDTO() : policy;
        PlanSolverResultDTO result = baseResult(safeObjectives, safeSnapshot);
        if (safeObjectives.getTargetCount() == null || safeObjectives.getTargetCount() < 0) {
            return blocked(result, started, "solver_input_invalid", null,
                    "canonical objective set 和非负 targetCount 必须存在。");
        }
        if (!Strings.isNullOrEmpty(safeSnapshot.getCountMode())
                && !Strings.isNullOrEmpty(safeObjectives.getCountMode())
                && !safeSnapshot.getCountMode().equalsIgnoreCase(safeObjectives.getCountMode())) {
            return blocked(result, started, "solver_input_invalid", null,
                    "snapshot countMode 与 objective set countMode 不一致。");
        }
        CandidatePoolReducer.Reduction reduction = null;
        List<CandidateFactDTO> facts;
        if (defaultList(safeSnapshot.getFacts()).size() > MAX_CANDIDATES) {
            reduction = CandidatePoolReducer.reduce(
                    safeSnapshot, safeObjectives, safePolicy, MAX_CANDIDATES);
            if (reduction.coreOverLimit) {
                return blocked(result, started, "candidate_cap_core_over_limit", null,
                        "mandatory/witness 超过候选帽：original="
                                + reduction.candidateCountOriginal + ", mandatory="
                                + reduction.mandatorySize + ", solved="
                                + reduction.candidateCountSolved);
            }
            facts = canonicalFacts(reduction.facts);
        } else {
            facts = canonicalFacts(safeSnapshot.getFacts());
        }
        result.setCandidateCount(facts.size());
        String invalid = validateFacts(facts);
        if (invalid != null) {
            return blocked(result, started, "candidate_fact_invalid", null, invalid);
        }
        int targetCount = safeObjectives.getTargetCount();
        List<CandidateFactDTO> eligible = new ArrayList<CandidateFactDTO>();
        List<CandidateFactDTO> locked = new ArrayList<CandidateFactDTO>();
        for (CandidateFactDTO fact : facts) {
            if (isEligible(fact, safeObjectives, safePolicy)) {
                eligible.add(fact);
            }
            if (Boolean.TRUE.equals(fact.getLocked()) || Boolean.TRUE.equals(fact.getPinned())) {
                locked.add(fact);
            }
        }
        if (eligible.size() < targetCount) {
            return blocked(result, started,
                    reduction != null && !reduction.witnessAvailable
                            ? "solver_infeasible_after_cap" : "candidate_shortage",
                    "selection_target",
                    reduction != null && !reduction.witnessAvailable
                            ? "候选帽内无法构造可行 witness，不能断言全量池候选不足。"
                            : "符合硬要求的候选不足，无法达到目标总数。");
        }
        if (locked.size() > targetCount) {
            return blocked(result, started, "locked_conflict", null,
                    "锁定/置顶项目数量超过目标总数。");
        }
        String policyError = validatePolicy(facts, safePolicy, safeObjectives);
        if (policyError != null) {
            return blocked(result, started, "mutation_policy_conflict", null, policyError);
        }

        ExpressionsBasedModel model = new ExpressionsBasedModel();
        List<Variable> variables = new ArrayList<Variable>();
        for (CandidateFactDTO fact : facts) {
            Variable variable = Variable.makeBinary("entity_" + fact.getStableOrder());
            variable.weight(BigDecimal.ZERO);
            if (!isEligible(fact, safeObjectives, safePolicy)) {
                variable.upper(0);
            }
            if (mustSelect(fact, safePolicy)) {
                variable.lower(1).upper(1);
            }
            if (mustRemove(fact, safePolicy)) {
                if (mustSelect(fact, safePolicy)) {
                    return blocked(result, started, "mutation_policy_conflict", null,
                            "同一实体同时被要求选择与移除：" + fact.getEntityId());
                }
                variable.upper(0);
            }
            model.addVariable(variable);
            variables.add(variable);
        }

        Expression target = model.addExpression("selection_target").level(targetCount);
        for (Variable variable : variables) {
            target.set(variable, 1);
        }
        String coverageError = addCoverage(model, variables, facts, safeObjectives);
        if (coverageError != null) {
            return blocked(result, started, "coverage_infeasible", null, coverageError);
        }
        TierAllocationConstraintDTO tierConstraint = canonicalTierConstraint(
                safeObjectives.getTierAllocationConstraint(), targetCount);
        addTierConstraints(model, variables, facts, tierConstraint);

        List<ObjectiveLevel> levels = new ArrayList<ObjectiveLevel>();
        List<Long> levelDurations = new ArrayList<Long>();
        long deadline = started + TIME_BUDGET_MS * 1_000_000L;

        int minLocalProtect = minLocalProtect(safeObjectives, safeSnapshot);
        Expression safetyObjective = null;
        Variable safetyDeficit = null;
        if (minLocalProtect > 0) {
            safetyDeficit = Variable.make("safety_deficit").integer(true)
                    .lower(0).upper(minLocalProtect);
            model.addVariable(safetyDeficit);
            Expression balance = model.addExpression("safety_balance").lower(minLocalProtect);
            for (int index = 0; index < facts.size(); index++) {
                if (isLocalProtect(facts.get(index), safeSnapshot.getSourceProvince())) {
                    balance.set(variables.get(index), 1);
                }
            }
            balance.set(safetyDeficit, 1);
            safetyObjective = model.addExpression("safety_objective").weight(1);
            safetyObjective.set(safetyDeficit, 1);
            Optimisation.Result safetySolved = solvePhase(model, deadline, "safety");
            if (safetySolved == null || !safetySolved.getState().isOptimal()) {
                return blocked(result, started, phaseFailureReason(reduction, safetySolved), "safety",
                        "保底阶段未证明最优"
                                + (safetySolved == null ? "" : "，solverState=" + safetySolved.getState()));
            }
            int deficit = localProtectDeficit(facts, variables, safetySolved, safeSnapshot.getSourceProvince(),
                    minLocalProtect);
            levels.add(new ObjectiveLevel("safety", deficit, deficit, "deficit_points"));
            levelDurations.add(lastPhaseDurationMs);
            safetyObjective.weight(0);
            Expression fixSafety = model.addExpression("fix_safety").upper(deficit);
            fixSafety.set(safetyDeficit, 1);
        }

        Expression churnExpression = null;
        Expression tierObjective = null;
        int currentCount = 0;
        List<Variable> tierDeviationVariables = new ArrayList<Variable>();
        TierCountsDTO anchor = structureAnchor(facts, safeObjectives, tierConstraint, targetCount);
        result.setHistoricalTierAnchor(anchor);
        // 锚位计数若为负（上游数据异常），按 0 估算偏差上界，避免低估 churn 权重
        // 后让 utility 阶段越过 churn/tier 的最优值。
        int anchorSum = 0;
        for (String tier : TIERS) {
            anchorSum += Math.max(0, tierCount(anchor, tier));
        }
        int maxTierDeviation = targetCount + anchorSum;
        long churnWeight = Math.max(1L, (long) maxTierDeviation + 1L);
        boolean churnApplicable = Boolean.TRUE.equals(safePolicy.getCountAsChurn());
        boolean tierApplicable = anchor != null;
        if (churnApplicable || tierApplicable) {
            if (churnApplicable) {
                churnExpression = model.addExpression("churn_expression")
                        .weight(BigDecimal.valueOf(churnWeight));
                currentCount = (int) facts.stream().filter(fact -> Boolean.TRUE.equals(fact.getCurrent())).count();
                for (int index = 0; index < facts.size(); index++) {
                    if (Boolean.TRUE.equals(facts.get(index).getCurrent())) {
                        churnExpression.set(variables.get(index), -1);
                    }
                }
            }
            if (tierApplicable) {
                tierObjective = model.addExpression("tier_objective").weight(1);
                for (String tier : TIERS) {
                    Variable positive = Variable.make("tier_deviation_positive_" + tier)
                            .integer(true).lower(0).upper(targetCount);
                    Variable negative = Variable.make("tier_deviation_negative_" + tier)
                            .integer(true).lower(0).upper(targetCount);
                    model.addVariable(positive);
                    model.addVariable(negative);
                    tierDeviationVariables.add(positive);
                    tierDeviationVariables.add(negative);
                    Expression balance = model.addExpression("tier_anchor:" + tier)
                            .level(tierCount(anchor, tier));
                    for (int index = 0; index < facts.size(); index++) {
                        if (tier.equals(facts.get(index).getTier())) {
                            balance.set(variables.get(index), 1);
                        }
                    }
                    balance.set(positive, -1);
                    balance.set(negative, 1);
                    tierObjective.set(positive, BigDecimal.ONE);
                    tierObjective.set(negative, BigDecimal.ONE);
                }
                result.setHistoricalTierAnchor(anchor);
            }
            Optimisation.Result mixedSolved = solvePhase(model, deadline, "churn_tier");
            if (mixedSolved == null || !mixedSolved.getState().isOptimal()) {
                return blocked(result, started, phaseFailureReason(reduction, mixedSolved), "churn_tier",
                        "churn/档位阶段未证明最优"
                                + (mixedSolved == null ? "" : "，solverState=" + mixedSolved.getState()));
            }
            int churnValue = churnValue(facts, variables, mixedSolved);
            int tierDeviation = tierDeviation(anchor, facts, variables, mixedSolved);
            if (churnApplicable) {
                levels.add(new ObjectiveLevel("churn", churnValue, churnValue, "removed_entities"));
                levelDurations.add(lastPhaseDurationMs);
            }
            if (tierApplicable) {
                levels.add(new ObjectiveLevel("tier_anchor", tierDeviation, tierDeviation, "deviation_points"));
                levelDurations.add(lastPhaseDurationMs);
            }
            if (churnExpression != null) {
                churnExpression.weight(0);
            }
            if (tierObjective != null) {
                tierObjective.weight(0);
            }
            long mixedValue = (churnApplicable ? -churnWeight * (currentCount - churnValue) : 0L)
                    + tierDeviation;
            Expression fixMixed = model.addExpression("fix_mixed").upper(mixedValue);
            if (churnApplicable) {
                for (int index = 0; index < facts.size(); index++) {
                    if (Boolean.TRUE.equals(facts.get(index).getCurrent())) {
                        fixMixed.set(variables.get(index), -churnWeight);
                    }
                }
            }
            for (Variable variable : tierDeviationVariables) {
                fixMixed.set(variable, BigDecimal.ONE);
            }
        }

        long maxStableTotal = Math.max(0L, (long) facts.size() * Math.max(0, facts.size() - 1));
        long utilityWeight = maxStableTotal + 1L;
        Expression utilityObjective = model.addExpression("utility_objective")
                .weight(BigDecimal.valueOf(-utilityWeight));
        for (int index = 0; index < facts.size(); index++) {
            int utility = facts.get(index).getUtilityScore() == null ? 0 : facts.get(index).getUtilityScore();
            utilityObjective.set(variables.get(index), BigDecimal.valueOf(utility));
        }
        Expression stableObjective = model.addExpression("stable_objective").weight(1);
        for (int index = 0; index < facts.size(); index++) {
            stableObjective.set(variables.get(index),
                    BigDecimal.valueOf(Math.max(0, facts.get(index).getStableOrder())));
        }
        Optimisation.Result utilitySolved = solvePhase(model, deadline, "utility");
        if (utilitySolved == null || !utilitySolved.getState().isOptimal()) {
            return blocked(result, started, phaseFailureReason(reduction, utilitySolved), "utility",
                    "效用阶段未证明最优"
                            + (utilitySolved == null ? "" : "，solverState=" + utilitySolved.getState()));
        }
        int utilityValue = utilityValue(facts, variables, utilitySolved);
        levels.add(new ObjectiveLevel("utility", utilityValue, utilityValue, "utility_points"));
        levelDurations.add(lastPhaseDurationMs);
        utilityObjective.weight(0);
        stableObjective.weight(0);

        Optimisation.Result finalSolved = utilitySolved;
        DiversityPolicyDTO diversity = safeObjectives.getDiversityPolicy();
        if (diversity != null && "soft".equalsIgnoreCase(
                Strings.nullToEmpty(diversity.getMode()).trim())) {
            // P3 只固定纯 utility 表达式；stable 留到 P4 做次级交换。
            Expression fixUtility = model.addExpression("fix_utility").level(utilityValue);
            for (int index = 0; index < facts.size(); index++) {
                int utility = facts.get(index).getUtilityScore() == null
                        ? 0 : facts.get(index).getUtilityScore();
                fixUtility.set(variables.get(index), BigDecimal.valueOf(utility));
            }
            Set<CandidateFactDTO> eligibleFacts = Collections.newSetFromMap(
                    new IdentityHashMap<CandidateFactDTO, Boolean>());
            eligibleFacts.addAll(eligible);
            List<DiversityGroup> groups = diversityGroups(facts, eligibleFacts, safePolicy);
            int maxGroups = diversity.getMaxGroups() == null
                    ? 32 : Math.max(0, diversity.getMaxGroups());
            if (groups.size() > maxGroups) {
                groups.sort(DIVERSITY_GROUP_ORDER);
                int originalGroups = groups.size();
                groups = new ArrayList<DiversityGroup>(groups.subList(0, maxGroups));
                PlanSolverResultDTO.DiagnosticDTO truncated = new PlanSolverResultDTO.DiagnosticDTO();
                truncated.setReasonCode("diversity_group_truncated");
                truncated.setObjectiveId("diversity");
                truncated.setMessage("groups=" + originalGroups + ", retained=" + maxGroups
                        + ", dropped=" + (originalGroups - maxGroups));
                result.getDiagnostics().add(truncated);
            }
            if (groups.isEmpty()) {
                levels.add(new ObjectiveLevel("diversity", 0L, 0L, "excess_count"));
                levelDurations.add(0L);
            } else {
                Expression diversityObjective = model.addExpression("diversity_objective")
                        .weight(BigDecimal.valueOf(utilityWeight));
                List<Variable> excessVariables = new ArrayList<Variable>();
                for (int index = 0; index < groups.size(); index++) {
                    DiversityGroup group = groups.get(index);
                    group.cap = diversityCap(group.dimension, diversity, targetCount);
                    Variable excess = Variable.make("diversity_excess_" + index)
                            .integer(true).lower(0).upper(targetCount);
                    model.addVariable(excess);
                    excessVariables.add(excess);
                    Expression capExpression = model.addExpression("diversity_cap:" + index)
                            .upper(group.cap);
                    for (Integer factIndex : group.factIndexes) {
                        capExpression.set(variables.get(factIndex), 1);
                    }
                    capExpression.set(excess, -1);
                    diversityObjective.set(excess, BigDecimal.ONE);
                }
                stableObjective.weight(1);
                Optimisation.Result diversitySolved = solvePhase(model, deadline, "diversity");
                if (diversitySolved == null || !diversitySolved.getState().isOptimal()) {
                    return blocked(result, started, phaseFailureReason(reduction, diversitySolved),
                            "diversity", "多样性阶段未证明最优"
                                    + (diversitySolved == null ? "" : "，solverState="
                                    + diversitySolved.getState()));
                }
                int diversityValue = diversityExcess(groups, diversitySolved);
                levels.add(new ObjectiveLevel("diversity", diversityValue, diversityValue,
                        "excess_count"));
                levelDurations.add(lastPhaseDurationMs);
                diversityObjective.weight(0);
                Expression fixDiversity = model.addExpression("fix_diversity").level(diversityValue);
                for (Variable excess : excessVariables) {
                    fixDiversity.set(excess, 1);
                }
            }
            stableObjective.weight(1);
            Optimisation.Result stableSolved = solvePhase(model, deadline, "diversity_stable");
            if (stableSolved == null || !stableSolved.getState().isOptimal()) {
                return blocked(result, started, phaseFailureReason(reduction, stableSolved),
                        "diversity", "多样性平局阶段未证明最优"
                                + (stableSolved == null ? "" : "，solverState="
                                + stableSolved.getState()));
            }
            finalSolved = stableSolved;
        }

        List<CandidateFactDTO> selected = selectedFacts(facts, variables, finalSolved);
        List<CandidateFactDTO> ordered = orderSelected(selected);
        result.setSelectedEntityIds(ids(selected));
        result.setOrderedEntityIds(ids(ordered));
        // 候选帽降维后 reduced facts 可能不含全部 current；移出名单必须按原始快照算，
        // 否则被 reducer 丢掉的存量行不会被删除，apply 后总数会悄悄多出来。
        result.setRemoveEntityIds(currentIds(defaultList(safeSnapshot.getFacts()), selected));
        result.setAddEntityIds(selected.stream()
                .filter(fact -> !Boolean.TRUE.equals(fact.getCurrent()))
                .map(CandidateFactDTO::getEntityId)
                .collect(java.util.stream.Collectors.toList()));
        result.setResolvedTierCounts(tierCounts(selected));
        populateObjectiveResults(result, safeObjectives, selected);
        result.setStatus("ready");
        result.setSolverState(finalSolved.getState().toString());
        result.setSolverVersion(SOLVER_VERSION);
        result.setInputDigest(inputDigest(safeSnapshot, safeObjectives, safePolicy));
        result.setDurationMs(elapsedMillis(started));
        populateStageResults(result, levels, levelDurations);
        LOG.info("staged solver ready: sourceVersion={} candidates={} selected={} durationMs={} stages={}",
                safeSnapshot == null ? null : safeSnapshot.getSourceVersion(),
                facts.size(), selected.size(), result.getDurationMs(), stageSummary(levels));
        if (reduction != null) {
            PlanSolverResultDTO.DiagnosticDTO cap = new PlanSolverResultDTO.DiagnosticDTO();
            cap.setReasonCode("candidate_cap_applied");
            cap.setMessage("original=" + reduction.candidateCountOriginal
                    + ", solved=" + reduction.candidateCountSolved
                    + ", dropped=" + reduction.droppedCount
                    + ", witnessAvailable=" + reduction.witnessAvailable
                    + ", protectionBudgetTruncated=" + reduction.protectionBudgetTruncated);
            result.getDiagnostics().add(cap);
        }
        return new Result(result, levels);
    }

    private String validatePolicy(List<CandidateFactDTO> facts,
                                  MutationPolicyDTO policy,
                                  CanonicalPlanningObjectiveSetDTO objectives) {
        for (CandidateFactDTO fact : facts) {
            // 锁定/置顶、lockExisting 的 current 会被强制选中；如果它已经不合格，
            // 继续求解只会让 apply 的 FrozenSelectionGuard 拒绝（预览 ready/确认 409）。
            // 在预览阶段 fail-closed，给出可操作原因。
            if (mustSelect(fact, policy) && !isEligible(fact, objectives, policy)) {
                return "锁定/置顶或必须保留的实体已不满足硬要求：" + fact.getEntityId();
            }
        }
        Set<String> required = new LinkedHashSet<String>();
        required.addAll(policy.getFrozenRequiredEntityIds());
        required.addAll(policy.getForcedAddEntityIds());
        for (String id : required) {
            CandidateFactDTO fact = fact(facts, id);
            if (fact == null) {
                return "required 实体不存在：" + id;
            }
            if (!isEligible(fact, objectives, policy)) {
                return "required 实体不满足硬要求：" + id;
            }
        }
        for (String id : policy.getForcedRemoveEntityIds()) {
            if (required.contains(id)) {
                return "实体同时被要求选择与移除：" + id;
            }
            CandidateFactDTO fact = fact(facts, id);
            if (fact == null) {
                return "forcedRemove 实体不存在：" + id;
            }
            if (Boolean.TRUE.equals(fact.getLocked()) || Boolean.TRUE.equals(fact.getPinned())) {
                return "锁定/置顶实体不能被 forcedRemove：" + id;
            }
        }
        return null;
    }

    private boolean mustSelect(CandidateFactDTO fact, MutationPolicyDTO policy) {
        return Boolean.TRUE.equals(fact.getLocked())
                || Boolean.TRUE.equals(fact.getPinned())
                || policy.getFrozenRequiredEntityIds().contains(fact.getEntityId())
                || policy.getForcedAddEntityIds().contains(fact.getEntityId())
                || (Boolean.TRUE.equals(policy.getLockExisting())
                && Boolean.TRUE.equals(fact.getCurrent())
                && !policy.getRemovableEntityIds().contains(fact.getEntityId())
                && !policy.getForcedRemoveEntityIds().contains(fact.getEntityId()));
    }

    private boolean mustRemove(CandidateFactDTO fact, MutationPolicyDTO policy) {
        return policy.getForcedRemoveEntityIds().contains(fact.getEntityId());
    }

    private String validateFacts(List<CandidateFactDTO> facts) {
        Set<String> ids = new LinkedHashSet<String>();
        Set<Integer> orders = new LinkedHashSet<Integer>();
        for (CandidateFactDTO fact : facts) {
            if (fact == null || Strings.isNullOrEmpty(fact.getEntityId())
                    || fact.getStableOrder() == null || fact.getStableOrder() < 0
                    || !ids.add(fact.getEntityId()) || !orders.add(fact.getStableOrder())) {
                return "entityId 或 stableOrder 为空/重复。";
            }
        }
        return null;
    }

    private String addCoverage(ExpressionsBasedModel model,
                               List<Variable> variables,
                               List<CandidateFactDTO> facts,
                               CanonicalPlanningObjectiveSetDTO objectives) {
        List<CoverageRequirementDTO> coverage = defaultList(objectives.getCoverageConstraints());
        for (int index = 0; index < coverage.size(); index++) {
            CoverageRequirementDTO requirement = coverage.get(index);
            Expression expression = model.addExpression("coverage:" + index)
                    .lower(CoverageRequirementSupport.minCount(requirement));
            for (int candidateIndex = 0; candidateIndex < facts.size(); candidateIndex++) {
                if (matchesCoverage(facts.get(candidateIndex), requirement)) {
                    expression.set(variables.get(candidateIndex), 1);
                }
            }
        }
        return null;
    }

    private boolean matchesCoverage(CandidateFactDTO fact, CoverageRequirementDTO requirement) {
        for (CandidateItemDTO candidate : defaultList(fact.getRawCandidates())) {
            if (CoverageRequirementSupport.matches(candidate, requirement)) {
                return true;
            }
        }
        return false;
    }

    private void addTierConstraints(ExpressionsBasedModel model,
                                    List<Variable> variables,
                                    List<CandidateFactDTO> facts,
                                    TierAllocationConstraintDTO constraint) {
        if (constraint == null) {
            return;
        }
        for (String tier : TIERS) {
            TierCountRangeDTO bound = tierBound(constraint, tier);
            Expression expression = model.addExpression("tier:" + tier);
            if (bound.getMinCount() != null) {
                expression.lower(bound.getMinCount());
            }
            if (bound.getMaxCount() != null) {
                expression.upper(bound.getMaxCount());
            }
            for (int index = 0; index < facts.size(); index++) {
                if (tier.equals(facts.get(index).getTier())) {
                    expression.set(variables.get(index), 1);
                }
            }
        }
    }

    private Optimisation.Result solvePhase(ExpressionsBasedModel model, long deadline, String phase) {
        long phaseStarted = System.nanoTime();
        long remaining = (deadline - phaseStarted) / 1_000_000L;
        if (remaining <= 0) {
            lastPhaseDurationMs = 0L;
            return null;
        }
        model.options.time_abort = remaining;
        model.options.time_suffice = remaining;
        model.options.iterations_abort = ITERATION_BUDGET;
        model.options.iterations_suffice = ITERATION_BUDGET;
        model.options.mip_gap = 0D;
        Optimisation.Result solved = model.minimise();
        lastPhaseDurationMs = elapsedMillis(phaseStarted);
        return solved;
    }

    private String phaseFailureReason(CandidatePoolReducer.Reduction reduction,
                                      Optimisation.Result result) {
        if (result == null) {
            return "solver_timeout";
        }
        if (result.getState() != Optimisation.State.INFEASIBLE) {
            return "solver_timeout";
        }
        if (reduction != null && !reduction.witnessAvailable) {
            return "solver_infeasible_after_cap";
        }
        if (reduction != null && reduction.witnessAvailable) {
            return "solver_witness_broken";
        }
        return "objective_set_infeasible";
    }

    private int minLocalProtect(CanonicalPlanningObjectiveSetDTO objectives,
                                CandidateSnapshotDTO snapshot) {
        StructureTargetDTO target = objectives.getStructureTarget();
        if (target == null || "not_applicable".equalsIgnoreCase(target.getSafetyFloorMode())) {
            return 0;
        }
        Integer min = target.getMinLocalProtect();
        if (min == null || min <= 0 || Strings.isNullOrEmpty(snapshot.getSourceProvince())) {
            return 0;
        }
        return min;
    }

    private boolean isLocalProtect(CandidateFactDTO fact, String sourceProvince) {
        return "protect".equals(fact.getTier()) && sameProvince(fact.getProvinceName(), sourceProvince);
    }

    private boolean sameProvince(String candidateProvince, String sourceProvince) {
        if (Strings.isNullOrEmpty(candidateProvince) || Strings.isNullOrEmpty(sourceProvince)) {
            return false;
        }
        // 与 review safety_guard 同源：规范化省份身份（"浙江省"＝"浙江"），
        // 不做双向子串放大。
        return RegionScopeSupport.sameRegionName(candidateProvince, sourceProvince);
    }

    private int localProtectDeficit(List<CandidateFactDTO> facts,
                                    List<Variable> variables,
                                    Optimisation.Result solved,
                                    String sourceProvince,
                                    int minLocalProtect) {
        int count = 0;
        for (int index = 0; index < facts.size(); index++) {
            if (isLocalProtect(facts.get(index), sourceProvince)
                    && solved.doubleValue(index) > 0.5D) {
                count++;
            }
        }
        return Math.max(0, minLocalProtect - count);
    }

    private int churnValue(List<CandidateFactDTO> facts, List<Variable> variables, Optimisation.Result solved) {
        int current = 0;
        int retained = 0;
        for (int index = 0; index < facts.size(); index++) {
            if (Boolean.TRUE.equals(facts.get(index).getCurrent())) {
                current++;
                if (solved.doubleValue(index) > 0.5D) {
                    retained++;
                }
            }
        }
        return current - retained;
    }

    private int tierDeviation(TierCountsDTO anchor,
                              List<CandidateFactDTO> facts,
                              List<Variable> variables,
                              Optimisation.Result solved) {
        if (anchor == null) {
            return 0;
        }
        int result = 0;
        for (String tier : TIERS) {
            int actual = 0;
            for (int index = 0; index < facts.size(); index++) {
                if (tier.equals(facts.get(index).getTier()) && solved.doubleValue(index) > 0.5D) {
                    actual++;
                }
            }
            result += Math.abs(actual - tierCount(anchor, tier));
        }
        return result;
    }

    private int utilityValue(List<CandidateFactDTO> facts, List<Variable> variables, Optimisation.Result solved) {
        int result = 0;
        for (int index = 0; index < facts.size(); index++) {
            if (solved.doubleValue(index) > 0.5D) {
                result += facts.get(index).getUtilityScore() == null ? 0 : facts.get(index).getUtilityScore();
            }
        }
        return result;
    }

    private List<DiversityGroup> diversityGroups(List<CandidateFactDTO> facts,
                                                 Set<CandidateFactDTO> eligibleFacts,
                                                 MutationPolicyDTO policy) {
        Map<String, DiversityGroup> groups = new LinkedHashMap<String, DiversityGroup>();
        for (int index = 0; index < facts.size(); index++) {
            CandidateFactDTO fact = facts.get(index);
            if (!eligibleFacts.contains(fact) || mustRemove(fact, policy)) {
                continue;
            }
            addDiversityGroup(groups, "region", fact.getProvinceName(), index);
            addDiversityGroup(groups, "major_category", fact.getMajorCategoryId(), index);
            addDiversityGroup(groups, "school_level", fact.getSchoolLevel(), index);
        }
        return new ArrayList<DiversityGroup>(groups.values());
    }

    private void addDiversityGroup(Map<String, DiversityGroup> groups,
                                   String dimension,
                                   String value,
                                   int factIndex) {
        String normalized = value == null ? null : value.trim();
        if (Strings.isNullOrEmpty(normalized)) {
            return;
        }
        String key = dimension + ":" + normalized;
        DiversityGroup group = groups.get(key);
        if (group == null) {
            group = new DiversityGroup(key, dimension);
            groups.put(key, group);
        }
        group.factIndexes.add(factIndex);
    }

    private int diversityCap(String dimension, DiversityPolicyDTO policy, int targetCount) {
        double share;
        if ("major_category".equals(dimension)) {
            share = policy.getMajorCategoryShare() == null
                    ? 0.4D : policy.getMajorCategoryShare();
        } else if ("school_level".equals(dimension)) {
            share = policy.getSchoolLevelShare() == null
                    ? 0.6D : policy.getSchoolLevelShare();
        } else {
            share = policy.getRegionShare() == null ? 0.4D : policy.getRegionShare();
        }
        return Math.max(1, (int) Math.ceil(share * targetCount));
    }

    private int diversityExcess(List<DiversityGroup> groups, Optimisation.Result solved) {
        int total = 0;
        for (DiversityGroup group : groups) {
            int count = 0;
            for (Integer factIndex : group.factIndexes) {
                if (solved.doubleValue(factIndex) > 0.5D) {
                    count++;
                }
            }
            total += Math.max(0, count - group.cap);
        }
        return total;
    }

    private List<CandidateFactDTO> selectedFacts(List<CandidateFactDTO> facts,
                                                 List<Variable> variables,
                                                 Optimisation.Result solved) {
        List<CandidateFactDTO> result = new ArrayList<CandidateFactDTO>();
        for (int index = 0; index < facts.size(); index++) {
            if (solved.doubleValue(index) > 0.5D) {
                result.add(facts.get(index));
            }
        }
        return result;
    }

    private List<CandidateFactDTO> orderSelected(List<CandidateFactDTO> selected) {
        List<CandidateFactDTO> sorted = new ArrayList<CandidateFactDTO>(selected);
        sorted.sort(Comparator.comparing(CandidateFactDTO::getStableOrder,
                Comparator.nullsLast(Integer::compareTo)));
        Map<String, List<CandidateFactDTO>> byTier = new LinkedHashMap<String, List<CandidateFactDTO>>();
        for (CandidateFactDTO fact : sorted) {
            List<CandidateFactDTO> bucket = byTier.get(fact.getTier());
            if (bucket == null) {
                bucket = new ArrayList<CandidateFactDTO>();
                byTier.put(fact.getTier(), bucket);
            }
            bucket.add(fact);
        }
        List<CandidateFactDTO> result = new ArrayList<CandidateFactDTO>();
        for (List<CandidateFactDTO> bucket : byTier.values()) {
            // 同档内：命中优先规则的前置；其余保持“已在本方案中的条目优先于新增条目”，
            // 避免一次补齐把用户当前顺序整体按分数重排（组内仍按 stableOrder 稳定）。
            List<CandidateFactDTO> matchedCurrent = new ArrayList<CandidateFactDTO>();
            List<CandidateFactDTO> matchedAdded = new ArrayList<CandidateFactDTO>();
            List<CandidateFactDTO> otherCurrent = new ArrayList<CandidateFactDTO>();
            List<CandidateFactDTO> otherAdded = new ArrayList<CandidateFactDTO>();
            for (CandidateFactDTO fact : bucket) {
                boolean matched = Boolean.TRUE.equals(fact.getPriorityMatched());
                boolean current = Boolean.TRUE.equals(fact.getCurrent());
                if (matched) {
                    (current ? matchedCurrent : matchedAdded).add(fact);
                } else {
                    (current ? otherCurrent : otherAdded).add(fact);
                }
            }
            result.addAll(matchedCurrent);
            result.addAll(matchedAdded);
            result.addAll(otherCurrent);
            result.addAll(otherAdded);
        }
        return result;
    }

    private void populateStageResults(PlanSolverResultDTO result, List<ObjectiveLevel> levels,
                                      List<Long> durations) {
        for (int index = 0; index < defaultList(levels).size(); index++) {
            ObjectiveLevel level = levels.get(index);
            PlanSolverResultDTO.StageResultDTO stage = new PlanSolverResultDTO.StageResultDTO();
            stage.setObjectiveId(level.level);
            stage.setValue(level.optimum);
            stage.setUnit(level.unit);
            if (index < defaultList(durations).size()) {
                stage.setDurationMs(durations.get(index));
            }
            result.getStageResults().add(stage);
        }
    }

    private String stageSummary(List<ObjectiveLevel> levels) {
        StringBuilder summary = new StringBuilder();
        for (ObjectiveLevel level : defaultList(levels)) {
            if (summary.length() > 0) {
                summary.append(',');
            }
            summary.append(level.level).append('=').append(level.optimum);
        }
        return summary.toString();
    }

    private void populateObjectiveResults(PlanSolverResultDTO result,
                                          CanonicalPlanningObjectiveSetDTO objectives,
                                          List<CandidateFactDTO> selected) {
        result.getObjectiveResults().add(objectiveResult("selection_target", "selection_target",
                objectives.getTargetCount(), objectives.getTargetCount(), selected.size()));
        List<CoverageRequirementDTO> coverage = defaultList(objectives.getCoverageConstraints());
        for (int index = 0; index < coverage.size(); index++) {
            int required = CoverageRequirementSupport.minCount(coverage.get(index));
            int actual = 0;
            for (CandidateFactDTO fact : selected) {
                if (matchesCoverage(fact, coverage.get(index))) {
                    actual++;
                }
            }
            result.getObjectiveResults().add(objectiveResult("coverage:" + index, "coverage",
                    required, null, actual));
        }
        TierAllocationConstraintDTO constraint = canonicalTierConstraint(
                objectives.getTierAllocationConstraint(), objectives.getTargetCount());
        if (constraint != null) {
            // 与旧 solver / 后置校验保持同一 objectiveType 口径：精确配额必须报
            // tier_exact，范围配额才是 tier_range；否则 freeze-apply 后置校验 40905。
            String objectiveType = exactAllocation(constraint) ? "tier_exact" : "tier_range";
            TierCountsDTO counts = tierCounts(selected);
            for (String tier : TIERS) {
                TierCountRangeDTO bound = tierBound(constraint, tier);
                result.getObjectiveResults().add(objectiveResult("tier:" + tier,
                        objectiveType, bound.getMinCount(), bound.getMaxCount(), tierCount(counts, tier)));
            }
        }
    }

    private boolean exactAllocation(TierAllocationConstraintDTO constraint) {
        String sourceType = Strings.nullToEmpty(constraint == null ? null : constraint.getSourceType())
                .trim().toLowerCase();
        return TierAllocationSupport.TYPE_EXACT_COUNTS.equals(sourceType)
                || TierAllocationSupport.TYPE_RATIOS.equals(sourceType);
    }

    private PlanSolverResultDTO.ObjectiveResultDTO objectiveResult(String id, String type,
                                                                   Integer min, Integer max, int actual) {
        PlanSolverResultDTO.ObjectiveResultDTO result = new PlanSolverResultDTO.ObjectiveResultDTO();
        result.setObjectiveId(id);
        result.setObjectiveType(type);
        result.setRequiredMin(min);
        result.setRequiredMax(max);
        result.setActualCount(actual);
        result.setSatisfied((min == null || actual >= min) && (max == null || actual <= max));
        return result;
    }

    private boolean isEligible(CandidateFactDTO fact,
                               CanonicalPlanningObjectiveSetDTO objectives,
                               MutationPolicyDTO policy) {
        if (!Boolean.TRUE.equals(fact.getEligible())) {
            return false;
        }
        // 补入安全谓词只约束“本次新增”。current 项已经写在方案里，
        // 即使学费/中外合作等不在补入安全口径内，也不能因此把整个动作判死
        // （ADD/REFILL 的 lockExisting 会强制选中它们）。
        if (policy != null && Boolean.TRUE.equals(policy.getRequireCompensationSafe())
                && !Boolean.TRUE.equals(fact.getCompensationSafe())
                && !Boolean.TRUE.equals(fact.getCurrent())) {
            return false;
        }
        HardConstraintsDTO hard = objectives.getEligibilityConstraints();
        if (hard == null) {
            return true;
        }
        List<CandidateItemDTO> raw = defaultList(fact.getRawCandidates());
        if (raw.isEmpty()) {
            return true;
        }
        for (CandidateItemDTO candidate : raw) {
            if (!RepairCandidateEligibility.isEligibleForHardConstraints(candidate, hard)) {
                return false;
            }
        }
        return true;
    }

    private TierCountsDTO structureAnchor(List<CandidateFactDTO> facts,
                                          CanonicalPlanningObjectiveSetDTO objectives,
                                          TierAllocationConstraintDTO tierConstraint,
                                          int targetCount) {
        StructureTargetDTO structureTarget = objectives.getStructureTarget();
        if (structureTarget != null && structureTarget.getTierAnchor() != null) {
            return structureTarget.getTierAnchor();
        }
        if (tierConstraint == null) {
            return null;
        }
        return TierStructureProjection.project(currentTierCounts(facts), targetCount, tierConstraint);
    }

    private TierCountsDTO currentTierCounts(List<CandidateFactDTO> facts) {
        List<CandidateFactDTO> current = new ArrayList<CandidateFactDTO>();
        for (CandidateFactDTO fact : facts) {
            if (Boolean.TRUE.equals(fact.getCurrent())) {
                current.add(fact);
            }
        }
        return tierCounts(current);
    }

    private TierCountsDTO tierCounts(List<CandidateFactDTO> facts) {
        TierCountsDTO result = new TierCountsDTO();
        result.setSprintCount(countTier(facts, "sprint"));
        result.setStableCount(countTier(facts, "stable"));
        result.setProtectCount(countTier(facts, "protect"));
        return result;
    }

    private int countTier(List<CandidateFactDTO> facts, String tier) {
        int result = 0;
        for (CandidateFactDTO fact : facts) {
            if (tier.equals(fact.getTier())) {
                result++;
            }
        }
        return result;
    }

    private int tierCount(TierCountsDTO counts, String tier) {
        if (counts == null) {
            return 0;
        }
        if ("sprint".equals(tier)) {
            return counts.getSprintCount() == null ? 0 : counts.getSprintCount();
        }
        if ("stable".equals(tier)) {
            return counts.getStableCount() == null ? 0 : counts.getStableCount();
        }
        return counts.getProtectCount() == null ? 0 : counts.getProtectCount();
    }

    private int tierCountSum(TierCountsDTO counts) {
        return tierCount(counts, "sprint") + tierCount(counts, "stable") + tierCount(counts, "protect");
    }

    private TierAllocationConstraintDTO canonicalTierConstraint(TierAllocationConstraintDTO source,
                                                                int targetCount) {
        if (source == null) {
            return null;
        }
        TierAllocationConstraintDTO result = new TierAllocationConstraintDTO();
        result.setType(source.getType());
        result.setSourceType(Strings.isNullOrEmpty(source.getSourceType())
                ? source.getType() : source.getSourceType());
        result.setSprint(effectiveBound(source.getSprint(), source.getSprintCount(), targetCount));
        result.setStable(effectiveBound(source.getStable(), source.getStableCount(), targetCount));
        result.setProtect(effectiveBound(source.getProtect(), source.getProtectCount(), targetCount));
        return result;
    }

    private TierCountRangeDTO effectiveBound(TierCountRangeDTO source, Integer exactCount, int targetCount) {
        TierCountRangeDTO result = new TierCountRangeDTO();
        if (source == null && exactCount != null) {
            result.setMinCount(exactCount);
            result.setMaxCount(exactCount);
            return result;
        }
        result.setMinCount(source == null || source.getMinCount() == null ? 0 : source.getMinCount());
        result.setMaxCount(source == null || source.getMaxCount() == null
                ? targetCount : source.getMaxCount());
        return result;
    }

    private TierCountRangeDTO tierBound(TierAllocationConstraintDTO constraint, String tier) {
        if ("sprint".equals(tier)) {
            return constraint.getSprint();
        }
        if ("stable".equals(tier)) {
            return constraint.getStable();
        }
        return constraint.getProtect();
    }

    private CandidateFactDTO fact(List<CandidateFactDTO> facts, String id) {
        for (CandidateFactDTO fact : facts) {
            if (fact != null && id != null && id.equals(fact.getEntityId())) {
                return fact;
            }
        }
        return null;
    }

    private String inputDigest(CandidateSnapshotDTO snapshot,
                               CanonicalPlanningObjectiveSetDTO objectives,
                               MutationPolicyDTO policy) {
        Map<String, Object> payload = new LinkedHashMap<String, Object>();
        payload.put("snapshot", snapshot == null ? null : snapshot.getNormalizationDigest());
        payload.put("objective", objectives == null ? null : objectives.getObjectiveDigest());
        payload.put("targetCount", objectives == null ? null : objectives.getTargetCount());
        payload.put("countMode", objectives == null ? null : objectives.getCountMode());
        payload.put("hardObjectiveVersion", HARD_OBJECTIVE_VERSION);
        payload.put("policy", policy);
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            return toHex(digest.digest(JSON.toJSONString(payload).getBytes(StandardCharsets.UTF_8)));
        } catch (NoSuchAlgorithmException ex) {
            throw new IllegalStateException("SHA-256 is unavailable", ex);
        }
    }

    private PlanSolverResultDTO baseResult(CanonicalPlanningObjectiveSetDTO objectives,
                                           CandidateSnapshotDTO snapshot) {
        PlanSolverResultDTO result = new PlanSolverResultDTO();
        result.setSolverVersion(SOLVER_VERSION);
        result.setHardObjectiveVersion(HARD_OBJECTIVE_VERSION);
        result.setCandidateCount(snapshot == null || snapshot.getFacts() == null
                ? 0 : snapshot.getFacts().size());
        result.setConstraintCount(1 + defaultList(objectives.getCoverageConstraints()).size()
                + (objectives.getTierAllocationConstraint() == null ? 0 : 3));
        result.setInputDigest(inputDigest(snapshot, objectives, new MutationPolicyDTO()));
        return result;
    }

    private Result blocked(PlanSolverResultDTO result,
                           long started,
                           String reasonCode,
                           String objectiveId,
                           String message) {
        result.setStatus("blocked");
        PlanSolverResultDTO.DiagnosticDTO diagnostic = new PlanSolverResultDTO.DiagnosticDTO();
        diagnostic.setReasonCode(reasonCode);
        diagnostic.setObjectiveId(objectiveId);
        diagnostic.setMessage(message);
        result.getDiagnostics().add(diagnostic);
        result.setDurationMs(elapsedMillis(started));
        LOG.warn("staged solver blocked: reason={} objective={} candidates={} durationMs={} message={}",
                reasonCode, objectiveId, result.getCandidateCount(), result.getDurationMs(), message);
        return new Result(result, new ArrayList<ObjectiveLevel>());
    }

    private List<CandidateFactDTO> canonicalFacts(List<CandidateFactDTO> facts) {
        List<CandidateFactDTO> result = new ArrayList<CandidateFactDTO>(defaultList(facts));
        result.sort(Comparator.comparing(CandidateFactDTO::getStableOrder,
                Comparator.nullsLast(Integer::compareTo))
                .thenComparing(CandidateFactDTO::getEntityId, Comparator.nullsLast(String::compareTo)));
        return result;
    }

    private List<String> ids(List<CandidateFactDTO> facts) {
        List<String> result = new ArrayList<String>();
        for (CandidateFactDTO fact : facts) {
            result.add(fact.getEntityId());
        }
        return result;
    }

    private List<String> currentIds(List<CandidateFactDTO> facts, List<CandidateFactDTO> selected) {
        Set<String> selectedIds = new LinkedHashSet<String>(ids(selected));
        List<String> result = new ArrayList<String>();
        for (CandidateFactDTO fact : facts) {
            if (Boolean.TRUE.equals(fact.getCurrent()) && !selectedIds.contains(fact.getEntityId())) {
                result.add(fact.getEntityId());
            }
        }
        return result;
    }

    private String toHex(byte[] values) {
        StringBuilder result = new StringBuilder(values.length * 2);
        for (byte value : values) {
            result.append(String.format("%02x", value & 0xff));
        }
        return result.toString();
    }

    private long elapsedMillis(long started) {
        return Math.max(0L, (System.nanoTime() - started) / 1_000_000L);
    }

    private static <T> List<T> defaultList(List<T> values) {
        return values == null ? new ArrayList<T>() : values;
    }

    static final class Result {
        final PlanSolverResultDTO solverResult;
        final List<ObjectiveLevel> levels;

        Result(PlanSolverResultDTO solverResult, List<ObjectiveLevel> levels) {
            this.solverResult = solverResult;
            this.levels = levels;
        }
    }

    private static final class DiversityGroup {
        final String key;
        final String dimension;
        final List<Integer> factIndexes = new ArrayList<Integer>();
        int cap;

        DiversityGroup(String key, String dimension) {
            this.key = key;
            this.dimension = dimension;
        }
    }

    static final class ObjectiveLevel {
        final String level;
        final long value;
        final long optimum;
        final String unit;

        ObjectiveLevel(String level, long value, long optimum, String unit) {
            this.level = level;
            this.value = value;
            this.optimum = optimum;
            this.unit = unit;
        }
    }

}
