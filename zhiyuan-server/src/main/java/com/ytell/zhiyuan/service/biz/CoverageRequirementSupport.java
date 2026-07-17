package com.ytell.zhiyuan.service.biz;

import com.google.common.base.Strings;
import com.google.common.collect.Lists;
import com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO;
import com.ytell.zhiyuan.model.dto.planning.ConstraintStateDTO;
import com.ytell.zhiyuan.model.dto.planning.CoverageRequirementDTO;
import com.ytell.zhiyuan.model.dto.planning.HardConstraintsDTO;
import com.ytell.zhiyuan.model.dto.planning.HardPlanningObjectivesDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import com.ytell.zhiyuan.model.dto.planning.UserGoalFixProposalReq;

import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Set;

final class CoverageRequirementSupport {

    private CoverageRequirementSupport() {
    }

    static String validate(UserGoalFixProposalReq.RequirementDTO requirement) {
        if (requirement == null || !ProjectedHardRequirementSupport.KIND_INCLUDE.equals(
                normalized(requirement.getKind()))) {
            return null;
        }
        if (targetList(requirement) == null) {
            return "暂不支持非排他覆盖要求字段：" + requirement.getDomain() + "." + requirement.getKey();
        }
        if (normalizedValues(requirement.getValues()).isEmpty()) {
            return "非排他覆盖要求必须包含明确值。";
        }
        if (isAdmissionTier(requirement)
                && normalizedValues(requirement.getValues()).stream()
                .anyMatch(value -> normalizeTier(value).isEmpty())) {
            return "录取档位只支持明确的冲、稳、保。";
        }
        if (minCount(requirement) <= 0) {
            return "非排他覆盖要求的 minCount 必须是大于 0 的整数。";
        }
        return null;
    }

    static boolean matches(CandidateItemDTO candidate, UserGoalFixProposalReq.RequirementDTO requirement) {
        List<String> target = targetList(requirement);
        if (candidate == null || target == null || target.isEmpty()) {
            return false;
        }
        String domain = normalized(requirement.getDomain());
        if ("admission".equals(domain) && "tier".equals(normalized(requirement.getKey()))) {
            return target.contains(normalizeTier(candidate.getTier()));
        }
        HardConstraintsDTO isolated = new HardConstraintsDTO();
        if ("region".equals(domain)) {
            isolated.setMustIncludeRegions(target);
        } else if ("major".equals(domain)) {
            isolated.setMustIncludeMajors(target);
        } else if ("school".equals(domain)) {
            isolated.setMustIncludeSchools(target);
        } else {
            return false;
        }
        return RepairCandidateEligibility.isEligibleForHardConstraints(candidate, isolated);
    }

    static void persist(PlanningStateDTO state,
                        List<UserGoalFixProposalReq.RequirementDTO> requirements) {
        if (state == null) {
            return;
        }
        List<UserGoalFixProposalReq.RequirementDTO> includeRequirements = defaultList(requirements);
        if (includeRequirements.stream().noneMatch(CoverageRequirementSupport::isInclude)) {
            return;
        }
        if (state.getConstraintState() == null) {
            state.setConstraintState(new ConstraintStateDTO());
        }
        ConstraintStateDTO constraintState = state.getConstraintState();
        if (constraintState.getHardPlanningObjectives() == null) {
            constraintState.setHardPlanningObjectives(new HardPlanningObjectivesDTO());
        }
        HardPlanningObjectivesDTO objectives = constraintState.getHardPlanningObjectives();
        if (objectives.getCoverageRequirements() == null) {
            objectives.setCoverageRequirements(Lists.newArrayList());
        }
        for (UserGoalFixProposalReq.RequirementDTO requirement : includeRequirements) {
            if (!isInclude(requirement)) {
                continue;
            }
            CoverageRequirementDTO objective = from(requirement);
            CoverageRequirementDTO existing = objectives.getCoverageRequirements().stream()
                    .filter(item -> sameIdentity(item, objective))
                    .findFirst()
                    .orElse(null);
            if (existing == null) {
                objectives.getCoverageRequirements().add(objective);
            } else {
                existing.setMinCount(Math.max(safeMinCount(existing.getMinCount()), safeMinCount(objective.getMinCount())));
            }
        }
    }

    static boolean isPersisted(PlanningStateDTO state,
                               UserGoalFixProposalReq.RequirementDTO requirement) {
        CoverageRequirementDTO expected = from(requirement);
        HardPlanningObjectivesDTO objectives = state == null || state.getConstraintState() == null
                ? null : state.getConstraintState().getHardPlanningObjectives();
        return defaultList(objectives == null ? null : objectives.getCoverageRequirements()).stream()
                .anyMatch(item -> sameIdentity(item, expected)
                        && safeMinCount(item.getMinCount()) >= safeMinCount(expected.getMinCount()));
    }

