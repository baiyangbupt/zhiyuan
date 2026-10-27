package com.ytell.zhiyuan.service.biz;

import com.google.common.base.Strings;
import com.google.common.collect.Lists;
import com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO;
import com.ytell.zhiyuan.model.dto.planning.EvaluationContextDTO;
import com.ytell.zhiyuan.model.dto.planning.EvaluationEntryRefDTO;
import com.ytell.zhiyuan.model.dto.planning.EvaluationFindingDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedItemDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedUnitDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanEvaluationDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningUnitDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningUnitMajorDTO;
import com.ytell.zhiyuan.model.dto.planning.StructureVectorDTO;
import com.ytell.zhiyuan.model.dto.planning.TierAllocationConstraintDTO;

import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;

/**
 * C 批：不依赖旧 review checks/probes 的只读质量评价 v2。
 *
 * <p>只回答四类问题：资格可行性、已确认偏好适配、结构建议、证据未知。
 * 不运行、也不翻译旧经验 probe；不生成可确认建议。unknown 不是 pass。</p>
 */
public class PlanQualityEvaluationService {

    static final String QUALITY_POLICY_VERSION = "plan-quality-v2.1";
    static final String OBJECTIVE_MODEL_VERSION = "quality-v2";

    private final EvaluationContextBuilder contextBuilder = new EvaluationContextBuilder();

    public PlanEvaluationDTO evaluate(PlanningStateDTO state, List<CandidateItemDTO> candidates) {
        EvaluationContextDTO context = contextBuilder.build(state, candidates, null);
        List<EvaluationEntryRefDTO> entries = defaultList(context.getEntries());
        PlanEvaluationDTO evaluation = new PlanEvaluationDTO();
        evaluation.setPlanVersion(context.getEvaluatedStateVersion());
        evaluation.setEvaluatedStateVersion(context.getEvaluatedStateVersion());
        evaluation.setPlanContentDigest(context.getPlanContentDigest());
        evaluation.setCandidateSourceVersion(context.getCandidateSourceVersion());
        evaluation.setDataVersion(context.getDataVersion());
        evaluation.setObjectiveModelVersion(OBJECTIVE_MODEL_VERSION);
        evaluation.setQualityPolicyVersion(QUALITY_POLICY_VERSION);
        evaluation.setReviewAvailability(ReviewPolicy.availability());
        evaluation.setStatus(entries.isEmpty() ? "no_plan" : "completed");
        evaluation.setStructure(structure(entries));

        List<EvaluationFindingDTO> findings = Lists.newArrayList();
        if (entries.isEmpty()) {
            findings.add(finding("plan_empty", "structure", "unknown", "system", "info",
                    "当前没有可评价的正式方案", "plan_empty", entries));
            evaluation.setProbesRun(findings.size());
            evaluation.setFindings(findings);
            evaluation.setHardFeasible(null);
            evaluation.setObjectiveDigest(EvaluationVersion.sha256(findings.toString()));
            evaluation.setEvaluationVersion(version(context, evaluation));
            return evaluation;
        }

        findings.add(eligibility(state, entries));
        findings.add(preference(state, entries));
        findings.add(tierSequence(entries));
        findings.add(count(state, context, entries));
        findings.add(dataCoverage(entries));
        findings.add(ratioGradient(entries));
        findings.add(diversity(entries));
        findings.add(evidence(context, state));

        boolean eligibilityFail = false;
        boolean eligibilityUnknown = false;
        for (EvaluationFindingDTO finding : findings) {
            if (!"eligibility".equals(finding.getLayer())) {
                continue;
            }
            if ("fail".equals(finding.getResultStatus())) {
                eligibilityFail = true;
            } else if ("unknown".equals(finding.getResultStatus())) {
                eligibilityUnknown = true;
            }
        }
        evaluation.setFindings(findings);
        evaluation.setProbesRun(findings.size());
        evaluation.setHardFeasible(eligibilityFail ? Boolean.FALSE
                : eligibilityUnknown ? null : Boolean.TRUE);
        evaluation.setObjectiveDigest(EvaluationVersion.sha256(findings.toString()));
        evaluation.setEvaluationVersion(version(context, evaluation));
        return evaluation;
    }

