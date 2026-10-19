package com.ytell.zhiyuan.service.biz;

import com.google.common.base.Strings;
import com.google.common.collect.Lists;
import com.google.common.collect.Maps;
import com.ytell.zhiyuan.model.dto.planning.CoverageRequirementDTO;
import com.ytell.zhiyuan.model.dto.planning.EvaluationContextDTO;
import com.ytell.zhiyuan.model.dto.planning.EvaluationEntryRefDTO;
import com.ytell.zhiyuan.model.dto.planning.EvaluationFindingDTO;
import com.ytell.zhiyuan.model.dto.planning.EvaluationProbeMetadataDTO;
import com.ytell.zhiyuan.model.dto.planning.ObjectiveDeltaDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanEvaluationDTO;
import com.ytell.zhiyuan.model.dto.planning.ReviewCheckDTO;
import com.ytell.zhiyuan.model.dto.planning.ReviewStateDTO;
import com.ytell.zhiyuan.model.dto.planning.StructureVectorDTO;
import com.ytell.zhiyuan.model.dto.planning.TierAllocationConstraintDTO;
import com.ytell.zhiyuan.model.dto.planning.TierCountRangeDTO;

import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * 旧 review check → 新 PlanEvaluation 的**影子映射**（J5.0）。
 *
 * <p>不改变审查行为：旧 `ReviewStateDTO.checks` 仍是权威输出；本类把同一份
 * 检查结果翻译成四字段 finding，用于 golden diff 和 J5.2 切换前的对照。
 * `count_validation` 按注册表拆成两个 probe；J5.4 起 coverage/safety/ratio、
 * 倒挂、高收费与条目级风险标签改为由 EvaluationContext 反向派生，
 * 有足够上下文数据时跳过对应 check 的翻译，其余仍 1:1。</p>
 */
public class ReviewEvaluationMapper {

    /** 相邻录取率比较的浮点容差，避免同值因浮点误差被判倒挂。 */
    private static final double RATIO_EPSILON = 1e-9D;

    private final FindingObjectiveDeltaBuilder deltaBuilder = new FindingObjectiveDeltaBuilder();
    private final PlanCommandCompiler commandCompiler = new PlanCommandCompiler();

