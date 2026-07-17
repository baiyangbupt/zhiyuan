package com.ytell.zhiyuan.service.biz;

import com.google.common.base.Strings;
import com.google.common.collect.Lists;
import com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO;
import com.ytell.zhiyuan.model.dto.planning.ConstraintStateDTO;
import com.ytell.zhiyuan.model.dto.planning.HardConstraintsDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import com.ytell.zhiyuan.model.dto.planning.UserGoalFixProposalReq;

import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Set;

final class ProjectedHardRequirementSupport {

    static final String KIND_EXCLUDE = "exclude";
    static final String KIND_ONLY_KEEP = "only_keep";
    static final String KIND_INCLUDE = "include";

    private ProjectedHardRequirementSupport() {
    }

    static String validate(List<UserGoalFixProposalReq.RequirementDTO> requirements) {
        Set<String> onlyKeepTargets = new LinkedHashSet<String>();
        for (UserGoalFixProposalReq.RequirementDTO requirement : defaultList(requirements)) {
            if (requirement == null) {
                return "复合硬要求不能为空。";
            }
            String kind = normalized(requirement.getKind());
            if (KIND_INCLUDE.equals(kind)) {
                String coverageError = CoverageRequirementSupport.validate(requirement);
                if (coverageError != null) {
                    return coverageError;
                }
                continue;
            }
            if (!KIND_EXCLUDE.equals(kind) && !KIND_ONLY_KEEP.equals(kind)) {
                return "当前只支持 exclude 和 only_keep 复合硬要求。";
            }
            if (targetListName(requirement) == null) {
                return "暂不支持复合要求字段：" + requirement.getDomain() + "." + requirement.getKey();
            }
            if (normalizedValues(requirement).isEmpty()) {
                return "复合硬要求必须包含明确值。";
            }
            if (KIND_ONLY_KEEP.equals(kind)) {
                String target = targetListName(requirement);
                if (!onlyKeepTargets.add(target)) {
                    return "同一领域的 only_keep 必须合并成一条要求并统一给出 values。";
                }
            }
        }
        return null;
    }

    static HardConstraintsDTO project(PlanningStateDTO state,
                                      List<UserGoalFixProposalReq.RequirementDTO> requirements) {
        HardConstraintsDTO projected = copy(state == null || state.getConstraintState() == null
                ? null : state.getConstraintState().getHardConstraints());
        merge(projected, requirements);
        return projected;
    }

    static void persist(PlanningStateDTO state,
                        List<UserGoalFixProposalReq.RequirementDTO> requirements) {
        if (state == null || defaultList(requirements).isEmpty()) {
            return;
        }
        if (state.getConstraintState() == null) {
            state.setConstraintState(new ConstraintStateDTO());
        }
        if (state.getConstraintState().getHardConstraints() == null) {
            state.getConstraintState().setHardConstraints(new HardConstraintsDTO());
        }
        merge(state.getConstraintState().getHardConstraints(), requirements);
        CoverageRequirementSupport.persist(state, requirements);
    }

    static boolean isAllowed(CandidateItemDTO candidate, HardConstraintsDTO projected) {
        return RepairCandidateEligibility.isEligibleForHardConstraints(candidate, projected);
    }

    static boolean matches(CandidateItemDTO candidate, UserGoalFixProposalReq.RequirementDTO requirement) {
        if (candidate == null || requirement == null) {
            return false;
        }
        if (KIND_INCLUDE.equals(normalized(requirement.getKind()))) {
            return CoverageRequirementSupport.matches(candidate, requirement);
        }
        HardConstraintsDTO isolated = new HardConstraintsDTO();
        merge(isolated, Lists.newArrayList(requirement));
        boolean eligible = RepairCandidateEligibility.isEligibleForHardConstraints(candidate, isolated);
        return KIND_ONLY_KEEP.equals(normalized(requirement.getKind())) ? eligible : !eligible;
    }

    static boolean isPersisted(PlanningStateDTO state, UserGoalFixProposalReq.RequirementDTO requirement) {
        if (KIND_INCLUDE.equals(normalized(requirement == null ? null : requirement.getKind()))) {
            return CoverageRequirementSupport.isPersisted(state, requirement);
        }
        HardConstraintsDTO hard = state == null || state.getConstraintState() == null
                ? null : state.getConstraintState().getHardConstraints();
        List<String> target = targetList(hard, requirement);
        if (target == null) {
            return false;
        }
        List<String> expected = encodedValues(requirement);
        if (KIND_ONLY_KEEP.equals(normalized(requirement.getKind()))) {
            return new LinkedHashSet<String>(target).equals(new LinkedHashSet<String>(expected));
        }
        return target.containsAll(expected);
    }

