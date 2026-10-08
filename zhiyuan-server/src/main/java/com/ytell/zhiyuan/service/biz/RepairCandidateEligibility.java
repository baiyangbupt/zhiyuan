package com.ytell.zhiyuan.service.biz;

import com.google.common.base.Strings;
import com.google.common.collect.Lists;
import com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO;
import com.ytell.zhiyuan.model.dto.planning.ConstraintStateDTO;
import com.ytell.zhiyuan.model.dto.planning.HardConstraintsDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningUnitDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningUnitMajorDTO;

import java.util.List;
import java.util.Locale;

final class RepairCandidateEligibility {

    /** 范围侧可去的尾缀（专业目录层级词汇）✓：`"医学类"`→`"医学"`、`"工学门类"`→`"工学"` ✓。 */
    private static final List<String> TAXONOMY_SUFFIXES = Lists.newArrayList("门类", "大类", "类");

    private RepairCandidateEligibility() {
    }

    static boolean hasConfirmedHardConstraints(PlanningStateDTO state) {
        return confirmedHardConstraints(state) != null;
    }

    static boolean isEligibleForConfirmedHardConstraints(CandidateItemDTO item, PlanningStateDTO state) {
        return isEligibleForHardConstraints(item, confirmedHardConstraints(state));
    }

    static boolean isEligibleForHardConstraints(CandidateItemDTO item, HardConstraintsDTO hard) {
        if (item == null) {
            return false;
        }
        if (hard == null) {
            return true;
        }
        if (regionExcluded(hard.getMustExcludeRegions(), hard.getMustExcludeRegionIds(),
                item.getProvinceName(), item.getCityName(), item.getProvinceId(), item.getCityId())
                || matchesAnySchool(item, hard.getMustExcludeSchools())
                || majorExcluded(item, hard.getMustExcludeMajors(), hard.getMustExcludeMajorIds())) {
            return false;
        }
        return regionRequired(hard.getMustIncludeRegions(), hard.getMustIncludeRegionIds(),
                item.getProvinceName(), item.getCityName(), item.getProvinceId(), item.getCityId())
                && matchesRequiredSchool(item, hard.getMustIncludeSchools())
                && majorRequired(item, hard.getMustIncludeMajors(), hard.getMustIncludeMajorIds());
    }

    static boolean isEligibleForConfirmedHardConstraints(PlanningUnitDTO unit, PlanningStateDTO state) {
        return isEligibleForHardConstraints(unit, confirmedHardConstraints(state));
    }

    static boolean isEligibleForHardConstraints(PlanningUnitDTO unit, HardConstraintsDTO hard) {
        if (unit == null) {
            return false;
        }
        if (hard == null) {
            return true;
        }
        if (regionExcluded(hard.getMustExcludeRegions(), hard.getMustExcludeRegionIds(),
                unit.getProvinceName(), unit.getCityName(), unit.getProvinceId(), unit.getCityId())
                || matchesAnyPlanningUnitSchool(unit, hard.getMustExcludeSchools())
                || planningUnitMajorExcluded(unit, hard.getMustExcludeMajors(), hard.getMustExcludeMajorIds())) {
            return false;
        }
        return regionRequired(hard.getMustIncludeRegions(), hard.getMustIncludeRegionIds(),
                unit.getProvinceName(), unit.getCityName(), unit.getProvinceId(), unit.getCityId())
                && (defaultList(hard.getMustIncludeSchools()).isEmpty()
                || matchesAnyPlanningUnitSchool(unit, hard.getMustIncludeSchools()))
                && planningUnitMajorRequired(unit, hard.getMustIncludeMajors(), hard.getMustIncludeMajorIds());
    }

    /**
     * 区域：**ID 优先、名字兜底** ✓。
     *
     * <p>两边都有 ID 时**以 ID 为准** ✓——名字会"各版本各说各话"（"北京"被按市级字段找 ✗、
     * "医学"⊂"临床医学"那种放大 ✗ 都是名字惹的 ✓）；任一边缺 ID 就回退名字 ✓——
     * 不能因为对方没带 ID 就把它判死 ✗。
     */
    private static boolean regionIdsMatch(String provinceId, String cityId, List<String> values) {
        if (provinceId == null && cityId == null) {
            return false;
        }
        for (String value : defaultList(values)) {
            if (value == null) {
                continue;
            }
            String trimmed = value.trim();
            if (trimmed.equals(provinceId) || trimmed.equals(cityId)) {
                return true;
            }
        }
        return false;
    }

