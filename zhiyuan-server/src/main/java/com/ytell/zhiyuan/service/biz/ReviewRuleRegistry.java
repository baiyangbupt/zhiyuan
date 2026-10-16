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

    /**
     * 审查 2.0 四级分级（2026-10-16 review §五-58 校准表）：
     * <ul>
     *   <li>{@code block} 拦下：安全/资格类硬风险，先处理再走后续；
     *       safety_guard、admission_limit、group_inner_safety_guard、官方口径 count 缺口；</li>
     *   <li>{@code action} 建议处理：结构/成本类问题，可一键修复；
     *       ratio_distribution、probability_gap、high_tuition、cooperative_program、
     *       special_enrollment、major_group_safety_intent_alignment；</li>
     *   <li>{@code notice} 提示：需要人工判断是否需要调整；probability_inversion、edge_score；</li>
     *   <li>{@code info} 信息：告知类，无需处理；plan_update_notice、adjustment_notice。</li>
     * </ul>
     */
    private static final String SEVERITY_BLOCK = "block";
    private static final String SEVERITY_ACTION = "action";
    private static final String SEVERITY_NOTICE = "notice";
    private static final String SEVERITY_INFO = "info";

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
        register(rules, rule("ratio_distribution", "冲稳保配比", "structure_risk", "warn", SEVERITY_ACTION,
                bothModes(), "structure", "preview_fixable",
                strategies(RepairProposalTaxonomy.Strategy.REBALANCE_TIER_RATIO,
                        RepairProposalTaxonomy.Strategy.REPLACE_RISK_ITEMS,
                        "regenerate_plan_with_constraints"),
                RepairProposalTaxonomy.Strategy.REBALANCE_TIER_RATIO, true, "tier_ratio_v1", "ratio_distribution"));
        register(rules, rule("safety_guard", "本省保底不足", "structure_risk", "risk", SEVERITY_BLOCK,
                bothModes(), "structure", "preview_fixable",
                strategies(RepairProposalTaxonomy.Strategy.ADD_SAFETY_ITEMS,
                        RepairProposalTaxonomy.Strategy.REPLACE_RISK_ITEMS,
                        RepairProposalTaxonomy.Strategy.FILL_MISSING_COUNT),
                RepairProposalTaxonomy.Strategy.ADD_SAFETY_ITEMS, true, "safety_guard_v1", "safety_guard"));
        register(rules, rule("probability_inversion", "录取率倒挂", "ordering_risk", "warn", SEVERITY_NOTICE,
                bothModes(), "structure", "preview_fixable",
                strategies(RepairProposalTaxonomy.Strategy.SORT_BY_PROBABILITY,
                        RepairProposalTaxonomy.Strategy.REPLACE_RISK_ITEMS,
                        "regenerate_order"),
                RepairProposalTaxonomy.Strategy.SORT_BY_PROBABILITY, true, "probability_inversion_v1", "probability_inversion"));
        register(rules, rule("probability_gap", "录取率梯度断层", "structure_risk", "warn", SEVERITY_ACTION,
                bothModes(), "structure", "preview_fixable",
                strategies(RepairProposalTaxonomy.Strategy.FILL_PROBABILITY_GAP,
                        RepairProposalTaxonomy.Strategy.REPLACE_RISK_ITEMS,
                        RepairProposalTaxonomy.Strategy.REBALANCE_TIER_RATIO),
                RepairProposalTaxonomy.Strategy.FILL_PROBABILITY_GAP, true, "probability_gap_v1", "probability_gap"));
        // count_validation 默认 block（官方口径数量缺口）；有方案目标（selectionTargetCount）时由
        // PlanningStateService 按结果降级：低于目标→action、目标内超额→info（2026-10-16 §五-58 数量感知）。
        register(rules, rule("count_validation", "数量校验", "structure_risk", "risk", SEVERITY_BLOCK,
                bothModes(), "structure", "preview_fixable",
                strategies(RepairProposalTaxonomy.Strategy.FILL_MISSING_COUNT,
                        "regenerate_plan_with_constraints"),
                RepairProposalTaxonomy.Strategy.FILL_MISSING_COUNT, true, "count_validation_v1", "count_validation"));
        register(rules, rule("high_tuition", "高收费", "item_risk", "warn", SEVERITY_ACTION,
                bothModes(), "item", "preview_fixable",
                strategies(RepairProposalTaxonomy.Strategy.REPLACE_RISK_ITEMS,
                        RepairProposalTaxonomy.Strategy.REMOVE_RISK_ITEMS),
                RepairProposalTaxonomy.Strategy.REPLACE_RISK_ITEMS, true, "high_tuition_v1", "high_tuition"));
        register(rules, rule("admission_limit", "限报条件", "item_risk", "risk", SEVERITY_BLOCK,
                bothModes(), "item", "preview_fixable",
                strategies(RepairProposalTaxonomy.Strategy.REMOVE_RISK_ITEMS,
                        RepairProposalTaxonomy.Strategy.REPLACE_RISK_ITEMS),
                RepairProposalTaxonomy.Strategy.REMOVE_RISK_ITEMS, true, "admission_limit_v1", "admission_limit"));
        register(rules, rule("special_enrollment", "特殊类型招生", "item_risk", "warn", SEVERITY_ACTION,
                bothModes(), "item", "preview_fixable",
                strategies(RepairProposalTaxonomy.Strategy.REMOVE_RISK_ITEMS,
                        RepairProposalTaxonomy.Strategy.REPLACE_RISK_ITEMS),
                RepairProposalTaxonomy.Strategy.REMOVE_RISK_ITEMS, true, "special_enrollment_v1", "special_enrollment"));
        register(rules, rule("edge_score", "边缘分风险", "structure_risk", "warn", SEVERITY_NOTICE,
                bothModes(), "structure", "preview_fixable",
                strategies(RepairProposalTaxonomy.Strategy.ADD_SAFETY_ITEMS,
                        RepairProposalTaxonomy.Strategy.REBALANCE_TIER_RATIO,
                        RepairProposalTaxonomy.Strategy.REPLACE_RISK_ITEMS),
                RepairProposalTaxonomy.Strategy.ADD_SAFETY_ITEMS, true, "edge_score_v1", "edge_score"));
        register(rules, rule("cooperative_program", "中外合作", "item_risk", "warn", SEVERITY_ACTION,
                bothModes(), "item", "preview_fixable",
                strategies(RepairProposalTaxonomy.Strategy.REPLACE_RISK_ITEMS,
                        RepairProposalTaxonomy.Strategy.REMOVE_RISK_ITEMS),
                RepairProposalTaxonomy.Strategy.REPLACE_RISK_ITEMS, true, "cooperative_program_v1", "cooperative_program"));
        register(rules, rule("major_group_safety_intent_alignment", "非意向托底", "major_group_risk", "warn", SEVERITY_ACTION,
                majorGroupOnly(), "major_group_inner", "preview_fixable",
                strategies(RepairProposalTaxonomy.Strategy.ADJUST_MAJOR_GROUP_INNER_SAFETY,
                        RepairProposalTaxonomy.Strategy.REPLACE_RISK_ITEMS),
                RepairProposalTaxonomy.Strategy.ADJUST_MAJOR_GROUP_INNER_SAFETY, true, "major_group_safety_intent_alignment_v1",
                "major_group_safety_intent_alignment"));
        register(rules, rule("group_inner_safety_guard", "组内安全垫不足", "major_group_risk", "risk", SEVERITY_BLOCK,
                majorGroupOnly(), "major_group_inner", "preview_fixable",
                strategies(RepairProposalTaxonomy.Strategy.ADJUST_MAJOR_GROUP_INNER_SAFETY,
                        RepairProposalTaxonomy.Strategy.REPLACE_RISK_ITEMS),
                RepairProposalTaxonomy.Strategy.ADJUST_MAJOR_GROUP_INNER_SAFETY, true, "group_inner_safety_guard_v1",
                "group_inner_safety_guard"));
        register(rules, rule("plan_update_notice", "招生计划更新提示", "policy_notice", "info", SEVERITY_INFO,
                bothModes(), "informational", "not_fixable",
                Collections.<String>emptyList(), null, false, "plan_update_notice_v1", null));
        register(rules, rule("adjustment_notice", "调剂风险提示", "policy_notice", "info", SEVERITY_INFO,
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
                                              String severity,
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
        metadata.setSeverity(severity);
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
        target.setSeverity(source.getSeverity());
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