    private EvaluationFindingDTO eligibility(PlanningStateDTO state,
                                             List<EvaluationEntryRefDTO> entries) {
        Boolean specialPlan = SpecialPlanQualification.specialPlanOf(state);
        List<EvaluationEntryRefDTO> conflicts = Lists.newArrayList();
        List<EvaluationEntryRefDTO> unknown = Lists.newArrayList();
        for (EvaluationEntryRefDTO entry : entries) {
            SpecialPlanRequirementSupport.Requirement requirement =
                    SpecialPlanRequirementSupport.requirement(entry);
            if (SpecialPlanRequirementSupport.conflictsWithNoSpecial(specialPlan, requirement)) {
                conflicts.add(entry);
            } else if (requirement.anyExplicit() || requirement.isUnknown() || requirement.evidenceConflict()) {
                unknown.add(entry);
            }
        }
        if (!conflicts.isEmpty()) {
            return finding("special_plan_conflict", "eligibility", "fail", "hard", "risk",
                    "方案中存在已知专项资格冲突，需要先移除或核对证据",
                    "special_plan_conflict", conflicts);
        }
        List<EvaluationEntryRefDTO> violations = hardConstraintViolations(state, entries);
        if (!violations.isEmpty()) {
            return finding("hard_constraint_violation", "eligibility", "fail", "hard", "risk",
                    "方案中有条目违反已确认的硬约束", "hard_constraint_violation", violations);
        }
        if (!unknown.isEmpty()) {
            return finding("special_plan_unknown", "eligibility", "unknown", "hard", "warn",
                    "方案含专项相关计划，具体专项类别及资格仍需核验",
                    "special_plan_unknown", unknown);
        }
        if (hasRestrictionEvidence(entries)) {
            return finding("restriction_evidence", "eligibility", "warn", "evidence", "warn",
                    "方案中存在身体/语种/限报等资格提示，需要用户自行核对",
                    "restriction_evidence", restrictionEntries(entries));
        }
        return finding("eligibility_feasible", "eligibility", "pass", "hard", "info",
                "未发现已确认资格冲突", null, entries);
    }

    private EvaluationFindingDTO preference(PlanningStateDTO state,
                                            List<EvaluationEntryRefDTO> entries) {
        Set<String> majors = new LinkedHashSet<String>();
        Set<String> schools = new LinkedHashSet<String>();
        Set<String> regions = new LinkedHashSet<String>();
        if (state != null && state.getProfileState() != null
                && state.getProfileState().getExplicitProfile() != null) {
            majors.addAll(defaultList(state.getProfileState().getExplicitProfile().getPositiveMajors()));
            schools.addAll(defaultList(state.getProfileState().getExplicitProfile().getPositiveSchools()));
            regions.addAll(defaultList(state.getProfileState().getExplicitProfile().getPositiveRegions()));
        }
        if (state != null && state.getConstraintState() != null
                && state.getConstraintState().getHardConstraints() != null) {
            majors.addAll(defaultList(state.getConstraintState().getHardConstraints().getMustIncludeMajors()));
            schools.addAll(defaultList(state.getConstraintState().getHardConstraints().getMustIncludeSchools()));
            regions.addAll(defaultList(state.getConstraintState().getHardConstraints().getMustIncludeRegions()));
        }
        if (majors.isEmpty() && schools.isEmpty() && regions.isEmpty()) {
            return finding("preference_no_confirmed_source", "preference", "unknown", "user", "info",
                    "未确认专业/院校/地域正向偏好，本轮不作适配判断",
                    "no_confirmed_preference", entries);
        }
        List<EvaluationEntryRefDTO> matched = Lists.newArrayList();
        for (EvaluationEntryRefDTO entry : entries) {
            if (matchesAny(entry.getMajorName(), majors)
                    || defaultList(entry.getSelectedMajorNames()).stream()
                    .anyMatch(major -> matchesAny(major, majors))
                    || matchesAny(entry.getSchoolName(), schools)
                    || matchesAny(entry.getProvinceName(), regions)) {
                matched.add(entry);
            }
        }
        if (matched.isEmpty()) {
            return finding("preference_not_matched", "preference", "warn", "user", "warn",
                    "当前方案没有命中已确认的正向偏好，请确认是否为有意保留",
                    "preference_not_matched", entries);
        }
        EvaluationFindingDTO finding = finding("preference_matched", "preference", "pass", "user", "info",
                "当前方案命中已确认正向偏好 " + matched.size() + " 条",
                "preference_matched", matched);
        finding.getThreshold().put("matched", matched.size());
        finding.getThreshold().put("total", entries.size());
        return finding;
    }