    public PlanEvaluationDTO map(ReviewStateDTO reviewState, EvaluationContextDTO context) {
        EvaluationContextDTO safeContext = context == null ? new EvaluationContextDTO() : context;
        PlanEvaluationDTO evaluation = new PlanEvaluationDTO();
        String objectiveModelVersion = EvaluationVersion.objectiveModelVersion();
        evaluation.setObjectiveModelVersion(objectiveModelVersion);
        evaluation.setPlanVersion(safeContext.getEvaluatedStateVersion());
        evaluation.setEvaluatedStateVersion(safeContext.getEvaluatedStateVersion());
        evaluation.setPlanContentDigest(safeContext.getPlanContentDigest());
        evaluation.setCandidateSourceVersion(safeContext.getCandidateSourceVersion());
        evaluation.setDataVersion(safeContext.getDataVersion());
        evaluation.setEvaluationVersion(EvaluationVersion.evaluationVersion(
                safeContext.getEvaluatedStateVersion(),
                safeContext.getPlanContentDigest(),
                safeContext.getCandidateSourceVersion(),
                safeContext.getDataVersion(),
                objectiveModelVersion));
        evaluation.setStructure(buildStructure(safeContext));

        if (reviewState == null || reviewState.getChecks() == null || reviewState.getChecks().isEmpty()) {
            evaluation.setStatus("unavailable");
            evaluation.setProbesRun(0);
            evaluation.setHardFeasible(false);
            evaluation.setObjectiveDigest(digestFindings(evaluation.getFindings()));
            return evaluation;
        }

        boolean deriveInversion = hasRatioData(safeContext);
        boolean deriveHighTuition = hasTuitionData(safeContext);
        boolean deriveItemRisks = hasEntryRefData(safeContext);
        List<EvaluationFindingDTO> findings = Lists.newArrayList();
        for (ReviewCheckDTO check : reviewState.getChecks()) {
            if (check == null || Strings.isNullOrEmpty(check.getCode())) {
                continue;
            }
            if ("safety_guard".equals(check.getCode())) {
                // J5.4：safety 由 context 的保底口径派生，不再翻译旧 review check。
                continue;
            }
            if ("ratio_distribution".equals(check.getCode())
                    && safeContext.getTierConstraint() != null) {
                // 有显式配额时，配比以配额边界为准；软带 check 不再参与。
                continue;
            }
            if ("probability_inversion".equals(check.getCode()) && deriveInversion) {
                // J5.4：context 有可比录取率时，倒挂由条目序列派生。
                continue;
            }
            if ("high_tuition".equals(check.getCode()) && deriveHighTuition) {
                // J5.4：context 有学费数据时，高收费由条目学费派生。
                continue;
            }
            if ("edge_score".equals(check.getCode())
                    && safeContext.getUserScore() != null
                    && safeContext.getBatchScore() != null) {
                // J5.4：分数/批次线都在 context 时，边缘分由同一判据派生。
                continue;
            }
            if (("admission_limit".equals(check.getCode())
                    || "special_enrollment".equals(check.getCode())
                    || "cooperative_program".equals(check.getCode()))
                    && deriveItemRisks) {
                // J5.4：条目级风险标签由 context.entries[].riskFlags 派生。
                continue;
            }
            if ("count_validation".equals(check.getCode())) {
                findings.add(mapCountHard(check, safeContext));
                findings.add(mapCountTarget(check, safeContext));
            } else {
                EvaluationFindingDTO finding = mapOne(check, safeContext);
                if (finding != null) {
                    findings.add(finding);
                }
            }
        }
        findings.addAll(mapCoverage(safeContext));
        EvaluationFindingDTO safety = mapSafety(safeContext);
        if (safety != null) {
            findings.add(safety);
        }
        EvaluationFindingDTO ratio = mapTierRatio(safeContext);
        if (ratio != null) {
            findings.add(ratio);
        }
        if (deriveInversion) {
            addIfPresent(findings, mapProbabilityInversion(safeContext));
        }
        if (deriveHighTuition) {
            addIfPresent(findings, mapHighTuition(safeContext));
        }
        if (deriveItemRisks) {
            addIfPresent(findings, mapRiskFlag(safeContext, "admission_limit",
                    "当前方案未发现明显限报标签", "当前方案包含限制报考专业"));
            addIfPresent(findings, mapRiskFlag(safeContext, "special_enrollment",
                    "当前方案未发现特殊类型招生标签", "当前方案包含特殊类型招生志愿"));
            addIfPresent(findings, mapRiskFlag(safeContext, "cooperative_program",
                    "当前方案未发现中外合作办学项目", "当前方案包含中外合作办学项目"));
        }
        if (safeContext.getUserScore() != null && safeContext.getBatchScore() != null) {
            addIfPresent(findings, mapEdgeScore(safeContext));
        }
        for (EvaluationFindingDTO finding : findings) {
            if ("unknown".equals(finding.getResultStatus())) {
                finding.setFixability("needs_input");
            }
            ObjectiveDeltaDTO delta = deltaBuilder.build(finding, safeContext);
            finding.setObjectiveDelta(delta);
            finding.setSuggestedCommand(commandCompiler.compile(delta, safeContext));
        }
        evaluation.setFindings(findings);
        evaluation.setProbesRun(findings.size());
        evaluation.setStatus("completed");
        evaluation.setHardFeasible(hardFeasible(findings));
        evaluation.setObjectiveDigest(digestFindings(findings));
        return evaluation;
    }

    /**
     * J5.4：coverage finding 由 context 的已确认覆盖要求 + 条目命中集合派生，
     * 不依赖旧 review check。每个要求一条 finding，id=coverage:index。
     */
    private List<EvaluationFindingDTO> mapCoverage(EvaluationContextDTO context) {
        List<EvaluationFindingDTO> findings = Lists.newArrayList();
        EvaluationProbeMetadataDTO metadata = EvaluationProbeRegistry.get("coverage");
        if (metadata == null) {
            return findings;
        }
        List<CoverageRequirementDTO> requirements = context.getCoverageRequirements() == null
                ? Lists.<CoverageRequirementDTO>newArrayList() : context.getCoverageRequirements();
        for (int index = 0; index < requirements.size(); index++) {
            CoverageRequirementDTO requirement = requirements.get(index);
            String coverageId = "coverage:" + index;
            int required = CoverageRequirementSupport.minCount(requirement);
            List<EvaluationEntryRefDTO> matched = Lists.newArrayList();
            for (EvaluationEntryRefDTO entry : safeList(context.getEntries())) {
                if (entry != null && safeList(entry.getMatchedCoverageIds()).contains(coverageId)) {
                    matched.add(entry);
                }
            }
            boolean passed = matched.size() >= required;
            EvaluationFindingDTO finding = new EvaluationFindingDTO();
            finding.setCode(coverageId);
            finding.setLayer(metadata.getLayer());
            finding.setRuleStrength(metadata.getRuleStrength());
            finding.setFixability(metadata.getFixability());
            finding.setMetric(metadata.getMetric());
            finding.setResultStatus(passed ? "pass" : "fail");
            finding.setDisplaySeverity(passed ? "info" : "action");
            finding.setSummary((passed ? "覆盖要求已满足：" : "覆盖要求未满足：")
                    + coverageLabel(requirement) + "（" + matched.size() + "/" + required + "）");
            if (!passed) {
                finding.setReasonCode("coverage_shortfall");
            }
            Map<String, Object> threshold = Maps.newLinkedHashMap();
            threshold.put("domain", requirement == null ? null : requirement.getDomain());
            threshold.put("key", requirement == null ? null : requirement.getKey());
            threshold.put("values", requirement == null ? null : requirement.getValues());
            threshold.put("minCount", required);
            threshold.put("matchedCount", matched.size());
            finding.setThreshold(threshold);
            finding.setAffectedEntryRefs(matched);
            validateCombination(finding, metadata);
            findings.add(finding);
        }
        return findings;
    }

