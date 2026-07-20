package com.ytell.zhiyuan.service.biz;

import com.google.common.base.Strings;
import com.google.common.collect.Lists;
import com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO;
import com.ytell.zhiyuan.model.dto.planning.ConstraintStateDTO;
import com.ytell.zhiyuan.model.dto.planning.DraftItemDTO;
import com.ytell.zhiyuan.model.dto.planning.HardPlanningObjectivesDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedItemDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedUnitDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningUnitMajorDTO;
import com.ytell.zhiyuan.model.dto.planning.PriorityRuleDTO;
import com.ytell.zhiyuan.model.dto.planning.UserGoalFixProposalReq;

import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.stream.Collectors;

final class PriorityRuleSupport {

    static final String ORDERING_RANK_BEFORE = "rank_before";
    static final String SCOPE_WITHIN_TIER = "within_tier";

    private PriorityRuleSupport() {
    }

    static String validate(List<PriorityRuleDTO> rules) {
        List<PriorityRuleDTO> safeRules = defaultList(rules);
        if (safeRules.isEmpty()) {
            return null;
        }
        if (safeRules.size() > 1) {
            return "当前只支持一条同档前置规则；多个有先后层级的优先目标需要先明确顺序。";
        }
        PriorityRuleDTO rule = safeRules.get(0);
        if (rule == null) {
            return "优先规则不能为空。";
        }
        if (!ORDERING_RANK_BEFORE.equals(normalized(defaultOrdering(rule)))) {
            return "当前只支持 orderingTarget=rank_before 的优先规则。";
        }
        if (!SCOPE_WITHIN_TIER.equals(normalized(defaultScope(rule)))) {
            return "当前只支持 scope=within_tier，不能跨冲稳保档移动。";
        }
        UserGoalFixProposalReq.RequirementDTO matcher = matcher(rule);
        String matcherError = CoverageRequirementSupport.validate(matcher);
        return Strings.isNullOrEmpty(matcherError)
                ? null : matcherError.replace("非排他覆盖要求", "同档前置规则");
    }

    static void persist(PlanningStateDTO state, List<PriorityRuleDTO> rules) {
        if (state == null || defaultList(rules).isEmpty()) {
            return;
        }
        if (state.getConstraintState() == null) {
            state.setConstraintState(new ConstraintStateDTO());
        }
        if (state.getConstraintState().getHardPlanningObjectives() == null) {
            state.getConstraintState().setHardPlanningObjectives(new HardPlanningObjectivesDTO());
        }
        HardPlanningObjectivesDTO objectives = state.getConstraintState().getHardPlanningObjectives();
        objectives.setPriorityRules(Lists.newArrayList(normalizeRule(rules.get(0))));
    }

    static List<PriorityRuleDTO> confirmedRules(PlanningStateDTO state) {
        HardPlanningObjectivesDTO objectives = state == null || state.getConstraintState() == null
                ? null : state.getConstraintState().getHardPlanningObjectives();
        return defaultList(objectives == null ? null : objectives.getPriorityRules());
    }

    static boolean isPersisted(PlanningStateDTO state, PriorityRuleDTO expected) {
        PriorityRuleDTO normalizedExpected = normalizeRule(expected);
        return confirmedRules(state).stream().anyMatch(item -> sameRule(item, normalizedExpected));
    }

    static boolean matches(CandidateItemDTO candidate, PriorityRuleDTO rule) {
        return CoverageRequirementSupport.matches(candidate, matcher(rule));
    }

    static String summarize(PriorityRuleDTO rule) {
        PriorityRuleDTO safe = normalizeRule(rule);
        String label = String.join("、", safe.getValues());
        String domain = "region".equals(safe.getDomain()) ? "地域"
                : "school".equals(safe.getDomain()) ? "院校" : "专业";
        return label + "（" + domain + "）在同一冲稳保档内优先靠前";
    }

    static Analysis analyze(PlanningStateDTO state,
                            List<CandidateItemDTO> candidates,
                            PriorityRuleDTO rule) {
        boolean unitMode = state != null && state.getCandidatePoolState() != null
                && "majorGroup".equalsIgnoreCase(state.getCandidatePoolState().getVolunteerModel());
        List<Entity> entities = unitMode
                ? unitEntities(state, candidates, rule) : volunteerEntities(state, candidates, rule);
        Analysis analysis = new Analysis();
        analysis.unitMode = unitMode;
        analysis.entityCount = entities.size();
        Map<String, Integer> unmatchedByTier = new LinkedHashMap<String, Integer>();
        Set<String> affectedTiers = new LinkedHashSet<String>();
        for (Entity entity : entities) {
            String tier = normalizedTier(entity.tier);
            analysis.missingTier = analysis.missingTier || tier.isEmpty();
            if (entity.matches) {
                analysis.matchedCount++;
                analysis.matchedIds.add(entity.id);
                int priorUnmatched = unmatchedByTier.getOrDefault(tier, 0);
                analysis.inversionCount += priorUnmatched;
                if (priorUnmatched > 0) {
                    analysis.movedTargetCount++;
                    affectedTiers.add(tier);
                }
            } else {
                unmatchedByTier.put(tier, unmatchedByTier.getOrDefault(tier, 0) + 1);
            }
        }
        if (!affectedTiers.isEmpty()) {
            analysis.pinnedConflict = entities.stream().anyMatch(entity -> entity.pinned
                    && affectedTiers.contains(normalizedTier(entity.tier)));
        }
        return analysis;
    }

