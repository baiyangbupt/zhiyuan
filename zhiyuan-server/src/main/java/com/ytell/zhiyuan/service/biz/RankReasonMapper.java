package com.ytell.zhiyuan.service.biz;

import com.ytell.zhiyuan.model.dto.volunteer.RankReasonDTO;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 把 rank 的内部理由标签映射成**稳定的结构化理由**（P1d 步骤 2）。
 *
 * <p>治理依据：{@code zhiyuan-rank/docs/tag-mapping.md}——rank 的内部标签可以继续存在，
 * 但**统一标签体系由 backend 负责对外收口**。所以这一层的职责是：把 rank 的中文标签
 * 换成本层定义的 {@code code}，把 rank 观测到的 {@code delta} 原样带出去，并且
 * **对认不出的标签不装懂**。
 *
 * <p>三条口径写死在这里：
 * <ul>
 *   <li><b>未知标签不丢</b>：映射表里没有的，以 {@code unknown:<原标签>} 保留 + WARN。
 *       静默丢弃会让"为什么加分"少一条，而少的那条恰恰是 rank 新加的规则；</li>
 *   <li><b>权重取不到就不设</b>：补 0 会让"没有这个权重"与"权重是零"混成一个样子；</li>
 *   <li><b>不在这一层重算 delta</b>：{@code delta} 必须来自 rank 的观测值。用
 *       {@code 权重 × 值} 去算一个 delta 是把观测值换成推断值，而理由是要给人看的。</li>
 * </ul>
 */
@Slf4j
@Component
public class RankReasonMapper {

    /** 一条映射规则：稳定 code + 给人看的 name + 权重键（null = 这一项没有权重）。 */
    private static final class FactorSpec {
        private final String code;
        private final String name;
        private final String weightKey;

        private FactorSpec(String code, String name, String weightKey) {
            this.code = code;
            this.name = name;
            this.weightKey = weightKey;
        }

        private String code() {
            return code;
        }

        private String name() {
            return name;
        }

        private String weightKey() {
            return weightKey;
        }
    }

    private static final Map<String, FactorSpec> COLLEGE_TAGS;
    private static final Map<String, FactorSpec> MAJOR_TAGS;

    static {
        Map<String, FactorSpec> college = new HashMap<String, FactorSpec>();
        college.put("院校正向加分", new FactorSpec("school.positive", "意向院校", null));
        college.put("院校负向减分", new FactorSpec("school.negative", "无意向院校", null));
        college.put("城市正向加分", new FactorSpec("city.positive", "意向城市", null));
        college.put("城市负向减分", new FactorSpec("city.negative", "无意向城市", null));
        college.put("省份正向加分", new FactorSpec("province.positive", "意向省份", null));
        college.put("省份负向减分", new FactorSpec("province.negative", "无意向省份", null));
        college.put("院校层次正向加分", new FactorSpec("school.level.positive", "院校层次加分", "level_score"));
        college.put("院校层次负向减分", new FactorSpec("school.level.negative", "院校层次减分", "level_score"));
        college.put("院校硕博点正向加分", new FactorSpec("school.postgraduate.positive", "院校硕博点加分", "postgraduate_recommend_ratio"));
        college.put("院校硕博点负向减分", new FactorSpec("school.postgraduate.negative", "院校硕博点减分", "postgraduate_recommend_ratio"));
        college.put("院校类型正向加分", new FactorSpec("school.category.positive", "院校类型加分", null));
        college.put("院校类型负向减分", new FactorSpec("school.category.negative", "院校类型减分", null));
        college.put("院校性质正向加分", new FactorSpec("school.nature.positive", "院校性质加分", null));
        college.put("院校性质负向减分", new FactorSpec("school.nature.negative", "院校性质减分", null));
        college.put("院校无意向减分", new FactorSpec("school.no_intent", "院校不在意向内", null));
        college.put("未知院校减分", new FactorSpec("school.unknown", "院校信息缺失", null));
        COLLEGE_TAGS = Collections.unmodifiableMap(college);

        Map<String, FactorSpec> major = new HashMap<String, FactorSpec>();
        major.put("专业正向加分", new FactorSpec("major.positive", "意向专业", null));
        major.put("专业（类）正向加分", new FactorSpec("major.group.positive", "意向专业类", null));
        major.put("专业负向减分", new FactorSpec("major.negative", "无意向专业", null));
        major.put("专业（类）负向减分", new FactorSpec("major.group.negative", "无意向专业类", null));
        major.put("高学费专业标签负向减分", new FactorSpec("major.tuition.high", "学费偏高减分", "salary_avg"));
        major.put("低学费专业标签正向加分", new FactorSpec("major.tuition.low", "学费适中加分", "salary_avg"));
        major.put("专业评估加分", new FactorSpec("major.evaluation.positive", "专业评估加分", null));
        major.put("特色专业加分", new FactorSpec("major.featured.positive", "特色专业加分", null));
        major.put("硕博点加分", new FactorSpec("major.postgraduate.positive", "专业硕博点加分", null));
        major.put("专业无意向减分", new FactorSpec("major.no_intent", "专业不在意向内", null));
        major.put("未知专业减分", new FactorSpec("major.unknown", "专业信息缺失", null));
        MAJOR_TAGS = Collections.unmodifiableMap(major);
    }

