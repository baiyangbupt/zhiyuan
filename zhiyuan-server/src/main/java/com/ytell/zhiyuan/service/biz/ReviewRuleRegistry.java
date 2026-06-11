package com.ytell.zhiyuan.service.biz;

import com.google.common.collect.Lists;
import com.ytell.zhiyuan.model.dto.planning.ReviewRuleMetadataDTO;

import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

public final class ReviewRuleRegistry {

    private static final String MODE_MAJOR = "major";
    private static final String MODE_MAJOR_GROUP = "major_group";

    private static final Map<String, ReviewRuleMetadataDTO> RULES = buildRules();

    private ReviewRuleRegistry() {
    }

    public static ReviewRuleMetadataDTO get(String code) {
        ReviewRuleMetadataDTO metadata = RULES.get(normalizeCode(code));
        return metadata == null ? null : copy(metadata);
    }

    public static List<ReviewRuleMetadataDTO> list() {
        List<ReviewRuleMetadataDTO> result = Lists.newArrayList();
        for (ReviewRuleMetadataDTO metadata : RULES.values()) {
            result.add(copy(metadata));
        }
        return result;
    }

    private static Map<String, ReviewRuleMetadataDTO> buildRules() {
        Map<String, ReviewRuleMetadataDTO> rules = new LinkedHashMap<String, ReviewRuleMetadataDTO>();
        register(rules, rule("ratio_distribution", "冲稳保配比", "structure_risk", "warn",
                bothModes(), "structure", "preview_fixable",
                strategies("rebalance_tier_ratio", "replace_risk_items", "regenerate_plan_with_constraints"),
                "rebalance_tier_ratio", true, "tier_ratio_v1", "ratio_distribution"));
        register(rules, rule("safety_guard", "本省保底不足", "structure_risk", "risk",
                bothModes(), "structure", "preview_fixable",
                strategies("add_safety_items", "replace_risk_items", "fill_missing_count"),
                "add_safety_items", true, "safety_guard_v1", "safety_guard"));
        register(rules, rule("probability_inversion", "录取率倒挂", "ordering_risk", "warn",
                bothModes(), "structure", "preview_fixable",
                strategies("sort_by_probability", "replace_risk_items", "regenerate_order"),
                "sort_by_probability", true, "probability_inversion_v1", "probability_inversion"));
        register(rules, rule("probability_gap", "录取率梯度断层", "structure_risk", "warn",
                bothModes(), "structure", "preview_fixable",
                strategies("fill_probability_gap", "replace_risk_items", "rebalance_tier_ratio"),
                "fill_probability_gap", true, "probability_gap_v1", "probability_gap"));
        register(rules, rule("count_validation", "数量校验", "structure_risk", "risk",
                bothModes(), "structure", "preview_fixable",
                strategies("fill_missing_count", "regenerate_plan_with_constraints"),
                "fill_missing_count", true, "count_validation_v1", "count_validation"));
        register(rules, rule("high_tuition", "高收费", "item_risk", "warn",
                bothModes(), "item", "preview_fixable",
                strategies("replace_risk_items", "remove_risk_items"),
                "replace_risk_items", true, "high_tuition_v1", "high_tuition"));
        register(rules, rule("admission_limit", "限报条件", "item_risk", "risk",
                bothModes(), "item", "preview_fixable",
                strategies("remove_risk_items", "replace_risk_items"),
                "remove_risk_items", true, "admission_limit_v1", "admission_limit"));
        register(rules, rule("special_enrollment", "特殊类型招生", "item_risk", "warn",
                bothModes(), "item", "preview_fixable",
                strategies("remove_risk_items", "replace_risk_items"),
                "remove_risk_items", true, "special_enrollment_v1", "special_enrollment"));
        register(rules, rule("edge_score", "边缘分风险", "structure_risk", "warn",
                bothModes(), "structure", "preview_fixable",
                strategies("add_safety_items", "rebalance_tier_ratio", "replace_risk_items"),
                "add_safety_items", true, "edge_score_v1", "edge_score"));
        register(rules, rule("cooperative_program", "中外合作", "item_risk", "warn",
                bothModes(), "item", "preview_fixable",
                strategies("replace_risk_items", "remove_risk_items"),
                "replace_risk_items", true, "cooperative_program_v1", "cooperative_program"));
        register(rules, rule("major_group_safety_intent_alignment", "非意向托底", "major_group_risk", "warn",
                majorGroupOnly(), "major_group_inner", "preview_fixable",
                strategies("adjust_major_group_inner_safety", "replace_risk_items"),
                "adjust_major_group_inner_safety", true, "major_group_safety_intent_alignment_v1",
                "major_group_safety_intent_alignment"));
        register(rules, rule("group_inner_safety_guard", "组内安全垫不足", "major_group_risk", "risk",
                majorGroupOnly(), "major_group_inner", "preview_fixable",
                strategies("adjust_major_group_inner_safety", "replace_risk_items"),
                "adjust_major_group_inner_safety", true, "group_inner_safety_guard_v1",
                "group_inner_safety_guard"));
        register(rules, rule("plan_update_notice", "招生计划更新提示", "policy_notice", "info",
                bothModes(), "informational", "not_fixable",
                Collections.<String>emptyList(), null, false, "plan_update_notice_v1", null));
        register(rules, rule("adjustment_notice", "调剂风险提示", "policy_notice", "info",
                bothModes(), "informational", "not_fixable",
                Collections.<String>emptyList(), null, false, "adjustment_notice_v1", null));
        return Collections.unmodifiableMap(rules);
    }