    private EvaluationFindingDTO tierSequence(List<EvaluationEntryRefDTO> entries) {
        boolean unknown = false;
        int previousRank = -1;
        boolean inverted = false;
        for (EvaluationEntryRefDTO entry : entries) {
            String tier = normalizeTier(entry.getPathTier());
            if ("unknown".equals(tier)) {
                unknown = true;
                continue;
            }
            int rank = tierRank(tier);
            if (previousRank >= 0 && rank < previousRank) {
                inverted = true;
            }
            previousRank = Math.max(previousRank, rank);
        }
        if (inverted) {
            return finding("structure_tier_inversion", "structure", "warn", "system", "warn",
                    "方案存在跨档位排列，按实际顺序展示，不自动修正",
                    "tier_sequence_inverted", entries);
        }
        if (unknown) {
            return finding("structure_tier_unknown", "structure", "unknown", "evidence", "info",
                    "部分条目档位未知，结构顺序只能部分判断", "tier_sequence_unknown", entries);
        }
        return finding("structure_tier_default", "structure", "pass", "system", "info",
                "档位顺序符合冲→稳→保默认结构", "tier_sequence_default", entries);
    }

    /**
     * 录取率梯度：只看档位内部，不把 admissionRatio 当概率。
     * 1.0/空值归 unknown 桶；unknown 不计入覆盖度，只单独限制。
     */
    private EvaluationFindingDTO ratioGradient(List<EvaluationEntryRefDTO> entries) {
        Map<String, Map<String, Integer>> byTier = new LinkedHashMap<String, Map<String, Integer>>();
        for (EvaluationEntryRefDTO entry : defaultList(entries)) {
            String tier = normalizeTier(entry.getPathTier());
            Double ratio = entry.getSchoolRatio() != null ? entry.getSchoolRatio() : entry.getMajorRatio();
            String bucket = AdmissionRatioBucketSupport.bucket(tier, ratio);
            Map<String, Integer> buckets = byTier.get(tier);
            if (buckets == null) {
                buckets = new LinkedHashMap<String, Integer>();
                byTier.put(tier, buckets);
            }
            buckets.put(bucket, buckets.getOrDefault(bucket, 0) + 1);
        }
        String worstTier = null;
        int worstUnknown = 0;
        int worstTotal = 0;
        int worstCoverage = 0;
        int worstMaxShare = 0;
        for (Map.Entry<String, Map<String, Integer>> tierEntry : byTier.entrySet()) {
            if ("unknown".equals(tierEntry.getKey())) {
                continue;
            }
            int total = 0;
            for (Integer count : tierEntry.getValue().values()) {
                total += count == null ? 0 : count;
            }
            if (total < 3) {
                continue;
            }
            int unknown = tierEntry.getValue().getOrDefault(AdmissionRatioBucketSupport.BUCKET_UNKNOWN, 0);
            int coverage = 0;
            int max = 0;
            for (Map.Entry<String, Integer> bucket : tierEntry.getValue().entrySet()) {
                if (AdmissionRatioBucketSupport.BUCKET_UNKNOWN.equals(bucket.getKey())) {
                    continue;
                }
                if (bucket.getValue() != null && bucket.getValue() > 0) {
                    coverage++;
                }
                max = Math.max(max, bucket.getValue() == null ? 0 : bucket.getValue());
            }
            int maxShare = total == 0 ? 0 : Math.round(max * 100.0F / total);
            int unknownShare = total == 0 ? 0 : Math.round(unknown * 100.0F / total);
            int definedBuckets = AdmissionRatioBucketSupport.knownBucketCount(tierEntry.getKey());
            int definedForMath = Math.max(1, definedBuckets);
            // 13 条分 2 个稳档桶，最大桶至少 7 条（54%），这是取整下界，
            // 不能当成“过度集中”。超过下界（或桶覆盖不足）才算 warn。
            int unavoidableMaxShare = total == 0 ? 0
                    : (int) Math.round(Math.ceil((double) total / definedForMath) * 100.0D / total);
            boolean coverageShort = definedBuckets > 0
                    ? coverage < Math.min(2, definedBuckets) : coverage < 2;
            if (unknownShare > 40 || (maxShare > 50 && maxShare > unavoidableMaxShare)
                    || coverageShort) {
                worstTier = tierEntry.getKey();
                worstUnknown = unknown;
                worstTotal = total;
                worstCoverage = coverage;
                worstMaxShare = maxShare;
                break;
            }
        }
        if (worstTier != null) {
            String lowest = worstUnknown > 0
                    ? "最低录取率桶（≤1%）" + worstUnknown + "/" + worstTotal + "；" : "";
            EvaluationFindingDTO finding = finding("ratio_bucket_concentration", "structure", "warn",
                    "system", "warn",
                    worstTier + "档录取率分布偏集中：" + lowest
                            + "覆盖 " + worstCoverage + " 个桶，单桶最大占比 " + worstMaxShare
                            + "%；1.0 代表约 1% 或数据下限，不是精确概率",
                    "ratio_bucket_concentration", entries);
            finding.getThreshold().put("tier", worstTier);
            finding.getThreshold().put("unknown", worstUnknown);
            finding.getThreshold().put("total", worstTotal);
            finding.getThreshold().put("coverage", worstCoverage);
            finding.getThreshold().put("maxBucketShare", worstMaxShare);
            return finding;
        }
        return finding("ratio_gradient_ok", "structure", "pass", "system", "info",
                "同档录取率桶未发现明显集中或断层", "ratio_gradient_ok", entries);
    }

