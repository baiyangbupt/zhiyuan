package com.ytell.zhiyuan.service.biz;

import com.google.common.base.Strings;
import com.ytell.zhiyuan.model.dto.planning.AdmissionInterpretationReq;
import com.ytell.zhiyuan.model.dto.planning.AdmissionInterpretationRes;
import com.ytell.zhiyuan.model.dto.planning.EvaluationFindingDTO;
import com.ytell.zhiyuan.model.dto.planning.EvaluationProbeMetadataDTO;
import com.ytell.zhiyuan.model.dto.planning.InterpretationEntryDTO;
import com.ytell.zhiyuan.model.dto.planning.LandingScenarioDTO;

import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Comparator;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Iterator;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * 当前方案的**结构与条件情景**说明（纯函数，只读）。
 *
 * <p>这不是录取预测：只描述首个稳/保位置、冲档最高校线率位置、最后保底位置、
 * 保底覆盖和数据缺口。输出里没有 likelihood/slipRisk 之类的概率/风险结论。
 *
 * <p>口径：
 * <ul>
 *   <li>{@code pathTier} 以方案条目自己的 tier 为准，不拿 schoolRatio 反向覆盖；</li>
 *   <li>{@code schoolRatio} 只用于冲档结构排序/数据完整度，{@code majorRatio} 只做组内证据；</li>
 *   <li>按实际 position 顺序扫描；base=第一条稳/保，upside=冲里校线率最高，
 *       downside=最后一条保；</li>
 *   <li>“有保底档位”只说明结构覆盖，不说明录取风险；数据齐全也不等于风险低。</li>
 * </ul>
 */
public class PlanAdmissionInterpretationService {

    private static final int MAX_POSITION = Integer.MAX_VALUE;
    private static final double FULL_COVERAGE = 0.8;
    private static final double PARTIAL_COVERAGE = 0.5;

    public AdmissionInterpretationRes interpret(AdmissionInterpretationReq req,
                                                List<InterpretationEntryDTO> inputEntries) {
        return interpret(req, inputEntries, Collections.<EvaluationFindingDTO>emptyList());
    }

