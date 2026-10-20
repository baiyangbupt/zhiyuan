package com.ytell.zhiyuan.service.biz;

import com.google.common.base.Strings;
import com.google.common.collect.Lists;
import com.ytell.zhiyuan.model.dto.planning.CandidateFactDTO;
import com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO;
import com.ytell.zhiyuan.model.dto.planning.CandidateSnapshotDTO;
import com.ytell.zhiyuan.model.dto.planning.CanonicalPlanningObjectiveSetDTO;
import com.ytell.zhiyuan.model.dto.planning.CoverageRequirementDTO;
import com.ytell.zhiyuan.model.dto.planning.MutationPolicyDTO;
import com.ytell.zhiyuan.model.dto.planning.StructureTargetDTO;
import com.ytell.zhiyuan.model.dto.planning.TierAllocationConstraintDTO;
import com.ytell.zhiyuan.model.dto.planning.TierCountRangeDTO;
import com.ytell.zhiyuan.model.dto.planning.TierCountsDTO;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;

/**
 * J5.3 候选帽 reducer（S0a 影子版）。
 *
 * <p>先保 mandatory（current/locked/pinned/required/forcedAdd/forcedRemove），
 * 再尽量构造一个满足硬约束的 witness；witness 放得进 cap 时，其余 coverage/
 * tier/safety 代表只能竞争剩余 budget，放不下只记
 * {@code protectionBudgetTruncated}，不把“保护预算不足”说成原问题无解。</p>
 */
final class CandidatePoolReducer {

    static final int DEFAULT_CAP = 600;

    private CandidatePoolReducer() {
    }

    static Reduction reduce(CandidateSnapshotDTO snapshot,
                            CanonicalPlanningObjectiveSetDTO objectives,
                            MutationPolicyDTO policy,
                            int cap) {
        List<CandidateFactDTO> facts = defaultList(snapshot == null ? null : snapshot.getFacts());
        Reduction result = new Reduction();
        result.candidateCountOriginal = facts.size();
        if (facts.size() <= cap) {
            result.facts = new ArrayList<CandidateFactDTO>(facts);
            result.candidateCountSolved = facts.size();
            result.witnessAvailable = false;
            result.mandatorySize = mandatoryIds(facts, policy, objectives).size();
            return result;
        }

        Set<String> mandatory = mandatoryIds(facts, policy, objectives);
        result.mandatorySize = mandatory.size();
        Set<String> core = new LinkedHashSet<String>(mandatory);
        for (CandidateFactDTO fact : facts) {
            if (Boolean.TRUE.equals(fact.getCurrent())) {
                core.add(fact.getEntityId());
            }
        }
        if (core.size() > cap) {
            result.coreOverLimit = true;
            result.facts = keepByIds(facts, core);
            result.candidateCountSolved = result.facts.size();
            result.droppedCount = Math.max(0, facts.size() - result.facts.size());
            return result;
        }

        List<CandidateFactDTO> witness;
        if (policy != null && (Boolean.TRUE.equals(policy.getPrioritySelection())
                || Boolean.TRUE.equals(policy.getInitialContentGuard()))) {
            CandidateSnapshotDTO seed = witnessSeed(snapshot, objectives, policy, core, cap, result);
            StagedDeterministicPlanSolver.Result solved = new StagedDeterministicPlanSolver()
                    .solveReductionWitness(seed, objectives, policy);
            witness = "ready".equals(solved.solverResult.getStatus())
                    ? keepByIds(facts, new LinkedHashSet<String>(solved.solverResult.getSelectedEntityIds()))
                    : null;
        } else {
            witness = findWitness(facts, objectives, policy, mandatory);
        }
        result.witnessAvailable = witness != null;
        Set<String> keep = new LinkedHashSet<String>(core);
        if (witness != null) {
            result.witnessSize = witness.size();
            for (CandidateFactDTO fact : witness) {
                keep.add(fact.getEntityId());
            }
        }
        if (keep.size() > cap) {
            result.coreOverLimit = true;
            result.facts = keepByIds(facts, keep);
            result.candidateCountSolved = result.facts.size();
            result.droppedCount = Math.max(0, facts.size() - result.facts.size());
            return result;
        }

        int budget = Math.max(0, cap - keep.size());
        List<CandidateFactDTO> optional = optionalRepresentatives(
                facts, objectives, policy, keep, witness,
                snapshot == null ? null : snapshot.getSourceProvince());
        for (CandidateFactDTO fact : optional) {
            if (budget <= 0) {
                result.protectionBudgetTruncated = true;
                break;
            }
            if (keep.add(fact.getEntityId())) {
                budget--;
            }
        }
        if (budget > 0) {
            List<CandidateFactDTO> fill = new ArrayList<CandidateFactDTO>();
            for (CandidateFactDTO fact : facts) {
                if (!keep.contains(fact.getEntityId())) {
                    fill.add(fact);
                }
            }
            fill.sort(fillComparator());
            for (CandidateFactDTO fact : fill) {
                if (budget <= 0) {
                    break;
                }
                if (isEligible(fact, objectives, policy)) {
                    keep.add(fact.getEntityId());
                    budget--;
                }
            }
        }

        result.facts = keepByIds(facts, keep);
        result.candidateCountSolved = result.facts.size();
        result.droppedCount = Math.max(0, facts.size() - result.facts.size());
        result.capLimited = result.droppedCount > 0;
        return result;
    }