    static String summarize(List<UserGoalFixProposalReq.RequirementDTO> requirements) {
        List<String> summaries = Lists.newArrayList();
        for (UserGoalFixProposalReq.RequirementDTO requirement : defaultList(requirements)) {
            if (requirement == null) {
                continue;
            }
            List<String> values = normalizedValues(requirement);
            String label = displayLabel(requirement.getKey());
            String kind = normalized(requirement.getKind());
            if (values.isEmpty() || label == null
                    || (!KIND_EXCLUDE.equals(kind) && !KIND_ONLY_KEEP.equals(kind) && !KIND_INCLUDE.equals(kind))) {
                continue;
            }
            String action = KIND_EXCLUDE.equals(kind) ? "排除"
                    : KIND_ONLY_KEEP.equals(kind) ? "只保留"
                    : CoverageRequirementSupport.minCount(requirement) > 1
                    ? "至少包含" + CoverageRequirementSupport.minCount(requirement) + "个"
                    : "至少包含";
            summaries.add(action + String.join("、", values) + "（" + label + "）");
        }
        return String.join("；", summaries);
    }

    private static void merge(HardConstraintsDTO hard,
                              List<UserGoalFixProposalReq.RequirementDTO> requirements) {
        if (hard == null) {
            return;
        }
        normalizeLists(hard);
        Set<String> resetTargets = new LinkedHashSet<String>();
        for (UserGoalFixProposalReq.RequirementDTO requirement : defaultList(requirements)) {
            if (!KIND_ONLY_KEEP.equals(normalized(requirement == null ? null : requirement.getKind()))) {
                continue;
            }
            String targetName = targetListName(requirement);
            if (targetName == null || !resetTargets.add(targetName)) {
                continue;
            }
            List<String> target = targetList(hard, requirement);
            if (target != null) {
                target.clear();
            }
        }
        for (UserGoalFixProposalReq.RequirementDTO requirement : defaultList(requirements)) {
            List<String> target = targetList(hard, requirement);
            if (target == null) {
                continue;
            }
            for (String value : encodedValues(requirement)) {
                if (!target.contains(value)) {
                    target.add(value);
                }
            }
        }
    }

    private static HardConstraintsDTO copy(HardConstraintsDTO source) {
        HardConstraintsDTO result = new HardConstraintsDTO();
        if (source == null) {
            return result;
        }
        result.setMustIncludeRegions(Lists.newArrayList(defaultList(source.getMustIncludeRegions())));
        result.setMustExcludeRegions(Lists.newArrayList(defaultList(source.getMustExcludeRegions())));
        result.setMustIncludeMajors(Lists.newArrayList(defaultList(source.getMustIncludeMajors())));
        result.setMustExcludeMajors(Lists.newArrayList(defaultList(source.getMustExcludeMajors())));
        result.setMustIncludeSchools(Lists.newArrayList(defaultList(source.getMustIncludeSchools())));
        result.setMustExcludeSchools(Lists.newArrayList(defaultList(source.getMustExcludeSchools())));
        return result;
    }

    private static void normalizeLists(HardConstraintsDTO hard) {
        hard.setMustIncludeRegions(nonNull(hard.getMustIncludeRegions()));
        hard.setMustExcludeRegions(nonNull(hard.getMustExcludeRegions()));
        hard.setMustIncludeMajors(nonNull(hard.getMustIncludeMajors()));
        hard.setMustExcludeMajors(nonNull(hard.getMustExcludeMajors()));
        hard.setMustIncludeSchools(nonNull(hard.getMustIncludeSchools()));
        hard.setMustExcludeSchools(nonNull(hard.getMustExcludeSchools()));
    }

