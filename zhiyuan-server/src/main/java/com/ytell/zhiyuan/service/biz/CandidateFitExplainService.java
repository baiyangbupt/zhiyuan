package com.ytell.zhiyuan.service.biz;

import com.google.common.base.Strings;
import com.google.common.collect.Lists;
import com.ytell.zhiyuan.common.exception.BusinessException;
import com.ytell.zhiyuan.model.dto.CreateSessionReq;
import com.ytell.zhiyuan.model.dto.planning.CandidateFitExplainReq;
import com.ytell.zhiyuan.model.dto.planning.CandidateFitExplainRes;
import com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO;
import com.ytell.zhiyuan.model.dto.planning.HardConstraintsDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import com.ytell.zhiyuan.model.dto.planning.SoftPreferencesDTO;
import com.ytell.zhiyuan.model.dto.planning.ExplicitProfileDTO;
import com.ytell.zhiyuan.model.dto.planning.ConstraintStateDTO;
import com.ytell.zhiyuan.model.dto.planning.ProfileStateDTO;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.List;
import java.util.Locale;

/**
 * 适配性解释（只读纵切）：解释**某一个**候选为什么匹配/不匹配。
 *
 * <p>分工：候选预览回答"有哪些候选"，候选比较回答"几个候选并排长什么样"，
 * 这一条回答"**为什么**是它"——匹配点逐条给出**来源字段**（没有来源的点不许说），
 * 风险原样透传候选行自己的标志，概率如实说不可用。</p>
 *
 * <p>四条纪律（每条都是评审点）：</p>
 * <ol>
 *   <li><b>只读</b>：载入走 {@link CandidatePreviewService#loadReadOnlyCandidatePool}
 *       （不 savePlanningState、不 bump version）——解释不改变被解释的东西；</li>
 *   <li><b>值来自候选行</b>：`entityId`（= volunteerId）只用于定位行，匹配点/风险里
 *       出现的取值全部取自真实候选行与会话状态，模型不能凭记忆复述；</li>
 *   <li><b>没有来源的匹配不存在</b>：每条 matched 都带 {@code source}
 *       （`候选行字段 vs 会话字段`）；算不了的一侧（缺画像/缺候选字段）进
 *       {@code limitations} 并在维度上标 {@code unknown}，不猜；</li>
 *   <li><b>不产出概率</b>：本服务没有任何权威概率来源，{@code probability} 恒为
 *       {@code unavailable} + 原因——"适配"（偏好/约束匹配度）与"概率"是两件事。</li>
 * </ol>
 */
@Slf4j
@Service
public class CandidateFitExplainService {

    /** 找不到的 ID 原样列出（前缀 + id），与比较链同一口径。 */
    public static final String LIMITATION_ENTITY_NOT_FOUND_PREFIX = "entity_not_found:";

    /** 会话侧字段缺失，某一维度算不了（如档案无选科）。 */
    public static final String LIMITATION_PROFILE_FIELD_MISSING_PREFIX = "profile_field_missing:";

    /** 候选行字段缺失，某一维度算不了（如学费为空）。 */
    public static final String LIMITATION_CANDIDATE_FIELD_MISSING_PREFIX = "candidate_field_missing:";

    /** 选科要求原样无法解析（如"物理或化学"这种选一格式）：如实标注，不硬猜。 */
    public static final String LIMITATION_SUBJECT_REQUIREMENT_UNPARSED_PREFIX = "subject_requirement_unparsed:";

    /** 带标签的范围（如"性质:985"）本切片不逐条求值：如实标注，不假装核过。 */
    public static final String LIMITATION_SCOPE_LABEL_NOT_EVALUATED_PREFIX = "scope_label_not_evaluated:";

    /** 硬约束聚合判定说不合格，但没有任何一个维度能归因：如实标注（解释不完整是事实）。 */
    public static final String LIMITATION_HARD_CONSTRAINTS_CONFLICT_UNATTRIBUTED =
            "hard_constraints_conflict_unattributed";

    public static final String DIM_SUBJECT_REQUIREMENT = "subject_requirement";
    public static final String DIM_REGION_PREFERENCE = "region_preference";
    public static final String DIM_MAJOR_INTENT = "major_intent";
    public static final String DIM_SCHOOL_INTENT = "school_intent";
    public static final String DIM_TUITION_RANGE = "tuition_range";

    public static final String STATUS_MATCHED = "matched";
    public static final String STATUS_CONFLICT = "conflict";
    public static final String STATUS_NO_MATCH = "no_match";
    public static final String STATUS_UNKNOWN = "unknown";
    public static final String STATUS_NOT_APPLICABLE = "not_applicable";

    /** 概率恒不可用的原因：没有权威来源（禁估算，禁拿历史数据顶替）。 */
    static final String PROBABILITY_UNAVAILABLE_REASON = "no_authoritative_probability_source";