    private static boolean regionExcluded(List<String> excludeNames, List<String> excludeIds,
                                          String provinceName, String cityName,
                                          String provinceId, String cityId) {
        // 排除看"命中即排" ✓：名字命中或 ID 命中都算 ✓（ID 是权威 ✓，名字命中也可执行 ✓）。
        return matchesAnyRegionScope(excludeNames, provinceName, cityName)
                || regionIdsMatch(provinceId, cityId, excludeIds);
    }

    private static boolean regionRequired(List<String> includeNames, List<String> includeIds,
                                          String provinceName, String cityName,
                                          String provinceId, String cityId) {
        boolean constraintHasIds = !defaultList(includeIds).isEmpty();
        boolean candidateHasIds = provinceId != null || cityId != null;
        if (constraintHasIds && candidateHasIds) {
            return regionIdsMatch(provinceId, cityId, includeIds);
        }
        return defaultList(includeNames).isEmpty()
                || matchesAnyRegionScope(includeNames, provinceName, cityName);
    }

    private static HardConstraintsDTO confirmedHardConstraints(PlanningStateDTO state) {
        ConstraintStateDTO constraintState = state == null ? null : state.getConstraintState();
        HardConstraintsDTO hard = constraintState == null ? null : constraintState.getHardConstraints();
        if (hard == null) {
            return null;
        }
        if (defaultList(hard.getMustIncludeRegions()).isEmpty()
                && defaultList(hard.getMustExcludeRegions()).isEmpty()
                && defaultList(hard.getMustIncludeRegionIds()).isEmpty()
                && defaultList(hard.getMustExcludeRegionIds()).isEmpty()
                && defaultList(hard.getMustIncludeSchools()).isEmpty()
                && defaultList(hard.getMustExcludeSchools()).isEmpty()
                && defaultList(hard.getMustIncludeMajors()).isEmpty()
                && defaultList(hard.getMustExcludeMajors()).isEmpty()
                // ID 列表也算数 ✓：只看名字会把"只给了 ID"的约束读成**空约束** ✗
                // → 整条约束被当成不存在 ✗（2026-09-26 单测红：只给专业 ID 时判成"无约束" ✓）。
                && defaultList(hard.getMustIncludeMajorIds()).isEmpty()
                && defaultList(hard.getMustExcludeMajorIds()).isEmpty()) {
            return null;
        }
        return hard;
    }

    /**
     * 专业：**ID 优先、名字兜底** ✓（与区域同一条规矩 ✓——"专业按 ID"，区域先行 ✓）。
     *
     * <p>ID 的用处正是名字判不动的那些格 ✗："临床医学" 在名字侧是**子串**匹配 ✓
     * （要能命中"临床医学(五年)"✓），于是也会命中"中西医临床医学"✗；躲开医学门类
     * 只能靠 `majorCategory` 的**整段相等** ✓（2026-09-25 那条裁决 ✓）。
     * `majorId` 是目录里的**同一个身份** ✓：池里 1008/1454 条带真 ID ✓，
     * 与 `/catalog/lookup/major` 同一套词汇表 ✓（真栈核对 ✓）。
     *
     * <p>`"0"`＝大类/试验班（池里 446 条 ✗）**没有单一专业身份** ✓ → 按"缺 ID"处理 ✓：
     * 回退名字 ✓、**不判死** ✗——"任一边缺 ID 就回退名字"这条规矩不许破 ✓。
     */
    private static boolean majorRequired(CandidateItemDTO item, List<String> includeNames, List<String> includeIds) {
        boolean constraintHasIds = !defaultList(includeIds).isEmpty();
        boolean candidateHasId = item != null && hasMajorId(item.getMajorId());
        if (constraintHasIds && candidateHasId) {
            return majorIdsMatch(item.getMajorId(), includeIds);
        }
        return defaultList(includeNames).isEmpty() || matchesAnyMajor(item, includeNames);
    }