    static boolean isSatisfied(PlanningStateDTO state,
                               List<CandidateItemDTO> candidates,
                               PriorityRuleDTO rule) {
        Analysis analysis = analyze(state, candidates, rule);
        return analysis.entityCount > 0 && analysis.matchedCount > 0
                && !analysis.hasMissingTier() && analysis.inversionCount == 0;
    }

    static CandidateItemDTO fallbackCandidate(OrderedUnitDTO unit, PlanningUnitMajorDTO major) {
        CandidateItemDTO candidate = new CandidateItemDTO();
        candidate.setVolunteerId(major == null ? null : major.getVolunteerId());
        candidate.setPlanSchoolDataId(unit == null ? null : unit.getUnitId());
        candidate.setSchoolName(unit == null ? null : unit.getSchoolName());
        candidate.setDisplaySchoolName(unit == null ? null : unit.getSchoolName());
        candidate.setProvinceName(unit == null ? null : unit.getProvinceName());
        candidate.setCityName(unit == null ? null : unit.getCityName());
        candidate.setSchoolLevel(unit == null ? null : unit.getSchoolLevel());
        candidate.setSchoolNature(unit == null ? null : unit.getSchoolNature());
        candidate.setSchoolCategory(unit == null ? null : unit.getSchoolCategory());
        candidate.setMajorName(major == null ? null : major.getMajorName());
        candidate.setMajorCategoryId(major == null ? null : major.getMajorCategoryId());
        candidate.setMajorSubCategoryId(major == null ? null : major.getMajorSubCategoryId());
        candidate.setMajorPlanTags(major == null ? Lists.newArrayList() : defaultList(major.getMajorPlanTags()));
        return candidate;
    }

    private static List<Entity> volunteerEntities(PlanningStateDTO state,
                                                  List<CandidateItemDTO> candidates,
                                                  PriorityRuleDTO rule) {
        Map<String, CandidateItemDTO> byId = candidateMap(candidates);
        List<Entity> result = Lists.newArrayList();
        List<OrderedItemDTO> ordered = state == null || state.getOrderedPlanState() == null
                ? Lists.newArrayList() : defaultList(state.getOrderedPlanState().getItems());
        if (!ordered.isEmpty()) {
            for (OrderedItemDTO item : ordered) {
                CandidateItemDTO candidate = byId.get(item.getVolunteerId());
                if (candidate == null) {
                    candidate = new CandidateItemDTO();
                    candidate.setVolunteerId(item.getVolunteerId());
                    candidate.setSchoolName(item.getSchoolName());
                    candidate.setDisplaySchoolName(item.getSchoolName());
                    candidate.setMajorName(item.getMajorName());
                }
                result.add(new Entity(item.getVolunteerId(), item.getTier(),
                        Boolean.TRUE.equals(item.getPinned()), matches(candidate, rule)));
            }
            return result;
        }
        for (DraftItemDTO item : defaultList(state == null || state.getWorkingPlanState() == null
                ? null : state.getWorkingPlanState().getItems())) {
            CandidateItemDTO candidate = byId.get(item.getVolunteerId());
            result.add(new Entity(item.getVolunteerId(), item.getTier(), false,
                    candidate != null && matches(candidate, rule)));
        }
        return result;
    }

    private static List<Entity> unitEntities(PlanningStateDTO state,
                                             List<CandidateItemDTO> candidates,
                                             PriorityRuleDTO rule) {
        Map<String, CandidateItemDTO> byId = candidateMap(candidates);
        Map<String, OrderedItemDTO> itemById = state == null || state.getOrderedPlanState() == null
                ? new LinkedHashMap<String, OrderedItemDTO>()
                : defaultList(state.getOrderedPlanState().getItems()).stream()
                .filter(item -> item != null && !Strings.isNullOrEmpty(item.getVolunteerId()))
                .collect(Collectors.toMap(OrderedItemDTO::getVolunteerId, item -> item,
                        (left, right) -> left, LinkedHashMap::new));
        List<Entity> result = Lists.newArrayList();
        for (OrderedUnitDTO unit : defaultList(state == null || state.getOrderedPlanState() == null
                ? null : state.getOrderedPlanState().getUnits())) {
            boolean matches = false;
            boolean pinned = Boolean.TRUE.equals(unit.getPinned());
            for (PlanningUnitMajorDTO major : defaultList(unit.getMajorItems())) {
                CandidateItemDTO candidate = byId.get(major.getVolunteerId());
                matches = matches || PriorityRuleSupport.matches(
                        candidate == null ? fallbackCandidate(unit, major) : candidate, rule);
                OrderedItemDTO item = itemById.get(major.getVolunteerId());
                pinned = pinned || (item != null && Boolean.TRUE.equals(item.getPinned()));
            }
            result.add(new Entity(unit.getUnitId(), unit.getTier(), pinned, matches));
        }
        return result;
    }