    static final String SOURCE_SUBJECT = "candidate.mustSubjects vs userScoreDetail.subjectList";
    static final String SOURCE_TUITION = "candidate.tuitionPerYear vs userScoreDetail.tuitionRange";
    static final String SOURCE_HARD_INCLUDE_REGIONS =
            "candidate.provinceName/cityName vs constraintState.hardConstraints.mustIncludeRegions";
    static final String SOURCE_HARD_EXCLUDE_REGIONS =
            "candidate.provinceName/cityName vs constraintState.hardConstraints.mustExcludeRegions";
    static final String SOURCE_SOFT_PREFER_REGIONS =
            "candidate.provinceName/cityName vs constraintState.softPreferences.preferRegions";
    static final String SOURCE_SOFT_AVOID_REGIONS =
            "candidate.provinceName/cityName vs constraintState.softPreferences.avoidRegions";
    static final String SOURCE_PROFILE_POSITIVE_REGIONS =
            "candidate.provinceName/cityName vs profileState.explicitProfile.positiveRegions";
    static final String SOURCE_PROFILE_NEGATIVE_REGIONS =
            "candidate.provinceName/cityName vs profileState.explicitProfile.negativeRegions";
    static final String SOURCE_HARD_INCLUDE_MAJORS =
            "candidate.majorName/majorId vs constraintState.hardConstraints.mustIncludeMajors";
    static final String SOURCE_HARD_EXCLUDE_MAJORS =
            "candidate.majorName/majorId vs constraintState.hardConstraints.mustExcludeMajors";
    static final String SOURCE_SOFT_PREFER_MAJORS =
            "candidate.majorName vs constraintState.softPreferences.preferMajors";
    static final String SOURCE_SOFT_AVOID_MAJORS =
            "candidate.majorName vs constraintState.softPreferences.avoidMajors";
    static final String SOURCE_PROFILE_POSITIVE_MAJORS =
            "candidate.majorName vs profileState.explicitProfile.positiveMajors";
    static final String SOURCE_PROFILE_NEGATIVE_MAJORS =
            "candidate.majorName vs profileState.explicitProfile.negativeMajors";
    static final String SOURCE_HARD_INCLUDE_SCHOOLS =
            "candidate.schoolName vs constraintState.hardConstraints.mustIncludeSchools";
    static final String SOURCE_HARD_EXCLUDE_SCHOOLS =
            "candidate.schoolName vs constraintState.hardConstraints.mustExcludeSchools";
    static final String SOURCE_SOFT_PREFER_SCHOOLS =
            "candidate.schoolName vs constraintState.softPreferences.preferSchools";
    static final String SOURCE_SOFT_AVOID_SCHOOLS =
            "candidate.schoolName vs constraintState.softPreferences.avoidSchools";
    static final String SOURCE_PROFILE_POSITIVE_SCHOOLS =
            "candidate.schoolName vs profileState.explicitProfile.positiveSchools";
    static final String SOURCE_PROFILE_NEGATIVE_SCHOOLS =
            "candidate.schoolName vs profileState.explicitProfile.negativeSchools";

    @Autowired
    private CandidatePreviewService candidatePreviewService;

    public CandidateFitExplainRes explain(Long tenantId, Long chatSessionId, CandidateFitExplainReq req) {
        CandidateFitExplainReq safeReq = req == null ? new CandidateFitExplainReq() : req;
        String entityId = trimToNull(safeReq.getEntityId());
        if (entityId == null) {
            throw new BusinessException(400, "entity_id_required");
        }

        CandidateFitExplainRes res = new CandidateFitExplainRes();
        res.setEntityId(entityId);

        CandidatePreviewService.ReadOnlyCandidatePool pool =
                candidatePreviewService.loadReadOnlyCandidatePool(tenantId, chatSessionId);
        res.setProfileVersion(pool.state == null ? null : pool.state.getVersion());
        res.getLimitations().addAll(pool.limitations);

        if (pool.items == null || pool.items.isEmpty()) {
            // 与预览/比较同一口径：来源不可用（FINISHED 会话 / 无志愿文件 / 空池）如实报，不 500。
            if (!res.getLimitations().contains(CandidatePreviewService.LIMITATION_SOURCE_UNAVAILABLE)) {
                res.getLimitations().add(CandidatePreviewService.LIMITATION_SOURCE_UNAVAILABLE);
            }
            return res;
        }

        CandidateItemDTO candidate = findCandidate(pool.items, entityId);
        if (candidate == null) {
            // 找不到就是找不到：空解释 + 原因，不编一条出来。
            res.getLimitations().add(LIMITATION_ENTITY_NOT_FOUND_PREFIX + entityId);
            return res;
        }

        res.setFound(true);
        res.setSchoolName(resolveSchoolName(candidate));
        res.setMajorName(candidate.getMajorName());
        res.setTier(candidate.getTier());
        res.setRisks(buildRisks(candidate));

        Context ctx = new Context(res, candidate, pool);
        explainSubjectRequirement(ctx);
        explainRegionPreference(ctx);
        explainMajorIntent(ctx);
        explainSchoolIntent(ctx);
        explainTuitionRange(ctx);
        crossCheckHardConstraints(ctx);
        return res;
    }

    /** 候选池行按 volunteerId 索引；同 id 多行时保留第一行（与预览/比较的实体语义一致）。 */
    private CandidateItemDTO findCandidate(List<CandidateItemDTO> items, String entityId) {
        for (CandidateItemDTO item : items) {
            if (item == null || Strings.isNullOrEmpty(item.getVolunteerId())) {
                continue;
            }
            if (entityId.equals(item.getVolunteerId().trim())) {
                return item;
            }
        }
        return null;
    }

    // ------------------------------------------------------------------
    // 风险区：候选行标志**逐字透传** + 事实陈述（不改写、不翻译、不推断）
    // ------------------------------------------------------------------

