package com.ytell.zhiyuan.service.biz;

import com.google.common.base.Strings;
import com.google.common.collect.Lists;
import com.google.common.collect.Maps;
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

import java.util.List;
import java.util.Map;

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
        evaluation.setFindings(findings);
        evaluation.setProbesRun(findings.size());
        evaluation.setStatus("completed");
        evaluation.setHardFeasible(hardFeasible(findings));
        evaluation.setObjectiveDigest(digestFindings(findings));
        return evaluation;
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
