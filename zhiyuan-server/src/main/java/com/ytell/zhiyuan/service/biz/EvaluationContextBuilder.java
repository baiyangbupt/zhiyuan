package com.ytell.zhiyuan.service.biz;

import com.alibaba.fastjson.JSON;
import com.google.common.base.Strings;
import com.google.common.collect.Lists;
import com.google.common.collect.Maps;
import com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO;
import com.ytell.zhiyuan.model.dto.planning.CoverageRequirementDTO;
import com.ytell.zhiyuan.model.dto.planning.EvaluationContextDTO;
import com.ytell.zhiyuan.model.dto.planning.EvaluationEntryRefDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedItemDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedUnitDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningUnitMajorDTO;
import com.ytell.zhiyuan.model.dto.planning.ReviewStateDTO;

import java.util.List;
import java.util.Map;

/** 把当前方案状态投影成不可变评价输入（J5.2）。不做规则判断，只搬输入。 */
public class EvaluationContextBuilder {

    public EvaluationContextDTO build(PlanningStateDTO state,
                                     List<CandidateItemDTO> candidates,
                                     ReviewStateDTO reviewState) {
        EvaluationContextDTO context = new EvaluationContextDTO();
        if (state == null) {
            return context;
        }
        List<CandidateItemDTO> effective = candidates == null || candidates.isEmpty()
                ? (state.getCandidatePoolState() == null
                ? Lists.newArrayList() : defaultList(state.getCandidatePoolState().getItems()))
                : candidates;
        Map<String, CandidateItemDTO> byVolunteer = Maps.newHashMap();
        for (CandidateItemDTO candidate : defaultList(effective)) {
            if (candidate != null && !Strings.isNullOrEmpty(candidate.getVolunteerId())) {
                byVolunteer.put(candidate.getVolunteerId(), candidate);
            }
        }
        boolean groupMode = state.getCandidatePoolState() != null
                && "majorGroup".equalsIgnoreCase(state.getCandidatePoolState().getVolunteerModel());
        List<CoverageRequirementDTO> coverage =
                CoverageRequirementSupport.confirmedRequirements(state);
        context.setCoverageRequirements(Lists.newArrayList(coverage));
        context.setEntries(groupMode
                ? unitEntries(state, byVolunteer, coverage)
                : itemEntries(state, byVolunteer, coverage));
        context.setAdmissionMode(groupMode ? "major_group" : "major");
        if (state.getCandidatePoolState() != null) {
            context.setRequiredCount(state.getCandidatePoolState().getRequiredCount());
            context.setRequiredTierCounts(state.getCandidatePoolState().getRequiredTierCounts());
            context.setSourceProvince(state.getCandidatePoolState().getSourceProvinceName());
            context.setUserScore(state.getCandidatePoolState().getUserScore());
            context.setCandidateSourceVersion(state.getCandidatePoolState().getSourceVersion());
        }
        context.setSelectionTargetCount(selectionTargetCount(state));
        context.setEvaluatedStateVersion(reviewState != null && reviewState.getSourceVersion() != null
                ? reviewState.getSourceVersion() : state.getVersion());
        context.setPlanContentDigest(EvaluationVersion.sha256(
                JSON.toJSONString(state.getOrderedPlanState())));
        context.setDataVersion(state.getDataFreshnessState() == null
                ? null : state.getDataFreshnessState().getDataVersion());
        return context;
    }