    private CandidateFitExplainRes.Risks buildRisks(CandidateItemDTO candidate) {
        CandidateFitExplainRes.Risks risks = new CandidateFitExplainRes.Risks();
        if (candidate.getRiskFlags() != null) {
            risks.getFlags().addAll(candidate.getRiskFlags());
        }
        if (candidate.getReasonCodes() != null) {
            risks.getReasonCodes().addAll(candidate.getReasonCodes());
        }
        if (!Strings.isNullOrEmpty(candidate.getTier())) {
            risks.getFacts().add(new CandidateFitExplainRes.RiskFact("tier", candidate.getTier()));
        }
        if (candidate.getRankInTier() != null) {
            risks.getFacts().add(new CandidateFitExplainRes.RiskFact(
                    "rankInTier", String.valueOf(candidate.getRankInTier())));
        }
        return risks;
    }

    // ------------------------------------------------------------------
    // 维度：选科要求
    // ------------------------------------------------------------------

    private void explainSubjectRequirement(Context ctx) {
        CandidateItemDTO candidate = ctx.candidate;
        List<String> rawRequirements = defaultList(candidate.getMustSubjects());
        List<String> parsed = new ArrayList<String>();
        boolean hadRawRequirement = false;
        for (String raw : rawRequirements) {
            String value = trimToNull(raw);
            if (value == null || value.contains("不限")) {
                continue;
            }
            hadRawRequirement = true;
            if (value.contains("或")) {
                // "物理或化学"是选一格式，本切片不强行求值：如实标注，不把"解析不了"说成"不满足"。
                addLimitation(ctx, LIMITATION_SUBJECT_REQUIREMENT_UNPARSED_PREFIX + value);
                continue;
            }
            List<String> one = parseSelectInfo(value);
            if (one.isEmpty()) {
                addLimitation(ctx, LIMITATION_SUBJECT_REQUIREMENT_UNPARSED_PREFIX + value);
                continue;
            }
            for (String subject : one) {
                if (!parsed.contains(subject)) {
                    parsed.add(subject);
                }
            }
        }
        if (!hadRawRequirement) {
            addDimension(ctx, DIM_SUBJECT_REQUIREMENT, STATUS_NOT_APPLICABLE,
                    "该候选行没有选科要求（mustSubjects 为空或原样为「不限」），本维度无可评估内容");
            return;
        }
        if (parsed.isEmpty()) {
            addDimension(ctx, DIM_SUBJECT_REQUIREMENT, STATUS_UNKNOWN,
                    "选科要求存在但原样无法解析（见 limitations），不硬猜是否满足");
            return;
        }

        List<String> userSubjects = userSubjectNames(ctx.scoreDetail());
        if (userSubjects.isEmpty()) {
            addLimitation(ctx, LIMITATION_PROFILE_FIELD_MISSING_PREFIX + "subjectList");
            addDimension(ctx, DIM_SUBJECT_REQUIREMENT, STATUS_UNKNOWN,
                    "档案缺选科（subjectList），选科要求「" + String.join("、", parsed) + "」无法核对");
            return;
        }

        if (userSubjects.containsAll(parsed)) {
            addDimension(ctx, DIM_SUBJECT_REQUIREMENT, STATUS_MATCHED,
                    "档案选科「" + String.join("、", userSubjects) + "」满足选科要求「"
                            + String.join("、", parsed) + "」");
            addMatched(ctx, DIM_SUBJECT_REQUIREMENT,
                    "选科要求「" + String.join("、", parsed) + "」已满足：档案选科「"
                            + String.join("、", userSubjects) + "」包含全部要求",
                    SOURCE_SUBJECT);
        } else {
            List<String> missing = new ArrayList<String>();
            for (String subject : parsed) {
                if (!userSubjects.contains(subject)) {
                    missing.add(subject);
                }
            }
            addDimension(ctx, DIM_SUBJECT_REQUIREMENT, STATUS_CONFLICT,
                    "选科要求「" + String.join("、", parsed) + "」未满足：档案选科缺「"
                            + String.join("、", missing) + "」");
        }
    }

    /**
     * 选科要求解析：与 {@code VolunteerFilterChain.parseSelectInfo} **同一套口径**
     * （"物和化"→[物理,化学]、单科缩写→全称、已是全称原样保留）。
     */
    static List<String> parseSelectInfo(String selectInfo) {
        List<String> required = new ArrayList<String>();
        String info = Strings.nullToEmpty(selectInfo).trim();
        if (info.isEmpty()) {
            return required;
        }
        if (info.contains("和")) {
            for (String part : info.split("和")) {
                addParsedSubject(required, part);
            }
        } else {
            addParsedSubject(required, info);
        }
        return required;
    }

    private static void addParsedSubject(List<String> required, String raw) {
        String fullName = convertSubjectAbbreviation(raw);
        if (!Strings.isNullOrEmpty(fullName) && !required.contains(fullName)) {
            required.add(fullName);
        }
    }

    private static String convertSubjectAbbreviation(String raw) {
        if (Strings.isNullOrEmpty(raw)) {
            return null;
        }
        String abbr = raw.trim();
        if ("物".equals(abbr)) {
            return "物理";
        }
        if ("化".equals(abbr)) {
            return "化学";
        }
        if ("生".equals(abbr)) {
            return "生物";
        }
        if ("政".equals(abbr)) {
            return "政治";
        }
        if ("史".equals(abbr)) {
            return "历史";
        }
        if ("地".equals(abbr)) {
            return "地理";
        }
        if (abbr.contains("物理") || abbr.contains("化学") || abbr.contains("生物")
                || abbr.contains("政治") || abbr.contains("历史") || abbr.contains("地理")) {
            return abbr;
        }
        return null;
    }