    /**
     * J5.2：解读同时消费统一评价 findings（drivers/caveats），不再另写规则链。
     * findings 为空时行为与旧版逐字一致；只取 fail/unknown，不把 pass 当提醒。
     */
    public AdmissionInterpretationRes interpret(AdmissionInterpretationReq req,
                                                List<InterpretationEntryDTO> inputEntries,
                                                List<EvaluationFindingDTO> findings) {
        if (req == null || req.getPlanVersion() == null) {
            throw new IllegalArgumentException("plan_version_required");
        }
        List<String> caveats = new ArrayList<String>();
        List<InterpretationEntryDTO> entries = copy(inputEntries);
        applyCounterfactual(req, entries, caveats);
        sortByPosition(entries);

        AdmissionInterpretationRes res = new AdmissionInterpretationRes();
        res.setPlanVersion(req.getPlanVersion());
        res.setGeneratedAt(OffsetDateTime.now().toString());
        res.setAdmissionMode(resolveMode(req.getAdmissionMode(), entries));
        res.setCaveats(caveats);
        caveats.add("这是方案结构与条件情景说明，不是录取预测；数据不足不等于风险高或低。");

        if (entries.isEmpty()) {
            res.setStatus(AdmissionInterpretationRes.STATUS_NO_PLAN);
            res.setSafetyCoverage(AdmissionInterpretationRes.SAFETY_UNKNOWN);
            res.setTierCoverage(0.0);
            res.setRatioCoverage(0.0);
            res.setDataCompleteness(0.0);
            res.setDataCompletenessBand(AdmissionInterpretationRes.COMPLETENESS_SEVERE);
            res.setOrderAnomaly(false);
            caveats.add("当前没有可解读的方案条目，请先排出方案。");
            enrichWithFindings(res, findings);
            return res;
        }

        res.setStatus(AdmissionInterpretationRes.STATUS_COMPLETED);

        int total = entries.size();
        int tierKnown = 0;
        int ratioKnown = 0;
        int safeCount = 0;
        int safeKnownRatio = 0;
        for (InterpretationEntryDTO entry : entries) {
            String tier = normalizeTier(entry.getPathTier());
            if (!InterpretationEntryDTO.TIER_UNKNOWN.equals(tier)) {
                tierKnown++;
            }
            if (entry.getSchoolRatio() != null) {
                ratioKnown++;
            }
            if (InterpretationEntryDTO.TIER_BAO.equals(tier)) {
                safeCount++;
                if (entry.getSchoolRatio() != null) {
                    safeKnownRatio++;
                }
            }
        }
        double tierCoverage = (double) tierKnown / total;
        double ratioCoverage = (double) ratioKnown / total;
        double dataCompleteness = Math.min(tierCoverage, ratioCoverage);
        res.setTierCoverage(tierCoverage);
        res.setRatioCoverage(ratioCoverage);
        res.setDataCompleteness(dataCompleteness);
        res.setDataCompletenessBand(completenessBand(dataCompleteness));

        String safetyCoverage = evaluateSafetyCoverage(tierKnown, safeCount, safeKnownRatio);
        res.setSafetyCoverage(safetyCoverage);
        addCoverageCaveats(caveats, ratioCoverage, safetyCoverage);

        InterpretationEntryDTO baseEntry = firstStableOrSafe(entries);
        InterpretationEntryDTO upsideEntry = bestReach(entries);
        InterpretationEntryDTO downsideEntry = lastSafe(entries);
        boolean orderAnomaly = hasOrderAnomaly(entries);
        res.setOrderAnomaly(orderAnomaly);

        if (baseEntry != null) {
            LandingScenarioDTO base = buildScenario(
                    LandingScenarioDTO.LABEL_BASE,
                    LandingScenarioDTO.STRUCTURE_FIRST_STABLE,
                    LandingScenarioDTO.CONDITION_PRIOR_MISSED,
                    baseEntry,
                    pathUpTo(entries, baseEntry),
                    orderAnomaly);
            res.getScenarios().add(base);
            res.setBaseLanding(base);
        }
        if (upsideEntry != null) {
            LandingScenarioDTO upside = buildScenario(
                    LandingScenarioDTO.LABEL_UPSIDE,
                    LandingScenarioDTO.STRUCTURE_BEST_REACH,
                    LandingScenarioDTO.CONDITION_REACH_HIT,
                    upsideEntry,
                    pathUpTo(entries, upsideEntry),
                    orderAnomaly);
            res.getScenarios().add(upside);
        }
        if (downsideEntry != null) {
            LandingScenarioDTO downside = buildScenario(
                    LandingScenarioDTO.LABEL_DOWNSIDE,
                    LandingScenarioDTO.STRUCTURE_LAST_SAFE,
                    LandingScenarioDTO.CONDITION_PRIOR_MISSED,
                    downsideEntry,
                    pathUpTo(entries, downsideEntry),
                    orderAnomaly);
            res.getScenarios().add(downside);
        }
        if (AdmissionInterpretationRes.SAFETY_NO_COVER.equals(safetyCoverage)
                || AdmissionInterpretationRes.SAFETY_UNKNOWN.equals(safetyCoverage)) {
            LandingScenarioDTO noSafe = new LandingScenarioDTO();
            noSafe.setScenarioId(LandingScenarioDTO.LABEL_NO_SAFE);
            noSafe.setLabel(LandingScenarioDTO.LABEL_NO_SAFE);
            noSafe.setStructureStatus(AdmissionInterpretationRes.SAFETY_UNKNOWN.equals(safetyCoverage)
                    ? LandingScenarioDTO.STRUCTURE_UNKNOWN
                    : LandingScenarioDTO.STRUCTURE_NO_SAFE);
            noSafe.setCondition(LandingScenarioDTO.CONDITION_NONE);
            noSafe.setPath(copy(entries));
            noSafe.getDrivers().add("保底档位数=" + safeCount);
            noSafe.getCaveats().add("只说明没有可识别的保底档位，不推演录取概率。");
            res.getScenarios().add(noSafe);
        }
        enrichWithFindings(res, findings);
        return res;
    }

