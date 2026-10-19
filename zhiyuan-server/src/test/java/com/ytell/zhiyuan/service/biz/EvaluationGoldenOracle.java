package com.ytell.zhiyuan.service.biz;

import com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO;
import com.ytell.zhiyuan.model.dto.planning.CandidatePoolStateDTO;
import com.ytell.zhiyuan.model.dto.planning.CoverageRequirementDTO;
import com.ytell.zhiyuan.model.dto.planning.EvaluationContextDTO;
import com.ytell.zhiyuan.model.dto.planning.EvaluationEntryRefDTO;
import com.ytell.zhiyuan.model.dto.planning.EvaluationFindingDTO;
import com.ytell.zhiyuan.model.dto.planning.EvaluationProbeMetadataDTO;
import com.ytell.zhiyuan.model.dto.planning.HardPlanningObjectivesDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanEvaluationDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedItemDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedUnitDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningUnitMajorDTO;
import com.ytell.zhiyuan.model.dto.planning.ReviewCheckDTO;
import com.ytell.zhiyuan.model.dto.planning.ReviewStateDTO;
import com.ytell.zhiyuan.model.dto.planning.TierAllocationConstraintDTO;
import com.ytell.zhiyuan.model.dto.planning.TierCountRangeDTO;
import com.ytell.zhiyuan.model.dto.planning.StructureTargetDTO;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import java.util.function.Predicate;
import java.util.stream.Collectors;

import static org.junit.jupiter.api.Assertions.*;

final class EvaluationGoldenOracle {

    private EvaluationGoldenOracle() {
    }

    static void verify(PlanningStateDTO state, EvaluationContextDTO context,
                       PlanEvaluationDTO evaluation, String name, StringBuilder report) {
        ReviewStateDTO review = state.getReviewState();
        verifyContext(state, context, name);
        verifySourceProjection(state, context, name);
        assertEquals("completed", evaluation.getStatus(), name + ": status");
        assertNotNull(evaluation.getEvaluationVersion(), name + ": evaluationVersion");
        assertEquals(context.getEvaluatedStateVersion(), evaluation.getEvaluatedStateVersion(), name + ": source version");
        assertEquals(context.getPlanContentDigest(), evaluation.getPlanContentDigest(), name + ": plan digest");
        assertEquals(context.getCandidateSourceVersion(), evaluation.getCandidateSourceVersion(), name + ": candidate version");
        assertEquals(context.getDataVersion(), evaluation.getDataVersion(), name + ": data version");
        Map<String, Expected> derived = derivedFacts(context);
        Map<String, ReviewCheckDTO> historical = new LinkedHashMap<>();
        Set<String> expectedCodes = new LinkedHashSet<>(derived.keySet());
        for (ReviewCheckDTO check : review.getChecks()) {
            assertNotNull(check, name + ": null review check");
            assertTrue("count_validation".equals(check.getCode())
                    || EvaluationProbeRegistry.get(check.getCode()) != null, name + ": unregistered check " + check.getCode());
            assertNull(historical.put(check.getCode(), check), name + ": duplicate legacy code");
            if ("count_validation".equals(check.getCode())) {
                verifyCount(check, context, evaluation, name, report);
                expectedCodes.addAll(Arrays.asList("count_validation_hard", "count_target"));
            } else if (!derived.containsKey(check.getCode())) {
                EvaluationFindingDTO actual = finding(evaluation, check.getCode());
                assertEquals(legacyStatus(check), actual.getResultStatus(), name + ": strict legacy " + check.getCode());
                assertEquals(legacySeverity(check, actual.getResultStatus()), actual.getDisplaySeverity(),
                        name + ": legacy severity " + check.getCode());
                assertEquals(check.getReasonCode(), actual.getReasonCode(), name + ": legacy reason " + check.getCode());
                expectedCodes.add(check.getCode());
                report.append("LEGACY_STRICT ").append(check.getCode()).append(" legacy=")
                        .append(rawStatus(check)).append('/').append(check.getSeverity())
                        .append(" translated=").append(actual.getResultStatus()).append('/')
                        .append(actual.getDisplaySeverity()).append(" reason=").append(actual.getReasonCode()).append('\n');
            }
        }
        for (Map.Entry<String, Expected> entry : derived.entrySet()) {
            String code = entry.getKey();
            Expected expected = entry.getValue();
            EvaluationFindingDTO actual = finding(evaluation, code);
            String label = name + ": derived " + code;
            assertEquals(expected.status, actual.getResultStatus(), label + " status");
            assertEquals(expected.severity, actual.getDisplaySeverity(), label + " severity");
            assertEquals(expected.reason, actual.getReasonCode(), label + " reason");
            assertEquals(expected.facts, actual.getThreshold(), label + " independently counted facts");
            assertEquals(refs(expected.affected), refs(actual.getAffectedEntryRefs()), label + " affected entries");
            ReviewCheckDTO old = historical.get(code);
            boolean difference = old != null && (!legacyStatus(old).equals(expected.status)
                    || !Objects.equals(legacySeverity(old, legacyStatus(old)), expected.severity));
            report.append("MIGRATION ").append(code).append(" legacy=")
                    .append(old == null ? "absent" : rawStatus(old) + "/" + old.getSeverity())
                    .append(" translated=").append(old == null ? "absent" : legacyStatus(old))
                    .append(" derived=").append(expected.status).append('/').append(expected.severity)
                    .append(" historicalDifference=").append(difference)
                    .append(" reason=").append(expected.reason).append(" basis=").append(expected.basis)
                    .append(" facts=").append(expected.facts).append(" affected=").append(refs(expected.affected))
                    .append(" legacyReason=").append(old == null ? null : old.getReasonCode())
                    .append(" legacySummary=").append(old == null ? null : old.getSummary()).append('\n');
        }
        explainHistoricalCooperation(state, derived.get("cooperative_program"), historical.get("cooperative_program"), report);
        Set<String> actualCodes = new LinkedHashSet<>();
        boolean feasible = true;
        for (EvaluationFindingDTO finding : evaluation.getFindings()) {
            assertTrue(actualCodes.add(finding.getCode()), name + ": duplicate finding " + finding.getCode());
            EvaluationProbeMetadataDTO metadata = EvaluationProbeRegistry.get(
                    finding.getCode().startsWith("coverage:") ? "coverage" : finding.getCode());
            assertNotNull(metadata, name + ": unexpected probe");
            assertEquals(metadata.getLayer(), finding.getLayer(), name + ": layer " + finding.getCode());
            assertEquals(metadata.getRuleStrength(), finding.getRuleStrength(), name + ": strength " + finding.getCode());
            if ("hard".equals(finding.getRuleStrength()) && !"pass".equals(finding.getResultStatus())) {
                feasible = false;
            }
        }
        assertEquals(expectedCodes, actualCodes, name + ": exact probe set");
        assertEquals(expectedCodes.size(), evaluation.getProbesRun(), name + ": probesRun");
        assertEquals(feasible, evaluation.getHardFeasible(), name + ": hard feasibility");
    }