    private static CandidateSnapshotDTO witnessSeed(CandidateSnapshotDTO snapshot,
                                                    CanonicalPlanningObjectiveSetDTO objectives,
                                                    MutationPolicyDTO policy,
                                                    Set<String> core,
                                                    int cap,
                                                    Reduction reduction) {
        int target = objectives == null || objectives.getTargetCount() == null
                ? 0 : Math.max(0, objectives.getTargetCount());
        boolean unitMode = "unit".equals(snapshot.getCountMode());
        List<CandidateFactDTO> sorted = new ArrayList<CandidateFactDTO>(snapshot.getFacts());
        Comparator<CandidateFactDTO> comparator = fillComparator();
        if (Boolean.TRUE.equals(policy.getInitialContentGuard())) {
            comparator = Comparator.comparingInt((CandidateFactDTO fact) ->
                    InitialContentPolicySupport.riskCounts(Lists.newArrayList(fact))
                            .values().stream().mapToInt(Integer::intValue).sum())
                    .thenComparing(fact -> InitialContentPolicySupport.preferredVolunteerIds(fact).size(),
                            Comparator.reverseOrder())
                    .thenComparingInt(fact -> InitialContentPolicySupport.itemCount(fact, unitMode))
                    .thenComparing(comparator);
        }
        if (Boolean.TRUE.equals(policy.getPrioritySelection())) {
            comparator = Comparator.comparing((CandidateFactDTO fact) ->
                    !Boolean.TRUE.equals(fact.getPriorityMatched())).thenComparing(comparator);
        }
        sorted.sort(comparator);
        Map<List<Object>, List<CandidateFactDTO>> profiles =
                new LinkedHashMap<List<Object>, List<CandidateFactDTO>>();
        int representativeCount = core.size();
        for (CandidateFactDTO fact : sorted) {
            if (target == 0 || core.contains(fact.getEntityId())
                    || !isEligible(fact, objectives, policy) || mustRemove(fact, policy)) {
                continue;
            }
            List<Object> profile = Lists.<Object>newArrayList(fact.getTier(),
                    "protect".equals(fact.getTier()) && sameProvince(fact.getProvinceName(), snapshot.getSourceProvince()));
            for (CoverageRequirementDTO requirement : defaultList(objectives.getCoverageConstraints())) {
                profile.add(matchesCoverage(fact, requirement));
            }
            if (Boolean.TRUE.equals(policy.getPrioritySelection())) {
                profile.add(Boolean.TRUE.equals(fact.getPriorityMatched()));
            }
            if (Boolean.TRUE.equals(policy.getInitialContentGuard())) {
                Set<String> riskTags = InitialContentPolicySupport.riskTags(fact);
                for (String code : InitialContentPolicySupport.RISK_CODES) {
                    profile.add(InitialContentPolicySupport.hasRisk(riskTags, code));
                }
                profile.add(InitialContentPolicySupport.itemCount(fact, unitMode));
                profile.add(InitialContentPolicySupport.preferredVolunteerIds(fact).size());
            }
            List<CandidateFactDTO> representatives = profiles.computeIfAbsent(
                    profile, key -> new ArrayList<CandidateFactDTO>());
            if (representatives.size() < target) {
                representatives.add(fact);
                representativeCount++;
            }
        }
        reduction.protectionBudgetTruncated = representativeCount > cap;
        Set<String> seedIds = new LinkedHashSet<String>(core);
        for (int round = 0; round < target && seedIds.size() < cap; round++) {
            boolean added = false;
            for (List<CandidateFactDTO> representatives : profiles.values()) {
                if (seedIds.size() < cap && round < representatives.size()) {
                    added |= seedIds.add(representatives.get(round).getEntityId());
                }
            }
            if (!added) {
                break;
            }
        }
        CandidateSnapshotDTO seed = new CandidateSnapshotDTO();
        seed.setCountMode(snapshot.getCountMode());
        seed.setSourceProvince(snapshot.getSourceProvince());
        seed.setFacts(keepByIds(snapshot.getFacts(), seedIds));
        return seed;
    }

