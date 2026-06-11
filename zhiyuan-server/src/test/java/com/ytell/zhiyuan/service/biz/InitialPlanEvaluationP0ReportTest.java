package com.ytell.zhiyuan.service.biz;

import com.alibaba.fastjson.JSONObject;
import com.ytell.zhiyuan.Application;
import com.ytell.zhiyuan.model.dto.planning.InitialRecommendationItemDTO;
import com.ytell.zhiyuan.model.dto.planning.InitialRecommendationStateDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedItemDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedPlanStateDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import com.ytell.zhiyuan.model.dto.planning.RecommendationOverlayStateDTO;
import com.ytell.zhiyuan.model.dto.inner.VolunteerRecommendListResponse;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfSystemProperty;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.transaction.annotation.Transactional;

import java.lang.reflect.Method;
import java.util.Arrays;
import java.util.Comparator;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import java.util.stream.Collectors;

@SpringBootTest(classes = Application.class)
@ActiveProfiles("local")
@Transactional
@EnabledIfSystemProperty(named = "RUN_P0_REAL_SESSION_REPORT", matches = "true")
class InitialPlanEvaluationP0ReportTest {

    @Autowired
    private VolunteerBizService volunteerBizService;

    @Autowired
    private PlanningStateService planningStateService;

    @Test
    void printP0RealSessionComparison() {
        for (Long sessionId : Arrays.asList(14L, 11L, 15L, 16L, 17L, 7L)) {
            printSessionReport(sessionId);
        }
    }

    private void printSessionReport(Long sessionId) {
        VolunteerRecommendListResponse legacy = volunteerBizService.recommendVolunteerList(1L, sessionId, false, false);
        PlanningStateDTO v2 = simulateInitialPlan(sessionId);

        System.out.println("=== SAMPLE session=" + sessionId + " ===");
        System.out.println("profile: province=" + extractProvince(legacy)
                + ", mode=" + extractMode(legacy)
                + ", score=" + extractScore(legacy)
                + ", rank=" + extractRank(legacy)
                + ", strategy=" + extractStrategy(legacy)
                + ", gender=" + extractGender(legacy));
        System.out.println("legacy.targets=" + normalizeLegacyTargetCounts(legacy));
        System.out.println("legacy.preferred=" + buildLegacyPreferredCounts(legacy));
        System.out.println("legacy.examples=" + buildLegacyExamples(legacy));
        System.out.println("v2.required=" + safeMap(v2.getCandidatePoolState() == null ? null : v2.getCandidatePoolState().getRequiredTierCounts()));
        System.out.println("v2.candidate=" + safeMap(v2.getCandidatePoolState() == null || v2.getCandidatePoolState().getSummary() == null
                ? null : v2.getCandidatePoolState().getSummary().getTierCounts()));
        System.out.println("v2.initial=" + safeMap(v2.getInitialRecommendationState() == null ? null : v2.getInitialRecommendationState().getSummary().getTierCounts()));
        System.out.println("v2.ordered=" + safeMap(v2.getOrderedPlanState() == null ? null : v2.getOrderedPlanState().getSummary().getTierCounts()));
        System.out.println("v2.unresolved=" + (v2.getInitialRecommendationState() == null
                || v2.getInitialRecommendationState().getSummary() == null
                ? Arrays.asList()
                : v2.getInitialRecommendationState().getSummary().getUnresolvedRuleCodes()));
        System.out.println("v2.score_rank=" + buildScoreRankSummary(v2));
        System.out.println("v2.examples=" + buildV2Examples(v2));
    }

    private PlanningStateDTO simulateInitialPlan(Long sessionId) {
        PlanningStateDTO source = planningStateService.getPlanningState(sessionId);
        PlanningStateDTO state = JSONObject.parseObject(JSONObject.toJSONString(source), PlanningStateDTO.class);
        state.setSessionId(sessionId);

        if (state.getRecommendationOverlayState() == null
                || state.getRecommendationOverlayState().getItems() == null
                || state.getRecommendationOverlayState().getItems().isEmpty()) {
            RecommendationOverlayStateDTO overlayState = invoke("buildRecommendationOverlayState",
                    new Class[]{state.getCandidatePoolState().getClass(), Integer.class},
                    state.getCandidatePoolState(),
                    state.getVersion());
            state.setRecommendationOverlayState(overlayState);
        }

        InitialRecommendationStateDTO initialRecommendationState = invoke("buildInitialRecommendationState",
                new Class[]{PlanningStateDTO.class},
                state);
        state.setInitialRecommendationState(initialRecommendationState);

        List<?> effectiveCandidates = invoke("resolveEffectiveCandidates",
                new Class[]{Long.class, Long.class, PlanningStateDTO.class, boolean.class},
                null,
                sessionId,
                state,
                false);
        invokeVoid("replaceWorkingPlanWithInitialRecommendation",
                new Class[]{PlanningStateDTO.class, List.class},
                state,
                effectiveCandidates);
        invokeVoid("recalculateWorkingPlanSummary",
                new Class[]{state.getDraftPlanState().getClass(), state.getCandidatePoolState().getClass()},
                state.getDraftPlanState(),
                state.getCandidatePoolState());

        List<OrderedItemDTO> orderedItems = invoke("buildOrderedItemsFromWorkingPlan",
                new Class[]{state.getDraftPlanState().getClass(), state.getCandidatePoolState().getClass(), List.class, Map.class, boolean.class},
                state.getDraftPlanState(),
                state.getCandidatePoolState(),
                effectiveCandidates,
                new LinkedHashMap<String, OrderedItemDTO>(),
                true);

        OrderedPlanStateDTO orderedPlanState = new OrderedPlanStateDTO();
        orderedPlanState.setItems(orderedItems);
        invokeVoid("recalculateOrderedSummary",
                new Class[]{OrderedPlanStateDTO.class, state.getCandidatePoolState().getClass()},
                orderedPlanState,
                state.getCandidatePoolState());
        state.setOrderedPlanState(orderedPlanState);
        return state;
    }