    /** 档案选科名：优先建会话时采集的 subjectList（name），退而取科目分数表的科名。 */
    private List<String> userSubjectNames(CreateSessionReq scoreDetail) {
        List<String> names = new ArrayList<String>();
        if (scoreDetail == null) {
            return names;
        }
        if (scoreDetail.getSubjectList() != null) {
            for (CreateSessionReq.SubjectItem item : scoreDetail.getSubjectList()) {
                if (item == null) {
                    continue;
                }
                String name = usableName(item.getName());
                if (name != null && !names.contains(name)) {
                    names.add(name);
                }
            }
        }
        if (names.isEmpty() && scoreDetail.getSubjectScoreList() != null) {
            for (CreateSessionReq.SubjectScore score : scoreDetail.getSubjectScoreList()) {
                if (score == null) {
                    continue;
                }
                String name = usableName(score.getSubjectName());
                if (name != null && !names.contains(name)) {
                    names.add(name);
                }
            }
        }
        return names;
    }

    private static String usableName(String value) {
        String name = trimToNull(value);
        return name == null || name.contains("?") ? null : name;
    }

    // ------------------------------------------------------------------
    // 维度：地域偏好
    // ------------------------------------------------------------------

    private void explainRegionPreference(Context ctx) {
        HardConstraintsDTO hard = ctx.hardConstraints();
        SoftPreferencesDTO soft = ctx.softPreferences();
        ExplicitProfileDTO profile = ctx.explicitProfile();

        RegionHits hardIncluded = evalRegionScope(ctx,
                hard == null ? null : hard.getMustIncludeRegions(),
                hard == null ? null : hard.getMustIncludeRegionIds(), true);
        RegionHits hardExcluded = evalRegionScope(ctx,
                hard == null ? null : hard.getMustExcludeRegions(),
                hard == null ? null : hard.getMustExcludeRegionIds(), true);
        RegionHits softPrefer = evalRegionScope(ctx,
                soft == null ? null : soft.getPreferRegions(), null, false);
        RegionHits softAvoid = evalRegionScope(ctx,
                soft == null ? null : soft.getAvoidRegions(), null, false);
        RegionHits profilePositive = evalRegionScope(ctx,
                profile == null ? null : profile.getPositiveRegions(), null, false);
        RegionHits profileNegative = evalRegionScope(ctx,
                profile == null ? null : profile.getNegativeRegions(), null, false);

        for (String hit : hardIncluded.scopeLabel()) {
            addMatched(ctx, DIM_REGION_PREFERENCE, "地域命中硬性要求「" + hit + "」", SOURCE_HARD_INCLUDE_REGIONS);
        }
        for (String hit : hardIncluded.idLabel()) {
            addMatched(ctx, DIM_REGION_PREFERENCE, "地域命中硬性要求（区域 ID " + hit + "）",
                    SOURCE_HARD_INCLUDE_REGIONS);
        }
        for (String hit : softPrefer.scopeLabel()) {
            addMatched(ctx, DIM_REGION_PREFERENCE, "地域命中偏好「" + hit + "」", SOURCE_SOFT_PREFER_REGIONS);
        }
        for (String hit : profilePositive.scopeLabel()) {
            addMatched(ctx, DIM_REGION_PREFERENCE, "地域命中意向「" + hit + "」", SOURCE_PROFILE_POSITIVE_REGIONS);
        }

        List<String> conflicts = new ArrayList<String>();
        conflicts.addAll(hardExcluded.scopeAndIdLabel());
        conflicts.addAll(softAvoid.scopeLabel());
        conflicts.addAll(profileNegative.scopeLabel());
        int matchedCount = hardIncluded.size() + softPrefer.size() + profilePositive.size();
        boolean anyPositive = hasAny(hard == null ? null : hard.getMustIncludeRegions())
                || hasAny(hard == null ? null : hard.getMustIncludeRegionIds())
                || hasAny(soft == null ? null : soft.getPreferRegions())
                || hasAny(profile == null ? null : profile.getPositiveRegions());
        boolean anyNegative = hasAny(hard == null ? null : hard.getMustExcludeRegions())
                || hasAny(hard == null ? null : hard.getMustExcludeRegionIds())
                || hasAny(soft == null ? null : soft.getAvoidRegions())
                || hasAny(profile == null ? null : profile.getNegativeRegions());

        if (!conflicts.isEmpty()) {
            addDimension(ctx, DIM_REGION_PREFERENCE, STATUS_CONFLICT,
                    "地域命中排除项「" + String.join("、", conflicts) + "」");
        } else if (matchedCount > 0) {
            addDimension(ctx, DIM_REGION_PREFERENCE, STATUS_MATCHED,
                    "地域命中 " + matchedCount + " 条偏好/要求（见 matched）");
        } else if (anyPositive) {
            addDimension(ctx, DIM_REGION_PREFERENCE, STATUS_NO_MATCH,
                    "已配置正向地域偏好，但该候选省份/城市均未命中");
        } else if (anyNegative) {
            addDimension(ctx, DIM_REGION_PREFERENCE, STATUS_NOT_APPLICABLE,
                    "未配置正向地域偏好；已配置的排除项未命中");
        } else {
            addDimension(ctx, DIM_REGION_PREFERENCE, STATUS_NOT_APPLICABLE,
                    "会话未配置地域偏好/约束，本维度无可评估内容");
        }
    }