    private static List<CandidateFactDTO> findWitness(List<CandidateFactDTO> facts,
                                                      CanonicalPlanningObjectiveSetDTO objectives,
                                                      MutationPolicyDTO policy,
                                                      Set<String> mandatory) {
        int target = objectives == null || objectives.getTargetCount() == null
                ? 0 : objectives.getTargetCount();
        List<CandidateFactDTO> eligible = new ArrayList<CandidateFactDTO>();
        for (CandidateFactDTO fact : facts) {
            if (isEligible(fact, objectives, policy) && !mustRemove(fact, policy)) {
                eligible.add(fact);
            }
        }
        if (eligible.size() < target) {
            return null;
        }
        List<CandidateFactDTO> selected = new ArrayList<CandidateFactDTO>();
        Set<String> selectedIds = new LinkedHashSet<String>();
        for (CandidateFactDTO fact : facts) {
            if (mandatory.contains(fact.getEntityId())
                    && !mustRemove(fact, policy) && selectedIds.add(fact.getEntityId())) {
                selected.add(fact);
            }
        }
        if (selected.size() > target) {
            return null;
        }
        List<CandidateFactDTO> sorted = new ArrayList<CandidateFactDTO>(eligible);
        sorted.sort(fillComparator());
        for (CandidateFactDTO fact : sorted) {
            if (selected.size() >= target) {
                break;
            }
            if (selectedIds.add(fact.getEntityId())) {
                selected.add(fact);
            }
        }
        if (selected.size() != target) {
            return null;
        }
        repairCoverage(selected, eligible, objectives, selectedIds);
        repairTiers(selected, eligible, objectives, selectedIds);
        if (!validWitness(selected, facts, policy, objectives, target)) {
            return null;
        }
        return selected;
    }

    private static void repairCoverage(List<CandidateFactDTO> selected,
                                       List<CandidateFactDTO> eligible,
                                       CanonicalPlanningObjectiveSetDTO objectives,
                                       Set<String> selectedIds) {
        List<CoverageRequirementDTO> coverage = defaultList(objectives.getCoverageConstraints());
        for (CoverageRequirementDTO requirement : coverage) {
            if (coverageCount(selected, requirement) >= CoverageRequirementSupport.minCount(requirement)) {
                continue;
            }
            CandidateFactDTO addition = bestMatch(eligible, selectedIds, requirement);
            if (addition == null) {
                continue;
            }
            CandidateFactDTO removal = worstSwapOut(selected, objectives, requirement);
            if (removal == null) {
                continue;
            }
            selectedIds.remove(removal.getEntityId());
            selected.remove(removal);
            selectedIds.add(addition.getEntityId());
            selected.add(addition);
        }
    }