    private static void verifyContext(PlanningStateDTO state, EvaluationContextDTO context, String name) {
        CandidatePoolStateDTO pool = state.getCandidatePoolState();
        HardPlanningObjectivesDTO objectives = state.getConstraintState() == null
                ? null : state.getConstraintState().getHardPlanningObjectives();
        Integer target = objectives == null ? null : objectives.getSelectionTargetCount();
        target = target != null && target > 0 ? target : null;
        assertEquals(target, context.getSelectionTargetCount(), name + ": source selection target");
        assertEquals(CoverageRequirementSupport.confirmedRequirements(state),
                safe(context.getCoverageRequirements()), name + ": source confirmed coverage");
        assertEquals(pool == null ? null : pool.getRequiredCount(), context.getRequiredCount(), name + ": source required count");
        String province = pool == null ? null : pool.getSourceProvinceName();
        Integer score = pool == null ? null : pool.getUserScore();
        assertEquals(province, context.getSourceProvince(), name + ": source province");
        assertEquals(score, context.getUserScore(), name + ": source score");
        assertEquals(pool == null ? null : pool.getBatchScore(), context.getBatchScore(), name + ": source batch score");
        StructureTargetDTO safety = SafetyFloorSupport.build(state);
        assertEquals(safety.getSafetyFloorMode(), context.getSafetyFloorMode(), name + ": source safety mode");
        assertEquals(safety.getMinLocalProtect(), context.getSafetyMinLocalProtect(), name + ": source safety floor");
        assertEquals(safety.getSafetyFloorReasonCode(), context.getSafetyReasonCode(), name + ": source safety reason");
        Integer total = target != null ? target : pool == null ? null : pool.getRequiredCount();
        TierAllocationConstraintDTO expectedTier = null;
        if (TierAllocationSupport.confirmedGoal(state) != null && total != null && total > 0) {
            try {
                expectedTier = TierAllocationSupport.compileConfirmed(state, total).getConstraint();
            } catch (RuntimeException invalidGoal) {
                assertNull(context.getTierConstraint(), name + ": invalid source tier goal");
                return;
            }
        }
        assertEquals(expectedTier, context.getTierConstraint(), name + ": source confirmed tier bounds");
    }