    /**
     * 把统一评价的 fail/unknown findings 挂到解读上：
     * - 命中某情景 landing 条目的 finding → 该情景 drivers；
     * - hard/policy 的未通过 finding → 全局 caveats（去重、最多 4 条）。
     * 只转述 label/summary，不带 metric 数字或概率。
     */
    private void enrichWithFindings(AdmissionInterpretationRes res,
                                    List<EvaluationFindingDTO> findings) {
        if (res == null || findings == null || findings.isEmpty()) {
            return;
        }
        Map<String, List<EvaluationFindingDTO>> byRef =
                new HashMap<String, List<EvaluationFindingDTO>>();
        Set<String> caveatSeen = new HashSet<String>(res.getCaveats());
        int caveatAdded = 0;
        for (EvaluationFindingDTO finding : findings) {
            if (finding == null || isPass(finding)) {
                continue;
            }
            for (com.ytell.zhiyuan.model.dto.planning.EvaluationEntryRefDTO ref
                    : safeList(finding.getAffectedEntryRefs())) {
                if (ref == null || Strings.isNullOrEmpty(ref.getId())) {
                    continue;
                }
                String key = String.valueOf(ref.getLevel()) + ":" + ref.getId();
                List<EvaluationFindingDTO> bucket = byRef.get(key);
                if (bucket == null) {
                    bucket = new ArrayList<EvaluationFindingDTO>();
                    byRef.put(key, bucket);
                }
                bucket.add(finding);
            }
            if ("hard".equals(finding.getRuleStrength()) || "policy".equals(finding.getRuleStrength())) {
                String line = findingLine(finding);
                if (!Strings.isNullOrEmpty(line) && caveatSeen.add(line) && caveatAdded < 4) {
                    res.getCaveats().add(line);
                    caveatAdded++;
                }
            }
        }
        for (LandingScenarioDTO scenario : safeList(res.getScenarios())) {
            InterpretationEntryDTO landing = scenario.getLandingEntry();
            if (landing == null || Strings.isNullOrEmpty(landing.getId())) {
                continue;
            }
            List<EvaluationFindingDTO> matched =
                    byRef.get(String.valueOf(landing.getLevel()) + ":" + landing.getId());
            if (matched == null) {
                continue;
            }
            Set<String> seen = new HashSet<String>(scenario.getDrivers());
            for (EvaluationFindingDTO finding : matched) {
                String line = findingLine(finding);
                if (!Strings.isNullOrEmpty(line) && seen.add(line) && scenario.getDrivers().size() < 3) {
                    scenario.getDrivers().add(line);
                }
            }
        }
    }

    private boolean isPass(EvaluationFindingDTO finding) {
        String status = finding.getResultStatus();
        return "pass".equals(status) || "not_applicable".equals(status);
    }

    private String findingLine(EvaluationFindingDTO finding) {
        EvaluationProbeMetadataDTO metadata = EvaluationProbeRegistry.get(finding.getCode());
        String label = metadata == null ? finding.getCode() : metadata.getLabel();
        String summary = Strings.isNullOrEmpty(finding.getSummary()) ? "" : finding.getSummary();
        String line = "审查：" + label + (summary.isEmpty() ? "" : "（" + summary + "）");
        return line.length() > 120 ? line.substring(0, 120) : line;
    }

    private static <T> List<T> safeList(List<T> value) {
        return value == null ? Collections.<T>emptyList() : value;
    }

    private List<InterpretationEntryDTO> copy(List<InterpretationEntryDTO> input) {
        List<InterpretationEntryDTO> result = new ArrayList<InterpretationEntryDTO>();
        if (input != null) {
            for (InterpretationEntryDTO entry : input) {
                if (entry != null) {
                    result.add(entry);
                }
            }
        }
        return result;
    }