    private String coverageLabel(CoverageRequirementDTO requirement) {
        if (requirement == null) {
            return "未命名覆盖要求";
        }
        return Strings.nullToEmpty(requirement.getDomain()) + "/"
                + Strings.nullToEmpty(requirement.getKey()) + " "
                + String.join("、", safeList(requirement.getValues()));
    }

    /**
     * J5.4：本省保底 finding 由 context 的 SafetyFloorSupport 口径派生。
     * not_applicable/unknown 只解释不阻断；applicable 时 actual &lt; required 才 fail/block。
     */
    private EvaluationFindingDTO mapSafety(EvaluationContextDTO context) {
        EvaluationProbeMetadataDTO metadata = EvaluationProbeRegistry.get("safety_guard");
        if (metadata == null) {
            return null;
        }
        int required = context.getSafetyMinLocalProtect() == null
                ? 0 : context.getSafetyMinLocalProtect();
        String mode = context.getSafetyFloorMode();
        List<EvaluationEntryRefDTO> matched = Lists.newArrayList();
        for (EvaluationEntryRefDTO entry : safeList(context.getEntries())) {
            if (entry != null
                    && "protect".equals(TierAllocationSupport.canonicalTierKey(entry.getPathTier()))
                    && RegionScopeSupport.sameRegionName(entry.getProvinceName(),
                    context.getSourceProvince())) {
                matched.add(entry);
            }
        }
        EvaluationFindingDTO finding = derivedFinding(metadata);
        finding.setAffectedEntryRefs(matched);
        Map<String, Object> threshold = Maps.newLinkedHashMap();
        threshold.put("required", required);
        threshold.put("actual", matched.size());
        threshold.put("mode", mode);
        threshold.put("safetyReasonCode", context.getSafetyReasonCode());
        finding.setThreshold(threshold);
        if ("not_applicable".equals(mode)) {
            pass(finding, "生源省已被明确排除，本省保底不适用");
        } else if ("unknown".equals(mode)) {
            // 缺输入不能冒充 pass：hard probe 的 unknown 必须是 block。
            finding.setResultStatus("unknown");
            finding.setDisplaySeverity("block");
            finding.setReasonCode("safety_unknown");
            finding.setSummary("缺少生源省份信息，无法完成本省保底校验");
        } else if (required <= 0 || matched.size() >= required) {
            pass(finding, "本省保底志愿数量满足要求（" + matched.size() + "/" + required + "）");
        } else {
            finding.setResultStatus("fail");
            finding.setDisplaySeverity("block");
            finding.setReasonCode("safety_shortfall");
            finding.setSummary("本省保底志愿数量不足（" + matched.size() + "/" + required + "）");
        }
        validateCombination(finding, metadata);
        return finding;
    }