    /** 一组地域范围求值结果：命中按"名字范围/区域 ID"两类分开，便于逐条写来源。 */
    static class RegionHits {
        final List<String> nameHits = new ArrayList<String>();
        final List<String> idHits = new ArrayList<String>();

        int size() {
            return nameHits.size() + idHits.size();
        }

        List<String> scopeLabel() {
            return nameHits;
        }

        List<String> idLabel() {
            return idHits;
        }

        List<String> scopeAndIdLabel() {
            List<String> all = new ArrayList<String>(nameHits);
            all.addAll(idHits);
            return all;
        }
    }

    /**
     * 对一组地域范围求值（**ID 优先、名字兜底**，与 {@code RepairCandidateEligibility}
     * 的区域口径一致）：硬约束两边都有 ID 时只按 ID 判；否则按名字（省/市/区域别名）。
     * 判不了的（只给 ID 而候选行无 ID）如实标 {@code candidate_field_missing}，返回空命中。
     */
    private RegionHits evalRegionScope(Context ctx, List<String> names, List<String> ids, boolean idFirst) {
        RegionHits hits = new RegionHits();
        List<String> safeIds = defaultList(ids);
        List<String> safeNames = defaultList(names);
        if (safeIds.isEmpty() && safeNames.isEmpty()) {
            return hits;
        }
        CandidateItemDTO candidate = ctx.candidate;
        boolean constraintHasIds = !safeIds.isEmpty();
        boolean candidateHasIds = candidate.getProvinceId() != null || candidate.getCityId() != null;
        if (idFirst && constraintHasIds && candidateHasIds) {
            for (String id : safeIds) {
                String value = trimToNull(id);
                if (value != null && (value.equals(candidate.getProvinceId()) || value.equals(candidate.getCityId()))) {
                    hits.idHits.add(value);
                }
            }
            return hits;
        }
        if (idFirst && constraintHasIds && !candidateHasIds && safeNames.isEmpty()) {
            // 约束只给了 ID、候选行没有区域 ID：没有可核对的一侧，如实标缺失，不猜。
            addLimitation(ctx, LIMITATION_CANDIDATE_FIELD_MISSING_PREFIX + "provinceId/cityId");
            return hits;
        }
        boolean candidateHasNames = !Strings.isNullOrEmpty(candidate.getProvinceName())
                || !Strings.isNullOrEmpty(candidate.getCityName());
        if (!candidateHasNames) {
            addLimitation(ctx, LIMITATION_CANDIDATE_FIELD_MISSING_PREFIX + "provinceName/cityName");
            return hits;
        }
        for (String name : safeNames) {
            String scope = trimToNull(name);
            if (scope == null) {
                continue;
            }
            if (regionNameHits(scope, candidate) && !hits.nameHits.contains(scope)) {
                hits.nameHits.add(scope);
            }
        }
        return hits;
    }

    private boolean regionNameHits(String scope, CandidateItemDTO candidate) {
        return RegionScopeSupport.sameRegionName(scope, candidate.getProvinceName())
                || RegionScopeSupport.sameRegionName(scope, candidate.getCityName())
                || RegionScopeSupport.matchesRegionScope(scope, candidate.getProvinceName(), candidate.getCityName());
    }

    // ------------------------------------------------------------------
    // 维度：专业意向 / 院校意向
    // ------------------------------------------------------------------