    private void applyCounterfactual(AdmissionInterpretationReq req,
                                     List<InterpretationEntryDTO> entries,
                                     List<String> caveats) {
        if (req.getCounterfactual() == null
                || req.getCounterfactual().getRemoveEntryRefs() == null
                || req.getCounterfactual().getRemoveEntryRefs().isEmpty()) {
            return;
        }
        int removed = 0;
        for (AdmissionInterpretationReq.EntryRefDTO ref : req.getCounterfactual().getRemoveEntryRefs()) {
            if (ref == null || ref.getId() == null) {
                continue;
            }
            Iterator<InterpretationEntryDTO> iterator = entries.iterator();
            while (iterator.hasNext()) {
                InterpretationEntryDTO entry = iterator.next();
                if (ref.getId().equals(entry.getId())
                        && (ref.getLevel() == null || ref.getLevel().equals(entry.getLevel()))) {
                    iterator.remove();
                    removed++;
                    break;
                }
            }
        }
        if (removed == 0) {
            caveats.add("反事实删除的条目未找到，已按原方案推演。");
        }
    }

    private void sortByPosition(List<InterpretationEntryDTO> entries) {
        Collections.sort(entries, new Comparator<InterpretationEntryDTO>() {
            @Override
            public int compare(InterpretationEntryDTO left, InterpretationEntryDTO right) {
                return Integer.compare(positionOf(left), positionOf(right));
            }
        });
    }

    private int positionOf(InterpretationEntryDTO entry) {
        return entry.getPosition() == null ? MAX_POSITION : entry.getPosition();
    }

    private String normalizeTier(String tier) {
        if (InterpretationEntryDTO.TIER_CHONG.equals(tier)
                || InterpretationEntryDTO.TIER_WEN.equals(tier)
                || InterpretationEntryDTO.TIER_BAO.equals(tier)) {
            return tier;
        }
        return InterpretationEntryDTO.TIER_UNKNOWN;
    }

    private InterpretationEntryDTO firstStableOrSafe(List<InterpretationEntryDTO> entries) {
        for (InterpretationEntryDTO entry : entries) {
            String tier = normalizeTier(entry.getPathTier());
            if (InterpretationEntryDTO.TIER_WEN.equals(tier)
                    || InterpretationEntryDTO.TIER_BAO.equals(tier)) {
                return entry;
            }
        }
        return null;
    }

    private InterpretationEntryDTO bestReach(List<InterpretationEntryDTO> entries) {
        InterpretationEntryDTO best = null;
        Double bestRatio = null;
        for (InterpretationEntryDTO entry : entries) {
            if (!InterpretationEntryDTO.TIER_CHONG.equals(normalizeTier(entry.getPathTier()))) {
                continue;
            }
            if (best == null) {
                best = entry;
                bestRatio = entry.getSchoolRatio();
                continue;
            }
            Double ratio = entry.getSchoolRatio();
            if (ratio != null && (bestRatio == null || ratio > bestRatio)) {
                best = entry;
                bestRatio = ratio;
            }
        }
        return best;
    }

    private InterpretationEntryDTO lastSafe(List<InterpretationEntryDTO> entries) {
        InterpretationEntryDTO last = null;
        for (InterpretationEntryDTO entry : entries) {
            if (InterpretationEntryDTO.TIER_BAO.equals(normalizeTier(entry.getPathTier()))) {
                last = entry;
            }
        }
        return last;
    }

    private boolean hasOrderAnomaly(List<InterpretationEntryDTO> entries) {
        int firstSafe = -1;
        int firstNonSafe = -1;
        for (int i = 0; i < entries.size(); i++) {
            String tier = normalizeTier(entries.get(i).getPathTier());
            if (InterpretationEntryDTO.TIER_BAO.equals(tier) && firstSafe < 0) {
                firstSafe = i;
            }
            if ((InterpretationEntryDTO.TIER_WEN.equals(tier)
                    || InterpretationEntryDTO.TIER_CHONG.equals(tier)) && firstNonSafe < 0) {
                firstNonSafe = i;
            }
        }
        return firstSafe >= 0 && firstNonSafe >= 0 && firstSafe < firstNonSafe;
    }

    private String evaluateSafetyCoverage(int tierKnown, int safeCount, int safeKnownRatio) {
        if (tierKnown == 0) {
            return AdmissionInterpretationRes.SAFETY_UNKNOWN;
        }
        if (safeCount == 0) {
            return AdmissionInterpretationRes.SAFETY_NO_COVER;
        }
        if (safeKnownRatio == 0) {
            return AdmissionInterpretationRes.SAFETY_HAS_COVER_DATA_GAP;
        }
        return AdmissionInterpretationRes.SAFETY_HAS_COVER;
    }