    /**
     * J5.4：有显式冲稳保配额时，配比 finding 由 context.tierConstraint 与条目档位
     * 计数派生；边界全部满足才 pass，否则按方向给 reasonCode。
     */
    private EvaluationFindingDTO mapTierRatio(EvaluationContextDTO context) {
        TierAllocationConstraintDTO constraint = context.getTierConstraint();
        EvaluationProbeMetadataDTO metadata = EvaluationProbeRegistry.get("ratio_distribution");
        if (constraint == null || metadata == null) {
            return null;
        }
        Map<String, Integer> counts = Maps.newLinkedHashMap();
        counts.put("sprint", 0);
        counts.put("stable", 0);
        counts.put("protect", 0);
        for (EvaluationEntryRefDTO entry : safeList(context.getEntries())) {
            String tier = entry == null
                    ? "" : TierAllocationSupport.canonicalTierKey(entry.getPathTier());
            if (counts.containsKey(tier)) {
                counts.put(tier, counts.get(tier) + 1);
            }
        }
        int sprint = counts.get("sprint");
        int stable = counts.get("stable");
        int protect = counts.get("protect");
        Set<String> outOfBounds = new LinkedHashSet<String>();
        if (!within(constraint.getSprint(), sprint)) {
            outOfBounds.add("sprint");
        }
        if (!within(constraint.getStable(), stable)) {
            outOfBounds.add("stable");
        }
        if (!within(constraint.getProtect(), protect)) {
            outOfBounds.add("protect");
        }
        List<EvaluationEntryRefDTO> affected = Lists.newArrayList();
        for (EvaluationEntryRefDTO entry : safeList(context.getEntries())) {
            if (entry != null && outOfBounds.contains(
                    TierAllocationSupport.canonicalTierKey(entry.getPathTier()))) {
                affected.add(entry);
            }
        }
        EvaluationFindingDTO finding = derivedFinding(metadata);
        finding.setAffectedEntryRefs(affected);
        Map<String, Object> threshold = Maps.newLinkedHashMap();
        threshold.put("sourceType", constraint.getSourceType());
        addTierThreshold(threshold, "sprint", constraint.getSprint(), sprint);
        addTierThreshold(threshold, "stable", constraint.getStable(), stable);
        addTierThreshold(threshold, "protect", constraint.getProtect(), protect);
        finding.setThreshold(threshold);
        if (outOfBounds.isEmpty()) {
            pass(finding, "冲稳保数量与已确认配额一致");
        } else {
            String reasonCode = ratioReasonCode(constraint, sprint, protect);
            finding.setResultStatus("fail");
            finding.setDisplaySeverity("action");
            finding.setReasonCode(reasonCode);
            finding.setSummary(TierQuotaResolver.summary(reasonCode));
        }
        validateCombination(finding, metadata);
        return finding;
    }

    private String ratioReasonCode(TierAllocationConstraintDTO constraint, int sprint, int protect) {
        if (below(constraint.getProtect(), protect)) {
            return "protect_tier_missing";
        }
        if (above(constraint.getSprint(), sprint)) {
            return "sprint_tier_over_limit";
        }
        if (below(constraint.getSprint(), sprint)) {
            return "sprint_tier_missing";
        }
        return "tier_quota_mismatch";
    }

    private void addTierThreshold(Map<String, Object> threshold, String tier,
                                  TierCountRangeDTO bound, int actual) {
        threshold.put(tier + "Actual", actual);
        threshold.put(tier + "Min", bound == null ? null : bound.getMinCount());
        threshold.put(tier + "Max", bound == null ? null : bound.getMaxCount());
    }

    private boolean within(TierCountRangeDTO bound, int actual) {
        if (bound == null) {
            return true;
        }
        return (bound.getMinCount() == null || actual >= bound.getMinCount())
                && (bound.getMaxCount() == null || actual <= bound.getMaxCount());
    }

    private boolean below(TierCountRangeDTO bound, int actual) {
        return bound != null && bound.getMinCount() != null && actual < bound.getMinCount();
    }

    private boolean above(TierCountRangeDTO bound, int actual) {
        return bound != null && bound.getMaxCount() != null && actual > bound.getMaxCount();
    }

    /**
     * J5.4：倒挂由 context 条目按 position（null 最后）排序后相邻录取率比较派生，
     * 与 review check 同向：前一位录取率高于后一位即倒挂。条目没有任何可比
     * 录取率时保留旧 check 翻译，避免把缺数据冒充 pass。
     */
    private EvaluationFindingDTO mapProbabilityInversion(EvaluationContextDTO context) {
        EvaluationProbeMetadataDTO metadata = EvaluationProbeRegistry.get("probability_inversion");
        if (metadata == null) {
            return null;
        }
        List<EvaluationEntryRefDTO> ordered = orderedEntries(context);
        Set<EvaluationEntryRefDTO> affected = new LinkedHashSet<EvaluationEntryRefDTO>();
        int inversionCount = 0;
        for (int index = 1; index < ordered.size(); index++) {
            Double previousRatio = ratioOf(ordered.get(index - 1));
            Double currentRatio = ratioOf(ordered.get(index));
            if (previousRatio == null || currentRatio == null) {
                continue;
            }
            if (previousRatio - currentRatio > RATIO_EPSILON) {
                inversionCount++;
                affected.add(ordered.get(index - 1));
                affected.add(ordered.get(index));
            }
        }
        EvaluationFindingDTO finding = derivedFinding(metadata);
        finding.setAffectedEntryRefs(Lists.newArrayList(affected));
        Map<String, Object> threshold = Maps.newLinkedHashMap();
        threshold.put("inversionCount", inversionCount);
        threshold.put("ratioField", "majorRatio|schoolRatio");
        finding.setThreshold(threshold);
        if (inversionCount == 0) {
            pass(finding, "当前排序未发现录取概率倒挂");
        } else {
            finding.setResultStatus("fail");
            finding.setDisplaySeverity(derivedFailSeverity(metadata));
            finding.setReasonCode("probability_inversion");
            finding.setSummary("当前排序存在录取概率倒挂（" + inversionCount + " 处）");
        }
        validateCombination(finding, metadata);
        return finding;
    }