    @SuppressWarnings("unchecked")
    private <T> T invoke(String methodName, Class<?>[] parameterTypes, Object... args) {
        try {
            Method method = PlanningStateService.class.getDeclaredMethod(methodName, parameterTypes);
            method.setAccessible(true);
            return (T) method.invoke(planningStateService, args);
        } catch (Exception e) {
            throw new IllegalStateException("invoke failed: " + methodName, e);
        }
    }

    private void invokeVoid(String methodName, Class<?>[] parameterTypes, Object... args) {
        invoke(methodName, parameterTypes, args);
    }

    private String extractProvince(VolunteerRecommendListResponse legacy) {
        return legacy == null || legacy.getUserScoreDetail() == null || legacy.getUserScoreDetail().getProvince() == null
                ? null : legacy.getUserScoreDetail().getProvince().getName();
    }

    private String extractMode(VolunteerRecommendListResponse legacy) {
        return legacy == null || legacy.getBaseData() == null || legacy.getBaseData().getVolunteerModel() == null
                ? null : legacy.getBaseData().getVolunteerModel().getCode();
    }

    private Integer extractScore(VolunteerRecommendListResponse legacy) {
        return legacy == null || legacy.getUserScoreDetail() == null ? null : legacy.getUserScoreDetail().getTotalScore();
    }

    private Integer extractRank(VolunteerRecommendListResponse legacy) {
        return legacy == null || legacy.getUserScoreDetail() == null ? null : legacy.getUserScoreDetail().getTotalScorePos();
    }

    private String extractStrategy(VolunteerRecommendListResponse legacy) {
        return legacy == null || legacy.getUserScoreDetail() == null || legacy.getUserScoreDetail().getStrategyType() == null
                ? null : legacy.getUserScoreDetail().getStrategyType().getCode();
    }

    private String extractGender(VolunteerRecommendListResponse legacy) {
        return legacy == null || legacy.getUserScoreDetail() == null || legacy.getUserScoreDetail().getSex() == null
                ? null : legacy.getUserScoreDetail().getSex().getName();
    }

    private Map<String, Integer> normalizeLegacyTargetCounts(VolunteerRecommendListResponse legacy) {
        Map<String, Integer> counts = new LinkedHashMap<String, Integer>();
        counts.put("冲", 0);
        counts.put("稳", 0);
        counts.put("保", 0);
        if (legacy == null || legacy.getBaseData() == null) {
            return counts;
        }
        Map<String, Integer> targetMap = legacy.getBaseData().getThree_target_count_map();
        if (targetMap != null) {
            counts.put("冲", defaultInt(targetMap.get("sprints_count")));
            counts.put("稳", defaultInt(targetMap.get("safes_count")));
            counts.put("保", defaultInt(targetMap.get("protects_count")));
        }
        return counts;
    }

    private Map<String, Integer> buildLegacyPreferredCounts(VolunteerRecommendListResponse legacy) {
        Map<String, Integer> counts = new LinkedHashMap<String, Integer>();
        counts.put("冲", countPreferred(legacy == null ? null : legacy.getSprints()));
        counts.put("稳", countPreferred(legacy == null ? null : legacy.getSafes()));
        counts.put("保", countPreferred(legacy == null ? null : legacy.getProtects()));
        return counts;
    }

    private int countPreferred(List<VolunteerRecommendListResponse.VolunteerSchool> schools) {
        if (schools == null) {
            return 0;
        }
        return (int) schools.stream().filter(item -> Boolean.TRUE.equals(item.getIs_preferred())).count();
    }

    private Map<String, List<String>> buildLegacyExamples(VolunteerRecommendListResponse legacy) {
        Map<String, List<String>> result = new LinkedHashMap<String, List<String>>();
        result.put("冲", schoolExamples(legacy == null ? null : legacy.getSprints()));
        result.put("稳", schoolExamples(legacy == null ? null : legacy.getSafes()));
        result.put("保", schoolExamples(legacy == null ? null : legacy.getProtects()));
        return result;
    }