    /** 排除看"命中即排" ✓：名字命中或 ID 命中都算 ✓（同区域口径 ✓）。 */
    private static boolean majorExcluded(CandidateItemDTO item, List<String> excludeNames, List<String> excludeIds) {
        return matchesAnyMajor(item, excludeNames)
                || majorIdsMatch(item == null ? null : item.getMajorId(), excludeIds);
    }

    /** `"0"` 与空都算"没有身份" ✓（大类/试验班 ✓）。 */
    private static boolean hasMajorId(String majorId) {
        return !Strings.isNullOrEmpty(majorId) && !"0".equals(majorId.trim());
    }

    private static boolean majorIdsMatch(String majorId, List<String> values) {
        if (!hasMajorId(majorId)) {
            return false;
        }
        for (String value : defaultList(values)) {
            if (value != null && majorId.trim().equals(value.trim())) {
                return true;
            }
        }
        return false;
    }

    private static boolean matchesRequiredSchool(CandidateItemDTO item, List<String> values) {
        return defaultList(values).isEmpty() || matchesAnySchool(item, values);
    }

    private static boolean matchesAnyRegion(CandidateItemDTO item, List<String> values) {
        return item != null && matchesAnyRegionScope(values, item.getProvinceName(), item.getCityName());
    }

    private static boolean matchesAnyRegionScope(List<String> values, String provinceName, String cityName) {
        for (String value : defaultList(values)) {
            // 与提案编译侧（`ScopeMatcher.matchesRegion`）**同一条判据** ✓：
            // 大区表 ✓ + 规范化身份相等 ✓（不再用双向子串 ✗——两层判据不一致会让
            // "编译时匹配上、过滤时匹配不上"这种自相矛盾出现 ✗）。
            if (RegionScopeSupport.matchesRegionScope(value, provinceName, cityName)
                    || RegionScopeSupport.sameRegionName(provinceName, value)
                    || RegionScopeSupport.sameRegionName(cityName, value)) {
                return true;
            }
        }
        return false;
    }

    private static boolean matchesAnySchool(CandidateItemDTO item, List<String> values) {
        return item != null && matchesAnySchoolScope(values, item);
    }

    private static boolean matchesAnyMajor(CandidateItemDTO item, List<String> values) {
        return item != null && matchesAnyMajorScope(values, item);
    }

    private static boolean matchesAnyPlanningUnitMajor(PlanningUnitDTO unit, List<String> values) {
        if (unit == null || defaultList(values).isEmpty()) {
            return false;
        }
        for (PlanningUnitMajorDTO major : planningUnitMajors(unit)) {
            if (major != null && matchesAnyMajorScope(values, planningUnitMajorAsCandidate(unit, major))) {
                return true;
            }
        }
        return false;
    }

    /** 组模式的匹配对象是**单元** ✓（与候选侧同一条"ID 优先" ✓，口径不许分叉 ✗）。 */
    private static boolean planningUnitMajorRequired(PlanningUnitDTO unit, List<String> includeNames, List<String> includeIds) {
        boolean constraintHasIds = !defaultList(includeIds).isEmpty();
        if (constraintHasIds && planningUnitHasMajorIds(unit)) {
            return planningUnitMajorIdsMatch(unit, includeIds);
        }
        return defaultList(includeNames).isEmpty() || matchesAnyPlanningUnitMajor(unit, includeNames);
    }

    private static boolean planningUnitMajorExcluded(PlanningUnitDTO unit, List<String> excludeNames, List<String> excludeIds) {
        return matchesAnyPlanningUnitMajor(unit, excludeNames) || planningUnitMajorIdsMatch(unit, excludeIds);
    }

    private static List<PlanningUnitMajorDTO> planningUnitMajors(PlanningUnitDTO unit) {
        if (unit == null) {
            return Lists.newArrayList();
        }
        return !defaultList(unit.getSelectedMajors()).isEmpty() ? unit.getSelectedMajors() : unit.getAllMajors();
    }

    private static boolean planningUnitHasMajorIds(PlanningUnitDTO unit) {
        for (PlanningUnitMajorDTO major : planningUnitMajors(unit)) {
            if (major != null && hasMajorId(major.getMajorId())) {
                return true;
            }
        }
        return false;
    }