    /**
     * J5.4：高收费由 context 条目学费直接判定（超过 2 万/学年）。
     * 条目完全没有学费数据时保留旧 check 翻译。
     */
    private EvaluationFindingDTO mapHighTuition(EvaluationContextDTO context) {
        EvaluationProbeMetadataDTO metadata = EvaluationProbeRegistry.get("high_tuition");
        if (metadata == null) {
            return null;
        }
        List<EvaluationEntryRefDTO> affected = Lists.newArrayList();
        Integer maxTuition = null;
        for (EvaluationEntryRefDTO entry : safeList(context.getEntries())) {
            if (entry == null || entry.getTuitionPerYear() == null) {
                continue;
            }
            maxTuition = maxTuition == null
                    ? entry.getTuitionPerYear() : Math.max(maxTuition, entry.getTuitionPerYear());
            if (entry.getTuitionPerYear() > TuitionThresholds.HIGH_TUITION_RISK_PER_YEAR) {
                affected.add(entry);
            }
        }
        EvaluationFindingDTO finding = derivedFinding(metadata);
        finding.setAffectedEntryRefs(affected);
        Map<String, Object> threshold = Maps.newLinkedHashMap();
        threshold.put("thresholdPerYear", TuitionThresholds.HIGH_TUITION_RISK_PER_YEAR);
        threshold.put("maxTuitionPerYear", maxTuition);
        threshold.put("matchedCount", affected.size());
        finding.setThreshold(threshold);
        if (affected.isEmpty()) {
            pass(finding, "当前方案未发现学费超过 2 万/学年的专业");
        } else {
            finding.setResultStatus("fail");
            finding.setDisplaySeverity(derivedFailSeverity(metadata));
            finding.setReasonCode("high_tuition");
            finding.setSummary("当前方案包含高收费专业（" + affected.size()
                    + " 个条目学费超过 2 万/学年）");
        }
        validateCombination(finding, metadata);
        return finding;
    }

    /**
     * J5.4：条目级风险标签（限报/特殊类型/中外合作）由
     * context.entries[].riskFlags 直接派生；条目存在即视为标签数据可用。
     */
    private EvaluationFindingDTO mapRiskFlag(EvaluationContextDTO context, String code,
                                             String passSummary, String failSummary) {
        EvaluationProbeMetadataDTO metadata = EvaluationProbeRegistry.get(code);
        if (metadata == null) {
            return null;
        }
        List<EvaluationEntryRefDTO> affected = Lists.newArrayList();
        for (EvaluationEntryRefDTO entry : safeList(context.getEntries())) {
            if (entry != null && matchesRiskEntry(code, entry)) {
                affected.add(entry);
            }
        }
        EvaluationFindingDTO finding = derivedFinding(metadata);
        finding.setAffectedEntryRefs(affected);
        Map<String, Object> threshold = Maps.newLinkedHashMap();
        threshold.put("riskFlag", code);
        threshold.put("matchedCount", affected.size());
        finding.setThreshold(threshold);
        if (affected.isEmpty()) {
            pass(finding, passSummary);
        } else {
            finding.setResultStatus("fail");
            finding.setDisplaySeverity(derivedFailSeverity(metadata));
            finding.setReasonCode(code);
            finding.setSummary(failSummary + "（" + affected.size() + " 个条目）");
        }
        validateCombination(finding, metadata);
        return finding;
    }

    /**
     * 与 review 的 admission_limit/special_enrollment/cooperative_program 同判据：
     * 标签来自 reasonCodes + riskFlags + mustSubjects；中外合作还看校名/专业名。
     */
    private boolean matchesRiskEntry(String code, EvaluationEntryRefDTO entry) {
        List<String> tags = Lists.newArrayList(safeList(entry.getRiskTags()));
        for (String flag : safeList(entry.getRiskFlags())) {
            if (flag != null && !tags.contains(flag)) {
                tags.add(flag);
            }
        }
        if ("admission_limit".equals(code)) {
            return tags.contains("admission_limit")
                    || containsAny(tags, "色盲", "色弱", "单科", "性别", "语种");
        }
        if ("special_enrollment".equals(code)) {
            return tags.contains("special_enrollment")
                    || containsAny(tags, "专项", "公费", "定向", "免费医学生", "强基",
                    "国家计划", "地方专项", "高校专项");
        }
        if ("cooperative_program".equals(code)) {
            return tags.contains("cooperative_program")
                    || containsAny(tags, "中外合作")
                    || containsText(entry.getSchoolName(), "中外合作")
                    || containsText(entry.getMajorName(), "中外合作");
        }
        return tags.contains(code);
    }