    private static void verifySourceProjection(PlanningStateDTO state, EvaluationContextDTO context, String name) {
        Map<String, CandidateItemDTO> candidates = candidates(state);
        boolean group = state.getCandidatePoolState() != null
                && "majorGroup".equalsIgnoreCase(state.getCandidatePoolState().getVolunteerModel());
        assertEquals(group ? "major_group" : "major", context.getAdmissionMode(), name + ": admission mode");
        int index = 0;
        if (state.getOrderedPlanState() != null && group) {
            for (OrderedUnitDTO unit : safe(state.getOrderedPlanState().getUnits())) {
                if (unit == null) {
                    continue;
                }
                EvaluationEntryRefDTO entry = context.getEntries().get(index++);
                List<CandidateItemDTO> members = new ArrayList<>();
                for (PlanningUnitMajorDTO major : safe(unit.getMajorItems())) {
                    CandidateItemDTO candidate = candidates.get(major.getVolunteerId());
                    if (candidate != null) {
                        members.add(candidate);
                    }
                }
                assertEquals("unit", entry.getLevel(), name + ": unit level");
                assertEquals(unit.getUnitId(), entry.getId(), name + ": unit identity");
                assertEquals(unit.getPosition(), entry.getPosition(), name + ": unit position");
                assertEquals(unit.getSchoolName(), entry.getSchoolName(), name + ": unit school");
                assertNull(entry.getMajorName(), name + ": unit projection has no member major name");
                assertEquals(unit.getProvinceName(), entry.getProvinceName(), name + ": unit province");
                assertEquals(unit.getTier(), entry.getPathTier(), name + ": unit tier");
                assertEquals(unit.getAdmissionRatio(), entry.getMajorRatio(), name + ": unit ratio");
                assertEquals(unit.getSchoolEnrollRatio(), entry.getSchoolRatio(), name + ": unit school ratio");
                verifyCandidateProjection(members, entry, name);
            }
        } else if (state.getOrderedPlanState() != null) {
            for (OrderedItemDTO item : safe(state.getOrderedPlanState().getItems())) {
                if (item == null) {
                    continue;
                }
                EvaluationEntryRefDTO entry = context.getEntries().get(index++);
                CandidateItemDTO candidate = candidates.get(item.getVolunteerId());
                assertEquals("volunteer", entry.getLevel(), name + ": item level");
                assertEquals(item.getVolunteerId(), entry.getId(), name + ": item identity");
                assertEquals(item.getPosition(), entry.getPosition(), name + ": item position");
                assertEquals(item.getSchoolName(), entry.getSchoolName(), name + ": item school");
                assertEquals(item.getMajorName(), entry.getMajorName(), name + ": item major");
                String tier = item.getTier();
                if ((tier == null || tier.isEmpty()) && candidate != null) {
                    tier = candidate.getTier();
                }
                assertEquals(tier, entry.getPathTier(), name + ": raw candidate tier fallback");
                assertEquals(candidate == null ? null : candidate.getProvinceName(), entry.getProvinceName(), name + ": item province");
                assertEquals(candidate == null ? null : candidate.getAdmissionRatio(), entry.getMajorRatio(), name + ": item ratio");
                assertEquals(candidate == null ? null : candidate.getSchoolEnrollRatio(), entry.getSchoolRatio(), name + ": item school ratio");
                verifyCandidateProjection(candidate == null ? Collections.emptyList() : Collections.singletonList(candidate), entry, name);
            }
        }
        assertEquals(index, context.getEntries().size(), name + ": complete raw entry projection");
    }