    private static boolean planningUnitMajorIdsMatch(PlanningUnitDTO unit, List<String> values) {
        for (PlanningUnitMajorDTO major : planningUnitMajors(unit)) {
            if (major != null && majorIdsMatch(major.getMajorId(), values)) {
                return true;
            }
        }
        return false;
    }

    private static boolean matchesAnyPlanningUnitSchool(PlanningUnitDTO unit, List<String> values) {
        if (unit == null) {
            return false;
        }
        if (matchesAnySchoolScope(values, planningUnitAsCandidate(unit))) {
            return true;
        }
        List<PlanningUnitMajorDTO> majors = !defaultList(unit.getSelectedMajors()).isEmpty()
                ? unit.getSelectedMajors() : unit.getAllMajors();
        for (PlanningUnitMajorDTO major : defaultList(majors)) {
            if (major != null && matchesAnySchoolScope(values, planningUnitMajorAsCandidate(unit, major))) {
                return true;
            }
        }
        return false;
    }

    private static CandidateItemDTO planningUnitAsCandidate(PlanningUnitDTO unit) {
        CandidateItemDTO item = new CandidateItemDTO();
        if (unit == null) {
            return item;
        }
        item.setSchoolName(unit.getSchoolName());
        item.setProvinceName(unit.getProvinceName());
        item.setProvinceId(unit.getProvinceId());
        item.setCityId(unit.getCityId());
        item.setCityName(unit.getCityName());
        item.setSchoolLevel(unit.getSchoolLevel());
        item.setSchoolNature(unit.getSchoolNature());
        item.setSchoolCategory(unit.getSchoolCategory());
        return item;
    }

    private static CandidateItemDTO planningUnitMajorAsCandidate(PlanningUnitDTO unit, PlanningUnitMajorDTO major) {
        CandidateItemDTO item = planningUnitAsCandidate(unit);
        if (major != null) {
            item.setMajorName(major.getMajorName());
            // 分类名一路带上来 ✓（不然单元侧只看得到专业名 ✗：`"医学类"` 命中不了
            // `discipline="医学"` ——候选侧能留、单元侧判违反，就是 2026-10-08 那条 40905 ✗）。
            item.setMajorCategory(major.getMajorCategory());
            item.setMajorDiscipline(major.getMajorDiscipline());
            item.setTuitionPerYear(major.getTuitionPerYear());
            item.setReasonCodes(defaultList(major.getReasonCodes()));
            item.setMajorPlanTags(defaultList(major.getMajorPlanTags()));
        }
        return item;
    }

    private static boolean matchesAnyText(List<String> values, String... fields) {
        for (String value : defaultList(values)) {
            for (String field : fields == null ? new String[0] : fields) {
                if (textMatches(field, value)) {
                    return true;
                }
            }
        }
        return false;
    }

    private static boolean matchesAnySchoolScope(List<String> values, CandidateItemDTO item) {
        for (String value : defaultList(values)) {
            if (matchesSchoolScope(value, item)) {
                return true;
            }
        }
        return false;
    }