    private boolean containsText(String value, String keyword) {
        return value != null && value.contains(keyword);
    }

    private boolean containsAny(List<String> values, String... keywords) {
        for (String value : values) {
            if (value == null) {
                continue;
            }
            for (String keyword : keywords) {
                if (value.contains(keyword)) {
                    return true;
                }
            }
        }
        return false;
    }

    /** 与 reviewEdgeScore 同判据：分数距批次线 ≤30 判边缘分。 */
    private EvaluationFindingDTO mapEdgeScore(EvaluationContextDTO context) {
        EvaluationProbeMetadataDTO metadata = EvaluationProbeRegistry.get("edge_score");
        if (metadata == null) {
            return null;
        }
        int delta = context.getUserScore() - context.getBatchScore();
        EvaluationFindingDTO finding = derivedFinding(metadata);
        Map<String, Object> threshold = Maps.newLinkedHashMap();
        threshold.put("userScore", context.getUserScore());
        threshold.put("batchScore", context.getBatchScore());
        threshold.put("delta", delta);
        finding.setThreshold(threshold);
        if (delta > 30) {
            pass(finding, "当前分数不属于边缘分数区间");
        } else {
            finding.setResultStatus("fail");
            finding.setDisplaySeverity("notice");
            finding.setReasonCode("edge_score");
            finding.setSummary("当前分数属于边缘分数区间（距批次线 " + delta + " 分）");
        }
        validateCombination(finding, metadata);
        return finding;
    }

    private void addIfPresent(List<EvaluationFindingDTO> findings, EvaluationFindingDTO finding) {
        if (finding != null) {
            findings.add(finding);
        }
    }

    private boolean hasRatioData(EvaluationContextDTO context) {
        for (EvaluationEntryRefDTO entry : safeList(context.getEntries())) {
            if (ratioOf(entry) != null) {
                return true;
            }
        }
        return false;
    }

    private boolean hasTuitionData(EvaluationContextDTO context) {
        for (EvaluationEntryRefDTO entry : safeList(context.getEntries())) {
            if (entry != null && entry.getTuitionPerYear() != null) {
                return true;
            }
        }
        return false;
    }

    private boolean hasEntryRefData(EvaluationContextDTO context) {
        for (EvaluationEntryRefDTO entry : safeList(context.getEntries())) {
            if (entry != null) {
                return true;
            }
        }
        return false;
    }

    /** position 升序即方案顺序；position 缺失的条目排在最后。 */
    private List<EvaluationEntryRefDTO> orderedEntries(EvaluationContextDTO context) {
        List<EvaluationEntryRefDTO> ordered = Lists.newArrayList();
        for (EvaluationEntryRefDTO entry : safeList(context.getEntries())) {
            if (entry != null) {
                ordered.add(entry);
            }
        }
        ordered.sort((left, right) -> {
            Integer leftPosition = left.getPosition();
            Integer rightPosition = right.getPosition();
            if (leftPosition == null && rightPosition == null) {
                return 0;
            }
            if (leftPosition == null) {
                return 1;
            }
            if (rightPosition == null) {
                return -1;
            }
            return Integer.compare(leftPosition, rightPosition);
        });
        return ordered;
    }

    private Double ratioOf(EvaluationEntryRefDTO entry) {
        if (entry == null) {
            return null;
        }
        return entry.getMajorRatio() != null ? entry.getMajorRatio() : entry.getSchoolRatio();
    }

    private String derivedFailSeverity(EvaluationProbeMetadataDTO metadata) {
        if ("hard".equals(metadata.getRuleStrength())) {
            return "block";
        }
        List<String> allowed = safeList(metadata.getAllowedSeverities());
        return allowed.contains("action") ? "action" : allowed.isEmpty() ? "notice" : allowed.get(0);
    }

    private EvaluationFindingDTO derivedFinding(EvaluationProbeMetadataDTO metadata) {
        EvaluationFindingDTO finding = new EvaluationFindingDTO();
        finding.setCode(metadata.getCode());
        finding.setLayer(metadata.getLayer());
        finding.setRuleStrength(metadata.getRuleStrength());
        finding.setFixability(metadata.getFixability());
        finding.setMetric(metadata.getMetric());
        return finding;
    }

    private void pass(EvaluationFindingDTO finding, String summary) {
        finding.setResultStatus("pass");
        finding.setDisplaySeverity("info");
        finding.setSummary(summary);
    }