    private EvaluationFindingDTO diversity(List<EvaluationEntryRefDTO> entries) {
        int total = defaultList(entries).size();
        if (total < 5) {
            return finding("diversity_ok", "structure", "pass", "system", "info",
                    "样本较少，暂不做地域/办学性质集中判断", "diversity_ok", entries);
        }
        Map<String, Integer> provinces = new LinkedHashMap<String, Integer>();
        Map<String, Integer> natures = new LinkedHashMap<String, Integer>();
        for (EvaluationEntryRefDTO entry : entries) {
            if (!Strings.isNullOrEmpty(entry.getProvinceName())) {
                provinces.put(entry.getProvinceName(), provinces.getOrDefault(entry.getProvinceName(), 0) + 1);
            }
            if (!Strings.isNullOrEmpty(entry.getSchoolNature())) {
                natures.put(entry.getSchoolNature(), natures.getOrDefault(entry.getSchoolNature(), 0) + 1);
            }
        }
        String topProvince = null;
        int topProvinceCount = 0;
        for (Map.Entry<String, Integer> item : provinces.entrySet()) {
            if (item.getValue() > topProvinceCount) {
                topProvince = item.getKey();
                topProvinceCount = item.getValue();
            }
        }
        String topNature = null;
        int topNatureCount = 0;
        for (Map.Entry<String, Integer> item : natures.entrySet()) {
            if (item.getValue() > topNatureCount) {
                topNature = item.getKey();
                topNatureCount = item.getValue();
            }
        }
        int provinceShare = Math.round(topProvinceCount * 100.0F / total);
        int natureShare = natures.isEmpty() ? 0 : Math.round(topNatureCount * 100.0F / Math.max(1, total));
        boolean provinceConcentrated = topProvince != null && provinceShare > 40;
        boolean natureConcentrated = topNature != null && natureShare > 60;
        if (provinceConcentrated || natureConcentrated) {
            EvaluationFindingDTO finding = finding("diversity_concentration", "structure", "warn",
                    "system", "warn",
                    "方案分布偏集中："
                            + (provinceConcentrated ? "省份 " + topProvince + " " + topProvinceCount + "/" + total + "；" : "")
                            + (natureConcentrated ? "办学性质 " + topNature + " " + topNatureCount + "/" + total + "；" : "")
                            + "建议结合地域/学费偏好复核",
                    "diversity_concentration", entries);
            finding.getThreshold().put("topProvinceShare", provinceShare);
            finding.getThreshold().put("topNatureShare", natureShare);
            return finding;
        }
        return finding("diversity_ok", "structure", "pass", "system", "info",
                "地域/办学性质未发现明显集中", "diversity_ok", entries);
    }

    private EvaluationFindingDTO count(PlanningStateDTO state,
                                       EvaluationContextDTO context,
                                       List<EvaluationEntryRefDTO> entries) {
        Integer target = context.getSelectionTargetCount() != null
                ? context.getSelectionTargetCount() : context.getRequiredCount();
        if (target == null || target <= 0) {
            return finding("structure_count_unknown", "structure", "unknown", "system", "info",
                    "缺少已确认的数量目标，无法判断数量完整性", "count_target_missing", entries);
        }
        if (entries.size() < target) {
            EvaluationFindingDTO finding = finding("structure_count_shortfall", "structure", "warn",
                    "system", "warn", "方案数量少于目标", "count_shortfall", entries);
            finding.getThreshold().put("target", target);
            finding.getThreshold().put("actual", entries.size());
            finding.getThreshold().put("shortage", target - entries.size());
            return finding;
        }
        EvaluationFindingDTO finding = finding("structure_count_ok", "structure", "pass",
                "system", "info", "方案数量达到目标", "count_ok", entries);
        finding.getThreshold().put("target", target);
        finding.getThreshold().put("actual", entries.size());
        return finding;
    }