    private static boolean matchesSchoolScope(String value, CandidateItemDTO item) {
        if (item == null || Strings.isNullOrEmpty(value)) {
            return false;
        }
        String scope = value.trim();
        if (textMatches(item.getSchoolName(), scope)) {
            return true;
        }
        int split = scope.indexOf(':');
        if (split < 0) {
            split = scope.indexOf('：');
        }
        if (split < 0) {
            return textMatches(item.getSchoolNature(), scope)
                    || textMatches(item.getSchoolCategory(), scope)
                    || textMatches(item.getSchoolLevel(), scope)
                    || matchesHighTuitionScope(item, scope)
                    || matchesAnyText(Lists.newArrayList(scope), defaultList(item.getSchoolRankTags()).toArray(new String[0]))
                    || matchesAnyText(Lists.newArrayList(scope), defaultList(item.getSchoolBasicTags()).toArray(new String[0]))
                    || matchesAnyText(Lists.newArrayList(scope), defaultList(item.getSchoolPopupTags()).toArray(new String[0]))
                    || matchesAnyText(Lists.newArrayList(scope), defaultList(item.getReasonCodes()).toArray(new String[0]));
        }
        String label = scope.substring(0, split).trim();
        String pattern = scope.substring(split + 1).trim();
        if (Strings.isNullOrEmpty(pattern)) {
            return false;
        }
        if (containsAny(label, "性质", "办学")) {
            return textMatches(item.getSchoolNature(), pattern);
        }
        if (containsAny(label, "招生类型", "项目", "限制")) {
            return matchesHighTuitionScope(item, pattern)
                    || textMatches(item.getSchoolName(), pattern)
                    || textMatches(item.getMajorName(), pattern)
                    || matchesAnyText(Lists.newArrayList(pattern), defaultList(item.getMajorPlanTags()).toArray(new String[0]))
                    || matchesAnyText(Lists.newArrayList(pattern), defaultList(item.getReasonCodes()).toArray(new String[0]));
        }
        if (containsAny(label, "院校类型", "学校类型") || "类型".equals(label)) {
            return textMatches(item.getSchoolCategory(), pattern);
        }
        if (containsAny(label, "层次", "级别")) {
            return textMatches(item.getSchoolLevel(), pattern)
                    || matchesAnyText(Lists.newArrayList(pattern), defaultList(item.getSchoolRankTags()).toArray(new String[0]));
        }
        if (containsAny(label, "标签")) {
            return matchesAnyText(Lists.newArrayList(pattern), defaultList(item.getSchoolRankTags()).toArray(new String[0]))
                    || matchesAnyText(Lists.newArrayList(pattern), defaultList(item.getSchoolBasicTags()).toArray(new String[0]))
                    || matchesAnyText(Lists.newArrayList(pattern), defaultList(item.getSchoolPopupTags()).toArray(new String[0]));
        }
        return false;
    }

    private static boolean matchesAnyMajorScope(List<String> values, CandidateItemDTO item) {
        for (String value : defaultList(values)) {
            if (matchesMajorScope(value, item)) {
                return true;
            }
        }
        return false;
    }

    private static boolean matchesMajorScope(String value, CandidateItemDTO item) {
        if (item == null || Strings.isNullOrEmpty(value)) {
            return false;
        }
        String scope = value.trim();
        // 专业名用子串（"临床医学" 必须能命中 "临床医学(五年)" ✓），
        // 但 `majorCategory` / `majorDiscipline` 是**粗粒度**分类字段，不能一起丢进双向子串：
        // `"临床医学".contains("医学")` 为真，于是"只保留临床医学"会命中整个医学门类
        // （2026-09-25 实测：池里 599 行 `discipline=医学` vs 真正 `category=临床医学类` 只有 71 行，
        //  且 `"中西医临床医学".contains("医学")` 让排除规则把 71 行真临床医学一起排掉 → 方案清空 ✓）。
        if (textMatches(item.getMajorName(), scope)
                || equalsTaxonomy(item.getMajorCategory(), scope)
                || equalsTaxonomy(item.getMajorDiscipline(), scope)) {
            return true;
        }
        int split = scope.indexOf(':');
        if (split < 0) {
            split = scope.indexOf('：');
        }
        if (split < 0) {
            return matchesAnyText(Lists.newArrayList(scope), defaultList(item.getMajorRankTags()).toArray(new String[0]))
                    || matchesAnyText(Lists.newArrayList(scope), defaultList(item.getMajorPlanTags()).toArray(new String[0]))
                    || matchesAnyText(Lists.newArrayList(scope), defaultList(item.getReasonCodes()).toArray(new String[0]));
        }
        String label = scope.substring(0, split).trim();
        String pattern = scope.substring(split + 1).trim();
        if (Strings.isNullOrEmpty(pattern)) {
            return false;
        }
        if (containsAny(label, "专业门类", "专业类", "门类")) {
            return matchesAnyText(Lists.newArrayList(pattern), item.getMajorCategory(), item.getMajorDiscipline());
        }
        if (containsAny(label, "专业标签", "标签")) {
            return matchesAnyText(Lists.newArrayList(pattern), defaultList(item.getMajorRankTags()).toArray(new String[0]))
                    || matchesAnyText(Lists.newArrayList(pattern), defaultList(item.getMajorPlanTags()).toArray(new String[0]));
        }
        if (containsAny(label, "招生类型", "项目", "限制")) {
            return textMatches(item.getMajorName(), pattern)
                    || matchesAnyText(Lists.newArrayList(pattern), defaultList(item.getMajorPlanTags()).toArray(new String[0]))
                    || matchesAnyText(Lists.newArrayList(pattern), defaultList(item.getReasonCodes()).toArray(new String[0]));
        }
        return false;
    }