    private static List<String> targetList(HardConstraintsDTO hard,
                                           UserGoalFixProposalReq.RequirementDTO requirement) {
        if (hard == null || requirement == null) {
            return null;
        }
        String target = targetListName(requirement);
        if ("include_region".equals(target)) {
            return hard.getMustIncludeRegions();
        }
        if ("exclude_region".equals(target)) {
            return hard.getMustExcludeRegions();
        }
        if ("include_major".equals(target)) {
            return hard.getMustIncludeMajors();
        }
        if ("exclude_major".equals(target)) {
            return hard.getMustExcludeMajors();
        }
        if ("include_school".equals(target)) {
            return hard.getMustIncludeSchools();
        }
        if ("exclude_school".equals(target)) {
            return hard.getMustExcludeSchools();
        }
        return null;
    }

    private static String targetListName(UserGoalFixProposalReq.RequirementDTO requirement) {
        if (requirement == null) {
            return null;
        }
        String kind = normalized(requirement.getKind());
        boolean include = KIND_ONLY_KEEP.equals(kind);
        boolean exclude = KIND_EXCLUDE.equals(kind);
        if (!include && !exclude) {
            return null;
        }
        String domain = normalized(requirement.getDomain());
        String key = normalized(requirement.getKey());
        if ("region".equals(domain) && in(key, "province", "city", "area", "region_group")) {
            return (include ? "include_" : "exclude_") + "region";
        }
        if ("major".equals(domain) && in(key, "major", "level1", "level2", "level3", "major_tag")) {
            return (include ? "include_" : "exclude_") + "major";
        }
        if ("school".equals(domain) && in(key, "school", "schools", "school_nature", "program_type",
                "school_category", "school_level", "school_tag")) {
            return (include ? "include_" : "exclude_") + "school";
        }
        return null;
    }

    private static List<String> encodedValues(UserGoalFixProposalReq.RequirementDTO requirement) {
        List<String> result = Lists.newArrayList();
        String key = normalized(requirement == null ? null : requirement.getKey());
        for (String value : normalizedValues(requirement)) {
            if ("school_nature".equals(key)) {
                result.add("院校性质:" + value);
            } else if ("program_type".equals(key)) {
                result.add("招生类型:" + value);
            } else if ("school_category".equals(key)) {
                result.add("院校类型:" + value);
            } else if ("school_level".equals(key)) {
                result.add("院校层次:" + value);
            } else if ("school_tag".equals(key)) {
                result.add("院校标签:" + value);
            } else if ("level1".equals(key)) {
                result.add("专业门类:" + value);
            } else if ("level2".equals(key) || "level3".equals(key)) {
                result.add("专业类:" + value);
            } else if ("major_tag".equals(key)) {
                result.add("专业标签:" + value);
            } else {
                result.add(value);
            }
        }
        return result;
    }

    private static List<String> normalizedValues(UserGoalFixProposalReq.RequirementDTO requirement) {
        Set<String> result = new LinkedHashSet<String>();
        for (String value : defaultList(requirement == null ? null : requirement.getValues())) {
            String text = Strings.nullToEmpty(value).trim();
            if (!text.isEmpty()) {
                result.add(text);
            }
        }
        return Lists.newArrayList(result);
    }

    private static String displayLabel(String rawKey) {
        String key = normalized(rawKey);
        if (in(key, "province", "city", "area", "region_group")) {
            return "地区";
        }
        if ("major".equals(key)) {
            return "专业";
        }
        if ("level1".equals(key)) {
            return "专业门类";
        }
        if (in(key, "level2", "level3")) {
            return "专业类";
        }
        if ("major_tag".equals(key)) {
            return "专业标签";
        }
        if (in(key, "school", "schools")) {
            return "院校";
        }
        if ("school_nature".equals(key)) {
            return "院校性质";
        }
        if ("program_type".equals(key)) {
            return "招生类型";
        }
        if ("school_category".equals(key)) {
            return "院校类型";
        }
        if ("school_level".equals(key)) {
            return "院校层次";
        }
        if ("school_tag".equals(key)) {
            return "院校标签";
        }
        if ("tier".equals(key)) {
            return "录取档位";
        }
        return null;
    }

    private static boolean in(String value, String... candidates) {
        for (String candidate : candidates) {
            if (candidate.equals(value)) {
                return true;
            }
        }
        return false;
    }

    private static String normalized(String value) {
        return Strings.nullToEmpty(value).trim().toLowerCase(Locale.ROOT);
    }

    private static <T> List<T> defaultList(List<T> values) {
        return values == null ? Lists.newArrayList() : values;
    }

    private static List<String> nonNull(List<String> values) {
        return values == null ? Lists.newArrayList() : values;
    }
}