    private EvaluationFindingDTO mapOne(ReviewCheckDTO check, EvaluationContextDTO context) {
        EvaluationProbeMetadataDTO metadata = EvaluationProbeRegistry.get(check.getCode());
        if (metadata == null) {
            return null;
        }
        boolean unknown = isUnknown(check);
        String resultStatus = unknown ? "unknown"
                : Boolean.FALSE.equals(check.getPassed()) ? "fail" : "pass";
        EvaluationFindingDTO finding = baseFinding(metadata, check, context, resultStatus);
        finding.setDisplaySeverity(displaySeverity(metadata, check, resultStatus));
        validateCombination(finding, metadata);
        return finding;
    }

    /**
     * `count_validation` 的官方口径 probe：官方数量缺失 → unknown；低于官方或
     * 超过官方上限 → fail/block；其余 pass。
     */
    private EvaluationFindingDTO mapCountHard(ReviewCheckDTO check, EvaluationContextDTO context) {
        EvaluationProbeMetadataDTO metadata = EvaluationProbeRegistry.get("count_validation_hard");
        String reasonCode = check.getReasonCode();
        boolean missingOfficial = Boolean.TRUE.equals(check.getPassed())
                && "warn".equals(check.getLevel())
                && Strings.isNullOrEmpty(reasonCode);
        boolean overOrMissing = "count_missing".equals(reasonCode)
                || "count_over_limit".equals(reasonCode);
        // 兜底：低于“方案目标”不是官方口径失败（count_below_target），hard probe 应 pass；
        // 只有官方缺失/低于官方/超过官方上限才进 hard 判据。
        String resultStatus = missingOfficial ? "unknown" : overOrMissing ? "fail" : "pass";
        EvaluationFindingDTO finding = baseFinding(metadata, check, context, resultStatus);
        finding.setDisplaySeverity("pass".equals(resultStatus) ? "info" : "block");
        finding.setSummary(missingOfficial
                ? "缺少官方数量要求，无法完成数量校验"
                : check.getSummary());
        finding.setReasonCode(reasonCode);
        validateCombination(finding, metadata);
        return finding;
    }

    /**
     * `count_validation` 的目标口径 probe：未设置目标 → not_applicable；
     * 低于目标 → fail/action；其余 pass。
     */
    private EvaluationFindingDTO mapCountTarget(ReviewCheckDTO check, EvaluationContextDTO context) {
        EvaluationProbeMetadataDTO metadata = EvaluationProbeRegistry.get("count_target");
        EvaluationFindingDTO finding = baseFinding(metadata, check, context, "pass");
        finding.setReasonCode(check.getReasonCode());
        if (context.getSelectionTargetCount() == null) {
            finding.setResultStatus("not_applicable");
            finding.setDisplaySeverity("info");
            finding.setSummary("未设置方案目标数量，目标口径不适用");
            validateCombination(finding, metadata);
            return finding;
        }
        if ("count_below_target".equals(check.getReasonCode())) {
            finding.setResultStatus("fail");
            finding.setDisplaySeverity("action");
            finding.setSummary(check.getSummary());
        } else {
            finding.setResultStatus("pass");
            finding.setDisplaySeverity("info");
            finding.setSummary("方案目标数量口径已满足");
        }
        validateCombination(finding, metadata);
        return finding;
    }

    private EvaluationFindingDTO baseFinding(EvaluationProbeMetadataDTO metadata,
                                             ReviewCheckDTO check,
                                             EvaluationContextDTO context,
                                             String resultStatus) {
        EvaluationFindingDTO finding = new EvaluationFindingDTO();
        finding.setCode(metadata.getCode());
        finding.setLayer(metadata.getLayer());
        finding.setRuleStrength(metadata.getRuleStrength());
        finding.setFixability(metadata.getFixability());
        finding.setMetric(metadata.getMetric());
        finding.setResultStatus(resultStatus);
        finding.setSummary(Strings.isNullOrEmpty(check.getSummary()) ? metadata.getLabel() : check.getSummary());
        finding.setReasonCode(check.getReasonCode());
        Map<String, Object> threshold = Maps.newLinkedHashMap();
        threshold.put("sourceCheck", metadata.getSourceCheck());
        if (!Strings.isNullOrEmpty(check.getSeverity())) {
            threshold.put("legacySeverity", check.getSeverity());
        }
        if (!Strings.isNullOrEmpty(check.getLevel())) {
            threshold.put("legacyLevel", check.getLevel());
        }
        finding.setThreshold(threshold);
        finding.setAffectedEntryRefs(affectedRefs(check, context));
        return finding;
    }