    private static void repairTiers(List<CandidateFactDTO> selected,
                                    List<CandidateFactDTO> eligible,
                                    CanonicalPlanningObjectiveSetDTO objectives,
                                    Set<String> selectedIds) {
        TierAllocationConstraintDTO constraint = canonicalTierConstraint(
                objectives.getTierAllocationConstraint(), objectives.getTargetCount());
        if (constraint == null) {
            return;
        }
        for (String tier : TIERS) {
            TierCountRangeDTO bound = tierBound(constraint, tier);
            int actual = countTier(selected, tier);
            if (bound.getMinCount() != null && actual < bound.getMinCount()) {
                CandidateFactDTO addition = bestTier(eligible, selectedIds, tier, null);
                CandidateFactDTO removal = worstSwapOut(selected, objectives, null);
                if (addition != null && removal != null) {
                    selectedIds.remove(removal.getEntityId());
                    selected.remove(removal);
                    selectedIds.add(addition.getEntityId());
                    selected.add(addition);
                }
            } else if (bound.getMaxCount() != null && actual > bound.getMaxCount()) {
                CandidateFactDTO removal = worstTier(selected, tier);
                CandidateFactDTO addition = bestTier(eligible, selectedIds, null, tier);
                if (removal != null && addition != null) {
                    selectedIds.remove(removal.getEntityId());
                    selected.remove(removal);
                    selectedIds.add(addition.getEntityId());
                    selected.add(addition);
                }
            }
        }
    }

    private static boolean validWitness(List<CandidateFactDTO> selected,
                                        List<CandidateFactDTO> allFacts,
                                        MutationPolicyDTO policy,
                                        CanonicalPlanningObjectiveSetDTO objectives,
                                        int target) {
        if (selected.size() != target) {
            return false;
        }
        Set<String> ids = new LinkedHashSet<String>();
        for (CandidateFactDTO fact : selected) {
            if (!isEligible(fact, objectives, policy) || mustRemove(fact, policy)
                    || !ids.add(fact.getEntityId())) {
                return false;
            }
        }
        // forcedRemove 只是 cap 必须保留的变量，不能要求 witness 选中；
        // 真正必须选中的是 locked/pinned/required/锁定存量。
        Set<String> required = new LinkedHashSet<String>();
        for (CandidateFactDTO fact : allFacts) {
            if (Boolean.TRUE.equals(fact.getLocked()) || Boolean.TRUE.equals(fact.getPinned())
                    || mustSelect(fact, policy)) {
                required.add(fact.getEntityId());
            }
        }
        if (!ids.containsAll(required)) {
            return false;
        }
        for (CoverageRequirementDTO requirement : defaultList(objectives.getCoverageConstraints())) {
            if (coverageCount(selected, requirement)
                    < CoverageRequirementSupport.minCount(requirement)) {
                return false;
            }
        }
        TierAllocationConstraintDTO constraint = canonicalTierConstraint(
                objectives.getTierAllocationConstraint(), objectives.getTargetCount());
        if (constraint != null) {
            for (String tier : TIERS) {
                int actual = countTier(selected, tier);
                TierCountRangeDTO bound = tierBound(constraint, tier);
                if (bound.getMinCount() != null && actual < bound.getMinCount()) {
                    return false;
                }
                if (bound.getMaxCount() != null && actual > bound.getMaxCount()) {
                    return false;
                }
            }
        }
        return true;
    }

    private static CandidateFactDTO bestMatch(List<CandidateFactDTO> eligible,
                                              Set<String> selectedIds,
                                              CoverageRequirementDTO requirement) {
        CandidateFactDTO best = null;
        for (CandidateFactDTO fact : eligible) {
            if (selectedIds.contains(fact.getEntityId()) || !matchesCoverage(fact, requirement)) {
                continue;
            }
            if (best == null || fillComparator().compare(fact, best) < 0) {
                best = fact;
            }
        }
        return best;
    }

    private static CandidateFactDTO bestTier(List<CandidateFactDTO> eligible,
                                             Set<String> selectedIds,
                                             String requiredTier,
                                             String excludedTier) {
        CandidateFactDTO best = null;
        for (CandidateFactDTO fact : eligible) {
            if (selectedIds.contains(fact.getEntityId())) {
                continue;
            }
            if (requiredTier != null && !requiredTier.equals(fact.getTier())) {
                continue;
            }
            if (excludedTier != null && excludedTier.equals(fact.getTier())) {
                continue;
            }
            if (best == null || fillComparator().compare(fact, best) < 0) {
                best = fact;
            }
        }
        return best;
    }