    private static Map<String, CandidateItemDTO> candidateMap(List<CandidateItemDTO> candidates) {
        return defaultList(candidates).stream()
                .filter(candidate -> candidate != null && !Strings.isNullOrEmpty(candidate.getVolunteerId()))
                .collect(Collectors.toMap(CandidateItemDTO::getVolunteerId, candidate -> candidate,
                        (left, right) -> left, LinkedHashMap::new));
    }

    private static UserGoalFixProposalReq.RequirementDTO matcher(PriorityRuleDTO rule) {
        PriorityRuleDTO safe = normalizeRule(rule);
        UserGoalFixProposalReq.RequirementDTO matcher = new UserGoalFixProposalReq.RequirementDTO();
        matcher.setKind(ProjectedHardRequirementSupport.KIND_INCLUDE);
        matcher.setDomain(safe.getDomain());
        matcher.setKey(safe.getKey());
        matcher.setValues(safe.getValues());
        matcher.setMinCount(1);
        return matcher;
    }

    private static PriorityRuleDTO normalizeRule(PriorityRuleDTO source) {
        PriorityRuleDTO result = new PriorityRuleDTO();
        result.setDomain(normalized(source == null ? null : source.getDomain()));
        result.setKey(normalized(source == null ? null : source.getKey()));
        Set<String> values = new LinkedHashSet<String>();
        for (String value : defaultList(source == null ? null : source.getValues())) {
            String text = Strings.nullToEmpty(value).trim();
            if (!text.isEmpty()) {
                values.add(text);
            }
        }
        result.setValues(Lists.newArrayList(values));
        result.setOrderingTarget(defaultOrdering(source));
        result.setScope(defaultScope(source));
        result.setRawText(source == null ? null : Strings.emptyToNull(Strings.nullToEmpty(source.getRawText()).trim()));
        return result;
    }

    private static boolean sameRule(PriorityRuleDTO left, PriorityRuleDTO right) {
        PriorityRuleDTO normalizedLeft = normalizeRule(left);
        PriorityRuleDTO normalizedRight = normalizeRule(right);
        return normalizedLeft.getDomain().equals(normalizedRight.getDomain())
                && normalizedLeft.getKey().equals(normalizedRight.getKey())
                && new LinkedHashSet<String>(normalizedLeft.getValues())
                .equals(new LinkedHashSet<String>(normalizedRight.getValues()))
                && normalizedLeft.getOrderingTarget().equals(normalizedRight.getOrderingTarget())
                && normalizedLeft.getScope().equals(normalizedRight.getScope());
    }

    private static String defaultOrdering(PriorityRuleDTO rule) {
        String value = rule == null ? null : rule.getOrderingTarget();
        return Strings.isNullOrEmpty(Strings.nullToEmpty(value).trim())
                ? ORDERING_RANK_BEFORE : normalized(value);
    }

    private static String defaultScope(PriorityRuleDTO rule) {
        String value = rule == null ? null : rule.getScope();
        return Strings.isNullOrEmpty(Strings.nullToEmpty(value).trim())
                ? SCOPE_WITHIN_TIER : normalized(value);
    }

    private static String normalizedTier(String value) {
        return TierQuotaSupport.canonicalTierKey(value);
    }

    private static String normalized(String value) {
        return Strings.nullToEmpty(value).trim().toLowerCase(Locale.ROOT);
    }

    private static <T> List<T> defaultList(List<T> values) {
        return values == null ? Lists.newArrayList() : values;
    }

    static final class Analysis {
        private boolean unitMode;
        private int entityCount;
        private int matchedCount;
        private int inversionCount;
        private int movedTargetCount;
        private boolean pinnedConflict;
        private boolean missingTier;
        private final List<String> matchedIds = Lists.newArrayList();

        boolean isUnitMode() {
            return unitMode;
        }

        int getEntityCount() {
            return entityCount;
        }

        int getMatchedCount() {
            return matchedCount;
        }

        int getInversionCount() {
            return inversionCount;
        }

        int getMovedTargetCount() {
            return movedTargetCount;
        }

        boolean hasPinnedConflict() {
            return pinnedConflict;
        }

        boolean hasMissingTier() {
            return missingTier;
        }

        List<String> getMatchedIds() {
            return matchedIds;
        }
    }

    private static final class Entity {
        private final String id;
        private final String tier;
        private final boolean pinned;
        private final boolean matches;

        private Entity(String id, String tier, boolean pinned, boolean matches) {
            this.id = id;
            this.tier = tier;
            this.pinned = pinned;
            this.matches = matches;
        }
    }
}