    private EvaluationFindingDTO dataCoverage(List<EvaluationEntryRefDTO> entries) {
        int known = 0;
        for (EvaluationEntryRefDTO entry : entries) {
            if (entry.getSchoolRatio() != null || entry.getMajorRatio() != null) {
                known++;
            }
        }
        if (known == 0) {
            return finding("structure_data_unknown", "evidence", "unknown", "evidence", "info",
                    "方案缺少录取率证据，不能做概率判断", "ratio_evidence_missing", entries);
        }
        if (known < entries.size()) {
            return finding("structure_data_partial", "evidence", "unknown", "evidence", "info",
                    "部分条目缺少录取率证据，相关判断保持未知", "ratio_evidence_partial", entries);
        }
        return finding("structure_data_complete", "evidence", "pass", "evidence", "info",
                "方案条目具备录取率证据", "ratio_evidence_complete", entries);
    }

    private EvaluationFindingDTO evidence(EvaluationContextDTO context, PlanningStateDTO state) {
        if (Strings.isNullOrEmpty(context.getDataVersion())) {
            return finding("evidence_version_unknown", "evidence", "unknown", "evidence", "info",
                    "缺少数据版本，不能声称已核验", "data_version_missing",
                    Lists.<EvaluationEntryRefDTO>newArrayList());
        }
        String examYear = state == null || state.getDataFreshnessState() == null
                ? null : state.getDataFreshnessState().getExamYear();
        if (Strings.isNullOrEmpty(examYear)) {
            return finding("evidence_year_unknown", "evidence", "unknown", "evidence", "info",
                    "缺少数据年份，无法判断是否适用于当前考试年度", "data_year_missing",
                    Lists.<EvaluationEntryRefDTO>newArrayList());
        }
        EvaluationFindingDTO finding = finding("evidence_version_present", "evidence", "pass",
                "evidence", "info", "数据版本与年份已记录", "data_version_present",
                Lists.<EvaluationEntryRefDTO>newArrayList());
        finding.getThreshold().put("dataVersion", context.getDataVersion());
        finding.getThreshold().put("examYear", examYear);
        return finding;
    }

    private List<EvaluationEntryRefDTO> hardConstraintViolations(PlanningStateDTO state,
                                                                 List<EvaluationEntryRefDTO> entries) {
        List<EvaluationEntryRefDTO> violations = Lists.newArrayList();
        if (state == null || !RepairCandidateEligibility.hasConfirmedHardConstraints(state)) {
            return violations;
        }
        boolean groupMode = state.getCandidatePoolState() != null
                && "majorGroup".equalsIgnoreCase(state.getCandidatePoolState().getVolunteerModel());
        if (groupMode && state.getOrderedPlanState() != null) {
            for (OrderedUnitDTO unit : defaultList(state.getOrderedPlanState().getUnits())) {
                if (unit == null) {
                    continue;
                }
                PlanningUnitDTO asUnit = new PlanningUnitDTO();
                asUnit.setSchoolName(unit.getSchoolName());
                asUnit.setProvinceName(unit.getProvinceName());
                asUnit.setSelectedMajors(defaultList(unit.getMajorItems()));
                if (!RepairCandidateEligibility.isEligibleForConfirmedHardConstraints(asUnit, state)) {
                    addEntryByUnit(entries, unit.getUnitId(), violations);
                }
            }
        } else if (state.getOrderedPlanState() != null) {
            for (OrderedItemDTO item : defaultList(state.getOrderedPlanState().getItems())) {
                CandidateItemDTO candidate = candidate(state, item.getVolunteerId());
                if (candidate == null) {
                    candidate = new CandidateItemDTO();
                    candidate.setVolunteerId(item.getVolunteerId());
                    candidate.setSchoolName(item.getSchoolName());
                    candidate.setMajorName(item.getMajorName());
                }
                if (!RepairCandidateEligibility.isEligibleForConfirmedHardConstraints(candidate, state)) {
                    addEntryByVolunteer(entries, item.getVolunteerId(), violations);
                }
            }
        }
        return violations;
    }

    private boolean hasRestrictionEvidence(List<EvaluationEntryRefDTO> entries) {
        return !restrictionEntries(entries).isEmpty();
    }

