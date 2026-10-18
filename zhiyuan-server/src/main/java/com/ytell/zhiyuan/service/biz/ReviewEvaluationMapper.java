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
import com.ytell.zhiyuan.model.dto.planning.ReviewRuleMetadataDTO;
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
 * <p>不改变审查行为：旧 `ReviewStateDTO.checks` 仍是权威输出；本类只把同一份
 * 检查结果翻译成四字段 finding，用于 golden diff 和 J5.2 切换前的对照。
 * `count_validation` 按注册表拆成两个 probe；其余 1:1。</p>
 */
public class ReviewEvaluationMapper {

    private final ActionCompiler actionCompiler = new ActionCompiler();

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
        // J5.2：未通过/未知的 finding 带 delta，修复意图统一由 ActionCompiler 编译；
        // pass/not_applicable 必须保持 null（“已通过还建议改”是非法组合）。
        if (!"pass".equals(resultStatus) && !"not_applicable".equals(resultStatus)) {
            ObjectiveDeltaDTO delta = buildDelta(metadata, check, finding.getAffectedEntryRefs());
            finding.setObjectiveDelta(delta);
            finding.setSuggestedCommand(actionCompiler.compile(delta));
        }
        return finding;
    }

    private ObjectiveDeltaDTO buildDelta(EvaluationProbeMetadataDTO metadata,
                                         ReviewCheckDTO check,
                                         List<EvaluationEntryRefDTO> refs) {
        ReviewRuleMetadataDTO rule = ReviewRuleRegistry.get(metadata.getSourceCheck());
        String strategy = rule == null ? null : rule.getDefaultFixStrategy();
        if (Strings.isNullOrEmpty(strategy)) {
            return null;
        }
        // 数量超官方上限是“精简”，不是“补足”——按结果码纠正默认策略。
        if ("count_over_limit".equals(check.getReasonCode())) {
            strategy = RepairProposalTaxonomy.Strategy.REMOVE_RISK_ITEMS;
        }
        ObjectiveDeltaDTO delta = new ObjectiveDeltaDTO();
        delta.setStrategy(strategy);
        delta.setSourceCheck(metadata.getSourceCheck());
        delta.setReasonCode(Strings.isNullOrEmpty(check.getReasonCode())
                ? metadata.getCode() : check.getReasonCode());
        String normalized = strategy.toLowerCase();
        if (normalized.contains("sort") || normalized.contains("reorder")
                || normalized.contains("regenerate_order")) {
            delta.getReorderTargets().addAll(refs);
        } else if (normalized.contains("remove") || normalized.contains("replace")) {
            delta.getRemoveTargets().addAll(refs);
        } else {
            delta.getAddTargets().addAll(refs);
        }
        return delta;
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