    private static void verifyCandidateProjection(List<CandidateItemDTO> candidates,
                                                   EvaluationEntryRefDTO entry, String name) {
        Set<String> tags = new LinkedHashSet<>();
        Set<String> flags = new LinkedHashSet<>();
        Integer maximum = null;
        for (CandidateItemDTO candidate : candidates) {
            List<String> raw = new ArrayList<>(safe(candidate.getReasonCodes()));
            raw.addAll(safe(candidate.getRiskFlags()));
            raw.addAll(safe(candidate.getMustSubjects()));
            raw.stream().filter(value -> value != null && !value.isEmpty()).forEach(tags::add);
            if ((candidate.getSchoolName() != null && candidate.getSchoolName().contains("中外合作"))
                    || (candidate.getMajorName() != null && candidate.getMajorName().contains("中外合作"))) {
                tags.add("cooperative_program");
            }
            flags.addAll(safe(candidate.getRiskFlags()));
            if (candidate.getTuitionPerYear() != null) {
                maximum = maximum == null ? candidate.getTuitionPerYear() : Math.max(maximum, candidate.getTuitionPerYear());
            }
        }
        assertEquals(tags, new LinkedHashSet<>(safe(entry.getRiskTags())), name + ": raw candidate risk tags " + entry.getId());
        assertEquals(flags, new LinkedHashSet<>(safe(entry.getRiskFlags())), name + ": raw candidate flags " + entry.getId());
        assertEquals(maximum, entry.getTuitionPerYear(), name + ": raw candidate tuition " + entry.getId());
    }

    private static Map<String, CandidateItemDTO> candidates(PlanningStateDTO state) {
        Map<String, CandidateItemDTO> result = new LinkedHashMap<>();
        if (state.getCandidatePoolState() != null) {
            for (CandidateItemDTO candidate : safe(state.getCandidatePoolState().getItems())) {
                if (candidate != null && candidate.getVolunteerId() != null && !candidate.getVolunteerId().isEmpty()) {
                    result.put(candidate.getVolunteerId(), candidate);
                }
            }
        }
        return result;
    }

    private static void explainHistoricalCooperation(PlanningStateDTO state, Expected derived,
                                                      ReviewCheckDTO historical, StringBuilder report) {
        if (derived == null || state.getOrderedPlanState() == null) {
            return;
        }
        Map<String, CandidateItemDTO> candidates = candidates(state);
        List<String> witnesses = new ArrayList<>();
        List<String> witnessIds = new ArrayList<>();
        Set<String> selected = new LinkedHashSet<>();
        for (OrderedItemDTO item : safe(state.getOrderedPlanState().getItems())) {
            if (item != null) {
                selected.add(item.getVolunteerId());
            }
            CandidateItemDTO candidate = item == null ? null : candidates.get(item.getVolunteerId());
            if (candidate == null) {
                continue;
            }
            List<String> texts = new ArrayList<>(safe(candidate.getReasonCodes()));
            texts.add(candidate.getSchoolName());
            texts.add(candidate.getMajorName());
            if (texts.stream().filter(Objects::nonNull).anyMatch(value -> value.contains("中外合作"))) {
                witnessIds.add(candidate.getVolunteerId());
                witnesses.add(candidate.getVolunteerId() + ":" + candidate.getSchoolName() + "/" + candidate.getMajorName()
                        + " reasonCodes=" + candidate.getReasonCodes() + " riskFlags=" + candidate.getRiskFlags()
                        + " mustSubjects=" + candidate.getMustSubjects());
            }
        }
        List<String> historicalIds = historical == null ? Collections.emptyList() : safe(historical.getAffectedVolunteerIds());
        List<String> selectedHistorical = historicalIds.stream().filter(selected::contains).collect(Collectors.toList());
        report.append("HISTORICAL_EVIDENCE cooperative_program historicalCandidateMatches=")
                .append(witnesses.size()).append(" derivedEntryMatches=").append(derived.affected.size())
                .append(" historicalAffected=").append(historicalIds)
                .append(" selectedHistoricalAffected=").append(selectedHistorical)
                .append(" witnesses=").append(witnesses);
        if (historical != null && "fail".equals(legacyStatus(historical)) && "pass".equals(derived.status)) {
            assertTrue(witnesses.isEmpty(),
                    "cooperative_program false-pass: current selected raw candidate names still identify cooperation: " + witnessIds);
        }
        report.append('\n');
    }