    private static void register(Map<String, ReviewRuleMetadataDTO> rules, ReviewRuleMetadataDTO metadata) {
        rules.put(metadata.getCode(), metadata);
    }

    private static ReviewRuleMetadataDTO rule(String code,
                                              String label,
                                              String category,
                                              String severityDefault,
                                              List<String> targetModes,
                                              String scopeKind,
                                              String fixability,
                                              List<String> supportedFixStrategies,
                                              String defaultFixStrategy,
                                              boolean requiresConfirmation,
                                              String evidenceSchema,
                                              String postApplyValidationRule) {
        ReviewRuleMetadataDTO metadata = new ReviewRuleMetadataDTO();
        metadata.setCode(code);
        metadata.setLabel(label);
        metadata.setCategory(category);
        metadata.setSeverityDefault(severityDefault);
        metadata.setTargetModes(Lists.newArrayList(targetModes));
        metadata.setScopeKind(scopeKind);
        metadata.setFixability(fixability);
        metadata.setSupportedFixStrategies(Lists.newArrayList(supportedFixStrategies));
        metadata.setDefaultFixStrategy(defaultFixStrategy);
        metadata.setRequiresConfirmation(requiresConfirmation);
        metadata.setEvidenceSchema(evidenceSchema);
        metadata.setPostApplyValidationRule(postApplyValidationRule);
        return metadata;
    }

    private static ReviewRuleMetadataDTO copy(ReviewRuleMetadataDTO source) {
        ReviewRuleMetadataDTO target = new ReviewRuleMetadataDTO();
        target.setCode(source.getCode());
        target.setLabel(source.getLabel());
        target.setCategory(source.getCategory());
        target.setSeverityDefault(source.getSeverityDefault());
        target.setTargetModes(Lists.newArrayList(source.getTargetModes()));
        target.setScopeKind(source.getScopeKind());
        target.setFixability(source.getFixability());
        target.setSupportedFixStrategies(Lists.newArrayList(source.getSupportedFixStrategies()));
        target.setDefaultFixStrategy(source.getDefaultFixStrategy());
        target.setRequiresConfirmation(source.getRequiresConfirmation());
        target.setEvidenceSchema(source.getEvidenceSchema());
        target.setPostApplyValidationRule(source.getPostApplyValidationRule());
        return target;
    }

    private static String normalizeCode(String code) {
        return code == null ? "" : code.trim();
    }

    private static List<String> bothModes() {
        return Lists.newArrayList(MODE_MAJOR, MODE_MAJOR_GROUP);
    }

    private static List<String> majorGroupOnly() {
        return Lists.newArrayList(MODE_MAJOR_GROUP);
    }

    private static List<String> strategies(String... strategies) {
        return Lists.newArrayList(strategies);
    }
}