    private String completenessBand(double coverage) {
        if (coverage >= FULL_COVERAGE) {
            return AdmissionInterpretationRes.COMPLETENESS_FULL;
        }
        if (coverage >= PARTIAL_COVERAGE) {
            return AdmissionInterpretationRes.COMPLETENESS_PARTIAL;
        }
        return AdmissionInterpretationRes.COMPLETENESS_SEVERE;
    }

    private void addCoverageCaveats(List<String> caveats,
                                    double ratioCoverage,
                                    String safetyCoverage) {
        if (ratioCoverage < 1.0) {
            caveats.add("部分条目缺少校线录取率，相关情景只能说明档位结构，不能说明录取把握。");
        }
        if (AdmissionInterpretationRes.SAFETY_NO_COVER.equals(safetyCoverage)) {
            caveats.add("方案没有可识别的保底档位，这是结构覆盖问题，不是概率结论。");
        } else if (AdmissionInterpretationRes.SAFETY_HAS_COVER_DATA_GAP.equals(safetyCoverage)) {
            caveats.add("方案有保底档位，但缺少校线录取率，无法确认其有效性。");
        } else if (AdmissionInterpretationRes.SAFETY_UNKNOWN.equals(safetyCoverage)) {
            caveats.add("档位数据不足，无法判断保底覆盖。");
        }
    }

    private LandingScenarioDTO buildScenario(String label,
                                             String structureStatus,
                                             String condition,
                                             InterpretationEntryDTO landing,
                                             List<InterpretationEntryDTO> path,
                                             boolean orderAnomaly) {
        LandingScenarioDTO scenario = new LandingScenarioDTO();
        scenario.setScenarioId(label);
        scenario.setLabel(label);
        scenario.setStructureStatus(structureStatus);
        scenario.setCondition(condition);
        scenario.setLandingEntry(landing);
        scenario.setPath(path);
        scenario.getDrivers().add("档位=" + normalizeTier(landing.getPathTier()));
        if (landing.getSchoolRatio() != null) {
            scenario.getDrivers().add("校线录取率=" + formatRatio(landing.getSchoolRatio()));
        }
        if (landing.getMajorRatio() != null) {
            scenario.getDrivers().add("专业录取率=" + formatRatio(landing.getMajorRatio()));
        }
        if (orderAnomaly) {
            scenario.getCaveats().add("方案顺序异常，按实际顺序展示。");
        }
        return scenario;
    }

    private List<InterpretationEntryDTO> pathUpTo(List<InterpretationEntryDTO> entries,
                                                  InterpretationEntryDTO landing) {
        List<InterpretationEntryDTO> path = new ArrayList<InterpretationEntryDTO>();
        for (InterpretationEntryDTO entry : entries) {
            path.add(entry);
            if (entry == landing) {
                break;
            }
        }
        return path;
    }

    private String resolveMode(String requestedMode, List<InterpretationEntryDTO> entries) {
        if (requestedMode != null && requestedMode.trim().length() > 0) {
            return requestedMode;
        }
        boolean hasUnit = false;
        boolean hasVolunteer = false;
        for (InterpretationEntryDTO entry : entries) {
            if (InterpretationEntryDTO.LEVEL_UNIT.equals(entry.getLevel())) {
                hasUnit = true;
            }
            if (InterpretationEntryDTO.LEVEL_VOLUNTEER.equals(entry.getLevel())) {
                hasVolunteer = true;
            }
        }
        if (hasUnit && !hasVolunteer) {
            return "major_group";
        }
        if (hasVolunteer && !hasUnit) {
            return "major";
        }
        return "unknown";
    }

    private String formatRatio(Double ratio) {
        if (ratio == null) {
            return "unknown";
        }
        if (ratio == Math.rint(ratio)) {
            return String.valueOf(ratio.intValue());
        }
        return String.valueOf(ratio);
    }
}