    private static Map<String, Expected> derivedFacts(EvaluationContextDTO context) {
        Map<String, Expected> result = new LinkedHashMap<>();
        List<EvaluationEntryRefDTO> entries = safe(context.getEntries()).stream()
                .filter(Objects::nonNull).collect(Collectors.toList());
        String mode = context.getSafetyFloorMode();
        assertTrue(Arrays.asList("applicable", "not_applicable", "unknown").contains(mode),
                "production safety context must be complete");
        assertNotNull(context.getSafetyMinLocalProtect(), "production safety floor");
        List<EvaluationEntryRefDTO> local = matching(entries, entry -> "protect".equals(tier(entry))
                && !region(context.getSourceProvince()).isEmpty()
                && region(context.getSourceProvince()).equals(region(entry.getProvinceName())));
        int required = context.getSafetyMinLocalProtect();
        String safetyStatus = "unknown".equals(mode) ? "unknown"
                : "not_applicable".equals(mode) || local.size() >= required ? "pass" : "fail";
        result.put("safety_guard", new Expected(safetyStatus,
                "pass".equals(safetyStatus) ? "info" : "block",
                "unknown".equals(safetyStatus) ? "safety_unknown"
                        : "fail".equals(safetyStatus) ? "safety_shortfall" : null,
                "J5.4 effective-only local protect floor from production builder", local,
                facts("required", required, "actual", local.size(), "mode", mode,
                        "safetyReasonCode", context.getSafetyReasonCode())));
        for (int index = 0; index < safe(context.getCoverageRequirements()).size(); index++) {
            CoverageRequirementDTO requirement = context.getCoverageRequirements().get(index);
            String code = "coverage:" + index;
            List<EvaluationEntryRefDTO> matched = matching(entries,
                    entry -> safe(entry.getMatchedCoverageIds()).contains(code));
            int minimum = requirement == null || requirement.getMinCount() == null ? 1 : requirement.getMinCount();
            result.put(code, outcome(matched.size() >= minimum, "action", "coverage_shortfall",
                    "J5.4 confirmed include coverage; count matching entries once", matched,
                    facts("domain", requirement == null ? null : requirement.getDomain(),
                            "key", requirement == null ? null : requirement.getKey(),
                            "values", requirement == null ? null : requirement.getValues(),
                            "minCount", minimum, "matchedCount", matched.size())));
        }
        if (context.getTierConstraint() != null) {
            result.put("ratio_distribution", tierOutcome(entries, context.getTierConstraint()));
        }
        if (entries.stream().anyMatch(entry -> ratio(entry) != null)) {
            List<EvaluationEntryRefDTO> ordered = new ArrayList<>(entries);
            ordered.sort(Comparator.comparing(EvaluationEntryRefDTO::getPosition,
                    Comparator.nullsLast(Comparator.naturalOrder())));
            Set<EvaluationEntryRefDTO> affected = new LinkedHashSet<>();
            int inversions = 0;
            for (int index = 1; index < ordered.size(); index++) {
                EvaluationEntryRefDTO previous = ordered.get(index - 1);
                EvaluationEntryRefDTO current = ordered.get(index);
                if (ratio(previous) != null && ratio(current) != null
                        && ratio(previous) - ratio(current) > 0.000000001D) {
                    inversions++;
                    affected.add(previous);
                    affected.add(current);
                }
            }
            result.put("probability_inversion", outcome(inversions == 0, "notice", "probability_inversion",
                    "J5.4 position-ordered adjacent major ratio, school fallback, epsilon=1e-9; missing pairs skipped",
                    new ArrayList<>(affected), facts("inversionCount", inversions, "ratioField", "majorRatio|schoolRatio")));
        }
        if (entries.stream().anyMatch(entry -> entry.getTuitionPerYear() != null)) {
            List<EvaluationEntryRefDTO> expensive = matching(entries,
                    entry -> entry.getTuitionPerYear() != null && entry.getTuitionPerYear() > 20000);
            Integer maximum = entries.stream().map(EvaluationEntryRefDTO::getTuitionPerYear)
                    .filter(Objects::nonNull).max(Integer::compareTo).orElse(null);
            result.put("high_tuition", outcome(expensive.isEmpty(), "action", "high_tuition",
                    "J5.4 entry tuition > 20000/year (group maximum)", expensive,
                    facts("thresholdPerYear", 20000, "maxTuitionPerYear", maximum, "matchedCount", expensive.size())));
        }
        if (!entries.isEmpty()) {
            for (String code : Arrays.asList("admission_limit", "special_enrollment", "cooperative_program")) {
                List<EvaluationEntryRefDTO> matched = matching(entries, entry -> risk(code, entry));
                result.put(code, outcome(matched.isEmpty(), "admission_limit".equals(code) ? "block" : "action", code,
                        "J5.4 reasonCodes + riskFlags + mustSubjects; cooperation also entry school/major names",
                        matched, facts("riskFlag", code, "matchedCount", matched.size())));
            }
        }
        if (context.getUserScore() != null && context.getBatchScore() != null) {
            int delta = context.getUserScore() - context.getBatchScore();
            result.put("edge_score", outcome(delta > 30, "notice", "edge_score",
                    "J5.4 score minus batch line <= 30", Collections.emptyList(),
                    facts("userScore", context.getUserScore(), "batchScore", context.getBatchScore(), "delta", delta)));
        }
        return result;
    }