    private static CandidateFactDTO worstSwapOut(List<CandidateFactDTO> selected,
                                                 CanonicalPlanningObjectiveSetDTO objectives,
                                                 CoverageRequirementDTO requirement) {
        CandidateFactDTO worst = null;
        for (CandidateFactDTO fact : selected) {
            if (isMandatoryProtected(fact, objectives)) {
                continue;
            }
            if (requirement != null && matchesCoverage(fact, requirement)
                    && coverageCount(selected, requirement)
                    <= CoverageRequirementSupport.minCount(requirement)) {
                continue;
            }
            if (worst == null || fillComparator().compare(fact, worst) > 0) {
                worst = fact;
            }
        }
        return worst;
    }

    private static CandidateFactDTO worstTier(List<CandidateFactDTO> selected, String tier) {
        CandidateFactDTO worst = null;
        for (CandidateFactDTO fact : selected) {
            if (!tier.equals(fact.getTier()) || Boolean.TRUE.equals(fact.getLocked())
                    || Boolean.TRUE.equals(fact.getPinned())) {
                continue;
            }
            if (worst == null || fillComparator().compare(fact, worst) > 0) {
                worst = fact;
            }
        }
        return worst;
    }

    private static boolean isMandatoryProtected(CandidateFactDTO fact,
                                                CanonicalPlanningObjectiveSetDTO objectives) {
        return Boolean.TRUE.equals(fact.getLocked()) || Boolean.TRUE.equals(fact.getPinned());
    }

    private static int coverageCount(List<CandidateFactDTO> facts, CoverageRequirementDTO requirement) {
        int result = 0;
        for (CandidateFactDTO fact : facts) {
            if (matchesCoverage(fact, requirement)) {
                result++;
            }
        }
        return result;
    }

    private static boolean matchesCoverage(CandidateFactDTO fact, CoverageRequirementDTO requirement) {
        for (CandidateItemDTO candidate : InitialContentPolicySupport.candidatesForSelection(fact)) {
            if (CoverageRequirementSupport.matches(candidate, requirement)) {
                return true;
            }
        }
        return false;
    }

    private static List<CandidateFactDTO> optionalRepresentatives(List<CandidateFactDTO> facts,
                                                                  CanonicalPlanningObjectiveSetDTO objectives,
                                                                  MutationPolicyDTO policy,
                                                                  Set<String> keep,
                                                                  List<CandidateFactDTO> witness,
                                                                  String sourceProvince) {
        List<CandidateFactDTO> result = new ArrayList<CandidateFactDTO>();
        Set<String> added = new LinkedHashSet<String>();
        int minLocalProtect = minLocalProtect(objectives);
        if (minLocalProtect > 0) {
            List<CandidateFactDTO> local = new ArrayList<CandidateFactDTO>();
            for (CandidateFactDTO fact : facts) {
                if (!keep.contains(fact.getEntityId()) && "protect".equals(fact.getTier())
                        && sameProvince(fact.getProvinceName(), sourceProvince)
                        && isEligible(fact, objectives, policy)) {
                    local.add(fact);
                }
            }
            local.sort(fillComparator());
            for (CandidateFactDTO fact : local) {
                if (added.add(fact.getEntityId())) {
                    result.add(fact);
                    if (result.size() >= minLocalProtect) {
                        break;
                    }
                }
            }
        }
        for (CoverageRequirementDTO requirement : defaultList(objectives.getCoverageConstraints())) {
            CandidateFactDTO best = null;
            for (CandidateFactDTO fact : facts) {
                if (keep.contains(fact.getEntityId()) || added.contains(fact.getEntityId())
                        || !isEligible(fact, objectives, policy)
                        || !matchesCoverage(fact, requirement)) {
                    continue;
                }
                if (best == null || fillComparator().compare(fact, best) < 0) {
                    best = fact;
                }
            }
            if (best != null && added.add(best.getEntityId())) {
                result.add(best);
            }
        }
        TierCountsDTO anchor = objectives == null || objectives.getStructureTarget() == null
                ? null : objectives.getStructureTarget().getTierAnchor();
        if (anchor != null) {
            for (String tier : TIERS) {
                int need = tierCount(anchor, tier);
                int have = 0;
                for (CandidateFactDTO fact : witness == null ? Lists.<CandidateFactDTO>newArrayList() : witness) {
                    if (tier.equals(fact.getTier())) {
                        have++;
                    }
                }
                for (CandidateFactDTO fact : facts) {
                    if (have >= need) {
                        break;
                    }
                    if (!keep.contains(fact.getEntityId()) && !added.contains(fact.getEntityId())
                            && tier.equals(fact.getTier()) && isEligible(fact, objectives, policy)) {
                        if (added.add(fact.getEntityId())) {
                            result.add(fact);
                            have++;
                        }
                    }
                }
            }
        }
        return result;
    }