    private void explainMajorIntent(Context ctx) {
        HardConstraintsDTO hard = ctx.hardConstraints();
        SoftPreferencesDTO soft = ctx.softPreferences();
        ExplicitProfileDTO profile = ctx.explicitProfile();

        MajorHits hardIncluded = evalHardMajors(ctx,
                hard == null ? null : hard.getMustIncludeMajors(),
                hard == null ? null : hard.getMustIncludeMajorIds());
        MajorHits hardExcluded = evalHardMajors(ctx,
                hard == null ? null : hard.getMustExcludeMajors(),
                hard == null ? null : hard.getMustExcludeMajorIds());
        List<String> softPrefer = evalNameScope(ctx, soft == null ? null : soft.getPreferMajors(), true);
        List<String> softAvoid = evalNameScope(ctx, soft == null ? null : soft.getAvoidMajors(), true);
        List<String> profilePositive = evalNameScope(ctx, profile == null ? null : profile.getPositiveMajors(), true);
        List<String> profileNegative = evalNameScope(ctx, profile == null ? null : profile.getNegativeMajors(), true);

        for (String hit : hardIncluded.nameHits) {
            addMatched(ctx, DIM_MAJOR_INTENT, "专业命中硬性要求「" + hit + "」", SOURCE_HARD_INCLUDE_MAJORS);
        }
        for (String hit : hardIncluded.idHits) {
            addMatched(ctx, DIM_MAJOR_INTENT, "专业命中硬性要求（专业 ID " + hit + "）", SOURCE_HARD_INCLUDE_MAJORS);
        }
        for (String hit : softPrefer) {
            addMatched(ctx, DIM_MAJOR_INTENT, "专业命中偏好「" + hit + "」", SOURCE_SOFT_PREFER_MAJORS);
        }
        for (String hit : profilePositive) {
            addMatched(ctx, DIM_MAJOR_INTENT, "专业命中意向「" + hit + "」", SOURCE_PROFILE_POSITIVE_MAJORS);
        }

        List<String> conflicts = new ArrayList<String>();
        conflicts.addAll(hardExcluded.scopeAndIdLabel());
        conflicts.addAll(softAvoid);
        conflicts.addAll(profileNegative);
        int matchedCount = hardIncluded.size() + softPrefer.size() + profilePositive.size();
        boolean anyPositive = hasAny(hard == null ? null : hard.getMustIncludeMajors())
                || hasAny(hard == null ? null : hard.getMustIncludeMajorIds())
                || hasAny(soft == null ? null : soft.getPreferMajors())
                || hasAny(profile == null ? null : profile.getPositiveMajors());
        boolean anyNegative = hasAny(hard == null ? null : hard.getMustExcludeMajors())
                || hasAny(hard == null ? null : hard.getMustExcludeMajorIds())
                || hasAny(soft == null ? null : soft.getAvoidMajors())
                || hasAny(profile == null ? null : profile.getNegativeMajors());

        if (!conflicts.isEmpty()) {
            addDimension(ctx, DIM_MAJOR_INTENT, STATUS_CONFLICT,
                    "专业命中排除项「" + String.join("、", conflicts) + "」");
        } else if (matchedCount > 0) {
            addDimension(ctx, DIM_MAJOR_INTENT, STATUS_MATCHED,
                    "专业命中 " + matchedCount + " 条偏好/要求（见 matched）");
        } else if (anyPositive) {
            addDimension(ctx, DIM_MAJOR_INTENT, STATUS_NO_MATCH,
                    "已配置正向专业偏好，但该候选专业未命中");
        } else if (anyNegative) {
            addDimension(ctx, DIM_MAJOR_INTENT, STATUS_NOT_APPLICABLE,
                    "未配置正向专业偏好；已配置的排除项未命中");
        } else {
            addDimension(ctx, DIM_MAJOR_INTENT, STATUS_NOT_APPLICABLE,
                    "会话未配置专业偏好/约束，本维度无可评估内容");
        }
    }

    private void explainSchoolIntent(Context ctx) {
        HardConstraintsDTO hard = ctx.hardConstraints();
        SoftPreferencesDTO soft = ctx.softPreferences();
        ExplicitProfileDTO profile = ctx.explicitProfile();

        List<String> hardIncluded = evalNameScope(ctx, hard == null ? null : hard.getMustIncludeSchools(), false);
        List<String> hardExcluded = evalNameScope(ctx, hard == null ? null : hard.getMustExcludeSchools(), false);
        List<String> softPrefer = evalNameScope(ctx, soft == null ? null : soft.getPreferSchools(), false);
        List<String> softAvoid = evalNameScope(ctx, soft == null ? null : soft.getAvoidSchools(), false);
        List<String> profilePositive = evalNameScope(ctx, profile == null ? null : profile.getPositiveSchools(), false);
        List<String> profileNegative = evalNameScope(ctx, profile == null ? null : profile.getNegativeSchools(), false);

        for (String hit : hardIncluded) {
            addMatched(ctx, DIM_SCHOOL_INTENT, "院校命中硬性要求「" + hit + "」", SOURCE_HARD_INCLUDE_SCHOOLS);
        }
        for (String hit : softPrefer) {
            addMatched(ctx, DIM_SCHOOL_INTENT, "院校命中偏好「" + hit + "」", SOURCE_SOFT_PREFER_SCHOOLS);
        }
        for (String hit : profilePositive) {
            addMatched(ctx, DIM_SCHOOL_INTENT, "院校命中意向「" + hit + "」", SOURCE_PROFILE_POSITIVE_SCHOOLS);
        }

        List<String> conflicts = new ArrayList<String>();
        conflicts.addAll(hardExcluded);
        conflicts.addAll(softAvoid);
        conflicts.addAll(profileNegative);
        int matchedCount = hardIncluded.size() + softPrefer.size() + profilePositive.size();
        boolean anyPositive = hasAny(hard == null ? null : hard.getMustIncludeSchools())
                || hasAny(soft == null ? null : soft.getPreferSchools())
                || hasAny(profile == null ? null : profile.getPositiveSchools());
        boolean anyNegative = hasAny(hard == null ? null : hard.getMustExcludeSchools())
                || hasAny(soft == null ? null : soft.getAvoidSchools())
                || hasAny(profile == null ? null : profile.getNegativeSchools());

        if (!conflicts.isEmpty()) {
            addDimension(ctx, DIM_SCHOOL_INTENT, STATUS_CONFLICT,
                    "院校命中排除项「" + String.join("、", conflicts) + "」");
        } else if (matchedCount > 0) {
            addDimension(ctx, DIM_SCHOOL_INTENT, STATUS_MATCHED,
                    "院校命中 " + matchedCount + " 条偏好/要求（见 matched）");
        } else if (anyPositive) {
            addDimension(ctx, DIM_SCHOOL_INTENT, STATUS_NO_MATCH,
                    "已配置正向院校偏好，但该候选院校未命中");
        } else if (anyNegative) {
            addDimension(ctx, DIM_SCHOOL_INTENT, STATUS_NOT_APPLICABLE,
                    "未配置正向院校偏好；已配置的排除项未命中");
        } else {
            addDimension(ctx, DIM_SCHOOL_INTENT, STATUS_NOT_APPLICABLE,
                    "会话未配置院校偏好/约束，本维度无可评估内容");
        }
    }