    static List<CoverageRequirementDTO> confirmedRequirements(PlanningStateDTO state) {
        HardPlanningObjectivesDTO objectives = state == null || state.getConstraintState() == null
                ? null : state.getConstraintState().getHardPlanningObjectives();
        return defaultList(objectives == null ? null : objectives.getCoverageRequirements());
    }

    static boolean matches(CandidateItemDTO candidate, CoverageRequirementDTO requirement) {
        if (requirement == null) {
            return false;
        }
        UserGoalFixProposalReq.RequirementDTO view = new UserGoalFixProposalReq.RequirementDTO();
        view.setKind(ProjectedHardRequirementSupport.KIND_INCLUDE);
        view.setDomain(requirement.getDomain());
        view.setKey(requirement.getKey());
        view.setValues(defaultList(requirement.getValues()));
        view.setMinCount(requirement.getMinCount());
        return matches(candidate, view);
    }

    static int minCount(UserGoalFixProposalReq.RequirementDTO requirement) {
        return safeMinCount(requirement == null ? null : requirement.getMinCount());
    }

    static int minCount(CoverageRequirementDTO requirement) {
        return safeMinCount(requirement == null ? null : requirement.getMinCount());
    }

    private static CoverageRequirementDTO from(UserGoalFixProposalReq.RequirementDTO requirement) {
        CoverageRequirementDTO objective = new CoverageRequirementDTO();
        objective.setDomain(normalized(requirement == null ? null : requirement.getDomain()));
        objective.setKey(normalized(requirement == null ? null : requirement.getKey()));
        objective.setValues(isAdmissionTier(requirement)
                ? canonicalTierValues(requirement == null ? null : requirement.getValues())
                : normalizedValues(requirement == null ? null : requirement.getValues()));
        objective.setMinCount(minCount(requirement));
        return objective;
    }

    private static List<String> targetList(UserGoalFixProposalReq.RequirementDTO requirement) {
        if (!isInclude(requirement)) {
            return null;
        }
        String domain = normalized(requirement.getDomain());
        String key = normalized(requirement.getKey());
        List<String> encoded = encodedValues(key, requirement.getValues());
        if ("region".equals(domain) && in(key, "province", "city", "area", "region_group")) {
            return encoded;
        }
        if ("major".equals(domain) && in(key, "major", "level1", "level2", "level3", "major_tag")) {
            return encoded;
        }
        if ("school".equals(domain) && in(key, "school", "schools", "school_nature", "program_type",
                "school_category", "school_level", "school_tag")) {
            return encoded;
        }
        if ("admission".equals(domain) && "tier".equals(key)) {
            return canonicalTierValues(requirement.getValues());
        }
        return null;
    }

    private static List<String> encodedValues(String key, List<String> values) {
        List<String> result = Lists.newArrayList();
        for (String value : normalizedValues(values)) {
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

    private static boolean sameIdentity(CoverageRequirementDTO left, CoverageRequirementDTO right) {
        return left != null && right != null
                && normalized(left.getDomain()).equals(normalized(right.getDomain()))
                && normalized(left.getKey()).equals(normalized(right.getKey()))
                && new LinkedHashSet<String>(normalizedValues(left.getValues()))
                .equals(new LinkedHashSet<String>(normalizedValues(right.getValues())));
    }

    private static boolean isInclude(UserGoalFixProposalReq.RequirementDTO requirement) {
        return requirement != null && ProjectedHardRequirementSupport.KIND_INCLUDE.equals(
                normalized(requirement.getKind()));
    }

    private static boolean isAdmissionTier(UserGoalFixProposalReq.RequirementDTO requirement) {
        return requirement != null
                && "admission".equals(normalized(requirement.getDomain()))
                && "tier".equals(normalized(requirement.getKey()));
    }

    private static List<String> canonicalTierValues(List<String> values) {
        Set<String> result = new LinkedHashSet<String>();
        for (String value : defaultList(values)) {
            String tier = normalizeTier(value);
            if (!tier.isEmpty()) {
                result.add(tier);
            }
        }
        return Lists.newArrayList(result);
    }

    private static String normalizeTier(String value) {
        String text = Strings.nullToEmpty(value).trim();
        String lowered = text.toLowerCase(Locale.ROOT);
        if (in(lowered, "protect", "protective", "safety") || in(text, "保", "保底", "兜底", "保险")) {
            return "保";
        }
        if (in(lowered, "stable", "safe") || in(text, "稳", "稳妥")) {
            return "稳";
        }
        if (in(lowered, "sprint", "reach") || in(text, "冲", "冲刺")) {
            return "冲";
        }
        return "";
    }

    private static int safeMinCount(Integer value) {
        return value == null ? 1 : value;
    }

    private static List<String> normalizedValues(List<String> values) {
        Set<String> result = new LinkedHashSet<String>();
        for (String value : defaultList(values)) {
            String text = Strings.nullToEmpty(value).trim();
            if (!text.isEmpty()) {
                result.add(text);
            }
        }
        return Lists.newArrayList(result);
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
}
