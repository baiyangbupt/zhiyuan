package com.ytell.zhiyuan.service.biz;

import com.google.common.collect.Lists;
import com.google.common.collect.Maps;
import com.ytell.zhiyuan.model.dto.planning.CandidateFactDTO;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;

/**
 * J5.3 软效用的唯一计算入口。
 *
 * <p>所有分量先归一化为 0..100 的整数，再按内部权重加权。缺失分量为 0
 * （保守），不奖励数据缺失。效用只在服务端/测试中使用，不得序列化到
 * agent、WS 或 Web 卡片。</p>
 */
final class CandidateUtilityScorer {

    static final String UTILITY_MODEL_VERSION = "utility-model-v1";

    private static final int WEIGHT_PREFERENCE = 40;
    private static final int WEIGHT_QUALITY = 25;
    private static final int WEIGHT_SAFETY = 20;
    private static final int WEIGHT_FUTURE = 10;
    private static final int WEIGHT_COST = 5;
    private static final int TOTAL_WEIGHT = 100;
    private static final int TUITION_CAP = 100_000;

    private CandidateUtilityScorer() {
    }

    static void scoreAll(List<CandidateFactDTO> facts) {
        List<CandidateFactDTO> safe = facts == null ? Lists.newArrayList() : facts;
        List<CandidateFactDTO> baseline = new ArrayList<CandidateFactDTO>();
        for (CandidateFactDTO fact : safe) {
            if (fact != null && Boolean.TRUE.equals(fact.getEligible())) {
                baseline.add(fact);
            }
        }
        if (baseline.isEmpty()) {
            for (CandidateFactDTO fact : safe) {
                if (fact != null) {
                    baseline.add(fact);
                }
            }
        }
        Map<String, List<Double>> safetyByTier = safetyValuesByTier(baseline);
        List<Double> preferences = values(baseline, ValueKind.PREFERENCE);
        List<Double> qualities = values(baseline, ValueKind.QUALITY);
        List<Double> futures = values(baseline, ValueKind.FUTURE);

        for (CandidateFactDTO fact : safe) {
            if (fact == null) {
                continue;
            }
            Map<String, Integer> components = new LinkedHashMap<String, Integer>();
            int coverage = 0;
            components.put("preference", percentile(preferences, value(fact, ValueKind.PREFERENCE)));
            coverage += fact.getIntentScore() == null ? 0 : WEIGHT_PREFERENCE;
            components.put("quality", percentile(qualities, value(fact, ValueKind.QUALITY)));
            coverage += fact.getFinalScore() == null ? 0 : WEIGHT_QUALITY;
            components.put("safety", percentile(
                    safetyByTier.get(normalizedTier(fact.getTier())),
                    value(fact, ValueKind.SAFETY)));
            coverage += fact.getAdmissionRatio() == null ? 0 : WEIGHT_SAFETY;
            components.put("future", percentile(futures, value(fact, ValueKind.FUTURE)));
            coverage += fact.getFutureDevelopmentScore() == null ? 0 : WEIGHT_FUTURE;
            components.put("cost", costComponent(fact.getTuitionPerYear()));
            coverage += fact.getTuitionPerYear() == null ? 0 : WEIGHT_COST;

            fact.setUtilityComponents(components);
            fact.setUtilityCoverage(coverage);
            fact.setUtilityScore(weighted(components));
        }
    }

    private static int weighted(Map<String, Integer> components) {
        int total = WEIGHT_PREFERENCE * components.get("preference")
                + WEIGHT_QUALITY * components.get("quality")
                + WEIGHT_SAFETY * components.get("safety")
                + WEIGHT_FUTURE * components.get("future")
                + WEIGHT_COST * components.get("cost");
        return clamp((int) Math.round(total * 1.0D / TOTAL_WEIGHT));
    }

    private static int costComponent(Integer tuition) {
        if (tuition == null) {
            return 0;
        }
        int bounded = Math.max(0, Math.min(TUITION_CAP, tuition));
        return clamp(100 - Math.round(bounded * 100.0F / TUITION_CAP));
    }

    private static int percentile(List<Double> sorted, Double value) {
        if (value == null || sorted == null || sorted.isEmpty()) {
            return 0;
        }
        if (sorted.size() == 1) {
            return 50;
        }
        int less = 0;
        int equal = 0;
        for (Double item : sorted) {
            if (item == null) {
                continue;
            }
            if (item < value) {
                less++;
            } else if (item.doubleValue() == value.doubleValue()) {
                equal++;
            }
        }
        int count = sorted.size();
        if (equal == 0) {
            return 0;
        }
        // 1-based average rank: equal values occupy (less+1)..(less+equal)
        double rank = (less + (equal + 1) / 2.0D) * 100.0D / count;
        return clamp(Math.round((float) rank));
    }

    private static List<Double> values(List<CandidateFactDTO> facts, ValueKind kind) {
        List<Double> result = new ArrayList<Double>();
        for (CandidateFactDTO fact : facts) {
            Double value = value(fact, kind);
            if (value != null) {
                result.add(value);
            }
        }
        result.sort(Comparator.naturalOrder());
        return result;
    }

    private static Map<String, List<Double>> safetyValuesByTier(List<CandidateFactDTO> facts) {
        Map<String, List<Double>> result = Maps.newLinkedHashMap();
        for (CandidateFactDTO fact : facts) {
            Double value = value(fact, ValueKind.SAFETY);
            if (value == null) {
                continue;
            }
            String tier = normalizedTier(fact.getTier());
            List<Double> values = result.get(tier);
            if (values == null) {
                values = new ArrayList<Double>();
                result.put(tier, values);
            }
            values.add(value);
        }
        for (List<Double> values : result.values()) {
            values.sort(Comparator.naturalOrder());
        }
        return result;
    }

    private static Double value(CandidateFactDTO fact, ValueKind kind) {
        if (fact == null) {
            return null;
        }
        Double value;
        switch (kind) {
            case PREFERENCE:
                value = fact.getIntentScore();
                break;
            case QUALITY:
                value = fact.getFinalScore();
                break;
            case SAFETY:
                value = fact.getAdmissionRatio();
                break;
            case FUTURE:
                value = fact.getFutureDevelopmentScore();
                break;
            default:
                value = null;
        }
        return value == null || value.isNaN() || value.isInfinite() ? null : value;
    }

    private static String normalizedTier(String tier) {
        String value = tier == null ? "" : tier.trim().toLowerCase(Locale.ROOT);
        if ("冲".equals(value) || "sprint".equals(value)) {
            return "sprint";
        }
        if ("稳".equals(value) || "stable".equals(value)) {
            return "stable";
        }
        if ("保".equals(value) || "protect".equals(value)) {
            return "protect";
        }
        return value.isEmpty() ? "unknown" : value;
    }

    private static int clamp(int value) {
        return Math.max(0, Math.min(100, value));
    }

    private enum ValueKind {
        PREFERENCE, QUALITY, SAFETY, FUTURE
    }
}