    private static boolean sameProvince(String candidateProvince, String sourceProvince) {
        if (Strings.isNullOrEmpty(candidateProvince) || Strings.isNullOrEmpty(sourceProvince)) {
            return false;
        }
        String candidate = candidateProvince.trim().toLowerCase(Locale.ROOT);
        String source = sourceProvince.trim().toLowerCase(Locale.ROOT);
        return candidate.contains(source) || source.contains(candidate);
    }

    private static int minLocalProtect(CanonicalPlanningObjectiveSetDTO objectives) {
        StructureTargetDTO target = objectives == null ? null : objectives.getStructureTarget();
        if (target == null || "not_applicable".equalsIgnoreCase(target.getSafetyFloorMode())) {
            return 0;
        }
        return target.getMinLocalProtect() == null ? 0 : Math.max(0, target.getMinLocalProtect());
    }

    private static Set<String> mandatoryIds(List<CandidateFactDTO> facts,
                                            MutationPolicyDTO policy,
                                            CanonicalPlanningObjectiveSetDTO objectives) {
        Set<String> result = new LinkedHashSet<String>();
        for (CandidateFactDTO fact : facts) {
            // current 只有在 lockExisting 或 locked/pinned 时才是必保核心（mandatory），
            // FILL/SCOPE 的违规项允许删除；但它们仍会在 reduce() 里进入 keep 集，
            // 保证 solver 能看见并报告 removeEntityIds。
            if (Boolean.TRUE.equals(fact.getLocked())
                    || Boolean.TRUE.equals(fact.getPinned())
                    || mustSelect(fact, policy)) {
                result.add(fact.getEntityId());
            }
        }
        if (policy != null) {
            result.addAll(defaultSet(policy.getForcedRemoveEntityIds()));
        }
        return result;
    }

    private static boolean mustSelect(CandidateFactDTO fact, MutationPolicyDTO policy) {
        if (policy == null) {
            return false;
        }
        return policy.getFrozenRequiredEntityIds().contains(fact.getEntityId())
                || policy.getForcedAddEntityIds().contains(fact.getEntityId())
                || (Boolean.TRUE.equals(policy.getLockExisting())
                && Boolean.TRUE.equals(fact.getCurrent())
                && !policy.getRemovableEntityIds().contains(fact.getEntityId())
                && !policy.getForcedRemoveEntityIds().contains(fact.getEntityId()));
    }

    private static boolean mustRemove(CandidateFactDTO fact, MutationPolicyDTO policy) {
        return policy != null && policy.getForcedRemoveEntityIds().contains(fact.getEntityId());
    }

