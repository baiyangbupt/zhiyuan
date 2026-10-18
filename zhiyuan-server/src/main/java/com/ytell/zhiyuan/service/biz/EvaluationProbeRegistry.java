package com.ytell.zhiyuan.service.biz;

import com.google.common.collect.Lists;
import com.ytell.zhiyuan.model.dto.planning.EvaluationProbeMetadataDTO;

import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 方案评价 probe 注册表（J5.0）。
 *
 * <p>14 个旧 review check → 15 个 probe：`count_validation` 拆成
 * `count_validation_hard`（hard/block）与 `count_target`（structure/action|notice）。
 * 本类只提供元数据；阈值与执行仍在现有 review 实现里，J5.2 再切换。</p>
 */
public final class EvaluationProbeRegistry {

    public static final String VERSION = "probe-registry-v1";

    private static final Map<String, EvaluationProbeMetadataDTO> PROBES = build();

    private EvaluationProbeRegistry() {
    }

    public static EvaluationProbeMetadataDTO get(String code) {
        EvaluationProbeMetadataDTO metadata = PROBES.get(code == null ? "" : code.trim());
        return metadata == null ? null : copy(metadata);
    }

    public static List<EvaluationProbeMetadataDTO> list() {
        List<EvaluationProbeMetadataDTO> result = Lists.newArrayList();
        for (EvaluationProbeMetadataDTO metadata : PROBES.values()) {
            result.add(copy(metadata));
        }
        return result;
    }

    private static Map<String, EvaluationProbeMetadataDTO> build() {
        Map<String, EvaluationProbeMetadataDTO> probes =
                new LinkedHashMap<String, EvaluationProbeMetadataDTO>();
        register(probes, probe("ratio_distribution", "冲稳保配比", "structure", "soft",
                severities("action"), "tierCounts", "unit|item", "preview_fixable",
                "ratio_distribution"));
        register(probes, probe("safety_guard", "本省保底不足", "hard", "hard",
                severities("block", "notice"), "localSafetyUnitCount", "unit|item",
                "preview_fixable", "safety_guard"));
        register(probes, probe("probability_inversion", "录取率倒挂", "structure", "soft",
                severities("notice"), "ratioSequence", "unit|item", "preview_fixable",
                "probability_inversion"));
        register(probes, probe("probability_gap", "录取率梯度断层", "structure", "soft",
                severities("action"), "adjacentRatioDelta", "unit|item", "preview_fixable",
                "probability_gap"));
        register(probes, probe("count_validation_hard", "官方数量口径", "hard", "hard",
                severities("block"), "actualCount", "unit|item", "preview_fixable",
                "count_validation"));
        register(probes, probe("count_target", "方案目标数量", "structure", "soft",
                severities("action", "notice", "info"), "actualCount", "unit|item",
                "preview_fixable", "count_validation"));
        register(probes, probe("high_tuition", "高收费", "soft", "soft",
                severities("action", "notice"), "tuitionPerYear", "item",
                "preview_fixable", "high_tuition"));
        register(probes, probe("admission_limit", "限报条件", "hard", "hard",
                severities("block"), "riskFlags.admissionLimit", "item",
                "preview_fixable", "admission_limit"));
        register(probes, probe("special_enrollment", "特殊类型招生", "soft", "soft",
                severities("action"), "riskFlags.specialEnrollment", "item",
                "preview_fixable", "special_enrollment"));
        register(probes, probe("edge_score", "边缘分风险", "structure", "soft",
                severities("notice"), "userScore", "structure", "preview_fixable",
                "edge_score"));
        register(probes, probe("cooperative_program", "中外合作", "soft", "soft",
                severities("action"), "riskFlags.cooperativeProgram", "item",
                "preview_fixable", "cooperative_program"));
        register(probes, probe("group_inner_safety_guard", "组内安全垫不足", "hard", "hard",
                severities("block"), "groupInnerSafety", "unit", "preview_fixable",
                "group_inner_safety_guard"));
        register(probes, probe("major_group_safety_intent_alignment", "非意向托底", "soft", "soft",
                severities("action"), "careerAlignment", "unit", "preview_fixable",
                "major_group_safety_intent_alignment"));
        register(probes, probe("plan_update_notice", "招生计划更新提示", "soft", "policy",
                severities("info"), "policyNotice", "plan", "none", "plan_update_notice"));
        register(probes, probe("adjustment_notice", "调剂风险提示", "soft", "policy",
                severities("info"), "policyNotice", "plan", "none", "adjustment_notice"));
        return Collections.unmodifiableMap(probes);
    }

    private static EvaluationProbeMetadataDTO probe(String code, String label, String layer,
                                                    String ruleStrength, List<String> allowedSeverities,
                                                    String metric, String scope, String fixability,
                                                    String sourceCheck) {
        EvaluationProbeMetadataDTO metadata = new EvaluationProbeMetadataDTO();
        metadata.setCode(code);
        metadata.setLabel(label);
        metadata.setLayer(layer);
        metadata.setRuleStrength(ruleStrength);
        metadata.setAllowedSeverities(Lists.newArrayList(allowedSeverities));
        metadata.setMetric(metric);
        metadata.setScope(scope);
        metadata.setFixability(fixability);
        metadata.setSourceCheck(sourceCheck);
        metadata.setProbeVersion(VERSION);
        return metadata;
    }

    private static List<String> severities(String... values) {
        return Lists.newArrayList(values);
    }

    private static void register(Map<String, EvaluationProbeMetadataDTO> probes,
                                 EvaluationProbeMetadataDTO metadata) {
        probes.put(metadata.getCode(), metadata);
    }

    private static EvaluationProbeMetadataDTO copy(EvaluationProbeMetadataDTO source) {
        EvaluationProbeMetadataDTO target = new EvaluationProbeMetadataDTO();
        target.setCode(source.getCode());
        target.setLabel(source.getLabel());
        target.setLayer(source.getLayer());
        target.setRuleStrength(source.getRuleStrength());
        target.setAllowedSeverities(Lists.newArrayList(source.getAllowedSeverities()));
        target.setMetric(source.getMetric());
        target.setScope(source.getScope());
        target.setFixability(source.getFixability());
        target.setSourceCheck(source.getSourceCheck());
        target.setProbeVersion(source.getProbeVersion());
        return target;
    }
}