    private List<EvaluationEntryRefDTO> unitEntries(PlanningStateDTO state,
                                                    Map<String, CandidateItemDTO> byVolunteer,
                                                    List<CoverageRequirementDTO> coverage) {
        List<EvaluationEntryRefDTO> entries = Lists.newArrayList();
        List<OrderedUnitDTO> units = state.getOrderedPlanState() == null
                ? Lists.newArrayList() : defaultList(state.getOrderedPlanState().getUnits());
        for (OrderedUnitDTO unit : units) {
            if (unit == null) {
                continue;
            }
            EvaluationEntryRefDTO entry = new EvaluationEntryRefDTO();
            entry.setLevel("unit");
            entry.setId(unit.getUnitId());
            entry.setPosition(unit.getPosition());
            entry.setSchoolName(unit.getSchoolName());
            entry.setProvinceName(unit.getProvinceName());
            entry.setPathTier(unit.getTier());
            entry.setSchoolRatio(unit.getSchoolEnrollRatio());
            entry.setMajorRatio(unit.getAdmissionRatio());
            Integer tuition = null;
            List<String> flags = Lists.newArrayList();
            List<CandidateItemDTO> unitCandidates = Lists.newArrayList();
            for (PlanningUnitMajorDTO major : defaultList(unit.getMajorItems())) {
                CandidateItemDTO candidate = byVolunteer.get(major.getVolunteerId());
                if (candidate == null) {
                    continue;
                }
                unitCandidates.add(candidate);
                if (candidate.getTuitionPerYear() != null) {
                    tuition = tuition == null ? candidate.getTuitionPerYear()
                            : Math.max(tuition, candidate.getTuitionPerYear());
                }
                for (String flag : defaultList(candidate.getRiskFlags())) {
                    if (!flags.contains(flag)) {
                        flags.add(flag);
                    }
                }
            }
            entry.setTuitionPerYear(tuition);
            entry.setRiskFlags(flags);
            entry.setMatchedCoverageIds(matchedCoverageIds(unitCandidates, coverage));
            entries.add(entry);
        }
        return entries;
    }

    private List<EvaluationEntryRefDTO> itemEntries(PlanningStateDTO state,
                                                    Map<String, CandidateItemDTO> byVolunteer,
                                                    List<CoverageRequirementDTO> coverage) {
        List<EvaluationEntryRefDTO> entries = Lists.newArrayList();
        List<OrderedItemDTO> items = state.getOrderedPlanState() == null
                ? Lists.newArrayList() : defaultList(state.getOrderedPlanState().getItems());
        for (OrderedItemDTO item : items) {
            if (item == null) {
                continue;
            }
            CandidateItemDTO candidate = byVolunteer.get(item.getVolunteerId());
            EvaluationEntryRefDTO entry = new EvaluationEntryRefDTO();
            entry.setLevel("volunteer");
            entry.setId(item.getVolunteerId());
            entry.setPosition(item.getPosition());
            entry.setSchoolName(item.getSchoolName());
            entry.setMajorName(item.getMajorName());
            entry.setPathTier(item.getTier());
            if (candidate != null) {
                entry.setProvinceName(candidate.getProvinceName());
                entry.setSchoolRatio(candidate.getSchoolEnrollRatio());
                entry.setMajorRatio(candidate.getAdmissionRatio());
                entry.setTuitionPerYear(candidate.getTuitionPerYear());
                entry.setRiskFlags(Lists.newArrayList(defaultList(candidate.getRiskFlags())));
                entry.setMatchedCoverageIds(matchedCoverageIds(
                        Lists.newArrayList(candidate), coverage));
            }
            entries.add(entry);
        }
        return entries;
    }

    private List<String> matchedCoverageIds(List<CandidateItemDTO> candidates,
                                            List<CoverageRequirementDTO> coverage) {
        List<String> result = Lists.newArrayList();
        for (int index = 0; index < defaultList(coverage).size(); index++) {
            CoverageRequirementDTO requirement = coverage.get(index);
            for (CandidateItemDTO candidate : defaultList(candidates)) {
                if (candidate != null && CoverageRequirementSupport.matches(candidate, requirement)) {
                    result.add("coverage:" + index);
                    break;
                }
            }
        }
        return result;
    }

    private Integer selectionTargetCount(PlanningStateDTO state) {
        if (state.getConstraintState() == null
                || state.getConstraintState().getHardPlanningObjectives() == null) {
            return null;
        }
        Integer target = state.getConstraintState().getHardPlanningObjectives()
                .getSelectionTargetCount();
        return target != null && target > 0 ? target : null;
    }

    private static <T> List<T> defaultList(List<T> value) {
        return value == null ? Lists.newArrayList() : value;
    }
}