    private static boolean isEligible(CandidateFactDTO fact,
                                      CanonicalPlanningObjectiveSetDTO objectives,
                                      MutationPolicyDTO policy) {
        if (!Boolean.TRUE.equals(fact.getEligible())) {
            return false;
        }
        // 补入安全谓词只约束“本次新增”；current 项已在方案里，不能因
        // 不安全被剔除（ADD/REFILL 还会 lockExisting 强制保留）。
        if (policy != null && Boolean.TRUE.equals(policy.getRequireCompensationSafe())
                && !Boolean.TRUE.equals(fact.getCompensationSafe())
                && !Boolean.TRUE.equals(fact.getCurrent())) {
            return false;
        }
        if (objectives == null || objectives.getEligibilityConstraints() == null) {
            return true;
        }
        List<CandidateItemDTO> raw = InitialContentPolicySupport.candidatesForSelection(fact);
        if (raw.isEmpty()) {
            return true;
        }
        for (CandidateItemDTO candidate : raw) {
            if (!RepairCandidateEligibility.isEligibleForHardConstraints(
                    candidate, objectives.getEligibilityConstraints())) {
                return false;
            }
        }
        return true;
    }

    private static Comparator<CandidateFactDTO> fillComparator() {
        return Comparator
                .comparing((CandidateFactDTO fact) -> fact.getUtilityScore() == null ? 0 : fact.getUtilityScore(),
                        Comparator.reverseOrder())
                .thenComparing(CandidateFactDTO::getStableOrder,
                        Comparator.nullsLast(Integer::compareTo))
                .thenComparing(CandidateFactDTO::getEntityId,
                        Comparator.nullsLast(String::compareTo));
    }

    private static List<CandidateFactDTO> keepByIds(List<CandidateFactDTO> facts, Set<String> ids) {
        List<CandidateFactDTO> result = new ArrayList<CandidateFactDTO>();
        for (CandidateFactDTO fact : facts) {
            if (ids.contains(fact.getEntityId())) {
                result.add(fact);
            }
        }
        result.sort(Comparator.comparing(CandidateFactDTO::getStableOrder,
                Comparator.nullsLast(Integer::compareTo))
                .thenComparing(CandidateFactDTO::getEntityId, Comparator.nullsLast(String::compareTo)));
        return result;
    }

    private static int countTier(List<CandidateFactDTO> facts, String tier) {
        int result = 0;
        for (CandidateFactDTO fact : facts) {
            if (tier.equals(fact.getTier())) {
                result++;
            }
        }
        return result;
    }

    private static int tierCount(TierCountsDTO counts, String tier) {
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

    private static TierAllocationConstraintDTO canonicalTierConstraint(TierAllocationConstraintDTO source,
                                                                        Integer targetCount) {
        if (source == null) {
            return null;
        }
        int target = targetCount == null ? 0 : targetCount;
        TierAllocationConstraintDTO result = new TierAllocationConstraintDTO();
        result.setType(source.getType());
        result.setSourceType(Strings.isNullOrEmpty(source.getSourceType())
                ? source.getType() : source.getSourceType());
        result.setSprint(effectiveBound(source.getSprint(), source.getSprintCount(), target));
        result.setStable(effectiveBound(source.getStable(), source.getStableCount(), target));
        result.setProtect(effectiveBound(source.getProtect(), source.getProtectCount(), target));
        return result;
    }

    private static TierCountRangeDTO effectiveBound(TierCountRangeDTO source, Integer exactCount, int targetCount) {
        TierCountRangeDTO result = new TierCountRangeDTO();
        if (source == null && exactCount != null) {
            result.setMinCount(exactCount);
            result.setMaxCount(exactCount);
            return result;
        }
        result.setMinCount(source == null || source.getMinCount() == null ? 0 : source.getMinCount());
        result.setMaxCount(source == null || source.getMaxCount() == null ? targetCount : source.getMaxCount());
        return result;
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

    private static Set<String> defaultSet(Set<String> values) {
        return values == null ? new LinkedHashSet<String>() : new LinkedHashSet<String>(values);
    }

    private static <T> List<T> defaultList(List<T> values) {
        return values == null ? new ArrayList<T>() : values;
    }

    private static final List<String> TIERS = Lists.newArrayList("sprint", "stable", "protect");

    static final class Reduction {
        List<CandidateFactDTO> facts = new ArrayList<CandidateFactDTO>();
        int candidateCountOriginal;
        int candidateCountSolved;
        int droppedCount;
        int mandatorySize;
        int witnessSize;
        boolean witnessAvailable;
        boolean coreOverLimit;
        boolean protectionBudgetTruncated;
        boolean capLimited;
    }
}