    /** 一组专业要求求值结果（硬约束专用：ID 优先、名字兜底，含"判不了"标记）。 */
    static class MajorHits {
        final List<String> nameHits = new ArrayList<String>();
        final List<String> idHits = new ArrayList<String>();

        int size() {
            return nameHits.size() + idHits.size();
        }

        List<String> scopeAndIdLabel() {
            List<String> all = new ArrayList<String>(nameHits);
            all.addAll(idHits);
            return all;
        }
    }

    private MajorHits evalHardMajors(Context ctx, List<String> names, List<String> ids) {
        MajorHits hits = new MajorHits();
        List<String> safeIds = defaultList(ids);
        boolean constraintHasIds = !safeIds.isEmpty();
        boolean candidateHasId = hasMajorId(ctx.candidate.getMajorId());
        if (constraintHasIds && candidateHasId) {
            for (String id : safeIds) {
                String value = trimToNull(id);
                if (value != null && value.equals(ctx.candidate.getMajorId().trim()) && !hits.idHits.contains(value)) {
                    hits.idHits.add(value);
                }
            }
            return hits;
        }
        if (constraintHasIds && !candidateHasId && defaultList(names).isEmpty()) {
            // 约束只给了专业 ID、候选行是大类（"0"）或空：ID 判不了、名字也没有，如实标缺失。
            addLimitation(ctx, LIMITATION_CANDIDATE_FIELD_MISSING_PREFIX + "majorId");
            return hits;
        }
        hits.nameHits.addAll(evalNameScope(ctx, names, true));
        return hits;
    }

    /**
     * 一组"名字范围"（专业名或院校名）求值：命中即返回原值。
     *
     * <p>专业名用**双向子串**（"临床医学"必须能命中"临床医学(五年)"），但
     * {@code majorCategory}/{@code majorDiscipline} 只允许**整段相等（含范围侧尾缀容忍）**
     * （与 {@code RepairCandidateEligibility} 同口径：粗粒度分类用子串会放大成整个门类；
     * 尾缀容忍让"医学类"当"医学"用 ✓）。
     * 带标签的范围（"性质:985"）本切片不求值——如实标 {@code scope_label_not_evaluated}，
     * 不假装核过。</p>
     */
    private List<String> evalNameScope(Context ctx, List<String> values, boolean majorScope) {
        List<String> hits = new ArrayList<String>();
        for (String raw : defaultList(values)) {
            String scope = trimToNull(raw);
            if (scope == null) {
                continue;
            }
            if (scope.contains(":") || scope.contains("：")) {
                addLimitation(ctx, LIMITATION_SCOPE_LABEL_NOT_EVALUATED_PREFIX + scope);
                continue;
            }
            boolean hit = majorScope
                    ? majorNameHits(scope, ctx.candidate)
                    : schoolNameHits(scope, ctx.candidate);
            if (hit && !hits.contains(scope)) {
                hits.add(scope);
            }
        }
        return hits;
    }

    private static boolean majorNameHits(String scope, CandidateItemDTO candidate) {
        return textMatches(candidate.getMajorName(), scope)
                || equalsTaxonomy(candidate.getMajorCategory(), scope)
                || equalsTaxonomy(candidate.getMajorDiscipline(), scope);
    }

    private static boolean schoolNameHits(String scope, CandidateItemDTO candidate) {
        return textMatches(resolveSchoolName(candidate), scope);
    }

    private static boolean hasMajorId(String majorId) {
        // "0"＝大类/试验班（没有单一专业身份）→ 按"缺 ID"处理（与 RepairCandidateEligibility 同口径）。
        return !Strings.isNullOrEmpty(majorId) && !"0".equals(majorId.trim());
    }

    private static boolean textMatches(String field, String pattern) {
        if (Strings.isNullOrEmpty(field) || Strings.isNullOrEmpty(pattern)) {
            return false;
        }
        String normalizedField = field.trim().toLowerCase(Locale.ROOT);
        String normalizedPattern = pattern.trim().toLowerCase(Locale.ROOT);
        return normalizedField.contains(normalizedPattern) || normalizedPattern.contains(normalizedField);
    }

    private static boolean equalsTaxonomy(String field, String scope) {
        // 与筛选侧**同一个实现** ✓（含范围侧尾缀容忍 ✓）：口径分叉时解释会与筛选互相打架 ✗
        //（"筛的时候留下、解释却说不在范围里"✓）。
        return RepairCandidateEligibility.equalsTaxonomy(field, scope);
    }

    // ------------------------------------------------------------------
    // 维度：学费区间
    // ------------------------------------------------------------------