    /**
     * 院校侧理由。
     *
     * @param factors rank 返回的 {@code college_factors}（每项 {@code {tag, delta}}）
     * @param weights rank 响应顶层的权重字典（可为 null）
     */
    public List<RankReasonDTO> mapCollege(List<Map<String, Object>> factors, Map<String, Double> weights) {
        return map(factors, weights, COLLEGE_TAGS, "college");
    }

    /** 专业侧理由。 */
    public List<RankReasonDTO> mapMajor(List<Map<String, Object>> factors, Map<String, Double> weights) {
        return map(factors, weights, MAJOR_TAGS, "major");
    }

    private List<RankReasonDTO> map(List<Map<String, Object>> factors, Map<String, Double> weights,
                                   Map<String, FactorSpec> table, String scope) {
        List<RankReasonDTO> reasons = new ArrayList<RankReasonDTO>();
        if (factors == null || factors.isEmpty()) {
            return reasons;
        }
        for (Map<String, Object> factor : factors) {
            if (factor == null) {
                continue;
            }
            String tag = str(factor.get("tag"));
            Double delta = number(factor.get("delta"));
            if (tag.isEmpty()) {
                log.warn("rank 理由缺少 tag，已跳过: {}", factor);
                continue;
            }
            FactorSpec spec = table.get(tag);
            if (spec == null) {
                spec = matchByNamePattern(tag, scope);
            }
            if (spec == null) {
                // 认不出**不装懂**，也不丢：换成 unknown: 前缀留出去，并留一条 WARN——
                // 新规则上线时这里就是发现它的地方。
                log.warn("rank 理由里有未纳入统一标签体系的标签: scope={}, tag={}", scope, tag);
                reasons.add(build("unknown:" + tag, tag, null, delta, "未纳入统一标签体系：" + tag));
                continue;
            }
            Double weight = spec.weightKey() == null ? null
                    : (weights == null ? null : weights.get(spec.weightKey()));
            reasons.add(build(spec.code(), spec.name(), weight, delta, describe(spec, delta, weight)));
        }
        return reasons;
    }

    /**
     * 动态标签：rank 会把用户意向标签拼进理由段名（例如 {@code 计算机类标签正向加分}）。
     * 这类标签**没有固定表**，按后缀模式归到稳定 code，具体标签进 name 与 reason。
     */
    private FactorSpec matchByNamePattern(String tag, String scope) {
        String prefix = tag;
        String suffix;
        if (tag.endsWith("（类）标签正向加分")) {
            suffix = "（类）标签正向加分";
        } else if (tag.endsWith("（类）标签负向减分")) {
            suffix = "（类）标签负向减分";
        } else if (tag.endsWith("标签正向加分")) {
            suffix = "标签正向加分";
        } else if (tag.endsWith("标签负向减分")) {
            suffix = "标签负向减分";
        } else if (tag.endsWith("类非意向标签")) {
            suffix = "类非意向标签";
        } else if (tag.endsWith("非意向标签")) {
            suffix = "非意向标签";
        } else if (tag.endsWith("类意向标签")) {
            suffix = "类意向标签";
        } else if (tag.endsWith("意向标签")) {
            suffix = "意向标签";
        } else {
            return null;
        }
        prefix = tag.substring(0, tag.length() - suffix.length());
        if (prefix.isEmpty()) {
            return null;
        }
        boolean group = suffix.contains("（类）") || suffix.startsWith("类");
        boolean positive = suffix.contains("正向") || suffix.contains("意向") && !suffix.contains("非意向");
        String code = ("major".equals(scope) ? "major" : "school") + (group ? ".group" : "")
                + (positive ? ".tag.positive" : ".tag.negative");
        return new FactorSpec(code, prefix, null);
    }

    private RankReasonDTO build(String code, String name, Double weight, Double delta, String reason) {
        RankReasonDTO dto = new RankReasonDTO();
        dto.setCode(code);
        dto.setName(name);
        dto.setWeight(weight);
        dto.setDelta(delta);
        dto.setReason(reason);
        return dto;
    }

    private String describe(FactorSpec spec, Double delta, Double weight) {
        StringBuilder text = new StringBuilder();
        text.append(spec.name());
        if (weight != null) {
            text.append("（权重 ").append(String.format("%.4f", weight)).append("）");
        }
        if (delta != null) {
            text.append("，本次").append(delta >= 0 ? "加 " : "减 ")
                    .append(String.format("%.2f", Math.abs(delta))).append(" 分");
        }
        return text.toString();
    }

    private static String str(Object value) {
        return value == null ? "" : String.valueOf(value).trim();
    }

    private static Double number(Object value) {
        if (value instanceof Number) {
            return ((Number) value).doubleValue();
        }
        if (value instanceof String) {
            try {
                return Double.valueOf(((String) value).trim());
            } catch (NumberFormatException ignored) {
                return null;
            }
        }
        return null;
    }

    /** 供上下游对齐用：本层定义的 code 全集（便于排查"某个 code 从哪来"）。 */
    public static Map<String, String> codeCatalog() {
        Map<String, String> catalog = new LinkedHashMap<String, String>();
        for (Map.Entry<String, FactorSpec> entry : COLLEGE_TAGS.entrySet()) {
            catalog.put(entry.getValue().code(), entry.getKey());
        }
        for (Map.Entry<String, FactorSpec> entry : MAJOR_TAGS.entrySet()) {
            catalog.put(entry.getValue().code(), entry.getKey());
        }
        return catalog;
    }
}