    private List<EvaluationEntryRefDTO> affectedRefs(ReviewCheckDTO check, EvaluationContextDTO context) {
        List<EvaluationEntryRefDTO> refs = Lists.newArrayList();
        Map<String, EvaluationEntryRefDTO> byUnit = Maps.newHashMap();
        Map<String, EvaluationEntryRefDTO> byVolunteer = Maps.newHashMap();
        for (EvaluationEntryRefDTO entry : safeList(context.getEntries())) {
            if (entry == null || Strings.isNullOrEmpty(entry.getId())) {
                continue;
            }
            if ("unit".equals(entry.getLevel())) {
                byUnit.put(entry.getId(), entry);
            } else {
                byVolunteer.put(entry.getId(), entry);
            }
        }
        for (String unitId : safeList(check.getAffectedUnitIds())) {
            EvaluationEntryRefDTO entry = byUnit.get(unitId);
            refs.add(entry == null ? minimalRef("unit", unitId) : entry);
        }
        for (String volunteerId : safeList(check.getAffectedVolunteerIds())) {
            EvaluationEntryRefDTO entry = byVolunteer.get(volunteerId);
            refs.add(entry == null ? minimalRef("volunteer", volunteerId) : entry);
        }
        return refs;
    }

    private EvaluationEntryRefDTO minimalRef(String level, String id) {
        EvaluationEntryRefDTO entry = new EvaluationEntryRefDTO();
        entry.setLevel(level);
        entry.setId(id);
        return entry;
    }

    private boolean isUnknown(ReviewCheckDTO check) {
        // 旧检查把“缺输入”表达为 passed=true + level=warn（如缺生源省/缺官方数量），
        // 新模型必须显式 unknown；不能冒充 pass。
        return Boolean.TRUE.equals(check.getPassed())
                && "warn".equals(check.getLevel())
                && !"info".equals(check.getSeverity());
    }

    private String displaySeverity(EvaluationProbeMetadataDTO metadata, ReviewCheckDTO check,
                                   String resultStatus) {
        if ("pass".equals(resultStatus)) {
            return "info";
        }
        List<String> allowed = safeList(metadata.getAllowedSeverities());
        if ("hard".equals(metadata.getRuleStrength())) {
            return allowed.contains("block") ? "block" : allowed.get(0);
        }
        String legacy = check.getSeverity();
        if (!Strings.isNullOrEmpty(legacy) && allowed.contains(legacy)) {
            return legacy;
        }
        if (allowed.contains("action")) {
            return "action";
        }
        return allowed.isEmpty() ? "notice" : allowed.get(0);
    }

    private void validateCombination(EvaluationFindingDTO finding, EvaluationProbeMetadataDTO metadata) {
        if ("pass".equals(finding.getResultStatus()) && !"info".equals(finding.getDisplaySeverity())) {
            throw new IllegalArgumentException("pass finding must be info: " + finding.getCode());
        }
        // allowedSeverities 描述 fail/unknown 可用的展示档；pass 一律 info（上面已校验）。
        if (!"pass".equals(finding.getResultStatus())
                && !safeList(metadata.getAllowedSeverities()).contains(finding.getDisplaySeverity())) {
            throw new IllegalArgumentException("displaySeverity not allowed for " + finding.getCode()
                    + ": " + finding.getDisplaySeverity());
        }
        if ("hard".equals(finding.getRuleStrength())
                && !"pass".equals(finding.getResultStatus())
                && !"block".equals(finding.getDisplaySeverity())) {
            throw new IllegalArgumentException("hard fail/unknown must be block: " + finding.getCode());
        }
        if ("policy".equals(finding.getRuleStrength())
                && !"notice".equals(finding.getDisplaySeverity())
                && !"info".equals(finding.getDisplaySeverity())) {
            throw new IllegalArgumentException("policy finding must be notice/info: " + finding.getCode());
        }
    }

    private boolean hardFeasible(List<EvaluationFindingDTO> findings) {
        if (findings == null || findings.isEmpty()) {
            return false;
        }
        for (EvaluationFindingDTO finding : findings) {
            if ("hard".equals(finding.getRuleStrength())
                    && !"pass".equals(finding.getResultStatus())) {
                return false;
            }
        }
        return true;
    }

    private String digestFindings(List<EvaluationFindingDTO> findings) {
        StringBuilder builder = new StringBuilder();
        for (EvaluationFindingDTO finding : findings) {
            builder.append(finding.getCode()).append(':')
                    .append(finding.getResultStatus()).append(';');
        }
        return EvaluationVersion.sha256(builder.toString());
    }

    private StructureVectorDTO buildStructure(EvaluationContextDTO context) {
        return PlanStructureEvaluator.build(context);
    }

    private static <T> List<T> safeList(List<T> value) {
        return value == null ? Lists.newArrayList() : value;
    }
}