    private static Expected tierOutcome(List<EvaluationEntryRefDTO> entries, TierAllocationConstraintDTO constraint) {
        Map<String, Object> facts = facts("sourceType", constraint.getSourceType());
        Set<String> outside = new LinkedHashSet<>();
        String reason = "tier_quota_mismatch";
        for (String tier : Arrays.asList("sprint", "stable", "protect")) {
            int count = (int) entries.stream().filter(entry -> tier.equals(tier(entry))).count();
            TierCountRangeDTO range = "sprint".equals(tier) ? constraint.getSprint()
                    : "stable".equals(tier) ? constraint.getStable() : constraint.getProtect();
            Integer min = range == null ? null : range.getMinCount();
            Integer max = range == null ? null : range.getMaxCount();
            facts.put(tier + "Actual", count);
            facts.put(tier + "Min", min);
            facts.put(tier + "Max", max);
            if ((min != null && count < min) || (max != null && count > max)) {
                outside.add(tier);
            }
            if ("sprint".equals(tier) && min != null && count < min) {
                reason = "sprint_tier_missing";
            } else if ("sprint".equals(tier) && max != null && count > max) {
                reason = "sprint_tier_over_limit";
            } else if ("protect".equals(tier) && min != null && count < min) {
                reason = "protect_tier_missing";
            }
        }
        return outcome(outside.isEmpty(), "action", reason,
                "J5.4 explicit confirmed quota bounds, not historical soft ratio bands",
                matching(entries, entry -> outside.contains(tier(entry))), facts);
    }

    private static void verifyCount(ReviewCheckDTO check, EvaluationContextDTO context,
                                    PlanEvaluationDTO evaluation, String name, StringBuilder report) {
        String reason = check.getReasonCode();
        boolean missing = Boolean.TRUE.equals(check.getPassed()) && "warn".equals(check.getLevel())
                && (reason == null || reason.isEmpty());
        String hardStatus = missing ? "unknown" : Arrays.asList("count_missing", "count_over_limit").contains(reason)
                ? "fail" : "pass";
        String targetStatus = context.getSelectionTargetCount() == null ? "not_applicable"
                : "count_below_target".equals(reason) ? "fail" : "pass";
        for (String code : Arrays.asList("count_validation_hard", "count_target")) {
            boolean hard = "count_validation_hard".equals(code);
            String status = hard ? hardStatus : targetStatus;
            String severity = hard ? "pass".equals(status) ? "info" : "block"
                    : "fail".equals(status) ? "action" : "info";
            EvaluationFindingDTO actual = finding(evaluation, code);
            assertEquals(status, actual.getResultStatus(), name + ": strict split " + code);
            assertEquals(severity, actual.getDisplaySeverity(), name + ": split severity " + code);
            assertEquals(reason, actual.getReasonCode(), name + ": split reason " + code);
            report.append("LEGACY_SPLIT_STRICT ").append(code).append(" legacy=").append(rawStatus(check))
                    .append(" translated=").append(status).append('/').append(severity)
                    .append(" reason=").append(reason).append(" target=").append(context.getSelectionTargetCount()).append('\n');
        }
    }

    static EvaluationFindingDTO finding(PlanEvaluationDTO evaluation, String code) {
        return evaluation.getFindings().stream().filter(item -> code.equals(item.getCode())).findFirst()
                .orElseThrow(() -> new AssertionError("missing finding " + code));
    }

    private static String legacyStatus(ReviewCheckDTO check) {
        return Boolean.TRUE.equals(check.getPassed()) && "warn".equals(check.getLevel())
                && !"info".equals(check.getSeverity()) ? "unknown" : rawStatus(check);
    }