    private static boolean matchesHighTuitionScope(CandidateItemDTO item, String pattern) {
        if (item == null || !isHighTuitionPattern(pattern)) {
            return false;
        }
        Integer tuition = item.getTuitionPerYear();
        return tuition != null && tuition > 20000;
    }

    private static boolean isHighTuitionPattern(String pattern) {
        if (Strings.isNullOrEmpty(pattern)) {
            return false;
        }
        String normalized = pattern.trim().toLowerCase(Locale.ROOT);
        return normalized.contains("高收费")
                || normalized.contains("高学费")
                || normalized.contains("学费高")
                || normalized.contains("high_tuition");
    }

    private static boolean containsAny(String text, String... needles) {
        if (Strings.isNullOrEmpty(text) || needles == null) {
            return false;
        }
        for (String needle : needles) {
            if (!Strings.isNullOrEmpty(needle) && text.contains(needle)) {
                return true;
            }
        }
        return false;
    }

    /**
     * 粗粒度分类字段（`majorCategory` / `majorDiscipline`）**整段相等**，
     * 外加**范围侧尾缀容忍**（`"医学类"` 当 `"医学"` 用 ✓）。
     *
     * <p>与 {@link #textMatches} 的区别是刻意的：这两个字段是"类/门类"层级，
     * 用子串比会把细粒度专业名放大成整个门类——`"临床医学"` 会命中所有
     * `discipline=医学` 的行（实测放大约 8 倍），而 `"中西医临床医学"`
     * 会反过来把整个医学门类排干净（实测把方案排成 0 单元）。
     *
     * <p>尾缀容忍是"用户/模型把门类说成'医学类'"那条实测缺陷的修点（2026-10-08）：
     * 确认载荷里范围只有名字（无编码）时值就是 `"医学类"` ——门类字段 `discipline`
     * 写的是 `"医学"` ✗，整段相等比对**一条都不中** ✗ → 132 条方案被排空 → 40906 ✓。
     * 只允许**范围侧**去 `<类|门类|大类>` 尾缀、字段侧原样比：把 `"临床医学"` 放大成
     * `category=临床医学类` 的那个方向仍然被挡住 ✗（去尾缀后的 `"临床医学"` 不等于
     * 字段 `"临床医学类"` ✓）。
     *
     * <p>字段侧不去尾缀是另一条边界：`discipline` 实样既有 `"医学"` 也有 `"工学类"` ✗，
     * "用户说'工学'、字段写'工学类'"这条今天仍对不上 ✗——但放宽它就会打开
     * `"临床医学"`↔`"临床医学类"` 那道闸 ✗，不在本次修点内。
     */
    static boolean equalsTaxonomy(String field, String scope) {
        if (Strings.isNullOrEmpty(field) || Strings.isNullOrEmpty(scope)) {
            return false;
        }
        String normalizedField = field.trim().toLowerCase(Locale.ROOT);
        String normalizedScope = scope.trim().toLowerCase(Locale.ROOT);
        if (normalizedField.equals(normalizedScope)) {
            return true;
        }
        for (String suffix : TAXONOMY_SUFFIXES) {
            if (normalizedScope.endsWith(suffix) && normalizedScope.length() > suffix.length()
                    && normalizedField.equals(normalizedScope.substring(0, normalizedScope.length() - suffix.length()))) {
                return true;
            }
        }
        return false;
    }

    private static boolean textMatches(String field, String pattern) {
        if (Strings.isNullOrEmpty(field) || Strings.isNullOrEmpty(pattern)) {
            return false;
        }
        String normalizedField = field.trim().toLowerCase(Locale.ROOT);
        String normalizedPattern = pattern.trim().toLowerCase(Locale.ROOT);
        return normalizedField.contains(normalizedPattern) || normalizedPattern.contains(normalizedField);
    }

    private static <T> List<T> defaultList(List<T> values) {
        return values == null ? Lists.newArrayList() : values;
    }
}