    private List<EvaluationEntryRefDTO> restrictionEntries(List<EvaluationEntryRefDTO> entries) {
        List<EvaluationEntryRefDTO> result = Lists.newArrayList();
        for (EvaluationEntryRefDTO entry : entries) {
            for (String tag : defaultList(entry.getRiskTags())) {
                if (tag != null && (tag.contains("色盲") || tag.contains("色弱")
                        || tag.contains("限报") || tag.contains("语种") || tag.contains("性别"))) {
                    result.add(entry);
                    break;
                }
            }
        }
        return result;
    }

    private EvaluationFindingDTO finding(String code, String layer, String resultStatus,
                                         String ruleStrength, String displaySeverity,
                                         String summary, String reasonCode,
                                         List<EvaluationEntryRefDTO> affected) {
        EvaluationFindingDTO finding = new EvaluationFindingDTO();
        finding.setCode(code);
        finding.setLayer(layer);
        finding.setResultStatus(resultStatus);
        finding.setRuleStrength(ruleStrength);
        finding.setDisplaySeverity(displaySeverity);
        finding.setFixability("none");
        finding.setSummary(summary);
        finding.setSource("quality_v2");
        finding.setReasonCode(reasonCode);
        finding.setAffectedEntryRefs(Lists.newArrayList(defaultList(affected)));
        return finding;
    }

    private String version(EvaluationContextDTO context, PlanEvaluationDTO evaluation) {
        return EvaluationVersion.sha256("qualityPolicy=" + QUALITY_POLICY_VERSION
                + "|state=" + context.getEvaluatedStateVersion()
                + "|plan=" + context.getPlanContentDigest()
                + "|candidateSource=" + context.getCandidateSourceVersion()
                + "|data=" + context.getDataVersion()
                + "|findings=" + evaluation.getFindings());
    }

    private StructureVectorDTO structure(List<EvaluationEntryRefDTO> entries) {
        StructureVectorDTO structure = new StructureVectorDTO();
        boolean group = !entries.isEmpty() && "unit".equals(entries.get(0).getLevel());
        structure.setUnitCount(group ? entries.size() : 0);
        structure.setItemCount(group ? 0 : entries.size());
        Map<String, Integer> counts = new LinkedHashMap<String, Integer>();
        for (EvaluationEntryRefDTO entry : entries) {
            String tier = normalizeTier(entry.getPathTier());
            counts.put(tier, counts.getOrDefault(tier, 0) + 1);
        }
        if (group) {
            structure.setUnitTierCounts(counts);
        } else {
            structure.setTierCounts(counts);
        }
        return structure;
    }

    private void addEntryByUnit(List<EvaluationEntryRefDTO> entries, String unitId,
                                List<EvaluationEntryRefDTO> target) {
        for (EvaluationEntryRefDTO entry : entries) {
            if (unitId != null && unitId.equals(entry.getId())) {
                target.add(entry);
                return;
            }
        }
    }

    private void addEntryByVolunteer(List<EvaluationEntryRefDTO> entries, String volunteerId,
                                     List<EvaluationEntryRefDTO> target) {
        for (EvaluationEntryRefDTO entry : entries) {
            if (volunteerId != null && volunteerId.equals(entry.getId())) {
                target.add(entry);
                return;
            }
        }
    }

    private CandidateItemDTO candidate(PlanningStateDTO state, String volunteerId) {
        if (state == null || state.getCandidatePoolState() == null
                || state.getCandidatePoolState().getItems() == null) {
            return null;
        }
        for (CandidateItemDTO candidate : state.getCandidatePoolState().getItems()) {
            if (candidate != null && Objects.equals(volunteerId, candidate.getVolunteerId())) {
                return candidate;
            }
        }
        return null;
    }

    private boolean matchesAny(String value, Set<String> preferences) {
        if (Strings.isNullOrEmpty(value)) {
            return false;
        }
        for (String preference : preferences) {
            if (!Strings.isNullOrEmpty(preference)
                    && value.contains(preference.trim())) {
                return true;
            }
        }
        return false;
    }

    private String normalizeTier(String tier) {
        if ("冲".equals(tier) || "稳".equals(tier) || "保".equals(tier)) {
            return tier;
        }
        return "unknown";
    }

    private int tierRank(String tier) {
        if ("冲".equals(tier)) {
            return 0;
        }
        if ("稳".equals(tier)) {
            return 1;
        }
        return 2;
    }

    private static <T> List<T> defaultList(List<T> value) {
        return value == null ? Lists.<T>newArrayList() : value;
    }
}