    private static String rawStatus(ReviewCheckDTO check) {
        return Boolean.FALSE.equals(check.getPassed()) ? "fail" : "pass";
    }

    private static String legacySeverity(ReviewCheckDTO check, String status) {
        if ("pass".equals(status)) {
            return "info";
        }
        EvaluationProbeMetadataDTO metadata = EvaluationProbeRegistry.get(check.getCode());
        if ("hard".equals(metadata.getRuleStrength())) {
            return "block";
        }
        List<String> allowed = metadata.getAllowedSeverities();
        return allowed.contains(check.getSeverity()) ? check.getSeverity()
                : allowed.contains("action") ? "action" : allowed.isEmpty() ? "notice" : allowed.get(0);
    }

    private static boolean risk(String code, EvaluationEntryRefDTO entry) {
        List<String> tags = new ArrayList<>(safe(entry.getRiskTags()));
        tags.addAll(safe(entry.getRiskFlags()));
        List<String> keywords = "admission_limit".equals(code) ? Arrays.asList("色盲", "色弱", "单科", "性别", "语种")
                : "special_enrollment".equals(code) ? Arrays.asList("专项", "公费", "定向", "免费医学生", "强基", "国家计划", "地方专项", "高校专项")
                : Collections.singletonList("中外合作");
        return tags.contains(code) || tags.stream().filter(Objects::nonNull)
                .anyMatch(tag -> keywords.stream().anyMatch(tag::contains))
                || ("cooperative_program".equals(code) && ((entry.getSchoolName() != null
                && entry.getSchoolName().contains("中外合作")) || (entry.getMajorName() != null
                && entry.getMajorName().contains("中外合作"))));
    }

    private static String tier(EvaluationEntryRefDTO entry) {
        String value = entry.getPathTier() == null ? "" : entry.getPathTier().trim().toLowerCase(java.util.Locale.ROOT);
        if (Arrays.asList("冲", "冲刺", "sprint", "reach").contains(value)) {
            return "sprint";
        }
        if (Arrays.asList("稳", "稳妥", "stable", "safe").contains(value)) {
            return "stable";
        }
        return Arrays.asList("保", "保底", "兜底", "保险", "protect", "protective", "safety").contains(value)
                ? "protect" : "unknown";
    }

    private static String region(String value) {
        return value == null ? "" : value.trim().replaceFirst(
                "(维吾尔自治区|壮族自治区|回族自治区|自治区|特别行政区|省|市)$", "").replaceAll("\\s+", "").toLowerCase(java.util.Locale.ROOT);
    }

    private static Double ratio(EvaluationEntryRefDTO entry) {
        return entry.getMajorRatio() == null ? entry.getSchoolRatio() : entry.getMajorRatio();
    }

    private static List<EvaluationEntryRefDTO> matching(List<EvaluationEntryRefDTO> entries,
                                                        Predicate<EvaluationEntryRefDTO> predicate) {
        return entries.stream().filter(predicate).collect(Collectors.toList());
    }

    private static List<String> refs(List<EvaluationEntryRefDTO> entries) {
        return safe(entries).stream().map(entry -> entry.getLevel() + ":" + entry.getId()).collect(Collectors.toList());
    }

    private static Map<String, Object> facts(Object... values) {
        Map<String, Object> result = new LinkedHashMap<>();
        for (int index = 0; index < values.length; index += 2) {
            result.put((String) values[index], values[index + 1]);
        }
        return result;
    }

    private static Expected outcome(boolean passed, String severity, String reason, String basis,
                                     List<EvaluationEntryRefDTO> affected, Map<String, Object> facts) {
        return new Expected(passed ? "pass" : "fail", passed ? "info" : severity,
                passed ? null : reason, basis, affected, facts);
    }

    private static <T> List<T> safe(List<T> values) {
        return values == null ? Collections.emptyList() : values;
    }

    private static final class Expected {
        private final String status;
        private final String severity;
        private final String reason;
        private final String basis;
        private final List<EvaluationEntryRefDTO> affected;
        private final Map<String, Object> facts;

        private Expected(String status, String severity, String reason, String basis,
                         List<EvaluationEntryRefDTO> affected, Map<String, Object> facts) {
            this.status = status;
            this.severity = severity;
            this.reason = reason;
            this.basis = basis;
            this.affected = affected;
            this.facts = facts;
        }
    }
}