    private List<String> schoolExamples(List<VolunteerRecommendListResponse.VolunteerSchool> schools) {
        if (schools == null) {
            return Arrays.asList();
        }
        return schools.stream()
                .filter(item -> Boolean.TRUE.equals(item.getIs_preferred()))
                .limit(3)
                .map(item -> item.getSchool_name() + "|" + item.getPlanSchoolDataId())
                .collect(Collectors.toList());
    }

    private Map<String, Integer> safeMap(Map<String, Integer> source) {
        Map<String, Integer> result = new LinkedHashMap<String, Integer>();
        result.put("冲", source == null ? 0 : defaultInt(source.get("冲")));
        result.put("稳", source == null ? 0 : defaultInt(source.get("稳")));
        result.put("保", source == null ? 0 : defaultInt(source.get("保")));
        return result;
    }

    private Integer defaultInt(Integer value) {
        return value == null ? 0 : value;
    }

    private Map<String, List<String>> buildV2Examples(PlanningStateDTO state) {
        Map<String, String> tierByVolunteerId = state.getInitialRecommendationState() == null
                || state.getInitialRecommendationState().getItems() == null
                ? new LinkedHashMap<String, String>()
                : state.getInitialRecommendationState().getItems().stream()
                .filter(Objects::nonNull)
                .collect(Collectors.toMap(InitialRecommendationItemDTO::getVolunteerId,
                        InitialRecommendationItemDTO::getRecommendTier,
                        (left, right) -> left,
                        LinkedHashMap::new));

        Map<String, List<String>> result = new LinkedHashMap<String, List<String>>();
        result.put("冲", orderedExamplesByTier(state, tierByVolunteerId, "冲"));
        result.put("稳", orderedExamplesByTier(state, tierByVolunteerId, "稳"));
        result.put("保", orderedExamplesByTier(state, tierByVolunteerId, "保"));
        return result;
    }

    private Map<String, String> buildScoreRankSummary(PlanningStateDTO state) {
        Map<String, String> result = new LinkedHashMap<String, String>();
        List<com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO> candidates = state == null
                || state.getCandidatePoolState() == null
                ? Arrays.asList()
                : state.getCandidatePoolState().getItems();
        Set<String> selectedIds = state == null || state.getInitialRecommendationState() == null
                || state.getInitialRecommendationState().getItems() == null
                ? new HashSet<String>()
                : state.getInitialRecommendationState().getItems().stream()
                .map(InitialRecommendationItemDTO::getVolunteerId)
                .filter(Objects::nonNull)
                .collect(Collectors.toSet());

        for (String tier : Arrays.asList("冲", "稳", "保")) {
            List<com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO> tierCandidates = candidates.stream()
                    .filter(Objects::nonNull)
                    .filter(item -> tier.equals(item.getTier()))
                    .sorted(Comparator.comparing((com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO item) -> item.getFinalScore() == null ? 0D : item.getFinalScore())
                            .reversed())
                    .collect(Collectors.toList());
            List<Integer> selectedRanks = Arrays.asList();
            if (!tierCandidates.isEmpty()) {
                selectedRanks = java.util.stream.IntStream.range(0, tierCandidates.size())
                        .filter(index -> selectedIds.contains(tierCandidates.get(index).getVolunteerId()))
                        .map(index -> index + 1)
                        .boxed()
                        .collect(Collectors.toList());
            }
            if (selectedRanks.isEmpty()) {
                result.put(tier, "none");
                continue;
            }
            int best = selectedRanks.stream().min(Integer::compareTo).orElse(0);
            int worst = selectedRanks.stream().max(Integer::compareTo).orElse(0);
            double avg = selectedRanks.stream().mapToInt(Integer::intValue).average().orElse(0D);
            result.put(tier, "best=" + best + ",avg=" + String.format(java.util.Locale.US, "%.1f", avg) + ",worst=" + worst + ",selected=" + selectedRanks.size() + "/" + tierCandidates.size());
        }
        return result;
    }

    private List<String> orderedExamplesByTier(PlanningStateDTO state,
                                               Map<String, String> tierByVolunteerId,
                                               String tier) {
        if (state == null || state.getOrderedPlanState() == null || state.getOrderedPlanState().getItems() == null) {
            return Arrays.asList();
        }
        return state.getOrderedPlanState().getItems().stream()
                .filter(Objects::nonNull)
                .filter(item -> tier.equals(tierByVolunteerId.get(item.getVolunteerId())))
                .limit(3)
                .map(this::orderedDisplay)
                .collect(Collectors.toList());
    }

    private String orderedDisplay(OrderedItemDTO item) {
        return item.getSchoolName() + "|" + item.getMajorName() + "|" + item.getVolunteerId();
    }
}