    private void explainTuitionRange(Context ctx) {
        CreateSessionReq scoreDetail = ctx.scoreDetail();
        CreateSessionReq.TuitionRange range = scoreDetail == null ? null : scoreDetail.getTuitionRange();
        if (range == null || (range.getMin() == null && range.getMax() == null)) {
            addDimension(ctx, DIM_TUITION_RANGE, STATUS_NOT_APPLICABLE,
                    "会话未设置学费区间（tuitionRange），本维度无可评估内容");
            return;
        }
        Integer tuition = ctx.candidate.getTuitionPerYear();
        if (tuition == null) {
            addLimitation(ctx, LIMITATION_CANDIDATE_FIELD_MISSING_PREFIX + "tuitionPerYear");
            addDimension(ctx, DIM_TUITION_RANGE, STATUS_UNKNOWN,
                    "候选行缺学费（tuitionPerYear），无法与区间核对");
            return;
        }
        String rangeText = (range.getMin() == null ? "不限" : range.getMin() + " 元/年")
                + " – " + (range.getMax() == null ? "不限" : range.getMax() + " 元/年");
        boolean below = range.getMin() != null && tuition < range.getMin();
        boolean above = range.getMax() != null && tuition > range.getMax();
        if (!below && !above) {
            addDimension(ctx, DIM_TUITION_RANGE, STATUS_MATCHED,
                    "学费 " + tuition + " 元/年在用户区间（" + rangeText + "）内");
            addMatched(ctx, DIM_TUITION_RANGE,
                    "学费 " + tuition + " 元/年在区间（" + rangeText + "）内", SOURCE_TUITION);
        } else {
            addDimension(ctx, DIM_TUITION_RANGE, STATUS_NO_MATCH,
                    "学费 " + tuition + " 元/年不在用户区间（" + rangeText + "）内");
        }
    }

    // ------------------------------------------------------------------
    // 硬约束聚合交叉核对：逐维度说得出冲突，才叫"解释清楚了"
    // ------------------------------------------------------------------

    private void crossCheckHardConstraints(Context ctx) {
        PlanningStateDTO state = ctx.pool.state;
        if (state == null || !RepairCandidateEligibility.hasConfirmedHardConstraints(state)) {
            return;
        }
        if (RepairCandidateEligibility.isEligibleForConfirmedHardConstraints(ctx.candidate, state)) {
            return;
        }
        boolean conflictAttributed = false;
        for (CandidateFitExplainRes.Dimension dimension : ctx.res.getFitDimensions()) {
            if (STATUS_CONFLICT.equals(dimension.getStatus())) {
                conflictAttributed = true;
                break;
            }
        }
        if (!conflictAttributed) {
            // 聚合判定说不合格，但没有任何一个维度归因到冲突项：解释不完整是事实，如实说。
            addLimitation(ctx, LIMITATION_HARD_CONSTRAINTS_CONFLICT_UNATTRIBUTED);
        }
    }

    // ------------------------------------------------------------------
    // 小工具
    // ------------------------------------------------------------------

    private void addDimension(Context ctx, String dimension, String status, String detail) {
        CandidateFitExplainRes.Dimension item = new CandidateFitExplainRes.Dimension();
        item.setDimension(dimension);
        item.setStatus(status);
        item.setDetail(detail);
        ctx.res.getFitDimensions().add(item);
    }

    private void addMatched(Context ctx, String dimension, String statement, String source) {
        CandidateFitExplainRes.MatchedPoint point = new CandidateFitExplainRes.MatchedPoint();
        point.setDimension(dimension);
        point.setStatement(statement);
        point.setSource(source);
        ctx.res.getMatched().add(point);
    }

    private void addLimitation(Context ctx, String limitation) {
        if (!Strings.isNullOrEmpty(limitation) && !ctx.res.getLimitations().contains(limitation)) {
            ctx.res.getLimitations().add(limitation);
        }
    }

    private static boolean hasAny(List<String> values) {
        if (values == null) {
            return false;
        }
        for (String value : values) {
            if (!Strings.isNullOrEmpty(value) && !value.trim().isEmpty()) {
                return true;
            }
        }
        return false;
    }

    private static <T> List<T> defaultList(List<T> values) {
        return values == null ? Lists.newArrayList() : values;
    }

    private static String resolveSchoolName(CandidateItemDTO candidate) {
        return Strings.isNullOrEmpty(candidate.getDisplaySchoolName())
                ? candidate.getSchoolName() : candidate.getDisplaySchoolName();
    }

    private static String trimToNull(String value) {
        if (value == null) {
            return null;
        }
        String trimmed = value.trim();
        return trimmed.isEmpty() ? null : trimmed;
    }

    /** 一次解释的上下文：候选行 + 只读载入的会话状态（含 userScoreDetail）。 */
    private static class Context {
        final CandidateFitExplainRes res;
        final CandidateItemDTO candidate;
        final CandidatePreviewService.ReadOnlyCandidatePool pool;

        Context(CandidateFitExplainRes res, CandidateItemDTO candidate,
                CandidatePreviewService.ReadOnlyCandidatePool pool) {
            this.res = res;
            this.candidate = candidate;
            this.pool = pool;
        }

        CreateSessionReq scoreDetail() {
            return pool.response == null ? null : pool.response.getUserScoreDetail();
        }

        HardConstraintsDTO hardConstraints() {
            ConstraintStateDTO constraintState = pool.state == null ? null : pool.state.getConstraintState();
            return constraintState == null ? null : constraintState.getHardConstraints();
        }

        SoftPreferencesDTO softPreferences() {
            ConstraintStateDTO constraintState = pool.state == null ? null : pool.state.getConstraintState();
            return constraintState == null ? null : constraintState.getSoftPreferences();
        }

        ExplicitProfileDTO explicitProfile() {
            ProfileStateDTO profileState = pool.state == null ? null : pool.state.getProfileState();
            return profileState == null ? null : profileState.getExplicitProfile();
        }
    }
}
