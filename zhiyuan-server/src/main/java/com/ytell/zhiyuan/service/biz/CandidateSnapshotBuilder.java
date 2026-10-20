package com.ytell.zhiyuan.service.biz;

import com.google.common.base.Strings;
import com.google.common.collect.Lists;
import com.ytell.zhiyuan.common.exception.BusinessException;
import com.ytell.zhiyuan.model.dto.planning.CandidateFactDTO;
import com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO;
import com.ytell.zhiyuan.model.dto.planning.CandidatePoolStateDTO;
import com.ytell.zhiyuan.model.dto.planning.CandidateSnapshotDTO;
import com.ytell.zhiyuan.model.dto.planning.DraftItemDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedItemDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedUnitDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningUnitMajorDTO;
import com.ytell.zhiyuan.model.dto.planning.PriorityRuleDTO;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * J5.1/J5.3 最小快照构建器。
 *
 * <p>只读输入、不落库、不改状态。当前先服务 shadow 与测试；运行时接入在
 * S0b/S1 之后。资格判定复用既有 {@link RepairCandidateEligibility} 与
 * {@link RepairCandidateSelector#isCompensationSafeCandidate}。</p>
 */
final class CandidateSnapshotBuilder {

    private CandidateSnapshotBuilder() {
    }

    enum CurrentSource {
        /** 工作草案 + 正式方案都算 current（默认兼容口径）。 */
        UNION,
        /** 只看工作草案（enforceSelection/refill 旧口径）。 */
        WORKING,
        /** 正式方案优先；正式方案为空时回退工作草案（fill/add 旧口径）。 */
        ORDERED_FIRST
    }

    static CandidateSnapshotDTO build(PlanningStateDTO state, List<CandidateItemDTO> effectiveCandidates) {
        return build(state, effectiveCandidates, CurrentSource.UNION);
    }

    static CandidateSnapshotDTO build(PlanningStateDTO state,
                                      List<CandidateItemDTO> effectiveCandidates,
                                      CurrentSource currentSource) {
        CurrentSource source = currentSource == null ? CurrentSource.UNION : currentSource;
        CandidateSnapshotDTO snapshot = new CandidateSnapshotDTO();
        if (state == null) {
            return snapshot;
        }
        CandidatePoolStateDTO pool = state.getCandidatePoolState();
        boolean unitMode = isUnitMode(state);
        snapshot.setSourceVersion(pool == null ? null : pool.getSourceVersion());
        snapshot.setDataVersion(state.getDataFreshnessState() == null
                ? null : state.getDataFreshnessState().getDataVersion());
        snapshot.setVolunteerModel(pool == null ? null : pool.getVolunteerModel());
        snapshot.setCountMode(unitMode ? "unit" : "volunteer");
        snapshot.setSourceProvince(pool == null ? null : pool.getSourceProvinceName());

        Map<String, CandidateItemDTO> byVolunteer = byVolunteer(effectiveCandidates);
        Map<String, DraftItemDTO> draftByVolunteer = draftByVolunteer(state);
        Map<String, OrderedItemDTO> orderedByVolunteer = orderedByVolunteer(state);
        Map<String, OrderedUnitDTO> orderedByUnit = orderedByUnit(state);

        List<Bucket> buckets = unitMode
                ? unitBuckets(state, effectiveCandidates, byVolunteer, draftByVolunteer,
                orderedByVolunteer, orderedByUnit, source)
                : volunteerBuckets(state, effectiveCandidates, draftByVolunteer,
                orderedByVolunteer, source);

        List<CandidateFactDTO> facts = new ArrayList<CandidateFactDTO>();
        PriorityRuleDTO priority = firstPriority(state);
        for (Bucket bucket : buckets) {
            facts.add(toFact(state, bucket, priority));
        }
        assignStableOrder(facts);
        CandidateUtilityScorer.scoreAll(facts);
        snapshot.setFacts(facts);
        snapshot.setNormalizationDigest(digest(snapshot));
        return snapshot;
    }

    private static boolean isUnitMode(PlanningStateDTO state) {
        CandidatePoolStateDTO pool = state.getCandidatePoolState();
        return pool != null && "majorGroup".equalsIgnoreCase(pool.getVolunteerModel());
    }

    private static Map<String, CandidateItemDTO> byVolunteer(List<CandidateItemDTO> candidates) {
        Map<String, CandidateItemDTO> result = new LinkedHashMap<String, CandidateItemDTO>();
        for (CandidateItemDTO candidate : defaultList(candidates)) {
            if (candidate == null || Strings.isNullOrEmpty(candidate.getVolunteerId())) {
                continue;
            }
            if (result.put(candidate.getVolunteerId(), candidate) != null) {
                throw new BusinessException(409,
                        "candidate_fact_invalid: duplicate volunteerId " + candidate.getVolunteerId());
            }
        }
        return result;
    }

    private static Map<String, DraftItemDTO> draftByVolunteer(PlanningStateDTO state) {
        Map<String, DraftItemDTO> result = new LinkedHashMap<String, DraftItemDTO>();
        if (state.getWorkingPlanState() == null) {
            return result;
        }
        for (DraftItemDTO item : defaultList(state.getWorkingPlanState().getItems())) {
            if (item != null && !Strings.isNullOrEmpty(item.getVolunteerId())) {
                result.put(item.getVolunteerId(), item);
            }
        }
        return result;
    }

    private static Map<String, OrderedItemDTO> orderedByVolunteer(PlanningStateDTO state) {
        Map<String, OrderedItemDTO> result = new LinkedHashMap<String, OrderedItemDTO>();
        if (state.getOrderedPlanState() == null) {
            return result;
        }
        for (OrderedItemDTO item : defaultList(state.getOrderedPlanState().getItems())) {
            if (item != null && !Strings.isNullOrEmpty(item.getVolunteerId())) {
                result.put(item.getVolunteerId(), item);
            }
        }
        return result;
    }

    private static Map<String, OrderedUnitDTO> orderedByUnit(PlanningStateDTO state) {
        Map<String, OrderedUnitDTO> result = new LinkedHashMap<String, OrderedUnitDTO>();
        if (state.getOrderedPlanState() == null) {
            return result;
        }
        for (OrderedUnitDTO unit : defaultList(state.getOrderedPlanState().getUnits())) {
            if (unit != null && !Strings.isNullOrEmpty(unit.getUnitId())) {
                result.put(unit.getUnitId(), unit);
            }
        }
        return result;
    }

    private static List<Bucket> volunteerBuckets(PlanningStateDTO state,
                                                 List<CandidateItemDTO> candidates,
                                                 Map<String, DraftItemDTO> draftByVolunteer,
                                                 Map<String, OrderedItemDTO> orderedByVolunteer,
                                                 CurrentSource source) {
        Map<String, Bucket> result = new LinkedHashMap<String, Bucket>();
        for (CandidateItemDTO candidate : defaultList(candidates)) {
            if (candidate == null || Strings.isNullOrEmpty(candidate.getVolunteerId())) {
                continue;
            }
            String id = candidate.getVolunteerId();
            Bucket bucket = result.get(id);
            if (bucket == null) {
                bucket = new Bucket(id, "candidate_pool");
                result.put(id, bucket);
            }
            bucket.candidates.add(candidate);
            bucket.current |= isCurrent(source,
                    draftByVolunteer.containsKey(id),
                    orderedByVolunteer.containsKey(id),
                    orderedByVolunteer.isEmpty());
            bucket.locked |= Boolean.TRUE.equals(draftByVolunteer.containsKey(id)
                    ? draftByVolunteer.get(id).getLocked() : null)
                    || Boolean.TRUE.equals(orderedByVolunteer.containsKey(id)
                    ? orderedByVolunteer.get(id).getLocked() : null);
            bucket.pinned |= Boolean.TRUE.equals(orderedByVolunteer.containsKey(id)
                    ? orderedByVolunteer.get(id).getPinned() : null);
        }
        // 存量项不在候选池也要保留 fact，否则 solver 会把它当不可见而删除。
        Set<String> currentIds = new LinkedHashSet<String>();
        if (source == CurrentSource.WORKING) {
            currentIds.addAll(draftByVolunteer.keySet());
        } else if (source == CurrentSource.ORDERED_FIRST && !orderedByVolunteer.isEmpty()) {
            currentIds.addAll(orderedByVolunteer.keySet());
        } else {
            currentIds.addAll(draftByVolunteer.keySet());
            currentIds.addAll(orderedByVolunteer.keySet());
        }
        for (String id : currentIds) {
            if (result.containsKey(id)) {
                continue;
            }
            CandidateItemDTO fallback = fallbackVolunteer(id, draftByVolunteer.get(id),
                    orderedByVolunteer.get(id));
            Bucket bucket = new Bucket(id, "working_plan");
            bucket.candidates.add(fallback);
            bucket.current = true;
            bucket.locked = Boolean.TRUE.equals(draftByVolunteer.containsKey(id)
                    ? draftByVolunteer.get(id).getLocked() : null)
                    || Boolean.TRUE.equals(orderedByVolunteer.containsKey(id)
                    ? orderedByVolunteer.get(id).getLocked() : null);
            bucket.pinned = Boolean.TRUE.equals(orderedByVolunteer.containsKey(id)
                    ? orderedByVolunteer.get(id).getPinned() : null);
            result.put(id, bucket);
        }
        return new ArrayList<Bucket>(result.values());
    }

    private static boolean isCurrent(CurrentSource source,
                                     boolean inDraft,
                                     boolean inOrdered,
                                     boolean orderedEmpty) {
        if (source == CurrentSource.WORKING) {
            return inDraft;
        }
        if (source == CurrentSource.ORDERED_FIRST) {
            return orderedEmpty ? inDraft : inOrdered;
        }
        return inDraft || inOrdered;
    }

    private static List<Bucket> unitBuckets(PlanningStateDTO state,
                                             List<CandidateItemDTO> candidates,
                                             Map<String, CandidateItemDTO> byVolunteer,
                                             Map<String, DraftItemDTO> draftByVolunteer,
                                             Map<String, OrderedItemDTO> orderedByVolunteer,
                                             Map<String, OrderedUnitDTO> orderedByUnit,
                                             CurrentSource source) {
        Map<String, Bucket> result = new LinkedHashMap<String, Bucket>();
        for (CandidateItemDTO candidate : defaultList(candidates)) {
            if (candidate == null || Strings.isNullOrEmpty(candidate.getVolunteerId())) {
                continue;
            }
            String unitId = unitId(candidate);
            if (Strings.isNullOrEmpty(unitId)) {
                continue;
            }
            Bucket bucket = result.get(unitId);
            if (bucket == null) {
                bucket = new Bucket(unitId, "candidate_pool");
                result.put(unitId, bucket);
            }
            bucket.candidates.add(candidate);
        }
        // 当前工作草案/正式方案里的单元，即使候选池没有，也要保留。
        Map<String, List<CandidateItemDTO>> currentByUnit = currentUnitCandidates(
                byVolunteer, draftByVolunteer, orderedByVolunteer, orderedByUnit, source);
        for (Map.Entry<String, List<CandidateItemDTO>> entry : currentByUnit.entrySet()) {
            String unitId = entry.getKey();
            Bucket bucket = result.get(unitId);
            if (bucket == null) {
                bucket = new Bucket(unitId, "working_plan");
                result.put(unitId, bucket);
            }
            bucket.selectedCandidates.addAll(entry.getValue());
            Set<String> candidateIds = new LinkedHashSet<String>(volunteerIds(bucket.candidates));
            for (CandidateItemDTO selected : entry.getValue()) {
                if (candidateIds.add(selected.getVolunteerId())) {
                    bucket.candidates.add(selected);
                }
            }
            bucket.current = true;
            OrderedUnitDTO ordered = orderedByUnit.get(unitId);
            if (ordered != null) {
                bucket.locked |= Boolean.TRUE.equals(ordered.getLocked());
                bucket.pinned |= Boolean.TRUE.equals(ordered.getPinned());
            }
            for (CandidateItemDTO candidate : bucket.candidates) {
                DraftItemDTO draft = draftByVolunteer.get(candidate.getVolunteerId());
                OrderedItemDTO item = orderedByVolunteer.get(candidate.getVolunteerId());
                bucket.locked |= draft != null && Boolean.TRUE.equals(draft.getLocked());
                bucket.locked |= item != null && Boolean.TRUE.equals(item.getLocked());
                bucket.pinned |= item != null && Boolean.TRUE.equals(item.getPinned());
            }
        }
        for (Bucket bucket : result.values()) {
            assertUnitTierConsistent(bucket);
        }
        return new ArrayList<Bucket>(result.values());
    }

    private static Map<String, List<CandidateItemDTO>> currentUnitCandidates(
            Map<String, CandidateItemDTO> byVolunteer,
            Map<String, DraftItemDTO> draftByVolunteer,
            Map<String, OrderedItemDTO> orderedByVolunteer,
            Map<String, OrderedUnitDTO> orderedByUnit,
            CurrentSource source) {
        Map<String, List<CandidateItemDTO>> ordered = new LinkedHashMap<String, List<CandidateItemDTO>>();
        Map<String, String> orderedUnitIds = new LinkedHashMap<String, String>();
        Map<String, CandidateItemDTO> orderedCandidates = new LinkedHashMap<String, CandidateItemDTO>();
        for (Map.Entry<String, OrderedUnitDTO> entry : orderedByUnit.entrySet()) {
            for (CandidateItemDTO fallback : fallbackUnitCandidates(entry.getKey(), entry.getValue())) {
                CandidateItemDTO candidate = byVolunteer.get(fallback.getVolunteerId());
                ordered.computeIfAbsent(entry.getKey(), key -> new ArrayList<CandidateItemDTO>())
                        .add(candidate == null ? fallback : candidate);
                orderedUnitIds.put(fallback.getVolunteerId(), entry.getKey());
                orderedCandidates.put(fallback.getVolunteerId(), candidate == null ? fallback : candidate);
            }
        }
        for (OrderedItemDTO item : orderedByVolunteer.values()) {
            if (orderedUnitIds.containsKey(item.getVolunteerId())) {
                continue;
            }
            CandidateItemDTO candidate = byVolunteer.get(item.getVolunteerId());
            String unitId = candidate == null ? unitIdFromVolunteer(item.getVolunteerId()) : unitId(candidate);
            if (candidate == null) {
                candidate = fallbackVolunteer(item.getVolunteerId(), null, item);
                candidate.setPlanSchoolDataId(unitId);
            }
            ordered.computeIfAbsent(unitId, key -> new ArrayList<CandidateItemDTO>()).add(candidate);
            orderedUnitIds.put(item.getVolunteerId(), unitId);
            orderedCandidates.put(item.getVolunteerId(), candidate);
        }
        Map<String, List<CandidateItemDTO>> current = new LinkedHashMap<String, List<CandidateItemDTO>>();
        if (source != CurrentSource.ORDERED_FIRST || ordered.isEmpty()) {
            for (DraftItemDTO item : draftByVolunteer.values()) {
                CandidateItemDTO candidate = byVolunteer.get(item.getVolunteerId());
                if (candidate == null) {
                    candidate = orderedCandidates.get(item.getVolunteerId());
                }
                String unitId = candidate == null ? orderedUnitIds.get(item.getVolunteerId()) : unitId(candidate);
                if (Strings.isNullOrEmpty(unitId)) {
                    unitId = unitIdFromVolunteer(item.getVolunteerId());
                }
                if (candidate == null) {
                    candidate = fallbackVolunteer(item.getVolunteerId(), item,
                            orderedByVolunteer.get(item.getVolunteerId()));
                    candidate.setPlanSchoolDataId(unitId);
                }
                current.computeIfAbsent(unitId, key -> new ArrayList<CandidateItemDTO>()).add(candidate);
            }
        }
        if (source != CurrentSource.WORKING) {
            for (Map.Entry<String, List<CandidateItemDTO>> entry : ordered.entrySet()) {
                List<CandidateItemDTO> selected = current.computeIfAbsent(
                        entry.getKey(), key -> new ArrayList<CandidateItemDTO>());
                Set<String> selectedIds = new LinkedHashSet<String>(volunteerIds(selected));
                for (CandidateItemDTO candidate : entry.getValue()) {
                    if (selectedIds.add(candidate.getVolunteerId())) {
                        selected.add(candidate);
                    }
                }
            }
        }
        return current;
    }

    private static void assertUnitTierConsistent(Bucket bucket) {
        Set<String> tiers = new LinkedHashSet<String>();
        for (CandidateItemDTO candidate : bucket.candidates) {
            String tier = TierAllocationSupport.canonicalTierKey(candidate.getTier());
            if (!Strings.isNullOrEmpty(tier)) {
                tiers.add(tier);
            }
        }
        if (tiers.size() > 1) {
            throw new BusinessException(409,
                    "tier_fact_conflict: 同一专业组存在多个冲稳保档位 " + bucket.entityId);
        }
    }

    private static CandidateFactDTO toFact(PlanningStateDTO state, Bucket bucket, PriorityRuleDTO priority) {
        List<CandidateItemDTO> candidates = defaultList(bucket.candidates);
        candidates.sort(candidateComparator());
        boolean unitMode = state != null && state.getCandidatePoolState() != null
                && "majorGroup".equalsIgnoreCase(state.getCandidatePoolState().getVolunteerModel());
        List<CandidateItemDTO> planned = Lists.newArrayList();
        if (unitMode && bucket.current) {
            planned = Lists.newArrayList(bucket.selectedCandidates);
        } else if (unitMode && GroupInnerMajorOptimizationFlags.enabled()) {
            Integer requiredMajorCount = state.getCandidatePoolState().getRequiredMajorCount();
            Double unitEnrollRatio = candidates.isEmpty() ? null : candidates.get(0).getSchoolEnrollRatio();
            planned = GroupInnerMajorSelector.select(candidates, requiredMajorCount, unitEnrollRatio);
        }
        CandidateItemDTO representative = planned.isEmpty()
                ? (candidates.isEmpty() ? new CandidateItemDTO() : candidates.get(0))
                : planned.get(0);
        CandidateFactDTO fact = new CandidateFactDTO();
        fact.setEntityId(bucket.entityId);
        fact.setVolunteerIds(volunteerIds(candidates));
        fact.setRawCandidates(Lists.newArrayList(candidates));
        fact.setPlannedCandidates(planned);
        fact.setSource(bucket.source);
        fact.setSchoolId(representative.getSchoolId());
        fact.setMajorId(representative.getMajorId());
        fact.setProvinceId(representative.getProvinceId());
        fact.setProvinceName(representative.getProvinceName());
        fact.setCityId(representative.getCityId());
        fact.setCityName(representative.getCityName());
        fact.setSchoolLevel(representative.getSchoolLevel());
        fact.setSchoolNature(representative.getSchoolNature());
        fact.setSchoolCategory(representative.getSchoolCategory());
        fact.setMajorCategoryId(representative.getMajorCategoryId());
        fact.setMajorSubCategoryId(representative.getMajorSubCategoryId());
        fact.setTuitionPerYear(representative.getTuitionPerYear());
        fact.setAdmissionRatio(representative.getAdmissionRatio());
        fact.setSchoolEnrollRatio(representative.getSchoolEnrollRatio());
        fact.setIntentScore(representative.getIntentScore());
        fact.setFinalScore(representative.getFinalScore());
        fact.setFutureDevelopmentScore(representative.getFutureDevelopmentScore());
        fact.setSchoolRank(representative.getSchoolRank());
        fact.setRiskFlags(Lists.newArrayList(defaultList(representative.getRiskFlags())));
        String tier = TierAllocationSupport.canonicalTierKey(representative.getTier());
        fact.setTier(Strings.isNullOrEmpty(tier) ? "unknown" : tier);
        fact.setTierSource(Strings.isNullOrEmpty(representative.getTier()) ? "unknown" : "explicit");
        fact.setCurrent(bucket.current);
        fact.setLocked(bucket.locked);
        fact.setPinned(bucket.pinned);
        // 存量工作草案项即使缺候选事实也视为可保留；是否移除由动作的
        // removableEntityIds / 后置校验决定，不能在这里判成不合格。
        List<CandidateItemDTO> selected = planned.isEmpty() ? candidates : planned;
        fact.setEligible("working_plan".equals(bucket.source) || allEligible(state, selected));
        fact.setEligibilityReasonCodes(fact.getEligible()
                ? Lists.newArrayList() : Lists.newArrayList("confirmed_hard_constraint"));
        boolean compensationSafe = "working_plan".equals(bucket.source)
                || allCompensationSafe(selected);
        fact.setCompensationSafe(compensationSafe);
        fact.setUnitAllSafe(compensationSafe);
        List<CandidateItemDTO> priorityCandidates = planned.isEmpty() ? candidates : planned;
        fact.setPriorityMatched(priority != null && priorityCandidates.stream()
                .anyMatch(candidate -> PriorityRuleSupport.matches(candidate, priority)));
        return fact;
    }

    private static boolean allEligible(PlanningStateDTO state, List<CandidateItemDTO> candidates) {
        if (candidates.isEmpty()) {
            return false;
        }
        for (CandidateItemDTO candidate : candidates) {
            if (!RepairCandidateEligibility.isEligibleForConfirmedHardConstraints(candidate, state)) {
                return false;
            }
        }
        return true;
    }

    private static boolean allCompensationSafe(List<CandidateItemDTO> candidates) {
        if (candidates.isEmpty()) {
            return false;
        }
        for (CandidateItemDTO candidate : candidates) {
            if (!RepairCandidateSelector.isCompensationSafeCandidate(candidate)) {
                return false;
            }
        }
        return true;
    }

    private static List<String> volunteerIds(List<CandidateItemDTO> candidates) {
        List<String> result = new ArrayList<String>();
        for (CandidateItemDTO candidate : candidates) {
            if (candidate != null && !Strings.isNullOrEmpty(candidate.getVolunteerId())
                    && !result.contains(candidate.getVolunteerId())) {
                result.add(candidate.getVolunteerId());
            }
        }
        return result;
    }

    private static void assignStableOrder(List<CandidateFactDTO> facts) {
        facts.sort(factComparator());
        for (int index = 0; index < facts.size(); index++) {
            facts.get(index).setStableOrder(index);
        }
    }

    private static Comparator<CandidateFactDTO> factComparator() {
        return Comparator
                .comparing(CandidateFactDTO::getIntentScore,
                        Comparator.nullsLast(Comparator.reverseOrder()))
                .thenComparing(CandidateFactDTO::getFinalScore,
                        Comparator.nullsLast(Comparator.reverseOrder()))
                .thenComparing(CandidateFactDTO::getAdmissionRatio,
                        Comparator.nullsLast(Comparator.reverseOrder()))
                .thenComparing(CandidateFactDTO::getSchoolRank,
                        Comparator.nullsLast(Integer::compareTo))
                .thenComparing(CandidateFactDTO::getEntityId,
                        Comparator.nullsLast(String::compareTo));
    }

    private static Comparator<CandidateItemDTO> candidateComparator() {
        return Comparator
                .comparing(CandidateItemDTO::getIntentScore,
                        Comparator.nullsLast(Comparator.reverseOrder()))
                .thenComparing(CandidateItemDTO::getFinalScore,
                        Comparator.nullsLast(Comparator.reverseOrder()))
                .thenComparing(CandidateItemDTO::getAdmissionRatio,
                        Comparator.nullsLast(Comparator.reverseOrder()))
                .thenComparing(CandidateItemDTO::getSchoolRank,
                        Comparator.nullsLast(Integer::compareTo))
                .thenComparing(CandidateItemDTO::getVolunteerId,
                        Comparator.nullsLast(String::compareTo));
    }

    private static PriorityRuleDTO firstPriority(PlanningStateDTO state) {
        List<PriorityRuleDTO> rules = PriorityRuleSupport.confirmedRules(state);
        return rules == null || rules.isEmpty() ? null : rules.get(0);
    }

    private static CandidateItemDTO fallbackVolunteer(String volunteerId,
                                                       DraftItemDTO draft,
                                                       OrderedItemDTO ordered) {
        CandidateItemDTO result = new CandidateItemDTO();
        result.setVolunteerId(volunteerId);
        result.setSchoolName(ordered != null ? ordered.getSchoolName()
                : draft == null ? null : draft.getSchoolName());
        result.setDisplaySchoolName(result.getSchoolName());
        result.setMajorName(ordered != null ? ordered.getMajorName()
                : draft == null ? null : draft.getMajorName());
        result.setTier(ordered != null ? ordered.getTier()
                : draft == null ? null : draft.getTier());
        return result;
    }

    private static List<CandidateItemDTO> fallbackUnitCandidates(String unitId, OrderedUnitDTO unit) {
        List<CandidateItemDTO> result = new ArrayList<CandidateItemDTO>();
        if (unit != null) {
            for (PlanningUnitMajorDTO major : defaultList(unit.getMajorItems())) {
                CandidateItemDTO candidate = new CandidateItemDTO();
                candidate.setVolunteerId(major.getVolunteerId());
                candidate.setPlanSchoolDataId(unitId);
                candidate.setSchoolId(unit.getSchoolId());
                candidate.setSchoolName(unit.getSchoolName());
                candidate.setDisplaySchoolName(unit.getSchoolName());
                candidate.setProvinceId(unit.getProvinceId());
                candidate.setProvinceName(unit.getProvinceName());
                candidate.setCityId(unit.getCityId());
                candidate.setCityName(unit.getCityName());
                candidate.setSchoolLevel(unit.getSchoolLevel());
                candidate.setSchoolNature(unit.getSchoolNature());
                candidate.setSchoolCategory(unit.getSchoolCategory());
                candidate.setTier(unit.getTier());
                candidate.setMajorName(major.getMajorName());
                candidate.setMajorCategoryId(major.getMajorCategoryId());
                candidate.setMajorSubCategoryId(major.getMajorSubCategoryId());
                candidate.setMajorCategory(major.getMajorCategory());
                candidate.setMajorDiscipline(major.getMajorDiscipline());
                candidate.setMajorId(major.getMajorId());
                candidate.setAdmissionRatio(major.getAdmissionRatio());
                candidate.setSchoolEnrollRatio(unit.getSchoolEnrollRatio());
                candidate.setFinalScore(major.getFinalScore());
                candidate.setIntentScore(major.getIntentScore());
                candidate.setTuitionPerYear(major.getTuitionPerYear());
                candidate.setPreferred(major.getPreferred());
                candidate.setReasonCodes(Lists.newArrayList(defaultList(major.getReasonCodes())));
                result.add(candidate);
            }
        }
        if (result.isEmpty()) {
            CandidateItemDTO candidate = new CandidateItemDTO();
            candidate.setVolunteerId(unitId);
            candidate.setPlanSchoolDataId(unitId);
            candidate.setSchoolName(unit == null ? null : unit.getSchoolName());
            candidate.setDisplaySchoolName(candidate.getSchoolName());
            candidate.setTier(unit == null ? null : unit.getTier());
            result.add(candidate);
        }
        return result;
    }

    private static String unitId(CandidateItemDTO candidate) {
        String resolved = RepairCandidateSelector.resolveInitialRecommendationUnitId(candidate);
        return Strings.isNullOrEmpty(resolved) ? unitIdFromVolunteer(candidate.getVolunteerId()) : resolved;
    }

    private static String unitIdFromVolunteer(String volunteerId) {
        if (Strings.isNullOrEmpty(volunteerId)) {
            return null;
        }
        int split = volunteerId.indexOf('_');
        return split > 0 ? volunteerId.substring(0, split) : volunteerId;
    }

    private static String digest(CandidateSnapshotDTO snapshot) {
        Map<String, Object> payload = new LinkedHashMap<String, Object>();
        payload.put("snapshotVersion", snapshot.getSnapshotVersion());
        payload.put("sourceVersion", snapshot.getSourceVersion());
        payload.put("dataVersion", snapshot.getDataVersion());
        payload.put("countMode", snapshot.getCountMode());
        payload.put("sourceProvince", snapshot.getSourceProvince());
        List<String> facts = new ArrayList<String>();
        for (CandidateFactDTO fact : defaultList(snapshot.getFacts())) {
            if (fact == null) {
                continue;
            }
            Map<String, Integer> components = fact.getUtilityComponents();
            facts.add(String.valueOf(fact.getEntityId()) + "|"
                    + fact.getTier() + "|" + fact.getEligible() + "|"
                    + fact.getUtilityScore() + "|" + fact.getUtilityCoverage() + "|"
                    + (components == null ? "" : components.toString()));
        }
        payload.put("facts", facts);
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            return toHex(digest.digest(com.alibaba.fastjson.JSON.toJSONString(payload)
                    .getBytes(StandardCharsets.UTF_8)));
        } catch (NoSuchAlgorithmException ex) {
            throw new IllegalStateException("SHA-256 is unavailable", ex);
        }
    }

    private static String toHex(byte[] values) {
        StringBuilder result = new StringBuilder(values.length * 2);
        for (byte value : values) {
            result.append(String.format("%02x", value & 0xff));
        }
        return result.toString();
    }

    private static <T> List<T> defaultList(List<T> value) {
        return value == null ? new ArrayList<T>() : value;
    }

    private static final class Bucket {
        private final String entityId;
        private final String source;
        private final List<CandidateItemDTO> candidates = new ArrayList<CandidateItemDTO>();
        private final List<CandidateItemDTO> selectedCandidates = new ArrayList<CandidateItemDTO>();
        private boolean current;
        private boolean locked;
        private boolean pinned;

        private Bucket(String entityId, String source) {
            this.entityId = entityId;
            this.source = source;
        }
    }
}
