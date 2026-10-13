package com.ytell.zhiyuan.service.biz;

import com.alibaba.fastjson.JSONObject;
import com.google.common.base.Strings;
import com.google.common.collect.Lists;
import com.ytell.zhiyuan.common.constants.ChatSessionExtraDataConstants;
import com.ytell.zhiyuan.common.exception.BusinessException;
import com.ytell.zhiyuan.common.util.ExcelUtil;
import com.ytell.zhiyuan.manager.MajorExtraDataManager;
import com.ytell.zhiyuan.manager.SchoolManager;
import com.ytell.zhiyuan.model.dto.CreateSessionReq;
import com.ytell.zhiyuan.model.dto.UserProfileData;
import com.ytell.zhiyuan.model.dto.inner.PendingConfirmationRes;
import com.ytell.zhiyuan.model.dto.inner.PendingConfirmationUpsertReq;
import com.ytell.zhiyuan.model.dto.inner.VolunteerRecommendListResponse;
import com.ytell.zhiyuan.model.dto.inner.VolunteerSourceDataSnapshot;
import com.ytell.zhiyuan.model.dto.planning.*;
import com.ytell.zhiyuan.model.entity.biz.ChatSession;
import com.ytell.zhiyuan.model.entity.biz.ChatSessionExtraData;
import com.ytell.zhiyuan.model.entity.biz.PlanningDataFreshnessScheduleEntity;
import com.ytell.zhiyuan.model.enums.DataType;
import com.ytell.zhiyuan.model.enums.VolunteerModel;
import com.ytell.zhiyuan.model.vo.MajorExtraDataVO;
import com.ytell.zhiyuan.model.vo.SchoolVO;
import com.ytell.zhiyuan.service.shared.PlanningBehaviorEventSharedService;
import com.ytell.zhiyuan.service.shared.PlanningDataFreshnessScheduleSharedService;
import com.ytell.zhiyuan.service.shared.ChatSessionExtraDataSharedService;
import com.ytell.zhiyuan.service.shared.ChatSessionSharedService;
import com.ytell.zhiyuan.service.volunteer.VolunteerIntervalService;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.BeanUtils;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.OffsetDateTime;
import java.time.ZoneId;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.Date;
import java.util.Comparator;
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import java.util.UUID;
import java.util.function.Consumer;
import java.util.stream.Collectors;

@Slf4j
@Service
public class PlanningStateService {

    private static final String OTHER_MAJOR_FILTER_LABEL = "其他专业";
    private static final int DEFAULT_INITIAL_PLAN_TARGET_COUNT = 45;

    /** overlay 合并落盘的 CAS 重试次数（每次都是"重读最新行→合并→CAS"，全输就放弃，下次读再刷）。 */
    private static final int RECOMMENDATION_OVERLAY_PERSIST_ATTEMPTS = 3;

    private static final String COOPERATIVE_SCHOOL_TAG = "\u4e2d\u5916\u5408\u4f5c";
    private static final String COOPERATIVE_MAJOR_TAG = "\u4e2d\u5916\u5408\u4f5c\u529e\u5b66";

    private static final Set<String> MACRO_REGION_TAGS = new HashSet<String>() {{
        add("华东");
        add("华北");
        add("华南");
        add("华中");
        add("西南");
        add("西北");
        add("东北");
        add("华东地区");
        add("华北地区");
        add("华南地区");
        add("华中地区");
        add("西南地区");
        add("西北地区");
        add("东北地区");
        add("京津冀");
        add("长三角");
        add("珠三角");
    }};

    private static final Set<String> SCHOOL_CATEGORY_TAGS = new HashSet<String>() {{
        add("综合");
        add("理工");
        add("师范");
        add("财经");
        add("政法");
        add("医药");
        add("语言");
        add("农林");
        add("民族");
        add("体育");
        add("艺术");
        add("军事");
    }};

    private static final Set<String> SCHOOL_NATURE_TAGS = new HashSet<String>() {{
        add("公办");
        add("民办");
        add("中外合作");
    }};

    private static final Set<String> SCHOOL_FEATURE_TAGS = new HashSet<String>() {{
        add("教育部直属");
        add("中央部委");
        add("省会城市");
    }};

    private static final Set<String> SCHOOL_LEVEL_TAGS = new HashSet<String>() {{
        add("本科");
        add("专科");
        add("985");
        add("211");
        add("双一流");
        add("强基");
        add("保研");
        add("国重点");
        add("省重点");
        add("双高计划");
        add("国家级示范");
        add("国家级骨干");
        add("职业本科");
    }};

    private static final Set<String> ADMISSION_TYPE_TAGS = new HashSet<String>() {{
        add("普通类");
        add("中外合作办学");
        add("地方专项");
        add("国家专项");
        add("特色计划");
        add("少数民族");
        add("预科");
        add("定向");
        add("试验班");
        add("实验班");
        add("师范专业");
        add("首年招生");
    }};

    private static final Set<String> CONSTRAINT_LIMIT_TAGS = new HashSet<String>() {{
        add("色盲色弱");
        add("语种要求");
        add("单科成绩");
        add("性别要求");
    }};

    private static final Set<String> MAJOR_INTENT_EXPLANATION_TAGS = new HashSet<String>() {{
        add("意向专业");
        add("意向专业类");
        add("非意向专业");
        add("非意向专业类");
    }};

    @Autowired
    private ChatSessionExtraDataSharedService chatSessionExtraDataSharedService;

    @Autowired
    private ChatSessionSharedService chatSessionSharedService;

    @Autowired
    private PlanningBehaviorEventSharedService planningBehaviorEventSharedService;

    @Autowired
    private PlanningDataFreshnessScheduleSharedService planningDataFreshnessScheduleSharedService;

    @Autowired
    private VolunteerBizService volunteerBizService;

    @Autowired
    private VolunteerSourceDataSyncService volunteerSourceDataSyncService;

    @Autowired
    private VolunteerDataProvider volunteerDataProvider;

    @Autowired
    private PlanningExcelExportBuilder planningExcelExportBuilder;

    @Autowired
    private VolunteerIntervalService volunteerIntervalService;

    @Autowired
    private MajorExtraDataManager majorExtraDataManager;

    @Autowired(required = false)
    private SchoolManager schoolManager;

    @Autowired
    private PendingConfirmationBizService pendingConfirmationBizService;

    @Autowired
    private ConversationProposalRequestService conversationProposalRequestService;

    public PlanningStateDTO getPlanningState(Long chatSessionId) {
        PlanningStateDTO state = loadPlanningState(chatSessionId);
        state.setSessionId(chatSessionId);
        enrichCandidateMajorTaxonomyFields(state.getCandidatePoolState() == null
                ? null : state.getCandidatePoolState().getItems());
        normalizeMajorGroupUnitMetadata(state);
        enrichReviewMetadata(state.getReviewState());
        normalizeReviewReasonCodes(buildReviewReasonAnalysisState(state), state.getReviewState());
        enrichPlanAdjustmentMetadata(state.getPlanAdjustmentState());
        return state;
    }

    public PlanningStateSummaryDTO getPlanningStateSummary(Long chatSessionId) {
        PlanningStateDTO state = getPlanningState(chatSessionId);
        PlanningStateSummaryDTO summary = new PlanningStateSummaryDTO();
        summary.setSessionId(chatSessionId);
        summary.setVersion(state.getVersion());
        summary.setPhase(state.getPhase());
        summary.setStaleFlags(state.getStaleFlags());
        return summary;
    }

    public PlanningWorkspaceStateRes getPlanningWorkspaceState(Long chatSessionId) {
        PlanningStateDTO state = getPlanningState(chatSessionId);
        return buildPlanningWorkspaceStateRes(state);
    }

    public PlanningWorkspaceStateRes getPlanningWorkspaceState(Long tenantId, Long chatSessionId) {
        PlanningStateDTO state = getPlanningState(chatSessionId);
        touchDataFreshnessSchedule(tenantId, chatSessionId, state, true, false);
        return buildPlanningWorkspaceStateRes(tenantId, state);
    }

    public PlanningWorkspaceStateRes buildPlanningWorkspaceStateRes(PlanningStateDTO state) {
        return buildPlanningWorkspaceStateRes(null, state);
    }

    public PlanningWorkspaceStateRes buildPlanningWorkspaceStateRes(Long tenantId, PlanningStateDTO state) {
        PlanningWorkspaceStateRes res = new PlanningWorkspaceStateRes();
        res.setSessionId(state.getSessionId());
        res.setVersion(state.getVersion());
        res.setPhase(state.getPhase());
        res.setStaleFlags(state.getStaleFlags());
        res.setStudentSummary(buildStudentPlanningSummary(state));
        res.setProfileState(state.getProfileState());
        res.setConstraintState(state.getConstraintState());
        res.setDataFreshnessState(mergeScheduleDataFreshnessState(tenantId, state));
        res.setPlanGenerationState(state.getPlanGenerationState());
        res.setInitialRecommendationState(state.getInitialRecommendationState());
        res.setCandidatePoolState(buildWorkspaceCandidatePoolState(state));
        res.setCandidateViewState(state.getCandidateViewState());
        res.setWorkingPlanState(state.getWorkingPlanState());
        res.setOrderedPlanState(state.getOrderedPlanState());
        res.setReviewState(state.getReviewState());
        res.setOperationLogs(state.getOperationLogs());
        res.setWorkflowStatus(PlanningWorkflowStatusBuilder.build(state, findLatestExportBehaviorEvent(state)));
        return res;
    }

    private StudentPlanningSummaryDTO buildStudentPlanningSummary(PlanningStateDTO state) {
        StudentPlanningSummaryDTO summary = new StudentPlanningSummaryDTO();
        CreateSessionReq scoreDetail = loadScoreDetail(state.getSessionId());
        if (scoreDetail == null) {
            CandidatePoolStateDTO candidatePoolState = state.getCandidatePoolState();
            if (candidatePoolState != null) {
                summary.setScore(candidatePoolState.getUserScore());
                summary.setBatchScore(candidatePoolState.getBatchScore());
                summary.setProvinceName(candidatePoolState.getSourceProvinceName());
            }
            summary.setStrengthSubjects(resolveStrengthSubjects(state, null));
            return summary;
        }
        summary.setSex(formatSex(scoreDetail.getSex()));
        summary.setExamYear(scoreDetail.getExamYear());
        summary.setScore(scoreDetail.getTotalScore());
        summary.setRank(scoreDetail.getTotalScorePos());
        if (scoreDetail.getBatch() != null) {
            summary.setBatchName(defaultString(scoreDetail.getBatch().getName()));
            if (scoreDetail.getBatch().getScore() != null) {
                summary.setBatchScore(Math.round(scoreDetail.getBatch().getScore()));
            }
        }
        if (scoreDetail.getProvince() != null) {
            summary.setProvinceName(defaultString(scoreDetail.getProvince().getName()));
        }
        summary.setSubjects(resolveSubjectNames(scoreDetail.getSubjectList()));
        summary.setStrengthSubjects(resolveStrengthSubjects(state, scoreDetail));
        return summary;
    }

    private String formatSex(CreateSessionReq.Sex sex) {
        if (sex == null) {
            return "";
        }
        String name = defaultString(sex.getName());
        if (!Strings.isNullOrEmpty(name)) {
            return name;
        }
        String code = defaultString(sex.getCode()).toLowerCase(Locale.ROOT);
        if ("male".equals(code) || "m".equals(code) || "1".equals(code) || "男".equals(code)) {
            return "男";
        }
        if ("female".equals(code) || "f".equals(code) || "2".equals(code) || "女".equals(code)) {
            return "女";
        }
        return defaultString(sex.getCode());
    }

    private List<String> resolveSubjectNames(List<CreateSessionReq.SubjectItem> subjectList) {
        if (subjectList == null) {
            return Lists.newArrayList();
        }
        return subjectList.stream()
                .filter(Objects::nonNull)
                .map(CreateSessionReq.SubjectItem::getName)
                .filter(name -> !Strings.isNullOrEmpty(name))
                .distinct()
                .collect(Collectors.toList());
    }

    private List<String> resolveStrengthSubjects(PlanningStateDTO state, CreateSessionReq scoreDetail) {
        List<String> stateProvided = Lists.newArrayList();
        if (state != null
                && state.getProfileState() != null
                && state.getProfileState().getExplicitProfile() != null
                && state.getProfileState().getExplicitProfile().getStrengthSubjects() != null) {
            stateProvided.addAll(state.getProfileState().getExplicitProfile().getStrengthSubjects());
        }
        // 历史 legacy 导入曾把中文写坏成 '??' 占位（实测 10041972：状态里是 ["??"]，
        // 而当前成绩行里是 物理/化学）。占位不是学科名——状态里出现过占位时，整组回落到
        // 当前成绩行：先用 subjectName，名字不可用时按选科码（如安徽 3+1+2 的 01/05/06）回查。
        boolean hasPlaceholder = stateProvided.stream().anyMatch(PlanningStateService::isPlaceholderOnly);
        List<String> fromState = stateProvided.stream()
                .filter(PlanningStateService::isUsableName)
                .distinct()
                .collect(Collectors.toList());
        List<String> fromScoreDetail = scoreDetail == null
                ? Lists.newArrayList()
                : extractStrengthSubjectNames(scoreDetail.getStrengthSubjectList(), scoreDetail);
        if (hasPlaceholder && !fromScoreDetail.isEmpty()) {
            return fromScoreDetail;
        }
        return fromState.isEmpty() ? fromScoreDetail : fromState;
    }

    /**
     * '??' 占位判定：legacy 源里的中文被写坏时留下的只由问号/空白组成的值
     * （实测状态里的 "??"、"???"——字符数还等于原文汉字数）。不是真实名称，读路径按"缺"处理。
     */
    private static boolean isPlaceholderOnly(String value) {
        if (Strings.isNullOrEmpty(value)) {
            return false;
        }
        for (int i = 0; i < value.length(); i++) {
            char c = value.charAt(i);
            if (c != '?' && c != '？' && !Character.isWhitespace(c)) {
                return false;
            }
        }
        return true;
    }

    private static boolean isUsableName(String value) {
        return !Strings.isNullOrEmpty(value) && !isPlaceholderOnly(value);
    }

    /**
     * 从优势学科列表解析名称：subjectName 可用直接用；是 '??' 占位或缺名字时，
     * 按选科码回查选科表 / 科目分数表里的名称（覆盖 3+1+2 省份只给代码 01/05/06 的口径）。
     */
    private List<String> extractStrengthSubjectNames(List<CreateSessionReq.SubjectScore> strengthSubjectList,
                                                     CreateSessionReq scoreDetail) {
        List<String> names = Lists.newArrayList();
        if (strengthSubjectList == null) {
            return names;
        }
        for (CreateSessionReq.SubjectScore strengthSubject : strengthSubjectList) {
            if (strengthSubject == null) {
                continue;
            }
            String name = strengthSubject.getSubjectName();
            if (!isUsableName(name)) {
                name = resolveSubjectNameByCode(scoreDetail, strengthSubject.getSubject());
            }
            if (isUsableName(name) && !names.contains(name)) {
                names.add(name);
            }
        }
        return names;
    }

    /**
     * 选科码 → 名称：先查建会话时采集的选科表（subjectList.value=码，如 01 物理），
     * 再查科目分数表（subjectScoreList.subject=码）。两处名称同样可能是 '??' 占位，跳过。
     */
    private String resolveSubjectNameByCode(CreateSessionReq scoreDetail, String subjectCode) {
        if (scoreDetail == null || Strings.isNullOrEmpty(subjectCode)) {
            return null;
        }
        if (scoreDetail.getSubjectList() != null) {
            for (CreateSessionReq.SubjectItem subjectItem : scoreDetail.getSubjectList()) {
                if (subjectItem != null && subjectCode.equals(subjectItem.getValue())
                        && isUsableName(subjectItem.getName())) {
                    return subjectItem.getName();
                }
            }
        }
        if (scoreDetail.getSubjectScoreList() != null) {
            for (CreateSessionReq.SubjectScore subjectScore : scoreDetail.getSubjectScoreList()) {
                if (subjectScore != null && subjectCode.equals(subjectScore.getSubject())
                        && isUsableName(subjectScore.getSubjectName())) {
                    return subjectScore.getSubjectName();
                }
            }
        }
        return null;
    }

    private CandidatePoolStateDTO buildWorkspaceCandidatePoolState(PlanningStateDTO state) {
        CandidatePoolStateDTO target = new CandidatePoolStateDTO();
        CandidatePoolStateDTO source = state == null ? null : state.getCandidatePoolState();
        if (source == null) {
            return target;
        }
        target.setGeneratedAt(source.getGeneratedAt());
        target.setSourceVersion(source.getSourceVersion());
        target.setStatusCode(source.getStatusCode());
        target.setStatusMessage(source.getStatusMessage());
        target.setRiskHints(source.getRiskHints());
        target.setRequiredCount(source.getRequiredCount());
        target.setRequiredTierCounts(source.getRequiredTierCounts());
        target.setRequiredUnitCount(source.getRequiredUnitCount());
        target.setRequiredMajorCount(source.getRequiredMajorCount());
        target.setUserScore(source.getUserScore());
        target.setBatchScore(source.getBatchScore());
        target.setSourceProvinceName(source.getSourceProvinceName());
        target.setVolunteerModel(source.getVolunteerModel());
        target.setSourceSummary(source.getSourceSummary());
        target.setSummary(source.getSummary());
        List<WorkspaceCandidateRef> workspaceRefs = collectWorkspaceCandidateRefs(state);
        if (!workspaceRefs.isEmpty()) {
            CandidateResolver resolver = new CandidateResolver(mergeOverlayIntoCandidates(source.getItems(), state.getRecommendationOverlayState()));
            Map<String, CandidateItemDTO> workspaceCandidates = new LinkedHashMap<String, CandidateItemDTO>();
            for (WorkspaceCandidateRef ref : workspaceRefs) {
                CandidateItemDTO candidate = resolver.resolve(ref.toOrderedItem());
                CandidateItemDTO copy = copyCandidateForWorkspaceVolunteerId(candidate, ref.getVolunteerId());
                if (copy != null && !workspaceCandidates.containsKey(copy.getVolunteerId())) {
                    workspaceCandidates.put(copy.getVolunteerId(), copy);
                }
            }
            target.setItems(Lists.newArrayList(workspaceCandidates.values()));
        }
        return target;
    }

    private CandidateItemDTO copyCandidateForWorkspaceVolunteerId(CandidateItemDTO candidate, String volunteerId) {
        if (candidate == null) {
            return null;
        }
        CandidateItemDTO copy = JSONObject.parseObject(JSONObject.toJSONString(candidate), CandidateItemDTO.class);
        copy.setVolunteerId(volunteerId);
        return copy;
    }

    private List<WorkspaceCandidateRef> collectWorkspaceCandidateRefs(PlanningStateDTO state) {
        Map<String, WorkspaceCandidateRef> refs = new LinkedHashMap<String, WorkspaceCandidateRef>();
        if (state == null) {
            return Lists.newArrayList();
        }
        DraftPlanStateDTO draft = state.getDraftPlanState();
        for (DraftItemDTO item : defaultDraftItems(draft == null ? null : draft.getItems())) {
            addWorkspaceCandidateRef(refs, item.getVolunteerId(), item.getSchoolName(), item.getMajorName());
        }
        for (DraftUnitDTO unit : defaultDraftUnits(draft == null ? null : draft.getUnits())) {
            for (PlanningUnitMajorDTO major : defaultPlanningUnitMajors(unit.getMajorItems())) {
                addWorkspaceCandidateRef(refs, major.getVolunteerId(), unit.getSchoolName(), major.getMajorName());
            }
        }
        OrderedPlanStateDTO ordered = state.getOrderedPlanState();
        for (OrderedItemDTO item : defaultOrderedItems(ordered == null ? null : ordered.getItems())) {
            addWorkspaceCandidateRef(refs, item.getVolunteerId(), item.getSchoolName(), item.getMajorName());
        }
        for (OrderedUnitDTO unit : defaultOrderedUnits(ordered == null ? null : ordered.getUnits())) {
            for (PlanningUnitMajorDTO major : defaultPlanningUnitMajors(unit.getMajorItems())) {
                addWorkspaceCandidateRef(refs, major.getVolunteerId(), unit.getSchoolName(), major.getMajorName());
            }
        }
        return Lists.newArrayList(refs.values());
    }

    private void addWorkspaceCandidateRef(Map<String, WorkspaceCandidateRef> refs,
                                          String volunteerId,
                                          String schoolName,
                                          String majorName) {
        if (Strings.isNullOrEmpty(volunteerId) || refs.containsKey(volunteerId)) {
            return;
        }
        refs.put(volunteerId, new WorkspaceCandidateRef(volunteerId, schoolName, majorName));
    }

    public ProfileStateDTO getProfileState(Long chatSessionId) {
        return getPlanningState(chatSessionId).getProfileState();
    }

    public void initializeProfileState(Long chatSessionId, CreateSessionReq scoreDetail, UserProfileData userProfileData) {
        syncProfileStateFromLegacy(chatSessionId, scoreDetail, userProfileData, false);
    }

    public PlanningStateVersionDTO syncProfileStateFromLegacy(Long chatSessionId,
                                                              CreateSessionReq scoreDetail,
                                                              UserProfileData userProfileData,
                                                              boolean markStale) {
        PlanningStateDTO state = markStale ? loadPlanningState(chatSessionId) : loadPlanningState(chatSessionId, false);
        applyLegacyProfileHydration(state, scoreDetail, userProfileData);
        if (markStale) {
            return touchAndSavePreference(chatSessionId, state,
                    latest -> applyLegacyProfileHydration(latest, scoreDetail, userProfileData));
        }
        // A 类站点（纯内存、hydrate 只补空 ⇒ 重放安全）：输了重读重放 ≤3 次；
        // 这是会话初始化/画像补全的幂等补缺，耗尽后放弃落盘（下一次读/调用会重放），不响亮失败。
        boolean saved = saveWithReplay(chatSessionId, state, "sync_profile_legacy",
                latest -> applyLegacyProfileHydration(latest, scoreDetail, userProfileData));
        if (!saved) {
            logWriteCasSkipped(chatSessionId, "sync_profile_legacy", "attempts_exhausted");
        }
        return null;
    }

    /** syncProfileStateFromLegacy 的纯内存变换：hydrate 只补空 + 缺省候选视图（重放幂等）。 */
    private void applyLegacyProfileHydration(PlanningStateDTO state,
                                             CreateSessionReq scoreDetail,
                                             UserProfileData userProfileData) {
        hydrateProfileState(state.getProfileState(), scoreDetail, userProfileData);
        if (state.getCandidateViewState() == null) {
            state.setCandidateViewState(buildDefaultCandidateViewState(state.getProfileState()));
        }
    }

    /**
     * 空会话（draft）**同会话补录成绩**后刷新规划状态：版本 +1、候选池相关全部置 stale、
     * 并把候选池状态里冗余的成绩上下文换成新值。
     *
     * <p>三件事必须一起做，缺一不可：</p>
     * <ul>
     *   <li><b>版本 +1</b>：Python 网关按版本淘汰快照缓存（`GatewayService._store_snapshot`），
     *       版本不动时"补录后重读到的快照"和缓存里那张分不出来，前端也拿不到"状态变了"的信号；</li>
     *   <li><b>置 stale</b>：候选池的 userScore/batchScore/省份已经变了，
     *       旧候选、旧推荐、旧方案与审查结论都不再作数。走
     *       {@link ReviewInvalidationPolicy#markCandidatePoolDependentsStale}（与候选池刷新同一套失效面），
     *       再补上 `candidatePool`/`recommendationOverlay` 两个开关——它们是"重算"的入口；</li>
     *   <li><b>刷新候选池成绩上下文</b>：与 {@code buildCandidatePoolStateFromResponse}（1353-1358）
     *       写进去的是同一组字段，避免工作台上"分数是旧的、候选是新标的"这种自相矛盾。</li>
     * </ul>
     *
     * <p>画像用 {@code fillIfEmpty} 语义合并进 profileState（与 {@code syncProfileStateFromLegacy} 一致），
     * 不覆盖既有非空值。`preferenceChanged` 为 true 时额外按"偏好变更"失效（专家推荐/排序/审查）。</p>
     *
     * @return 刷新后的版本与失效标记，供接口回给前端
     */
    public PlanningStateVersionDTO applyScoreDetailUpdate(Long chatSessionId,
                                                          CreateSessionReq scoreDetail,
                                                          UserProfileData userProfileData,
                                                          boolean preferenceChanged) {
        PlanningStateDTO state = loadPlanningState(chatSessionId);
        // A 类站点（用户动作）：纯内存变换可重放（hydrate 只补空、置 stale 幂等），
        // 输了重读重放 ≤3；重试耗尽**响亮失败**——补录结果绝不静默丢。
        boolean saved = saveWithReplay(chatSessionId, state, "score_detail_update",
                latest -> applyScoreDetailUpdateMutation(latest, chatSessionId, scoreDetail, userProfileData, preferenceChanged));
        if (!saved) {
            throw writeCasConflict("成绩补录");
        }

        PlanningStateVersionDTO versionDTO = new PlanningStateVersionDTO();
        versionDTO.setVersion(state.getVersion());
        versionDTO.setStaleFlags(state.getStaleFlags());
        return versionDTO;
    }

    /** 补录的成绩/画像域字段 + 失效面（重放幂等：fillIfEmpty 与布尔置位）。 */
    private void applyScoreDetailUpdateMutation(PlanningStateDTO state,
                                                Long chatSessionId,
                                                CreateSessionReq scoreDetail,
                                                UserProfileData userProfileData,
                                                boolean preferenceChanged) {
        hydrateProfileState(state.getProfileState(), scoreDetail, userProfileData);
        if (state.getCandidateViewState() == null) {
            state.setCandidateViewState(buildDefaultCandidateViewState(state.getProfileState()));
        }
        refreshCandidatePoolScoreContext(state.getCandidatePoolState(), scoreDetail);

        state.setSessionId(chatSessionId);
        state.setVersion((state.getVersion() == null ? 0 : state.getVersion()) + 1);
        state.setPhase("profile_ready");
        state.getStaleFlags().setCandidatePool(true);
        state.getStaleFlags().setRecommendationOverlay(true);
        ReviewInvalidationPolicy.markCandidatePoolDependentsStale(state);
        if (preferenceChanged) {
            ReviewInvalidationPolicy.markPreferenceIntentStale(state);
        }
        state.getStaleFlags().setReasonCode("score_detail_updated");
        state.getStaleFlags().setMessage(preferenceChanged
                ? "成绩与报考意向已补录，候选池、专家推荐与当前方案需要重新计算。"
                : "成绩信息已补录，候选池、专家推荐与当前方案需要重新计算。");
    }

    /**
     * 把候选池状态里的成绩上下文（`userScore` / `batchScore` / `sourceProvinceName`）换成新成绩。
     * 字段与 `buildCandidatePoolStateFromResponse` 保持一致；候选条目本身不动，
     * 是否重算由 `staleFlags.candidatePool` 决定。
     */
    private void refreshCandidatePoolScoreContext(CandidatePoolStateDTO candidatePoolState,
                                                  CreateSessionReq scoreDetail) {
        if (candidatePoolState == null || scoreDetail == null) {
            return;
        }
        if (scoreDetail.getTotalScore() != null) {
            candidatePoolState.setUserScore(scoreDetail.getTotalScore());
        }
        if (scoreDetail.getBatch() != null && scoreDetail.getBatch().getScore() != null) {
            candidatePoolState.setBatchScore(Math.round(scoreDetail.getBatch().getScore()));
        }
        if (scoreDetail.getProvince() != null && !Strings.isNullOrEmpty(scoreDetail.getProvince().getName())) {
            candidatePoolState.setSourceProvinceName(scoreDetail.getProvince().getName());
        }
    }

    public CandidateViewStateDTO getCandidateViewState(Long chatSessionId) {
        PlanningStateDTO state = getPlanningState(chatSessionId);
        if (state.getCandidateViewState() == null) {
            // 读入口懒写：**只补缺**。CAS 输了（有并发写）先重读——别人已经补上就以库里的为准，不再写；
            // 还是缺就再试（≤3），耗尽也只是带着内存里补的默认视图返回（不覆盖任何并发写）。
            for (int attempt = 0; attempt < WRITE_CAS_ATTEMPTS; attempt++) {
                state.setCandidateViewState(buildDefaultCandidateViewState(state.getProfileState()));
                state.setSessionId(chatSessionId);
                if (savePlanningState(chatSessionId, state, "candidate_view_backfill")) {
                    return state.getCandidateViewState();
                }
                reloadPlanningState(chatSessionId, state);
                if (state.getCandidateViewState() != null) {
                    return state.getCandidateViewState();
                }
            }
            logWriteCasSkipped(chatSessionId, "candidate_view_backfill", "attempts_exhausted");
        }
        return state.getCandidateViewState();
    }

    public PlanningStateDTO updateCandidateViewState(Long chatSessionId, CandidateViewStateDTO req) {
        PlanningStateDTO state = loadPlanningState(chatSessionId);
        // A 类站点（用户动作）：把 req 的视图原样套到最新态（纯内存），输了重读重放 ≤3；
        // 重试耗尽**响亮失败**（40901 语义面）——用户的筛选视图变更绝不静默丢。
        boolean saved = saveWithReplay(chatSessionId, state, "candidate_view_update",
                latest -> applyCandidateViewStateUpdate(latest, req));
        if (!saved) {
            throw writeCasConflict("候选视图更新");
        }
        return state;
    }

    /** 候选视图变更（重放幂等：整字段赋值 + 幂等的失效面切换）。 */
    private void applyCandidateViewStateUpdate(PlanningStateDTO state, CandidateViewStateDTO req) {
        CandidateViewStateDTO previous = normalizeCandidateViewState(state.getCandidateViewState());
        CandidateViewStateDTO next = normalizeCandidateViewState(req);
        state.setCandidateViewState(next);
        boolean hardRegionChanged = syncHardRegionRequirementsFromCandidateViewChange(state, previous, next);
        if (hardRegionChanged) {
            ReviewInvalidationPolicy.markConstraintIntentStale(state);
        } else {
            ReviewInvalidationPolicy.markCandidateViewStale(state);
        }
        state.setVersion((state.getVersion() == null ? 0 : state.getVersion()) + 1);
    }

    public InitialRecommendationStateDTO getInitialRecommendationState(Long chatSessionId) {
        return getPlanningState(chatSessionId).getInitialRecommendationState();
    }

    public PlanningStateDTO generateInitialRecommendation(Long tenantId,
                                                          Long chatSessionId,
                                                          InitialRecommendationGenerateReq req) {
        PlanningStateDTO state = loadPlanningState(chatSessionId);
        normalizeCandidatePoolForPlanning(state);
        if (shouldRefreshRecommendationOverlay(state)) {
            // overlay 刷新自带 CAS 与重读合并，且会把 state 刷成落盘后的最新态
            refreshRecommendationOverlay(tenantId, chatSessionId, state);
        }
        // B+C 站点（overlay 刷新是外部拉取，不可重放整方法）：冲突时重读最新 → 以最新态**只重算**
        // 初始推荐域字段与 phase/version，不重拉上游。
        boolean saved = false;
        for (int attempt = 0; attempt < WRITE_CAS_ATTEMPTS; attempt++) {
            applyInitialRecommendationState(state, chatSessionId);
            if (savePlanningState(chatSessionId, state, "initial_recommendation")) {
                saved = true;
                break;
            }
            reloadPlanningState(chatSessionId, state);
            normalizeCandidatePoolForPlanning(state);
        }
        if (!saved) {
            throw writeCasConflict("初始推荐生成");
        }
        return state;
    }

    /** 初始推荐的域字段（纯派生，重放幂等；version 以最新为基 +1，允许跳号）。 */
    private void applyInitialRecommendationState(PlanningStateDTO state, Long chatSessionId) {
        state.setInitialRecommendationState(buildInitialRecommendationState(state));
        state.getStaleFlags().setInitialRecommendation(false);
        state.setSessionId(chatSessionId);
        state.setVersion((state.getVersion() == null ? 0 : state.getVersion()) + 1);
    }

    public PlanAdjustmentStateDTO getPlanAdjustmentState(Long chatSessionId) {
        return getPlanningState(chatSessionId).getPlanAdjustmentState();
    }

    public PlanAdjustmentStateDTO analyzePlanAdjustment(Long tenantId,
                                                        Long chatSessionId,
                                                        PlanAdjustmentAnalyzeReq req) {
        PlanningStateDTO state = loadPlanningState(chatSessionId);
        if (shouldRefreshRecommendationOverlay(state)) {
            refreshRecommendationOverlay(tenantId, chatSessionId, state);
        }
        // B+C 站点：调整建议是纯内存分析，冲突时以**最新态**重算（重放幂等）再 CAS ≤3
        boolean saved = saveWithReplay(chatSessionId, state, "plan_adjustment_analyze",
                latest -> applyPlanAdjustmentAnalysis(latest, chatSessionId, req));
        if (!saved) {
            throw writeCasConflict("方案调整分析");
        }
        return state.getPlanAdjustmentState();
    }

    /** 方案调整分析的域字段（纯内存重算，重放幂等）。 */
    private void applyPlanAdjustmentAnalysis(PlanningStateDTO state, Long chatSessionId, PlanAdjustmentAnalyzeReq req) {
        state.setPlanAdjustmentState(buildPlanAdjustmentState(state, req));
        state.getStaleFlags().setPlanAdjustment(false);
        state.setSessionId(chatSessionId);
        state.setVersion((state.getVersion() == null ? 0 : state.getVersion()) + 1);
    }

    public PlanningStateDTO applyPlanAdjustment(Long tenantId,
                                                Long chatSessionId,
                                                PlanAdjustmentApplyReq req) {
        throw new BusinessException(410, "方案调整应用入口已废弃，请使用 fix-proposals/apply 生成并应用可验证的修复建议");
    }

    public ConstraintStateDTO getConstraintState(Long chatSessionId) {
        return getPlanningState(chatSessionId).getConstraintState();
    }

    public DraftPlanStateDTO getWorkingPlanState(Long chatSessionId) {
        return getPlanningState(chatSessionId).getWorkingPlanState();
    }

    /**
     * @deprecated use {@link #getWorkingPlanState(Long)}
     */
    @Deprecated
    public DraftPlanStateDTO getDraftState(Long chatSessionId) {
        return getWorkingPlanState(chatSessionId);
    }

    public OrderedPlanStateDTO getOrderedPlanState(Long chatSessionId) {
        return getPlanningState(chatSessionId).getOrderedPlanState();
    }

    @Transactional(rollbackFor = Exception.class)
    public ExcelExportResult exportOrderedPlan(Long tenantId, Long chatSessionId) {
        PlanningStateDTO state = getPlanningState(chatSessionId);
        if (state.getOrderedPlanState() == null || state.getOrderedPlanState().getItems() == null
                || state.getOrderedPlanState().getItems().isEmpty()) {
            throw new BusinessException(400, "当前方案为空，无法导出，请先生成方案");
        }
        CreateSessionReq userScoreDetail = volunteerDataProvider.getUserScoreDetail(chatSessionId);
        PlanningExcelExportBuilder.PlanningExportData exportData = planningExcelExportBuilder.build(state, userScoreDetail);
        byte[] excelBytes = ExcelUtil.generateVolunteerExcel(
                userScoreDetail,
                exportData.getMainList(),
                Lists.<ExcelUtil.VolunteerExcelData>newArrayList(),
                exportData.isMajorGroupMode());
        PlanningBehaviorEventDTO exportEvent = buildBehaviorEvent(
                state,
                tenantId,
                chatSessionId,
                "plan_export",
                collectOrderedVolunteerIds(state),
                true);
        recordBehaviorEvent(state, exportEvent);
        // B 类站点（副作用=行为事件落库 + 生成 Excel，不可重放）：事件已单独落库，state 侧没有新改动
        // 需要合并；落盘改走 CAS——库里那行被并发改过就**不写**（旧快照不覆盖新行），导出照常返回。
        if (!savePlanningState(chatSessionId, state, "export_ordered_plan")) {
            logWriteCasSkipped(chatSessionId, "export_ordered_plan", "row_changed_under_us");
        }
        return new ExcelExportResult(excelBytes, generateExcelFileName(userScoreDetail));
    }

    public ReviewStateDTO getReviewState(Long chatSessionId) {
        return getPlanningState(chatSessionId).getReviewState();
    }

    public List<ReviewRuleMetadataDTO> listReviewRuleMetadata() {
        return ReviewRuleRegistry.list();
    }

    public FixProposalStateDTO generateFixProposals(Long tenantId, Long chatSessionId) {
        PlanningStateDTO state = loadPlanningState(chatSessionId);
        ReviewStateDTO reviewState = state.getReviewState();
        if (reviewState == null || reviewState.getChecks() == null || reviewState.getChecks().isEmpty()
                || Boolean.TRUE.equals(state.getStaleFlags().getReview())) {
            reviewState = runReview(tenantId, chatSessionId);
            state = loadPlanningState(chatSessionId);
        }
        enrichReviewMetadata(reviewState);
        PlanningStateDTO proposalAnalysisState = buildReviewReasonAnalysisState(state);
        normalizeReviewReasonCodes(proposalAnalysisState, reviewState);
        List<CandidateItemDTO> effectiveCandidates = resolveEffectiveCandidates(tenantId, chatSessionId, state, true);
        CompensationPreviewDTO compensationPreview = buildCompensationPreview(proposalAnalysisState, effectiveCandidates);
        FixProposalStateDTO proposalState = buildFixProposalState(proposalAnalysisState, reviewState, compensationPreview);
        return proposalState;
    }

    public FixProposalStateDTO generateUserGoalFixProposals(Long chatSessionId, UserGoalFixProposalReq req) {
        PlanningStateDTO state = loadPlanningState(chatSessionId);
        state.getCandidatePoolState().setItems(resolveCandidateFactsForProposalAnalysis(state));
        return UserGoalProposalBuilder.build(state, req);
    }

    /**
     * P2：把"用户复合目标预览"物化成**待确认**（pending）——写闭环的第一段。
     *
     * 与 {@link #generateUserGoalFixProposals} 的唯一区别就是这一步：那个只出预览（只读实例继续走它），
     * 这个把预览变成 pending，并在 pending 的 dataValue 里落下 **Java 产出的 operationId**——
     * 写闭环的幂等键，用户确认后 execute 必须原样复用它。网关侧取不到这个键会**拒绝执行**
     * （见 codex 网关 `conversation_actions._execute_claimed_command`），所以它必须由这里落下。
     * 快照会把 dataValue 原样暴露给网关（`activeProposal.data`），网关不需要自己记录。
     *
     * 幂等、supersede、并发防线都由 {@link ConversationProposalRequestService#prepareOnce} 承担：
     * 同一个 requestId 重放返回同一次结果（**同一个 operationId**）；并发只有一个能插进去；
     * 被后一次取代的预览明确回"请使用最新预览"（对应用户要在旧卡上确认的那类陈旧场景）。
     */
    public PrepareResultDTO prepareUserGoalProposal(Long tenantId, Long chatSessionId, String requestId,
                                                    String requestDigest, UserGoalFixProposalReq req) {
        PendingConfirmationRes active = pendingConfirmationBizService.getCurrent(tenantId, chatSessionId);
        String activePendingStatus = active == null ? null : active.getStatus();
        return conversationProposalRequestService.prepareOnce(
                tenantId, chatSessionId, requestId, requestDigest, activePendingStatus,
                () -> {
                    FixProposalStateDTO preview = generateUserGoalFixProposals(chatSessionId, req);
                    String operationId = UUID.randomUUID().toString().replace("-", "");
                    Map<String, Object> dataValue = new LinkedHashMap<String, Object>();
                    dataValue.put("operationId", operationId);
                    dataValue.put("proposalSource", "user_goal");
                    if (req != null) {
                        // `user_goal` 来源的提案在 apply 时**要求带上原始目标**
                        // （`PendingPlanningCommandBizService`："user_goal proposal requires userGoalRequest"）
                        // ——落进 pending 的 dataValue，确认时由网关原样透传。
                        dataValue.put("userGoalRequest", JSONObject.parseObject(JSONObject.toJSONString(req)));
                    }
                    if (preview != null) {
                        dataValue.put("sourceVersion", preview.getSourceVersion());
                        FixProposalDTO primary = primaryProposal(preview);
                        if (primary != null) {
                            dataValue.put("proposalId", primary.getProposalId());
                            // **canonical 三件套一并落下** ✓✓：apply 那条路上
                            // `RepairProposalApplyPolicy.validateCanonicalMetadata`（:95-100）
                            // 要求请求里**必须带**它们之一（除非提案是 legacy 那种），
                            // 而网关手上只有 dataValue（`activeProposal.data`）——
                            // 不落的话确认那一刻必然 `409 canonical Proposal 元数据缺失`，
                            // 卡上只显示"未生效"，看起来像写链坏了
                            // （2026-09-27 真栈实测）。空值不落：网关按"非空才透传"读。
                            putIfNotBlank(dataValue, "canonicalObjectiveDigest", primary.getCanonicalObjectiveDigest());
                            putIfNotBlank(dataValue, "solverVersion", primary.getSolverVersion());
                            putIfNotBlank(dataValue, "solverInputDigest", primary.getSolverInputDigest());
                        }
                    }
                    PendingConfirmationUpsertReq upsert = new PendingConfirmationUpsertReq();
                    upsert.setChatSessionId(chatSessionId);
                    // pendingId 由**调用方**给（`validateUpsert` 要求；服务不生成），
                    // 取值与 legacy 同一约定：uuid。同一个 requestId 重放时 work 不会再跑
                    // （prepareOnce 直接回放已存的结果），所以不会造出第二个 pending ✓。
                    upsert.setPendingId(UUID.randomUUID().toString());
                    upsert.setKind("plan_change_proposal");
                    upsert.setActionFamily("apply_plan_change_proposal");
                    upsert.setDataValue(dataValue);
                    // **CAS 修订号**（2026-10-07 F09 实测）：已有 pending 行时按修订号**替换**
                    // ——与补录成绩路径（`ChatSessionBizService#prepareScoreUpdateProposal`）同口径。
                    // 不传时 `upsert` 默认 0：第二次预览必 `40901 pending revision conflict:
                    // current=1 expected=0`，网关侧 `proposal_preview_unavailable`，新预览根本出不来
                    // （老卡也就无从被"取代"——F09 第二张卡永远缺席）。
                    upsert.setExpectedRevision(
                            active == null || active.getRevision() == null ? 0L : active.getRevision());
                    PendingConfirmationRes pending = pendingConfirmationBizService.upsert(tenantId, upsert);
                    return new ConversationProposalRequestService.PrepareOutcome(
                            pending == null ? null : pending.getPendingId(), operationId, preview);
                });
    }

    /** 主提案：预览里第一个 `ready` 的；一个都没有时退回第一条（执行侧还会再校验，不会错写）。 */
    private static FixProposalDTO primaryProposal(FixProposalStateDTO preview) {
        if (preview.getProposals() == null) {
            return null;
        }
        for (FixProposalDTO proposal : preview.getProposals()) {
            if (proposal != null && "ready".equals(proposal.getStatus())) {
                return proposal;
            }
        }
        return preview.getProposals().isEmpty() ? null : preview.getProposals().get(0);
    }

    /** 只在非空时落键：空串/null 落进去会让网关"带上了一个空的 canonical 元数据"，
     * 而 Java 侧的判据是"至少一个非空"，两边对同一个字段的理解必须一致。 */
    private static void putIfNotBlank(Map<String, Object> target, String key, String value) {
        if (!Strings.isNullOrEmpty(value)) {
            target.put(key, value);
        }
    }

    public ReviewWorkflowRunRes runReviewWorkflow(Long tenantId, Long chatSessionId) {
        ReviewStateDTO reviewState = runReview(tenantId, chatSessionId);
        FixProposalStateDTO fixProposalState = generateFixProposals(tenantId, chatSessionId);
        PlanningWorkspaceStateRes workspaceState = getPlanningWorkspaceState(chatSessionId);

        ReviewWorkflowRunRes res = new ReviewWorkflowRunRes();
        res.setStatus(ReviewWorkflowStatusResolver.resolveRunStatus(reviewState, fixProposalState));
        res.setSessionId(chatSessionId);
        res.setSourceVersion(workspaceState.getVersion());
        res.setReviewState(reviewState);
        res.setFixProposalState(fixProposalState);
        res.setWorkflowStatus(workspaceState.getWorkflowStatus());
        res.setWorkspaceState(workspaceState);
        return res;
    }

    public FixProposalApplyRes applyFixProposal(Long tenantId, Long chatSessionId, FixProposalApplyReq req) {
        FixProposalApplyReq safeReq = RepairProposalApplyPolicy.safeRequest(req);
        RepairProposalApplyPolicy.validateRequest(safeReq);
        if (RepairProposalTaxonomy.isUserGoalSource(safeReq.getProposalSource())) {
            return applyUserGoalFixProposal(tenantId, chatSessionId, safeReq);
        }
        PlanningStateDTO state = loadPlanningState(chatSessionId);
        RepairProposalApplyPolicy.validateStateVersionGuard(safeReq, state);
        RepairProposalApplyPolicy.ensureReviewReady(state);
        FixProposalStateDTO proposalState = generateFixProposals(tenantId, chatSessionId);
        FixProposalDTO proposal = RepairProposalStateBuilder.findProposal(proposalState, safeReq.getProposalId());
        if (proposal == null) {
            throw new BusinessException(404, "修复建议不存在或已失效");
        }
        RepairProposalApplyPolicy.validateProposalForApply(safeReq, proposal);

        state = loadPlanningState(chatSessionId);
        ReviewSummaryDTO beforeReviewSummary = state.getReviewState() == null ? null : state.getReviewState().getSummary();
        state = applySupportedFixProposalStrategy(tenantId, chatSessionId, safeReq, proposal, state);

        FixProposalApplyRes res = new FixProposalApplyRes();
        res.setStatus("applied");
        res.setMessage("已应用修复建议，并刷新当前方案状态");
        res.setProposal(proposal);
        res.setRepairReport(RepairReportBuilder.build(proposal, beforeReviewSummary, state));
        res.setState(state);
        return res;
    }

    private FixProposalApplyRes applyUserGoalFixProposal(Long tenantId, Long chatSessionId, FixProposalApplyReq req) {
        PlanningStateDTO state = loadPlanningState(chatSessionId);
        RepairProposalApplyPolicy.validateStateVersionGuard(req, state);
        UserGoalFixProposalReq userGoalRequest = req.getUserGoalRequest();
        if (userGoalRequest == null) {
            throw new BusinessException(400, "缺少用户目标调整请求");
        }
        userGoalRequest.setSourceVersionGuard(req.getSourceVersionGuard());
        FixProposalStateDTO proposalState = generateUserGoalFixProposals(chatSessionId, userGoalRequest);
        FixProposalDTO proposal = RepairProposalStateBuilder.findProposal(proposalState, req.getProposalId());
        if (proposal == null && !RepairProposalApplyPolicy.hasCanonicalMetadata(req)) {
            proposal = findReadyUserGoalProposalByStrategy(proposalState, userGoalRequest.getGoalType());
        }
        if (proposal == null) {
            throw new BusinessException(404, "调整预览不存在或已失效");
        }
        RepairProposalApplyPolicy.validateProposalForApply(req, proposal);

        state = loadPlanningState(chatSessionId);
        ReviewSummaryDTO beforeReviewSummary = state.getReviewState() == null ? null : state.getReviewState().getSummary();
        ensureWorkingPlanContainsOrderedPlanItems(state);
        applyUserGoalTargetToPlanningState(state, userGoalRequest, proposal);
        state = applySupportedFixProposalStrategy(tenantId, chatSessionId, req, proposal, state);

        FixProposalApplyRes res = new FixProposalApplyRes();
        res.setStatus("applied");
        res.setMessage("已按这次目标调整当前方案，并刷新当前方案状态");
        res.setProposal(proposal);
        res.setRepairReport(RepairReportBuilder.build(proposal, beforeReviewSummary, state));
        res.setState(state);
        return res;
    }

    private void applyUserGoalTargetToPlanningState(PlanningStateDTO state,
                                                     UserGoalFixProposalReq userGoalRequest,
                                                     FixProposalDTO proposal) {
        if (state == null || userGoalRequest == null || proposal == null) {
            return;
        }
        ProjectedHardRequirementSupport.persist(state, userGoalRequest.getRequirements());
        PriorityRuleSupport.persist(state, userGoalRequest.getPriorityRules());
        if (proposal.getTierQuotaChange() != null
                && Boolean.TRUE.equals(proposal.getTierQuotaChange().getStateChanged())) {
            TierAllocationSupport.persist(state,
                    proposal.getTierQuotaChange().getEffectiveGoal(),
                    proposal.getTierQuotaChange().getResolution());
        }
        if (!RepairProposalTaxonomy.Strategy.FILL_MISSING_COUNT.equals(
                RepairProposalTaxonomy.normalizeStrategy(proposal.getStrategy()))) {
            return;
        }
        Integer targetCount = userGoalRequest.getTargetCount();
        if (targetCount == null || targetCount <= 0) {
            throw new BusinessException(400, "补齐目标数量必须是大于 0 的整数");
        }
        if (state.getConstraintState() == null) {
            state.setConstraintState(new ConstraintStateDTO());
        }
        if (state.getConstraintState().getHardPlanningObjectives() == null) {
            state.getConstraintState().setHardPlanningObjectives(new HardPlanningObjectivesDTO());
        }
        state.getConstraintState().getHardPlanningObjectives().setSelectionTargetCount(targetCount);
        if (Boolean.FALSE.equals(userGoalRequest.getPersistTargetCount())) {
            return;
        }
        if (state.getCandidatePoolState() == null) {
            throw new BusinessException(400, "当前候选池不可用，不能应用补齐目标");
        }
        state.getCandidatePoolState().setRequiredCount(targetCount);
    }

    private FixProposalDTO findReadyUserGoalProposalByStrategy(FixProposalStateDTO proposalState, String goalType) {
        if (proposalState == null || proposalState.getProposals() == null || Strings.isNullOrEmpty(goalType)) {
            return null;
        }
        String targetStrategy = RepairProposalTaxonomy.normalizeStrategy(goalType);
        return proposalState.getProposals().stream()
                .filter(proposal -> RepairProposalTaxonomy.isUserGoalSource(proposal.getProposalSource()))
                .filter(proposal -> RepairProposalTaxonomy.isReadyStatus(proposal.getStatus()))
                .filter(RepairProposalApplyPolicy::isLegacyCanonicalProposal)
                .filter(proposal -> targetStrategy.equals(RepairProposalTaxonomy.normalizeStrategy(proposal.getStrategy())))
                .findFirst()
                .orElse(null);
    }

    private PlanningStateDTO applySupportedFixProposalStrategy(Long tenantId,
                                                               Long chatSessionId,
                                                               FixProposalApplyReq req,
                                                               FixProposalDTO proposal,
                                                               PlanningStateDTO state) {
        String strategy = RepairProposalTaxonomy.normalizeStrategy(proposal.getStrategy());
        if (RepairProposalTaxonomy.Strategy.SORT_BY_PROBABILITY.equals(strategy)) {
            OrderedPlanSortReq sortReq = new OrderedPlanSortReq();
            sortReq.setSortField("admissionRatio");
            state = sortOrderedPlan(chatSessionId, sortReq);
            return rerunReviewAfterFixApplyIfRequested(tenantId, chatSessionId, req, state);
        }
        if (RepairProposalTaxonomy.Strategy.REMOVE_RISK_ITEMS.equals(strategy)) {
            List<CandidateItemDTO> effectiveCandidates = resolveEffectiveCandidates(tenantId, chatSessionId, state, true);
            RepairApplyMutationBuilder.applyRemoveRiskItems(state, effectiveCandidates, proposal);
            return saveAndRefreshAfterFixApply(tenantId, chatSessionId, req, state);
        }
        if (RepairProposalTaxonomy.Strategy.REPLACE_RISK_ITEMS.equals(strategy)) {
            List<CandidateItemDTO> effectiveCandidates = resolveEffectiveCandidates(tenantId, chatSessionId, state, true);
            RepairApplyMutationBuilder.MutationResult result =
                    RepairApplyMutationBuilder.applyReplaceVolunteers(state, effectiveCandidates, proposal);
            ensureFixMutationApplied(result);
            return saveAndRefreshAfterFixApply(tenantId, chatSessionId, req, state);
        }
        if (RepairProposalTaxonomy.Strategy.ONLY_KEEP_SCOPE.equals(strategy)
                || RepairProposalTaxonomy.Strategy.MUST_INCLUDE_SCOPE.equals(strategy)
                || RepairProposalTaxonomy.Strategy.EXCLUDE_SCOPE.equals(strategy)
                || RepairProposalTaxonomy.Strategy.TUITION_BUDGET_SCOPE.equals(strategy)) {
            List<CandidateItemDTO> effectiveCandidates = resolveEffectiveCandidates(tenantId, chatSessionId, state, true);
            RepairApplyMutationBuilder.MutationResult result =
                    RepairApplyMutationBuilder.applyUserGoalActions(state, effectiveCandidates, proposal);
            ensureFixMutationApplied(result);
            return saveAndRefreshAfterFixApply(tenantId, chatSessionId, req, state);
        }
        if (RepairProposalTaxonomy.Strategy.ADJUST_MAJOR_GROUP_INNER_SAFETY.equals(strategy)) {
            List<CandidateItemDTO> effectiveCandidates = resolveEffectiveCandidates(tenantId, chatSessionId, state, true);
            RepairApplyMutationBuilder.applyMajorGroupInnerSafety(state, effectiveCandidates, proposal);
            return saveAndRefreshAfterFixApply(tenantId, chatSessionId, req, state);
        }
        if (RepairProposalTaxonomy.Strategy.PRIORITIZE_WITHIN_TIER.equals(strategy)) {
            List<CandidateItemDTO> effectiveCandidates = resolveEffectiveCandidates(
                    tenantId, chatSessionId, state, true);
            if (proposal.getSolverResult() == null) {
                CanonicalPlanningRuntime.enforceOrdering(state, effectiveCandidates);
            } else {
                CanonicalPlanningRuntime.applyFrozenOrdering(state, proposal.getSolverResult());
                CanonicalPlanningRuntime.verifyFrozenState(state, proposal.getSolverResult());
            }
            recalculateOrderedSummary(state.getOrderedPlanState(), state.getCandidatePoolState());
            // 修复应用链（FAIL_CONFLICT）：变换依赖同一份快照上刚算出的冻结排序结果，重放风险高；
            // 用户动作输不起 -> 不覆盖并发写，响亮冲突
            if (!saveOrderedState(chatSessionId, state, "fix_apply_prioritize")) {
                throw writeCasConflict("修复建议应用");
            }
            return rerunReviewAfterFixApplyIfRequested(tenantId, chatSessionId, req, state);
        }
        if (RepairProposalTaxonomy.Strategy.FILL_MISSING_COUNT.equals(strategy)) {
            List<CandidateItemDTO> effectiveCandidates = resolveEffectiveCandidates(tenantId, chatSessionId, state, true);
            RepairApplyMutationBuilder.MutationResult result;
            if (RepairProposalTaxonomy.isUserGoalSource(proposal.getProposalSource())) {
                if (proposal.getSolverResult() != null) {
                    CanonicalPlanningRuntime.applyFrozenSelection(
                            state, effectiveCandidates, proposal.getSolverResult());
                    return saveAndRefreshAfterFixApply(
                            tenantId, chatSessionId, req, state, proposal.getSolverResult());
                }
                result = RepairApplyMutationBuilder.applyUserGoalActions(state, effectiveCandidates, proposal);
                boolean objectiveOnly = req.getUserGoalRequest() != null
                        && ((req.getUserGoalRequest().getRequirements() != null
                        && !req.getUserGoalRequest().getRequirements().isEmpty())
                        || (req.getUserGoalRequest().getPriorityRules() != null
                        && !req.getUserGoalRequest().getPriorityRules().isEmpty())
                        || req.getUserGoalRequest().getTierQuotaGoal() != null)
                        && result != null
                        && result.getRemovedVolunteerIds().isEmpty()
                        && result.getAddedVolunteerIds().isEmpty();
                if (!objectiveOnly) {
                    ensureFixMutationApplied(result);
                }
            } else {
                result = RepairApplyMutationBuilder.applyFixProposalCompensationActions(
                        state, effectiveCandidates, proposal);
            }
            return saveAndRefreshAfterFixApply(tenantId, chatSessionId, req, state);
        }
        throw new BusinessException(400, "当前修复建议暂不支持自动应用");
    }

    private void ensureWorkingPlanContainsOrderedPlanItems(PlanningStateDTO state) {
        if (state == null || state.getOrderedPlanState() == null || state.getWorkingPlanState() == null) {
            return;
        }
        Set<String> draftIds = defaultDraftItems(state.getWorkingPlanState().getItems()).stream()
                .map(DraftItemDTO::getVolunteerId)
                .filter(value -> !Strings.isNullOrEmpty(value))
                .collect(Collectors.toCollection(LinkedHashSet::new));
        for (OrderedItemDTO orderedItem : defaultOrderedItems(state.getOrderedPlanState().getItems())) {
            if (orderedItem == null || Strings.isNullOrEmpty(orderedItem.getVolunteerId())
                    || draftIds.contains(orderedItem.getVolunteerId())) {
                continue;
            }
            DraftItemDTO item = new DraftItemDTO();
            item.setVolunteerId(orderedItem.getVolunteerId());
            item.setTier(orderedItem.getTier());
            item.setSchoolName(orderedItem.getSchoolName());
            item.setMajorName(orderedItem.getMajorName());
            item.setLocked(orderedItem.getLocked());
            item.setSource(Strings.isNullOrEmpty(orderedItem.getSource()) ? "ordered_sync" : orderedItem.getSource());
            state.getWorkingPlanState().getItems().add(item);
            draftIds.add(item.getVolunteerId());
        }
        for (OrderedUnitDTO orderedUnit : defaultOrderedUnits(state.getOrderedPlanState().getUnits())) {
            for (PlanningUnitMajorDTO orderedMajor : defaultPlanningUnitMajors(
                    orderedUnit == null ? null : orderedUnit.getMajorItems())) {
                if (orderedMajor == null || Strings.isNullOrEmpty(orderedMajor.getVolunteerId())
                        || draftIds.contains(orderedMajor.getVolunteerId())) {
                    continue;
                }
                DraftItemDTO item = new DraftItemDTO();
                item.setVolunteerId(orderedMajor.getVolunteerId());
                item.setTier(orderedMajor.getTier() == null ? orderedUnit.getTier() : orderedMajor.getTier());
                item.setSchoolName(orderedUnit.getSchoolName());
                item.setMajorName(orderedMajor.getMajorName());
                item.setLocked(orderedUnit.getLocked());
                item.setSource("ordered_sync");
                state.getWorkingPlanState().getItems().add(item);
                draftIds.add(item.getVolunteerId());
            }
        }
        List<CandidateItemDTO> effectiveCandidates = resolveEffectiveCandidates(null, state.getSessionId(), state, false);
        syncWorkingPlanUnitsWithItems(state.getWorkingPlanState(), effectiveCandidates, state.getCandidatePoolState());
        recalculateWorkingPlanSummary(state.getWorkingPlanState(), state.getCandidatePoolState());
    }

    private void ensureFixMutationApplied(RepairApplyMutationBuilder.MutationResult result) {
        if (result == null) {
            throw new BusinessException(400, "修复建议没有可执行动作");
        }
        if (RepairProposalTaxonomy.isBlockedStatus(result.getStatus())) {
            throw new BusinessException(409, Strings.isNullOrEmpty(result.getBlockingReason())
                    ? "修复建议已失效，请重新生成" : result.getBlockingReason());
        }
        if (result.getRemovedVolunteerIds().isEmpty() && result.getAddedVolunteerIds().isEmpty()) {
            throw new BusinessException(400, "修复建议没有可执行动作");
        }
    }

    private PlanningStateDTO saveAndRefreshAfterFixApply(Long tenantId,
                                                         Long chatSessionId,
                                                         FixProposalApplyReq req,
                                                         PlanningStateDTO state) {
        return saveAndRefreshAfterFixApply(tenantId, chatSessionId, req, state, null);
    }

    private PlanningStateDTO saveAndRefreshAfterFixApply(Long tenantId,
                                                         Long chatSessionId,
                                                         FixProposalApplyReq req,
                                                         PlanningStateDTO state,
                                                         PlanSolverResultDTO frozenResult) {
        // 修复应用链（FAIL_CONFLICT）：见 applySupportedFixProposalStrategy 同名注释
        if (!saveWorkingPlanState(chatSessionId, state, "fix_apply")) {
            throw writeCasConflict("修复建议应用");
        }

        if (Boolean.TRUE.equals(req.getRegenerateOrderedPlan())) {
            OrderedPlanGenerateReq generateReq = new OrderedPlanGenerateReq();
            generateReq.setForceRegenerate(true);
            generateReq.setRegroupByTier(true);
            state = generateOrderedPlan(tenantId, chatSessionId, generateReq, frozenResult);
        }
        return rerunReviewAfterFixApplyIfRequested(tenantId, chatSessionId, req, state);
    }

    private PlanningStateDTO rerunReviewAfterFixApplyIfRequested(Long tenantId,
                                                                 Long chatSessionId,
                                                                 FixProposalApplyReq req,
                                                                 PlanningStateDTO state) {
        if (Boolean.TRUE.equals(req.getRerunReview())) {
            runReview(tenantId, chatSessionId);
            state = getPlanningState(chatSessionId);
        }
        return state;
    }

    public static class ExcelExportResult {
        private final byte[] excelData;
        private final String fileName;

        public ExcelExportResult(byte[] excelData, String fileName) {
            this.excelData = excelData;
            this.fileName = fileName;
        }

        public byte[] getExcelData() {
            return excelData;
        }

        public String getFileName() {
            return fileName;
        }
    }

    private String generateExcelFileName(CreateSessionReq userScoreDetail) {
        List<String> parts = new ArrayList<String>();
        if (userScoreDetail != null && userScoreDetail.getProvince() != null && userScoreDetail.getProvince().getName() != null) {
            parts.add(userScoreDetail.getProvince().getName());
        }
        if (userScoreDetail != null && userScoreDetail.getTotalScore() != null) {
            parts.add(userScoreDetail.getTotalScore() + "分");
        }
        String subjectStr = getSubjectString(userScoreDetail);
        if (!Strings.isNullOrEmpty(subjectStr)) {
            parts.add(subjectStr);
        }
        parts.add(java.time.LocalDate.now().format(java.time.format.DateTimeFormatter.ofPattern("yyyyMMdd")));
        return String.join("_", parts) + ".xlsx";
    }

    private String getSubjectString(CreateSessionReq userScoreDetail) {
        if (userScoreDetail == null) {
            return "";
        }
        if (userScoreDetail.getSubjectList() != null && !userScoreDetail.getSubjectList().isEmpty()) {
            List<String> ignored = Lists.newArrayList("08", "10", "11");
            List<String> names = userScoreDetail.getSubjectList().stream()
                    .filter(subject -> subject != null && !ignored.contains(subject.getValue()))
                    .map(CreateSessionReq.SubjectItem::getName)
                    .filter(Objects::nonNull)
                    .collect(Collectors.toList());
            if (!names.isEmpty()) {
                return String.join(".", names);
            }
        }
        return userScoreDetail.getSubjectType() == null ? "" : defaultString(userScoreDetail.getSubjectType().getDesc());
    }

    private String defaultString(String value) {
        return value == null ? "" : value;
    }

    public PlanningStateVersionDTO updateExplicitProfile(Long chatSessionId, UpdateExplicitProfileReq req) {
        PlanningStateDTO state = loadPlanningState(chatSessionId);
        applyExplicitProfileUpdate(state, req);
        return touchAndSavePreference(chatSessionId, state, latest -> applyExplicitProfileUpdate(latest, req));
    }

    /** 明确画像的整字段赋值（重放幂等）。 */
    private void applyExplicitProfileUpdate(PlanningStateDTO state, UpdateExplicitProfileReq req) {
        ExplicitProfileDTO explicitProfile = state.getProfileState().getExplicitProfile();
        if (req.getMajorPreferences() != null) {
            explicitProfile.setPositiveMajors(defaultList(req.getMajorPreferences().getPositive()));
            explicitProfile.setNegativeMajors(defaultList(req.getMajorPreferences().getNegative()));
        }
        if (req.getSchoolPreferences() != null) {
            explicitProfile.setPositiveSchools(defaultList(req.getSchoolPreferences().getPositive()));
            explicitProfile.setNegativeSchools(defaultList(req.getSchoolPreferences().getNegative()));
        }
        if (req.getRegionPreferences() != null) {
            explicitProfile.setPositiveRegions(defaultList(req.getRegionPreferences().getPositive()));
            explicitProfile.setNegativeRegions(defaultList(req.getRegionPreferences().getNegative()));
        }
        if (req.getStrengthSubjects() != null) {
            explicitProfile.setStrengthSubjects(defaultList(req.getStrengthSubjects()));
        }
    }

    /**
     * 约束/意向状态写入（内部接口）。**legacy 围栏**（2026-10-13 队列 21 定稿）：
     * {@code softPreferences} 自 4.0 起为 **legacy 只读**（权威 = {@code hardPlanningObjectives}
     * + {@code hardConstraints}）——4.0 写链恒发 {@code intentMode=constraint}（网关
     * {@code _constraint_update_from_goal} 显式带 {@code "intentMode": "constraint"}；agent 侧
     * {@code _apply_intent_pending} 亦把一切取值归一为 constraint），因此
     * {@code intentMode != "constraint"}（含缺省 "preference"）的**软偏好写分支已无现网调用者**，
     * 仅为兼容旧会话保留：**不删字段、不删读分支；勿在此分支新增逻辑**。
     */
    public PlanningStateVersionDTO updateConstraintState(Long chatSessionId, UpdateConstraintStateReq req) {
        PlanningStateDTO state = loadPlanningState(chatSessionId);
        boolean hardMode = applyConstraintStateUpdate(state, req);
        Consumer<PlanningStateDTO> reapply = latest -> applyConstraintStateUpdate(latest, req);
        return hardMode
                ? touchAndSaveConstraint(chatSessionId, state, reapply)
                : touchAndSavePreference(chatSessionId, state, reapply);
    }

    /**
     * 约束/意向合并的纯内存变换（add-unique/remove/mutex ⇒ 重放幂等），返回是否硬约束模式
     * （决定失效面与候选视图同步）。H2：{@link #updateConstraintState} 在冲突重读后重放它。
     */
    private boolean applyConstraintStateUpdate(PlanningStateDTO state, UpdateConstraintStateReq req) {
        if (state.getConstraintState() == null) {
            state.setConstraintState(new ConstraintStateDTO());
        }
        if (state.getConstraintState().getHardPlanningObjectives() == null) {
            state.getConstraintState().setHardPlanningObjectives(new HardPlanningObjectivesDTO());
        }
        if (state.getConstraintState().getHardPlanningObjectives().getCoverageRequirements() == null) {
            state.getConstraintState().getHardPlanningObjectives().setCoverageRequirements(Lists.newArrayList());
        }
        if (state.getConstraintState().getHardPlanningObjectives().getPriorityRules() == null) {
            state.getConstraintState().getHardPlanningObjectives().setPriorityRules(Lists.newArrayList());
        }
        ConstraintStateDTO constraintState = state.getConstraintState();
        if (constraintState.getHardConstraints() == null) {
            constraintState.setHardConstraints(new HardConstraintsDTO());
        }
        if (constraintState.getSoftPreferences() == null) {
            constraintState.setSoftPreferences(new SoftPreferencesDTO());
        }
        HardConstraintsDTO hard = constraintState.getHardConstraints();
        SoftPreferencesDTO soft = constraintState.getSoftPreferences();
        normalizeConstraintStateLists(hard, soft);
        // true = 4.0 写链（唯一现网路径）；false = legacy preference 软偏好写分支
        // （现网无写者，围栏见 {@link #updateConstraintState} 方法注）。
        boolean hardMode = req != null && "constraint".equalsIgnoreCase(req.getIntentMode());

        if (req != null && req.getMajorPreferences() != null) {
            mergeIntentStrengthGroup(
                    req.getMajorPreferences(),
                    soft.getPreferMajors(),
                    soft.getAvoidMajors(),
                    hard.getMustIncludeMajors(),
                    hard.getMustExcludeMajors(),
                    hardMode
            );
        }
        if (req != null && req.getSchoolPreferences() != null) {
            mergeIntentStrengthGroup(
                    req.getSchoolPreferences(),
                    soft.getPreferSchools(),
                    soft.getAvoidSchools(),
                    hard.getMustIncludeSchools(),
                    hard.getMustExcludeSchools(),
                    hardMode
            );
        }
        if (req != null && req.getRegionPreferences() != null) {
            mergeIntentStrengthGroup(
                    req.getRegionPreferences(),
                    soft.getPreferRegions(),
                    soft.getAvoidRegions(),
                    hard.getMustIncludeRegions(),
                    hard.getMustExcludeRegions(),
                    hardMode
            );
        }
        if (req != null && req.getRegionPreferenceIds() != null) {
            // 区域 ID 只走**硬约束**那一套规矩（加去重、互斥 ✓）——ID 是"筛选身份" ✓，
            // 不是"偏好" ✗，所以 soft 那条分支不动它 ✓。
            mergeHardIdGroup(
                    req.getRegionPreferenceIds(),
                    hard.getMustIncludeRegionIds(),
                    hard.getMustExcludeRegionIds());
        }
        if (req != null && req.getMajorPreferenceIds() != null) {
            // 专业 ID 与区域 ID **逐条同规矩** ✓（同一套"筛选身份"口径 ✓），否则
            // "ID 优先、名字兜底"在两侧取值不一致时会自己打自己 ✗。
            mergeHardIdGroup(
                    req.getMajorPreferenceIds(),
                    hard.getMustIncludeMajorIds(),
                    hard.getMustExcludeMajorIds());
        }
        if (hardMode) {
            syncCandidateViewStateWithHardRegionRequirements(state);
        }
        return hardMode;
    }

    private void normalizeConstraintStateLists(HardConstraintsDTO hard, SoftPreferencesDTO soft) {
        hard.setMustIncludeRegions(defaultList(hard.getMustIncludeRegions()));
        hard.setMustExcludeRegions(defaultList(hard.getMustExcludeRegions()));
        hard.setMustIncludeRegionIds(defaultList(hard.getMustIncludeRegionIds()));
        hard.setMustExcludeRegionIds(defaultList(hard.getMustExcludeRegionIds()));
        hard.setMustIncludeMajors(defaultList(hard.getMustIncludeMajors()));
        hard.setMustExcludeMajors(defaultList(hard.getMustExcludeMajors()));
        hard.setMustIncludeMajorIds(defaultList(hard.getMustIncludeMajorIds()));
        hard.setMustExcludeMajorIds(defaultList(hard.getMustExcludeMajorIds()));
        hard.setMustIncludeSchools(defaultList(hard.getMustIncludeSchools()));
        hard.setMustExcludeSchools(defaultList(hard.getMustExcludeSchools()));
        soft.setPreferRegions(defaultList(soft.getPreferRegions()));
        soft.setPreferMajors(defaultList(soft.getPreferMajors()));
        soft.setPreferSchools(defaultList(soft.getPreferSchools()));
        soft.setAvoidRegions(defaultList(soft.getAvoidRegions()));
        soft.setAvoidMajors(defaultList(soft.getAvoidMajors()));
        soft.setAvoidSchools(defaultList(soft.getAvoidSchools()));
    }

    /**
     * **身份 ID**（区域 ✓／专业 ✓）的并入/移出：与 `mergeIntentStrengthGroup` 的**硬模式分支逐条同规矩** ✓
     * （加入去重 ✓、同一值不得同时出现在两侧 ✓）。规矩一致才能在"ID 优先、名字兜底"下不打架 ✓。
     */
    private void mergeHardIdGroup(UpdateConstraintStateReq.PreferenceGroup group,
                                  List<String> hardPositive,
                                  List<String> hardNegative) {
        List<String> positive = normalizeIntentStateValues(group == null ? null : group.getPositive());
        List<String> negative = normalizeIntentStateValues(group == null ? null : group.getNegative());
        addUniqueValues(hardPositive, positive);
        addUniqueValues(hardNegative, negative);
        removeValues(hardNegative, positive);
        removeValues(hardPositive, negative);
    }

    private void mergeIntentStrengthGroup(UpdateConstraintStateReq.PreferenceGroup group,
                                          List<String> softPositive,
                                          List<String> softNegative,
                                          List<String> hardPositive,
                                          List<String> hardNegative,
                                          boolean hardMode) {
        List<String> positive = normalizeIntentStateValues(group.getPositive());
        List<String> negative = normalizeIntentStateValues(group.getNegative());
        if (hardMode) {
            addUniqueValues(hardPositive, positive);
            addUniqueValues(hardNegative, negative);
            removeValues(hardNegative, positive);
            removeValues(hardPositive, negative);
            removeValues(softPositive, positive);
            removeValues(softPositive, negative);
            removeValues(softNegative, positive);
            removeValues(softNegative, negative);
            return;
        }
        // ⚠ legacy 软偏好写入分支（现网无写者，仅旧会话兼容；围栏见 #updateConstraintState 方法注）：
        // 4.0 起权威字段为 hardPlanningObjectives/hardConstraints，勿新增逻辑。
        List<String> softPositiveToAdd = positive.stream()
                .filter(value -> !hardPositive.contains(value))
                .collect(Collectors.toList());
        List<String> softNegativeToAdd = negative.stream()
                .filter(value -> !hardNegative.contains(value))
                .collect(Collectors.toList());
        addUniqueValues(softPositive, softPositiveToAdd);
        addUniqueValues(softNegative, softNegativeToAdd);
        removeValues(softNegative, positive);
        removeValues(softPositive, negative);
        removeValues(hardNegative, positive);
        removeValues(hardPositive, negative);
    }

    private List<String> normalizeIntentStateValues(List<String> values) {
        return defaultList(values).stream()
                .filter(Objects::nonNull)
                .map(String::trim)
                .filter(value -> !value.isEmpty())
                .distinct()
                .collect(Collectors.toList());
    }

    private void addUniqueValues(List<String> target, List<String> values) {
        for (String value : values) {
            if (!target.contains(value)) {
                target.add(value);
            }
        }
    }

    private void removeValues(List<String> target, List<String> values) {
        if (values.isEmpty()) {
            return;
        }
        target.removeIf(values::contains);
    }

    public PlanningStateVersionDTO updateLatentProfile(Long chatSessionId, UpdateLatentProfileReq req) {
        PlanningStateDTO state = loadPlanningState(chatSessionId);
        applyLatentProfileUpdate(state, req);
        return touchAndSavePreference(chatSessionId, state, latest -> applyLatentProfileUpdate(latest, req));
    }

    /** 潜在画像的整字段赋值（重放幂等）。 */
    private void applyLatentProfileUpdate(PlanningStateDTO state, UpdateLatentProfileReq req) {
        LatentProfileDTO latentProfile = state.getProfileState().getLatentProfile();
        if (req.getFutureDevelopment() != null) {
            latentProfile.setFutureDevelopment(req.getFutureDevelopment());
        }
        if (req.getInterestPersonality() != null) {
            latentProfile.setInterestPersonality(req.getInterestPersonality());
        }
        if (req.getFamilyContext() != null) {
            latentProfile.setFamilyContext(req.getFamilyContext());
        }
    }

    public PlanningStateVersionDTO updatePhysicalConstraints(Long chatSessionId, UpdatePhysicalConstraintsReq req) {
        PlanningStateDTO state = loadPlanningState(chatSessionId);
        applyPhysicalConstraintsUpdate(state, req);
        return touchAndSaveConstraint(chatSessionId, state, latest -> applyPhysicalConstraintsUpdate(latest, req));
    }

    /** 体检约束的整字段赋值（重放幂等）。 */
    private void applyPhysicalConstraintsUpdate(PlanningStateDTO state, UpdatePhysicalConstraintsReq req) {
        PhysicalConstraintsDTO physicalConstraints = state.getProfileState().getPhysicalConstraints();
        if (req.getVision() != null) {
            physicalConstraints.setVision(req.getVision());
        }
        if (req.getColorVision() != null) {
            physicalConstraints.setColorVision(defaultList(req.getColorVision()));
        }
        if (req.getHeight() != null) {
            physicalConstraints.setHeight(req.getHeight());
        }
        if (req.getSpecialLimits() != null) {
            physicalConstraints.setSpecialLimits(defaultList(req.getSpecialLimits()));
        }
    }

    public PlanningStateVersionDTO markIntentChangeStale(Long chatSessionId, MarkPlanningIntentStaleReq req) {
        PlanningStateDTO state = loadPlanningState(chatSessionId);
        String intentMode = req == null ? null : req.getIntentMode();
        if ("constraint".equalsIgnoreCase(intentMode)) {
            return touchAndSaveConstraint(chatSessionId, state, null);
        }
        return touchAndSavePreference(chatSessionId, state, null);
    }

    public ConstraintDeriveRes deriveConstraints(Long chatSessionId) {
        PlanningStateDTO state = loadPlanningState(chatSessionId);
        DerivedPreferencesDTO derived = applyDerivedPreferences(state);
        PlanningStateVersionDTO versionDTO = touchAndSaveConstraint(chatSessionId, state,
                latest -> applyDerivedPreferences(latest));
        // 重试耗尽会抛冲突；拿到的 versionDTO 一定对应成功落盘的那份（derived 是纯派生，重算一致）
        derived = state.getConstraintState().getDerivedPreferences();

        ConstraintDeriveRes res = new ConstraintDeriveRes();
        res.setVersion(versionDTO.getVersion());
        res.setDerivedPreferences(derived);
        res.setStaleFlags(versionDTO.getStaleFlags());
        return res;
    }

    /** 派生偏好的重算（纯函数，重放幂等）。 */
    private DerivedPreferencesDTO applyDerivedPreferences(PlanningStateDTO state) {
        DerivedPreferencesDTO derived = buildDerivedPreferences(state.getProfileState());
        ConstraintStateDTO constraintState = state.getConstraintState();
        constraintState.setDerivedPreferences(derived);
        state.setConstraintState(constraintState);
        return derived;
    }

    public PlanningStateDTO generateCandidatePool(Long tenantId, Long chatSessionId, CandidatePoolGenerateReq req) {
        PlanningStateDTO state = loadPlanningState(chatSessionId);
        if (!Boolean.TRUE.equals(req.getForceRegenerate()) && !Boolean.TRUE.equals(state.getStaleFlags().getCandidatePool())
                && state.getCandidatePoolState() != null && state.getCandidatePoolState().getItems() != null
                && !state.getCandidatePoolState().getItems().isEmpty()) {
            state.setSessionId(chatSessionId);
            touchDataFreshnessSchedule(tenantId, chatSessionId, state, true, false);
            return state;
        }

        VolunteerRecommendListResponse response;
        VolunteerSourceDataSnapshot sourceSnapshot = null;
        if (Boolean.TRUE.equals(req.getRefreshSourceData())) {
            sourceSnapshot = volunteerSourceDataSyncService.fetchLatestSourceData(tenantId, chatSessionId, false);
            response = volunteerBizService.recommendVolunteerListWithSourceData(tenantId, chatSessionId, false, sourceSnapshot.getVolunteerData());
        } else {
            response = volunteerBizService.recommendVolunteerList(tenantId, chatSessionId, false, false);
        }
        CandidatePoolStateDTO candidatePoolState = buildCandidatePoolStateFromResponse(chatSessionId, state, response);
        if (Boolean.TRUE.equals(req.getRefreshSourceData())) {
            LatestCandidatePoolApplyCheck applyCheck = checkLatestCandidatePoolApplicable(state, candidatePoolState);
            if (!applyCheck.applicable) {
                log.warn("skip candidate pool source refresh because latest candidate pool is incomplete chatSessionId={} "
                                + "currentCount={} latestCount={} selectedCount={} selectedMatchedCount={}",
                        chatSessionId,
                        applyCheck.currentCount,
                        applyCheck.latestCount,
                        applyCheck.selectedCount,
                        applyCheck.selectedMatchedCount);
                throw new BusinessException(110, "最新招生计划数据暂未完整返回，已保留当前候选和方案数据");
            }
            volunteerSourceDataSyncService.persistFetchedSourceData(tenantId, chatSessionId, sourceSnapshot);
        }

        // B+C 站点（上游拉取几百 ms，不可重放整方法）：冲突时**重读最新 → 只把候选池域字段
        // 合并上去**（以最新 version 为基 +1），上游结果与源数据快照不重拉、副作用只做一次。
        boolean saved = false;
        for (int attempt = 0; attempt < WRITE_CAS_ATTEMPTS; attempt++) {
            applyCandidatePoolRefresh(chatSessionId, state,
                    buildCandidatePoolStateFromResponse(chatSessionId, state, response), sourceSnapshot);
            if (savePlanningState(chatSessionId, state, "candidate_pool_generate")) {
                saved = true;
                break;
            }
            reloadPlanningState(chatSessionId, state);
        }
        if (!saved) {
            throw writeCasConflict("候选池刷新");
        }
        state.setSessionId(chatSessionId);
        touchDataFreshnessSchedule(tenantId, chatSessionId, state, true, Boolean.TRUE.equals(req.getRefreshSourceData()));
        return state;
    }

    /**
     * 候选池刷新的**域字段合并**（H2 C 类）：只写候选池/新鲜度/overlay/phase/stale/version，
     * 其余字段（草案、排序、审查…）以传入的 state（重读后的最新）为准。
     *
     * <p>重放幂等：值全部来自上游响应/快照（candidatePoolState 每次以最新 state 重建），
     * version 以最新为基 +1（允许跳号）。</p>
     */
    private void applyCandidatePoolRefresh(Long chatSessionId,
                                           PlanningStateDTO state,
                                           CandidatePoolStateDTO candidatePoolState,
                                           VolunteerSourceDataSnapshot sourceSnapshot) {
        state.setCandidatePoolState(candidatePoolState);
        refreshDataFreshnessSnapshot(chatSessionId, state, candidatePoolState);
        if (sourceSnapshot != null && !Strings.isNullOrEmpty(sourceSnapshot.getSourceDataHash())) {
            state.getDataFreshnessState().setSourceDataHash(sourceSnapshot.getSourceDataHash());
            state.getDataFreshnessState().setLatestSourceDataHash(sourceSnapshot.getSourceDataHash());
        }
        state.setRecommendationOverlayState(buildRecommendationOverlayState(candidatePoolState, state.getVersion()));
        state.setPhase("candidate_generated");
        state.setVersion((state.getVersion() == null ? 0 : state.getVersion()) + 1);
        state.getStaleFlags().setCandidatePool(false);
        state.getStaleFlags().setRecommendationOverlay(false);
        ReviewInvalidationPolicy.markCandidatePoolDependentsStale(state);
    }

    /**
     * 候选成形（响应 → 候选池状态）。**从本类抽出的可复用包内方法**。
     *
     * <p>只抽出可见性，逻辑与调用点一字未改：它本身不含 savePlanningState / version 自增
     * （那两件在 {@link #generateCandidatePool} 里，见 1396-1408 那段）。抽出来的理由是
     * 只读的候选预览（{@link CandidatePreviewService}）需要同一份成形逻辑——复制一份
     * 迟早会与这里分叉，而"候选长什么样"正是两边都要回答的问题。</p>
     */
    CandidatePoolStateDTO buildCandidatePoolStateFromResponse(Long chatSessionId,
                                                               PlanningStateDTO state,
                                                               VolunteerRecommendListResponse response) {
        CandidatePoolStateDTO candidatePoolState = new CandidatePoolStateDTO();
        candidatePoolState.setGeneratedAt(OffsetDateTime.now().toString());
        candidatePoolState.setSourceVersion((state.getVersion() == null ? 0 : state.getVersion()) + 1);
        candidatePoolState.setRequiredCount(resolveRequiredPlanCount(chatSessionId, response));
        fillRequiredTierCounts(chatSessionId, candidatePoolState, response);
        candidatePoolState.setRequiredUnitCount(response.getBaseData() != null && response.getBaseData().getVolunteerCount() != null
                ? response.getBaseData().getVolunteerCount().getSchoolCount() : null);
        candidatePoolState.setRequiredMajorCount(response.getBaseData() != null && response.getBaseData().getVolunteerCount() != null
                ? response.getBaseData().getVolunteerCount().getMajorCount() : null);
        candidatePoolState.setVolunteerModel(response.getBaseData() != null && response.getBaseData().getVolunteerModel() != null
                ? response.getBaseData().getVolunteerModel().getCode() : null);
        candidatePoolState.setUserScore(response.getUserScoreDetail() != null ? response.getUserScoreDetail().getTotalScore() : null);
        candidatePoolState.setBatchScore(response.getUserScoreDetail() != null && response.getUserScoreDetail().getBatch() != null
                && response.getUserScoreDetail().getBatch().getScore() != null
                ? Math.round(response.getUserScoreDetail().getBatch().getScore()) : null);
        candidatePoolState.setSourceProvinceName(response.getUserScoreDetail() != null && response.getUserScoreDetail().getProvince() != null
                ? response.getUserScoreDetail().getProvince().getName() : null);
        List<CandidateItemDTO> items = Lists.newArrayList();
        items.addAll(flattenCandidates(response.getSprints(), "冲"));
        items.addAll(flattenCandidates(response.getSafes(), "稳"));
        items.addAll(flattenCandidates(response.getProtects(), "保"));
        List<CandidateItemDTO> normalizedItems = enrichCandidateMajorTaxonomyFields(
                normalizeCandidateIdentities(candidatePoolState, items));
        candidatePoolState.setItems(normalizedItems);
        recalculateCandidatePoolSummary(candidatePoolState);
        populateCandidatePoolSourceSummary(candidatePoolState, items, normalizedItems);
        normalizeRequiredTierCountsByAvailableCapacity(candidatePoolState);
        CandidatePoolQualityStatusBuilder.apply(state, candidatePoolState);
        return candidatePoolState;
    }

    private void fillRequiredTierCounts(Long chatSessionId,
                                        CandidatePoolStateDTO candidatePoolState,
                                        VolunteerRecommendListResponse response) {
        if (candidatePoolState == null || response == null || response.getBaseData() == null) {
            return;
        }
        Map<String, Integer> requiredTierCounts = buildRequiredTierCounts(chatSessionId, response);
        candidatePoolState.setRequiredTierCounts(requiredTierCounts);
    }

    private void normalizeCandidatePoolForPlanning(PlanningStateDTO state) {
        if (state == null || state.getCandidatePoolState() == null
                || state.getCandidatePoolState().getItems() == null
                || state.getCandidatePoolState().getItems().isEmpty()) {
            return;
        }
        recalculateCandidatePoolSummary(state.getCandidatePoolState());
        normalizeRequiredTierCountsByAvailableCapacity(state.getCandidatePoolState());
    }

    private CandidateViewStateDTO buildDefaultCandidateViewState(ProfileStateDTO profileState) {
        return new CandidateViewStateDTO();
    }

    private CandidateViewStateDTO normalizeCandidateViewState(CandidateViewStateDTO req) {
        CandidateViewStateDTO safe = req == null ? new CandidateViewStateDTO() : req;
        if (safe.getFilters() == null) {
            safe.setFilters(new CandidateViewStateDTO.Filters());
        }
        if (safe.getSort() == null) {
            safe.setSort(new CandidateViewStateDTO.Sort());
        }
        safe.setExpertPreferredOnly(Boolean.TRUE.equals(safe.getExpertPreferredOnly()));
        safe.getFilters().setTiers(defaultList(safe.getFilters().getTiers()));
        safe.getFilters().setProvinceNames(defaultList(safe.getFilters().getProvinceNames()));
        safe.getFilters().setNegativeProvinceNames(defaultList(safe.getFilters().getNegativeProvinceNames()));
        safe.getFilters().setCityNames(defaultList(safe.getFilters().getCityNames()));
        safe.getFilters().setNegativeCityNames(defaultList(safe.getFilters().getNegativeCityNames()));
        safe.getFilters().setSchoolKeywords(defaultList(safe.getFilters().getSchoolKeywords()));
        safe.getFilters().setNegativeSchoolKeywords(defaultList(safe.getFilters().getNegativeSchoolKeywords()));
        safe.getFilters().setMajorKeywords(defaultList(safe.getFilters().getMajorKeywords()));
        safe.getFilters().setNegativeMajorKeywords(defaultList(safe.getFilters().getNegativeMajorKeywords()));
        safe.getFilters().setSchoolTags(defaultList(safe.getFilters().getSchoolTags()));
        safe.getFilters().setNegativeSchoolTags(defaultList(safe.getFilters().getNegativeSchoolTags()));
        safe.getFilters().setMajorTags(defaultList(safe.getFilters().getMajorTags()));
        safe.getFilters().setNegativeMajorTags(defaultList(safe.getFilters().getNegativeMajorTags()));
        if (Strings.isNullOrEmpty(safe.getSort().getField())) {
            safe.getSort().setField("finalScore");
        }
        if (Strings.isNullOrEmpty(safe.getSort().getOrder())) {
            safe.getSort().setOrder("desc");
        }
        return safe;
    }

    private void syncCandidateViewStateWithHardRegionRequirements(PlanningStateDTO state) {
        if (state == null || state.getConstraintState() == null
                || state.getConstraintState().getHardConstraints() == null) {
            return;
        }
        CandidateViewStateDTO viewState = normalizeCandidateViewState(state.getCandidateViewState());
        state.setCandidateViewState(viewState);
        CandidateViewStateDTO.Filters filters = viewState.getFilters();
        HardConstraintsDTO hard = state.getConstraintState().getHardConstraints();
        List<String> includeRegions = normalizeIntentStateValues(hard.getMustIncludeRegions());
        List<String> excludeRegions = normalizeIntentStateValues(hard.getMustExcludeRegions());
        addUniqueValues(filters.getProvinceNames(), includeRegions);
        addUniqueValues(filters.getNegativeProvinceNames(), excludeRegions);
        removeValues(filters.getNegativeProvinceNames(), includeRegions);
        removeValues(filters.getProvinceNames(), excludeRegions);
    }

    private boolean syncHardRegionRequirementsFromCandidateViewChange(PlanningStateDTO state,
                                                                      CandidateViewStateDTO previous,
                                                                      CandidateViewStateDTO next) {
        if (state == null || state.getConstraintState() == null
                || state.getConstraintState().getHardConstraints() == null) {
            return false;
        }
        HardConstraintsDTO hard = state.getConstraintState().getHardConstraints();
        CandidateViewStateDTO.Filters previousFilters = normalizeCandidateViewState(previous).getFilters();
        CandidateViewStateDTO.Filters nextFilters = normalizeCandidateViewState(next).getFilters();
        boolean changed = removeHardRegionsNoLongerVisible(
                hard.getMustIncludeRegions(),
                previousFilters.getProvinceNames(),
                nextFilters.getProvinceNames());
        changed = removeHardRegionsNoLongerVisible(
                hard.getMustExcludeRegions(),
                previousFilters.getNegativeProvinceNames(),
                nextFilters.getNegativeProvinceNames()) || changed;
        return changed;
    }

    private boolean removeHardRegionsNoLongerVisible(List<String> hardRegions,
                                                     List<String> previousVisible,
                                                     List<String> nextVisible) {
        List<String> previous = normalizeIntentStateValues(previousVisible);
        List<String> next = normalizeIntentStateValues(nextVisible);
        if (hardRegions == null || hardRegions.isEmpty() || previous.isEmpty()) {
            return false;
        }
        List<String> removed = previous.stream()
                .filter(value -> !next.contains(value))
                .collect(Collectors.toList());
        int before = hardRegions.size();
        removeValues(hardRegions, removed);
        return hardRegions.size() != before;
    }

    private Map<String, Integer> buildRequiredTierCounts(Long chatSessionId, VolunteerRecommendListResponse response) {
        Map<String, Integer> requiredTierCounts = new HashMap<String, Integer>();
        if (response == null || response.getBaseData() == null) {
            return requiredTierCounts;
        }
        Integer requiredCount = resolveRequiredPlanCount(chatSessionId, response);
        CreateSessionReq userScoreDetail = resolveTierTargetScoreDetail(chatSessionId, response);
        CreateSessionReq.StrategyType strategyType = resolveExplicitRequiredTierStrategy(userScoreDetail);
        if (requiredCount != null && requiredCount > 0 && strategyType != null) {
            Map<String, Integer> calculated = volunteerIntervalService.calculateTargetCounts(
                    requiredCount,
                    false,
                    strategyType);
            putPositive(requiredTierCounts, "冲", calculated.get("冲"));
            putPositive(requiredTierCounts, "稳", calculated.get("稳"));
            putPositive(requiredTierCounts, "保", calculated.get("保"));
            if (!requiredTierCounts.isEmpty()) {
                return requiredTierCounts;
            }
        }
        Map<String, Integer> trustedTargetMap = buildTrustedRequiredTierCounts(
                response.getBaseData().getThree_target_count_map(),
                requiredCount);
        if (!trustedTargetMap.isEmpty()) {
            return trustedTargetMap;
        }
        if (requiredCount != null && requiredCount > 0) {
            Map<String, Integer> calculated = volunteerIntervalService.calculateTargetCounts(
                    requiredCount,
                    false,
                    buildDefaultRequiredTierStrategy());
            putPositive(requiredTierCounts, "冲", calculated.get("冲"));
            putPositive(requiredTierCounts, "稳", calculated.get("稳"));
            putPositive(requiredTierCounts, "保", calculated.get("保"));
            if (!requiredTierCounts.isEmpty()) {
                return requiredTierCounts;
            }
        }
        Map<String, Integer> targetMap = response.getBaseData().getThree_target_count_map();
        if (targetMap != null && !targetMap.isEmpty()) {
            putPositive(requiredTierCounts, "冲", targetMap.get("sprints_count"));
            putPositive(requiredTierCounts, "稳", targetMap.get("safes_count"));
            putPositive(requiredTierCounts, "保", targetMap.get("protects_count"));
        }
        putPositive(requiredTierCounts, "冲", response.getBaseData().getSprints_count());
        putPositive(requiredTierCounts, "稳", response.getBaseData().getSafes_count());
        putPositive(requiredTierCounts, "保", response.getBaseData().getProtects_count());
        return requiredTierCounts;
    }

    private Integer resolveRequiredPlanCount(Long chatSessionId, VolunteerRecommendListResponse response) {
        if (response == null || response.getBaseData() == null) {
            return null;
        }
        Integer sessionTargetCount = resolveRequiredPlanCountFromScoreDetail(
                resolveTierTargetScoreDetail(chatSessionId, response),
                response.getBaseData().getVolunteerModel());
        boolean responseHasExplicitCountContext = response.getBaseData().getVolunteerCount() != null
                && response.getBaseData().getVolunteerModel() != null;
        if (!responseHasExplicitCountContext && sessionTargetCount != null && sessionTargetCount > 0) {
            return sessionTargetCount;
        }
        Integer requiredCount = response.getBaseData().getNeed_count();
        if (requiredCount != null && requiredCount > 0) {
            return requiredCount;
        }
        if (response.getBaseData().getVolunteerCount() != null) {
            Integer modelCount = isMajorGroupVolunteerModel(response)
                    ? response.getBaseData().getVolunteerCount().getSchoolCount()
                    : response.getBaseData().getVolunteerCount().getMajorCount();
            if (modelCount != null && modelCount > 0) {
                return modelCount;
            }
        }
        if (sessionTargetCount != null && sessionTargetCount > 0) {
            return sessionTargetCount;
        }
        return DEFAULT_INITIAL_PLAN_TARGET_COUNT;
    }

    private Integer resolveRequiredPlanCountFromScoreDetail(CreateSessionReq scoreDetail,
                                                            VolunteerModel fallbackModel) {
        if (scoreDetail == null || scoreDetail.getVolunteerCount() == null) {
            return null;
        }
        VolunteerModel model = scoreDetail.getVolunteerModel() != null ? scoreDetail.getVolunteerModel() : fallbackModel;
        if (VolunteerModel.majorGroup.equals(model)) {
            return scoreDetail.getVolunteerCount().getSchoolCount();
        }
        if (VolunteerModel.major.equals(model)) {
            return scoreDetail.getVolunteerCount().getMajorCount();
        }
        return null;
    }

    private boolean isMajorGroupVolunteerModel(VolunteerRecommendListResponse response) {
        return response != null
                && response.getBaseData() != null
                && response.getBaseData().getVolunteerModel() != null
                && "majorGroup".equalsIgnoreCase(response.getBaseData().getVolunteerModel().getCode());
    }

    private Map<String, Integer> buildTrustedRequiredTierCounts(Map<String, Integer> targetMap, Integer requiredCount) {
        Map<String, Integer> requiredTierCounts = new HashMap<String, Integer>();
        if (targetMap == null || targetMap.isEmpty() || requiredCount == null || requiredCount <= 0) {
            return requiredTierCounts;
        }
        Integer sprintCount = targetMap.get("sprints_count");
        Integer safeCount = targetMap.get("safes_count");
        Integer protectCount = targetMap.get("protects_count");
        int total = valueOrZero(sprintCount) + valueOrZero(safeCount) + valueOrZero(protectCount);
        if (total != requiredCount) {
            return requiredTierCounts;
        }
        putPositive(requiredTierCounts, "冲", sprintCount);
        putPositive(requiredTierCounts, "稳", safeCount);
        putPositive(requiredTierCounts, "保", protectCount);
        return requiredTierCounts;
    }

    private CreateSessionReq.StrategyType resolveExplicitRequiredTierStrategy(CreateSessionReq userScoreDetail) {
        if (userScoreDetail != null && userScoreDetail.getStrategyType() != null
                && !Strings.isNullOrEmpty(userScoreDetail.getStrategyType().getCode())) {
            return userScoreDetail.getStrategyType();
        }
        return null;
    }

    private CreateSessionReq.StrategyType buildDefaultRequiredTierStrategy() {
        CreateSessionReq.StrategyType fallback = new CreateSessionReq.StrategyType();
        fallback.setCode("cautious");
        fallback.setName("稳妥型");
        return fallback;
    }

    private void normalizeRequiredTierCountsByAvailableCapacity(CandidatePoolStateDTO candidatePoolState) {
        if (candidatePoolState == null || candidatePoolState.getRequiredTierCounts() == null
                || candidatePoolState.getRequiredTierCounts().isEmpty() || candidatePoolState.getSummary() == null) {
            return;
        }
        if (!isMajorGroupMode(candidatePoolState)) {
            return;
        }
        Map<String, Integer> availableTierCounts = candidatePoolState.getSummary().getUnitTierCounts();
        if (availableTierCounts == null || availableTierCounts.isEmpty()) {
            return;
        }

        int availableTotal = sumPositiveCounts(availableTierCounts);
        int requestedTotal = candidatePoolState.getRequiredTierCounts().values().stream()
                .filter(value -> value != null && value > 0)
                .mapToInt(Integer::intValue)
                .sum();
        int targetTotal = candidatePoolState.getRequiredCount() != null && candidatePoolState.getRequiredCount() > 0
                ? candidatePoolState.getRequiredCount()
                : requestedTotal;
        if (targetTotal <= 0 || availableTotal <= 0) {
            return;
        }
        targetTotal = Math.min(targetTotal, availableTotal);

        Map<String, Integer> normalized = new LinkedHashMap<String, Integer>();
        for (String tier : Lists.newArrayList("冲", "稳", "保")) {
            int requested = positiveCount(candidatePoolState.getRequiredTierCounts().get(tier));
            int available = positiveCount(availableTierCounts.get(tier));
            normalized.put(tier, Math.min(requested, available));
        }

        int missing = targetTotal - sumPositiveCounts(normalized);
        for (String tier : Lists.newArrayList("稳", "保", "冲")) {
            if (missing <= 0) {
                break;
            }
            int available = positiveCount(availableTierCounts.get(tier));
            int current = positiveCount(normalized.get(tier));
            int supplement = Math.min(missing, Math.max(0, available - current));
            if (supplement <= 0) {
                continue;
            }
            normalized.put(tier, current + supplement);
            missing -= supplement;
        }

        candidatePoolState.setRequiredTierCounts(normalized);
    }

    private int sumPositiveCounts(Map<String, Integer> counts) {
        if (counts == null || counts.isEmpty()) {
            return 0;
        }
        return counts.values().stream()
                .filter(value -> value != null && value > 0)
                .mapToInt(Integer::intValue)
                .sum();
    }

    private int positiveCount(Integer value) {
        return value == null || value <= 0 ? 0 : value;
    }

    private CreateSessionReq resolveTierTargetScoreDetail(Long chatSessionId,
                                                          VolunteerRecommendListResponse response) {
        CreateSessionReq responseScoreDetail = response == null ? null : response.getUserScoreDetail();
        if (responseScoreDetail != null && responseScoreDetail.getStrategyType() != null) {
            return responseScoreDetail;
        }
        CreateSessionReq storedScoreDetail = loadScoreDetail(chatSessionId);
        if (storedScoreDetail != null && storedScoreDetail.getStrategyType() != null) {
            return storedScoreDetail;
        }
        return responseScoreDetail;
    }

    private void putPositive(Map<String, Integer> target, String key, Integer value) {
        if (target == null || Strings.isNullOrEmpty(key) || value == null || value <= 0) {
            return;
        }
        target.put(key, value);
    }

    public CandidatePoolQueryRes queryCandidatePool(Long tenantId, Long chatSessionId, CandidatePoolQueryReq req) {
        CandidatePoolQueryReq safeReq = req == null ? new CandidatePoolQueryReq() : req;
        PlanningStateDTO state = loadPlanningState(chatSessionId);
        if (state.getCandidateViewState() == null) {
            state.setCandidateViewState(buildDefaultCandidateViewState(state.getProfileState()));
        }
        refreshRecommendationOverlayBestEffort(tenantId, chatSessionId, state, "candidate-pool query");
        List<CandidateItemDTO> items = normalizeCandidateIdentities(
                state.getCandidatePoolState(),
                mergeOverlayIntoCandidates(
                        state.getCandidatePoolState().getItems(),
                        state.getRecommendationOverlayState(),
                        state));
        List<CandidateItemDTO> filtered = items.stream()
                .filter(item -> matchesTier(item, safeReq))
                .filter(item -> matchesProvince(item, safeReq))
                .filter(item -> matchesCity(item, safeReq))
                .filter(item -> matchesSchoolKeyword(item, safeReq))
                .filter(item -> matchesMajorKeyword(item, safeReq))
                .filter(item -> matchesSchoolTags(item, safeReq))
                .filter(item -> matchesMajorTags(item, safeReq))
                .collect(Collectors.toList());

        Comparator<CandidateItemDTO> comparator = buildComparator(safeReq.getSort() != null ? safeReq.getSort().getField() : "finalScore");
        if ("asc".equalsIgnoreCase(safeReq.getSort() != null ? safeReq.getSort().getOrder() : "desc")) {
            filtered = filtered.stream().sorted(comparator).collect(Collectors.toList());
        } else {
            filtered = filtered.stream().sorted(comparator.reversed()).collect(Collectors.toList());
        }

        int page = safeReq.getPage() == null || safeReq.getPage() < 1 ? 1 : safeReq.getPage();
        int pageSize = safeReq.getPageSize() == null || safeReq.getPageSize() < 1 ? 20 : safeReq.getPageSize();
        int fromIndex = Math.min((page - 1) * pageSize, filtered.size());
        int toIndex = Math.min(fromIndex + pageSize, filtered.size());

        CandidatePoolQueryRes res = new CandidatePoolQueryRes();
        List<CandidateItemDTO> pagedItems = filtered.subList(fromIndex, toIndex);
        res.setItems(pagedItems);
        res.setPage(page);
        res.setPageSize(pageSize);
        res.setTotal(filtered.size());
        res.setTotalUnitCount(countCandidateUnits(filtered));
        res.setLoadedEntryCount(pagedItems.size());
        res.setLoadedUnitCount(countCandidateUnits(pagedItems));
        CandidatePoolQueryRes.ViewSummary viewSummary = new CandidatePoolQueryRes.ViewSummary();
        viewSummary.setPoolEntryTotal(items.size());
        viewSummary.setPoolUnitTotal(countCandidateUnits(items));
        viewSummary.setViewEntryTotal(filtered.size());
        viewSummary.setViewUnitTotal(countCandidateUnits(filtered));
        viewSummary.setLoadedEntryCount(pagedItems.size());
        viewSummary.setLoadedUnitCount(countCandidateUnits(pagedItems));
        res.setViewSummary(viewSummary);
        return res;
    }

    public CandidateFilterOptionsDTO getCandidateFilterOptions(Long tenantId, Long chatSessionId) {
        PlanningStateDTO state = loadPlanningState(chatSessionId);
        refreshRecommendationOverlayBestEffort(tenantId, chatSessionId, state, "candidate filter options");
        List<CandidateItemDTO> items = mergeOverlayIntoCandidates(
                state.getCandidatePoolState().getItems(),
                state.getRecommendationOverlayState());
        CandidateFilterOptionsDTO dto = new CandidateFilterOptionsDTO();
        List<String> provinceNames = items.stream()
                .map(CandidateItemDTO::getProvinceName)
                .filter(this::isEnumLikeFilterOption)
                .distinct()
                .sorted()
                .collect(Collectors.toList());
        List<String> cityNames = items.stream()
                .map(CandidateItemDTO::getCityName)
                .filter(this::isEnumLikeFilterOption)
                .distinct()
                .sorted()
                .collect(Collectors.toList());
        List<String> schoolKeywords = items.stream()
                .map(this::resolveDisplaySchoolName)
                .map(this::normalizeKeywordFilterOption)
                .filter(Objects::nonNull)
                .distinct()
                .sorted()
                .collect(Collectors.toList());
        List<String> majorDisciplines = items.stream()
                .map(this::resolveMajorDiscipline)
                .filter(this::isEnumLikeFilterOption)
                .distinct()
                .sorted()
                .collect(Collectors.toList());
        List<String> majorCategories = items.stream()
                .map(this::resolveMajorCategory)
                .filter(this::isEnumLikeFilterOption)
                .distinct()
                .sorted()
                .collect(Collectors.toList());
        List<String> majorNameKeywords = items.stream()
                .map(CandidateItemDTO::getMajorName)
                .map(this::normalizeMajorNameFilterOption)
                .filter(Objects::nonNull)
                .distinct()
                .sorted()
                .collect(Collectors.toList());
        List<String> schoolTags = items.stream()
                .flatMap(item -> collectSchoolFilterTags(item).stream())
                .filter(this::isEnumLikeFilterOption)
                .distinct()
                .sorted()
                .collect(Collectors.toList());
        List<String> majorTags = items.stream()
                .flatMap(item -> collectMajorFilterTags(item).stream())
                .filter(tag -> !MAJOR_INTENT_EXPLANATION_TAGS.contains(tag))
                .filter(this::isEnumLikeFilterOption)
                .distinct()
                .sorted()
                .collect(Collectors.toList());
        dto.setProvinceNames(provinceNames);
        dto.setCityNames(cityNames);
        dto.setSchoolKeywords(schoolKeywords);
        dto.setMajorKeywords(majorCategories);
        dto.setSchoolTags(schoolTags);
        dto.setMajorTags(majorTags);
        dto.setGroups(buildCandidateFilterGroups(provinceNames, cityNames, schoolKeywords,
                schoolTags, majorTags, majorDisciplines, majorCategories, majorNameKeywords));
        dto.setRegionTree(buildCandidateRegionTree(items, provinceNames, cityNames));
        dto.setMajorTree(buildCandidateMajorTree(items));
        return dto;
    }

    @Transactional(rollbackFor = Exception.class)
    public PlanningStateDTO selectWorkingPlanItems(Long chatSessionId, DraftSelectReq req) {
        return selectDraftItems(chatSessionId, req);
    }

    /**
     * @deprecated use {@link #selectWorkingPlanItems(Long, DraftSelectReq)}
     */
    @Deprecated
    @Transactional(rollbackFor = Exception.class)
    public PlanningStateDTO selectDraftItems(Long chatSessionId, DraftSelectReq req) {
        PlanningStateDTO state = loadPlanningState(chatSessionId);
        List<String> selectedVolunteerIds = applyDraftSelection(state, chatSessionId, req);
        if (selectedVolunteerIds.isEmpty()) {
            state.setSessionId(chatSessionId);
            return state;
        }
        // 行为事件是副作用：只记一次（重放时不再补记）
        List<CandidateItemDTO> candidates = resolveEffectiveCandidates(null, chatSessionId, state, false);
        appendPlanItemsBehaviorEvent(state, null, chatSessionId, "plan_add", selectedVolunteerIds, false, candidates);
        return saveWorkingPlanStateWithReplay(chatSessionId, state, "draft_select",
                latest -> applyDraftSelection(latest, chatSessionId, req));
    }

    /** 选中志愿（纯内存、add-if-allowed 幂等）；返回本次新增的志愿 id（空=无变化，不必落盘）。 */
    private List<String> applyDraftSelection(PlanningStateDTO state, Long chatSessionId, DraftSelectReq req) {
        DraftPlanStateDTO draft = state.getDraftPlanState();
        List<CandidateItemDTO> candidates = resolveEffectiveCandidates(null, chatSessionId, state, false);
        List<String> selectedVolunteerIds = Lists.newArrayList();
        for (String volunteerId : defaultList(req == null ? null : req.getVolunteerIds())) {
            CandidateItemDTO candidate = findCandidate(candidates, volunteerId);
            if (!WorkingPlanMutationSupport.addWorkingPlanItemIfAllowed(draft, candidate, req == null ? null : req.getSource())) {
                continue;
            }
            selectedVolunteerIds.add(candidate.getVolunteerId());
        }
        if (selectedVolunteerIds.isEmpty()) {
            return selectedVolunteerIds;
        }
        syncWorkingPlanUnitsWithItems(draft, candidates, state.getCandidatePoolState());
        recalculateWorkingPlanSummary(draft, state.getCandidatePoolState());
        return selectedVolunteerIds;
    }

    @Transactional(rollbackFor = Exception.class)
    public PlanningStateDTO removeWorkingPlanItems(Long chatSessionId, DraftRemoveReq req) {
        return removeDraftItems(chatSessionId, req);
    }

    /**
     * @deprecated use {@link #removeWorkingPlanItems(Long, DraftRemoveReq)}
     */
    @Deprecated
    @Transactional(rollbackFor = Exception.class)
    public PlanningStateDTO removeDraftItems(Long chatSessionId, DraftRemoveReq req) {
        PlanningStateDTO state = loadPlanningState(chatSessionId);
        List<String> removedVolunteerIds = applyDraftRemoval(state, chatSessionId, req);
        if (removedVolunteerIds.isEmpty()) {
            state.setSessionId(chatSessionId);
            return state;
        }
        List<CandidateItemDTO> candidates = resolveEffectiveCandidates(null, chatSessionId, state, false);
        appendPlanItemsBehaviorEvent(state, null, chatSessionId, "plan_remove", removedVolunteerIds, false, candidates);
        return saveWorkingPlanStateWithReplay(chatSessionId, state, "draft_remove",
                latest -> applyDraftRemoval(latest, chatSessionId, req));
    }

    /** 移除志愿（幂等：按 id 过滤）；返回本次实际移除的志愿 id。 */
    private List<String> applyDraftRemoval(PlanningStateDTO state, Long chatSessionId, DraftRemoveReq req) {
        DraftPlanStateDTO draft = state.getDraftPlanState();
        List<CandidateItemDTO> candidates = resolveEffectiveCandidates(null, chatSessionId, state, false);
        List<String> requestedVolunteerIds = defaultList(req == null ? null : req.getVolunteerIds());
        List<String> removedVolunteerIds = defaultDraftItems(draft.getItems()).stream()
                .filter(item -> containsVolunteerId(requestedVolunteerIds, item.getVolunteerId()))
                .map(DraftItemDTO::getVolunteerId)
                .filter(value -> !Strings.isNullOrEmpty(value))
                .collect(Collectors.toList());
        if (removedVolunteerIds.isEmpty()) {
            return removedVolunteerIds;
        }
        draft.setItems(draft.getItems().stream()
                .filter(item -> !containsVolunteerId(requestedVolunteerIds, item.getVolunteerId()))
                .collect(Collectors.toList()));
        syncWorkingPlanUnitsWithItems(draft, candidates, state.getCandidatePoolState());
        recalculateWorkingPlanSummary(draft, state.getCandidatePoolState());
        return removedVolunteerIds;
    }

    public PlanningStateDTO lockWorkingPlanItems(Long chatSessionId, DraftLockReq req) {
        return lockDraftItems(chatSessionId, req);
    }

    /**
     * @deprecated use {@link #lockWorkingPlanItems(Long, DraftLockReq)}
     */
    @Deprecated
    public PlanningStateDTO lockDraftItems(Long chatSessionId, DraftLockReq req) {
        PlanningStateDTO state = loadPlanningState(chatSessionId);
        applyDraftLock(state, chatSessionId, req);
        return saveWorkingPlanStateWithReplay(chatSessionId, state, "draft_lock",
                latest -> applyDraftLock(latest, chatSessionId, req));
    }

    /** 锁定/解锁志愿（整字段赋值，幂等）。 */
    private void applyDraftLock(PlanningStateDTO state, Long chatSessionId, DraftLockReq req) {
        DraftPlanStateDTO draft = state.getDraftPlanState();
        for (DraftItemDTO item : draft.getItems()) {
            if (defaultList(req.getVolunteerIds()).contains(item.getVolunteerId())) {
                item.setLocked(req.getLocked());
            }
        }
        syncWorkingPlanUnitsWithItems(draft, resolveEffectiveCandidates(null, chatSessionId, state, false), state.getCandidatePoolState());
        recalculateWorkingPlanSummary(draft, state.getCandidatePoolState());
    }

    public PlanningStateDTO banWorkingPlanItems(Long chatSessionId, DraftBanReq req) {
        return banDraftItems(chatSessionId, req);
    }

    /**
     * @deprecated use {@link #banWorkingPlanItems(Long, DraftBanReq)}
     */
    @Deprecated
    public PlanningStateDTO banDraftItems(Long chatSessionId, DraftBanReq req) {
        PlanningStateDTO state = loadPlanningState(chatSessionId);
        applyDraftBan(state, chatSessionId, req);
        return saveWorkingPlanStateWithReplay(chatSessionId, state, "draft_ban",
                latest -> applyDraftBan(latest, chatSessionId, req));
    }

    /** 屏蔽志愿（add-unique + 同步剔除，幂等）。 */
    private void applyDraftBan(PlanningStateDTO state, Long chatSessionId, DraftBanReq req) {
        DraftPlanStateDTO draft = state.getDraftPlanState();
        for (String volunteerId : defaultList(req.getVolunteerIds())) {
            if (!containsVolunteerId(draft.getBannedVolunteerIds(), volunteerId)) {
                draft.getBannedVolunteerIds().add(volunteerId);
            }
        }
        draft.setItems(draft.getItems().stream()
                .filter(item -> !containsVolunteerId(draft.getBannedVolunteerIds(), item.getVolunteerId()))
                .collect(Collectors.toList()));
        syncWorkingPlanUnitsWithItems(draft, resolveEffectiveCandidates(null, chatSessionId, state, false), state.getCandidatePoolState());
        recalculateWorkingPlanSummary(draft, state.getCandidatePoolState());
    }

    public PlanningStateDTO generateOrderedPlan(Long tenantId, Long chatSessionId, OrderedPlanGenerateReq req) {
        return generateOrderedPlan(tenantId, chatSessionId, req, null);
    }

    private PlanningStateDTO generateOrderedPlan(Long tenantId,
                                                 Long chatSessionId,
                                                 OrderedPlanGenerateReq req,
                                                 PlanSolverResultDTO frozenResult) {
        PlanningStateDTO state = loadPlanningState(chatSessionId);
        normalizeCandidatePoolForPlanning(state);
        OrderedPlanGenerateReq safeReq = req == null ? new OrderedPlanGenerateReq() : req;
        OrderedPlanStateDTO orderedPlanState = state.getOrderedPlanState();
        if (!Boolean.TRUE.equals(safeReq.getForceRegenerate())
                && !Boolean.TRUE.equals(state.getStaleFlags().getOrderedPlan())
                && orderedPlanState.getItems() != null && !orderedPlanState.getItems().isEmpty()) {
            state.setSessionId(chatSessionId);
            return state;
        }

        Map<String, OrderedItemDTO> existing = orderedPlanState.getItems().stream()
                .collect(Collectors.toMap(OrderedItemDTO::getVolunteerId, item -> item, (left, right) -> left, LinkedHashMap::new));
        // RETRY_REPLAY（B+C：唯一不可重放的输入是 frozenResult，它由调用方持有；其余重算都在内存）
        for (int attempt = 0; attempt < WRITE_CAS_ATTEMPTS; attempt++) {
            if (attempt > 0) {
                reloadPlanningState(chatSessionId, state);
                normalizeCandidatePoolForPlanning(state);
                // 并发写者可能已经生成了排序：非强制重生时尊重对方成果，不覆盖
                OrderedPlanStateDTO latestOrdered = state.getOrderedPlanState();
                if (!Boolean.TRUE.equals(safeReq.getForceRegenerate())
                        && !Boolean.TRUE.equals(state.getStaleFlags().getOrderedPlan())
                        && latestOrdered != null && latestOrdered.getItems() != null
                        && !latestOrdered.getItems().isEmpty()) {
                    state.setSessionId(chatSessionId);
                    return state;
                }
            }
            applyOrderedPlanGeneration(tenantId, chatSessionId, state, safeReq, existing, frozenResult);
            if (saveOrderedState(chatSessionId, state, "ordered_plan_generate")) {
                state.setSessionId(chatSessionId);
                return state;
            }
        }
        throw writeCasConflict("方案排序生成");
    }

    /** 排序生成变换（纯内存，重放安全）：选择确认 → 建序列 → 单位同步 → 冻结/常规排序 → 汇总。 */
    private void applyOrderedPlanGeneration(Long tenantId,
                                            Long chatSessionId,
                                            PlanningStateDTO state,
                                            OrderedPlanGenerateReq safeReq,
                                            Map<String, OrderedItemDTO> existing,
                                            PlanSolverResultDTO frozenResult) {
        OrderedPlanStateDTO orderedPlanState = state.getOrderedPlanState();
        List<CandidateItemDTO> effectiveCandidates = resolveEffectiveCandidates(tenantId, chatSessionId, state, true);
        syncWorkingPlanWithEffectiveCandidatesForConfirmedRequirements(state, effectiveCandidates);
        if (frozenResult == null) {
            CanonicalPlanningRuntime.enforceSelection(state, effectiveCandidates);
        } else {
            CanonicalPlanningRuntime.verifyFrozenWorkingSelection(state, effectiveCandidates, frozenResult);
        }
        List<OrderedItemDTO> items = buildOrderedItemsFromWorkingPlan(state.getDraftPlanState(), state.getCandidatePoolState(), effectiveCandidates, existing,
                Boolean.TRUE.equals(safeReq.getRegroupByTier()));
        orderedPlanState.setItems(items);
        if (isMajorGroupMode(state.getCandidatePoolState())) {
            orderedPlanState.setUnits(buildOrderedUnitsFromOrderedItems(items, state.getDraftPlanState(), effectiveCandidates));
        }
        syncOrderedPlanWithEffectiveCandidatesForConfirmedRequirements(state, effectiveCandidates);
        if (frozenResult == null) {
            CanonicalPlanningRuntime.enforceOrdering(state, effectiveCandidates);
        } else {
            CanonicalPlanningRuntime.applyFrozenOrdering(state, frozenResult);
            CanonicalPlanningRuntime.verifyFrozenState(state, frozenResult);
        }
        recalculateOrderedSummary(orderedPlanState, state.getCandidatePoolState());
        state.setOrderedPlanState(orderedPlanState);
    }

    public PlanningStateDTO generateInitialPlan(Long tenantId, Long chatSessionId, InitialPlanGenerateReq req) {
        InitialPlanGenerateReq safeReq = req == null ? new InitialPlanGenerateReq() : req;
        PlanningStateDTO state = loadPlanningState(chatSessionId);
        normalizeCandidatePoolForPlanning(state);
        boolean hasDraftItems = state.getDraftPlanState() != null
                && state.getDraftPlanState().getItems() != null
                && !state.getDraftPlanState().getItems().isEmpty();
        if (hasDraftItems && !Boolean.TRUE.equals(safeReq.getOverwriteExistingDraft())) {
            return reorderDraftPlan(tenantId, chatSessionId, buildDraftPlanReorderReq(safeReq));
        }

        if (Boolean.TRUE.equals(safeReq.getForceRegenerate())
                || Boolean.TRUE.equals(state.getStaleFlags().getCandidatePool())
                || state.getCandidatePoolState() == null
                || state.getCandidatePoolState().getItems() == null
                || state.getCandidatePoolState().getItems().isEmpty()) {
            CandidatePoolGenerateReq generateReq = new CandidatePoolGenerateReq();
            generateReq.setForceRegenerate(Boolean.TRUE.equals(safeReq.getForceRegenerate()));
            state = generateCandidatePool(tenantId, chatSessionId, generateReq);
        } else if (shouldRefreshRecommendationOverlay(state)) {
            refreshRecommendationOverlay(tenantId, chatSessionId, state);
        }
        if (state.getCandidatePoolState() != null && "empty".equals(state.getCandidatePoolState().getStatusCode())) {
            state.setSessionId(chatSessionId);
            return state;
        }

        // RETRY_REPLAY：初荐重建 + 工作台替换都是纯内存派生（候选池若被并发刷新，重读后重算即可）
        applyInitialPlanGeneration(tenantId, chatSessionId, state, safeReq);
        saveWorkingPlanStateWithReplay(chatSessionId, state, "initial_plan_generate",
                latest -> applyInitialPlanGeneration(tenantId, chatSessionId, latest, safeReq));
        return reorderWorkingPlanInternal(tenantId, chatSessionId, buildDraftPlanReorderReq(safeReq), "initial_auto");
    }

    /** 初始方案生成变换（纯内存、幂等重放）：必要时重建初荐 → 用初荐替换工作台 → 重算摘要。 */
    private void applyInitialPlanGeneration(Long tenantId,
                                            Long chatSessionId,
                                            PlanningStateDTO state,
                                            InitialPlanGenerateReq safeReq) {
        if (Boolean.TRUE.equals(safeReq.getForceRegenerate())
                || Boolean.TRUE.equals(state.getStaleFlags().getInitialRecommendation())
                || state.getInitialRecommendationState() == null
                || state.getInitialRecommendationState().getItems() == null
                || state.getInitialRecommendationState().getItems().isEmpty()) {
            state.setInitialRecommendationState(buildInitialRecommendationState(state));
            state.getStaleFlags().setInitialRecommendation(false);
        }
        List<CandidateItemDTO> effectiveCandidates = resolveEffectiveCandidates(tenantId, chatSessionId, state, true);
        replaceWorkingPlanWithInitialRecommendation(state, effectiveCandidates);
        recalculateWorkingPlanSummary(state.getDraftPlanState(), state.getCandidatePoolState());
    }

    public PlanningStateDTO reorderWorkingPlan(Long tenantId, Long chatSessionId, DraftPlanReorderReq req) {
        return reorderWorkingPlanInternal(tenantId, chatSessionId, req, "draft_reorder");
    }

    /**
     * @deprecated use {@link #reorderWorkingPlan(Long, Long, DraftPlanReorderReq)}
     */
    @Deprecated
    public PlanningStateDTO reorderDraftPlan(Long tenantId, Long chatSessionId, DraftPlanReorderReq req) {
        return reorderWorkingPlan(tenantId, chatSessionId, req);
    }

    private PlanningStateDTO reorderWorkingPlanInternal(Long tenantId,
                                                        Long chatSessionId,
                                                        DraftPlanReorderReq req,
                                                        String mode) {
        DraftPlanReorderReq safeReq = req == null ? new DraftPlanReorderReq() : req;
        PlanningStateDTO state = loadPlanningState(chatSessionId);
        if (state.getDraftPlanState() == null || state.getDraftPlanState().getItems().isEmpty()) {
            state.setSessionId(chatSessionId);
            return state;
        }
        OrderedPlanGenerateReq generateReq = new OrderedPlanGenerateReq();
        generateReq.setForceRegenerate(Boolean.TRUE.equals(safeReq.getForceRegenerate()));
        generateReq.setRegroupByTier(Boolean.TRUE.equals(safeReq.getRegroupByTier()));
        // E 类嵌套写：内层 generateOrderedPlan 自己 CAS 落盘，返回态即"内层写进库里的那份"
        // （基线随之刷新），外层**不再**拿更早的快照当基线。
        state = generateOrderedPlan(tenantId, chatSessionId, generateReq);
        // 内层落盘之后仍可能有并发写者插入：输的一方重读最新，只把本方法的重排元数据域
        // 重新合到最新态上（重放幂等），再 CAS；耗尽才响亮冲突。
        for (int attempt = 0; attempt < WRITE_CAS_ATTEMPTS; attempt++) {
            if (attempt > 0) {
                reloadPlanningState(chatSessionId, state);
            }
            applyReorderOutcome(state, mode, safeReq);
            if (savePlanningState(chatSessionId, state, "reorder_working_plan")) {
                state.setSessionId(chatSessionId);
                return state;
            }
        }
        throw writeCasConflict("方案重排");
    }

    /** 重排元数据（纯内存、幂等重放）：生成方式/自动补全/人工项计数，有排序则翻 ordered。 */
    private void applyReorderOutcome(PlanningStateDTO state, String mode, DraftPlanReorderReq safeReq) {
        applyPlanGenerationMetadata(state,
                mode,
                Boolean.TRUE.equals(safeReq.getAllowAutoComplete()),
                0,
                countManualOrderedItems(state.getOrderedPlanState()));
        if (state.getOrderedPlanState() != null
                && state.getOrderedPlanState().getItems() != null
                && !state.getOrderedPlanState().getItems().isEmpty()) {
            state.setPhase("ordered");
            state.getStaleFlags().setOrderedPlan(false);
        }
    }

    @Transactional(rollbackFor = Exception.class)
    public PlanningStateDTO moveOrderedItem(Long chatSessionId, OrderedMoveReq req) {
        PlanningStateDTO state = loadPlanningState(chatSessionId);
        // RETRY_REPLAY：移动是纯内存变换（按位置重算，重放幂等），行为事件只记一次
        OrderedMovePositions positions = applyOrderedItemMove(state, req);
        if (!positions.applied) {
            state.setSessionId(chatSessionId);
            return state;
        }
        appendPlanItemsBehaviorEvent(state, null, chatSessionId, "plan_item_move",
                Lists.newArrayList(req.getVolunteerId()), false, resolveEffectiveCandidates(null, chatSessionId, state, false),
                positions.beforePositions, positions.afterPositions);
        return saveOrderedStateWithReplay(chatSessionId, state, "ordered_item_move",
                latest -> applyOrderedItemMove(latest, req));
    }

    /** 单条移动的结果位置（供行为事件；重放时忽略）。 */
    private static final class OrderedMovePositions {
        private final Map<String, Integer> beforePositions = new HashMap<String, Integer>();
        private final Map<String, Integer> afterPositions = new HashMap<String, Integer>();
        private boolean applied;
    }

    /** 移动单条志愿（纯内存、重放安全）；返回是否实际发生移动与前后位置。 */
    private OrderedMovePositions applyOrderedItemMove(PlanningStateDTO state, OrderedMoveReq req) {
        OrderedMovePositions positions = new OrderedMovePositions();
        OrderedPlanStateDTO orderedPlanState = ensureOrderedPlanState(state);
        List<OrderedItemDTO> current = new ArrayList<OrderedItemDTO>(orderedPlanState.getItems());
        OrderedItemDTO target = findOrderedItem(current, req.getVolunteerId());
        if (target == null) {
            return positions;
        }
        int currentIndex = current.indexOf(target);
        int targetIndex = OrderedPlanPositioningSupport.resolveMovableTargetIndex(current, currentIndex, req.getTargetPosition());
        if (targetIndex == currentIndex) {
            return positions;
        }
        current = OrderedPlanPositioningSupport.moveWithinUnlockedSlots(current, currentIndex, targetIndex);
        target.setOrderedBy("user");
        target.setOrderReason("user_move");
        orderedPlanState.setItems(OrderedPlanPositioningSupport.rebuildItems(current));
        recalculateOrderedSummary(orderedPlanState, state.getCandidatePoolState());
        state.setOrderedPlanState(orderedPlanState);
        ReviewInvalidationPolicy.markPlanStructureStale(state);
        positions.beforePositions.put(req.getVolunteerId(), currentIndex + 1);
        positions.afterPositions.put(req.getVolunteerId(), targetIndex + 1);
        positions.applied = true;
        return positions;
    }

    @Transactional(rollbackFor = Exception.class)
    public PlanningStateDTO moveOrderedUnit(Long chatSessionId, OrderedUnitMoveReq req) {
        PlanningStateDTO state = loadPlanningState(chatSessionId);
        // RETRY_REPLAY：整组移动是纯内存变换（按当前分组重算，重放幂等），行为事件只记一次
        OrderedUnitMoveOutcome outcome = applyOrderedUnitMove(state, chatSessionId, req);
        if (!outcome.applied) {
            state.setSessionId(chatSessionId);
            return state;
        }
        appendUnitBehaviorEvent(state, chatSessionId, "plan_unit_move", outcome.unitId, outcome.unitItems,
                outcome.candidates, outcome.beforePositions, outcome.afterPositions);
        return saveOrderedStateWithReplay(chatSessionId, state, "ordered_unit_move",
                latest -> applyOrderedUnitMove(latest, chatSessionId, req));
    }

    /** 整组移动的结果（供行为事件；重放时忽略）。 */
    private static final class OrderedUnitMoveOutcome {
        private final Map<String, Integer> beforePositions = new HashMap<String, Integer>();
        private final Map<String, Integer> afterPositions = new HashMap<String, Integer>();
        private String unitId;
        private List<OrderedItemDTO> unitItems = Lists.newArrayList();
        private List<CandidateItemDTO> candidates = Lists.newArrayList();
        private boolean applied;
    }

    /** 移动整组（纯内存、重放安全）；返回是否实际发生移动与事件载荷。 */
    private OrderedUnitMoveOutcome applyOrderedUnitMove(PlanningStateDTO state,
                                                        Long chatSessionId,
                                                        OrderedUnitMoveReq req) {
        OrderedUnitMoveOutcome outcome = new OrderedUnitMoveOutcome();
        OrderedPlanStateDTO orderedPlanState = ensureOrderedPlanState(state);
        List<OrderedItemDTO> current = defaultOrderedItems(orderedPlanState.getItems());
        String unitId = req == null ? null : req.getUnitId();
        if (Strings.isNullOrEmpty(unitId) || current.isEmpty()) {
            return outcome;
        }
        List<OrderedItemDTO> unitItems = current.stream()
                .filter(item -> unitId.equals(resolveDraftOrOrderedUnitId(item)))
                .collect(Collectors.toList());
        if (unitItems.isEmpty()) {
            return outcome;
        }
        List<String> orderedUnitIds = buildOrderedUnitIds(current);
        int currentUnitIndex = orderedUnitIds.indexOf(unitId);
        int targetUnitIndex = OrderedPlanPositioningSupport.normalizeIndex(req.getTargetPosition(), orderedUnitIds.size());
        if (currentUnitIndex < 0 || targetUnitIndex == currentUnitIndex) {
            return outcome;
        }
        List<String> nextUnitIds = new ArrayList<String>(orderedUnitIds);
        nextUnitIds.remove(currentUnitIndex);
        nextUnitIds.add(targetUnitIndex, unitId);
        Map<String, List<OrderedItemDTO>> groupedItems = current.stream()
                .collect(Collectors.groupingBy(this::resolveDraftOrOrderedUnitId, LinkedHashMap::new, Collectors.toList()));
        List<OrderedItemDTO> moved = Lists.newArrayList();
        for (String nextUnitId : nextUnitIds) {
            List<OrderedItemDTO> nextItems = groupedItems.get(nextUnitId);
            if (nextItems != null) {
                moved.addAll(nextItems);
            }
        }
        for (OrderedItemDTO item : unitItems) {
            item.setOrderedBy("user");
            item.setOrderReason("user_unit_move");
        }
        List<CandidateItemDTO> candidates = resolveEffectiveCandidates(null, chatSessionId, state, false);
        orderedPlanState.setItems(OrderedPlanPositioningSupport.rebuildItems(moved));
        orderedPlanState.setUnits(buildOrderedUnitsFromOrderedItems(orderedPlanState.getItems(), state.getDraftPlanState(), candidates));
        recalculateOrderedSummary(orderedPlanState, state.getCandidatePoolState());
        state.setOrderedPlanState(orderedPlanState);
        ReviewInvalidationPolicy.markPlanStructureStale(state);
        outcome.unitId = unitId;
        outcome.unitItems = unitItems;
        outcome.candidates = candidates;
        outcome.beforePositions.put(unitId, currentUnitIndex + 1);
        outcome.afterPositions.put(unitId, targetUnitIndex + 1);
        outcome.applied = true;
        return outcome;
    }

    @Transactional(rollbackFor = Exception.class)
    public PlanningStateDTO removeOrderedUnits(Long chatSessionId, OrderedUnitRemoveReq req) {
        PlanningStateDTO state = loadPlanningState(chatSessionId);
        // RETRY_REPLAY：整组移除是纯内存变换（按当前分组过滤，重放幂等），行为事件只记一次
        List<OrderedItemDTO> removedItems = applyOrderedUnitRemoval(state, chatSessionId, req);
        if (removedItems.isEmpty()) {
            state.setSessionId(chatSessionId);
            return state;
        }
        Set<String> unitIds = new LinkedHashSet<String>(defaultList(req == null ? null : req.getUnitIds()));
        List<CandidateItemDTO> candidates = resolveEffectiveCandidates(null, chatSessionId, state, false);
        for (String unitId : unitIds) {
            List<OrderedItemDTO> removedUnitItems = removedItems.stream()
                    .filter(item -> unitId.equals(resolveDraftOrOrderedUnitId(item)))
                    .collect(Collectors.toList());
            if (!removedUnitItems.isEmpty()) {
                appendUnitBehaviorEvent(state, chatSessionId, "plan_unit_remove", unitId, removedUnitItems, candidates, null, null);
            }
        }
        return saveOrderedStateWithReplay(chatSessionId, state, "ordered_unit_remove",
                latest -> applyOrderedUnitRemoval(latest, chatSessionId, req));
    }

    /** 移除整组（纯内存、重放安全）；返回本次实际移除的排序项（空=无变化）。 */
    private List<OrderedItemDTO> applyOrderedUnitRemoval(PlanningStateDTO state,
                                                         Long chatSessionId,
                                                         OrderedUnitRemoveReq req) {
        OrderedPlanStateDTO orderedPlanState = ensureOrderedPlanState(state);
        Set<String> unitIds = new LinkedHashSet<String>(defaultList(req == null ? null : req.getUnitIds()));
        if (unitIds.isEmpty()) {
            return Lists.newArrayList();
        }
        List<OrderedItemDTO> removedItems = defaultOrderedItems(orderedPlanState.getItems()).stream()
                .filter(item -> unitIds.contains(resolveDraftOrOrderedUnitId(item)))
                .collect(Collectors.toList());
        if (removedItems.isEmpty()) {
            return removedItems;
        }
        orderedPlanState.setItems(OrderedPlanPositioningSupport.rebuildItems(defaultOrderedItems(orderedPlanState.getItems()).stream()
                .filter(item -> !unitIds.contains(resolveDraftOrOrderedUnitId(item)))
                .collect(Collectors.toList())));
        DraftPlanStateDTO draft = state.getDraftPlanState();
        draft.setItems(defaultDraftItems(draft.getItems()).stream()
                .filter(item -> !unitIds.contains(resolveDraftOrOrderedUnitId(item)))
                .collect(Collectors.toList()));
        List<CandidateItemDTO> candidates = resolveEffectiveCandidates(null, chatSessionId, state, false);
        syncWorkingPlanUnitsWithItems(draft, candidates, state.getCandidatePoolState());
        recalculateWorkingPlanSummary(draft, state.getCandidatePoolState());
        orderedPlanState.setUnits(buildOrderedUnitsFromOrderedItems(orderedPlanState.getItems(), draft, candidates));
        recalculateOrderedSummary(orderedPlanState, state.getCandidatePoolState());
        state.setWorkingPlanState(draft);
        state.setOrderedPlanState(orderedPlanState);
        ReviewInvalidationPolicy.markPlanStructureStale(state);
        return removedItems;
    }

    @Transactional(rollbackFor = Exception.class)
    public PlanningStateDTO sortOrderedPlan(Long chatSessionId, OrderedPlanSortReq req) {
        PlanningStateDTO state = loadPlanningState(chatSessionId);
        // RETRY_REPLAY：排序是纯内存变换（按当前态重排，重放幂等），行为事件只记一次
        OrderedPlanSortOutcome outcome = applyOrderedPlanSort(state, chatSessionId, req);
        if (!outcome.applied) {
            state.setSessionId(chatSessionId);
            return state;
        }
        appendPlanSortApplyEvent(state, chatSessionId, outcome.sortField, outcome.beforePositions,
                outcome.orderedPlanState, outcome.candidates);
        return saveOrderedStateWithReplay(chatSessionId, state, "ordered_sort",
                latest -> applyOrderedPlanSort(latest, chatSessionId, req));
    }

    /** 排序的结果载荷（供行为事件；重放时忽略）。 */
    private static final class OrderedPlanSortOutcome {
        private Map<String, Integer> beforePositions = new HashMap<String, Integer>();
        private String sortField;
        private OrderedPlanStateDTO orderedPlanState;
        private List<CandidateItemDTO> candidates = Lists.newArrayList();
        private boolean applied;
    }

    /** 排序变换（纯内存、重放安全）；返回是否实际发生排序与事件载荷。 */
    private OrderedPlanSortOutcome applyOrderedPlanSort(PlanningStateDTO state,
                                                        Long chatSessionId,
                                                        OrderedPlanSortReq req) {
        OrderedPlanSortOutcome outcome = new OrderedPlanSortOutcome();
        OrderedPlanStateDTO orderedPlanState = ensureOrderedPlanState(state);
        List<OrderedItemDTO> current = defaultOrderedItems(orderedPlanState.getItems());
        if (current.isEmpty()) {
            return outcome;
        }
        String sortField = normalizeOrderedSortField(req == null ? null : req.getSortField());
        Map<String, Integer> beforePositions = buildOrderedPositionMap(current);
        List<CandidateItemDTO> candidates = resolveEffectiveCandidates(null, chatSessionId, state, false);
        List<OrderedItemDTO> sorted = isMajorGroupMode(state.getCandidatePoolState())
                ? sortOrderedPlanByUnit(current, orderedPlanState, state.getDraftPlanState(), candidates, sortField)
                : sortOrderedPlanItems(current, candidates, sortField);
        orderedPlanState.setItems(OrderedPlanPositioningSupport.rebuildItems(sorted));
        orderedPlanState.setUnits(buildOrderedUnitsFromOrderedItems(orderedPlanState.getItems(), state.getDraftPlanState(), candidates));
        recalculateOrderedSummary(orderedPlanState, state.getCandidatePoolState());
        state.setOrderedPlanState(orderedPlanState);
        markOrderedItemsSortedByUser(orderedPlanState, sortField);
        ReviewInvalidationPolicy.markPlanStructureStale(state);
        outcome.sortField = sortField;
        outcome.beforePositions = beforePositions;
        outcome.orderedPlanState = orderedPlanState;
        outcome.candidates = candidates;
        outcome.applied = true;
        return outcome;
    }

    public OrderedPlanActionRes buildOrderedPlanActionRes(PlanningStateDTO state) {
        OrderedPlanActionRes res = new OrderedPlanActionRes();
        res.setSessionId(state.getSessionId());
        res.setVersion(state.getVersion());
        res.setPhase(state.getPhase());
        res.setStaleFlags(state.getStaleFlags());
        res.setWorkingPlanState(state.getWorkingPlanState());
        res.setOrderedPlanState(state.getOrderedPlanState());
        return res;
    }

    public ReviewStateDTO runReview(Long tenantId, Long chatSessionId) {
        PlanningStateDTO state = loadPlanningState(chatSessionId);
        ReviewStateDTO reviewState = runReviewInternal(tenantId, chatSessionId, state);
        // B+C：审查结论以**最新态**重算（resolveEffectiveCandidates 读外部/缓存，不重放旧快照结论）；
        // 用户动作 -> 重试耗尽响亮冲突
        for (int attempt = 0; attempt < WRITE_CAS_ATTEMPTS; attempt++) {
            if (attempt > 0) {
                reloadPlanningState(chatSessionId, state);
                reviewState = runReviewInternal(tenantId, chatSessionId, state);
            }
            if (savePlanningState(chatSessionId, state, "review_run")) {
                return reviewState;
            }
        }
        throw writeCasConflict("方案审查");
    }

    /** 审查计算（纯内存；以传入 state 为事实来源），并把结论与版本/阶段写回 state。 */
    private ReviewStateDTO runReviewInternal(Long tenantId, Long chatSessionId, PlanningStateDTO state) {
        normalizeCandidatePoolForPlanning(state);
        List<CandidateItemDTO> effectiveCandidates = resolveEffectiveCandidates(tenantId, chatSessionId, state, true);
        ReviewStateDTO reviewState = new ReviewStateDTO();
        reviewState.setStatus("completed");
        reviewState.setReviewedAt(OffsetDateTime.now().toString());
        reviewState.setSourceVersion(state.getVersion());

        OrderedPlanStateDTO structuralOrderedState = buildStructuralOrderedSnapshot(state.getCandidatePoolState(),
                state.getOrderedPlanState(),
                effectiveCandidates);
        PlanningStateDTO structuralState = buildPlanAdjustmentAnalysisState(state, structuralOrderedState);

        List<ReviewCheckDTO> checks = Lists.newArrayList();
        checks.add(reviewRatioDistribution(structuralState));
        checks.add(reviewSafetyGuard(structuralState, effectiveCandidates));
        checks.add(reviewProbabilityInversion(structuralState, effectiveCandidates));
        checks.add(reviewProbabilityGap(structuralState, effectiveCandidates));
        checks.add(reviewCountValidation(structuralState, effectiveCandidates));
        checks.add(reviewHighTuition(state, effectiveCandidates));
        checks.add(reviewAdmissionLimit(state, effectiveCandidates));
        checks.add(reviewSpecialEnrollment(state, effectiveCandidates));
        checks.add(reviewEdgeScore(state));
        checks.add(reviewCooperativeProgram(state, effectiveCandidates));
        checks.add(reviewGroupInnerSafetyGuard(state, effectiveCandidates));
        checks.add(reviewMajorGroupSafetyIntentAlignment(state));
        checks.add(buildFixedNoticeCheck("plan_update_notice", "info", "招生计划代码可能动态更新",
                "填报期间可能存在官方招生计划代码更新，建议同步查阅教育考试院官网。"));
        checks.add(buildFixedNoticeCheck("adjustment_notice", "info", "当前方案存在调剂风险提示",
                "正式填报存在调剂风险，建议结合个人专业偏好谨慎确认是否服从调剂。"));
        reviewState.setChecks(checks);
        CompensationPreviewDTO compensationPreview = buildCompensationPreview(structuralState, effectiveCandidates);
        reviewState.setCompensationPreview(compensationPreview);
        attachCompensationsToReviewChecks(reviewState, compensationPreview);
        enrichReviewMetadata(reviewState);
        normalizeReviewReasonCodes(structuralState, reviewState);
        recalculateReviewSummary(reviewState);

        state.setReviewState(reviewState);
        state.setSessionId(chatSessionId);
        state.setVersion((state.getVersion() == null ? 0 : state.getVersion()) + 1);
        state.setPhase("reviewed");
        state.getStaleFlags().setReview(false);
        return reviewState;
    }

    /**
     * 偏好变更落盘（H2 A 类站点：纯内存变换，可重放）。
     *
     * <p>调用方先把本次变更施加到 {@code state} 上（首次尝试），冲突时本方法重读最新行、
     * 由 {@code reapply} 把同一变换重新施加到最新态上再 CAS（≤{@value #WRITE_CAS_ATTEMPTS} 次；
     * 重复施加幂等：hydrate 只补空、偏好合并按 add-unique）。重试耗尽**响亮冲突**（40901 语义面）：
     * 用户的偏好变更绝不静默丢。</p>
     */
    private PlanningStateVersionDTO touchAndSavePreference(Long chatSessionId,
                                                           PlanningStateDTO state,
                                                           Consumer<PlanningStateDTO> reapply) {
        for (int attempt = 0; attempt < WRITE_CAS_ATTEMPTS; attempt++) {
            if (attempt > 0) {
                reloadPlanningState(chatSessionId, state);
                if (reapply != null) {
                    reapply.accept(state);
                }
            }
            state.setSessionId(chatSessionId);
            state.setVersion((state.getVersion() == null ? 0 : state.getVersion()) + 1);
            state.setPhase("profile_ready");
            ReviewInvalidationPolicy.markPreferenceIntentStale(state);
            if (savePlanningState(chatSessionId, state, "touch_preference")) {
                PlanningStateVersionDTO versionDTO = new PlanningStateVersionDTO();
                versionDTO.setVersion(state.getVersion());
                versionDTO.setStaleFlags(state.getStaleFlags());
                return versionDTO;
            }
        }
        throw writeCasConflict("偏好变更");
    }

    private PlanningStateVersionDTO touchAndSaveConstraint(Long chatSessionId,
                                                           PlanningStateDTO state,
                                                           Consumer<PlanningStateDTO> reapply) {
        for (int attempt = 0; attempt < WRITE_CAS_ATTEMPTS; attempt++) {
            if (attempt > 0) {
                reloadPlanningState(chatSessionId, state);
                if (reapply != null) {
                    reapply.accept(state);
                }
            }
            state.setSessionId(chatSessionId);
            state.setVersion((state.getVersion() == null ? 0 : state.getVersion()) + 1);
            state.setPhase("profile_ready");
            ReviewInvalidationPolicy.markConstraintIntentStale(state);
            if (savePlanningState(chatSessionId, state, "touch_constraint")) {
                PlanningStateVersionDTO versionDTO = new PlanningStateVersionDTO();
                versionDTO.setVersion(state.getVersion());
                versionDTO.setStaleFlags(state.getStaleFlags());
                return versionDTO;
            }
        }
        throw writeCasConflict("约束变更");
    }

    private RecommendationOverlayStateDTO buildRecommendationOverlayState(CandidatePoolStateDTO candidatePoolState,
                                                                          Integer currentVersion) {
        RecommendationOverlayStateDTO overlayState = new RecommendationOverlayStateDTO();
        overlayState.setGeneratedAt(OffsetDateTime.now().toString());
        overlayState.setSourceVersion(currentVersion == null ? 0 : currentVersion + 1);
        overlayState.setProfileVersion(currentVersion == null ? 0 : currentVersion);

        List<CandidateItemDTO> items = candidatePoolState == null ? Lists.newArrayList() : candidatePoolState.getItems();
        int preferredCount = 0;
        for (CandidateItemDTO candidate : items) {
            RecommendationOverlayStateDTO.Item overlayItem = new RecommendationOverlayStateDTO.Item();
            overlayItem.setVolunteerId(candidate.getVolunteerId());
            overlayItem.setBaseScore(candidate.getBaseScore());
            overlayItem.setIntentScore(candidate.getIntentScore());
            overlayItem.setFinalScore(candidate.getFinalScore());
            overlayItem.setRankInTier(candidate.getRankInTier());
            overlayItem.setPreferred(candidate.getPreferred());
            overlayItem.setReasonCodes(defaultList(candidate.getReasonCodes()));
            overlayItem.setSchoolRankTags(defaultList(candidate.getSchoolRankTags()));
            overlayItem.setMajorRankTags(defaultList(candidate.getMajorRankTags()));
            overlayState.getItems().add(overlayItem);

            if (Boolean.TRUE.equals(candidate.getPreferred())) {
                preferredCount++;
                String tier = Strings.isNullOrEmpty(candidate.getTier()) ? "未知" : candidate.getTier();
                overlayState.getSummary().getTierPreferredCounts().merge(tier, 1, Integer::sum);
            }
        }
        overlayState.getSummary().setTotal(overlayState.getItems().size());
        overlayState.getSummary().setPreferredCount(preferredCount);
        return overlayState;
    }

    private RecommendationOverlayStateDTO buildRecommendationOverlayState(VolunteerRecommendListResponse response,
                                                                          Integer currentVersion) {
        CandidatePoolStateDTO candidatePoolState = new CandidatePoolStateDTO();
        candidatePoolState.setVolunteerModel(response != null && response.getBaseData() != null
                && response.getBaseData().getVolunteerModel() != null
                ? response.getBaseData().getVolunteerModel().getCode() : null);
        List<CandidateItemDTO> items = Lists.newArrayList();
        if (response != null) {
            items.addAll(flattenCandidates(response.getSprints(), "冲"));
            items.addAll(flattenCandidates(response.getSafes(), "稳"));
            items.addAll(flattenCandidates(response.getProtects(), "保"));
        }
        candidatePoolState.setItems(normalizeCandidateIdentities(candidatePoolState, items));
        return buildRecommendationOverlayState(candidatePoolState, currentVersion);
    }

    private InitialRecommendationStateDTO buildInitialRecommendationState(PlanningStateDTO state) {
        if (isMajorGroupMode(state.getCandidatePoolState())) {
            return buildInitialRecommendationStateForMajorGroup(state);
        }
        return buildInitialRecommendationStateForFlatCandidates(state);
    }

    private InitialRecommendationStateDTO buildInitialRecommendationStateForFlatCandidates(PlanningStateDTO state) {
        InitialRecommendationStateDTO recommendationState = new InitialRecommendationStateDTO();
        recommendationState.setGeneratedAt(OffsetDateTime.now().toString());
        recommendationState.setSourceVersion(state.getVersion() == null ? 0 : state.getVersion());
        recommendationState.setCandidateViewVersion(state.getVersion() == null ? 0 : state.getVersion());
        recommendationState.setProfileVersion(state.getVersion() == null ? 0 : state.getVersion());
        initializeTierCounts(recommendationState.getSummary().getTierCounts());
        List<CandidateItemDTO> candidates = mergeOverlayIntoCandidates(
                state.getCandidatePoolState().getItems(),
                state.getRecommendationOverlayState(),
                state);
        candidates = applyConfirmedPlanRequirements(candidates, state.getSessionId(), state);
        InitialRecommendationSelectionState selectionState = buildInitialRecommendationSelectionState(state, candidates);
        recommendationState.getSummary().setTotal(selectionState.selected.size());
        recommendationState.getSummary().setLocalProtectCount(countLocalProtectCandidates(selectionState.selected,
                state.getCandidatePoolState().getSourceProvinceName()));
        recommendationState.getSummary().setGapFixCount(selectionState.gapFixCount);
        recommendationState.getSummary().setUnresolvedGapCount(selectionState.unresolvedGapCount);
        recommendationState.getSummary().setUnitCompletionCount(selectionState.unitCompletionCount);
        recommendationState.getSummary().setAppliedRepairCount(selectionState.appliedRepairCount);
        recommendationState.getSummary().setUnresolvedRuleCodes(Lists.newArrayList(selectionState.unresolvedRuleCodes));
        recommendationState.setStrategyReport(buildInitialPlanStrategyReport(selectionState,
                selectionState.selected.size(),
                selectionState.unresolvedRuleCodes));
        for (CandidateItemDTO candidate : selectionState.selected) {
            InitialRecommendationItemDTO item = new InitialRecommendationItemDTO();
            item.setVolunteerId(candidate.getVolunteerId());
            item.setComboScore(candidate.getFinalScore());
            item.setRecommendTier(candidate.getTier());
            List<String> reasonCodes = Lists.newArrayList(defaultList(candidate.getReasonCodes()));
            reasonCodes.addAll(resolveInitialRecommendationReasonCodes(selectionState, candidate));
            item.setReasonCodes(reasonCodes);
            recommendationState.getItems().add(item);
            recommendationState.getSummary().setExpertPreferredCount(
                    recommendationState.getSummary().getExpertPreferredCount() + 1);
            String tier = Strings.isNullOrEmpty(candidate.getTier()) ? "未知" : candidate.getTier();
            recommendationState.getSummary().getTierCounts().merge(tier, 1, Integer::sum);
        }
        return recommendationState;
    }

    private InitialRecommendationStateDTO buildInitialRecommendationStateForMajorGroup(PlanningStateDTO state) {
        InitialRecommendationStateDTO recommendationState = new InitialRecommendationStateDTO();
        recommendationState.setGeneratedAt(OffsetDateTime.now().toString());
        recommendationState.setSourceVersion(state.getVersion() == null ? 0 : state.getVersion());
        recommendationState.setCandidateViewVersion(state.getVersion() == null ? 0 : state.getVersion());
        recommendationState.setProfileVersion(state.getVersion() == null ? 0 : state.getVersion());
        initializeTierCounts(recommendationState.getSummary().getTierCounts());

        List<CandidateItemDTO> candidates = mergeOverlayIntoCandidates(
                state.getCandidatePoolState().getItems(),
                state.getRecommendationOverlayState(),
                state);
        candidates = applyConfirmedPlanRequirements(candidates, state.getSessionId(), state);
        MajorGroupInitialRecommendationSelection selection = buildMajorGroupInitialRecommendationSelection(state, candidates);
        recommendationState.setUnits(Lists.newArrayList(selection.selectedUnits));

        recommendationState.getSummary().setTotal(selection.selectedUnits.size());
        recommendationState.getSummary().setLocalProtectCount((int) selection.selectedUnits.stream()
                .filter(unit -> containsIgnoreCase(unit == null ? null : unit.getProvinceName(),
                        state.getCandidatePoolState().getSourceProvinceName()))
                .count());
        recommendationState.getSummary().setGapFixCount(selection.groupSelectionState.gapFixCount);
        recommendationState.getSummary().setUnresolvedGapCount(selection.groupSelectionState.unresolvedGapCount);
        recommendationState.getSummary().setUnitCompletionCount(selection.selectedUnits.size());
        recommendationState.getSummary().setAppliedRepairCount(selection.groupSelectionState.appliedRepairCount + selection.majorSelectionRepairCount);
        recommendationState.getSummary().setUnresolvedRuleCodes(Lists.newArrayList(selection.unresolvedRuleCodes));
        recommendationState.setStrategyReport(buildInitialPlanStrategyReport(selection.groupSelectionState,
                selection.selectedUnits.size(),
                selection.unresolvedRuleCodes));
        recommendationState.getSummary().setExpertPreferredCount(selection.selectedUnits.size());
        Map<String, Integer> tierCounts = countUnitTierCounts(selection.selectedUnits);
        for (Map.Entry<String, Integer> entry : tierCounts.entrySet()) {
            recommendationState.getSummary().getTierCounts().put(entry.getKey(), entry.getValue());
        }

        for (PlanningUnitDTO unit : selection.selectedUnits) {
            List<String> unitReasonCodes = selection.groupSelectionState.selectionReasons.getOrDefault(
                    unit.getUnitId(),
                    Lists.newArrayList("selected_by_tier_target"));
            for (PlanningUnitMajorDTO major : defaultPlanningUnitMajors(unit.getSelectedMajors())) {
                InitialRecommendationItemDTO item = new InitialRecommendationItemDTO();
                item.setVolunteerId(major.getVolunteerId());
                item.setComboScore(major.getFinalScore());
                item.setRecommendTier(Strings.isNullOrEmpty(unit.getTier()) ? major.getTier() : unit.getTier());
                item.setReasonCodes(Lists.newArrayList(unitReasonCodes));
                recommendationState.getItems().add(item);
            }
        }
        return recommendationState;
    }

    private InitialPlanStrategyReportDTO buildInitialPlanStrategyReport(InitialRecommendationSelectionState selectionState,
                                                                        int selectedCount,
                                                                        List<String> unresolvedRuleCodes) {
        InitialPlanStrategyReportDTO report = new InitialPlanStrategyReportDTO();
        if (selectionState == null) {
            return report;
        }
        report.getTargetProfile().setTargetCount(selectionState.targetCount);
        report.getTargetProfile().setTargetTierCounts(new LinkedHashMap<String, Integer>(selectionState.targetTierCounts));
        report.getTargetProfile().setSourceProvinceName(selectionState.sourceProvinceName);
        report.getTargetProfile().setVolunteerModel(selectionState.volunteerModel);
        report.getTargetProfile().setRequiredMajorCount(selectionState.requiredMajorCount);
        report.setObjectiveWeights(buildInitialPlanObjectiveWeights(selectionState));
        report.setSelectedCount(selectedCount);
        report.setAppliedRepairs(Lists.newArrayList(selectionState.appliedRepairs));
        report.setActions(Lists.newArrayList(selectionState.actions));
        report.setTradeoffs(Lists.newArrayList(selectionState.tradeoffs));
        report.setCandidateShortages(buildInitialPlanCandidateShortages(selectionState,
                selectedCount,
                unresolvedRuleCodes));

        for (String ruleCode : defaultList(unresolvedRuleCodes)) {
            InitialPlanStrategyReportDTO.UnresolvedRisk risk = new InitialPlanStrategyReportDTO.UnresolvedRisk();
            risk.setRuleCode(ruleCode);
            risk.setDetail(resolveInitialPlanUnresolvedRiskDetail(ruleCode));
            report.getUnresolvedRisks().add(risk);
        }
        if (!report.getAppliedRepairs().isEmpty()) {
            report.getUserAttentionMessages().add(String.format("生成初始推荐时已为降低结构风险调整 %d 个候选。",
                    report.getAppliedRepairs().size()));
        }
        if (!report.getUnresolvedRisks().isEmpty()) {
            report.getUserAttentionMessages().add(String.format("仍有 %d 类风险需要结合审查结果继续关注。",
                    report.getUnresolvedRisks().size()));
        }
        if (report.getAppliedRepairs().isEmpty() && report.getUnresolvedRisks().isEmpty()) {
            report.getUserAttentionMessages().add("初始推荐已按目标数量、冲稳保和基础安全性完成校验。");
        }
        return report;
    }

    private List<InitialPlanStrategyReportDTO.ObjectiveWeight> buildInitialPlanObjectiveWeights(InitialRecommendationSelectionState selectionState) {
        List<InitialPlanStrategyReportDTO.ObjectiveWeight> weights = Lists.newArrayList();
        addInitialPlanObjectiveWeight(weights,
                "tier_structure",
                "冲稳保结构",
                0.24D,
                1,
                "先按目标冲稳保数量分桶选择，并在生成阶段尝试补齐结构缺口。");
        addInitialPlanObjectiveWeight(weights,
                "preference_match",
                "偏好和专家优选",
                0.18D,
                2,
                "同层候选优先保留已确认偏好或专家优选命中的方向。");
        addInitialPlanObjectiveWeight(weights,
                "admission_safety",
                "录取安全和梯度",
                0.18D,
                3,
                "生成后会尝试修复录取率倒挂和录取率梯度断层。");
        addInitialPlanObjectiveWeight(weights,
                "future_development",
                "发展前景",
                0.14D,
                4,
                "同层候选排序会参考专业未来发展分。");
        addInitialPlanObjectiveWeight(weights,
                "recommend_score",
                "推荐系数",
                0.14D,
                5,
                "同层候选排序会参考综合推荐分，但不会单独压过安全结构。");
        addInitialPlanObjectiveWeight(weights,
                "local_safety",
                "本省和保底安全垫",
                0.07D,
                6,
                "低分段会额外关注本省或保底候选数量。");
        if (selectionState != null && "majorGroup".equalsIgnoreCase(selectionState.volunteerModel)) {
            addInitialPlanObjectiveWeight(weights,
                    "major_group_inner_safety",
                    "专业组内安全专业",
                    0.05D,
                    7,
                    "专业组模式下会关注组内是否有录取率不低于组整体录取率的专业。");
        }
        return weights;
    }

    private void addInitialPlanObjectiveWeight(List<InitialPlanStrategyReportDTO.ObjectiveWeight> weights,
                                               String code,
                                               String label,
                                               Double relativeWeight,
                                               Integer priority,
                                               String description) {
        InitialPlanStrategyReportDTO.ObjectiveWeight weight = new InitialPlanStrategyReportDTO.ObjectiveWeight();
        weight.setCode(code);
        weight.setLabel(label);
        weight.setRelativeWeight(relativeWeight);
        weight.setPriority(priority);
        weight.setDescription(description);
        weights.add(weight);
    }

    private List<CandidateShortageDTO> buildInitialPlanCandidateShortages(InitialRecommendationSelectionState selectionState,
                                                                          int selectedCount,
                                                                          List<String> unresolvedRuleCodes) {
        List<CandidateShortageDTO> shortages = Lists.newArrayList();
        if (selectionState == null || unresolvedRuleCodes == null || unresolvedRuleCodes.isEmpty()) {
            return shortages;
        }
        for (String ruleCode : defaultList(unresolvedRuleCodes)) {
            if ("count_validation".equals(ruleCode)) {
                addInitialPlanCountShortage(shortages, selectionState, selectedCount);
            } else if ("safety_guard".equals(ruleCode)) {
                addInitialPlanSafetyShortage(shortages, selectionState);
            } else if ("ratio_distribution".equals(ruleCode)) {
                addInitialPlanTierShortages(shortages, selectionState);
            } else if ("probability_gap".equals(ruleCode)) {
                addInitialPlanProbabilityGapShortage(shortages, selectionState);
            } else if ("probability_inversion".equals(ruleCode)) {
                addInitialPlanShortage(shortages,
                        "probability_inversion",
                        "capacity_or_replacement",
                        "no_sort_or_replacement_candidate",
                        null,
                        null,
                        null,
                        null,
                        countInitialPlanAvailableCandidates(selectionState),
                        "初始推荐仍有录取率倒挂，当前缺少可安全替换或重排的候选。");
            } else if ("group_inner_safety_guard".equals(ruleCode)) {
                addInitialPlanShortage(shortages,
                        "group_inner_safety_guard",
                        "candidate_pool",
                        "major_group_safety_candidate_insufficient",
                        null,
                        null,
                        null,
                        null,
                        null,
                        "部分专业组内缺少录取率不低于专业组整体录取率的安全专业。");
            }
        }
        return shortages;
    }

    private void addInitialPlanCountShortage(List<CandidateShortageDTO> shortages,
                                             InitialRecommendationSelectionState selectionState,
                                             int selectedCount) {
        int required = Math.max(0, selectionState.targetCount);
        int shortageCount = Math.max(0, required - selectedCount);
        if (shortageCount <= 0) {
            return;
        }
        addInitialPlanShortage(shortages,
                "count_validation",
                "candidate_pool",
                "candidate_pool_insufficient",
                null,
                required,
                selectedCount,
                shortageCount,
                countInitialPlanAvailableCandidates(selectionState),
                "当前可用于规划的候选池里，初始方案目标数量暂时补不齐。");
    }

    private void addInitialPlanSafetyShortage(List<CandidateShortageDTO> shortages,
                                              InitialRecommendationSelectionState selectionState) {
        if (selectionState.userScore != null && selectionState.userScore >= 580) {
            return;
        }
        if (Strings.isNullOrEmpty(selectionState.sourceProvinceName)) {
            return;
        }
        int required = 2;
        int current = countLocalProtectCandidates(selectionState.selected, selectionState.sourceProvinceName);
        int shortageCount = Math.max(0, required - current);
        if (shortageCount <= 0) {
            return;
        }
        int available = (int) defaultCandidates(selectionState.selected).stream()
                .filter(candidate -> isLocalProtectCandidate(candidate, selectionState.sourceProvinceName))
                .count()
                + (int) defaultCandidates(selectionState.remaining).stream()
                .filter(candidate -> isLocalProtectCandidate(candidate, selectionState.sourceProvinceName))
                .count();
        addInitialPlanShortage(shortages,
                "safety_guard",
                "candidate_pool",
                "safety_candidate_insufficient",
                "保",
                required,
                current,
                shortageCount,
                available,
                "当前可用于规划的候选池里，本省或保底安全垫候选不足。");
    }

    private void addInitialPlanTierShortages(List<CandidateShortageDTO> shortages,
                                             InitialRecommendationSelectionState selectionState) {
        Map<String, Integer> currentCounts = countInitialRecommendationTiers(selectionState.selected);
        List<CandidateItemDTO> availableCandidates = Lists.newArrayList();
        availableCandidates.addAll(defaultCandidates(selectionState.selected));
        availableCandidates.addAll(defaultCandidates(selectionState.remaining));
        for (String tier : Lists.newArrayList("冲", "稳", "保")) {
            int required = selectionState.targetTierCounts.getOrDefault(tier, 0);
            int current = currentCounts.getOrDefault(tier, 0);
            int shortageCount = Math.max(0, required - current);
            if (shortageCount <= 0) {
                continue;
            }
            int available = (int) availableCandidates.stream()
                    .filter(candidate -> tier.equals(candidate == null || Strings.isNullOrEmpty(candidate.getTier())
                            ? "保" : candidate.getTier()))
                    .count();
            addInitialPlanShortage(shortages,
                    "ratio_distribution",
                    "candidate_pool",
                    "tier_candidate_insufficient",
                    tier,
                    required,
                    current,
                    shortageCount,
                    available,
                    "当前可用于规划的候选池里，目标" + tier + "区候选不足。");
        }
    }

    private void addInitialPlanProbabilityGapShortage(List<CandidateShortageDTO> shortages,
                                                      InitialRecommendationSelectionState selectionState) {
        int required = selectionState.unresolvedGapCount > 0 ? selectionState.unresolvedGapCount : 1;
        int available = countInitialPlanGapFillCandidates(selectionState);
        String scope = available > 0 ? "capacity_or_replacement" : "candidate_pool";
        String reasonCode = available > 0 ? "replacement_pair_missing" : "probability_gap_candidate_insufficient";
        String message = available > 0
                ? "当前不是单纯缺候选，而是初始推荐缺少可安全一进一出的梯度修复配对。"
                : "当前可用于规划的候选池里，断层中间录取率候选不足。";
        addInitialPlanShortage(shortages,
                "probability_gap",
                scope,
                reasonCode,
                null,
                required,
                0,
                required,
                available,
                message);
    }

    private int countInitialPlanGapFillCandidates(InitialRecommendationSelectionState selectionState) {
        if (selectionState == null) {
            return 0;
        }
        List<InitialRecommendationGap> gaps = findInitialRecommendationGaps(selectionState.selected);
        if (gaps.isEmpty()) {
            return 0;
        }
        return (int) defaultCandidates(selectionState.remaining).stream()
                .filter(candidate -> findCoveringInitialRecommendationGap(gaps, candidate) != null)
                .count();
    }

    private int countInitialPlanAvailableCandidates(InitialRecommendationSelectionState selectionState) {
        if (selectionState == null) {
            return 0;
        }
        return defaultCandidates(selectionState.selected).size() + defaultCandidates(selectionState.remaining).size();
    }

    private void addInitialPlanShortage(List<CandidateShortageDTO> shortages,
                                        String sourceCheckCode,
                                        String scope,
                                        String reasonCode,
                                        String targetTier,
                                        Integer requiredCount,
                                        Integer currentCount,
                                        Integer shortageCount,
                                        Integer availableCount,
                                        String message) {
        CandidateShortageDTO shortage = new CandidateShortageDTO();
        shortage.setStrategy("initial_plan_generation");
        shortage.setSourceCheckCode(sourceCheckCode);
        shortage.setScope(scope);
        shortage.setReasonCode(reasonCode);
        shortage.setTargetTier(targetTier);
        shortage.setRequiredCount(requiredCount);
        shortage.setCurrentCount(currentCount);
        shortage.setShortageCount(shortageCount);
        shortage.setAvailableCount(availableCount);
        shortage.setMessage(message);
        shortages.add(shortage);
    }

    private String resolveInitialPlanUnresolvedRiskDetail(String ruleCode) {
        if ("safety_guard".equals(ruleCode)) {
            return "当前候选中本省或保底候选不足，初始推荐无法完全补足安全垫。";
        }
        if ("probability_inversion".equals(ruleCode)) {
            return "当前候选录取率排序仍存在倒挂，需要后续审查或排序继续处理。";
        }
        if ("probability_gap".equals(ruleCode)) {
            return "当前候选录取率梯度仍有断层，可替换的中间候选不足。";
        }
        if ("ratio_distribution".equals(ruleCode)) {
            return "当前候选无法完全满足目标冲稳保比例。";
        }
        if ("group_inner_safety_guard".equals(ruleCode)) {
            return "部分专业组内缺少录取率不低于专业组整体录取率的安全专业。";
        }
        return "初始推荐阶段仍有该规则相关风险未完全解决。";
    }

    private InitialRecommendationSelectionState buildInitialRecommendationSelectionState(PlanningStateDTO state,
                                                                                         List<CandidateItemDTO> candidates) {
        InitialRecommendationSelectionState selectionState = new InitialRecommendationSelectionState();
        selectionState.targetCount = resolveInitialRecommendationTargetCount(state);
        selectionState.targetTierCounts.putAll(normalizeInitialRecommendationTierTargets(state));
        selectionState.sourceProvinceName = state.getCandidatePoolState().getSourceProvinceName();
        selectionState.userScore = state.getCandidatePoolState().getUserScore();
        selectionState.requiredMajorCount = state.getCandidatePoolState().getRequiredMajorCount();
        selectionState.volunteerModel = state.getCandidatePoolState().getVolunteerModel();

        Map<String, List<CandidateItemDTO>> tierBuckets = bucketInitialRecommendationCandidatesByTier(candidates);
        for (Map.Entry<String, List<CandidateItemDTO>> entry : tierBuckets.entrySet()) {
            entry.getValue().sort(buildInitialRecommendationCandidateComparator());
        }

        for (String tier : Lists.newArrayList("冲", "稳", "保")) {
            int target = selectionState.targetTierCounts.getOrDefault(tier, 0);
            List<CandidateItemDTO> bucket = tierBuckets.getOrDefault(tier, Lists.newArrayList());
            for (CandidateItemDTO candidate : bucket) {
                if (target <= 0) {
                    break;
                }
                if (!selectionState.selectedIds.add(candidate.getVolunteerId())) {
                    continue;
                }
                selectionState.selected.add(candidate);
                selectionState.selectionReasons.put(candidate.getVolunteerId(), Lists.newArrayList("selected_by_tier_target"));
                target--;
            }
        }

        for (CandidateItemDTO candidate : candidates) {
            if (!selectionState.selectedIds.contains(candidate.getVolunteerId())) {
                selectionState.remaining.add(candidate);
            }
        }

        fillInitialRecommendationCountGap(selectionState);
        repairInitialRecommendationSafety(selectionState);
        repairInitialRecommendationProbabilityInversion(selectionState);
        repairInitialRecommendationProbabilityGap(selectionState);
        rebalanceInitialRecommendationTierCounts(selectionState);
        sortInitialRecommendationSelected(selectionState.selected);
        return selectionState;
    }

    private MajorGroupInitialRecommendationSelection buildMajorGroupInitialRecommendationSelection(PlanningStateDTO state,
                                                                                                   List<CandidateItemDTO> candidates) {
        Integer requiredMajorCount = state.getCandidatePoolState() == null ? null : state.getCandidatePoolState().getRequiredMajorCount();
        List<PlanningUnitDTO> units = groupCandidatesToPlanningUnits(candidates, requiredMajorCount);
        Map<String, PlanningUnitDTO> unitMap = units.stream()
                .filter(unit -> unit != null && !Strings.isNullOrEmpty(unit.getUnitId()))
                .collect(Collectors.toMap(PlanningUnitDTO::getUnitId,
                        unit -> unit,
                        (left, right) -> left,
                        LinkedHashMap::new));
        List<CandidateItemDTO> representatives = units.stream()
                .map(this::toPlanningUnitRepresentativeCandidate)
                .filter(Objects::nonNull)
                .collect(Collectors.toList());

        InitialRecommendationSelectionState groupSelectionState = buildInitialRecommendationSelectionStateWithoutUnitRepair(state, representatives);
        MajorGroupInitialRecommendationSelection selection = new MajorGroupInitialRecommendationSelection();
        selection.groupSelectionState = groupSelectionState;
        repairMajorGroupRepresentativeSelection(selection, unitMap, state);
        rebuildMajorGroupInitialRecommendationUnits(selection, unitMap, state);
        return selection;
    }

    private void repairMajorGroupRepresentativeSelection(MajorGroupInitialRecommendationSelection selection,
                                                         Map<String, PlanningUnitDTO> unitMap,
                                                         PlanningStateDTO state) {
        if (selection == null || selection.groupSelectionState == null) {
            return;
        }
        int guard = 0;
        while (guard++ < 20) {
            CandidateItemDTO weakRepresentative = findWeakMajorGroupRepresentative(selection.groupSelectionState.selected,
                    unitMap);
            if (weakRepresentative == null) {
                break;
            }
            CandidateItemDTO replacement = findReplacementMajorGroupRepresentative(weakRepresentative,
                    selection.groupSelectionState.remaining,
                    unitMap,
                    selection.groupSelectionState.targetTierCounts,
                    selection.groupSelectionState.selected);
            if (replacement == null) {
                break;
            }
            replaceInitialRecommendationCandidate(selection.groupSelectionState,
                    weakRepresentative,
                    replacement,
                    "selected_by_unit_repair");
        }

        selection.groupSelectionState.unresolvedRuleCodes.remove("probability_inversion");
        selection.groupSelectionState.unresolvedRuleCodes.remove("probability_gap");
        selection.groupSelectionState.unresolvedRuleCodes.remove("ratio_distribution");
        repairInitialRecommendationProbabilityInversion(selection.groupSelectionState);
        repairInitialRecommendationProbabilityGap(selection.groupSelectionState);
        rebalanceInitialRecommendationTierCounts(selection.groupSelectionState);
        sortInitialRecommendationSelected(selection.groupSelectionState.selected);
    }

    private void rebuildMajorGroupInitialRecommendationUnits(MajorGroupInitialRecommendationSelection selection,
                                                             Map<String, PlanningUnitDTO> unitMap,
                                                             PlanningStateDTO state) {
        selection.selectedUnits.clear();
        selection.unresolvedRuleCodes.clear();
        selection.unresolvedRuleCodes.addAll(selection.groupSelectionState.unresolvedRuleCodes);
        selection.majorSelectionRepairCount = 0;
        for (CandidateItemDTO representative : selection.groupSelectionState.selected) {
            String unitId = resolveInitialRecommendationUnitId(representative);
            PlanningUnitDTO unit = unitMap.get(unitId);
            if (unit == null) {
                continue;
            }
            selection.selectedUnits.add(unit);

            if (!Boolean.TRUE.equals(unit.getHasSafetyMajor()) && !defaultPlanningUnitMajors(unit.getAllMajors()).isEmpty()) {
                addUnresolvedRuleCode(selection.unresolvedRuleCodes, "group_inner_safety_guard");
            } else if (Boolean.TRUE.equals(unit.getHasSafetyMajor())) {
                selection.majorSelectionRepairCount++;
            }
        }
    }

    private CandidateItemDTO findWeakMajorGroupRepresentative(List<CandidateItemDTO> selected,
                                                              Map<String, PlanningUnitDTO> unitMap) {
        MajorGroupUnitQuality weakest = null;
        for (CandidateItemDTO representative : defaultCandidates(selected)) {
            MajorGroupUnitQuality quality = evaluateMajorGroupUnitQuality(representative, unitMap);
            if (quality == null || quality.isQualified()) {
                continue;
            }
            if (weakest == null || compareMajorGroupUnitQuality(quality, weakest) < 0) {
                weakest = quality;
            }
        }
        return weakest == null ? null : weakest.representative;
    }

    private CandidateItemDTO findReplacementMajorGroupRepresentative(CandidateItemDTO target,
                                                                     List<CandidateItemDTO> remaining,
                                                                     Map<String, PlanningUnitDTO> unitMap,
                                                                     Map<String, Integer> targetTierCounts,
                                                                     List<CandidateItemDTO> selected) {
        if (target == null) {
            return null;
        }
        Map<String, Integer> currentTierCounts = countInitialRecommendationTiers(selected);
        MajorGroupUnitQuality targetQuality = evaluateMajorGroupUnitQuality(target, unitMap);
        CandidateItemDTO best = null;
        MajorGroupUnitQuality bestQuality = null;
        for (CandidateItemDTO candidate : defaultCandidates(remaining)) {
            if (candidate == null) {
                continue;
            }
            if (!isAcceptableInitialRecommendationTierSwap(currentTierCounts, target, candidate, targetTierCounts)) {
                continue;
            }
            MajorGroupUnitQuality candidateQuality = evaluateMajorGroupUnitQuality(candidate, unitMap);
            if (candidateQuality == null || compareMajorGroupUnitQuality(candidateQuality, targetQuality) <= 0) {
                continue;
            }
            if (bestQuality == null || compareMajorGroupUnitQuality(candidateQuality, bestQuality) > 0) {
                best = candidate;
                bestQuality = candidateQuality;
            }
        }
        return best;
    }

    private MajorGroupUnitQuality evaluateMajorGroupUnitQuality(CandidateItemDTO representative,
                                                                Map<String, PlanningUnitDTO> unitMap) {
        if (representative == null) {
            return null;
        }
        String unitId = resolveInitialRecommendationUnitId(representative);
        PlanningUnitDTO unit = unitMap.get(unitId);
        if (unit == null) {
            return null;
        }
        MajorGroupUnitQuality quality = new MajorGroupUnitQuality();
        quality.representative = representative;
        quality.safe = Boolean.TRUE.equals(unit.getHasSafetyMajor()) || defaultPlanningUnitMajors(unit.getAllMajors()).isEmpty();
        quality.finalScore = unit.getFinalScore() == null ? 0D : unit.getFinalScore();
        quality.admissionRatio = unit.getAdmissionRatio() == null ? 0D : unit.getAdmissionRatio();
        return quality;
    }

    private int compareMajorGroupUnitQuality(MajorGroupUnitQuality left,
                                             MajorGroupUnitQuality right) {
        if (left == null && right == null) {
            return 0;
        }
        if (left == null) {
            return -1;
        }
        if (right == null) {
            return 1;
        }
        int compare = Boolean.compare(left.safe, right.safe);
        if (compare != 0) {
            return compare;
        }
        compare = Double.compare(left.finalScore, right.finalScore);
        if (compare != 0) {
            return compare;
        }
        return Double.compare(left.admissionRatio, right.admissionRatio);
    }

    private InitialRecommendationSelectionState buildInitialRecommendationSelectionStateWithoutUnitRepair(PlanningStateDTO state,
                                                                                                          List<CandidateItemDTO> candidates) {
        InitialRecommendationSelectionState selectionState = new InitialRecommendationSelectionState();
        selectionState.targetCount = resolveInitialRecommendationTargetCount(state);
        selectionState.targetTierCounts.putAll(normalizeInitialRecommendationTierTargets(state));
        selectionState.sourceProvinceName = state.getCandidatePoolState().getSourceProvinceName();
        selectionState.userScore = state.getCandidatePoolState().getUserScore();
        selectionState.requiredMajorCount = state.getCandidatePoolState().getRequiredMajorCount();
        selectionState.volunteerModel = state.getCandidatePoolState().getVolunteerModel();

        Map<String, List<CandidateItemDTO>> tierBuckets = bucketInitialRecommendationCandidatesByTier(candidates);
        for (Map.Entry<String, List<CandidateItemDTO>> entry : tierBuckets.entrySet()) {
            entry.getValue().sort(buildInitialRecommendationCandidateComparator());
        }

        for (String tier : Lists.newArrayList("冲", "稳", "保")) {
            int target = selectionState.targetTierCounts.getOrDefault(tier, 0);
            List<CandidateItemDTO> bucket = tierBuckets.getOrDefault(tier, Lists.newArrayList());
            for (CandidateItemDTO candidate : bucket) {
                if (target <= 0) {
                    break;
                }
                if (!selectionState.selectedIds.add(candidate.getVolunteerId())) {
                    continue;
                }
                selectionState.selected.add(candidate);
                selectionState.selectionReasons.put(candidate.getVolunteerId(), Lists.newArrayList("selected_by_tier_target"));
                target--;
            }
        }

        for (CandidateItemDTO candidate : candidates) {
            if (!selectionState.selectedIds.contains(candidate.getVolunteerId())) {
                selectionState.remaining.add(candidate);
            }
        }

        fillInitialRecommendationCountGap(selectionState);
        repairInitialRecommendationSafety(selectionState);
        repairInitialRecommendationProbabilityInversion(selectionState);
        repairInitialRecommendationProbabilityGap(selectionState);
        rebalanceInitialRecommendationTierCounts(selectionState);
        sortInitialRecommendationSelected(selectionState.selected);
        return selectionState;
    }

    private int resolveInitialRecommendationTargetCount(PlanningStateDTO state) {
        if (state.getCandidatePoolState() != null && state.getCandidatePoolState().getRequiredCount() != null
                && state.getCandidatePoolState().getRequiredCount() > 0) {
            return state.getCandidatePoolState().getRequiredCount();
        }
        if (state.getCandidatePoolState() != null && state.getCandidatePoolState().getRequiredTierCounts() != null
                && !state.getCandidatePoolState().getRequiredTierCounts().isEmpty()) {
            int tierSum = state.getCandidatePoolState().getRequiredTierCounts().values().stream()
                    .filter(Objects::nonNull)
                    .filter(count -> count > 0)
                    .mapToInt(Integer::intValue)
                    .sum();
            if (tierSum > 0) {
                return tierSum;
            }
        }
        if (isMajorGroupMode(state.getCandidatePoolState())) {
            if (state.getCandidatePoolState() != null && state.getCandidatePoolState().getRequiredUnitCount() != null
                    && state.getCandidatePoolState().getRequiredUnitCount() > 0) {
                return state.getCandidatePoolState().getRequiredUnitCount();
            }
        } else if (state.getCandidatePoolState() != null && state.getCandidatePoolState().getRequiredMajorCount() != null
                && state.getCandidatePoolState().getRequiredMajorCount() > 0) {
            return state.getCandidatePoolState().getRequiredMajorCount();
        }
        return state.getCandidatePoolState() == null || state.getCandidatePoolState().getItems() == null
                ? 0 : state.getCandidatePoolState().getItems().size();
    }

    private Map<String, Integer> normalizeInitialRecommendationTierTargets(PlanningStateDTO state) {
        Map<String, Integer> result = new LinkedHashMap<String, Integer>();
        result.put("冲", 0);
        result.put("稳", 0);
        result.put("保", 0);
        if (state.getCandidatePoolState() != null && state.getCandidatePoolState().getRequiredTierCounts() != null
                && !state.getCandidatePoolState().getRequiredTierCounts().isEmpty()) {
            result.put("冲", defaultInt(state.getCandidatePoolState().getRequiredTierCounts().get("冲")));
            result.put("稳", defaultInt(state.getCandidatePoolState().getRequiredTierCounts().get("稳")));
            result.put("保", defaultInt(state.getCandidatePoolState().getRequiredTierCounts().get("保")));
        }
        int total = result.values().stream().mapToInt(Integer::intValue).sum();
        int targetCount = resolveInitialRecommendationTargetCount(state);
        if (total <= 0 && targetCount > 0) {
            result.put("冲", Math.max(0, (int) Math.floor(targetCount * 0.3D)));
            result.put("稳", Math.max(0, (int) Math.floor(targetCount * 0.3D)));
            result.put("保", Math.max(0, targetCount - result.get("冲") - result.get("稳")));
            total = targetCount;
        }
        if (targetCount > 0 && total < targetCount) {
            result.put("保", result.get("保") + (targetCount - total));
        }
        return result;
    }

    private Map<String, List<CandidateItemDTO>> bucketInitialRecommendationCandidatesByTier(List<CandidateItemDTO> candidates) {
        Map<String, List<CandidateItemDTO>> buckets = new LinkedHashMap<String, List<CandidateItemDTO>>();
        buckets.put("冲", Lists.newArrayList());
        buckets.put("稳", Lists.newArrayList());
        buckets.put("保", Lists.newArrayList());
        for (CandidateItemDTO candidate : defaultCandidates(candidates)) {
            String tier = Strings.isNullOrEmpty(candidate.getTier()) ? "保" : candidate.getTier();
            buckets.computeIfAbsent(tier, key -> Lists.newArrayList()).add(candidate);
        }
        return buckets;
    }

    private Comparator<CandidateItemDTO> buildInitialRecommendationCandidateComparator() {
        return Comparator
                .comparing((CandidateItemDTO item) -> Boolean.TRUE.equals(item.getPreferred()) ? 0 : 1)
                .thenComparing((CandidateItemDTO item) -> item.getFutureDevelopmentScore(),
                        Comparator.nullsLast(Comparator.reverseOrder()))
                .thenComparing((CandidateItemDTO item) -> item.getFinalScore() == null ? 0D : item.getFinalScore(),
                        Comparator.reverseOrder())
                .thenComparing((CandidateItemDTO item) -> item.getAdmissionRatio(),
                        Comparator.nullsLast(Double::compareTo))
                .thenComparing((CandidateItemDTO item) -> item.getRankInTier(),
                        Comparator.nullsLast(Integer::compareTo));
    }

    private void fillInitialRecommendationCountGap(InitialRecommendationSelectionState selectionState) {
        while (selectionState.selected.size() < selectionState.targetCount && !selectionState.remaining.isEmpty()) {
            String shortageTier = resolveInitialRecommendationShortageTier(selectionState);
            CandidateItemDTO candidate = takeInitialRecommendationGapFillCandidate(selectionState.remaining, shortageTier);
            String reasonCode = "selected_by_tier_target";
            if (candidate == null) {
                break;
            }
            if (!Strings.isNullOrEmpty(shortageTier) && !shortageTier.equals(candidate.getTier())) {
                reasonCode = "selected_by_tier_borrow";
            }
            selectionState.selected.add(candidate);
            selectionState.selectedIds.add(candidate.getVolunteerId());
            selectionState.selectionReasons.put(candidate.getVolunteerId(), Lists.newArrayList(reasonCode));
            selectionState.appliedRepairCount++;
        }
        if (selectionState.selected.size() < selectionState.targetCount) {
            addUnresolvedRuleCode(selectionState, "count_validation");
        }
    }

    private String resolveInitialRecommendationShortageTier(InitialRecommendationSelectionState selectionState) {
        Map<String, Integer> currentCounts = countInitialRecommendationTiers(selectionState.selected);
        String shortageTier = null;
        int maxDeficit = 0;
        for (String tier : Lists.newArrayList("保", "稳", "冲")) {
            int deficit = selectionState.targetTierCounts.getOrDefault(tier, 0) - currentCounts.getOrDefault(tier, 0);
            if (deficit > maxDeficit) {
                maxDeficit = deficit;
                shortageTier = tier;
            }
        }
        return shortageTier;
    }

    private CandidateItemDTO takeInitialRecommendationGapFillCandidate(List<CandidateItemDTO> remaining,
                                                                       String shortageTier) {
        Comparator<CandidateItemDTO> comparator = buildInitialRecommendationCandidateComparator();
        if (Strings.isNullOrEmpty(shortageTier)) {
            return pollNextInitialRecommendationCandidate(remaining, comparator);
        }
        for (String tier : resolveInitialRecommendationBorrowOrder(shortageTier)) {
            CandidateItemDTO candidate = takeInitialRecommendationRemainingCandidate(remaining,
                    item -> tier.equals(item.getTier()),
                    Comparator.comparing((CandidateItemDTO item) -> !tier.equals(item.getTier()))
                            .thenComparing(comparator));
            if (candidate != null) {
                return candidate;
            }
        }
        return pollNextInitialRecommendationCandidate(remaining, comparator);
    }

    private List<String> resolveInitialRecommendationBorrowOrder(String shortageTier) {
        if ("冲".equals(shortageTier)) {
            return Lists.newArrayList("冲", "稳", "保");
        }
        if ("稳".equals(shortageTier)) {
            return Lists.newArrayList("稳", "保", "冲");
        }
        if ("保".equals(shortageTier)) {
            return Lists.newArrayList("保", "稳", "冲");
        }
        return Lists.newArrayList("冲", "稳", "保");
    }

    private void repairInitialRecommendationSafety(InitialRecommendationSelectionState selectionState) {
        if (selectionState.userScore != null && selectionState.userScore >= 580) {
            return;
        }
        if (Strings.isNullOrEmpty(selectionState.sourceProvinceName)) {
            return;
        }
        int localProtectCount = countLocalProtectCandidates(selectionState.selected, selectionState.sourceProvinceName);
        while (localProtectCount < 2) {
            CandidateItemDTO localProtectCandidate = takeInitialRecommendationRemainingCandidate(selectionState.remaining,
                    item -> "保".equals(item.getTier())
                            && containsIgnoreCase(item.getProvinceName(), selectionState.sourceProvinceName),
                    Comparator.comparing((CandidateItemDTO item) -> !"保".equals(item.getTier()))
                            .thenComparing((CandidateItemDTO item) -> !containsIgnoreCase(item.getProvinceName(),
                                    selectionState.sourceProvinceName))
                            .thenComparing(buildInitialRecommendationCandidateComparator()));
            if (localProtectCandidate == null) {
                addUnresolvedRuleCode(selectionState, "safety_guard");
                break;
            }
            CandidateItemDTO removable = findInitialRecommendationRemovableCandidate(selectionState,
                    candidate -> "保".equals(candidate.getTier())
                            && !containsIgnoreCase(candidate.getProvinceName(), selectionState.sourceProvinceName));
            if (removable == null) {
                removable = findInitialRecommendationRemovableCandidate(selectionState,
                        candidate -> !containsIgnoreCase(candidate.getProvinceName(), selectionState.sourceProvinceName));
            }
            if (removable == null) {
                addUnresolvedRuleCode(selectionState, "safety_guard");
                break;
            }
            replaceInitialRecommendationCandidate(selectionState, removable, localProtectCandidate, "selected_by_local_protect");
            localProtectCount = countLocalProtectCandidates(selectionState.selected, selectionState.sourceProvinceName);
        }
    }

    private void repairInitialRecommendationProbabilityGap(InitialRecommendationSelectionState selectionState) {
        InitialRecommendationGapMetrics metrics = evaluateInitialRecommendationGapMetrics(selectionState.selected);
        if (metrics.gapCount <= 0) {
            selectionState.unresolvedGapCount = 0;
            return;
        }
        int guard = 0;
        while (guard++ < 10) {
            InitialRecommendationGapSwap swap = findBestInitialRecommendationGapSwap(selectionState, metrics);
            if (swap == null) {
                break;
            }
            replaceInitialRecommendationCandidate(selectionState, swap.removable, swap.filler, "selected_by_gap_fill");
            selectionState.gapFixCount++;
            metrics = swap.metricsAfter;
            if (metrics.gapCount <= 0) {
                selectionState.unresolvedGapCount = 0;
                return;
            }
        }
        selectionState.unresolvedGapCount = metrics.gapCount;
        if (selectionState.unresolvedGapCount > 0) {
            addUnresolvedRuleCode(selectionState, "probability_gap");
        }
    }

    private void repairInitialRecommendationProbabilityInversion(InitialRecommendationSelectionState selectionState) {
        InitialRecommendationInversionMetrics metrics = evaluateInitialRecommendationInversionMetrics(selectionState.selected);
        if (metrics.inversionCount <= 0) {
            return;
        }
        int guard = 0;
        while (guard++ < 10) {
            InitialRecommendationInversionSwap swap = findBestInitialRecommendationInversionSwap(selectionState, metrics);
            if (swap == null) {
                break;
            }
            replaceInitialRecommendationCandidate(selectionState, swap.removable, swap.filler, "selected_by_inversion_repair");
            metrics = swap.metricsAfter;
            if (metrics.inversionCount <= 0) {
                return;
            }
        }
        if (metrics.inversionCount > 0) {
            addUnresolvedRuleCode(selectionState, "probability_inversion");
        }
    }

    private void rebalanceInitialRecommendationTierCounts(InitialRecommendationSelectionState selectionState) {
        Map<String, Integer> currentCounts = countInitialRecommendationTiers(selectionState.selected);
        for (String tier : selectionState.targetTierCounts.keySet()) {
            while (currentCounts.getOrDefault(tier, 0) < selectionState.targetTierCounts.getOrDefault(tier, 0)) {
                CandidateItemDTO filler = takeInitialRecommendationRemainingCandidate(selectionState.remaining,
                        item -> tier.equals(item.getTier()),
                        Comparator.comparing((CandidateItemDTO item) -> !tier.equals(item.getTier()))
                                .thenComparing(buildInitialRecommendationCandidateComparator()));
                if (filler == null) {
                    addUnresolvedRuleCode(selectionState, "ratio_distribution");
                    break;
                }
                final Map<String, Integer> rebalanceSnapshot = currentCounts;
                CandidateItemDTO removable = findInitialRecommendationRemovableCandidate(selectionState,
                        candidate -> rebalanceSnapshot.getOrDefault(candidate.getTier(), 0)
                                > selectionState.targetTierCounts.getOrDefault(candidate.getTier(), 0)
                                && !isLocalProtectCandidate(candidate, selectionState.sourceProvinceName));
                if (removable == null) {
                    selectionState.remaining.add(filler);
                    addUnresolvedRuleCode(selectionState, "ratio_distribution");
                    break;
                }
                replaceInitialRecommendationCandidate(selectionState, removable, filler, "selected_by_tier_target");
                currentCounts = countInitialRecommendationTiers(selectionState.selected);
            }
        }
    }

    private List<String> resolveInitialRecommendationReasonCodes(InitialRecommendationSelectionState selectionState,
                                                                 CandidateItemDTO candidate) {
        return selectionState.selectionReasons.getOrDefault(candidate.getVolunteerId(), Lists.newArrayList("selected_by_tier_target"));
    }

    private CandidateItemDTO pollNextInitialRecommendationCandidate(List<CandidateItemDTO> candidates,
                                                                    Comparator<CandidateItemDTO> comparator) {
        if (candidates == null || candidates.isEmpty()) {
            return null;
        }
        candidates.sort(comparator);
        return candidates.remove(0);
    }

    private CandidateItemDTO takeInitialRecommendationRemainingCandidate(List<CandidateItemDTO> candidates,
                                                                         java.util.function.Predicate<CandidateItemDTO> predicate,
                                                                         Comparator<CandidateItemDTO> comparator) {
        if (candidates == null || candidates.isEmpty()) {
            return null;
        }
        candidates.sort(comparator);
        for (int i = 0; i < candidates.size(); i++) {
            CandidateItemDTO candidate = candidates.get(i);
            if (predicate.test(candidate)) {
                candidates.remove(i);
                return candidate;
            }
        }
        return null;
    }

    private CandidateItemDTO findInitialRecommendationRemovableCandidate(InitialRecommendationSelectionState selectionState,
                                                                         java.util.function.Predicate<CandidateItemDTO> predicate) {
        return selectionState.selected.stream()
                .filter(predicate)
                .sorted(buildInitialRecommendationRemovableComparator(selectionState.sourceProvinceName))
                .findFirst()
                .orElse(null);
    }

    private Comparator<CandidateItemDTO> buildInitialRecommendationRemovableComparator(String sourceProvinceName) {
        return Comparator
                .comparing((CandidateItemDTO item) -> isLocalProtectCandidate(item, sourceProvinceName) ? 1 : 0)
                .thenComparing((CandidateItemDTO item) -> Boolean.TRUE.equals(item.getPreferred()) ? 1 : 0)
                .thenComparing((CandidateItemDTO item) -> item.getFinalScore() == null ? 0D : item.getFinalScore())
                .thenComparing((CandidateItemDTO item) -> item.getAdmissionRatio(),
                        Comparator.nullsLast(Double::compareTo));
    }

    private void replaceInitialRecommendationCandidate(InitialRecommendationSelectionState selectionState,
                                                       CandidateItemDTO remove,
                                                       CandidateItemDTO add,
                                                       String reasonCode) {
        selectionState.selected.removeIf(item -> item.getVolunteerId().equals(remove.getVolunteerId()));
        selectionState.selected.removeIf(item -> item.getVolunteerId().equals(add.getVolunteerId()));
        selectionState.selectedIds.remove(remove.getVolunteerId());
        selectionState.selectedIds.remove(add.getVolunteerId());
        selectionState.remaining.add(remove);
        selectionState.remaining.removeIf(item -> item.getVolunteerId().equals(add.getVolunteerId()));
        selectionState.selected.add(add);
        selectionState.selectedIds.add(add.getVolunteerId());
        selectionState.selectionReasons.put(add.getVolunteerId(), Lists.newArrayList(reasonCode));
        selectionState.appliedRepairCount++;
        InitialPlanStrategyReportDTO.Tradeoff tradeoff = buildInitialPlanTradeoff(remove, add, reasonCode);
        selectionState.appliedRepairs.add(buildInitialPlanAppliedRepair(remove, add, reasonCode, tradeoff));
        selectionState.actions.add(buildInitialPlanReplacementAction(remove, add, reasonCode, tradeoff));
        selectionState.tradeoffs.add(tradeoff);
    }

    private FixProposalActionDTO buildInitialPlanReplacementAction(CandidateItemDTO remove,
                                                                   CandidateItemDTO add,
                                                                   String reasonCode,
                                                                   InitialPlanStrategyReportDTO.Tradeoff tradeoff) {
        String ruleCode = resolveInitialPlanRepairRuleCode(reasonCode);
        FixProposalActionDTO action = new FixProposalActionDTO();
        action.setActionType(RepairProposalTaxonomy.ActionType.REPLACE_VOLUNTEERS);
        action.setLevel("info");
        action.setSourceCheckCode(ruleCode);
        action.setSummary(resolveInitialPlanRepairDetail(reasonCode));
        action.setDetail(tradeoff == null ? resolveInitialPlanRepairDetail(reasonCode) : tradeoff.getSummary());
        if (remove != null && !Strings.isNullOrEmpty(remove.getVolunteerId())) {
            action.getRemoveVolunteerIds().add(remove.getVolunteerId());
        }
        if (add != null && !Strings.isNullOrEmpty(add.getVolunteerId())) {
            action.getCandidateVolunteerIds().add(add.getVolunteerId());
        }
        String removeUnitId = resolveInitialRecommendationUnitId(remove);
        if (!Strings.isNullOrEmpty(removeUnitId)) {
            action.getRemoveUnitIds().add(removeUnitId);
        }
        String addUnitId = resolveInitialRecommendationUnitId(add);
        if (!Strings.isNullOrEmpty(addUnitId)) {
            action.getCandidateUnitIds().add(addUnitId);
        }
        ReplacementPairDTO pair = new ReplacementPairDTO();
        pair.setFromUnitId(removeUnitId);
        pair.setFromVolunteerId(remove == null ? null : remove.getVolunteerId());
        pair.setToUnitId(addUnitId);
        pair.setToVolunteerId(add == null ? null : add.getVolunteerId());
        pair.getReasonCodes().add(reasonCode);
        if (!Strings.isNullOrEmpty(ruleCode)) {
            pair.getReasonCodes().add(ruleCode);
        }
        action.getReplacementPairs().add(pair);
        return action;
    }

    private InitialPlanStrategyReportDTO.AppliedRepair buildInitialPlanAppliedRepair(CandidateItemDTO remove,
                                                                                     CandidateItemDTO add,
                                                                                     String reasonCode,
                                                                                     InitialPlanStrategyReportDTO.Tradeoff tradeoff) {
        InitialPlanStrategyReportDTO.AppliedRepair repair = new InitialPlanStrategyReportDTO.AppliedRepair();
        repair.setReasonCode(reasonCode);
        repair.setRuleCode(resolveInitialPlanRepairRuleCode(reasonCode));
        repair.setActionType("replace_candidate");
        repair.setFromVolunteerId(remove == null ? null : remove.getVolunteerId());
        repair.setFromLabel(formatInitialPlanCandidateLabel(remove));
        repair.setToVolunteerId(add == null ? null : add.getVolunteerId());
        repair.setToLabel(formatInitialPlanCandidateLabel(add));
        repair.setDetail(resolveInitialPlanRepairDetail(reasonCode));
        repair.setTradeoffSummary(tradeoff == null ? null : tradeoff.getSummary());
        return repair;
    }

    private InitialPlanStrategyReportDTO.Tradeoff buildInitialPlanTradeoff(CandidateItemDTO remove,
                                                                           CandidateItemDTO add,
                                                                           String reasonCode) {
        InitialPlanStrategyReportDTO.Tradeoff tradeoff = new InitialPlanStrategyReportDTO.Tradeoff();
        tradeoff.setReasonCode(reasonCode);
        tradeoff.setRuleCode(resolveInitialPlanRepairRuleCode(reasonCode));
        tradeoff.setActionType("replace_candidate");
        tradeoff.setFromVolunteerId(remove == null ? null : remove.getVolunteerId());
        tradeoff.setFromLabel(formatInitialPlanCandidateLabel(remove));
        tradeoff.setToVolunteerId(add == null ? null : add.getVolunteerId());
        tradeoff.setToLabel(formatInitialPlanCandidateLabel(add));
        tradeoff.setFinalScoreDelta(roundOneDecimal(delta(add == null ? null : add.getFinalScore(),
                remove == null ? null : remove.getFinalScore())));
        tradeoff.setAdmissionRatioDelta(roundOneDecimal(delta(add == null ? null : add.getAdmissionRatio(),
                remove == null ? null : remove.getAdmissionRatio())));
        tradeoff.setHotIndexDelta(roundOneDecimal(delta(add == null ? null : add.getHotIndex(),
                remove == null ? null : remove.getHotIndex())));
        tradeoff.setSchoolRankDelta(delta(add == null ? null : add.getSchoolRank(),
                remove == null ? null : remove.getSchoolRank()));
        tradeoff.setPreferredDowngraded(Boolean.TRUE.equals(remove == null ? null : remove.getPreferred())
                && !Boolean.TRUE.equals(add == null ? null : add.getPreferred()));
        tradeoff.setPreferredUpgraded(!Boolean.TRUE.equals(remove == null ? null : remove.getPreferred())
                && Boolean.TRUE.equals(add == null ? null : add.getPreferred()));
        populateInitialPlanTradeoffGainsAndCosts(tradeoff, reasonCode);
        tradeoff.setSummary(buildInitialPlanTradeoffSummary(tradeoff));
        return tradeoff;
    }

    private void populateInitialPlanTradeoffGainsAndCosts(InitialPlanStrategyReportDTO.Tradeoff tradeoff,
                                                          String reasonCode) {
        if (tradeoff == null) {
            return;
        }
        String reasonGain = resolveInitialPlanTradeoffGain(reasonCode);
        if (!Strings.isNullOrEmpty(reasonGain)) {
            tradeoff.getGains().add(reasonGain);
        }
        if (tradeoff.getAdmissionRatioDelta() != null) {
            if (tradeoff.getAdmissionRatioDelta() > 0D) {
                tradeoff.getGains().add("录取率提高" + formatPositiveNumber(tradeoff.getAdmissionRatioDelta()) + "个百分点");
            } else if (tradeoff.getAdmissionRatioDelta() < 0D) {
                tradeoff.getCosts().add("录取率下降" + formatPositiveNumber(Math.abs(tradeoff.getAdmissionRatioDelta())) + "个百分点");
            }
        }
        if (tradeoff.getFinalScoreDelta() != null) {
            if (tradeoff.getFinalScoreDelta() > 0D) {
                tradeoff.getGains().add("推荐分提高" + formatPositiveNumber(tradeoff.getFinalScoreDelta()));
            } else if (tradeoff.getFinalScoreDelta() < 0D) {
                tradeoff.getCosts().add("推荐分下降" + formatPositiveNumber(Math.abs(tradeoff.getFinalScoreDelta())));
            }
        }
        if (tradeoff.getHotIndexDelta() != null) {
            if (tradeoff.getHotIndexDelta() > 0D) {
                tradeoff.getGains().add("专业热度提高" + formatPositiveNumber(tradeoff.getHotIndexDelta()));
            } else if (tradeoff.getHotIndexDelta() < 0D) {
                tradeoff.getCosts().add("专业热度下降" + formatPositiveNumber(Math.abs(tradeoff.getHotIndexDelta())));
            }
        }
        if (tradeoff.getSchoolRankDelta() != null) {
            if (tradeoff.getSchoolRankDelta() < 0) {
                tradeoff.getGains().add("院校排名序号前移" + Math.abs(tradeoff.getSchoolRankDelta()) + "位");
            } else if (tradeoff.getSchoolRankDelta() > 0) {
                tradeoff.getCosts().add("院校排名序号后移" + tradeoff.getSchoolRankDelta() + "位");
            }
        }
        if (Boolean.TRUE.equals(tradeoff.getPreferredUpgraded())) {
            tradeoff.getGains().add("更匹配已确认偏好或专家优选");
        }
        if (Boolean.TRUE.equals(tradeoff.getPreferredDowngraded())) {
            tradeoff.getCosts().add("从偏好命中候选换出");
        }
    }

    private String resolveInitialPlanTradeoffGain(String reasonCode) {
        if ("selected_by_local_protect".equals(reasonCode)) {
            return "补足本省或保底安全垫";
        }
        if ("selected_by_gap_fill".equals(reasonCode)) {
            return "缓解录取率梯度断层";
        }
        if ("selected_by_inversion_repair".equals(reasonCode)) {
            return "缓解录取率倒挂";
        }
        if ("selected_by_unit_repair".equals(reasonCode)) {
            return "提升专业组内安全性";
        }
        if ("selected_by_tier_target".equals(reasonCode)) {
            return "贴近目标冲稳保比例";
        }
        return "降低初始方案结构风险";
    }

    private String buildInitialPlanTradeoffSummary(InitialPlanStrategyReportDTO.Tradeoff tradeoff) {
        if (tradeoff == null) {
            return null;
        }
        String gains = tradeoff.getGains().isEmpty() ? "结构风险降低" : String.join("、", tradeoff.getGains());
        String costs = tradeoff.getCosts().isEmpty() ? "未发现明显推荐指标损失" : String.join("、", tradeoff.getCosts());
        return "收益：" + gains + "；取舍：" + costs;
    }

    private Double delta(Double next, Double previous) {
        if (next == null || previous == null) {
            return null;
        }
        return next - previous;
    }

    private Integer delta(Integer next, Integer previous) {
        if (next == null || previous == null) {
            return null;
        }
        return next - previous;
    }

    private Double roundOneDecimal(Double value) {
        if (value == null) {
            return null;
        }
        return Math.round(value * 10D) / 10D;
    }

    private String formatPositiveNumber(Double value) {
        if (value == null) {
            return "0";
        }
        double abs = Math.abs(value);
        if (Math.abs(abs - Math.rint(abs)) < 0.000001D) {
            return String.valueOf((int) Math.rint(abs));
        }
        return String.format(Locale.ROOT, "%.1f", abs);
    }

    private String resolveInitialPlanRepairRuleCode(String reasonCode) {
        if ("selected_by_local_protect".equals(reasonCode)) {
            return "safety_guard";
        }
        if ("selected_by_gap_fill".equals(reasonCode)) {
            return "probability_gap";
        }
        if ("selected_by_inversion_repair".equals(reasonCode)) {
            return "probability_inversion";
        }
        if ("selected_by_unit_repair".equals(reasonCode)) {
            return "group_inner_safety_guard";
        }
        if ("selected_by_tier_target".equals(reasonCode)) {
            return "ratio_distribution";
        }
        return "initial_plan_strategy";
    }

    private String resolveInitialPlanRepairDetail(String reasonCode) {
        if ("selected_by_local_protect".equals(reasonCode)) {
            return "为补足本省或保底安全垫，替换了一个候选。";
        }
        if ("selected_by_gap_fill".equals(reasonCode)) {
            return "为缓解录取率梯度断层，替换了一个候选。";
        }
        if ("selected_by_inversion_repair".equals(reasonCode)) {
            return "为缓解录取率倒挂，替换了一个候选。";
        }
        if ("selected_by_unit_repair".equals(reasonCode)) {
            return "为提升专业组内安全性，替换了一个专业组候选。";
        }
        if ("selected_by_tier_target".equals(reasonCode)) {
            return "为尽量贴近目标冲稳保比例，替换了一个候选。";
        }
        return "初始推荐阶段执行了一次结构性调整。";
    }

    private String formatInitialPlanCandidateLabel(CandidateItemDTO candidate) {
        if (candidate == null) {
            return null;
        }
        if (!Strings.isNullOrEmpty(candidate.getSchoolName()) && !Strings.isNullOrEmpty(candidate.getMajorName())) {
            return candidate.getSchoolName() + "-" + candidate.getMajorName();
        }
        if (!Strings.isNullOrEmpty(candidate.getSchoolName())) {
            return candidate.getSchoolName();
        }
        if (!Strings.isNullOrEmpty(candidate.getMajorName())) {
            return candidate.getMajorName();
        }
        return candidate.getVolunteerId();
    }

    private InitialRecommendationGap findInitialRecommendationGap(List<CandidateItemDTO> ordered) {
        for (int i = 1; i < ordered.size(); i++) {
            CandidateItemDTO previous = ordered.get(i - 1);
            CandidateItemDTO current = ordered.get(i);
            if (previous.getAdmissionRatio() == null || current.getAdmissionRatio() == null) {
                continue;
            }
            if (Math.abs(current.getAdmissionRatio() - previous.getAdmissionRatio()) > 8D) {
                InitialRecommendationGap gap = new InitialRecommendationGap();
                gap.left = previous;
                gap.right = current;
                return gap;
            }
        }
        return null;
    }

    private InitialRecommendationGapSwap findBestInitialRecommendationGapSwap(InitialRecommendationSelectionState selectionState,
                                                                              InitialRecommendationGapMetrics currentMetrics) {
        List<InitialRecommendationGap> gaps = findInitialRecommendationGaps(selectionState.selected);
        if (gaps.isEmpty()) {
            return null;
        }
        Map<String, Integer> currentTierCounts = countInitialRecommendationTiers(selectionState.selected);
        int currentTierDeviation = calculateInitialRecommendationTierDeviation(selectionState.selected,
                selectionState.targetTierCounts);
        InitialRecommendationGapSwap best = null;
        for (CandidateItemDTO filler : defaultCandidates(selectionState.remaining)) {
            if (filler.getAdmissionRatio() == null) {
                continue;
            }
            InitialRecommendationGap coveringGap = findCoveringInitialRecommendationGap(gaps, filler);
            if (coveringGap == null) {
                continue;
            }
            for (CandidateItemDTO removable : defaultCandidates(selectionState.selected)) {
                if (isLocalProtectCandidate(removable, selectionState.sourceProvinceName)) {
                    continue;
                }
                if (removable.getAdmissionRatio() == null) {
                    continue;
                }
                int tierDeviationAfter = calculateInitialRecommendationTierDeviationAfterSwap(
                        selectionState.selected, removable, filler, selectionState.targetTierCounts);
                if (tierDeviationAfter > currentTierDeviation) {
                    continue;
                }
                if (!isAcceptableInitialRecommendationTierSwap(currentTierCounts,
                        removable,
                        filler,
                        selectionState.targetTierCounts)) {
                    continue;
                }
                InitialRecommendationGapMetrics metricsAfter = evaluateInitialRecommendationGapMetricsAfterSwap(
                        selectionState.selected, removable, filler);
                if (!isBetterInitialRecommendationGapMetrics(metricsAfter, currentMetrics)) {
                    continue;
                }
                InitialRecommendationGapSwap candidateSwap = new InitialRecommendationGapSwap();
                candidateSwap.filler = filler;
                candidateSwap.removable = removable;
                candidateSwap.metricsAfter = metricsAfter;
                candidateSwap.coveringGap = coveringGap;
                candidateSwap.tierDeviationAfter = tierDeviationAfter;
                if (best == null || compareInitialRecommendationGapSwap(candidateSwap, best) < 0) {
                    best = candidateSwap;
                }
            }
        }
        return best;
    }

    private InitialRecommendationInversionSwap findBestInitialRecommendationInversionSwap(InitialRecommendationSelectionState selectionState,
                                                                                          InitialRecommendationInversionMetrics currentMetrics) {
        List<InitialRecommendationInversion> inversions = findInitialRecommendationInversions(selectionState.selected);
        if (inversions.isEmpty()) {
            return null;
        }
        Map<String, Integer> currentTierCounts = countInitialRecommendationTiers(selectionState.selected);
        InitialRecommendationInversionSwap best = null;
        for (InitialRecommendationInversion inversion : inversions) {
            if (inversion.previous == null || inversion.current == null
                    || inversion.previous.getAdmissionRatio() == null
                    || inversion.current.getAdmissionRatio() == null) {
                continue;
            }
            for (CandidateItemDTO filler : defaultCandidates(selectionState.remaining)) {
                if (filler.getAdmissionRatio() == null) {
                    continue;
                }
                CandidateItemDTO removable = null;
                if (sameTier(filler, inversion.previous)
                        && filler.getAdmissionRatio() <= inversion.current.getAdmissionRatio()
                        && !isLocalProtectCandidate(inversion.previous, selectionState.sourceProvinceName)) {
                    removable = inversion.previous;
                } else if (sameTier(filler, inversion.current)
                        && filler.getAdmissionRatio() >= inversion.previous.getAdmissionRatio()
                        && !isLocalProtectCandidate(inversion.current, selectionState.sourceProvinceName)) {
                    removable = inversion.current;
                }
                if (removable == null) {
                    continue;
                }
                if (!isAcceptableInitialRecommendationTierSwap(currentTierCounts,
                        removable,
                        filler,
                        selectionState.targetTierCounts)) {
                    continue;
                }
                InitialRecommendationInversionMetrics metricsAfter = evaluateInitialRecommendationInversionMetricsAfterSwap(
                        selectionState.selected, removable, filler);
                if (!isBetterInitialRecommendationInversionMetrics(metricsAfter, currentMetrics)) {
                    continue;
                }
                InitialRecommendationInversionSwap candidateSwap = new InitialRecommendationInversionSwap();
                candidateSwap.filler = filler;
                candidateSwap.removable = removable;
                candidateSwap.metricsAfter = metricsAfter;
                candidateSwap.targetInversion = inversion;
                if (best == null || compareInitialRecommendationInversionSwap(candidateSwap, best) < 0) {
                    best = candidateSwap;
                }
            }
        }
        return best;
    }

    private int compareInitialRecommendationInversionSwap(InitialRecommendationInversionSwap left,
                                                          InitialRecommendationInversionSwap right) {
        int compare = Integer.compare(left.metricsAfter.inversionCount, right.metricsAfter.inversionCount);
        if (compare != 0) {
            return compare;
        }
        compare = Double.compare(left.metricsAfter.maxDelta, right.metricsAfter.maxDelta);
        if (compare != 0) {
            return compare;
        }
        compare = Double.compare(distanceToInversionBoundary(left.filler, left.targetInversion),
                distanceToInversionBoundary(right.filler, right.targetInversion));
        if (compare != 0) {
            return compare;
        }
        compare = compareInitialRecommendationReplacementTradeoff(left.removable, left.filler,
                right.removable, right.filler);
        if (compare != 0) {
            return compare;
        }
        compare = buildInitialRecommendationCandidateComparator().compare(left.filler, right.filler);
        if (compare != 0) {
            return compare;
        }
        return buildInitialRecommendationRemovableComparator(null).compare(left.removable, right.removable);
    }

    private double distanceToInversionBoundary(CandidateItemDTO filler, InitialRecommendationInversion inversion) {
        if (filler == null || filler.getAdmissionRatio() == null || inversion == null
                || inversion.previous == null || inversion.previous.getAdmissionRatio() == null
                || inversion.current == null || inversion.current.getAdmissionRatio() == null) {
            return Double.MAX_VALUE;
        }
        if (sameTier(filler, inversion.previous)) {
            return Math.abs(filler.getAdmissionRatio() - inversion.current.getAdmissionRatio());
        }
        return Math.abs(filler.getAdmissionRatio() - inversion.previous.getAdmissionRatio());
    }

    private boolean isBetterInitialRecommendationInversionMetrics(InitialRecommendationInversionMetrics candidate,
                                                                  InitialRecommendationInversionMetrics baseline) {
        if (candidate == null || baseline == null) {
            return false;
        }
        if (candidate.inversionCount < baseline.inversionCount) {
            return true;
        }
        return candidate.inversionCount == baseline.inversionCount && candidate.maxDelta < baseline.maxDelta;
    }

    private InitialRecommendationInversionMetrics evaluateInitialRecommendationInversionMetricsAfterSwap(List<CandidateItemDTO> selected,
                                                                                                         CandidateItemDTO removable,
                                                                                                         CandidateItemDTO filler) {
        List<CandidateItemDTO> simulated = Lists.newArrayList();
        for (CandidateItemDTO item : defaultCandidates(selected)) {
            if (!item.getVolunteerId().equals(removable.getVolunteerId())) {
                simulated.add(item);
            }
        }
        simulated.add(filler);
        return evaluateInitialRecommendationInversionMetrics(simulated);
    }

    private InitialRecommendationInversionMetrics evaluateInitialRecommendationInversionMetrics(List<CandidateItemDTO> selected) {
        InitialRecommendationInversionMetrics metrics = new InitialRecommendationInversionMetrics();
        List<InitialRecommendationInversion> inversions = findInitialRecommendationInversions(selected);
        metrics.inversionCount = inversions.size();
        metrics.maxDelta = inversions.stream()
                .mapToDouble(inversion -> inversion.delta)
                .max()
                .orElse(0D);
        return metrics;
    }

    private List<InitialRecommendationInversion> findInitialRecommendationInversions(List<CandidateItemDTO> selected) {
        List<CandidateItemDTO> ordered = Lists.newArrayList(defaultCandidates(selected));
        sortInitialRecommendationSelected(ordered);
        List<InitialRecommendationInversion> inversions = Lists.newArrayList();
        for (int i = 1; i < ordered.size(); i++) {
            CandidateItemDTO previous = ordered.get(i - 1);
            CandidateItemDTO current = ordered.get(i);
            if (previous.getAdmissionRatio() == null || current.getAdmissionRatio() == null) {
                continue;
            }
            if (previous.getAdmissionRatio() > current.getAdmissionRatio()) {
                InitialRecommendationInversion inversion = new InitialRecommendationInversion();
                inversion.previous = previous;
                inversion.current = current;
                inversion.delta = previous.getAdmissionRatio() - current.getAdmissionRatio();
                inversions.add(inversion);
            }
        }
        inversions.sort(Comparator.comparing((InitialRecommendationInversion inversion) -> inversion.delta, Comparator.reverseOrder()));
        return inversions;
    }

    private int compareInitialRecommendationGapSwap(InitialRecommendationGapSwap left,
                                                    InitialRecommendationGapSwap right) {
        int compare = Integer.compare(left.metricsAfter.gapCount, right.metricsAfter.gapCount);
        if (compare != 0) {
            return compare;
        }
        compare = Double.compare(left.metricsAfter.maxGap, right.metricsAfter.maxGap);
        if (compare != 0) {
            return compare;
        }
        compare = Integer.compare(left.tierDeviationAfter, right.tierDeviationAfter);
        if (compare != 0) {
            return compare;
        }
        compare = Double.compare(distanceToGapMidpoint(left.filler, left.coveringGap),
                distanceToGapMidpoint(right.filler, right.coveringGap));
        if (compare != 0) {
            return compare;
        }
        compare = compareInitialRecommendationReplacementTradeoff(left.removable, left.filler,
                right.removable, right.filler);
        if (compare != 0) {
            return compare;
        }
        compare = buildInitialRecommendationRemovableComparator(null).compare(left.removable, right.removable);
        if (compare != 0) {
            return compare;
        }
        return buildInitialRecommendationCandidateComparator().compare(left.filler, right.filler);
    }

    private int compareInitialRecommendationReplacementTradeoff(CandidateItemDTO leftRemove,
                                                                CandidateItemDTO leftAdd,
                                                                CandidateItemDTO rightRemove,
                                                                CandidateItemDTO rightAdd) {
        return RepairReplacementTradeoffSupport.compareTradeoff(leftRemove, leftAdd, rightRemove, rightAdd);
    }

    private double distanceToGapMidpoint(CandidateItemDTO filler, InitialRecommendationGap gap) {
        if (filler == null || filler.getAdmissionRatio() == null || gap == null
                || gap.left == null || gap.left.getAdmissionRatio() == null
                || gap.right == null || gap.right.getAdmissionRatio() == null) {
            return Double.MAX_VALUE;
        }
        double min = Math.min(gap.left.getAdmissionRatio(), gap.right.getAdmissionRatio());
        double max = Math.max(gap.left.getAdmissionRatio(), gap.right.getAdmissionRatio());
        return Math.abs(filler.getAdmissionRatio() - ((min + max) / 2D));
    }

    private boolean isBetterInitialRecommendationGapMetrics(InitialRecommendationGapMetrics candidate,
                                                            InitialRecommendationGapMetrics baseline) {
        if (candidate == null || baseline == null) {
            return false;
        }
        if (candidate.gapCount < baseline.gapCount) {
            return true;
        }
        return candidate.gapCount == baseline.gapCount && candidate.maxGap < baseline.maxGap;
    }

    private InitialRecommendationGapMetrics evaluateInitialRecommendationGapMetricsAfterSwap(List<CandidateItemDTO> selected,
                                                                                             CandidateItemDTO removable,
                                                                                             CandidateItemDTO filler) {
        List<CandidateItemDTO> simulated = Lists.newArrayList();
        for (CandidateItemDTO item : defaultCandidates(selected)) {
            if (!item.getVolunteerId().equals(removable.getVolunteerId())) {
                simulated.add(item);
            }
        }
        simulated.add(filler);
        return evaluateInitialRecommendationGapMetrics(simulated);
    }

    private InitialRecommendationGapMetrics evaluateInitialRecommendationGapMetrics(List<CandidateItemDTO> selected) {
        InitialRecommendationGapMetrics metrics = new InitialRecommendationGapMetrics();
        List<InitialRecommendationGap> gaps = findInitialRecommendationGaps(selected);
        metrics.gapCount = gaps.size();
        metrics.maxGap = gaps.stream()
                .mapToDouble(gap -> gap.delta)
                .max()
                .orElse(0D);
        return metrics;
    }

    private List<InitialRecommendationGap> findInitialRecommendationGaps(List<CandidateItemDTO> selected) {
        List<CandidateItemDTO> ordered = defaultCandidates(selected).stream()
                .filter(item -> item.getAdmissionRatio() != null)
                .sorted(Comparator.comparing(CandidateItemDTO::getAdmissionRatio))
                .collect(Collectors.toList());
        List<InitialRecommendationGap> gaps = Lists.newArrayList();
        for (int i = 1; i < ordered.size(); i++) {
            CandidateItemDTO previous = ordered.get(i - 1);
            CandidateItemDTO current = ordered.get(i);
            if (previous.getAdmissionRatio() == null || current.getAdmissionRatio() == null) {
                continue;
            }
            double delta = Math.abs(current.getAdmissionRatio() - previous.getAdmissionRatio());
            if (delta > 8D) {
                InitialRecommendationGap gap = new InitialRecommendationGap();
                gap.left = previous;
                gap.right = current;
                gap.delta = delta;
                gaps.add(gap);
            }
        }
        gaps.sort(Comparator.comparing((InitialRecommendationGap gap) -> gap.delta, Comparator.reverseOrder()));
        return gaps;
    }

    private InitialRecommendationGap findCoveringInitialRecommendationGap(List<InitialRecommendationGap> gaps,
                                                                          CandidateItemDTO filler) {
        if (filler == null || filler.getAdmissionRatio() == null) {
            return null;
        }
        for (InitialRecommendationGap gap : gaps) {
            if (gap == null || gap.left == null || gap.left.getAdmissionRatio() == null
                    || gap.right == null || gap.right.getAdmissionRatio() == null) {
                continue;
            }
            double min = Math.min(gap.left.getAdmissionRatio(), gap.right.getAdmissionRatio());
            double max = Math.max(gap.left.getAdmissionRatio(), gap.right.getAdmissionRatio());
            if (filler.getAdmissionRatio() > min && filler.getAdmissionRatio() < max) {
                return gap;
            }
        }
        return null;
    }

    private Map<String, Integer> countInitialRecommendationTiers(List<CandidateItemDTO> items) {
        Map<String, Integer> result = new LinkedHashMap<String, Integer>();
        result.put("冲", 0);
        result.put("稳", 0);
        result.put("保", 0);
        for (CandidateItemDTO item : defaultCandidates(items)) {
            String tier = Strings.isNullOrEmpty(item.getTier()) ? "保" : item.getTier();
            result.put(tier, result.getOrDefault(tier, 0) + 1);
        }
        return result;
    }

    private int calculateInitialRecommendationTierDeviation(List<CandidateItemDTO> items,
                                                            Map<String, Integer> targetTierCounts) {
        Map<String, Integer> counts = countInitialRecommendationTiers(items);
        int deviation = 0;
        for (String tier : Lists.newArrayList("冲", "稳", "保")) {
            deviation += Math.abs(counts.getOrDefault(tier, 0) - targetTierCounts.getOrDefault(tier, 0));
        }
        return deviation;
    }

    private int calculateInitialRecommendationTierDeviationAfterSwap(List<CandidateItemDTO> selected,
                                                                     CandidateItemDTO removable,
                                                                     CandidateItemDTO filler,
                                                                     Map<String, Integer> targetTierCounts) {
        List<CandidateItemDTO> simulated = Lists.newArrayList();
        for (CandidateItemDTO item : defaultCandidates(selected)) {
            if (!item.getVolunteerId().equals(removable.getVolunteerId())) {
                simulated.add(item);
            }
        }
        simulated.add(filler);
        return calculateInitialRecommendationTierDeviation(simulated, targetTierCounts);
    }

    private boolean isAcceptableInitialRecommendationTierSwap(Map<String, Integer> currentTierCounts,
                                                              CandidateItemDTO removable,
                                                              CandidateItemDTO filler,
                                                              Map<String, Integer> targetTierCounts) {
        if (removable == null || filler == null) {
            return false;
        }
        String removeTier = Strings.isNullOrEmpty(removable.getTier()) ? "保" : removable.getTier();
        String addTier = Strings.isNullOrEmpty(filler.getTier()) ? "保" : filler.getTier();
        if (removeTier.equals(addTier)) {
            return true;
        }
        int currentRemoveCount = currentTierCounts.getOrDefault(removeTier, 0);
        int currentAddCount = currentTierCounts.getOrDefault(addTier, 0);
        int removeTarget = targetTierCounts.getOrDefault(removeTier, 0);
        int addTarget = targetTierCounts.getOrDefault(addTier, 0);
        if (currentRemoveCount <= removeTarget) {
            return false;
        }
        if (currentAddCount >= addTarget) {
            return false;
        }
        return true;
    }

    private int countLocalProtectCandidates(List<CandidateItemDTO> items, String sourceProvinceName) {
        if (Strings.isNullOrEmpty(sourceProvinceName)) {
            return 0;
        }
        int count = 0;
        for (CandidateItemDTO item : defaultCandidates(items)) {
            if (isLocalProtectCandidate(item, sourceProvinceName)) {
                count++;
            }
        }
        return count;
    }

    private boolean isLocalProtectCandidate(CandidateItemDTO item, String sourceProvinceName) {
        return item != null
                && "保".equals(item.getTier())
                && !Strings.isNullOrEmpty(sourceProvinceName)
                && containsIgnoreCase(item.getProvinceName(), sourceProvinceName);
    }

    private void initializeTierCounts(Map<String, Integer> tierCounts) {
        if (tierCounts == null) {
            return;
        }
        tierCounts.putIfAbsent("冲", 0);
        tierCounts.putIfAbsent("稳", 0);
        tierCounts.putIfAbsent("保", 0);
    }

    private boolean sameTier(CandidateItemDTO left, CandidateItemDTO right) {
        if (left == null || right == null) {
            return false;
        }
        return Strings.nullToEmpty(left.getTier()).equals(Strings.nullToEmpty(right.getTier()));
    }

    private String resolveInitialRecommendationUnitId(CandidateItemDTO item) {
        if (item == null) {
            return null;
        }
        if (!Strings.isNullOrEmpty(item.getPlanSchoolDataId())) {
            return item.getPlanSchoolDataId();
        }
        if (!Strings.isNullOrEmpty(item.getSchoolId())) {
            return item.getSchoolId();
        }
        return item.getSchoolName();
    }

    private void sortInitialRecommendationSelected(List<CandidateItemDTO> selected) {
        selected.sort(Comparator
                .comparing((CandidateItemDTO item) -> initialRecommendationTierOrder(item.getTier()))
                .thenComparing((CandidateItemDTO item) -> item.getAdmissionRatio(),
                        Comparator.nullsLast(Double::compareTo))
                .thenComparing((CandidateItemDTO item) -> item.getFinalScore() == null ? 0D : item.getFinalScore(),
                        Comparator.reverseOrder()));
    }

    private int initialRecommendationTierOrder(String tier) {
        if ("冲".equals(tier)) {
            return 0;
        }
        if ("稳".equals(tier)) {
            return 1;
        }
        if ("保".equals(tier)) {
            return 2;
        }
        return 3;
    }

    private boolean isMajorGroupMode(CandidatePoolStateDTO candidatePoolState) {
        return candidatePoolState != null
                && "majorGroup".equalsIgnoreCase(candidatePoolState.getVolunteerModel());
    }

    private boolean isMajorMode(CandidatePoolStateDTO candidatePoolState) {
        return candidatePoolState != null
                && "major".equalsIgnoreCase(candidatePoolState.getVolunteerModel());
    }

    private Map<String, List<CandidateItemDTO>> groupCandidatesByUnit(List<CandidateItemDTO> candidates) {
        Map<String, List<CandidateItemDTO>> grouped = new LinkedHashMap<String, List<CandidateItemDTO>>();
        for (CandidateItemDTO candidate : defaultCandidates(candidates)) {
            String unitId = resolveInitialRecommendationUnitId(candidate);
            if (Strings.isNullOrEmpty(unitId)) {
                unitId = Strings.isNullOrEmpty(candidate.getVolunteerId()) ? String.valueOf(grouped.size()) : candidate.getVolunteerId();
            }
            grouped.computeIfAbsent(unitId, key -> Lists.newArrayList()).add(candidate);
        }
        return grouped;
    }

    private List<PlanningUnitDTO> groupCandidatesToPlanningUnits(List<CandidateItemDTO> candidates,
                                                                 Integer requiredMajorCount) {
        Map<String, List<CandidateItemDTO>> groupedCandidates = groupCandidatesByUnit(candidates);
        List<PlanningUnitDTO> units = Lists.newArrayList();
        for (List<CandidateItemDTO> unitCandidates : groupedCandidates.values()) {
            PlanningUnitDTO unit = buildPlanningUnit(unitCandidates, requiredMajorCount);
            if (unit != null) {
                units.add(unit);
            }
        }
        return units;
    }

    private PlanningUnitDTO buildPlanningUnit(List<CandidateItemDTO> unitCandidates,
                                              Integer requiredMajorCount) {
        if (unitCandidates == null || unitCandidates.isEmpty()) {
            return null;
        }
        CandidateItemDTO representative = buildMajorGroupUnitRepresentative(unitCandidates);
        if (representative == null) {
            return null;
        }
        MajorGroupSelectedMajorsResult majorsResult = selectMajorGroupPreferredMajors(
                unitCandidates,
                requiredMajorCount,
                representative.getSchoolEnrollRatio());

        PlanningUnitDTO unit = new PlanningUnitDTO();
        unit.setUnitId(resolveInitialRecommendationUnitId(representative));
        unit.setPlanSchoolDataId(representative.getPlanSchoolDataId());
        unit.setSchoolId(representative.getSchoolId());
        unit.setSchoolName(representative.getSchoolName());
        unit.setProvinceName(representative.getProvinceName());
        unit.setCityName(representative.getCityName());
        // 区域 ID 一起带上 ✓（"ID 优先"要一路传到计划单元上 ✓，否则组模式只能按名字 ✓）
        unit.setProvinceId(representative.getProvinceId());
        unit.setCityId(representative.getCityId());
        unit.setSchoolLevel(representative.getSchoolLevel());
        unit.setSchoolNature(representative.getSchoolNature());
        unit.setSchoolCategory(representative.getSchoolCategory());
        unit.setTier(representative.getTier());
        unit.setSchoolEnrollRatio(representative.getSchoolEnrollRatio());
        unit.setFinalScore(representative.getFinalScore());
        unit.setIntentScore(representative.getIntentScore());
        unit.setAdmissionRatio(representative.getAdmissionRatio());
        unit.setFutureDevelopmentScore(representative.getFutureDevelopmentScore());
        unit.setPreferred(representative.getPreferred());
        unit.setRequiredMajorCount(requiredMajorCount == null ? 0 : requiredMajorCount);
        unit.setHasSafetyMajor(majorsResult.hasSafetyCandidate);
        unit.setTotalMajorCount(defaultCandidates(unitCandidates).size());
        unit.setAllMajors(defaultCandidates(unitCandidates).stream()
                .sorted(buildMajorGroupInnerCandidateComparator())
                .map(this::toPlanningUnitMajor)
                .collect(Collectors.toList()));
        unit.setSelectedMajors(defaultCandidates(majorsResult.selectedMajors).stream()
                .map(candidate -> toPlanningUnitMajor(candidate, true,
                        isSafetyMajorRatio(candidate.getAdmissionRatio(), representative.getSchoolEnrollRatio())))
                .sorted(buildSelectedMajorDisplayComparator())
                .collect(Collectors.toList()));
        unit.setSelectedMajorCount(unit.getSelectedMajors().size());
        unit.setComplete(requiredMajorCount == null
                || requiredMajorCount <= 0
                || unit.getSelectedMajorCount() >= requiredMajorCount);
        return unit;
    }

    private PlanningUnitMajorDTO toPlanningUnitMajor(CandidateItemDTO candidate) {
        return toPlanningUnitMajor(candidate, false, false);
    }

    private PlanningUnitMajorDTO toPlanningUnitMajor(CandidateItemDTO candidate,
                                                     boolean selected,
                                                     boolean safetyMajor) {
        if (candidate == null) {
            return null;
        }
        PlanningUnitMajorDTO major = new PlanningUnitMajorDTO();
        major.setVolunteerId(candidate.getVolunteerId());
        major.setMajorId(candidate.getMajorId());
        major.setMajorName(candidate.getMajorName());
        major.setMajorCode(candidate.getMajorCode());
        major.setMajorCategoryId(candidate.getMajorCategoryId());
        major.setMajorSubCategoryId(candidate.getMajorSubCategoryId());
        // 分类名随候选带上 ✓：单元侧的专业筛选（`RepairCandidateEligibility`）按这两个名字比对 ✓。
        major.setMajorCategory(candidate.getMajorCategory());
        major.setMajorDiscipline(candidate.getMajorDiscipline());
        major.setTier(candidate.getTier());
        major.setAdmissionRatio(candidate.getAdmissionRatio());
        major.setFinalScore(candidate.getFinalScore());
        major.setIntentScore(candidate.getIntentScore());
        major.setPreferred(candidate.getPreferred());
        major.setSelected(selected);
        major.setSafetyMajor(safetyMajor);
        major.setTuitionPerYear(candidate.getTuitionPerYear());
        major.setRankInTier(candidate.getRankInTier());
        major.setReasonCodes(defaultList(candidate.getReasonCodes()));
        major.setMajorPlanTags(defaultList(candidate.getMajorPlanTags()));
        return major;
    }

    private Map<String, Integer> countUnitTierCounts(List<PlanningUnitDTO> units) {
        Map<String, Integer> counts = new LinkedHashMap<String, Integer>();
        counts.put("冲", 0);
        counts.put("稳", 0);
        counts.put("保", 0);
        for (PlanningUnitDTO unit : units == null ? Lists.<PlanningUnitDTO>newArrayList() : units) {
            String tier = unit == null || Strings.isNullOrEmpty(unit.getTier()) ? "保" : unit.getTier();
            counts.put(tier, counts.getOrDefault(tier, 0) + 1);
        }
        return counts;
    }

    private PlanningUnitDTO evaluatePlanningUnitQuality(List<CandidateItemDTO> unitCandidates,
                                                        Integer requiredMajorCount) {
        return buildPlanningUnit(unitCandidates, requiredMajorCount);
    }

    private CandidateItemDTO toPlanningUnitRepresentativeCandidate(PlanningUnitDTO unit) {
        if (unit == null || Strings.isNullOrEmpty(unit.getUnitId())) {
            return null;
        }
        CandidateItemDTO representative = new CandidateItemDTO();
        representative.setVolunteerId(unit.getUnitId());
        representative.setPlanSchoolDataId(unit.getPlanSchoolDataId());
        representative.setSchoolId(unit.getSchoolId());
        representative.setSchoolName(unit.getSchoolName());
        representative.setProvinceName(unit.getProvinceName());
        representative.setCityName(unit.getCityName());
        // 反过来（单元 → 代表候选）也一样 ✓：这里漏抄 ID ✗，组模式的"单元匹配"就只能按名字 ✓
        representative.setProvinceId(unit.getProvinceId());
        representative.setCityId(unit.getCityId());
        representative.setSchoolLevel(unit.getSchoolLevel());
        representative.setSchoolNature(unit.getSchoolNature());
        representative.setSchoolCategory(unit.getSchoolCategory());
        representative.setTier(unit.getTier());
        representative.setSchoolEnrollRatio(unit.getSchoolEnrollRatio());
        representative.setFinalScore(unit.getFinalScore());
        representative.setIntentScore(unit.getIntentScore());
        representative.setFutureDevelopmentScore(unit.getFutureDevelopmentScore());
        representative.setAdmissionRatio(unit.getAdmissionRatio());
        representative.setPreferred(unit.getPreferred());
        return representative;
    }

    private List<PlanningUnitMajorDTO> defaultPlanningUnitMajors(List<PlanningUnitMajorDTO> majors) {
        return majors == null ? Lists.newArrayList() : majors;
    }

    private CandidateItemDTO buildMajorGroupUnitRepresentative(List<CandidateItemDTO> unitCandidates) {
        if (unitCandidates == null || unitCandidates.isEmpty()) {
            return null;
        }
        CandidateItemDTO top = unitCandidates.stream()
                .sorted(buildMajorGroupInnerCandidateComparator())
                .findFirst()
                .orElse(unitCandidates.get(0));
        CandidateItemDTO representative = cloneCandidateItem(top);
        representative.setAdmissionRatio(top.getSchoolEnrollRatio() == null ? top.getAdmissionRatio() : top.getSchoolEnrollRatio());
        representative.setVolunteerId(top.getVolunteerId());
        return representative;
    }

    private Comparator<CandidateItemDTO> buildMajorGroupInnerCandidateComparator() {
        return Comparator
                .comparing((CandidateItemDTO item) -> Boolean.TRUE.equals(item.getPreferred()) ? 0 : 1)
                .thenComparing((CandidateItemDTO item) -> item.getFutureDevelopmentScore(),
                        Comparator.nullsLast(Comparator.reverseOrder()))
                .thenComparing((CandidateItemDTO item) -> item.getIntentScore(), Comparator.nullsLast(Comparator.reverseOrder()))
                .thenComparing((CandidateItemDTO item) -> item.getAdmissionRatio(), Comparator.nullsLast(Comparator.reverseOrder()))
                .thenComparing((CandidateItemDTO item) -> item.getFinalScore(), Comparator.nullsLast(Comparator.reverseOrder()))
                .thenComparing(CandidateItemDTO::getVolunteerId, Comparator.nullsLast(String::compareTo));
    }

    private Comparator<PlanningUnitMajorDTO> buildSelectedMajorDisplayComparator() {
        return Comparator
                .comparing((PlanningUnitMajorDTO item) -> item.getAdmissionRatio(), Comparator.nullsLast(Double::compareTo))
                .thenComparing((PlanningUnitMajorDTO item) -> item.getIntentScore(), Comparator.nullsLast(Comparator.reverseOrder()))
                .thenComparing((PlanningUnitMajorDTO item) -> item.getFinalScore(), Comparator.nullsLast(Comparator.reverseOrder()))
                .thenComparing(PlanningUnitMajorDTO::getVolunteerId, Comparator.nullsLast(String::compareTo));
    }

    private List<PlanningUnitMajorDTO> sortSelectedMajorsForDisplay(List<PlanningUnitMajorDTO> majors) {
        return defaultPlanningUnitMajors(majors).stream()
                .filter(Objects::nonNull)
                .sorted(buildSelectedMajorDisplayComparator())
                .collect(Collectors.toList());
    }

    private MajorGroupSelectedMajorsResult selectMajorGroupPreferredMajors(List<CandidateItemDTO> unitCandidates,
                                                                           Integer requiredMajorCount,
                                                                           Double unitEnrollRatio) {
        MajorGroupSelectedMajorsResult result = new MajorGroupSelectedMajorsResult();
        List<CandidateItemDTO> sortedCandidates = defaultCandidates(unitCandidates).stream()
                .sorted(buildMajorGroupInnerCandidateComparator())
                .collect(Collectors.toList());
        result.candidateHasAnyMajor = !sortedCandidates.isEmpty();
        if (sortedCandidates.isEmpty()) {
            return result;
        }

        int targetCount = requiredMajorCount == null || requiredMajorCount <= 0 ? sortedCandidates.size() : requiredMajorCount;
        if (targetCount <= 0) {
            return result;
        }

        CandidateItemDTO safetyMajor = sortedCandidates.stream()
                .filter(item -> item.getAdmissionRatio() != null
                        && unitEnrollRatio != null
                        && isSafetyMajorRatio(item.getAdmissionRatio(), unitEnrollRatio))
                .findFirst()
                .orElse(null);
        if (safetyMajor != null) {
            result.selectedMajors.add(safetyMajor);
            result.hasSafetyCandidate = true;
        }

        for (CandidateItemDTO candidate : sortedCandidates) {
            if (result.selectedMajors.size() >= targetCount) {
                break;
            }
            if (result.selectedMajors.stream().anyMatch(item -> item.getVolunteerId().equals(candidate.getVolunteerId()))) {
                continue;
            }
            result.selectedMajors.add(candidate);
        }
        return result;
    }

    private List<CandidateItemDTO> defaultCandidates(List<CandidateItemDTO> candidates) {
        return candidates == null ? Lists.newArrayList() : candidates;
    }

    private int defaultInt(Integer value) {
        return value == null ? 0 : value;
    }

    private boolean isSafetyMajorRatio(Double majorAdmissionRatio, Double unitEnrollRatio) {
        return majorAdmissionRatio != null
                && unitEnrollRatio != null
                && majorAdmissionRatio >= unitEnrollRatio;
    }

    private void addUnresolvedRuleCode(InitialRecommendationSelectionState selectionState, String ruleCode) {
        if (!selectionState.unresolvedRuleCodes.contains(ruleCode)) {
            selectionState.unresolvedRuleCodes.add(ruleCode);
        }
    }

    private void addUnresolvedRuleCode(List<String> unresolvedRuleCodes, String ruleCode) {
        if (unresolvedRuleCodes != null && !unresolvedRuleCodes.contains(ruleCode)) {
            unresolvedRuleCodes.add(ruleCode);
        }
    }

    private static class InitialRecommendationSelectionState {
        private final List<CandidateItemDTO> selected = Lists.newArrayList();
        private final List<CandidateItemDTO> remaining = Lists.newArrayList();
        private final Set<String> selectedIds = new LinkedHashSet<String>();
        private final Map<String, Integer> targetTierCounts = new LinkedHashMap<String, Integer>();
        private final Map<String, List<String>> selectionReasons = new LinkedHashMap<String, List<String>>();
        private final List<String> unresolvedRuleCodes = Lists.newArrayList();
        private final List<InitialPlanStrategyReportDTO.AppliedRepair> appliedRepairs = Lists.newArrayList();
        private final List<FixProposalActionDTO> actions = Lists.newArrayList();
        private final List<InitialPlanStrategyReportDTO.Tradeoff> tradeoffs = Lists.newArrayList();
        private int targetCount;
        private String sourceProvinceName;
        private Integer userScore;
        private Integer requiredMajorCount;
        private String volunteerModel;
        private int gapFixCount;
        private int unresolvedGapCount;
        private int unitCompletionCount;
        private int appliedRepairCount;
    }

    private static class MajorGroupInitialRecommendationSelection {
        private final List<PlanningUnitDTO> selectedUnits = Lists.newArrayList();
        private final List<String> unresolvedRuleCodes = Lists.newArrayList();
        private InitialRecommendationSelectionState groupSelectionState;
        private int majorSelectionRepairCount;
    }

    private static class MajorGroupSelectedMajorsResult {
        private final List<CandidateItemDTO> selectedMajors = Lists.newArrayList();
        private boolean hasSafetyCandidate;
        private boolean candidateHasAnyMajor;
    }

    private static class MajorGroupUnitQuality {
        private CandidateItemDTO representative;
        private boolean safe;
        private double finalScore;
        private double admissionRatio;

        private boolean isQualified() {
            return safe;
        }
    }

    private static class InitialRecommendationGap {
        private CandidateItemDTO left;
        private CandidateItemDTO right;
        private double delta;
    }

    private static class InitialRecommendationGapMetrics {
        private int gapCount;
        private double maxGap;
    }

    private static class InitialRecommendationGapSwap {
        private CandidateItemDTO filler;
        private CandidateItemDTO removable;
        private InitialRecommendationGap coveringGap;
        private InitialRecommendationGapMetrics metricsAfter;
        private int tierDeviationAfter;
    }

    private static class InitialRecommendationInversion {
        private CandidateItemDTO previous;
        private CandidateItemDTO current;
        private double delta;
    }

    private static class InitialRecommendationInversionMetrics {
        private int inversionCount;
        private double maxDelta;
    }

    private static class InitialRecommendationInversionSwap {
        private CandidateItemDTO filler;
        private CandidateItemDTO removable;
        private InitialRecommendationInversion targetInversion;
        private InitialRecommendationInversionMetrics metricsAfter;
    }

    private PlanAdjustmentStateDTO buildPlanAdjustmentState(PlanningStateDTO state, PlanAdjustmentAnalyzeReq req) {
        PlanAdjustmentStateDTO adjustmentState = new PlanAdjustmentStateDTO();
        adjustmentState.setGeneratedAt(OffsetDateTime.now().toString());
        adjustmentState.setSourceVersion(state.getVersion() == null ? 0 : state.getVersion());
        adjustmentState.setDraftVersion(state.getVersion() == null ? 0 : state.getVersion());
        adjustmentState.setOrderedVersion(state.getVersion() == null ? 0 : state.getVersion());
        adjustmentState.setStatus("ready");

        String target = normalizePlanAdjustmentTarget(req);
        List<CandidateItemDTO> effectiveCandidates = resolveEffectiveCandidates(null, state.getSessionId(), state, false);
        OrderedPlanStateDTO analysisOrderedState = buildPlanAdjustmentOrderedSnapshot(state, effectiveCandidates, target);
        OrderedPlanStateDTO structuralOrderedState = buildStructuralOrderedSnapshot(state.getCandidatePoolState(),
                analysisOrderedState,
                effectiveCandidates);
        PlanningStateDTO analysisState = buildPlanAdjustmentAnalysisState(state, structuralOrderedState);
        PlanningStateDTO flatAnalysisState = buildPlanAdjustmentAnalysisState(state, analysisOrderedState);

        List<ReviewCheckDTO> checks = Lists.newArrayList();
        checks.add(reviewCountValidation(analysisState, effectiveCandidates));
        checks.add(reviewRatioDistribution(analysisState));
        checks.add(reviewProbabilityInversion(analysisState, effectiveCandidates));
        checks.add(reviewProbabilityGap(analysisState, effectiveCandidates));
        checks.add(reviewSafetyGuard(analysisState, effectiveCandidates));
        checks.add(reviewMajorGroupSafetyIntentAlignment(flatAnalysisState));

        CompensationPreviewDTO compensationPreview = buildCompensationPreview(analysisState, effectiveCandidates);
        Map<String, List<CompensationActionDTO>> compensationMap = compensationPreview.getActions().stream()
                .filter(action -> !Strings.isNullOrEmpty(action.getSourceCheckCode()))
                .collect(Collectors.groupingBy(CompensationActionDTO::getSourceCheckCode,
                        LinkedHashMap::new,
                        Collectors.toList()));

        List<String> hitSummaries = Lists.newArrayList();
        for (ReviewCheckDTO check : checks) {
            List<CompensationActionDTO> linkedActions = compensationMap.get(check.getCode());
            enrichReviewMetadata(check);
            adjustmentState.getAnalysis().getRules().add(buildPlanAdjustmentRuleResult(check, linkedActions));
            if (Boolean.FALSE.equals(check.getPassed()) && !Strings.isNullOrEmpty(check.getSummary())) {
                hitSummaries.add(check.getSummary());
            }
            appendPlanAdjustmentSuggestions(adjustmentState,
                    check,
                    linkedActions,
                    effectiveCandidates,
                    target,
                    analysisOrderedState,
                    analysisState);
        }

        if (hitSummaries.isEmpty()) {
            adjustmentState.getAnalysis().setSummaryText("当前方案暂未发现需要立即处理的结构性问题。");
        } else {
            adjustmentState.getAnalysis().setSummaryText(String.join("；", hitSummaries));
        }
        return adjustmentState;
    }

    private String normalizePlanAdjustmentTarget(PlanAdjustmentAnalyzeReq req) {
        return req != null && "ordered".equalsIgnoreCase(req.getTarget()) ? "ordered" : "draft";
    }

    private OrderedPlanStateDTO buildPlanAdjustmentOrderedSnapshot(PlanningStateDTO state,
                                                                   List<CandidateItemDTO> candidates,
                                                                   String target) {
        OrderedPlanStateDTO snapshot = new OrderedPlanStateDTO();
        if ("ordered".equalsIgnoreCase(target) && state.getOrderedPlanState() != null
                && state.getOrderedPlanState().getItems() != null
                && !state.getOrderedPlanState().getItems().isEmpty()) {
            snapshot.setItems(state.getOrderedPlanState().getItems().stream()
                    .map(this::copyOrderedItem)
                    .collect(Collectors.toList()));
            snapshot.setUnits(defaultOrderedUnits(state.getOrderedPlanState().getUnits()).stream()
                    .map(this::copyOrderedUnit)
                    .collect(Collectors.toList()));
        } else {
            Map<String, OrderedItemDTO> existing = state.getOrderedPlanState() == null
                    || state.getOrderedPlanState().getItems() == null
                    ? new LinkedHashMap<String, OrderedItemDTO>()
                    : state.getOrderedPlanState().getItems().stream()
                    .collect(Collectors.toMap(OrderedItemDTO::getVolunteerId,
                            this::copyOrderedItem,
                            (left, right) -> left,
                            LinkedHashMap::new));
            snapshot.setItems(buildOrderedItemsFromWorkingPlan(state.getDraftPlanState(),
                    state.getCandidatePoolState(),
                    candidates,
                    existing,
                    false));
            if (isMajorGroupMode(state.getCandidatePoolState())) {
                snapshot.setUnits(buildOrderedUnitsFromOrderedItems(snapshot.getItems(), state.getDraftPlanState(), candidates));
            }
        }
        recalculateOrderedSummary(snapshot, state.getCandidatePoolState());
        return snapshot;
    }

    private OrderedItemDTO copyOrderedItem(OrderedItemDTO source) {
        OrderedItemDTO copy = new OrderedItemDTO();
        copy.setPosition(source.getPosition());
        copy.setVolunteerId(source.getVolunteerId());
        copy.setTier(source.getTier());
        copy.setSchoolName(source.getSchoolName());
        copy.setMajorName(source.getMajorName());
        copy.setLocked(source.getLocked());
        copy.setPinned(source.getPinned());
        copy.setPinnedPosition(source.getPinnedPosition());
        copy.setOrderedBy(source.getOrderedBy());
        copy.setOrderReason(source.getOrderReason());
        copy.setSource(source.getSource());
        return copy;
    }

    private OrderedUnitDTO copyOrderedUnit(OrderedUnitDTO source) {
        OrderedUnitDTO copy = new OrderedUnitDTO();
        copy.setPosition(source.getPosition());
        copy.setUnitId(source.getUnitId());
        copy.setPlanSchoolDataId(source.getPlanSchoolDataId());
        copy.setSchoolId(source.getSchoolId());
        copy.setSchoolUnitCode(source.getSchoolUnitCode());
        copy.setTier(source.getTier());
        copy.setSchoolName(source.getSchoolName());
        copy.setProvinceName(source.getProvinceName());
        copy.setCityName(source.getCityName());
        copy.setSchoolLevel(source.getSchoolLevel());
        copy.setSchoolNature(source.getSchoolNature());
        copy.setSchoolCategory(source.getSchoolCategory());
        copy.setSource(source.getSource());
        copy.setLocked(source.getLocked());
        copy.setPinned(source.getPinned());
        copy.setPinnedPosition(source.getPinnedPosition());
        copy.setOrderedBy(source.getOrderedBy());
        copy.setOrderReason(source.getOrderReason());
        copy.setAdmissionRatio(source.getAdmissionRatio());
        copy.setFinalScore(source.getFinalScore());
        copy.setSchoolEnrollRatio(source.getSchoolEnrollRatio());
        copy.setTotalMajorCount(source.getTotalMajorCount());
        copy.setMajorItems(Lists.newArrayList(defaultPlanningUnitMajors(source.getMajorItems())));
        return copy;
    }

    private OrderedPlanStateDTO buildStructuralOrderedSnapshot(CandidatePoolStateDTO candidatePoolState,
                                                               OrderedPlanStateDTO flatOrderedState,
                                                               List<CandidateItemDTO> candidates) {
        if (!isMajorGroupMode(candidatePoolState)
                || flatOrderedState == null
                || flatOrderedState.getItems() == null
                || flatOrderedState.getItems().isEmpty()) {
            return flatOrderedState;
        }
        OrderedPlanStateDTO snapshot = new OrderedPlanStateDTO();
        List<OrderedUnitDTO> units = defaultOrderedUnits(flatOrderedState.getUnits());
        if (units.isEmpty()) {
            units = buildOrderedUnitsFromOrderedItems(flatOrderedState.getItems(), null, candidates);
        } else {
            units = units.stream().map(this::copyOrderedUnit).collect(Collectors.toList());
        }
        Map<String, OrderedItemDTO> groupedItems = new LinkedHashMap<String, OrderedItemDTO>();
        for (OrderedUnitDTO unit : units) {
            if (unit == null || Strings.isNullOrEmpty(unit.getUnitId()) || groupedItems.containsKey(unit.getUnitId())) {
                continue;
            }
            OrderedItemDTO structuralItem = new OrderedItemDTO();
            structuralItem.setPosition(unit.getPosition());
            structuralItem.setVolunteerId(unit.getUnitId());
            structuralItem.setTier(unit.getTier());
            structuralItem.setSchoolName(unit.getSchoolName());
            structuralItem.setMajorName(unit.getSchoolName());
            structuralItem.setLocked(unit.getLocked());
            structuralItem.setPinned(unit.getPinned());
            structuralItem.setPinnedPosition(unit.getPinnedPosition());
            structuralItem.setOrderedBy(unit.getOrderedBy());
            structuralItem.setOrderReason("unit_order");
            structuralItem.setSource(unit.getSource());
            groupedItems.put(unit.getUnitId(), structuralItem);
        }
        snapshot.setItems(OrderedPlanPositioningSupport.rebuildItems(Lists.newArrayList(groupedItems.values())));
        snapshot.setUnits(units);
        snapshot.setGenerationMode(flatOrderedState.getGenerationMode());
        snapshot.setAutoCompleted(flatOrderedState.getAutoCompleted());
        snapshot.setGradientAdjusted(flatOrderedState.getGradientAdjusted());
        snapshot.setPreservedPinnedCount(flatOrderedState.getPreservedPinnedCount());
        snapshot.setPreservedManualOrderCount(flatOrderedState.getPreservedManualOrderCount());
        recalculateOrderedSummary(snapshot, candidatePoolState);
        return snapshot;
    }

    private PlanningStateDTO buildPlanAdjustmentAnalysisState(PlanningStateDTO state,
                                                              OrderedPlanStateDTO analysisOrderedState) {
        PlanningStateDTO analysisState = new PlanningStateDTO();
        analysisState.setSessionId(state.getSessionId());
        analysisState.setVersion(state.getVersion());
        analysisState.setCandidatePoolState(state.getCandidatePoolState());
        analysisState.setConstraintState(state.getConstraintState());
        analysisState.setWorkingPlanState(state.getWorkingPlanState());
        analysisState.setOrderedPlanState(analysisOrderedState);
        return analysisState;
    }

    private PlanAdjustmentRuleResultDTO buildPlanAdjustmentRuleResult(ReviewCheckDTO check,
                                                                      List<CompensationActionDTO> linkedActions) {
        PlanAdjustmentRuleResultDTO result = new PlanAdjustmentRuleResultDTO();
        result.setRuleCode(check.getCode());
        result.setLabel(check.getLabel());
        result.setCategory(check.getCategory());
        result.setScopeKind(check.getScopeKind());
        result.setFixability(check.getFixability());
        result.setSupportedFixStrategies(defaultList(check.getSupportedFixStrategies()));
        result.setDefaultFixStrategy(check.getDefaultFixStrategy());
        result.setSeverity(normalizePlanAdjustmentSeverity(check.getLevel()));
        result.setHit(Boolean.FALSE.equals(check.getPassed()));
        result.setReasonCode(check.getReasonCode());
        result.setSummary(check.getSummary());
        result.setAffectedUnitIds(defaultList(check.getAffectedUnitIds()));
        result.setAffectedVolunteerIds(defaultList(check.getAffectedVolunteerIds()));
        result.setSuggestionTypes(defaultPlanAdjustmentSuggestionTypes(check, linkedActions));
        return result;
    }

    private List<String> defaultPlanAdjustmentSuggestionTypes(ReviewCheckDTO check,
                                                              List<CompensationActionDTO> linkedActions) {
        LinkedHashSet<String> suggestionTypes = new LinkedHashSet<String>();
        if (linkedActions != null) {
            for (CompensationActionDTO action : linkedActions) {
                suggestionTypes.add("add");
            }
        }
        if (!Boolean.FALSE.equals(check.getPassed())) {
            return Lists.newArrayList(suggestionTypes);
        }
        if ("count_validation".equals(check.getCode())
                || "probability_gap".equals(check.getCode())
                || "safety_guard".equals(check.getCode())) {
            suggestionTypes.add("add");
        }
        if ("probability_gap".equals(check.getCode())) {
            suggestionTypes.add("replace");
        }
        if ("probability_inversion".equals(check.getCode())) {
            suggestionTypes.add("replace");
        }
        if ("ratio_distribution".equals(check.getCode())) {
            if (isRatioDistributionAddSuggestion(check)) {
                suggestionTypes.add("add");
            } else {
                suggestionTypes.add("replace");
            }
        }
        if ("probability_inversion".equals(check.getCode())) {
            suggestionTypes.add("reorder");
        }
        return Lists.newArrayList(suggestionTypes);
    }

    private void appendPlanAdjustmentSuggestions(PlanAdjustmentStateDTO adjustmentState,
                                                 ReviewCheckDTO check,
                                                 List<CompensationActionDTO> linkedActions,
                                                 List<CandidateItemDTO> candidates,
                                                 String target,
                                                 OrderedPlanStateDTO analysisOrderedState,
                                                 PlanningStateDTO analysisState) {
        if (linkedActions != null && !linkedActions.isEmpty()) {
            for (CompensationActionDTO action : linkedActions) {
                adjustmentState.getSuggestions().getAddSuggestions().add(
                        buildAddSuggestionFromCompensation(check, action, candidates, target));
            }
        }
        if (!Boolean.FALSE.equals(check.getPassed())) {
            return;
        }
        if ("ratio_distribution".equals(check.getCode()) && isRatioDistributionAddSuggestion(check)) {
            adjustmentState.getSuggestions().getAddSuggestions().add(
                    buildGenericAddSuggestion(check, target, "补充缺失区间志愿", "append_only"));
        }
        if ("probability_inversion".equals(check.getCode())) {
            ReorderSuggestionDTO suggestion = buildProbabilityInversionReorderSuggestion(check, target, analysisOrderedState, candidates);
            if (suggestion != null) {
                adjustmentState.getSuggestions().getReorderSuggestions().add(suggestion);
            }
            ReplaceSuggestionDTO replaceSuggestion = buildProbabilityInversionReplaceSuggestion(check, target, analysisOrderedState, candidates);
            if (replaceSuggestion != null) {
                adjustmentState.getSuggestions().getReplaceSuggestions().add(replaceSuggestion);
            }
            return;
        }
        if ("probability_gap".equals(check.getCode())) {
            ReplaceSuggestionDTO suggestion = buildProbabilityGapReplaceSuggestion(check, target, linkedActions, candidates);
            if (suggestion != null) {
                adjustmentState.getSuggestions().getReplaceSuggestions().add(suggestion);
            }
            return;
        }
        if ("ratio_distribution".equals(check.getCode()) && isRatioDistributionReplaceSuggestion(check, analysisOrderedState, linkedActions, analysisState)) {
            ReplaceSuggestionDTO suggestion = buildRatioDistributionReplaceSuggestion(check, target, linkedActions, analysisOrderedState, candidates);
            if (suggestion != null) {
                adjustmentState.getSuggestions().getReplaceSuggestions().add(suggestion);
            }
        }
    }

    private AddSuggestionDTO buildAddSuggestionFromCompensation(ReviewCheckDTO check,
                                                                CompensationActionDTO action,
                                                                List<CandidateItemDTO> candidates,
                                                                String target) {
        AddSuggestionDTO suggestion = new AddSuggestionDTO();
        suggestion.setId(action.getSourceCheckCode() + "_" + action.getType());
        suggestion.setRuleCode(action.getSourceCheckCode());
        suggestion.setTitle(action.getSummary());
        suggestion.setDescription(action.getDetail());
        suggestion.setSeverity(normalizePlanAdjustmentSeverity(action.getLevel()));
        suggestion.setTarget(target);
        if (!defaultList(check.getAffectedUnitIds()).isEmpty()) {
            suggestion.setAffectedUnitIds(defaultList(check.getAffectedUnitIds()));
        }
        suggestion.setAffectedVolunteerIds(defaultList(check.getAffectedVolunteerIds()));
        suggestion.setReasonCodes(Lists.newArrayList(action.getSourceCheckCode()));
        if (!defaultList(action.getUnitIds()).isEmpty()) {
            suggestion.setCandidateUnitIds(defaultList(action.getUnitIds()));
        }
        suggestion.setCandidateVolunteerIds(defaultList(action.getVolunteerIds()));
        suggestion.setCandidateSummaries(buildPlanAdjustmentCandidateSummaries(action.getVolunteerIds(), candidates));
        return suggestion;
    }

    private AddSuggestionDTO buildGenericAddSuggestion(ReviewCheckDTO check,
                                                       String target,
                                                       String title,
                                                       String preferredApplyMode) {
        AddSuggestionDTO suggestion = new AddSuggestionDTO();
        suggestion.setId(check.getCode() + "_generic_add");
        suggestion.setRuleCode(check.getCode());
        suggestion.setTitle(title);
        suggestion.setDescription(Strings.isNullOrEmpty(check.getSuggestedAction()) ? check.getSummary() : check.getSuggestedAction());
        suggestion.setSeverity(normalizePlanAdjustmentSeverity(check.getLevel()));
        suggestion.setTarget(target);
        if (!defaultList(check.getAffectedUnitIds()).isEmpty()) {
            suggestion.setAffectedUnitIds(defaultList(check.getAffectedUnitIds()));
        }
        suggestion.setAffectedVolunteerIds(defaultList(check.getAffectedVolunteerIds()));
        suggestion.setReasonCodes(Lists.newArrayList(check.getCode()));
        suggestion.setPreferredApplyMode(preferredApplyMode);
        return suggestion;
    }

    private ReorderSuggestionDTO buildProbabilityInversionReorderSuggestion(ReviewCheckDTO check,
                                                                            String target,
                                                                            OrderedPlanStateDTO analysisOrderedState,
                                                                            List<CandidateItemDTO> candidates) {
        if (analysisOrderedState == null || analysisOrderedState.getItems() == null || analysisOrderedState.getItems().isEmpty()) {
            return null;
        }
        List<String> affectedVolunteerIds = defaultList(check.getAffectedVolunteerIds());
        if (affectedVolunteerIds.size() < 2) {
            return null;
        }
        List<OrderedItemDTO> orderedItems = analysisOrderedState.getItems();
        List<Integer> originalPositions = Lists.newArrayList();
        for (OrderedItemDTO item : orderedItems) {
            if (affectedVolunteerIds.contains(item.getVolunteerId())) {
                originalPositions.add(item.getPosition());
            }
        }
        if (originalPositions.size() < 2) {
            return null;
        }

        List<String> reorderedAffectedIds = affectedVolunteerIds.stream()
                .sorted(Comparator.comparing((String volunteerId) -> admissionRatioOf(candidates, volunteerId),
                        Comparator.nullsLast(Double::compareTo)))
                .collect(Collectors.toList());

        List<String> fullOrderedIds = orderedItems.stream()
                .map(OrderedItemDTO::getVolunteerId)
                .collect(Collectors.toList());
        List<Integer> sortedPositions = originalPositions.stream()
                .sorted()
                .collect(Collectors.toList());
        for (int i = 0; i < sortedPositions.size() && i < reorderedAffectedIds.size(); i++) {
            int position = sortedPositions.get(i);
            int index = Math.max(0, position - 1);
            if (index < fullOrderedIds.size()) {
                fullOrderedIds.set(index, reorderedAffectedIds.get(i));
            }
        }

        ReorderSuggestionDTO suggestion = new ReorderSuggestionDTO();
        suggestion.setId(check.getCode() + "_reorder");
        suggestion.setRuleCode(check.getCode());
        suggestion.setTitle("调整相邻志愿顺序");
        suggestion.setDescription(Strings.isNullOrEmpty(check.getSuggestedAction()) ? check.getSummary() : check.getSuggestedAction());
        suggestion.setSeverity(normalizePlanAdjustmentSeverity(check.getLevel()));
        suggestion.setTarget(target);
        if (!defaultList(check.getAffectedUnitIds()).isEmpty()) {
            suggestion.setAffectedUnitIds(defaultList(check.getAffectedUnitIds()));
        }
        suggestion.setAffectedVolunteerIds(affectedVolunteerIds);
        suggestion.setReasonCodes(Lists.newArrayList(check.getCode()));
        suggestion.setFromPositions(Lists.newArrayList(sortedPositions));
        List<Integer> toPositions = reorderedAffectedIds.stream()
                .map(fullOrderedIds::indexOf)
                .filter(index -> index >= 0)
                .map(index -> index + 1)
                .collect(Collectors.toList());
        suggestion.setToPositions(toPositions);
        if (!defaultList(check.getAffectedUnitIds()).isEmpty()) {
            suggestion.setOrderedUnitIds(resolveOrderedUnitIds(fullOrderedIds, analysisOrderedState, candidates));
        }
        suggestion.setOrderedVolunteerIds(fullOrderedIds);
        suggestion.setPreferredApplyMode("reorder_only");
        return suggestion;
    }

    private ReplaceSuggestionDTO buildProbabilityGapReplaceSuggestion(ReviewCheckDTO check,
                                                                      String target,
                                                                      List<CompensationActionDTO> linkedActions,
                                                                      List<CandidateItemDTO> candidates) {
        CompensationActionDTO action = (linkedActions == null ? Lists.<CompensationActionDTO>newArrayList() : linkedActions).stream()
                .filter(item -> "probability_gap".equals(item.getSourceCheckCode()))
                .findFirst()
                .orElse(null);
        List<String> affectedVolunteerIds = defaultList(check.getAffectedVolunteerIds());
        if (affectedVolunteerIds.size() < 2) {
            return null;
        }
        String removableVolunteerId = resolveProbabilityGapReplacementSource(affectedVolunteerIds, candidates);
        if (Strings.isNullOrEmpty(removableVolunteerId)) {
            return null;
        }
        List<String> replacementVolunteerIds = action == null
                ? resolveProbabilityGapReplacementCandidates(affectedVolunteerIds, candidates)
                : defaultList(action.getVolunteerIds());
        if (replacementVolunteerIds.isEmpty()) {
            return null;
        }

        ReplaceSuggestionDTO suggestion = new ReplaceSuggestionDTO();
        suggestion.setId(check.getCode() + "_replace");
        suggestion.setRuleCode(check.getCode());
        suggestion.setTitle("替换断层边界志愿");
        suggestion.setDescription(action == null || Strings.isNullOrEmpty(action.getDetail()) ? check.getSummary() : action.getDetail());
        suggestion.setSeverity(normalizePlanAdjustmentSeverity(check.getLevel()));
        suggestion.setTarget(target);
        if (!defaultList(check.getAffectedUnitIds()).isEmpty()) {
            suggestion.setAffectedUnitIds(defaultList(check.getAffectedUnitIds()));
        }
        suggestion.setAffectedVolunteerIds(affectedVolunteerIds);
        suggestion.setReasonCodes(Lists.newArrayList(check.getCode()));
        if (!defaultList(check.getAffectedUnitIds()).isEmpty() || action != null && !defaultList(action.getUnitIds()).isEmpty()) {
            suggestion.setRemoveUnitIds(resolveUnitIdsFromVolunteerIds(Lists.newArrayList(removableVolunteerId), candidates));
        }
        suggestion.setRemoveVolunteerIds(Lists.newArrayList(removableVolunteerId));
        if (action != null && !defaultList(action.getUnitIds()).isEmpty()) {
            suggestion.setCandidateUnitIds(defaultList(action.getUnitIds()));
        } else if (!defaultList(check.getAffectedUnitIds()).isEmpty()) {
            suggestion.setCandidateUnitIds(resolveUnitIdsFromVolunteerIds(replacementVolunteerIds, candidates));
        }
        suggestion.setCandidateVolunteerIds(replacementVolunteerIds);
        for (String candidateVolunteerId : replacementVolunteerIds) {
            ReplacementPairDTO pair = new ReplacementPairDTO();
            pair.setFromUnitId(suggestion.getRemoveUnitIds().isEmpty() ? null : suggestion.getRemoveUnitIds().get(0));
            pair.setFromVolunteerId(removableVolunteerId);
            if (!suggestion.getCandidateUnitIds().isEmpty()) {
                pair.setToUnitId(resolveUnitId(candidateVolunteerId, candidates));
            }
            pair.setToVolunteerId(candidateVolunteerId);
            pair.setReasonCodes(Lists.newArrayList(check.getCode(),
                    RepairProposalTaxonomy.CompensationActionType.FILL_PROBABILITY_GAP));
            suggestion.getReplacementPairs().add(pair);
        }
        suggestion.setPreferredApplyMode("replace_and_reorder");
        return suggestion;
    }

    private List<String> resolveProbabilityGapReplacementCandidates(List<String> affectedVolunteerIds,
                                                                     List<CandidateItemDTO> candidates) {
        if (affectedVolunteerIds == null || affectedVolunteerIds.size() < 2) {
            return Lists.newArrayList();
        }
        List<CandidateItemDTO> affectedCandidates = affectedVolunteerIds.stream()
                .map(volunteerId -> findCandidate(candidates, volunteerId))
                .filter(Objects::nonNull)
                .filter(item -> item.getAdmissionRatio() != null)
                .collect(Collectors.toList());
        if (affectedCandidates.size() < 2) {
            return Lists.newArrayList();
        }
        double min = affectedCandidates.stream().map(CandidateItemDTO::getAdmissionRatio).min(Double::compareTo).orElse(0D);
        double max = affectedCandidates.stream().map(CandidateItemDTO::getAdmissionRatio).max(Double::compareTo).orElse(0D);
        double midpoint = (min + max) / 2D;
        Set<String> affectedSet = new LinkedHashSet<String>(affectedVolunteerIds);
        return candidates.stream()
                .filter(item -> item != null && !affectedSet.contains(item.getVolunteerId()))
                .filter(item -> item.getAdmissionRatio() != null)
                .filter(item -> item.getAdmissionRatio() > min && item.getAdmissionRatio() < max)
                .sorted(Comparator
                        .comparingDouble((CandidateItemDTO item) -> Math.abs(item.getAdmissionRatio() - midpoint))
                        .thenComparing(buildInitialRecommendationCandidateComparator()))
                .limit(2)
                .map(CandidateItemDTO::getVolunteerId)
                .collect(Collectors.toList());
    }

    private ReplaceSuggestionDTO buildProbabilityInversionReplaceSuggestion(ReviewCheckDTO check,
                                                                            String target,
                                                                            OrderedPlanStateDTO analysisOrderedState,
                                                                            List<CandidateItemDTO> candidates) {
        if (analysisOrderedState == null || analysisOrderedState.getItems() == null || analysisOrderedState.getItems().isEmpty()) {
            return null;
        }
        List<String> affectedVolunteerIds = defaultList(check.getAffectedVolunteerIds());
        if (affectedVolunteerIds.size() < 2) {
            return null;
        }
        Map<String, OrderedItemDTO> orderedMap = analysisOrderedState.getItems().stream()
                .collect(Collectors.toMap(OrderedItemDTO::getVolunteerId, item -> item, (left, right) -> left, LinkedHashMap::new));
        OrderedItemDTO previousOrdered = orderedMap.get(affectedVolunteerIds.get(0));
        OrderedItemDTO currentOrdered = orderedMap.get(affectedVolunteerIds.get(1));
        if (previousOrdered == null || currentOrdered == null) {
            return null;
        }
        Double previousRatio = admissionRatioOf(candidates, previousOrdered.getVolunteerId());
        Double currentRatio = admissionRatioOf(candidates, currentOrdered.getVolunteerId());
        if (previousRatio == null || currentRatio == null || previousRatio <= currentRatio) {
            return null;
        }
        Set<String> existingIds = analysisOrderedState.getItems().stream()
                .map(OrderedItemDTO::getVolunteerId)
                .collect(Collectors.toSet());

        List<CandidateItemDTO> previousSideCandidates = candidates.stream()
                .filter(item -> !existingIds.contains(item.getVolunteerId()))
                .filter(item -> sameTierValue(item.getTier(), previousOrdered.getTier()))
                .filter(item -> item.getAdmissionRatio() != null && item.getAdmissionRatio() <= currentRatio)
                .sorted(Comparator
                        .comparingDouble((CandidateItemDTO item) -> Math.abs(item.getAdmissionRatio() - currentRatio))
                        .thenComparing(buildInitialRecommendationCandidateComparator()))
                .collect(Collectors.toList());

        List<CandidateItemDTO> currentSideCandidates = candidates.stream()
                .filter(item -> !existingIds.contains(item.getVolunteerId()))
                .filter(item -> sameTierValue(item.getTier(), currentOrdered.getTier()))
                .filter(item -> item.getAdmissionRatio() != null && item.getAdmissionRatio() >= previousRatio)
                .sorted(Comparator
                        .comparingDouble((CandidateItemDTO item) -> Math.abs(item.getAdmissionRatio() - previousRatio))
                        .thenComparing(buildInitialRecommendationCandidateComparator()))
                .collect(Collectors.toList());

        String removeVolunteerId;
        List<CandidateItemDTO> replacementCandidates;
        if (!previousSideCandidates.isEmpty()) {
            removeVolunteerId = previousOrdered.getVolunteerId();
            replacementCandidates = previousSideCandidates;
        } else if (!currentSideCandidates.isEmpty()) {
            removeVolunteerId = currentOrdered.getVolunteerId();
            replacementCandidates = currentSideCandidates;
        } else {
            return null;
        }

        ReplaceSuggestionDTO suggestion = new ReplaceSuggestionDTO();
        suggestion.setId(check.getCode() + "_replace");
        suggestion.setRuleCode(check.getCode());
        suggestion.setTitle("替换倒挂条目");
        suggestion.setDescription(Strings.isNullOrEmpty(check.getSuggestedAction()) ? check.getSummary() : check.getSuggestedAction());
        suggestion.setSeverity(normalizePlanAdjustmentSeverity(check.getLevel()));
        suggestion.setTarget(target);
        if (!defaultList(check.getAffectedUnitIds()).isEmpty()) {
            suggestion.setAffectedUnitIds(defaultList(check.getAffectedUnitIds()));
        }
        suggestion.setAffectedVolunteerIds(affectedVolunteerIds);
        suggestion.setReasonCodes(Lists.newArrayList(check.getCode()));
        if (!defaultList(check.getAffectedUnitIds()).isEmpty()) {
            suggestion.setRemoveUnitIds(resolveUnitIdsFromVolunteerIds(Lists.newArrayList(removeVolunteerId), candidates));
        }
        suggestion.setRemoveVolunteerIds(Lists.newArrayList(removeVolunteerId));
        List<String> candidateVolunteerIds = replacementCandidates.stream()
                .limit(2)
                .map(CandidateItemDTO::getVolunteerId)
                .collect(Collectors.toList());
        suggestion.setCandidateVolunteerIds(candidateVolunteerIds);
        if (!defaultList(check.getAffectedUnitIds()).isEmpty()) {
            suggestion.setCandidateUnitIds(resolveUnitIdsFromVolunteerIds(candidateVolunteerIds, candidates));
        }
        for (String candidateVolunteerId : suggestion.getCandidateVolunteerIds()) {
            ReplacementPairDTO pair = new ReplacementPairDTO();
            pair.setFromUnitId(suggestion.getRemoveUnitIds().isEmpty() ? null : suggestion.getRemoveUnitIds().get(0));
            pair.setFromVolunteerId(removeVolunteerId);
            if (!suggestion.getCandidateUnitIds().isEmpty()) {
                pair.setToUnitId(resolveUnitId(candidateVolunteerId, candidates));
            }
            pair.setToVolunteerId(candidateVolunteerId);
            pair.setReasonCodes(Lists.newArrayList(check.getCode(), "same_tier_inversion_repair"));
            suggestion.getReplacementPairs().add(pair);
        }
        suggestion.setPreferredApplyMode("replace_and_reorder");
        return suggestion;
    }

    private ReplaceSuggestionDTO buildRatioDistributionReplaceSuggestion(ReviewCheckDTO check,
                                                                         String target,
                                                                         List<CompensationActionDTO> linkedActions,
                                                                         OrderedPlanStateDTO analysisOrderedState,
                                                                         List<CandidateItemDTO> candidates) {
        if (analysisOrderedState == null || analysisOrderedState.getItems() == null || analysisOrderedState.getItems().isEmpty()) {
            return null;
        }
        CompensationActionDTO action = linkedActions == null ? null : linkedActions.stream()
                .filter(item -> "ratio_distribution".equals(item.getSourceCheckCode()))
                .findFirst()
                .orElse(null);
        if (action == null || defaultList(action.getVolunteerIds()).isEmpty()) {
            return null;
        }
        List<String> removeVolunteerIds = analysisOrderedState.getItems().stream()
                .filter(item -> "冲".equals(item.getTier()))
                .sorted(Comparator.comparing((OrderedItemDTO item) -> admissionRatioOf(candidates, item.getVolunteerId()),
                        Comparator.nullsLast(Double::compareTo)))
                .limit(action.getVolunteerIds().size())
                .map(OrderedItemDTO::getVolunteerId)
                .collect(Collectors.toList());
        if (removeVolunteerIds.isEmpty()) {
            return null;
        }

        ReplaceSuggestionDTO suggestion = new ReplaceSuggestionDTO();
        suggestion.setId(check.getCode() + "_replace");
        suggestion.setRuleCode(check.getCode());
        suggestion.setTitle("平衡冲稳保区间配比");
        suggestion.setDescription(Strings.isNullOrEmpty(action.getDetail()) ? check.getSummary() : action.getDetail());
        suggestion.setSeverity(normalizePlanAdjustmentSeverity(check.getLevel()));
        suggestion.setTarget(target);
        if (!defaultList(action.getUnitIds()).isEmpty()) {
            suggestion.setAffectedUnitIds(resolveUnitIdsFromVolunteerIds(removeVolunteerIds, candidates));
        }
        suggestion.setAffectedVolunteerIds(Lists.newArrayList(removeVolunteerIds));
        suggestion.setReasonCodes(Lists.newArrayList(check.getCode(),
                RepairProposalTaxonomy.CompensationActionType.REBALANCE_PROTECT_RATIO));
        if (!defaultList(action.getUnitIds()).isEmpty()) {
            suggestion.setRemoveUnitIds(resolveUnitIdsFromVolunteerIds(removeVolunteerIds, candidates));
        }
        suggestion.setRemoveVolunteerIds(removeVolunteerIds);
        if (!defaultList(action.getUnitIds()).isEmpty()) {
            suggestion.setCandidateUnitIds(defaultList(action.getUnitIds()));
        }
        suggestion.setCandidateVolunteerIds(defaultList(action.getVolunteerIds()));
        int pairCount = Math.min(removeVolunteerIds.size(), defaultList(action.getVolunteerIds()).size());
        for (int i = 0; i < pairCount; i++) {
            ReplacementPairDTO pair = new ReplacementPairDTO();
            pair.setFromUnitId(i < suggestion.getRemoveUnitIds().size() ? suggestion.getRemoveUnitIds().get(i) : null);
            pair.setFromVolunteerId(removeVolunteerIds.get(i));
            pair.setToUnitId(i < suggestion.getCandidateUnitIds().size() ? suggestion.getCandidateUnitIds().get(i) : null);
            pair.setToVolunteerId(action.getVolunteerIds().get(i));
            pair.setReasonCodes(Lists.newArrayList(check.getCode(),
                    RepairProposalTaxonomy.CompensationActionType.REBALANCE_PROTECT_RATIO));
            suggestion.getReplacementPairs().add(pair);
        }
        suggestion.setPreferredApplyMode("replace_and_reorder");
        return suggestion;
    }

    private String resolveProbabilityGapReplacementSource(List<String> affectedVolunteerIds,
                                                          List<CandidateItemDTO> candidates) {
        if (affectedVolunteerIds == null || affectedVolunteerIds.isEmpty()) {
            return null;
        }
        double min = Double.MAX_VALUE;
        double max = Double.MIN_VALUE;
        List<CandidateItemDTO> affectedCandidates = Lists.newArrayList();
        for (String volunteerId : affectedVolunteerIds) {
            CandidateItemDTO candidate = findCandidate(candidates, volunteerId);
            if (candidate == null || candidate.getAdmissionRatio() == null) {
                continue;
            }
            affectedCandidates.add(candidate);
            min = Math.min(min, candidate.getAdmissionRatio());
            max = Math.max(max, candidate.getAdmissionRatio());
        }
        if (affectedCandidates.isEmpty()) {
            return null;
        }
        double midpoint = (min + max) / 2D;
        return affectedCandidates.stream()
                .sorted(Comparator
                        .comparingDouble((CandidateItemDTO item) -> -Math.abs(item.getAdmissionRatio() - midpoint))
                        .thenComparing((CandidateItemDTO item) -> item.getAdmissionRatio(), Comparator.nullsLast(Double::compareTo)))
                .map(CandidateItemDTO::getVolunteerId)
                .findFirst()
                .orElse(null);
    }

    private boolean sameTierValue(String left, String right) {
        return Strings.nullToEmpty(left).equals(Strings.nullToEmpty(right));
    }

    private List<String> resolveOrderedUnitIds(List<String> orderedVolunteerIds,
                                               OrderedPlanStateDTO analysisOrderedState,
                                               List<CandidateItemDTO> candidates) {
        if (analysisOrderedState != null && !defaultOrderedUnits(analysisOrderedState.getUnits()).isEmpty()) {
            return defaultOrderedUnits(analysisOrderedState.getUnits()).stream()
                    .map(OrderedUnitDTO::getUnitId)
                    .filter(id -> !Strings.isNullOrEmpty(id))
                    .collect(Collectors.toList());
        }
        return resolveUnitIdsFromVolunteerIds(orderedVolunteerIds, candidates);
    }

    private List<String> resolveUnitIdsFromVolunteerIds(List<String> volunteerIds,
                                                        List<CandidateItemDTO> candidates) {
        return defaultList(volunteerIds).stream()
                .map(volunteerId -> resolveUnitId(volunteerId, candidates))
                .filter(id -> !Strings.isNullOrEmpty(id))
                .distinct()
                .collect(Collectors.toList());
    }

    private String resolveUnitId(String volunteerId, List<CandidateItemDTO> candidates) {
        CandidateItemDTO candidate = findCandidate(candidates, volunteerId);
        if (candidate != null) {
            return resolveInitialRecommendationUnitId(candidate);
        }
        return null;
    }

    private List<PlanAdjustmentCandidateSummaryDTO> buildPlanAdjustmentCandidateSummaries(List<String> volunteerIds,
                                                                                          List<CandidateItemDTO> candidates) {
        List<PlanAdjustmentCandidateSummaryDTO> summaries = Lists.newArrayList();
        for (String volunteerId : defaultList(volunteerIds)) {
            CandidateItemDTO candidate = findCandidate(candidates, volunteerId);
            if (candidate == null) {
                continue;
            }
            PlanAdjustmentCandidateSummaryDTO summary = new PlanAdjustmentCandidateSummaryDTO();
            summary.setUnitId(resolveInitialRecommendationUnitId(candidate));
            summary.setVolunteerId(candidate.getVolunteerId());
            summary.setSchoolName(candidate.getSchoolName());
            summary.setMajorName(candidate.getMajorName());
            summary.setTier(candidate.getTier());
            summary.setAdmissionRatio(candidate.getAdmissionRatio());
            summary.setFinalScore(candidate.getFinalScore());
            summaries.add(summary);
        }
        return summaries;
    }

    private String normalizePlanAdjustmentSeverity(String level) {
        if ("warn".equalsIgnoreCase(level)) {
            return "warning";
        }
        if ("risk".equalsIgnoreCase(level)) {
            return "risk";
        }
        return "info";
    }

    private PlanningStateDTO loadPlanningState(Long chatSessionId) {
        return loadPlanningState(chatSessionId, true);
    }

    /**
     * 只读加载规划状态：**不做 legacy 懒导入、不落盘**。
     *
     * <p>只读调用方（候选预览）用这条而不是 {@link #loadPlanningState}——后者会为
     * legacy 会话懒导入并 savePlanningState（版本会动），那正是只读纵切不能发生的事。</p>
     */
    PlanningStateDTO loadPlanningStateReadOnly(Long chatSessionId) {
        ChatSessionExtraData extraData = chatSessionExtraDataSharedService.getBySessionIdAndDataKey(
                chatSessionId, ChatSessionExtraDataConstants.PLANNING_STATE_KEY);
        PlanningStateDTO state = extraData == null || Strings.isNullOrEmpty(extraData.getDataValue())
                ? new PlanningStateDTO()
                : JSONObject.parseObject(extraData.getDataValue(), PlanningStateDTO.class);
        normalizePlanningStateDefaults(chatSessionId, state);
        // 写路径 CAS 的基线：手里这份就是"读到的那串"（只读入口没有懒导入/补写，不刷新）
        state.setBaselineDataValue(extraData == null ? null : extraData.getDataValue());
        return state;
    }

    private PlanningStateDTO loadPlanningState(Long chatSessionId, boolean allowLegacyImport) {
        ChatSessionExtraData extraData = chatSessionExtraDataSharedService.getBySessionIdAndDataKey(
                chatSessionId, ChatSessionExtraDataConstants.PLANNING_STATE_KEY);
        ChatSessionExtraData rowRef = extraData;
        String baselineDataValue = extraData == null ? null : extraData.getDataValue();
        PlanningStateDTO state;
        if (extraData == null || extraData.getDataValue() == null) {
            state = allowLegacyImport ? tryImportLegacyPlanningState(chatSessionId) : null;
            if (state != null) {
                // 读路径懒导入**只补缺**：并发写（页面自举 initial-plan/generate）先落盘时，
                // 以库里那份为准继续，读接口不再把别人的新状态盖回去（评审 §六）。
                PlanningStateImportPersist persistResult = persistImportedPlanningState(chatSessionId, extraData, state);
                rowRef = persistResult.row;
                // 懒导入之后基线以"实际落在库里的那串"为准（自己赢=导入串；并发赢家=赢家那份；
                // 行没了=null → 按首建处理）——否则写者一上手拿到的基线就是过期的。
                baselineDataValue = persistResult.row == null ? null : persistResult.row.getDataValue();
                if (persistResult.winnerState != null) {
                    state = persistResult.winnerState;
                }
            } else {
                state = new PlanningStateDTO();
                state.setSessionId(chatSessionId);
            }
        } else {
            state = JSONObject.parseObject(extraData.getDataValue(), PlanningStateDTO.class);
        }
        state.setBaselineDataValue(baselineDataValue);
        normalizePlanningStateDefaults(chatSessionId, state);
        backfillLegacyProfileState(chatSessionId, state);
        boolean planEditCacheNoticeAdded = appendPlanEditCacheNotice(chatSessionId, state);
        boolean dataFreshnessBackfilled = backfillDataFreshnessState(chatSessionId, state);
        backfillLegacySummaryFields(state);
        if (planEditCacheNoticeAdded || dataFreshnessBackfilled) {
            // 读路径的补写同样做"读到的那份还在才写"：输了就不落盘（补写幂等，下次读会重放）。
            // 赢了则由 savePlanningStateIfUnchanged 把基线刷成"实际写进库里的那串"。
            savePlanningStateIfUnchanged(chatSessionId, rowRef, state, "read_backfill");
        }
        return state;
    }

    /**
     * 写路径 CAS 的重读：把**最新**那份规划态拷回调用方手里的对象（对象身份不变，
     * baselineDataValue 随之刷新为最新行值），供各站点"重读重放 / 重读合并"用。
     *
     * <p>用 {@link BeanUtils#copyProperties} 而不是换引用：调用方方法体后续还引用着这个
     * state（返回值、version、staleFlags 都从它取），换引用会写出"旧对象"。</p>
     */
    private PlanningStateDTO reloadPlanningState(Long chatSessionId, PlanningStateDTO state) {
        PlanningStateDTO latest = loadPlanningState(chatSessionId);
        BeanUtils.copyProperties(latest, state);
        return state;
    }

    /**
     * legacy 懒导入落盘：**只补缺，不覆盖**。
     *
     * <p>老会话的首次读（workspace-state / state / filter-options，甚至同一秒 2-3 条）都会懒导入，
     * 而页面自举 {@code initial-plan/generate} 也在写同一行——原来的"无条件整文档覆盖"会把自举
     * 出来的草案/排序打回"只有候选池"（phase 卡 {@code candidate_generated}），
     * 见 {@code docs/superpowers/reviews/2026-10-06-test-www-chain-recovery.md} §六。</p>
     *
     * <p>这里是：行不存在才 INSERT；撞唯一键说明别人先落盘了——内容一致（同一次导入）就沿用，
     * 内容不同就以库里那份为准返回给调用方。任何情况下都不再把本次内存态 updateById 覆盖上去。</p>
     */
    private PlanningStateImportPersist persistImportedPlanningState(Long chatSessionId,
                                                                    ChatSessionExtraData existingRow,
                                                                    PlanningStateDTO imported) {
        String dataValue = JSONObject.toJSONString(imported);
        if (existingRow != null && existingRow.getId() != null) {
            // 行在但 data_value 是空的（历史空壳行）：不能 INSERT（唯一键会撞自己），走 CAS 补值。
            if (chatSessionExtraDataSharedService.updateDataValueIfUnchanged(existingRow, existingRow.getDataValue(), dataValue)) {
                return new PlanningStateImportPersist(copyRow(existingRow, dataValue), null);
            }
            return new PlanningStateImportPersist(existingRow, null);
        }
        ChatSessionExtraData entity = new ChatSessionExtraData();
        entity.setChatSessionId(chatSessionId);
        entity.setDataKey(ChatSessionExtraDataConstants.PLANNING_STATE_KEY);
        entity.setDataType(DataType.JSON_OBJECT);
        entity.setDataVersion(0);
        entity.setDataValue(dataValue);
        try {
            chatSessionExtraDataSharedService.save(entity);
            return new PlanningStateImportPersist(entity, null);
        } catch (DuplicateKeyException duplicate) {
            // 唯一键 uk_chat_session_id_data_key_data_version 是并发防线：多个首次读各自导入时
            // 只有一个 INSERT 成功（2026-10-06 已修"读接口撞键回 500"）。这里再进一步：
            // 输的一方不再把导入结果覆盖上去（那是旧快照），以库里赢家为准。
            ChatSessionExtraData winner = chatSessionExtraDataSharedService.getBySessionIdAndDataKey(
                    chatSessionId, ChatSessionExtraDataConstants.PLANNING_STATE_KEY);
            if (winner == null) {
                log.warn("planningStateImportPersist skipped chatSessionId={} reason=row_vanished_after_duplicate",
                        chatSessionId);
                return new PlanningStateImportPersist(null, null);
            }
            if (winner.getDataValue() == null) {
                // 赢家是个空壳行（value 为空）：CAS 把本次导入补上去（期望值 null → isNull 条件）。
                if (chatSessionExtraDataSharedService.updateDataValueIfUnchanged(winner, null, dataValue)) {
                    return new PlanningStateImportPersist(copyRow(winner, dataValue), null);
                }
                return new PlanningStateImportPersist(winner, null);
            }
            if (dataValue.equals(winner.getDataValue())) {
                return new PlanningStateImportPersist(winner, null);
            }
            log.info("planningStateImportPersist skipped stale write chatSessionId={} reason=row_written_by_other",
                    chatSessionId);
            return new PlanningStateImportPersist(winner,
                    JSONObject.parseObject(winner.getDataValue(), PlanningStateDTO.class));
        }
    }

    private ChatSessionExtraData copyRow(ChatSessionExtraData source, String dataValue) {
        ChatSessionExtraData row = new ChatSessionExtraData();
        row.setId(source.getId());
        row.setChatSessionId(source.getChatSessionId());
        row.setDataKey(source.getDataKey());
        row.setDataVersion(source.getDataVersion());
        row.setDataValue(dataValue);
        return row;
    }

    /**
     * 读路径补写的 CAS 落盘：库里那行仍是我们读到的快照才整文档写回，否则放弃（不覆盖并发写）。
     */
    private boolean savePlanningStateIfUnchanged(Long chatSessionId,
                                                 ChatSessionExtraData rowRef,
                                                 PlanningStateDTO state,
                                                 String scene) {
        if (rowRef == null || rowRef.getId() == null) {
            log.warn("planningStateCasSave skipped chatSessionId={} scene={} reason=row_ref_missing",
                    chatSessionId, scene);
            return false;
        }
        String dataValue = JSONObject.toJSONString(state);
        boolean updated = chatSessionExtraDataSharedService.updateDataValueIfUnchanged(
                rowRef, rowRef.getDataValue(), dataValue);
        if (!updated) {
            log.info("planningStateCasSave skipped chatSessionId={} scene={} reason=row_changed_under_us",
                    chatSessionId, scene);
        } else {
            // 写成功了：手里这份的基线就是刚写进库里的那串（后续写路径 CAS 以它为期望值）
            state.setBaselineDataValue(dataValue);
        }
        return updated;
    }

    /** 懒导入落盘结果：row=库里那行（后续 CAS 的基准）；winnerState=并发赢家那份（null=自己写的为准）。 */
    private static class PlanningStateImportPersist {
        private final ChatSessionExtraData row;
        private final PlanningStateDTO winnerState;

        private PlanningStateImportPersist(ChatSessionExtraData row, PlanningStateDTO winnerState) {
            this.row = row;
            this.winnerState = winnerState;
        }
    }

    private void normalizePlanningStateDefaults(Long chatSessionId, PlanningStateDTO state) {
        if (state == null) {
            return;
        }
        state.setSessionId(chatSessionId);
        if (state.getProfileState() == null) {
            state.setProfileState(new ProfileStateDTO());
        }
        if (state.getStaleFlags() == null) {
            state.setStaleFlags(new StaleFlagsDTO());
        }
        if (state.getConstraintState() == null) {
            state.setConstraintState(new ConstraintStateDTO());
        }
        if (state.getConstraintState().getHardPlanningObjectives() == null) {
            state.getConstraintState().setHardPlanningObjectives(new HardPlanningObjectivesDTO());
        }
        if (state.getConstraintState().getHardPlanningObjectives().getCoverageRequirements() == null) {
            state.getConstraintState().getHardPlanningObjectives().setCoverageRequirements(Lists.newArrayList());
        }
        if (state.getConstraintState().getHardPlanningObjectives().getPriorityRules() == null) {
            state.getConstraintState().getHardPlanningObjectives().setPriorityRules(Lists.newArrayList());
        }
        if (state.getDataFreshnessState() == null) {
            state.setDataFreshnessState(new DataFreshnessStateDTO());
        }
        if (state.getCandidatePoolState() == null) {
            state.setCandidatePoolState(new CandidatePoolStateDTO());
        }
        if (state.getInitialRecommendationState() == null) {
            state.setInitialRecommendationState(new InitialRecommendationStateDTO());
        }
        if (state.getWorkingPlanState() == null) {
            state.setWorkingPlanState(new DraftPlanStateDTO());
        }
        if (state.getOrderedPlanState() == null) {
            state.setOrderedPlanState(new OrderedPlanStateDTO());
        }
        if (state.getPlanAdjustmentState() == null) {
            state.setPlanAdjustmentState(new PlanAdjustmentStateDTO());
        }
        if (state.getReviewState() == null) {
            state.setReviewState(new ReviewStateDTO());
        }
        if (state.getOperationLogs() == null) {
            state.setOperationLogs(Lists.newArrayList());
        }
    }

    private PlanningStateDTO tryImportLegacyPlanningState(Long chatSessionId) {
        LegacyPlanSource legacyPlanSource = loadLegacyPlanSource(chatSessionId);
        if (legacyPlanSource == null || legacyPlanSource.response == null) {
            log.info("legacyPlanImport skipped chatSessionId={} reason=no_legacy_plan", chatSessionId);
            return null;
        }
        try {
            PlanningStateDTO state = buildPlanningStateFromLegacyPlan(chatSessionId, legacyPlanSource);
            log.info("legacyPlanImport success chatSessionId={} source={} candidates={} preferred={} ordered={} tierCounts={}",
                    chatSessionId,
                    legacyPlanSource.source,
                    state.getCandidatePoolState().getItems().size(),
                    state.getDraftPlanState().getItems().size(),
                    state.getOrderedPlanState().getItems().size(),
                    state.getOrderedPlanState().getSummary().getTierCounts());
            return state;
        } catch (Exception ex) {
            log.warn("legacyPlanImport failed chatSessionId={} source={}", chatSessionId, legacyPlanSource.source, ex);
            return null;
        }
    }

    private LegacyPlanSource loadLegacyPlanSource(Long chatSessionId) {
        try {
            VolunteerRecommendListResponse response = volunteerBizService.loadFinalSubmitVolunteerData(chatSessionId);
            if (hasLegacyPlanItems(response)) {
                return new LegacyPlanSource(response, "submitted", true);
            }
            log.info("legacyPlanImport final plan empty chatSessionId={}", chatSessionId);
        } catch (Exception ex) {
            log.info("legacyPlanImport final plan unavailable chatSessionId={} reason={}", chatSessionId, ex.getMessage());
        }
        try {
            VolunteerRecommendListResponse response = volunteerBizService.loadCachedRecommendData(chatSessionId);
            if (hasLegacyPlanItems(response)) {
                return new LegacyPlanSource(response, "temp", false);
            }
            log.info("legacyPlanImport temp plan empty chatSessionId={}", chatSessionId);
        } catch (Exception ex) {
            log.info("legacyPlanImport temp plan unavailable chatSessionId={} reason={}", chatSessionId, ex.getMessage());
        }
        try {
            VolunteerRecommendListResponse response = volunteerBizService.loadOriginalVolunteerData(chatSessionId);
            if (hasLegacyPlanItems(response)) {
                return new LegacyPlanSource(response, "original", false);
            }
            log.info("legacyPlanImport original plan empty chatSessionId={}", chatSessionId);
        } catch (Exception ex) {
            log.info("legacyPlanImport original plan unavailable chatSessionId={} reason={}", chatSessionId, ex.getMessage());
        }
        return null;
    }

    private boolean hasLegacyPlanItems(VolunteerRecommendListResponse response) {
        return response != null
                && (!defaultLegacySchools(response.getSprints()).isEmpty()
                || !defaultLegacySchools(response.getSafes()).isEmpty()
                || !defaultLegacySchools(response.getProtects()).isEmpty());
    }

    private List<VolunteerRecommendListResponse.VolunteerSchool> defaultLegacySchools(
            List<VolunteerRecommendListResponse.VolunteerSchool> schools) {
        return schools == null ? Lists.newArrayList() : schools;
    }

    private PlanningStateDTO buildPlanningStateFromLegacyPlan(Long chatSessionId, LegacyPlanSource legacyPlanSource) {
        PlanningStateDTO state = new PlanningStateDTO();
        state.setSessionId(chatSessionId);
        VolunteerRecommendListResponse response = legacyPlanSource.response;
        hydrateProfileState(state.getProfileState(), response.getUserScoreDetail(), response.getUserFinalProfileData());
        CandidatePoolStateDTO candidatePoolState = buildLegacyCandidatePoolState(chatSessionId, response);
        state.setCandidatePoolState(candidatePoolState);
        refreshDataFreshnessSnapshot(chatSessionId, state, candidatePoolState);

        List<CandidateItemDTO> candidates = defaultCandidates(candidatePoolState.getItems());
        List<CandidateItemDTO> preferredCandidates = selectLegacyPreferredCandidates(candidates, candidatePoolState, legacyPlanSource);
        preferredCandidates = expandLegacyMajorGroupPreferredCandidates(preferredCandidates, candidates, candidatePoolState);
        DraftPlanStateDTO draftPlanState = buildLegacyDraftPlanState(preferredCandidates, candidatePoolState, legacyPlanSource.submitted);
        OrderedPlanStateDTO orderedPlanState = buildLegacyOrderedPlanState(draftPlanState, candidatePoolState, candidates, legacyPlanSource);

        state.setWorkingPlanState(draftPlanState);
        state.setOrderedPlanState(orderedPlanState);
        state.setCandidateViewState(buildDefaultCandidateViewState(state.getProfileState()));
        state.setPhase(preferredCandidates.isEmpty() ? "candidate_generated" : "ordered");
        state.getStaleFlags().setCandidatePool(false);
        state.getStaleFlags().setRecommendationOverlay(false);
        state.getStaleFlags().setInitialRecommendation(false);
        state.getStaleFlags().setOrderedPlan(false);
        ReviewInvalidationPolicy.markPlanStructureStale(state);
        appendLegacyImportLog(state, legacyPlanSource, preferredCandidates);
        return state;
    }

    private CandidatePoolStateDTO buildLegacyCandidatePoolState(Long chatSessionId, VolunteerRecommendListResponse response) {
        CandidatePoolStateDTO candidatePoolState = new CandidatePoolStateDTO();
        candidatePoolState.setGeneratedAt(OffsetDateTime.now().toString());
        candidatePoolState.setSourceVersion(0);
        candidatePoolState.setRequiredCount(resolveRequiredPlanCount(chatSessionId, response));
        fillRequiredTierCounts(chatSessionId, candidatePoolState, response);
        candidatePoolState.setRequiredUnitCount(response.getBaseData() != null && response.getBaseData().getVolunteerCount() != null
                ? response.getBaseData().getVolunteerCount().getSchoolCount() : null);
        candidatePoolState.setRequiredMajorCount(response.getBaseData() != null && response.getBaseData().getVolunteerCount() != null
                ? response.getBaseData().getVolunteerCount().getMajorCount() : null);
        candidatePoolState.setVolunteerModel(response.getBaseData() != null && response.getBaseData().getVolunteerModel() != null
                ? response.getBaseData().getVolunteerModel().getCode() : null);
        candidatePoolState.setUserScore(response.getUserScoreDetail() != null ? response.getUserScoreDetail().getTotalScore() : null);
        candidatePoolState.setBatchScore(response.getUserScoreDetail() != null && response.getUserScoreDetail().getBatch() != null
                && response.getUserScoreDetail().getBatch().getScore() != null
                ? Math.round(response.getUserScoreDetail().getBatch().getScore()) : null);
        candidatePoolState.setSourceProvinceName(response.getUserScoreDetail() != null && response.getUserScoreDetail().getProvince() != null
                ? response.getUserScoreDetail().getProvince().getName() : null);
        List<CandidateItemDTO> items = Lists.newArrayList();
        items.addAll(flattenCandidates(response.getSprints(), "冲"));
        items.addAll(flattenCandidates(response.getSafes(), "稳"));
        items.addAll(flattenCandidates(response.getProtects(), "保"));
        List<CandidateItemDTO> normalizedItems = normalizeCandidateIdentities(candidatePoolState, items);
        candidatePoolState.setItems(normalizedItems);
        recalculateCandidatePoolSummary(candidatePoolState);
        populateCandidatePoolSourceSummary(candidatePoolState, items, normalizedItems);
        normalizeRequiredTierCountsByAvailableCapacity(candidatePoolState);
        return candidatePoolState;
    }

    private List<CandidateItemDTO> selectLegacyPreferredCandidates(List<CandidateItemDTO> candidates,
                                                                   CandidatePoolStateDTO candidatePoolState,
                                                                   LegacyPlanSource legacyPlanSource) {
        List<CandidateItemDTO> preferred = defaultCandidates(candidates).stream()
                .filter(item -> Boolean.TRUE.equals(item.getPreferred()))
                .sorted(buildLegacyPreferredComparator())
                .collect(Collectors.toList());
        if (!preferred.isEmpty()) {
            return deduplicateLegacyMajorGroupPreferredUnits(preferred, candidatePoolState);
        }
        if (legacyPlanSource != null && "original".equals(legacyPlanSource.source)) {
            return Lists.newArrayList();
        }
        Map<String, Integer> requiredTierCounts = candidatePoolState == null ? null : candidatePoolState.getRequiredTierCounts();
        if (requiredTierCounts == null || requiredTierCounts.isEmpty()) {
            return Lists.newArrayList();
        }
        List<CandidateItemDTO> selected = Lists.newArrayList();
        Set<String> selectedIds = new LinkedHashSet<String>();
        for (String tier : Lists.newArrayList("冲", "稳", "保")) {
            Integer required = requiredTierCounts.get(tier);
            if (required == null || required <= 0) {
                continue;
            }
            List<CandidateItemDTO> tierCandidates = defaultCandidates(candidates).stream()
                    .filter(item -> tier.equals(item.getTier()))
                    .sorted(buildLegacyPreferredComparator())
                    .collect(Collectors.toList());
            for (CandidateItemDTO candidate : tierCandidates) {
                if ((int) selected.stream().filter(item -> tier.equals(item.getTier())).count() >= required) {
                    break;
                }
                String selectedKey = isMajorGroupMode(candidatePoolState)
                        ? resolveInitialRecommendationUnitId(candidate)
                        : candidate.getVolunteerId();
                if (selectedIds.add(selectedKey)) {
                    selected.add(candidate);
                }
            }
        }
        return selected;
    }

    private List<CandidateItemDTO> deduplicateLegacyMajorGroupPreferredUnits(List<CandidateItemDTO> preferred,
                                                                                CandidatePoolStateDTO candidatePoolState) {
        if (!isMajorGroupMode(candidatePoolState)) {
            return preferred;
        }
        Map<String, CandidateItemDTO> unitMap = new LinkedHashMap<String, CandidateItemDTO>();
        for (CandidateItemDTO candidate : defaultCandidates(preferred)) {
            String unitId = resolveInitialRecommendationUnitId(candidate);
            if (!Strings.isNullOrEmpty(unitId) && !unitMap.containsKey(unitId)) {
                unitMap.put(unitId, candidate);
            }
        }
        return Lists.newArrayList(unitMap.values());
    }

    private List<CandidateItemDTO> expandLegacyMajorGroupPreferredCandidates(List<CandidateItemDTO> preferredCandidates,
                                                                             List<CandidateItemDTO> candidates,
                                                                             CandidatePoolStateDTO candidatePoolState) {
        if (!isMajorGroupMode(candidatePoolState) || preferredCandidates == null || preferredCandidates.isEmpty()) {
            return preferredCandidates;
        }
        Map<String, List<CandidateItemDTO>> candidateUnitMap = groupCandidatesByUnit(candidates);
        List<CandidateItemDTO> expanded = Lists.newArrayList();
        Set<String> addedVolunteerIds = new LinkedHashSet<String>();
        for (CandidateItemDTO preferred : defaultCandidates(preferredCandidates)) {
            String unitId = resolveInitialRecommendationUnitId(preferred);
            List<CandidateItemDTO> unitCandidates = candidateUnitMap.get(unitId);
            if (unitCandidates == null || unitCandidates.isEmpty()) {
                if (!Strings.isNullOrEmpty(preferred.getVolunteerId()) && addedVolunteerIds.add(preferred.getVolunteerId())) {
                    expanded.add(preferred);
                }
                continue;
            }
            for (CandidateItemDTO candidate : unitCandidates.stream()
                    .sorted(buildMajorGroupInnerCandidateComparator())
                    .collect(Collectors.toList())) {
                if (!Strings.isNullOrEmpty(candidate.getVolunteerId()) && addedVolunteerIds.add(candidate.getVolunteerId())) {
                    expanded.add(candidate);
                }
            }
        }
        return expanded;
    }

    private Comparator<CandidateItemDTO> buildLegacyPreferredComparator() {
        return Comparator
                .comparingInt((CandidateItemDTO item) -> tierOrder(item.getTier()))
                .thenComparing((CandidateItemDTO item) -> rankInTierOf(item), Comparator.nullsLast(Integer::compareTo))
                .thenComparing((CandidateItemDTO item) -> finalScoreOf(item), Comparator.nullsLast(Comparator.reverseOrder()))
                .thenComparing(CandidateItemDTO::getVolunteerId, Comparator.nullsLast(String::compareTo));
    }

    private DraftPlanStateDTO buildLegacyDraftPlanState(List<CandidateItemDTO> preferredCandidates,
                                                        CandidatePoolStateDTO candidatePoolState,
                                                        boolean submitted) {
        DraftPlanStateDTO draftPlanState = new DraftPlanStateDTO();
        for (CandidateItemDTO candidate : defaultCandidates(preferredCandidates)) {
            DraftItemDTO item = WorkingPlanMutationSupport.buildWorkingPlanItem(candidate, "legacy_preferred", submitted);
            draftPlanState.getItems().add(item);
        }
        syncWorkingPlanUnitsWithItems(draftPlanState, preferredCandidates, candidatePoolState);
        recalculateWorkingPlanSummary(draftPlanState, candidatePoolState);
        return draftPlanState;
    }

    private OrderedPlanStateDTO buildLegacyOrderedPlanState(DraftPlanStateDTO draftPlanState,
                                                            CandidatePoolStateDTO candidatePoolState,
                                                            List<CandidateItemDTO> candidates,
                                                            LegacyPlanSource legacyPlanSource) {
        OrderedPlanStateDTO orderedPlanState = new OrderedPlanStateDTO();
        List<OrderedItemDTO> orderedItems = buildOrderedItemsFromWorkingPlan(
                draftPlanState,
                candidatePoolState,
                candidates,
                new LinkedHashMap<String, OrderedItemDTO>(),
                false);
        for (OrderedItemDTO item : defaultOrderedItems(orderedItems)) {
            item.setLocked(legacyPlanSource.submitted);
            item.setPinned(legacyPlanSource.submitted);
            item.setPinnedPosition(legacyPlanSource.submitted ? item.getPosition() : null);
            item.setOrderedBy("legacy");
            item.setOrderReason(legacyPlanSource.submitted ? "legacy_submitted_order" : "legacy_import_order");
            item.setSource("legacy_preferred");
        }
        orderedPlanState.setItems(orderedItems);
        orderedPlanState.setUnits(buildOrderedUnitsFromOrderedItems(orderedItems, draftPlanState, candidates));
        orderedPlanState.setGenerationMode(legacyPlanSource.submitted ? "legacy_submitted" : "legacy_import");
        recalculateOrderedSummary(orderedPlanState, candidatePoolState);
        return orderedPlanState;
    }

    private void appendLegacyImportLog(PlanningStateDTO state,
                                       LegacyPlanSource legacyPlanSource,
                                       List<CandidateItemDTO> preferredCandidates) {
        OperationLogDTO logItem = new OperationLogDTO();
        logItem.setType("legacy_plan_import");
        logItem.setOperator("system");
        logItem.setDetail("从老版本" + (legacyPlanSource.submitted ? "已提交方案" : "临时方案") + "导入 V2 工作台");
        logItem.setCreatedAt(OffsetDateTime.now().toString());
        logItem.setVolunteerIds(defaultCandidates(preferredCandidates).stream()
                .map(CandidateItemDTO::getVolunteerId)
                .filter(Objects::nonNull)
                .collect(Collectors.toList()));
        state.getOperationLogs().add(logItem);
    }

    private boolean appendPlanEditCacheNotice(Long chatSessionId, PlanningStateDTO state) {
        if (state == null || hasOperationLog(state, "legacy_plan_edit_cache_pending")) {
            return false;
        }
        ChatSessionExtraData cacheData = chatSessionExtraDataSharedService
                .getBySessionIdAndDataKey(chatSessionId, ChatSessionExtraDataConstants.PLAN_EDIT_CACHE_KEY);
        if (cacheData == null || Strings.isNullOrEmpty(cacheData.getDataValue()) || isBlankJsonValue(cacheData.getDataValue())) {
            return false;
        }
        OperationLogDTO logItem = new OperationLogDTO();
        logItem.setType("legacy_plan_edit_cache_pending");
        logItem.setOperator("system");
        logItem.setCreatedAt(OffsetDateTime.now().toString());
        logItem.setDetail("检测到老版本对话中存在待确认的方案调整意向，未自动应用到当前方案");
        state.getOperationLogs().add(logItem);
        return true;
    }

    private boolean hasOperationLog(PlanningStateDTO state, String type) {
        return state.getOperationLogs() != null
                && state.getOperationLogs().stream().anyMatch(logItem -> type.equals(logItem.getType()));
    }

    private boolean isBlankJsonValue(String value) {
        String normalized = value == null ? "" : value.trim();
        return normalized.isEmpty()
                || "{}".equals(normalized)
                || "[]".equals(normalized)
                || "null".equalsIgnoreCase(normalized);
    }

    private static class LegacyPlanSource {
        private final VolunteerRecommendListResponse response;
        private final String source;
        private final boolean submitted;

        private LegacyPlanSource(VolunteerRecommendListResponse response, String source, boolean submitted) {
            this.response = response;
            this.source = source;
            this.submitted = submitted;
        }
    }


    public DataFreshnessCheckRes checkDataFreshness(Long chatSessionId, DataFreshnessCheckReq req) {
        return checkDataFreshness(null, chatSessionId, req);
    }

    public DataFreshnessCheckRes checkDataFreshness(Long tenantId, Long chatSessionId, DataFreshnessCheckReq req) {
        PlanningDataFreshnessScheduleEntity schedule = touchDataFreshnessSchedule(tenantId, chatSessionId, null, true, false);
        PlanningStateDTO state = loadPlanningStateReadOnly(chatSessionId);
        if (isEmptyPlanningWorkspaceState(state)) {
            DataFreshnessCheckRes res = new DataFreshnessCheckRes();
            res.setDataFreshnessState(buildScheduleOnlyDataFreshnessState(schedule));
            return res;
        }
        String existingPrepareType = normalizeText(state.getDataFreshnessState() == null
                ? null : state.getDataFreshnessState().getPrepareType());
        boolean changed = false;
        if (backfillDataFreshnessState(chatSessionId, state)) {
            changed = true;
        }
        DataFreshnessStateDTO freshness = state.getDataFreshnessState();
        if (freshness == null) {
            freshness = new DataFreshnessStateDTO();
            state.setDataFreshnessState(freshness);
            changed = true;
        }
        if (Strings.isNullOrEmpty(freshness.getPrepareType()) && !Strings.isNullOrEmpty(existingPrepareType)) {
            freshness.setPrepareType(existingPrepareType);
        }
        DataFreshnessCheckReq safeReq = req == null ? new DataFreshnessCheckReq() : req;
        String prepareType = resolveDataFreshnessPrepareType(schedule, freshness);
        if (!Strings.isNullOrEmpty(prepareType) && !DataFreshnessSchedulePolicy.isSupportedPrepareType(prepareType)) {
            DataFreshnessCheckRes res = markUnsupportedDataFreshnessCurrent(tenantId, chatSessionId, state, freshness, safeReq, prepareType);
            return res;
        }
        CandidatePoolStateDTO latestCandidatePool = null;
        if (Boolean.TRUE.equals(safeReq.getFetchLatest())) {
            try {
                latestCandidatePool = populateLatestDataFreshnessRequest(tenantId, chatSessionId, state, safeReq);
            } catch (Exception ex) {
                return handleLatestDataFreshnessFetchFailure(tenantId, chatSessionId, state, ex);
            }
        }

        String now = OffsetDateTime.now().toString();
        freshness.setLastCheckedAt(now);
        String incomingHash = normalizeText(safeReq.getDataHash());
        String currentHash = normalizeCurrentCandidateDataHash(state, freshness);
        boolean hasExternalSnapshot = !Strings.isNullOrEmpty(incomingHash);
        boolean hashChanged = hasExternalSnapshot && !incomingHash.equals(currentHash);
        boolean applyLatestSnapshotToWorkspace = shouldApplyLatestDataFreshnessSnapshotToWorkspace(
                chatSessionId, state, latestCandidatePool, safeReq);
        // 合并重放要用到的"本次做过哪些派生动作"（MERGE_LATEST 只重放这些，不重放跨域的工作区同步）
        boolean clearFreshnessStale = false;
        boolean markFreshnessStale = false;
        boolean logFreshnessChange = false;
        boolean freshnessVersionBumped = false;
        if (!hasExternalSnapshot) {
            if (!"changed".equals(freshness.getStatusCode())) {
                markDataFreshnessCurrent(freshness, currentHash, safeReq);
                freshness.setSummary("未提供最新招生计划快照，已保留当前本地数据状态。");
            }
            changed = true;
        } else if (!hashChanged) {
            markDataFreshnessCurrent(freshness, incomingHash, safeReq);
            if (applyLatestSnapshotToWorkspace
                    && syncLatestDataFreshnessSnapshotToWorkspace(chatSessionId, state, freshness, latestCandidatePool, safeReq, incomingHash)) {
                state.setVersion((state.getVersion() == null ? 0 : state.getVersion()) + 1);
                freshnessVersionBumped = true;
            }
            clearDataFreshnessStaleFlags(state);
            clearFreshnessStale = true;
            changed = true;
        } else if (isSamePendingDataFreshnessChange(freshness, safeReq, incomingHash)) {
            preservePendingDataFreshnessCheckResult(freshness, safeReq, now);
            if (applyLatestSnapshotToWorkspace
                    && syncLatestDataFreshnessSnapshotToWorkspace(chatSessionId, state, freshness, latestCandidatePool, safeReq, incomingHash)) {
                state.setVersion((state.getVersion() == null ? 0 : state.getVersion()) + 1);
                freshnessVersionBumped = true;
            }
            changed = true;
        } else {
            applyDataFreshnessChange(state, freshness, safeReq, incomingHash, now);
            if (Boolean.TRUE.equals(safeReq.getMarkStale())) {
                markDataFreshnessStale(state, freshness);
                markFreshnessStale = true;
            }
            if (applyLatestSnapshotToWorkspace) {
                syncLatestDataFreshnessSnapshotToWorkspace(chatSessionId, state, freshness, latestCandidatePool, safeReq, incomingHash);
            }
            appendDataFreshnessOperationLog(state, freshness);
            logFreshnessChange = true;
            state.setVersion((state.getVersion() == null ? 0 : state.getVersion()) + 1);
            freshnessVersionBumped = true;
            changed = true;
        }
        if (changed) {
            boolean saved = savePlanningState(chatSessionId, state, "data_freshness_check");
            for (int attempt = 1; !saved && attempt < WRITE_CAS_ATTEMPTS; attempt++) {
                // MERGE_LATEST：重读最新后**只把数据新鲜度这一域**合上去（freshness 快照 + 由它派生的
                // stale 清理/标记、操作日志、版本 +1）；工作区快照同步依赖本次上游拉数、且属跨域，
                // 不重放（不动并发写者的工作区），下次检查会基于最新态重算。
                reloadPlanningState(chatSessionId, state);
                state.setDataFreshnessState(freshness);
                if (clearFreshnessStale) {
                    clearDataFreshnessStaleFlags(state);
                }
                if (markFreshnessStale) {
                    markDataFreshnessStale(state, freshness);
                }
                if (logFreshnessChange) {
                    appendDataFreshnessOperationLog(state, freshness);
                }
                if (freshnessVersionBumped) {
                    state.setVersion((state.getVersion() == null ? 0 : state.getVersion()) + 1);
                }
                saved = savePlanningState(chatSessionId, state, "data_freshness_check_merge");
            }
            if (!saved) {
                logWriteCasSkipped(chatSessionId, "data_freshness_check", "row_written_by_other");
            }
        }
        state.setSessionId(chatSessionId);
        touchDataFreshnessSchedule(tenantId, chatSessionId, state, true, true);
        DataFreshnessCheckRes res = new DataFreshnessCheckRes();
        res.setVersion(state.getVersion());
        res.setStaleFlags(state.getStaleFlags());
        res.setDataFreshnessState(state.getDataFreshnessState());
        res.setWorkspaceState(buildPlanningWorkspaceStateRes(tenantId, state));
        return res;
    }

    private DataFreshnessCheckRes handleLatestDataFreshnessFetchFailure(Long tenantId,
                                                                         Long chatSessionId,
                                                                         PlanningStateDTO state,
                                                                         Exception ex) {
        String error = ex == null ? "检查最新招生计划失败" : ex.getMessage();
        log.warn("dataFreshness latest fetch failed tenantId={} chatSessionId={}", tenantId, chatSessionId, ex);
        planningDataFreshnessScheduleSharedService.markFailure(chatSessionId, "interactive", error, new Date());
        DataFreshnessCheckRes res = new DataFreshnessCheckRes();
        res.setVersion(state == null ? null : state.getVersion());
        res.setStaleFlags(state == null ? null : state.getStaleFlags());
        res.setDataFreshnessState(mergeScheduleDataFreshnessState(tenantId, state));
        res.setWorkspaceState(buildPlanningWorkspaceStateRes(tenantId, state));
        return res;
    }

    private String resolveDataFreshnessPrepareType(PlanningDataFreshnessScheduleEntity schedule,
                                                    DataFreshnessStateDTO freshness) {
        String schedulePrepareType = normalizeText(schedule == null ? null : schedule.getPrepareType());
        if (!Strings.isNullOrEmpty(schedulePrepareType)) {
            return schedulePrepareType;
        }
        return normalizeText(freshness == null ? null : freshness.getPrepareType());
    }

    private boolean isSamePendingDataFreshnessChange(DataFreshnessStateDTO freshness,
                                                       DataFreshnessCheckReq req,
                                                       String incomingHash) {
        if (freshness == null || !"changed".equals(freshness.getStatusCode())) {
            return false;
        }
        String latestDataHash = normalizeText(freshness.getLatestDataHash());
        if (!Strings.isNullOrEmpty(incomingHash) && incomingHash.equals(latestDataHash)) {
            return true;
        }
        String incomingSourceHash = normalizeText(req == null ? null : req.getSourceDataHash());
        String latestSourceHash = normalizeText(freshness.getLatestSourceDataHash());
        return !Strings.isNullOrEmpty(incomingSourceHash) && incomingSourceHash.equals(latestSourceHash);
    }

    private void preservePendingDataFreshnessCheckResult(DataFreshnessStateDTO freshness,
                                                         DataFreshnessCheckReq req,
                                                         String checkedAt) {
        if (freshness == null) {
            return;
        }
        freshness.setLastCheckedAt(checkedAt);
        String incomingSourceHash = normalizeText(req == null ? null : req.getSourceDataHash());
        if (!Strings.isNullOrEmpty(incomingSourceHash)) {
            freshness.setLatestSourceDataHash(incomingSourceHash);
        }
        String incomingDataHash = normalizeText(req == null ? null : req.getDataHash());
        if (!Strings.isNullOrEmpty(incomingDataHash)) {
            freshness.setLatestDataHash(incomingDataHash);
        }
        if (Strings.isNullOrEmpty(freshness.getSummary()) && req != null && !Strings.isNullOrEmpty(req.getSummary())) {
            freshness.setSummary(req.getSummary());
        }
        if (Strings.isNullOrEmpty(freshness.getDetail()) && req != null && !Strings.isNullOrEmpty(req.getDetail())) {
            freshness.setDetail(req.getDetail());
        }
    }

    private DataFreshnessCheckRes markUnsupportedDataFreshnessCurrent(Long tenantId,
                                                                       Long chatSessionId,
                                                                       PlanningStateDTO state,
                                                                       DataFreshnessStateDTO freshness,
                                                                       DataFreshnessCheckReq req,
                                                                       String prepareType) {
        // A 类（纯内存、重放幂等）：CAS 输 -> 重读最新 -> 重放同一变换 -> 再 CAS ≤3 次；
        // 派生状态回报，最终输也不吵用户（记日志，下次检查重算），但绝不覆盖并发写。
        boolean saved = false;
        for (int attempt = 0; attempt < WRITE_CAS_ATTEMPTS && !saved; attempt++) {
            DataFreshnessStateDTO target = freshness;
            if (attempt > 0) {
                reloadPlanningState(chatSessionId, state);
                target = state.getDataFreshnessState();
                if (target == null) {
                    target = new DataFreshnessStateDTO();
                    state.setDataFreshnessState(target);
                }
            }
            applyUnsupportedFreshnessCurrent(state, target, req, prepareType);
            saved = savePlanningState(chatSessionId, state, "data_freshness_unsupported");
        }
        if (!saved) {
            logWriteCasSkipped(chatSessionId, "data_freshness_unsupported", "row_written_by_other");
        }
        state.setSessionId(chatSessionId);
        touchDataFreshnessSchedule(tenantId, chatSessionId, state, true, true);
        DataFreshnessCheckRes res = new DataFreshnessCheckRes();
        res.setVersion(state.getVersion());
        res.setStaleFlags(state.getStaleFlags());
        res.setDataFreshnessState(state.getDataFreshnessState());
        res.setWorkspaceState(buildPlanningWorkspaceStateRes(tenantId, state));
        return res;
    }

    /** "当前会话不参与自动同步"的新鲜度变换（纯内存、重放幂等）。 */
    private void applyUnsupportedFreshnessCurrent(PlanningStateDTO state,
                                                  DataFreshnessStateDTO freshness,
                                                  DataFreshnessCheckReq req,
                                                  String prepareType) {
        String now = OffsetDateTime.now().toString();
        String currentHash = normalizeCurrentCandidateDataHash(state, freshness);
        markDataFreshnessCurrent(freshness, currentHash, req);
        freshness.setLastCheckedAt(now);
        if (!Strings.isNullOrEmpty(prepareType)) {
            freshness.setPrepareType(prepareType);
        }
        freshness.setSummary("PREDICT".equalsIgnoreCase(normalizeText(prepareType))
                ? "模拟填报使用2025年的志愿数据，不参与招生计划自动同步。"
                : "当前会话暂不参与招生计划自动同步。");
        clearDataFreshnessStaleFlags(state);
    }

    private CandidatePoolStateDTO populateLatestDataFreshnessRequest(Long tenantId,
                                                                     Long chatSessionId,
                                                                     PlanningStateDTO state,
                                                                     DataFreshnessCheckReq req) {
        if (tenantId == null) {
            throw new BusinessException(110, "检查最新招生计划需要租户信息");
        }
        VolunteerSourceDataSnapshot snapshot = volunteerSourceDataSyncService.fetchLatestSourceData(
                tenantId,
                chatSessionId,
                Boolean.TRUE.equals(req.getSyncSourceData())
        );
        VolunteerRecommendListResponse latestResponse = volunteerBizService.recommendVolunteerListWithSourceData(
                tenantId,
                chatSessionId,
                false,
                snapshot.getVolunteerData()
        );
        CandidatePoolStateDTO latestCandidatePool = buildCandidatePoolStateFromResponse(chatSessionId, state, latestResponse);
        DataFreshnessChangeSummary summary = buildDataFreshnessChangeSummary(state.getCandidatePoolState(), latestCandidatePool);
        req.setDataHash(buildCandidateDataHash(latestCandidatePool));
        req.setDataVersion(snapshot.getSourceDataHash());
        req.setSourceDataHash(snapshot.getSourceDataHash());
        if (Strings.isNullOrEmpty(req.getChangeLevel())) {
            req.setChangeLevel(summary.changeLevel);
        }
        if (req.getChangedCount() == null) {
            req.setChangedCount(summary.changedCount());
        }
        if (req.getAddedCount() == null) {
            req.setAddedCount(summary.addedCount);
        }
        if (req.getRemovedCount() == null) {
            req.setRemovedCount(summary.removedCount);
        }
        if (req.getUpdatedCount() == null) {
            req.setUpdatedCount(summary.updatedCount);
        }
        if (req.getInvalidCount() == null) {
            req.setInvalidCount(summary.removedCount);
        }
        if (req.getAffectedVolunteerIds() == null || req.getAffectedVolunteerIds().isEmpty()) {
            req.setAffectedVolunteerIds(summary.affectedVolunteerIds);
        }
        if (req.getAffectedUnitIds() == null || req.getAffectedUnitIds().isEmpty()) {
            req.setAffectedUnitIds(summary.affectedUnitIds);
        }
        if (Strings.isNullOrEmpty(req.getSummary()) && summary.changedCount() > 0) {
            req.setSummary(summary.summaryText());
        }
        if (Strings.isNullOrEmpty(req.getDetail()) && summary.changedCount() > 0) {
            req.setDetail(summary.detailText());
        }
        if (Strings.isNullOrEmpty(req.getSummary()) && summary.changedCount() == 0) {
            req.setSummary("最新招生计划与当前工作区快照一致。");
        }
        return latestCandidatePool;
    }

    private boolean shouldApplyLatestDataFreshnessSnapshotToWorkspace(Long chatSessionId,
                                                                      PlanningStateDTO state,
                                                                      CandidatePoolStateDTO latestCandidatePool,
                                                                      DataFreshnessCheckReq req) {
        if (!Boolean.TRUE.equals(req == null ? null : req.getApplyLatestSnapshotToWorkspace())) {
            return false;
        }
        LatestCandidatePoolApplyCheck applyCheck = checkLatestCandidatePoolApplicable(state, latestCandidatePool);
        if (!applyCheck.applicable) {
            log.warn("skip dataFreshness workspace sync because latest candidate pool is incomplete chatSessionId={} "
                            + "currentCount={} latestCount={} selectedCount={} selectedMatchedCount={}",
                    chatSessionId,
                    applyCheck.currentCount,
                    applyCheck.latestCount,
                    applyCheck.selectedCount,
                    applyCheck.selectedMatchedCount);
            return false;
        }
        return true;
    }

    private LatestCandidatePoolApplyCheck checkLatestCandidatePoolApplicable(PlanningStateDTO state,
                                                                            CandidatePoolStateDTO latestCandidatePool) {
        LatestCandidatePoolApplyCheck result = new LatestCandidatePoolApplyCheck();
        CandidatePoolStateDTO currentCandidatePool = state == null ? null : state.getCandidatePoolState();
        result.currentCount = resolveCandidatePoolEntryCount(currentCandidatePool);
        result.latestCount = resolveCandidatePoolEntryCount(latestCandidatePool);
        if (result.currentCount <= 0) {
            result.applicable = latestCandidatePool != null;
            return result;
        }
        if (result.latestCount <= 0) {
            result.applicable = false;
            return result;
        }

        CandidateResolver resolver = new CandidateResolver(defaultCandidates(latestCandidatePool.getItems()));
        Set<String> selectedKeys = new LinkedHashSet<String>();
        for (OrderedItemDTO item : defaultOrderedItems(state == null || state.getOrderedPlanState() == null
                ? null : state.getOrderedPlanState().getItems())) {
            String key = buildWorkspacePlanCandidateLookupKey(item.getVolunteerId(), item.getSchoolName(), item.getMajorName());
            if (!Strings.isNullOrEmpty(key) && selectedKeys.add(key)) {
                result.selectedCount++;
                if (resolver.resolve(item) != null) {
                    result.selectedMatchedCount++;
                }
            }
        }
        for (DraftItemDTO item : defaultDraftItems(state == null || state.getWorkingPlanState() == null
                ? null : state.getWorkingPlanState().getItems())) {
            String key = buildWorkspacePlanCandidateLookupKey(item.getVolunteerId(), item.getSchoolName(), item.getMajorName());
            if (!Strings.isNullOrEmpty(key) && selectedKeys.add(key)) {
                result.selectedCount++;
                if (resolver.resolve(toCandidateLookupItem(item)) != null) {
                    result.selectedMatchedCount++;
                }
            }
        }

        boolean latestMuchSmallerThanCurrent = result.currentCount >= 8
                && result.latestCount * 10 < result.currentCount * 8;
        boolean selectedPlanNotCovered = result.selectedCount > 0
                && result.selectedMatchedCount < result.selectedCount;
        result.applicable = !(latestMuchSmallerThanCurrent && selectedPlanNotCovered);
        return result;
    }

    private int resolveCandidatePoolEntryCount(CandidatePoolStateDTO candidatePoolState) {
        if (candidatePoolState == null) {
            return 0;
        }
        int itemCount = defaultCandidates(candidatePoolState.getItems()).size();
        int summaryTotal = candidatePoolState.getSummary() == null
                ? 0 : defaultInteger(candidatePoolState.getSummary().getEntryTotal());
        int normalizedTotal = candidatePoolState.getSourceSummary() == null
                ? 0 : defaultInteger(candidatePoolState.getSourceSummary().getNormalizedEntryTotal());
        return Math.max(itemCount, Math.max(summaryTotal, normalizedTotal));
    }

    private String buildWorkspacePlanCandidateLookupKey(String volunteerId, String schoolName, String majorName) {
        String normalizedVolunteerId = normalizeText(volunteerId);
        if (!Strings.isNullOrEmpty(normalizedVolunteerId)) {
            return normalizedVolunteerId;
        }
        return buildCandidateFreshnessFallbackKey(schoolName, majorName);
    }

    private boolean syncLatestDataFreshnessSnapshotToWorkspace(Long chatSessionId,
                                                               PlanningStateDTO state,
                                                               DataFreshnessStateDTO freshness,
                                                               CandidatePoolStateDTO latestCandidatePool,
                                                               DataFreshnessCheckReq req,
                                                               String incomingHash) {
        if (state == null || latestCandidatePool == null) {
            return false;
        }
        String beforeSignature = buildDataFreshnessWorkspaceSyncSignature(state);
        state.setCandidatePoolState(latestCandidatePool);
        state.setRecommendationOverlayState(buildRecommendationOverlayState(latestCandidatePool, state.getVersion()));
        List<CandidateItemDTO> latestCandidates = resolveEffectiveCandidates(null, chatSessionId, state, false);
        CandidateResolver resolver = new CandidateResolver(latestCandidates);

        DraftPlanStateDTO draft = state.getWorkingPlanState();
        if (draft != null) {
            syncWorkingPlanItemsWithLatestCandidates(draft, resolver);
            syncWorkingPlanUnitsWithItems(draft, latestCandidates, latestCandidatePool);
            recalculateWorkingPlanSummary(draft, latestCandidatePool);
            state.setWorkingPlanState(draft);
        }

        OrderedPlanStateDTO orderedPlanState = state.getOrderedPlanState();
        if (orderedPlanState != null) {
            syncOrderedPlanItemsWithLatestCandidates(orderedPlanState, resolver);
            orderedPlanState.setUnits(buildOrderedUnitsFromOrderedItems(orderedPlanState.getItems(), draft, latestCandidates));
            recalculateOrderedSummary(orderedPlanState, latestCandidatePool);
            state.setOrderedPlanState(orderedPlanState);
        }

        syncAppliedDataFreshnessSnapshot(chatSessionId, freshness, latestCandidatePool, req, incomingHash);
        markDataFreshnessWorkspaceSynced(state, freshness);
        String afterSignature = buildDataFreshnessWorkspaceSyncSignature(state);
        return !Objects.equals(beforeSignature, afterSignature);
    }

    private String buildDataFreshnessWorkspaceSyncSignature(PlanningStateDTO state) {
        if (state == null) {
            return "";
        }
        return String.join("|",
                normalizeText(state.getCandidatePoolState() == null ? null : buildCandidateDataHash(state.getCandidatePoolState())),
                JSONObject.toJSONString(state.getRecommendationOverlayState()),
                JSONObject.toJSONString(state.getWorkingPlanState()),
                JSONObject.toJSONString(state.getOrderedPlanState()),
                JSONObject.toJSONString(state.getStaleFlags()));
    }

    private void syncAppliedDataFreshnessSnapshot(Long chatSessionId,
                                                  DataFreshnessStateDTO freshness,
                                                  CandidatePoolStateDTO latestCandidatePool,
                                                  DataFreshnessCheckReq req,
                                                  String incomingHash) {
        if (freshness == null || latestCandidatePool == null) {
            return;
        }
        String latestHash = Strings.isNullOrEmpty(incomingHash) ? buildCandidateDataHash(latestCandidatePool) : incomingHash;
        freshness.setFetchTime(latestCandidatePool.getGeneratedAt());
        freshness.setRequestHash(buildCandidateRequestHash(chatSessionId, latestCandidatePool));
        freshness.setDataHash(latestHash);
        freshness.setLatestDataHash(latestHash);
        freshness.setDataVersion(normalizeText(req == null ? null : req.getDataVersion()));
        freshness.setLatestDataVersion(normalizeText(req == null ? null : req.getDataVersion()));
        String sourceHash = normalizeText(req == null ? null : req.getSourceDataHash());
        if (!Strings.isNullOrEmpty(sourceHash)) {
            freshness.setSourceDataHash(sourceHash);
            freshness.setLatestSourceDataHash(sourceHash);
        }
        freshness.setProvince(latestCandidatePool.getSourceProvinceName());
        freshness.setScore(latestCandidatePool.getUserScore());
        freshness.setRequiresCandidateRefresh(Boolean.TRUE.equals(freshness.getRequiresCandidateRefresh())
                || hasDataFreshnessCandidateChanges(req));
    }

    private boolean hasDataFreshnessCandidateChanges(DataFreshnessCheckReq req) {
        if (req == null) {
            return false;
        }
        return defaultInteger(req.getChangedCount()) > 0
                || defaultInteger(req.getAddedCount()) > 0
                || defaultInteger(req.getRemovedCount()) > 0
                || defaultInteger(req.getUpdatedCount()) > 0
                || defaultInteger(req.getInvalidCount()) > 0;
    }

    private void markDataFreshnessWorkspaceSynced(PlanningStateDTO state, DataFreshnessStateDTO freshness) {
        if (state == null || state.getStaleFlags() == null || freshness == null) {
            return;
        }
        state.getStaleFlags().setCandidatePool(false);
        state.getStaleFlags().setRecommendationOverlay(false);
        state.getStaleFlags().setInitialRecommendation(false);
        state.getStaleFlags().setOrderedPlan(false);
        state.getStaleFlags().setPlanAdjustment(false);
        if (Boolean.TRUE.equals(freshness.getRequiresReview())) {
            state.getStaleFlags().setReview(true);
            state.getStaleFlags().setReasonCode("volunteer_data_synced");
            state.getStaleFlags().setMessage("招生计划数据已更新，系统已同步候选和专家推荐，并清理失效志愿，建议重新审查当前方案。");
            state.getStaleFlags().setAffectedReviewCodes(dataFreshnessAffectedReviewCodes());
        } else if (normalizeText(state.getStaleFlags().getReasonCode()).startsWith("volunteer_data")) {
            state.getStaleFlags().setReview(false);
            state.getStaleFlags().setReasonCode(null);
            state.getStaleFlags().setMessage(null);
            state.getStaleFlags().setAffectedReviewCodes(Lists.newArrayList());
        }
    }

    private void syncWorkingPlanItemsWithLatestCandidates(DraftPlanStateDTO draft, CandidateResolver resolver) {
        if (draft == null || resolver == null) {
            return;
        }
        List<DraftItemDTO> synced = Lists.newArrayList();
        Set<String> selectedVolunteerIds = new LinkedHashSet<String>();
        for (DraftItemDTO item : defaultDraftItems(draft.getItems())) {
            CandidateItemDTO candidate = resolver.resolve(toCandidateLookupItem(item));
            if (candidate == null || Strings.isNullOrEmpty(candidate.getVolunteerId())
                    || !selectedVolunteerIds.add(candidate.getVolunteerId())) {
                continue;
            }
            DraftItemDTO updated = new DraftItemDTO();
            updated.setVolunteerId(candidate.getVolunteerId());
            updated.setTier(candidate.getTier());
            updated.setSchoolName(candidate.getSchoolName());
            updated.setMajorName(candidate.getMajorName());
            updated.setLocked(item.getLocked());
            updated.setSource(item.getSource());
            synced.add(updated);
        }
        draft.setItems(synced);
    }

    private void syncOrderedPlanItemsWithLatestCandidates(OrderedPlanStateDTO orderedPlanState, CandidateResolver resolver) {
        if (orderedPlanState == null || resolver == null) {
            return;
        }
        List<OrderedItemDTO> synced = Lists.newArrayList();
        Set<String> selectedVolunteerIds = new LinkedHashSet<String>();
        for (OrderedItemDTO item : defaultOrderedItems(orderedPlanState.getItems())) {
            CandidateItemDTO candidate = resolver.resolve(item);
            if (candidate == null || Strings.isNullOrEmpty(candidate.getVolunteerId())
                    || !selectedVolunteerIds.add(candidate.getVolunteerId())) {
                continue;
            }
            OrderedItemDTO updated = new OrderedItemDTO();
            updated.setVolunteerId(candidate.getVolunteerId());
            updated.setTier(candidate.getTier());
            updated.setSchoolName(candidate.getSchoolName());
            updated.setMajorName(candidate.getMajorName());
            updated.setLocked(item.getLocked());
            updated.setPinned(item.getPinned());
            updated.setPinnedPosition(item.getPinnedPosition());
            updated.setOrderedBy(item.getOrderedBy());
            updated.setOrderReason(item.getOrderReason());
            updated.setSource(item.getSource());
            synced.add(updated);
        }
        orderedPlanState.setItems(OrderedPlanPositioningSupport.rebuildItems(synced));
    }

    private OrderedItemDTO toCandidateLookupItem(DraftItemDTO item) {
        if (item == null) {
            return null;
        }
        OrderedItemDTO lookup = new OrderedItemDTO();
        lookup.setVolunteerId(item.getVolunteerId());
        lookup.setSchoolName(item.getSchoolName());
        lookup.setMajorName(item.getMajorName());
        return lookup;
    }

    private String normalizeCurrentCandidateDataHash(PlanningStateDTO state, DataFreshnessStateDTO freshness) {
        CandidatePoolStateDTO candidatePoolState = state == null ? null : state.getCandidatePoolState();
        if (candidatePoolState != null && !defaultCandidates(candidatePoolState.getItems()).isEmpty()) {
            return normalizeText(buildCandidateDataHash(candidatePoolState));
        }
        return normalizeText(freshness == null ? null : freshness.getDataHash());
    }

    private String normalizeCurrentSourceDataHash(Long chatSessionId, DataFreshnessStateDTO freshness) {
        String sourceHash = normalizeText(freshness == null ? null : freshness.getSourceDataHash());
        if (!Strings.isNullOrEmpty(sourceHash)) {
            return sourceHash;
        }
        String latestSourceHash = normalizeText(freshness == null ? null : freshness.getLatestSourceDataHash());
        if (!Strings.isNullOrEmpty(latestSourceHash)) {
            return latestSourceHash;
        }
        return normalizeText(volunteerSourceDataSyncService.loadLocalSourceDataHash(chatSessionId));
    }

    private void markDataFreshnessCurrent(DataFreshnessStateDTO freshness,
                                          String latestHash,
                                          DataFreshnessCheckReq req) {
        freshness.setStatusCode("current");
        freshness.setChangeLevel("none");
        if (!Strings.isNullOrEmpty(latestHash)) {
            freshness.setDataHash(latestHash);
        }
        freshness.setLatestDataHash(Strings.isNullOrEmpty(latestHash) ? freshness.getDataHash() : latestHash);
        freshness.setLatestDataVersion(normalizeText(req.getDataVersion()));
        String sourceHash = normalizeText(req.getSourceDataHash());
        if (!Strings.isNullOrEmpty(sourceHash)) {
            freshness.setSourceDataHash(sourceHash);
            freshness.setLatestSourceDataHash(sourceHash);
        }
        freshness.setShouldNotify(false);
        freshness.setRequiresCandidateRefresh(false);
        freshness.setRequiresReview(false);
        freshness.setSummary(Strings.isNullOrEmpty(req.getSummary()) ? "招生计划数据未发现变化。" : req.getSummary());
        freshness.setDetail(null);
        freshness.setChangedCount(0);
        freshness.setAddedCount(0);
        freshness.setRemovedCount(0);
        freshness.setUpdatedCount(0);
        freshness.setInvalidCount(0);
        freshness.setAffectedVolunteerIds(Lists.newArrayList());
        freshness.setAffectedUnitIds(Lists.newArrayList());
        freshness.setAffectedReviewCodes(Lists.newArrayList());
    }

    private void clearDataFreshnessStaleFlags(PlanningStateDTO state) {
        if (state == null || state.getStaleFlags() == null) {
            return;
        }
        String reasonCode = normalizeText(state.getStaleFlags().getReasonCode());
        if (!reasonCode.startsWith("volunteer_data")) {
            return;
        }
        state.getStaleFlags().setCandidatePool(false);
        state.getStaleFlags().setRecommendationOverlay(false);
        state.getStaleFlags().setInitialRecommendation(false);
        state.getStaleFlags().setOrderedPlan(false);
        state.getStaleFlags().setPlanAdjustment(false);
        state.getStaleFlags().setReview(false);
        state.getStaleFlags().setReasonCode(null);
        state.getStaleFlags().setMessage(null);
        state.getStaleFlags().setAffectedReviewCodes(Lists.newArrayList());
    }

    private DataFreshnessChangeSummary buildDataFreshnessChangeSummary(CandidatePoolStateDTO current,
                                                                       CandidatePoolStateDTO latest) {
        Map<String, String> currentRows = buildCandidateFreshnessRowMap(current);
        Map<String, String> latestRows = buildCandidateFreshnessRowMap(latest);
        Map<String, CandidateItemDTO> currentItems = buildCandidateFreshnessItemMap(current);
        Map<String, CandidateItemDTO> latestItems = buildCandidateFreshnessItemMap(latest);
        Map<String, String> latestUnits = buildCandidateFreshnessUnitMap(latest);
        DataFreshnessChangeSummary summary = new DataFreshnessChangeSummary();
        Set<String> affectedIds = new LinkedHashSet<String>();
        Set<String> affectedUnitIds = new LinkedHashSet<String>();
        boolean majorGroupMode = isMajorGroupMode(latest) || isMajorGroupMode(current);
        Map<String, DataFreshnessUnitChangeSummary> unitChanges = new LinkedHashMap<String, DataFreshnessUnitChangeSummary>();
        for (Map.Entry<String, String> entry : latestRows.entrySet()) {
            String key = entry.getKey();
            CandidateItemDTO latestItem = latestItems.get(key);
            if (!currentRows.containsKey(key)) {
                summary.addedCount++;
                affectedIds.add(key);
                addIfNotEmpty(affectedUnitIds, latestUnits.get(key));
                recordDataFreshnessUnitChange(unitChanges, latestItem, key, "added", majorGroupMode);
            } else if (!Objects.equals(entry.getValue(), currentRows.get(key))) {
                summary.updatedCount++;
                affectedIds.add(key);
                addIfNotEmpty(affectedUnitIds, latestUnits.get(key));
                recordDataFreshnessUnitChange(unitChanges, latestItem, key, "updated", majorGroupMode);
            }
        }
        for (String key : currentRows.keySet()) {
            if (!latestRows.containsKey(key)) {
                summary.removedCount++;
                affectedIds.add(key);
                CandidateItemDTO currentItem = currentItems.get(key);
                addIfNotEmpty(affectedUnitIds, resolveInitialRecommendationUnitId(currentItem));
                recordDataFreshnessUnitChange(unitChanges, currentItem, key, "removed", majorGroupMode);
            }
        }
        summary.affectedVolunteerIds = Lists.newArrayList(affectedIds);
        summary.affectedUnitIds = Lists.newArrayList(affectedUnitIds);
        summary.detailLines = unitChanges.values().stream()
                .sorted(Comparator.comparing(DataFreshnessUnitChangeSummary::changedCount).reversed()
                        .thenComparing(item -> normalizeText(item.groupName)))
                .limit(5)
                .map(item -> item.lineText(majorGroupMode))
                .collect(Collectors.toList());
        int hiddenUnitCount = unitChanges.size() - summary.detailLines.size();
        if (hiddenUnitCount > 0) {
            summary.detailLines.add(majorGroupMode
                    ? "另有 " + hiddenUnitCount + " 个专业组发生变化。"
                    : "另有 " + hiddenUnitCount + " 所院校涉及专业变化。");
        }
        summary.changeLevel = deriveDataFreshnessChangeLevel(summary);
        return summary;
    }

    private void recordDataFreshnessUnitChange(Map<String, DataFreshnessUnitChangeSummary> unitChanges,
                                                CandidateItemDTO item,
                                                String fallbackKey,
                                                String changeType,
                                                boolean majorGroupMode) {
        if (unitChanges == null) {
            return;
        }
        String unitKey = resolveDataFreshnessChangeGroupKey(item, fallbackKey, majorGroupMode);
        if (Strings.isNullOrEmpty(unitKey)) {
            return;
        }
        DataFreshnessUnitChangeSummary unitChange = unitChanges.get(unitKey);
        if (unitChange == null) {
            unitChange = new DataFreshnessUnitChangeSummary();
            unitChange.groupName = resolveDataFreshnessChangeGroupName(item, fallbackKey, majorGroupMode);
            if (Strings.isNullOrEmpty(unitChange.groupName)) {
                unitChange.groupName = unitKey;
            }
            unitChanges.put(unitKey, unitChange);
        }
        if ("added".equals(changeType)) {
            unitChange.addedCount++;
        } else if ("removed".equals(changeType)) {
            unitChange.removedCount++;
        } else {
            unitChange.updatedCount++;
        }
        String majorName = normalizeText(item == null ? null : item.getMajorName());
        if (Strings.isNullOrEmpty(majorName)) {
            majorName = normalizeText(fallbackKey);
        }
        if (!Strings.isNullOrEmpty(majorName)) {
            unitChange.itemNames.add(majorName);
        }
    }

    private String resolveDataFreshnessChangeGroupKey(CandidateItemDTO item,
                                                      String fallbackKey,
                                                      boolean majorGroupMode) {
        if (item == null) {
            return normalizeText(fallbackKey);
        }
        if (majorGroupMode) {
            return normalizeText(firstNonEmpty(
                    item.getPlanSchoolDataId(),
                    item.getSchoolUnitCode(),
                    resolveInitialRecommendationUnitId(item),
                    item.getSchoolName(),
                    fallbackKey
            ));
        }
        return normalizeText(firstNonEmpty(
                item.getSchoolId(),
                item.getSchoolName(),
                fallbackKey
        ));
    }

    private String resolveDataFreshnessChangeGroupName(CandidateItemDTO item,
                                                       String fallbackKey,
                                                       boolean majorGroupMode) {
        if (item == null) {
            return normalizeText(fallbackKey);
        }
        String rawSchoolName = normalizeText(item.getSchoolName());
        String displaySchoolName = normalizeText(item.getDisplaySchoolName());
        if (majorGroupMode) {
            String groupName = firstNonEmpty(rawSchoolName, displaySchoolName);
            String groupCode = normalizeText(item.getSchoolUnitCode());
            if (!Strings.isNullOrEmpty(groupCode)
                    && !Strings.isNullOrEmpty(groupName)
                    && !groupName.contains(groupCode)
                    && !groupName.contains("(")
                    && !groupName.contains("（")) {
                return groupName + "（" + groupCode + "）";
            }
            return firstNonEmpty(groupName, groupCode, normalizeText(fallbackKey));
        }
        String schoolName = firstNonEmpty(displaySchoolName, rawSchoolName);
        return firstNonEmpty(schoolName, normalizeText(item.getMajorName()), normalizeText(fallbackKey));
    }

    private Map<String, CandidateItemDTO> buildCandidateFreshnessItemMap(CandidatePoolStateDTO candidatePoolState) {
        Map<String, CandidateItemDTO> rows = new LinkedHashMap<String, CandidateItemDTO>();
        for (CandidateItemDTO item : defaultCandidates(candidatePoolState == null ? null : candidatePoolState.getItems())) {
            String key = resolveCandidateFreshnessKey(item);
            if (Strings.isNullOrEmpty(key)) {
                continue;
            }
            rows.put(key, item);
        }
        return rows;
    }

    private Map<String, String> buildCandidateFreshnessRowMap(CandidatePoolStateDTO candidatePoolState) {
        Map<String, String> rows = new LinkedHashMap<String, String>();
        for (CandidateItemDTO item : defaultCandidates(candidatePoolState == null ? null : candidatePoolState.getItems())) {
            String key = resolveCandidateFreshnessKey(item);
            if (Strings.isNullOrEmpty(key)) {
                continue;
            }
            rows.put(key, buildPayloadDigest(JSONObject.toJSONString(buildCandidateDataHashRow(item))));
        }
        return rows;
    }

    private Map<String, String> buildCandidateFreshnessUnitMap(CandidatePoolStateDTO candidatePoolState) {
        Map<String, String> rows = new LinkedHashMap<String, String>();
        for (CandidateItemDTO item : defaultCandidates(candidatePoolState == null ? null : candidatePoolState.getItems())) {
            String key = resolveCandidateFreshnessKey(item);
            if (Strings.isNullOrEmpty(key)) {
                continue;
            }
            rows.put(key, resolveInitialRecommendationUnitId(item));
        }
        return rows;
    }

    private String resolveCandidateFreshnessKey(CandidateItemDTO item) {
        if (item == null) {
            return null;
        }
        if (!Strings.isNullOrEmpty(item.getVolunteerId())) {
            return item.getVolunteerId();
        }
        return buildCandidateFreshnessFallbackKey(item.getSchoolName(), item.getMajorName());
    }

    private String buildCandidateFreshnessFallbackKey(String schoolName, String majorName) {
        String normalizedSchool = normalizeText(schoolName);
        String normalizedMajor = normalizeText(majorName);
        if (Strings.isNullOrEmpty(normalizedSchool) && Strings.isNullOrEmpty(normalizedMajor)) {
            return null;
        }
        return normalizedSchool + "::" + normalizedMajor;
    }

    private void addIfNotEmpty(Set<String> values, String value) {
        if (values != null && !Strings.isNullOrEmpty(value)) {
            values.add(value);
        }
    }

    private String deriveDataFreshnessChangeLevel(DataFreshnessChangeSummary summary) {
        int changedCount = summary.changedCount();
        if (changedCount == 0) {
            return "none";
        }
        if (summary.removedCount > 0 || changedCount >= 50) {
            return "major";
        }
        if (changedCount >= 10) {
            return "medium";
        }
        return "minor";
    }

    private static class DataFreshnessUnitChangeSummary {
        private String groupName;
        private int addedCount;
        private int removedCount;
        private int updatedCount;
        private LinkedHashSet<String> itemNames = new LinkedHashSet<String>();

        private int changedCount() {
            return addedCount + removedCount + updatedCount;
        }

        private String lineText(boolean majorGroupMode) {
            List<String> parts = Lists.newArrayList();
            if (addedCount > 0) {
                parts.add("新增 " + addedCount + " 项");
            }
            if (updatedCount > 0) {
                parts.add("更新 " + updatedCount + " 项");
            }
            if (removedCount > 0) {
                parts.add("失效 " + removedCount + " 项");
            }
            List<String> itemTexts = itemNames.stream()
                    .filter(itemName -> !Strings.isNullOrEmpty(itemName) && !itemName.equals(groupName))
                    .limit(3)
                    .collect(Collectors.toList());
            String itemLabel = majorGroupMode ? "组内专业" : "专业";
            String itemText = itemTexts.isEmpty()
                    ? ""
                    : "，涉及" + itemLabel + " " + String.join("、", itemTexts) + (itemNames.size() > 3 ? "等" : "");
            return groupName + "：" + String.join("，", parts) + itemText;
        }
    }

    private static class DataFreshnessChangeSummary {
        private int addedCount;
        private int removedCount;
        private int updatedCount;
        private String changeLevel = "none";
        private List<String> affectedVolunteerIds = Lists.newArrayList();
        private List<String> affectedUnitIds = Lists.newArrayList();
        private List<String> detailLines = Lists.newArrayList();

        private int changedCount() {
            return addedCount + removedCount + updatedCount;
        }

        private String summaryText() {
            List<String> parts = Lists.newArrayList();
            if (addedCount > 0) {
                parts.add("新增 " + addedCount + " 项");
            }
            if (updatedCount > 0) {
                parts.add("更新 " + updatedCount + " 项");
            }
            if (removedCount > 0) {
                parts.add("失效 " + removedCount + " 项");
            }
            return "招生计划数据已变化：" + String.join("，", parts) + "。";
        }

        private String detailText() {
            if (detailLines == null || detailLines.isEmpty()) {
                return null;
            }
            return "主要影响：\n" + String.join("\n", detailLines);
        }
    }

    private static class LatestCandidatePoolApplyCheck {
        private boolean applicable = true;
        private int currentCount;
        private int latestCount;
        private int selectedCount;
        private int selectedMatchedCount;
    }

    private boolean backfillDataFreshnessState(Long chatSessionId, PlanningStateDTO state) {
        if (state == null) {
            return false;
        }
        if (state.getDataFreshnessState() == null) {
            state.setDataFreshnessState(new DataFreshnessStateDTO());
        }
        DataFreshnessStateDTO freshness = state.getDataFreshnessState();
        CandidatePoolStateDTO candidatePoolState = state.getCandidatePoolState();
        if (candidatePoolState == null || defaultCandidates(candidatePoolState.getItems()).isEmpty()) {
            return false;
        }
        if (!Strings.isNullOrEmpty(freshness.getDataHash())) {
            return false;
        }
        refreshDataFreshnessSnapshot(chatSessionId, state, candidatePoolState);
        return true;
    }

    private void refreshDataFreshnessSnapshot(Long chatSessionId,
                                              PlanningStateDTO state,
                                              CandidatePoolStateDTO candidatePoolState) {
        if (state == null) {
            return;
        }
        DataFreshnessStateDTO previous = state.getDataFreshnessState();
        DataFreshnessStateDTO freshness = buildDataFreshnessSnapshot(chatSessionId, state, candidatePoolState);
        preserveRecentDataFreshnessChange(previous, freshness);
        state.setDataFreshnessState(freshness);
    }

    private DataFreshnessStateDTO buildDataFreshnessSnapshot(Long chatSessionId,
                                                             PlanningStateDTO state,
                                                             CandidatePoolStateDTO candidatePoolState) {
        DataFreshnessStateDTO freshness = new DataFreshnessStateDTO();
        freshness.setSource("gaotu");
        CreateSessionReq scoreDetail = loadCreateSessionReq(chatSessionId);
        String now = OffsetDateTime.now().toString();
        freshness.setFetchTime(candidatePoolState == null || Strings.isNullOrEmpty(candidatePoolState.getGeneratedAt())
                ? now : candidatePoolState.getGeneratedAt());
        freshness.setLastCheckedAt(now);
        freshness.setExamYear(scoreDetail == null || scoreDetail.getExamYear() == null
                ? null : String.valueOf(scoreDetail.getExamYear()));
        freshness.setPrepareType(scoreDetail == null || scoreDetail.getPrepareType() == null
                ? null : scoreDetail.getPrepareType().getCode());
        freshness.setProvince(candidatePoolState == null ? null : candidatePoolState.getSourceProvinceName());
        freshness.setBatch(scoreDetail == null || scoreDetail.getBatch() == null ? null : scoreDetail.getBatch().getName());
        freshness.setSubjectType(scoreDetail == null || scoreDetail.getSubjectType() == null
                ? null : scoreDetail.getSubjectType().getDesc());
        freshness.setScore(candidatePoolState == null ? null : candidatePoolState.getUserScore());
        freshness.setRequestHash(buildCandidateRequestHash(chatSessionId, candidatePoolState));
        freshness.setDataHash(buildCandidateDataHash(candidatePoolState));
        freshness.setDataVersion(candidatePoolState == null || candidatePoolState.getSourceVersion() == null
                ? null : String.valueOf(candidatePoolState.getSourceVersion()));
        freshness.setLatestDataHash(freshness.getDataHash());
        String sourceDataHash = normalizeText(volunteerSourceDataSyncService.loadLocalSourceDataHash(chatSessionId));
        freshness.setSourceDataHash(sourceDataHash);
        freshness.setLatestSourceDataHash(sourceDataHash);
        freshness.setLatestDataVersion(freshness.getDataVersion());
        freshness.setStatusCode("current");
        freshness.setChangeLevel("none");
        freshness.setShouldNotify(false);
        freshness.setRequiresCandidateRefresh(false);
        freshness.setRequiresReview(false);
        freshness.setSummary("已记录当前招生计划快照。");
        freshness.setChangedCount(0);
        freshness.setAffectedVolunteerIds(Lists.newArrayList());
        freshness.setAffectedUnitIds(Lists.newArrayList());
        freshness.setAffectedReviewCodes(Lists.newArrayList());
        return freshness;
    }

    private void preserveRecentDataFreshnessChange(DataFreshnessStateDTO previous, DataFreshnessStateDTO target) {
        if (!hasRecentDataFreshnessChangeSummary(previous) || target == null) {
            return;
        }
        target.setSummary(previous.getSummary());
        target.setDetail(previous.getDetail());
        target.setChangedCount(defaultInteger(previous.getChangedCount()));
        target.setAddedCount(defaultInteger(previous.getAddedCount()));
        target.setRemovedCount(defaultInteger(previous.getRemovedCount()));
        target.setUpdatedCount(defaultInteger(previous.getUpdatedCount()));
        target.setInvalidCount(defaultInteger(previous.getInvalidCount()));
        target.setAffectedVolunteerIds(defaultStringList(previous.getAffectedVolunteerIds()));
        target.setAffectedUnitIds(defaultStringList(previous.getAffectedUnitIds()));
        target.setAffectedReviewCodes(defaultStringList(previous.getAffectedReviewCodes()));
        String latestSourceHash = normalizeText(previous.getLatestSourceDataHash());
        if (!Strings.isNullOrEmpty(latestSourceHash)) {
            target.setLatestSourceDataHash(latestSourceHash);
        }
    }

    private boolean hasRecentDataFreshnessChangeSummary(DataFreshnessStateDTO state) {
        if (state == null) {
            return false;
        }
        int changedCount = defaultInteger(state.getChangedCount())
                + defaultInteger(state.getAddedCount())
                + defaultInteger(state.getRemovedCount())
                + defaultInteger(state.getUpdatedCount())
                + defaultInteger(state.getInvalidCount());
        if (changedCount > 0) {
            return true;
        }
        String summary = normalizeText(state.getSummary());
        return summary.startsWith("招生计划数据已变化") || summary.startsWith("检测到高途招生计划源数据有更新");
    }

    private void applyDataFreshnessChange(PlanningStateDTO state,
                                          DataFreshnessStateDTO freshness,
                                          DataFreshnessCheckReq req,
                                          String incomingHash,
                                          String checkedAt) {
        String level = normalizeChangeLevel(req.getChangeLevel());
        freshness.setStatusCode("changed");
        freshness.setChangeLevel(level);
        freshness.setLatestDataHash(incomingHash);
        freshness.setLatestDataVersion(normalizeText(req.getDataVersion()));
        freshness.setLastCheckedAt(checkedAt);
        freshness.setShouldNotify(true);
        freshness.setRequiresCandidateRefresh(true);
        freshness.setRequiresReview(!"minor".equals(level));
        freshness.setSummary(Strings.isNullOrEmpty(req.getSummary()) ? defaultDataFreshnessSummary(level) : req.getSummary());
        freshness.setDetail(req.getDetail());
        freshness.setChangedCount(defaultInteger(req.getChangedCount()));
        freshness.setAddedCount(defaultInteger(req.getAddedCount()));
        freshness.setRemovedCount(defaultInteger(req.getRemovedCount()));
        freshness.setUpdatedCount(defaultInteger(req.getUpdatedCount()));
        freshness.setInvalidCount(defaultInteger(req.getInvalidCount()));
        String sourceHash = normalizeText(req.getSourceDataHash());
        if (!Strings.isNullOrEmpty(sourceHash)) {
            freshness.setLatestSourceDataHash(sourceHash);
        }
        freshness.setAffectedVolunteerIds(defaultStringList(req.getAffectedVolunteerIds()));
        freshness.setAffectedUnitIds(defaultStringList(req.getAffectedUnitIds()));
        freshness.setAffectedReviewCodes("minor".equals(level) ? Lists.newArrayList() : dataFreshnessAffectedReviewCodes());
    }

    private void markDataFreshnessSourceChanged(PlanningStateDTO state,
                                                DataFreshnessStateDTO freshness,
                                                String latestSourceHash,
                                                String checkedAt) {
        freshness.setStatusCode("changed");
        freshness.setChangeLevel("minor");
        freshness.setLatestSourceDataHash(latestSourceHash);
        freshness.setLatestDataVersion(latestSourceHash);
        freshness.setLastCheckedAt(checkedAt);
        freshness.setShouldNotify(true);
        freshness.setRequiresCandidateRefresh(true);
        freshness.setRequiresReview(false);
        freshness.setSummary("检测到高途招生计划源数据有更新，建议点击检查更新确认影响范围，或刷新候选后继续填报。");
        freshness.setDetail("本次为轻量版本检查，尚未执行候选级影响分析。");
        freshness.setChangedCount(0);
        freshness.setAddedCount(0);
        freshness.setRemovedCount(0);
        freshness.setUpdatedCount(0);
        freshness.setInvalidCount(0);
        freshness.setAffectedVolunteerIds(Lists.newArrayList());
        freshness.setAffectedUnitIds(Lists.newArrayList());
        freshness.setAffectedReviewCodes(Lists.newArrayList());
    }

    private void markDataFreshnessStale(PlanningStateDTO state, DataFreshnessStateDTO freshness) {
        if (state == null || state.getStaleFlags() == null || freshness == null) {
            return;
        }
        String level = normalizeChangeLevel(freshness.getChangeLevel());
        if ("minor".equals(level)) {
            state.getStaleFlags().setCandidatePool(true);
            state.getStaleFlags().setInitialRecommendation(true);
            state.getStaleFlags().setPlanAdjustment(true);
            state.getStaleFlags().setReasonCode("volunteer_data_minor_changed");
            state.getStaleFlags().setMessage("招生计划数据有轻微更新，系统将刷新候选和专家推荐，当前方案不自动调整。");
            state.getStaleFlags().setAffectedReviewCodes(Lists.newArrayList());
            return;
        }
        state.getStaleFlags().setCandidatePool(true);
        state.getStaleFlags().setRecommendationOverlay(true);
        ReviewInvalidationPolicy.markCandidatePoolDependentsStale(state);
        state.getStaleFlags().setReasonCode("volunteer_data_changed");
        state.getStaleFlags().setMessage("招生计划数据已更新，系统将刷新候选和专家推荐，当前方案不自动调整，建议重新审查确认。");
        state.getStaleFlags().setAffectedReviewCodes(dataFreshnessAffectedReviewCodes());
    }

    private void appendDataFreshnessOperationLog(PlanningStateDTO state, DataFreshnessStateDTO freshness) {
        if (state == null || freshness == null) {
            return;
        }
        if (state.getOperationLogs() == null) {
            state.setOperationLogs(Lists.newArrayList());
        }
        OperationLogDTO logItem = new OperationLogDTO();
        logItem.setType("volunteer_data_change_detected");
        logItem.setOperator("system");
        logItem.setCreatedAt(OffsetDateTime.now().toString());
        logItem.setDetail(freshness.getSummary());
        logItem.setVolunteerIds(defaultStringList(freshness.getAffectedVolunteerIds()));
        state.getOperationLogs().add(logItem);
    }

    private String buildCandidateRequestHash(Long chatSessionId, CandidatePoolStateDTO candidatePoolState) {
        Map<String, Object> payload = new LinkedHashMap<String, Object>();
        payload.put("chatSessionId", chatSessionId);
        payload.put("province", candidatePoolState == null ? null : candidatePoolState.getSourceProvinceName());
        payload.put("volunteerModel", candidatePoolState == null ? null : candidatePoolState.getVolunteerModel());
        payload.put("userScore", candidatePoolState == null ? null : candidatePoolState.getUserScore());
        payload.put("batchScore", candidatePoolState == null ? null : candidatePoolState.getBatchScore());
        payload.put("requiredCount", candidatePoolState == null ? null : candidatePoolState.getRequiredCount());
        payload.put("requiredUnitCount", candidatePoolState == null ? null : candidatePoolState.getRequiredUnitCount());
        payload.put("requiredMajorCount", candidatePoolState == null ? null : candidatePoolState.getRequiredMajorCount());
        return buildPayloadDigest(JSONObject.toJSONString(payload));
    }

    private String buildCandidateDataHash(CandidatePoolStateDTO candidatePoolState) {
        List<Map<String, Object>> rows = defaultCandidates(candidatePoolState == null ? null : candidatePoolState.getItems()).stream()
                .sorted(Comparator.comparing((CandidateItemDTO item) -> normalizeText(item.getVolunteerId()))
                        .thenComparing(item -> normalizeText(resolveInitialRecommendationUnitId(item))))
                .map(this::buildCandidateDataHashRow)
                .collect(Collectors.toList());
        return buildPayloadDigest(JSONObject.toJSONString(rows));
    }

    private Map<String, Object> buildCandidateDataHashRow(CandidateItemDTO item) {
        Map<String, Object> row = new LinkedHashMap<String, Object>();
        row.put("volunteerId", item == null ? null : item.getVolunteerId());
        row.put("unitId", item == null ? null : resolveInitialRecommendationUnitId(item));
        row.put("tier", item == null ? null : item.getTier());
        row.put("subTier", item == null ? null : item.getSubTier());
        row.put("rankInTier", item == null ? null : item.getRankInTier());

        row.put("planSchoolDataId", item == null ? null : item.getPlanSchoolDataId());
        row.put("schoolId", item == null ? null : item.getSchoolId());
        row.put("schoolUnitCode", item == null ? null : item.getSchoolUnitCode());
        row.put("schoolName", item == null ? null : item.getSchoolName());
        row.put("provinceName", item == null ? null : item.getProvinceName());
        row.put("cityName", item == null ? null : item.getCityName());
        row.put("schoolBatch", item == null ? null : item.getSchoolBatch());
        row.put("schoolLevel", item == null ? null : item.getSchoolLevel());
        row.put("schoolNature", item == null ? null : item.getSchoolNature());
        row.put("schoolCategory", item == null ? null : item.getSchoolCategory());
        row.put("schoolRank", item == null ? null : item.getSchoolRank());
        row.put("schoolEnrollRatio", item == null ? null : item.getSchoolEnrollRatio());
        row.put("baoyanRatio", item == null ? null : item.getBaoyanRatio());
        row.put("upgradeRatio", item == null ? null : item.getUpgradeRatio());
        row.put("masterCount", item == null ? null : item.getMasterCount());
        row.put("doctorCount", item == null ? null : item.getDoctorCount());
        row.put("schoolRankTags", item == null ? null : normalizeHashList(item.getSchoolRankTags()));
        row.put("schoolBasicTags", item == null ? null : normalizeHashList(item.getSchoolBasicTags()));
        row.put("schoolPopupTags", item == null ? null : normalizeHashList(item.getSchoolPopupTags()));
        row.put("schoolHistoryScores", item == null ? null : buildHistoryScoreHashRows(item.getSchoolHistoryScores()));

        row.put("majorId", item == null ? null : item.getMajorId());
        row.put("majorName", item == null ? null : item.getMajorName());
        row.put("majorCode", item == null ? null : item.getMajorCode());
        row.put("majorCategoryId", item == null ? null : item.getMajorCategoryId());
        row.put("majorSubCategoryId", item == null ? null : item.getMajorSubCategoryId());
        row.put("majorLevel", item == null ? null : item.getMajorLevel());
        row.put("majorDiscipline", item == null ? null : item.getMajorDiscipline());
        row.put("majorCategory", item == null ? null : item.getMajorCategory());
        row.put("majorTier", item == null ? null : item.getMajorTier());
        row.put("planNum", item == null ? null : item.getPlanNum());
        row.put("duration", item == null ? null : item.getDuration());
        row.put("tuitionPerYear", item == null ? null : item.getTuitionPerYear());
        row.put("admissionRatio", item == null ? null : item.getAdmissionRatio());
        row.put("mustSubjects", item == null ? null : normalizeHashList(item.getMustSubjects()));
        row.put("majorRankTags", item == null ? null : normalizeHashList(item.getMajorRankTags()));
        row.put("majorPlanTags", item == null ? null : normalizeHashList(item.getMajorPlanTags()));
        row.put("majorHistoryScores", item == null ? null : buildHistoryScoreHashRows(item.getMajorHistoryScores()));

        row.put("baseScore", item == null ? null : item.getBaseScore());
        row.put("intentScore", item == null ? null : item.getIntentScore());
        row.put("finalScore", item == null ? null : item.getFinalScore());
        row.put("futureDevelopmentScore", item == null ? null : item.getFutureDevelopmentScore());
        row.put("hotIndex", item == null ? null : item.getHotIndex());
        row.put("salaryAvg", item == null ? null : item.getSalaryAvg());
        row.put("reasonCodes", item == null ? null : normalizeHashList(item.getReasonCodes()));
        row.put("riskFlags", item == null ? null : normalizeHashList(item.getRiskFlags()));
        return row;
    }

    private List<String> normalizeHashList(List<String> values) {
        return defaultStringList(values).stream()
                .map(this::normalizeText)
                .filter(value -> !Strings.isNullOrEmpty(value))
                .distinct()
                .sorted()
                .collect(Collectors.toList());
    }

    private List<Map<String, Object>> buildHistoryScoreHashRows(List<CandidateItemDTO.HistoryScoreItem> historyScores) {
        return (historyScores == null ? Lists.<CandidateItemDTO.HistoryScoreItem>newArrayList() : historyScores).stream()
                .sorted(Comparator.comparing((CandidateItemDTO.HistoryScoreItem item) -> item == null ? null : item.getYear(), Comparator.nullsLast(Integer::compareTo)))
                .map(item -> {
                    Map<String, Object> row = new LinkedHashMap<String, Object>();
                    row.put("year", item == null ? null : item.getYear());
                    row.put("score", item == null ? null : item.getScore());
                    row.put("pos", item == null ? null : item.getPos());
                    row.put("planNum", item == null ? null : item.getPlanNum());
                    row.put("enrollNum", item == null ? null : item.getEnrollNum());
                    return row;
                })
                .collect(Collectors.toList());
    }

    private List<String> dataFreshnessAffectedReviewCodes() {
        return Lists.newArrayList(
                "ratio_distribution",
                "safety_guard",
                "probability_inversion",
                "probability_gap",
                "count_validation",
                "high_tuition",
                "admission_limit",
                "special_enrollment",
                "edge_score",
                "cooperative_program",
                "major_group_safety_intent_alignment",
                "group_inner_safety_guard",
                "plan_update_notice"
        );
    }

    private String defaultDataFreshnessSummary(String level) {
        if ("major".equals(level)) {
            return "招生计划数据出现重要变化，当前方案需要尽快重新核验。";
        }
        if ("medium".equals(level)) {
            return "部分院校或专业组数据已更新，建议重新审查当前方案。";
        }
        return "招生计划数据有轻微更新，当前方案未发现明确结构性影响。";
    }

    private String normalizeChangeLevel(String value) {
        String normalized = normalizeText(value).toLowerCase(Locale.ROOT);
        if ("major".equals(normalized) || "critical".equals(normalized) || "high".equals(normalized)) {
            return "major";
        }
        if ("medium".equals(normalized) || "moderate".equals(normalized)) {
            return "medium";
        }
        if ("minor".equals(normalized) || "low".equals(normalized)) {
            return "minor";
        }
        return "medium";
    }

    private String normalizeText(String value) {
        return value == null ? "" : value.trim();
    }

    private String blankToNull(String value) {
        String normalized = normalizeText(value);
        return Strings.isNullOrEmpty(normalized) ? null : normalized;
    }

    private Integer defaultInteger(Integer value) {
        return value == null ? 0 : value;
    }

    private List<String> defaultStringList(List<String> values) {
        return values == null ? Lists.newArrayList() : Lists.newArrayList(values.stream()
                .filter(value -> !Strings.isNullOrEmpty(value))
                .collect(Collectors.toList()));
    }


    public DataFreshnessStateDTO getDataFreshnessState(Long tenantId, Long chatSessionId) {
        PlanningDataFreshnessScheduleEntity schedule = touchDataFreshnessSchedule(tenantId, chatSessionId, null, true, false);
        PlanningStateDTO state = loadPlanningStateReadOnly(chatSessionId);
        if (isEmptyPlanningWorkspaceState(state)) {
            return buildScheduleOnlyDataFreshnessState(schedule);
        }
        touchDataFreshnessSchedule(tenantId, chatSessionId, state, true, false);
        return mergeScheduleDataFreshnessState(tenantId, state);
    }

    public DataFreshnessScheduleDTO getDataFreshnessSchedule(Long tenantId, Long chatSessionId) {
        PlanningDataFreshnessScheduleEntity entity = touchDataFreshnessSchedule(tenantId, chatSessionId, null, true, false);
        return planningDataFreshnessScheduleSharedService.toDto(entity);
    }

    public DataFreshnessScheduleDTO ensureDataFreshnessScheduleIndex(Long tenantId, Long chatSessionId) {
        PlanningDataFreshnessScheduleEntity entity = touchDataFreshnessSchedule(tenantId, chatSessionId, null, false, false);
        return planningDataFreshnessScheduleSharedService.toDto(entity);
    }

    public DataFreshnessScheduleDTO checkDataFreshnessLightweightForSchedule(Long tenantId,
                                                                              Long chatSessionId,
                                                                              String source) {
        PlanningDataFreshnessScheduleEntity schedule = planningDataFreshnessScheduleSharedService.getByChatSessionId(chatSessionId);
        if (schedule == null) {
            schedule = touchDataFreshnessSchedule(tenantId, chatSessionId, null, false, false);
        }
        if (schedule == null || !Boolean.TRUE.equals(schedule.getEnabled())) {
            return planningDataFreshnessScheduleSharedService.toDto(schedule);
        }
        String checkSource = Strings.isNullOrEmpty(source) ? "scheduler" : source;
        planningDataFreshnessScheduleSharedService.markChecking(chatSessionId);
        try {
            VolunteerSourceDataSnapshot snapshot = volunteerSourceDataSyncService.fetchLatestSourceData(tenantId, chatSessionId, false);
            String latestSourceHash = normalizeText(snapshot == null ? null : snapshot.getSourceDataHash());
            String currentSourceHash = normalizeText(schedule.getSourceDataHash());
            if (Strings.isNullOrEmpty(currentSourceHash)) {
                currentSourceHash = normalizeText(volunteerSourceDataSyncService.loadLocalSourceDataHash(chatSessionId));
            }
            String status = (!Strings.isNullOrEmpty(currentSourceHash)
                    && !Strings.isNullOrEmpty(latestSourceHash)
                    && !latestSourceHash.equals(currentSourceHash)) ? "changed" : "current";
            planningDataFreshnessScheduleSharedService.markSuccess(chatSessionId, checkSource, status, currentSourceHash, latestSourceHash, new Date());
            return planningDataFreshnessScheduleSharedService.toDto(
                    planningDataFreshnessScheduleSharedService.getByChatSessionId(chatSessionId));
        } catch (Exception ex) {
            log.warn("dataFreshnessSchedule lightweight check failed tenantId={} chatSessionId={} source={}",
                    tenantId, chatSessionId, checkSource, ex);
            planningDataFreshnessScheduleSharedService.markFailure(chatSessionId, checkSource, ex.getMessage(), new Date());
            return planningDataFreshnessScheduleSharedService.toDto(
                    planningDataFreshnessScheduleSharedService.getByChatSessionId(chatSessionId));
        }
    }

    private PlanningDataFreshnessScheduleEntity touchDataFreshnessSchedule(Long tenantId,
                                                                            Long chatSessionId,
                                                                            PlanningStateDTO state,
                                                                            boolean markAccess,
                                                                            boolean syncFreshnessState) {
        if (chatSessionId == null) {
            return null;
        }
        ChatSession session = chatSessionSharedService.getById(chatSessionId);
        CreateSessionReq scoreDetail = loadCreateSessionReq(chatSessionId);
        if (session == null || scoreDetail == null) {
            return null;
        }
        DataFreshnessStateDTO freshness = state == null ? null : state.getDataFreshnessState();
        PlanningDataFreshnessScheduleEntity entity = buildDataFreshnessScheduleEntity(tenantId, chatSessionId, session,
                scoreDetail, freshness, markAccess, syncFreshnessState);
        return planningDataFreshnessScheduleSharedService.saveOrUpdateSchedule(entity);
    }

    private PlanningDataFreshnessScheduleEntity buildDataFreshnessScheduleEntity(Long tenantId,
                                                                                  Long chatSessionId,
                                                                                  ChatSession session,
                                                                                  CreateSessionReq scoreDetail,
                                                                                  DataFreshnessStateDTO freshness,
                                                                                  boolean markAccess,
                                                                                  boolean syncFreshnessState) {
        PlanningDataFreshnessScheduleEntity entity = new PlanningDataFreshnessScheduleEntity();
        entity.setChatSessionId(chatSessionId);
        entity.setTenantId(tenantId != null ? tenantId : (session == null ? null : session.getTenantId()));
        entity.setSessionStatus(session == null || session.getSessionStatus() == null ? null : session.getSessionStatus().name());
        entity.setSessionCreateTime(session == null ? null : session.getCreateTime());
        if (markAccess) {
            entity.setLastAccessedAt(new Date());
        }
        String prepareType = scoreDetail == null || scoreDetail.getPrepareType() == null ? null : scoreDetail.getPrepareType().getCode();
        entity.setPrepareType(prepareType);
        if (scoreDetail != null && scoreDetail.getProvince() != null) {
            entity.setProvinceCode(scoreDetail.getProvince().getCode());
            entity.setProvinceName(scoreDetail.getProvince().getName());
        }
        entity.setExamYear(scoreDetail == null ? null : scoreDetail.getExamYear());
        entity.setEnabled(DataFreshnessSchedulePolicy.isBackgroundEligible(prepareType, entity.getSessionStatus()));
        String sourceDataHash = syncFreshnessState ? blankToNull(freshness == null ? null : freshness.getSourceDataHash()) : null;
        if (syncFreshnessState && Strings.isNullOrEmpty(sourceDataHash)) {
            sourceDataHash = blankToNull(volunteerSourceDataSyncService.loadLocalSourceDataHash(chatSessionId));
        }
        entity.setSourceDataHash(sourceDataHash);
        if (syncFreshnessState) {
            entity.setLatestSourceDataHash(blankToNull(freshness == null ? null : freshness.getLatestSourceDataHash()));
            entity.setLastCheckedAt(parseDate(freshness == null ? null : freshness.getLastCheckedAt()));
            String lastCheckSource = blankToNull(freshness == null ? null : freshness.getLastCheckSource());
            if (Strings.isNullOrEmpty(lastCheckSource)) {
                lastCheckSource = blankToNull(freshness == null ? null : freshness.getCheckSource());
            }
            entity.setLastCheckSource(lastCheckSource);
            String lastCheckStatus = blankToNull(freshness == null ? null : freshness.getLastCheckStatus());
            if (Strings.isNullOrEmpty(lastCheckStatus)) {
                lastCheckStatus = blankToNull(freshness == null ? null : freshness.getStatusCode());
            }
            entity.setLastCheckStatus(lastCheckStatus);
            entity.setFailCount(freshness == null ? null : freshness.getFailCount());
            entity.setLastError(blankToNull(freshness == null ? null : freshness.getLastError()));
            entity.setLastFailedAt(parseDate(freshness == null ? null : freshness.getLastFailedAt()));
        }
        return entity;
    }

    private DataFreshnessStateDTO mergeScheduleDataFreshnessState(Long tenantId, PlanningStateDTO state) {
        DataFreshnessStateDTO base = state == null ? null : state.getDataFreshnessState();
        DataFreshnessStateDTO merged = cloneDataFreshnessState(base);
        Long chatSessionId = state == null ? null : state.getSessionId();
        if (chatSessionId == null) {
            return merged;
        }
        PlanningDataFreshnessScheduleEntity schedule = planningDataFreshnessScheduleSharedService.getByChatSessionId(chatSessionId);
        if (schedule == null) {
            return merged;
        }
        applyScheduleToFreshnessState(merged, schedule);
        backfillRecentDataFreshnessChangeFromOperationLog(state, merged);
        return merged;
    }

    private void backfillRecentDataFreshnessChangeFromOperationLog(PlanningStateDTO state, DataFreshnessStateDTO target) {
        if (state == null || target == null || hasRecentDataFreshnessChangeSummary(target)) {
            return;
        }
        if ("changed".equals(target.getStatusCode()) || state.getOperationLogs() == null) {
            return;
        }
        for (int index = state.getOperationLogs().size() - 1; index >= 0; index--) {
            OperationLogDTO logItem = state.getOperationLogs().get(index);
            if (logItem == null || !"volunteer_data_change_detected".equals(logItem.getType())) {
                continue;
            }
            String detail = normalizeText(logItem.getDetail());
            if (Strings.isNullOrEmpty(detail)) {
                continue;
            }
            int addedCount = extractDataFreshnessLogCount(detail, "新增");
            int updatedCount = extractDataFreshnessLogCount(detail, "更新");
            int removedCount = extractDataFreshnessLogCount(detail, "失效");
            int changedCount = addedCount + updatedCount + removedCount;
            if (changedCount <= 0) {
                changedCount = defaultStringList(logItem.getVolunteerIds()).size();
            }
            target.setSummary(detail);
            target.setChangedCount(changedCount);
            target.setAddedCount(addedCount);
            target.setUpdatedCount(updatedCount);
            target.setRemovedCount(removedCount);
            target.setInvalidCount(removedCount);
            target.setAffectedVolunteerIds(defaultStringList(logItem.getVolunteerIds()));
            return;
        }
    }

    private int extractDataFreshnessLogCount(String detail, String label) {
        String normalized = normalizeText(detail);
        int labelIndex = normalized.indexOf(label);
        if (labelIndex < 0) {
            return 0;
        }
        int index = labelIndex + label.length();
        while (index < normalized.length() && Character.isWhitespace(normalized.charAt(index))) {
            index++;
        }
        int start = index;
        while (index < normalized.length() && Character.isDigit(normalized.charAt(index))) {
            index++;
        }
        if (start == index) {
            return 0;
        }
        try {
            return Integer.parseInt(normalized.substring(start, index));
        } catch (NumberFormatException ex) {
            return 0;
        }
    }

    private boolean isEmptyPlanningWorkspaceState(PlanningStateDTO state) {
        return state == null
                || (defaultCandidates(state.getCandidatePoolState() == null ? null : state.getCandidatePoolState().getItems()).isEmpty()
                && defaultDraftItems(state.getDraftPlanState() == null ? null : state.getDraftPlanState().getItems()).isEmpty()
                && defaultOrderedItems(state.getOrderedPlanState() == null ? null : state.getOrderedPlanState().getItems()).isEmpty());
    }

    private DataFreshnessStateDTO buildScheduleOnlyDataFreshnessState(PlanningDataFreshnessScheduleEntity schedule) {
        DataFreshnessStateDTO state = new DataFreshnessStateDTO();
        state.setStatusCode("current");
        state.setChangeLevel("none");
        state.setShouldNotify(false);
        state.setRequiresCandidateRefresh(false);
        state.setRequiresReview(false);
        if (schedule == null) {
            return state;
        }
        state.setPrepareType(schedule.getPrepareType());
        state.setProvince(schedule.getProvinceName());
        state.setExamYear(schedule.getExamYear() == null ? null : String.valueOf(schedule.getExamYear()));
        applyScheduleToFreshnessState(state, schedule);
        if (!Boolean.TRUE.equals(schedule.getEnabled())) {
            state.setSummary("当前会话暂不参与招生计划自动同步。");
        }
        return state;
    }

    private DataFreshnessStateDTO cloneDataFreshnessState(DataFreshnessStateDTO source) {
        if (source == null) {
            return new DataFreshnessStateDTO();
        }
        return JSONObject.parseObject(JSONObject.toJSONString(source), DataFreshnessStateDTO.class);
    }

    private void applyScheduleToFreshnessState(DataFreshnessStateDTO target, PlanningDataFreshnessScheduleEntity schedule) {
        if (target == null || schedule == null) {
            return;
        }
        if (!Strings.isNullOrEmpty(schedule.getPrepareType())) {
            target.setPrepareType(schedule.getPrepareType());
        }
        if (schedule.getExamYear() != null) {
            target.setExamYear(String.valueOf(schedule.getExamYear()));
        }
        if (!Strings.isNullOrEmpty(schedule.getProvinceName())) {
            target.setProvince(schedule.getProvinceName());
        }
        target.setLastCheckedAt(formatDate(schedule.getLastCheckedAt()));
        target.setNextCheckAt(formatDate(schedule.getNextCheckAt()));
        target.setCheckIntervalMinutes(schedule.getCheckIntervalMinutes());
        target.setLastCheckSource(schedule.getLastCheckSource());
        target.setCheckSource(schedule.getLastCheckSource());
        target.setLastCheckStatus(schedule.getLastCheckStatus());
        target.setSourceDataHash(schedule.getSourceDataHash());
        target.setLatestSourceDataHash(schedule.getLatestSourceDataHash());
        target.setFailCount(schedule.getFailCount());
        target.setLastError(schedule.getLastError());
        target.setLastFailedAt(formatDate(schedule.getLastFailedAt()));
        if ("changed".equals(schedule.getLastCheckStatus())) {
            if (hasDetailedDataFreshnessChange(target)) {
                return;
            }
            target.setStatusCode("changed");
            target.setChangeLevel("minor");
            target.setShouldNotify(true);
            target.setRequiresCandidateRefresh(true);
            target.setRequiresReview(false);
            if (Strings.isNullOrEmpty(target.getSummary())) {
                target.setSummary("检测到高途招生计划源数据有更新，建议点击检查更新确认影响范围，或刷新候选后继续填报。");
            }
            if (Strings.isNullOrEmpty(target.getDetail())) {
                target.setDetail("本次为后台轻量版本检查，尚未执行候选级影响分析。");
            }
        } else if ("failed".equals(schedule.getLastCheckStatus())) {
            target.setLastCheckStatus("failed");
            if (Strings.isNullOrEmpty(target.getSummary())) {
                target.setSummary("招生计划后台检查暂时失败，系统会继续重试。");
            }
        }
    }

    private boolean hasDetailedDataFreshnessChange(DataFreshnessStateDTO target) {
        return target != null
                && "changed".equals(target.getStatusCode())
                && !Strings.isNullOrEmpty(target.getChangeLevel())
                && !"none".equals(target.getChangeLevel());
    }

    private CreateSessionReq loadCreateSessionReq(Long chatSessionId) {
        ChatSessionExtraData scoreData = chatSessionExtraDataSharedService.getBySessionIdAndDataKey(
                chatSessionId, ChatSessionExtraDataConstants.USER_SCORE_KEY);
        if (scoreData == null || Strings.isNullOrEmpty(scoreData.getDataValue())) {
            return null;
        }
        try {
            return JSONObject.parseObject(scoreData.getDataValue(), CreateSessionReq.class);
        } catch (Exception ex) {
            log.warn("loadCreateSessionReq failed chatSessionId={}", chatSessionId, ex);
            return null;
        }
    }

    private Date parseDate(String value) {
        if (Strings.isNullOrEmpty(value)) {
            return null;
        }
        try {
            return Date.from(OffsetDateTime.parse(value).toInstant());
        } catch (Exception ignored) {
            return null;
        }
    }

    private String formatDate(Date date) {
        if (date == null) {
            return null;
        }
        return OffsetDateTime.ofInstant(date.toInstant(), ZoneId.systemDefault()).toString();
    }

    /**
     * 写路径落盘**统一入口**（H2）：带基线就 CAS，输的一方**不覆盖**（返回 false 由站点策略处置）。
     *
     * <p>语义（与 {@code H2-WRITE-CAS-PLAN.md} §3 一一对应）：</p>
     * <ul>
     *   <li>行不存在 → INSERT（首建；撞唯一键按 {@link #handleInsertRace} 处理，不再整文档覆盖赢家）；</li>
     *   <li>行是空壳（data_value IS NULL）且手里没有基线 → CAS 期望 null 补值（"只补缺"）；</li>
     *   <li>手里有基线 → {@code updateDataValueIfUnchanged(row, baseline, newValue)}：库里那行仍是
     *       手里这份快照才写，否则不写（输的一方由调用方决定 重读重放 / 重读合并 / 响亮冲突）；</li>
     *   <li>行里有别人的值、手里却没基线（不是这行的快照）→ 不写。</li>
     * </ul>
     *
     * <p>任何情况下都不再"拿内存整文档无条件 updateById 最新行"——那正是 D1⑧ 钉住的丢失并发写
     * 的形状。赢的一方把 {@code baselineDataValue} 刷成刚写进去的那串，后续写接着 CAS。</p>
     *
     * @return true=这次落盘成功（我们赢）；false=没落盘（基线过期/无基线且行里有别人的值），
     *         调用方必须按站点策略处置——绝不静默当成功
     */
    private boolean savePlanningState(Long chatSessionId, PlanningStateDTO state, String scene) {
        String dataValue = JSONObject.toJSONString(state);
        ChatSessionExtraData extraData = chatSessionExtraDataSharedService.getBySessionIdAndDataKey(
                chatSessionId, ChatSessionExtraDataConstants.PLANNING_STATE_KEY);
        if (extraData == null) {
            ChatSessionExtraData entity = new ChatSessionExtraData();
            entity.setChatSessionId(chatSessionId);
            entity.setDataKey(ChatSessionExtraDataConstants.PLANNING_STATE_KEY);
            entity.setDataType(DataType.JSON_OBJECT);
            entity.setDataVersion(0);
            entity.setDataValue(dataValue);
            try {
                chatSessionExtraDataSharedService.save(entity);
                state.setBaselineDataValue(dataValue);
                return true;
            } catch (DuplicateKeyException duplicate) {
                // 唯一键 `uk_chat_session_id_data_key_data_version` 是并发防线：空会话的**首次**读
                // 会先懒导入（legacy import）再落这一行，而同一时刻可能有多个首次读在跑
                // （页面自己的 workspace-state / candidate-pool/filter-options，以及测试的 inner 读）——
                // 它们都看到"没有行"，于是只有一个 INSERT 成功，其余拿 DuplicateKeyException，
                // 并让整个**读**接口回 `{"code":-1,"msg":"系统错误"}`（前端面板直接拿不到状态）。
                return handleInsertRace(chatSessionId, state, dataValue, scene, duplicate);
            }
        }
        String baselineDataValue = state.getBaselineDataValue();
        if (extraData.getDataValue() == null && baselineDataValue == null) {
            // 空壳行补值（历史行 data_value 为 NULL）：期望值 null → IS NULL 分支，同样是 CAS
            boolean filled = chatSessionExtraDataSharedService.updateDataValueIfUnchanged(extraData, null, dataValue);
            if (filled) {
                state.setBaselineDataValue(dataValue);
            } else {
                logWriteCasSkipped(chatSessionId, scene, "row_changed_under_us");
            }
            return filled;
        }
        if (baselineDataValue == null) {
            // 手里不是这行的快照（没 load 过/被 JSON 往返洗掉）：没有可比对的期望值 → 不写
            logWriteCasSkipped(chatSessionId, scene, "baseline_missing");
            return false;
        }
        boolean updated = chatSessionExtraDataSharedService.updateDataValueIfUnchanged(
                extraData, baselineDataValue, dataValue);
        if (updated) {
            state.setBaselineDataValue(dataValue);
        } else {
            logWriteCasSkipped(chatSessionId, scene, "row_changed_under_us");
        }
        return updated;
    }

    /**
     * INSERT 撞唯一键（并发首建）的收口：读回赢家，**只补空壳**，绝不整文档覆盖有内容的赢家。
     *
     * <p>与读路径 {@code persistImportedPlanningState} 的撞键分支同口径。输的一方返回 false，
     * 由站点策略重读重放/重读合并。</p>
     */
    private boolean handleInsertRace(Long chatSessionId,
                                     PlanningStateDTO state,
                                     String dataValue,
                                     String scene,
                                     DuplicateKeyException duplicate) {
        ChatSessionExtraData raced = chatSessionExtraDataSharedService.getBySessionIdAndDataKey(
                chatSessionId, ChatSessionExtraDataConstants.PLANNING_STATE_KEY);
        if (raced == null) {
            // 赢家写进去又没了：这种情况没有可写目标，原样抛出（原来是直接抛）。
            throw duplicate;
        }
        if (raced.getDataValue() == null) {
            boolean filled = chatSessionExtraDataSharedService.updateDataValueIfUnchanged(raced, null, dataValue);
            if (filled) {
                state.setBaselineDataValue(dataValue);
                return true;
            }
            logWriteCasSkipped(chatSessionId, scene, "row_changed_under_us");
            return false;
        }
        // 赢家已经有内容：另一条链路先落盘了。它的文档里有本轮没有的改动，整文档盖上去就是丢写。
        logWriteCasSkipped(chatSessionId, scene, "row_written_by_other");
        return false;
    }

    /**
     * 写路径 CAS 输/放弃的统一日志锚点——与读路径 {@code planningStateCasSave skipped} 同名前缀，
     * 便于按 anchor 计数（H2 观测 DoD）。
     */
    private void logWriteCasSkipped(Long chatSessionId, String scene, String reason) {
        if ("baseline_missing".equals(reason) || "row_written_by_other".equals(reason)) {
            log.warn("planningStateCasSave skipped chatSessionId={} scene={} reason={}", chatSessionId, scene, reason);
        } else {
            log.info("planningStateCasSave skipped chatSessionId={} scene={} reason={}", chatSessionId, scene, reason);
        }
    }

    /** 站点策略写死冲突重试上限（与读路径 overlay 的 3 次同口径）：够覆盖短暂竞争，又不无限重试。 */
    private static final int WRITE_CAS_ATTEMPTS = 3;

    /**
     * RETRY_REPLAY 站点的统一循环（H2 §3 策略一）：把纯内存变换施加到当前态 → CAS 落盘；
     * 输了重读最新行、把**同一变换**重新施加到最新态上再试（≤{@value #WRITE_CAS_ATTEMPTS} 次）。
     *
     * <p>约束：{@code mutation} 必须是纯内存且**幂等**的（只补空/按集合合并/整字段赋值）；带外部
     * 副作用（行为事件、Excel、上游拉取）的部分必须在循环外只做一次。变换在**每次尝试**都施加一遍，
     * 所以调用方不要预先施加（需要变换结果做副作用的例外，见各站点注释）。</p>
     *
     * @return true=落盘成功；false=重试耗尽仍未落盘（调用方决定 响亮冲突 or 放弃/降级）
     */
    private boolean saveWithReplay(Long chatSessionId,
                                   PlanningStateDTO state,
                                   String scene,
                                   Consumer<PlanningStateDTO> mutation) {
        for (int attempt = 0; attempt < WRITE_CAS_ATTEMPTS; attempt++) {
            mutation.accept(state);
            if (savePlanningState(chatSessionId, state, scene)) {
                return true;
            }
            reloadPlanningState(chatSessionId, state);
        }
        return false;
    }

    /** 写路径重试耗尽的响亮失败：沿用 CAS 冲突码 40901 的语义面（不新造错误码）。 */
    private BusinessException writeCasConflict(String scene) {
        return new BusinessException(PendingConfirmationBizService.CAS_CONFLICT_CODE,
                "规划状态已被其他操作更新，本次" + scene + "未生效，请重试");
    }

    private List<String> defaultList(List<String> values) {
        return values == null ? Lists.newArrayList() : values;
    }

    private int valueOrZero(Integer value) {
        return value == null ? 0 : value;
    }

    private List<String> collectOrderedVolunteerIds(PlanningStateDTO state) {
        if (state == null || state.getOrderedPlanState() == null || state.getOrderedPlanState().getItems() == null) {
            return Lists.newArrayList();
        }
        return state.getOrderedPlanState().getItems().stream()
                .filter(Objects::nonNull)
                .map(OrderedItemDTO::getVolunteerId)
                .filter(value -> !Strings.isNullOrEmpty(value))
                .collect(Collectors.toList());
    }

    private void appendPlanItemsBehaviorEvent(PlanningStateDTO state,
                                               Long tenantId,
                                               Long chatSessionId,
                                               String eventType,
                                               List<String> volunteerIds,
                                               boolean positiveFeedback,
                                               List<CandidateItemDTO> candidates) {
        appendPlanItemsBehaviorEvent(state, tenantId, chatSessionId, eventType, volunteerIds, positiveFeedback, candidates, null, null);
    }

    private void appendPlanItemsBehaviorEvent(PlanningStateDTO state,
                                               Long tenantId,
                                               Long chatSessionId,
                                               String eventType,
                                               List<String> volunteerIds,
                                               boolean positiveFeedback,
                                               List<CandidateItemDTO> candidates,
                                               Map<String, Integer> beforePositions,
                                               Map<String, Integer> afterPositions) {
        if (state == null || defaultList(volunteerIds).isEmpty()) {
            return;
        }
        PlanningBehaviorEventDTO event = new PlanningBehaviorEventDTO();
        event.setEventId(UUID.randomUUID().toString());
        event.setTenantId(tenantId);
        event.setChatSessionId(chatSessionId);
        event.setEventType(eventType);
        event.setMode(resolveBehaviorMode(state));
        event.setPlanVersion(resolveNextSavedPlanVersion(state));
        event.setGenerationMode(state.getOrderedPlanState() == null ? null : state.getOrderedPlanState().getGenerationMode());
        event.setVolunteerIds(Lists.newArrayList(defaultList(volunteerIds)));
        event.setFromPositions(new HashMap<String, Integer>(defaultIntegerMap(beforePositions)));
        event.setToPositions(new HashMap<String, Integer>(defaultIntegerMap(afterPositions)));
        fillPlanItemBehaviorContext(event, candidates, volunteerIds);
        event.setPositiveFeedback(positiveFeedback);
        setBehaviorEventPayload(event, buildPlanItemsPayload(state, event.getPlanVersion(), candidates, volunteerIds, beforePositions, afterPositions));
        event.setCreatedAt(OffsetDateTime.now().toString());
        recordBehaviorEvent(state, event);
    }

    private void appendUnitBehaviorEvent(PlanningStateDTO state,
                                         Long chatSessionId,
                                         String eventType,
                                         String unitId,
                                         List<OrderedItemDTO> items,
                                         List<CandidateItemDTO> candidates,
                                         Map<String, Integer> beforePositions,
                                         Map<String, Integer> afterPositions) {
        if (state == null || Strings.isNullOrEmpty(unitId)) {
            return;
        }
        PlanningBehaviorEventDTO event = new PlanningBehaviorEventDTO();
        event.setEventId(UUID.randomUUID().toString());
        event.setChatSessionId(chatSessionId);
        event.setEventType(eventType);
        event.setMode(resolveBehaviorMode(state));
        event.setPlanVersion(resolveNextSavedPlanVersion(state));
        event.setGenerationMode(state.getOrderedPlanState() == null ? null : state.getOrderedPlanState().getGenerationMode());
        event.setUnitIds(Lists.newArrayList(unitId));
        event.setVolunteerIds(defaultOrderedItems(items).stream()
                .map(OrderedItemDTO::getVolunteerId)
                .filter(value -> !Strings.isNullOrEmpty(value))
                .collect(Collectors.toList()));
        event.setFromPositions(new HashMap<String, Integer>(defaultIntegerMap(beforePositions)));
        event.setToPositions(new HashMap<String, Integer>(defaultIntegerMap(afterPositions)));
        fillPlanItemBehaviorContext(event, candidates, event.getVolunteerIds());
        event.setPositiveFeedback(false);
        setBehaviorEventPayload(event, buildUnitBehaviorPayload(state, event.getPlanVersion(), unitId, items, candidates, beforePositions, afterPositions));
        event.setCreatedAt(OffsetDateTime.now().toString());
        recordBehaviorEvent(state, event);
    }

    private void appendPlanSortApplyEvent(PlanningStateDTO state,
                                          Long chatSessionId,
                                          String sortField,
                                          Map<String, Integer> beforePositions,
                                          OrderedPlanStateDTO orderedPlanState,
                                          List<CandidateItemDTO> candidates) {
        if (state == null || orderedPlanState == null) {
            return;
        }
        PlanningBehaviorEventDTO event = new PlanningBehaviorEventDTO();
        event.setEventId(UUID.randomUUID().toString());
        event.setChatSessionId(chatSessionId);
        event.setEventType("plan_sort_apply");
        event.setMode(resolveBehaviorMode(state));
        event.setPlanVersion(resolveNextSavedPlanVersion(state));
        event.setGenerationMode(orderedPlanState.getGenerationMode());
        event.setSortKey(sortField);
        event.setVolunteerIds(collectOrderedVolunteerIds(state));
        event.setUnitIds(defaultOrderedUnits(orderedPlanState.getUnits()).stream()
                .map(OrderedUnitDTO::getUnitId)
                .filter(value -> !Strings.isNullOrEmpty(value))
                .collect(Collectors.toList()));
        event.setFromPositions(new HashMap<String, Integer>(beforePositions));
        event.setToPositions(buildOrderedPositionMap(orderedPlanState.getItems()));
        event.setPositiveFeedback(false);
        setBehaviorEventPayload(event, buildSortBehaviorPayload(state, event.getPlanVersion(), sortField, beforePositions, orderedPlanState, candidates));
        event.setCreatedAt(OffsetDateTime.now().toString());
        recordBehaviorEvent(state, event);
    }

    private PlanningBehaviorEventDTO findLatestExportBehaviorEvent(PlanningStateDTO state) {
        PlanningBehaviorEventDTO latest = null;
        if (planningBehaviorEventSharedService != null && state != null && state.getSessionId() != null) {
            latest = planningBehaviorEventSharedService.getLatestBySessionIdAndEventType(state.getSessionId(), "plan_export");
        }
        return latest;
    }

    private PlanningBehaviorEventDTO buildBehaviorEvent(PlanningStateDTO state,
                                                        Long tenantId,
                                                        Long chatSessionId,
                                                        String eventType,
                                                        List<String> volunteerIds,
                                                        boolean positiveFeedback) {
        if (state == null) {
            return null;
        }
        PlanningBehaviorEventDTO event = new PlanningBehaviorEventDTO();
        event.setEventId(UUID.randomUUID().toString());
        event.setTenantId(tenantId);
        event.setChatSessionId(chatSessionId);
        event.setEventType(eventType);
        event.setMode(resolveBehaviorMode(state));
        event.setPlanVersion(state.getVersion());
        event.setGenerationMode(state.getOrderedPlanState() == null ? null : state.getOrderedPlanState().getGenerationMode());
        event.setVolunteerIds(Lists.newArrayList(defaultList(volunteerIds)));
        event.setPositiveFeedback(positiveFeedback);
        setBehaviorEventPayload(event, buildExportBehaviorPayload(state, event.getPlanVersion(), volunteerIds));
        event.setCreatedAt(OffsetDateTime.now().toString());
        return event;
    }

    private String resolveBehaviorMode(PlanningStateDTO state) {
        if (state == null || state.getCandidatePoolState() == null || Strings.isNullOrEmpty(state.getCandidatePoolState().getVolunteerModel())) {
            return null;
        }
        return state.getCandidatePoolState().getVolunteerModel();
    }

    private void fillPlanItemBehaviorContext(PlanningBehaviorEventDTO event,
                                             List<CandidateItemDTO> candidates,
                                             List<String> volunteerIds) {
        if (event == null) {
            return;
        }
        CandidateItemDTO candidate = findFirstCandidate(candidates, volunteerIds);
        if (candidate == null) {
            return;
        }
        event.setTier(candidate.getTier());
        event.setAdmissionRatio(candidate.getAdmissionRatio());
        event.setSchoolName(candidate.getSchoolName());
        event.setMajorName(candidate.getMajorName());
    }

    private CandidateItemDTO findFirstCandidate(List<CandidateItemDTO> candidates, List<String> volunteerIds) {
        for (String volunteerId : defaultList(volunteerIds)) {
            CandidateItemDTO candidate = findCandidate(candidates, volunteerId);
            if (candidate != null) {
                return candidate;
            }
        }
        return null;
    }

    private Map<String, Object> buildPlanItemsPayload(PlanningStateDTO state,
                                                      Integer planVersion,
                                                      List<CandidateItemDTO> candidates,
                                                      List<String> volunteerIds,
                                                      Map<String, Integer> beforePositions,
                                                      Map<String, Integer> afterPositions) {
        Map<String, Object> payload = buildBaseBehaviorPayload(state, "plan_item", planVersion);
        payload.put("volunteerIds", defaultList(volunteerIds));
        payload.put("beforePositions", defaultIntegerMap(beforePositions));
        payload.put("afterPositions", defaultIntegerMap(afterPositions));
        payload.put("items", summarizeCandidatesForPayload(candidates, volunteerIds));
        return payload;
    }

    private Map<String, Object> buildUnitBehaviorPayload(PlanningStateDTO state,
                                                         Integer planVersion,
                                                         String unitId,
                                                         List<OrderedItemDTO> items,
                                                         List<CandidateItemDTO> candidates,
                                                         Map<String, Integer> beforePositions,
                                                         Map<String, Integer> afterPositions) {
        Map<String, Object> payload = buildBaseBehaviorPayload(state, "plan_unit", planVersion);
        payload.put("unitId", unitId);
        payload.put("volunteerIds", defaultOrderedItems(items).stream()
                .map(OrderedItemDTO::getVolunteerId)
                .filter(value -> !Strings.isNullOrEmpty(value))
                .collect(Collectors.toList()));
        payload.put("beforePositions", defaultIntegerMap(beforePositions));
        payload.put("afterPositions", defaultIntegerMap(afterPositions));
        payload.put("items", summarizeOrderedItemsForPayload(state, items, candidates));
        return payload;
    }

    private Map<String, Object> buildSortBehaviorPayload(PlanningStateDTO state,
                                                         Integer planVersion,
                                                         String sortField,
                                                         Map<String, Integer> beforePositions,
                                                         OrderedPlanStateDTO orderedPlanState,
                                                         List<CandidateItemDTO> candidates) {
        Map<String, Object> payload = buildBaseBehaviorPayload(state, "plan_sort", planVersion);
        payload.put("sortField", sortField);
        payload.put("beforePositions", beforePositions);
        payload.put("afterPositions", buildOrderedPositionMap(orderedPlanState == null ? null : orderedPlanState.getItems()));
        payload.put("items", summarizeOrderedItemsForPayload(state, orderedPlanState == null ? null : orderedPlanState.getItems(), candidates));
        return payload;
    }

    private Map<String, Object> buildExportBehaviorPayload(PlanningStateDTO state, Integer planVersion, List<String> volunteerIds) {
        Map<String, Object> payload = buildBaseBehaviorPayload(state, "plan_export", planVersion);
        payload.put("volunteerIds", defaultList(volunteerIds));
        payload.put("unitIds", defaultOrderedUnits(state == null || state.getOrderedPlanState() == null ? null : state.getOrderedPlanState().getUnits()).stream()
                .map(OrderedUnitDTO::getUnitId)
                .filter(value -> !Strings.isNullOrEmpty(value))
                .collect(Collectors.toList()));
        payload.put("items", summarizePlanItemsForPayload(state));
        return payload;
    }

    private Map<String, Object> buildBaseBehaviorPayload(PlanningStateDTO state, String source, Integer planVersion) {
        Map<String, Object> payload = new LinkedHashMap<String, Object>();
        payload.put("source", source);
        payload.put("mode", resolveBehaviorMode(state));
        payload.put("planVersion", planVersion);
        payload.put("requiredCount", state == null || state.getCandidatePoolState() == null
                ? null
                : state.getCandidatePoolState().getRequiredCount());
        payload.put("requiredUnitCount", state == null || state.getCandidatePoolState() == null
                ? null
                : state.getCandidatePoolState().getRequiredUnitCount());
        return payload;
    }

    private List<Map<String, Object>> summarizeCandidatesForPayload(List<CandidateItemDTO> candidates,
                                                                    List<String> volunteerIds) {
        List<Map<String, Object>> summary = Lists.newArrayList();
        for (String volunteerId : defaultList(volunteerIds)) {
            CandidateItemDTO candidate = findCandidate(candidates, volunteerId);
            if (candidate == null) {
                continue;
            }
            summary.add(summarizeCandidateForPayload(candidate));
        }
        return summary;
    }

    private List<Map<String, Object>> summarizePlanItemsForPayload(PlanningStateDTO state) {
        if (state == null || state.getOrderedPlanState() == null) {
            return Lists.newArrayList();
        }
        List<CandidateItemDTO> candidates = resolveEffectiveCandidates(null, state.getSessionId(), state, false);
        List<Map<String, Object>> summary = Lists.newArrayList();
        for (OrderedItemDTO item : defaultOrderedItems(state.getOrderedPlanState().getItems())) {
            CandidateItemDTO candidate = findCandidate(candidates, item.getVolunteerId());
            Map<String, Object> value = candidate == null
                    ? summarizeOrderedItemForPayload(item)
                    : summarizeCandidateForPayload(candidate);
            value.put("position", item.getPosition());
            value.put("orderedBy", item.getOrderedBy());
            value.put("orderReason", item.getOrderReason());
            summary.add(value);
        }
        return summary;
    }

    private List<Map<String, Object>> summarizeOrderedItemsForPayload(PlanningStateDTO state,
                                                                      List<OrderedItemDTO> items,
                                                                      List<CandidateItemDTO> candidates) {
        List<Map<String, Object>> summary = Lists.newArrayList();
        List<CandidateItemDTO> effectiveCandidates = candidates;
        if (effectiveCandidates == null && state != null) {
            effectiveCandidates = resolveEffectiveCandidates(null, state.getSessionId(), state, false);
        }
        CandidateResolver resolver = new CandidateResolver(effectiveCandidates);
        for (OrderedItemDTO item : defaultOrderedItems(items)) {
            summary.add(summarizeOrderedItemForPayload(item, resolver.resolve(item)));
        }
        return summary;
    }

    private Map<String, Object> summarizeOrderedItemForPayload(OrderedItemDTO item, CandidateItemDTO candidate) {
        Map<String, Object> value = candidate == null
                ? summarizeOrderedItemForPayload(item)
                : summarizeCandidateForPayload(candidate);
        if (item == null) {
            return value;
        }
        value.put("position", item.getPosition());
        value.put("orderedBy", item.getOrderedBy());
        value.put("orderReason", item.getOrderReason());
        return value;
    }

    private Map<String, Object> summarizeOrderedItemForPayload(OrderedItemDTO item) {
        Map<String, Object> value = new LinkedHashMap<String, Object>();
        if (item == null) {
            return value;
        }
        value.put("volunteerId", item.getVolunteerId());
        value.put("position", item.getPosition());
        value.put("tier", item.getTier());
        value.put("schoolName", item.getSchoolName());
        value.put("majorName", item.getMajorName());
        value.put("orderedBy", item.getOrderedBy());
        value.put("orderReason", item.getOrderReason());
        return value;
    }

    private Map<String, Object> summarizeCandidateForPayload(CandidateItemDTO candidate) {
        Map<String, Object> item = new LinkedHashMap<String, Object>();
        item.put("volunteerId", candidate.getVolunteerId());
        item.put("planSchoolDataId", candidate.getPlanSchoolDataId());
        item.put("schoolId", candidate.getSchoolId());
        item.put("schoolName", candidate.getSchoolName());
        item.put("schoolRank", candidate.getSchoolRank());
        item.put("provinceName", candidate.getProvinceName());
        item.put("cityName", candidate.getCityName());
        item.put("majorId", candidate.getMajorId());
        item.put("majorName", candidate.getMajorName());
        item.put("majorCode", candidate.getMajorCode());
        item.put("tier", candidate.getTier());
        item.put("admissionRatio", candidate.getAdmissionRatio());
        item.put("schoolEnrollRatio", candidate.getSchoolEnrollRatio());
        item.put("finalScore", candidate.getFinalScore());
        item.put("preferred", candidate.getPreferred());
        return item;
    }

    private void setBehaviorEventPayload(PlanningBehaviorEventDTO event, Map<String, Object> payload) {
        String payloadJson = JSONObject.toJSONString(payload == null ? new LinkedHashMap<String, Object>() : payload);
        event.setEventPayloadJson(payloadJson);
        event.setSnapshotDigest(buildPayloadDigest(payloadJson));
    }

    private Map<String, Integer> defaultIntegerMap(Map<String, Integer> values) {
        return values == null ? new HashMap<String, Integer>() : values;
    }

    private String buildPayloadDigest(String payloadJson) {
        if (payloadJson == null) {
            return null;
        }
        try {
            MessageDigest messageDigest = MessageDigest.getInstance("SHA-256");
            byte[] digest = messageDigest.digest(payloadJson.getBytes(StandardCharsets.UTF_8));
            StringBuilder builder = new StringBuilder();
            for (int i = 0; i < digest.length && i < 16; i++) {
                builder.append(String.format("%02x", digest[i]));
            }
            return builder.toString();
        } catch (Exception ex) {
            log.warn("build behavior payload digest failed", ex);
            return String.valueOf(payloadJson.hashCode());
        }
    }

    private Integer resolveNextSavedPlanVersion(PlanningStateDTO state) {
        int currentVersion = state == null || state.getVersion() == null ? 0 : state.getVersion();
        return currentVersion + 1;
    }

    private void recordBehaviorEvent(PlanningStateDTO state, PlanningBehaviorEventDTO event) {
        if (state == null || event == null) {
            return;
        }
        persistBehaviorEvent(event);
    }

    private void persistBehaviorEvent(PlanningBehaviorEventDTO event) {
        if (event == null || planningBehaviorEventSharedService == null) {
            return;
        }
        try {
            planningBehaviorEventSharedService.saveBehaviorEvent(event);
        } catch (Exception ex) {
            log.warn("persistBehaviorEvent failed eventType={} chatSessionId={} eventId={}",
                    event.getEventType(), event.getChatSessionId(), event.getEventId(), ex);
        }
    }

    private void backfillLegacyProfileState(Long chatSessionId, PlanningStateDTO state) {
        if (state == null || state.getProfileState() == null) {
            return;
        }
        if (isProfileStateEmpty(state.getProfileState())) {
            CreateSessionReq scoreDetail = loadScoreDetail(chatSessionId);
            UserProfileData userProfileData = loadUserProfileData(chatSessionId);
            hydrateProfileState(state.getProfileState(), scoreDetail, userProfileData);
            return;
        }
        repairPlaceholderStrengthSubjects(chatSessionId, state);
    }

    /**
     * 修复 explicitProfile.strengthSubjects 里的 '??' 占位（历史 legacy 导入把中文写坏）：
     * 整个列表都是占位（或混有占位）时，用当前成绩行里的名称替换——实测 10041972 修复后
     * workspace-state / 学生摘要读数从 ["??"] 变成 ["物理","化学"]。
     *
     * <p>只在内存态修复，不落盘：读路径不主动写（评审 §六 的方向），修复后的值会随下一次
     * 明确写点自然持久化。</p>
     */
    private void repairPlaceholderStrengthSubjects(Long chatSessionId, PlanningStateDTO state) {
        ExplicitProfileDTO explicitProfile = state.getProfileState().getExplicitProfile();
        if (explicitProfile == null || explicitProfile.getStrengthSubjects() == null
                || explicitProfile.getStrengthSubjects().isEmpty()) {
            return;
        }
        boolean hasPlaceholder = explicitProfile.getStrengthSubjects().stream()
                .anyMatch(PlanningStateService::isPlaceholderOnly);
        if (!hasPlaceholder) {
            return;
        }
        List<String> resolved = resolveStrengthSubjects(state, loadScoreDetail(chatSessionId));
        if (resolved.isEmpty()) {
            return;
        }
        log.info("repairPlaceholderStrengthSubjects chatSessionId={} before={} after={}",
                chatSessionId, explicitProfile.getStrengthSubjects(), resolved);
        explicitProfile.setStrengthSubjects(resolved);
    }

    private CreateSessionReq loadScoreDetail(Long chatSessionId) {
        ChatSessionExtraData scoreData = chatSessionExtraDataSharedService
                .getBySessionIdAndDataKey(chatSessionId, ChatSessionExtraDataConstants.USER_SCORE_KEY);
        if (scoreData == null || Strings.isNullOrEmpty(scoreData.getDataValue())) {
            return null;
        }
        try {
            return JSONObject.parseObject(scoreData.getDataValue(), CreateSessionReq.class);
        } catch (Exception ex) {
            log.warn("loadScoreDetail failed, chatSessionId={}", chatSessionId, ex);
            return null;
        }
    }

    private UserProfileData loadUserProfileData(Long chatSessionId) {
        ChatSessionExtraData profileData = chatSessionExtraDataSharedService
                .getBySessionIdAndDataKey(chatSessionId, ChatSessionExtraDataConstants.USER_PROFILE_KEY);
        if (profileData == null || Strings.isNullOrEmpty(profileData.getDataValue())) {
            return null;
        }
        try {
            return JSONObject.parseObject(profileData.getDataValue(), UserProfileData.class);
        } catch (Exception ex) {
            log.warn("loadUserProfileData failed, chatSessionId={}", chatSessionId, ex);
            return null;
        }
    }

    private void hydrateProfileState(ProfileStateDTO profileState, CreateSessionReq scoreDetail, UserProfileData userProfileData) {
        if (profileState == null) {
            return;
        }
        hydrateExplicitProfile(profileState.getExplicitProfile(), scoreDetail, userProfileData);
        hydratePhysicalConstraints(profileState.getPhysicalConstraints(), scoreDetail);
    }

    private void hydrateExplicitProfile(ExplicitProfileDTO explicitProfile, CreateSessionReq scoreDetail, UserProfileData userProfileData) {
        if (explicitProfile == null) {
            return;
        }
        fillIfEmpty(explicitProfile.getPositiveMajors(), extractPositiveMajors(scoreDetail, userProfileData));
        fillIfEmpty(explicitProfile.getNegativeMajors(), extractNegativeMajors(scoreDetail, userProfileData));
        fillIfEmpty(explicitProfile.getPositiveSchools(), extractPositiveSchools(userProfileData));
        fillIfEmpty(explicitProfile.getNegativeSchools(), extractNegativeSchools(userProfileData));
        fillIfEmpty(explicitProfile.getPositiveRegions(), extractPositiveRegions(scoreDetail, userProfileData));
        fillIfEmpty(explicitProfile.getNegativeRegions(), extractNegativeRegions(userProfileData));
        fillIfEmpty(explicitProfile.getStrengthSubjects(), extractStrengthSubjects(scoreDetail, userProfileData));
    }

    private void hydratePhysicalConstraints(PhysicalConstraintsDTO physicalConstraints, CreateSessionReq scoreDetail) {
        if (physicalConstraints == null || scoreDetail == null) {
            return;
        }
        if (physicalConstraints.getVision() == null) {
            physicalConstraints.setVision(new PhysicalConstraintsDTO.VisionDTO());
        }
        if (scoreDetail.getVisionAbility() != null) {
            if (Strings.isNullOrEmpty(physicalConstraints.getVision().getLeft())) {
                physicalConstraints.getVision().setLeft(scoreDetail.getVisionAbility().getLeft());
            }
            if (Strings.isNullOrEmpty(physicalConstraints.getVision().getRight())) {
                physicalConstraints.getVision().setRight(scoreDetail.getVisionAbility().getRight());
            }
        }
        if (Strings.isNullOrEmpty(physicalConstraints.getHeight())) {
            physicalConstraints.setHeight(scoreDetail.getHeight());
        }
        fillIfEmpty(physicalConstraints.getColorVision(), extractColorVision(scoreDetail));
        fillIfEmpty(physicalConstraints.getSpecialLimits(), extractSpecialLimits(scoreDetail));
    }

    private List<String> extractPositiveMajors(CreateSessionReq scoreDetail, UserProfileData userProfileData) {
        List<String> values = Lists.newArrayList();
        if (scoreDetail != null && scoreDetail.getPreferredMajors() != null) {
            for (CreateSessionReq.PreferredMajor preferredMajor : scoreDetail.getPreferredMajors()) {
                if (preferredMajor != null && !Strings.isNullOrEmpty(preferredMajor.getMajorSubName())) {
                    values.add(preferredMajor.getMajorSubName());
                }
            }
        }
        if (values.isEmpty() && userProfileData != null && userProfileData.getMajor_intent() != null) {
            values.addAll(defaultList(userProfileData.getMajor_intent().getLevel2()));
            if (values.isEmpty()) {
                values.addAll(defaultList(userProfileData.getMajor_intent().getLevel3()));
            }
            if (values.isEmpty()) {
                values.addAll(defaultList(userProfileData.getMajor_intent().getLevel1()));
            }
        }
        return distinct(values);
    }

    private List<String> extractNegativeMajors(CreateSessionReq scoreDetail, UserProfileData userProfileData) {
        List<String> values = Lists.newArrayList();
        if (scoreDetail != null && scoreDetail.getUnacceptableMajors() != null) {
            for (CreateSessionReq.UnacceptableMajor unacceptableMajor : scoreDetail.getUnacceptableMajors()) {
                if (unacceptableMajor != null && !Strings.isNullOrEmpty(unacceptableMajor.getMajorName())) {
                    values.add(unacceptableMajor.getMajorName());
                }
            }
        }
        if (values.isEmpty() && userProfileData != null && userProfileData.getNegative_major_intent() != null) {
            values.addAll(defaultList(userProfileData.getNegative_major_intent().getLevel2()));
            if (values.isEmpty()) {
                values.addAll(defaultList(userProfileData.getNegative_major_intent().getLevel3()));
            }
            if (values.isEmpty()) {
                values.addAll(defaultList(userProfileData.getNegative_major_intent().getLevel1()));
            }
        }
        return distinct(values);
    }

    private List<String> extractPositiveSchools(UserProfileData userProfileData) {
        if (userProfileData == null || userProfileData.getCollege_info() == null) {
            return Lists.newArrayList();
        }
        return distinct(defaultList(userProfileData.getCollege_info().getValues()));
    }

    private List<String> extractNegativeSchools(UserProfileData userProfileData) {
        if (userProfileData == null || userProfileData.getNegative_college_info() == null) {
            return Lists.newArrayList();
        }
        return distinct(defaultList(userProfileData.getNegative_college_info().getValues()));
    }

    private List<String> extractPositiveRegions(CreateSessionReq scoreDetail, UserProfileData userProfileData) {
        List<String> values = Lists.newArrayList();
        if (scoreDetail != null && scoreDetail.getPreferredRegions() != null) {
            for (CreateSessionReq.PreferredRegion preferredRegion : scoreDetail.getPreferredRegions()) {
                if (preferredRegion != null && !Strings.isNullOrEmpty(preferredRegion.getProvinceName())) {
                    values.add(preferredRegion.getProvinceName());
                }
            }
        }
        if (values.isEmpty() && userProfileData != null && userProfileData.getCity_info() != null) {
            values.addAll(defaultList(userProfileData.getCity_info().getProvince()));
        }
        return distinct(values);
    }

    private List<String> extractNegativeRegions(UserProfileData userProfileData) {
        if (userProfileData == null || userProfileData.getNegative_city_info() == null) {
            return Lists.newArrayList();
        }
        return distinct(defaultList(userProfileData.getNegative_city_info().getProvince()));
    }

    private List<String> extractStrengthSubjects(CreateSessionReq scoreDetail, UserProfileData userProfileData) {
        List<String> values = Lists.newArrayList();
        if (scoreDetail != null) {
            // 名字是 '??' 占位时不要原样入库（历史坏数据的来源），按选科码回查后只存可用名称。
            values.addAll(extractStrengthSubjectNames(scoreDetail.getStrengthSubjectList(), scoreDetail));
        }
        if (values.isEmpty() && userProfileData != null && userProfileData.getStrength_subject_info() != null) {
            values.addAll(defaultList(userProfileData.getStrength_subject_info().getValues()));
        }
        return values.stream()
                .filter(PlanningStateService::isUsableName)
                .distinct()
                .collect(Collectors.toList());
    }

    private List<String> extractColorVision(CreateSessionReq scoreDetail) {
        List<String> values = Lists.newArrayList();
        if (scoreDetail == null) {
            return values;
        }
        if (scoreDetail.getColorSituation() != null) {
            for (String colorVision : scoreDetail.getColorSituation()) {
                if (!Strings.isNullOrEmpty(colorVision)) {
                    values.add(colorVision);
                }
            }
        }
        if (values.isEmpty() && Boolean.TRUE.equals(scoreDetail.getColorBlindness())) {
            values.add("色盲色弱");
        }
        return distinct(values);
    }

    private List<String> extractSpecialLimits(CreateSessionReq scoreDetail) {
        List<String> values = Lists.newArrayList();
        if (scoreDetail == null) {
            return values;
        }
        if (Boolean.TRUE.equals(scoreDetail.getSpecialPlan())) {
            values.add("专项计划");
        }
        if (Boolean.TRUE.equals(scoreDetail.getMinority())) {
            values.add("少数民族");
        }
        if (Boolean.FALSE.equals(scoreDetail.getAcceptForeignSchool())) {
            values.add("不接受中外合作");
        }
        return values;
    }

    private void fillIfEmpty(List<String> target, List<String> source) {
        if (target == null || source == null || source.isEmpty() || !target.isEmpty()) {
            return;
        }
        target.addAll(source);
    }

    private List<String> distinct(List<String> values) {
        if (values == null || values.isEmpty()) {
            return Lists.newArrayList();
        }
        return values.stream()
                .filter(value -> !Strings.isNullOrEmpty(value))
                .distinct()
                .collect(Collectors.toList());
    }

    private boolean isProfileStateEmpty(ProfileStateDTO profileState) {
        if (profileState == null) {
            return true;
        }
        ExplicitProfileDTO explicitProfile = profileState.getExplicitProfile();
        PhysicalConstraintsDTO physicalConstraints = profileState.getPhysicalConstraints();
        return (explicitProfile == null || allListsEmpty(
                explicitProfile.getPositiveMajors(),
                explicitProfile.getNegativeMajors(),
                explicitProfile.getPositiveSchools(),
                explicitProfile.getNegativeSchools(),
                explicitProfile.getPositiveRegions(),
                explicitProfile.getNegativeRegions(),
                explicitProfile.getStrengthSubjects()))
                && (physicalConstraints == null || (Strings.isNullOrEmpty(physicalConstraints.getHeight())
                && (physicalConstraints.getVision() == null
                || (Strings.isNullOrEmpty(physicalConstraints.getVision().getLeft())
                && Strings.isNullOrEmpty(physicalConstraints.getVision().getRight())))
                && allListsEmpty(physicalConstraints.getColorVision(), physicalConstraints.getSpecialLimits())));
    }

    @SafeVarargs
    private final boolean allListsEmpty(List<String>... lists) {
        if (lists == null || lists.length == 0) {
            return true;
        }
        for (List<String> list : lists) {
            if (list != null && !list.isEmpty()) {
                return false;
            }
        }
        return true;
    }

    private void backfillLegacySummaryFields(PlanningStateDTO state) {
        if (state == null || state.getCandidatePoolState() == null || state.getOrderedPlanState() == null
                || state.getOrderedPlanState().getSummary() == null) {
            return;
        }
        Integer requiredCount = state.getCandidatePoolState().getRequiredCount();
        if ((requiredCount == null || requiredCount <= 0) && state.getCandidatePoolState().getRequiredTierCounts() != null) {
            int tierSum = state.getCandidatePoolState().getRequiredTierCounts().values().stream()
                    .filter(value -> value != null && value > 0)
                    .mapToInt(Integer::intValue)
                    .sum();
            if (tierSum > 0) {
                requiredCount = tierSum;
                state.getCandidatePoolState().setRequiredCount(requiredCount);
            }
        }
        if ((state.getOrderedPlanState().getSummary().getTargetCount() == null
                || state.getOrderedPlanState().getSummary().getTargetCount() <= 0)
                && requiredCount != null && requiredCount > 0) {
            state.getOrderedPlanState().getSummary().setTargetCount(requiredCount);
        }
    }

    private DerivedPreferencesDTO buildDerivedPreferences(ProfileStateDTO profileState) {
        DerivedPreferencesDTO derived = new DerivedPreferencesDTO();
        if (profileState == null || profileState.getLatentProfile() == null) {
            return derived;
        }
        LatentProfileDTO latent = profileState.getLatentProfile();
        if (latent.getFutureDevelopment() != null) {
            if (latent.getFutureDevelopment().getIndustryPreferences() != null) {
                derived.getRecommendedMajorClusters().addAll(latent.getFutureDevelopment().getIndustryPreferences());
            }
            if (latent.getFutureDevelopment().getCareerTypes() != null) {
                derived.getEmploymentOrientationInferred().addAll(latent.getFutureDevelopment().getCareerTypes());
            }
        }
        if (latent.getInterestPersonality() != null && latent.getInterestPersonality().getSubjectInterests() != null) {
            derived.getRecommendedMajorClusters().addAll(latent.getInterestPersonality().getSubjectInterests());
        }
        if (latent.getFamilyContext() != null) {
            derived.setTuitionFlexibilityInferred(latent.getFamilyContext().getTuitionTolerance());
        }
        derived.setRiskToleranceInferred("medium");
        derived.setRecommendedMajorClusters(derived.getRecommendedMajorClusters().stream().distinct().collect(Collectors.toList()));
        derived.setEmploymentOrientationInferred(derived.getEmploymentOrientationInferred().stream().distinct().collect(Collectors.toList()));
        return derived;
    }

    /** 逐条候选成形（冲刺/稳妥/保底三段共用）。**包内可见**，只读预览复用同一份。 */
    List<CandidateItemDTO> flattenCandidates(List<VolunteerRecommendListResponse.VolunteerSchool> schools, String tier) {
        List<CandidateItemDTO> items = Lists.newArrayList();
        if (schools == null) {
            return items;
        }
        for (VolunteerRecommendListResponse.VolunteerSchool school : schools) {
            if (school.getMajors() == null || school.getMajors().isEmpty()) {
                CandidateItemDTO item = new CandidateItemDTO();
                item.setVolunteerId(safeId(school.getPlanSchoolDataId(), school.getSchoolId(), school.getSchool_name()));
                item.setTier(tier);
                fillSchoolFields(item, school);
                item.setAdmissionRatio(parseDouble(school.getEnroll_ratio()));
                item.setRankInTier(school.getRank_in_tier());
                item.setBaseScore(extractDouble(school.getAlgTagMap(), "college_score_new"));
                item.setIntentScore(extractDouble(school.getAlgTagMap(), "major_score"));
                item.setFinalScore(extractDouble(school.getAlgTagMap(), "volunteer_score"));
                if (item.getFinalScore() == null) {
                    item.setFinalScore(rankToScore(school.getRank_in_tier()));
                }
                item.setReasonCodes(defaultList(school.getRankTagList()));
                item.setRiskFlags(extractRiskFlags(school.getAlgTagMap()));
                item.setHotIndex(extractDouble(school.getAlgTagMap(), "hot_index"));
                item.setSalaryAvg(extractDouble(school.getAlgTagMap(), "salary_avg"));
                items.add(item);
                continue;
            }
            for (VolunteerRecommendListResponse.VolunteerMajor major : school.getMajors()) {
                CandidateItemDTO item = new CandidateItemDTO();
                item.setVolunteerId(legacyMajorVolunteerId(school, major));
                item.setTier(tier);
                fillSchoolFields(item, school);
                item.setMajorId(major.getMajorId());
                item.setMajorName(major.getMajor_name());
                item.setMajorCode(major.getMajorUnitCode());
                item.setMajorCategoryId(major.getCategoryId());
                item.setMajorSubCategoryId(major.getSubCategoryId());
                item.setMajorLevel(major.getLevel());
                item.setMajorTier(major.getLevel());
                item.setPlanNum(major.getPlanNum());
                item.setDuration(major.getDuration());
                item.setTuitionPerYear(parseMoney(major.getPlanMoney()));
                item.setAdmissionRatio(parseDouble(major.getEnroll_ratio()));
                item.setRankInTier(school.getRank_in_tier());
                item.setBaseScore(extractDouble(school.getAlgTagMap(), "college_score_new"));
                item.setIntentScore(extractDouble(major.getAlgTagMap(), "major_score_new"));
                item.setFinalScore(extractDouble(school.getAlgTagMap(), "volunteer_score"));
                if (item.getFinalScore() == null) {
                    item.setFinalScore(rankToScore(school.getRank_in_tier()));
                }
                item.setMustSubjects(defaultList(major.getMust_subject()));
                item.setHotIndex(extractDouble(major.getAlgTagMap(), "hot_index"));
                item.setSalaryAvg(extractDouble(major.getAlgTagMap(), "salary_avg"));
                item.setMajorRankTags(defaultList(major.getRankTagList()));
                item.setMajorPlanTags(defaultList(major.getPlanTagList()));
                item.setMajorHistoryScores(convertHistoryScores(major.getHistory_score_list()));
                item.setReasonCodes(mergeReasons(school.getRankTagList(), school.getBasicTagList(), school.getPopTagList(),
                        major.getRankTagList(), major.getPlanTagList()));
                item.setRiskFlags(extractRiskFlags(school.getAlgTagMap(), major.getAlgTagMap()));
                items.add(item);
            }
        }
        return items;
    }

    private boolean shouldRefreshRecommendationOverlay(PlanningStateDTO state) {
        if (state == null || state.getStaleFlags() == null) {
            return false;
        }
        if (Boolean.TRUE.equals(state.getStaleFlags().getRecommendationOverlay())) {
            return true;
        }
        RecommendationOverlayStateDTO overlayState = state.getRecommendationOverlayState();
        return overlayState == null || overlayState.getItems() == null || overlayState.getItems().isEmpty();
    }

    private void refreshRecommendationOverlay(Long tenantId, Long chatSessionId, PlanningStateDTO state) {
        if (!canRefreshRecommendationOverlay(chatSessionId)) {
            return;
        }
        VolunteerRecommendListResponse response = volunteerBizService.recommendVolunteerList(tenantId, chatSessionId, false, false);
        CandidatePoolStateDTO overlayCandidatePoolState = new CandidatePoolStateDTO();
        overlayCandidatePoolState.setVolunteerModel(response != null && response.getBaseData() != null
                && response.getBaseData().getVolunteerModel() != null
                ? response.getBaseData().getVolunteerModel().getCode()
                : (state.getCandidatePoolState() == null ? null : state.getCandidatePoolState().getVolunteerModel()));
        List<CandidateItemDTO> items = Lists.newArrayList();
        if (response != null) {
            items.addAll(flattenCandidates(response.getSprints(), "冲"));
            items.addAll(flattenCandidates(response.getSafes(), "稳"));
            items.addAll(flattenCandidates(response.getProtects(), "保"));
        }
        overlayCandidatePoolState.setItems(enrichCandidateMajorTaxonomyFields(
                normalizeCandidateIdentities(overlayCandidatePoolState, items)));
        persistRecommendationOverlay(chatSessionId, state, overlayCandidatePoolState);
    }

    /**
     * 推荐 overlay 刷新前的**前置条件**：建会话第 2-3 步写入的"填报数量"
     * （{@code userScoreDetail.volunteerCount}，见 {@code ChatSessionBizService#enrichVolunteerCountAndModel}）。
     *
     * <p>推荐流水线里 {@code VolunteerDataProvider#calculateTargetSchoolCount} 会直接解引用它，
     * 老会话/只做过 legacy 导入、还没补录成绩的草稿会话没有这个字段（实测 74B stub 成绩行），
     * 以前这里必然 NPE → {@code GlobalExceptionHandler} 回 {@code code -1"系统错误"}
     * （实测 10041966 的 14:05-14:13 七次调用全挂；NPE 栈：
     * {@code generateInitialPlan:2087 → refreshRecommendationOverlay → recommendVolunteerList →
     * prepareVolunteerData → calculateTargetSchoolCount}）。</p>
     *
     * <p>overlay 只是缓存：缺前置条件就跳过，stale 标记留着，等成绩补齐（补录）后下次读/自举再刷
     * ——自愈，且不再把"系统错误"暴露给前端。</p>
     */
    private boolean canRefreshRecommendationOverlay(Long chatSessionId) {
        CreateSessionReq scoreDetail = loadScoreDetail(chatSessionId);
        if (scoreDetail == null || scoreDetail.getVolunteerCount() == null) {
            log.warn("Skip recommendation overlay refresh chatSessionId={} reason=volunteer_count_missing",
                    chatSessionId);
            return false;
        }
        return true;
    }

    /**
     * overlay 落盘：**合并非覆盖 + CAS**。
     *
     * <p>流水线要跑几百毫秒（读志愿源数据、过滤、排序），期间页面自举/确认链可能已经把这行改新
     * （草案、排序、version 都动了）。原来拿手里那份旧快照整文档 {@code savePlanningState} 回去，
     * 就是"旧快照覆盖新行"——2026-10-07 并发压测实测抓到：{@code phase=ordered/draft=132} 的行被
     * 打回 {@code candidate_generated/draft=0}（与评审 §六 同型的覆盖指纹）。</p>
     *
     * <p>这里改成：落盘前重读最新行，把 overlay 合并进**最新那份**再 CAS 写回——草案/排序/版本
     * 以最新为准，只加 overlay、清 stale 标记；CAS 连输 {@value #RECOMMENDATION_OVERLAY_PERSIST_ATTEMPTS}
     * 次就放弃落盘，但内存态仍然带上刚算出的 overlay（本请求看到的候选是新的，只是不持久化——
     * 下一次读/自举会再刷）。</p>
     */
    private void persistRecommendationOverlay(Long chatSessionId,
                                              PlanningStateDTO state,
                                              CandidatePoolStateDTO overlayCandidatePoolState) {
        for (int attempt = 0; attempt < RECOMMENDATION_OVERLAY_PERSIST_ATTEMPTS; attempt++) {
            ChatSessionExtraData row = chatSessionExtraDataSharedService.getBySessionIdAndDataKey(
                    chatSessionId, ChatSessionExtraDataConstants.PLANNING_STATE_KEY);
            if (row == null || row.getDataValue() == null) {
                // 行不存在（与"首建"竞态）：按内存态整文档落盘（savePlanningState 的首建 INSERT 语义，
                // 撞键时读回赢家、只在空壳行上补值 —— 见 handleInsertRace）
                applyRecommendationOverlay(state, overlayCandidatePoolState, state.getVersion());
                savePlanningState(chatSessionId, state, "recommendation_overlay_first_write");
                return;
            }
            PlanningStateDTO latest = JSONObject.parseObject(row.getDataValue(), PlanningStateDTO.class);
            normalizePlanningStateDefaults(chatSessionId, latest);
            applyRecommendationOverlay(latest, overlayCandidatePoolState, latest.getVersion());
            String newDataValue = JSONObject.toJSONString(latest);
            if (chatSessionExtraDataSharedService.updateDataValueIfUnchanged(
                    row, row.getDataValue(), newDataValue)) {
                // 调用方继续用最新内容（后续 saveWorkingPlanState 等才会带上并发写进来的草案/排序），
                // 基线也要刷成"实际写进库里的那串"：latest 是 JSON 反解的，baseline 字段是 null，
                // copyProperties 会把它带过来 —— 不补这一手，调用方随后落盘会因"基线缺失"静默跳过。
                BeanUtils.copyProperties(latest, state);
                state.setBaselineDataValue(newDataValue);
                return;
            }
        }
        log.warn("recommendationOverlayPersist skipped chatSessionId={} reason=state_kept_changing", chatSessionId);
        applyRecommendationOverlay(state, overlayCandidatePoolState, state.getVersion());
    }

    private void applyRecommendationOverlay(PlanningStateDTO target,
                                            CandidatePoolStateDTO overlayCandidatePoolState,
                                            Integer baseVersion) {
        target.setRecommendationOverlayState(buildRecommendationOverlayState(overlayCandidatePoolState, baseVersion));
        if (target.getStaleFlags() == null) {
            target.setStaleFlags(new StaleFlagsDTO());
        }
        target.getStaleFlags().setRecommendationOverlay(false);
    }

    private void refreshRecommendationOverlayBestEffort(Long tenantId,
                                                        Long chatSessionId,
                                                        PlanningStateDTO state,
                                                        String scene) {
        if (!shouldRefreshRecommendationOverlay(state)) {
            return;
        }
        try {
            refreshRecommendationOverlay(tenantId, chatSessionId, state);
        } catch (Exception e) {
            log.warn("Skip recommendation overlay refresh for {}: chatSessionId={}", scene, chatSessionId, e);
        }
    }

    private List<CandidateItemDTO> resolveEffectiveCandidates(Long tenantId,
                                                              Long chatSessionId,
                                                              PlanningStateDTO state,
                                                              boolean refreshOverlayIfNeeded) {
        if (refreshOverlayIfNeeded && tenantId != null && shouldRefreshRecommendationOverlay(state)) {
            refreshRecommendationOverlay(tenantId, chatSessionId, state);
        }
        List<CandidateItemDTO> candidates = resolveCandidateFactsForProposalAnalysis(state);
        return applyConfirmedPlanRequirements(candidates, chatSessionId, state);
    }

    private List<CandidateItemDTO> resolveCandidateFactsForProposalAnalysis(PlanningStateDTO state) {
        if (state == null || state.getCandidatePoolState() == null) {
            return Lists.newArrayList();
        }
        CandidatePoolStateDTO candidatePoolState = state.getCandidatePoolState();
        return enrichCandidateMajorTaxonomyFields(normalizeCandidateIdentities(
                candidatePoolState,
                mergeOverlayIntoCandidates(
                        candidatePoolState.getItems(),
                        state.getRecommendationOverlayState(),
                        state)));
    }

    private List<CandidateItemDTO> mergeOverlayIntoCandidates(List<CandidateItemDTO> candidates,
                                                              RecommendationOverlayStateDTO overlayState) {
        return mergeOverlayIntoCandidates(candidates, overlayState, null);
    }

    private List<CandidateItemDTO> mergeOverlayIntoCandidates(List<CandidateItemDTO> candidates,
                                                              RecommendationOverlayStateDTO overlayState,
                                                              PlanningStateDTO state) {
        List<CandidateItemDTO> source = candidates == null ? Lists.newArrayList() : candidates;
        if (overlayState == null || overlayState.getItems() == null || overlayState.getItems().isEmpty()) {
            return applyFutureDevelopmentScores(source, state);
        }
        Map<String, RecommendationOverlayStateDTO.Item> overlayMap = overlayState.getItems().stream()
                .filter(item -> !Strings.isNullOrEmpty(item.getVolunteerId()))
                .collect(Collectors.toMap(RecommendationOverlayStateDTO.Item::getVolunteerId, item -> item, (left, right) -> right));

        List<CandidateItemDTO> merged = Lists.newArrayListWithCapacity(source.size());
        for (CandidateItemDTO candidate : source) {
            CandidateItemDTO item = cloneCandidateItem(candidate);
            RecommendationOverlayStateDTO.Item overlay = overlayMap.get(candidate.getVolunteerId());
            if (overlay != null) {
                item.setBaseScore(overlay.getBaseScore());
                item.setIntentScore(overlay.getIntentScore());
                item.setFinalScore(overlay.getFinalScore());
                item.setRankInTier(overlay.getRankInTier());
                item.setPreferred(overlay.getPreferred());
                if (overlay.getReasonCodes() != null && !overlay.getReasonCodes().isEmpty()) {
                    item.setReasonCodes(defaultList(overlay.getReasonCodes()));
                }
                if (overlay.getSchoolRankTags() != null && !overlay.getSchoolRankTags().isEmpty()) {
                    item.setSchoolRankTags(defaultList(overlay.getSchoolRankTags()));
                }
                if (overlay.getMajorRankTags() != null && !overlay.getMajorRankTags().isEmpty()) {
                    item.setMajorRankTags(defaultList(overlay.getMajorRankTags()));
                }
            }
            merged.add(item);
        }
        return applyFutureDevelopmentScores(merged, state);
    }

    private List<CandidateItemDTO> applyConfirmedPlanRequirements(List<CandidateItemDTO> candidates,
                                                                  Long chatSessionId,
                                                                  PlanningStateDTO state) {
        List<CandidateItemDTO> source = candidates == null ? Lists.newArrayList() : candidates;
        boolean hasHardConstraints = RepairCandidateEligibility.hasConfirmedHardConstraints(state);
        CreateSessionReq.TuitionRange tuitionRange = loadSessionTuitionRange(chatSessionId);
        if (!hasHardConstraints && !hasActiveTuitionRange(tuitionRange)) {
            return source;
        }
        return source.stream()
                .filter(candidate -> !hasHardConstraints
                        || RepairCandidateEligibility.isEligibleForConfirmedHardConstraints(candidate, state))
                .filter(candidate -> isEligibleForTuitionRange(candidate, tuitionRange))
                .collect(Collectors.toList());
    }

    private CreateSessionReq.TuitionRange loadSessionTuitionRange(Long chatSessionId) {
        if (chatSessionId == null) {
            return null;
        }
        ChatSessionExtraData userScoreData = chatSessionExtraDataSharedService.getBySessionIdAndDataKey(
                chatSessionId,
                ChatSessionExtraDataConstants.USER_SCORE_KEY);
        if (userScoreData == null || Strings.isNullOrEmpty(userScoreData.getDataValue())) {
            return null;
        }
        try {
            CreateSessionReq scoreDetail = JSONObject.parseObject(userScoreData.getDataValue(), CreateSessionReq.class);
            return scoreDetail == null ? null : scoreDetail.getTuitionRange();
        } catch (Exception e) {
            log.warn("Skip session tuition range for planning effective candidates: chatSessionId={}", chatSessionId, e);
            return null;
        }
    }

    private boolean hasActiveTuitionRange(CreateSessionReq.TuitionRange tuitionRange) {
        if (tuitionRange == null) {
            return false;
        }
        Integer min = tuitionRange.getMin();
        Integer max = tuitionRange.getMax();
        return (min != null && min > 0) || (max != null && max > 0);
    }

    private boolean isEligibleForTuitionRange(CandidateItemDTO candidate,
                                              CreateSessionReq.TuitionRange tuitionRange) {
        if (!hasActiveTuitionRange(tuitionRange) || candidate == null) {
            return true;
        }
        Integer tuition = candidate.getTuitionPerYear();
        if (tuition == null || tuition <= 0) {
            return true;
        }
        Integer min = tuitionRange.getMin();
        Integer max = tuitionRange.getMax();
        return (min == null || min <= 0 || tuition >= min)
                && (max == null || max <= 0 || tuition <= max);
    }

    private void syncWorkingPlanWithEffectiveCandidatesForConfirmedRequirements(PlanningStateDTO state,
                                                                                List<CandidateItemDTO> effectiveCandidates) {
        if (state == null
                || state.getDraftPlanState() == null
                || !hasConfirmedPlanRequirements(state)) {
            return;
        }
        DraftPlanStateDTO draft = state.getDraftPlanState();
        syncWorkingPlanItemsWithLatestCandidates(draft, new CandidateResolver(effectiveCandidates));
        syncWorkingPlanUnitsWithItems(draft, effectiveCandidates, state.getCandidatePoolState());
        recalculateWorkingPlanSummary(draft, state.getCandidatePoolState());
    }

    private void syncOrderedPlanWithEffectiveCandidatesForConfirmedRequirements(PlanningStateDTO state,
                                                                                List<CandidateItemDTO> effectiveCandidates) {
        if (state == null
                || state.getOrderedPlanState() == null
                || !hasConfirmedPlanRequirements(state)) {
            return;
        }
        OrderedPlanStateDTO orderedPlanState = state.getOrderedPlanState();
        syncOrderedPlanItemsWithLatestCandidates(orderedPlanState, new CandidateResolver(effectiveCandidates));
        orderedPlanState.setUnits(buildOrderedUnitsFromOrderedItems(
                orderedPlanState.getItems(), state.getDraftPlanState(), effectiveCandidates));
    }

    private boolean hasConfirmedPlanRequirements(PlanningStateDTO state) {
        return RepairCandidateEligibility.hasConfirmedHardConstraints(state)
                || !CoverageRequirementSupport.confirmedRequirements(state).isEmpty()
                || !PriorityRuleSupport.confirmedRules(state).isEmpty()
                || TierAllocationSupport.confirmedGoal(state) != null
                || hasActiveTuitionRange(loadSessionTuitionRange(state == null ? null : state.getSessionId()));
    }

    private List<CandidateItemDTO> applyFutureDevelopmentScores(List<CandidateItemDTO> candidates,
                                                                PlanningStateDTO state) {
        List<CandidateItemDTO> source = candidates == null ? Lists.newArrayList() : candidates;
        FutureDevelopmentSignals signals = buildFutureDevelopmentSignals(state);
        if (!signals.enabled) {
            for (CandidateItemDTO candidate : source) {
                if (candidate != null) {
                    candidate.setFutureDevelopmentScore(0D);
                }
            }
            return source;
        }
        for (CandidateItemDTO candidate : source) {
            if (candidate != null) {
                candidate.setFutureDevelopmentScore(calculateFutureDevelopmentScore(candidate, signals));
            }
        }
        return source;
    }

    private FutureDevelopmentSignals buildFutureDevelopmentSignals(PlanningStateDTO state) {
        FutureDevelopmentSignals signals = new FutureDevelopmentSignals();
        if (state == null) {
            return signals;
        }
        DerivedPreferencesDTO derivedPreferences = buildDerivedPreferences(state.getProfileState());
        List<String> orientations = derivedPreferences == null ? Lists.newArrayList()
                : defaultList(derivedPreferences.getEmploymentOrientationInferred());
        if (orientations.stream().anyMatch(value -> containsIgnoreCase(value, "体制内") || containsIgnoreCase(value, "考公"))) {
            signals.enabled = true;
            signals.publicSectorBias = true;
            signals.stabilityBias = true;
        }
        return signals;
    }

    private double calculateFutureDevelopmentScore(CandidateItemDTO item,
                                                   FutureDevelopmentSignals signals) {
        if (item == null || signals == null || !signals.enabled) {
            return 0D;
        }
        double score = 0D;
        if (signals.publicSectorBias) {
            if (matchesSchoolNature(item, "公办")) {
                score += 2.5D;
            }
            if (matchesSchoolLevel(item, "本科")) {
                score += 1.4D;
            }
            if (matchesSchoolCategory(item, "师范", "政法", "财经", "农林", "医药")) {
                score += 1.3D;
            }
            if (matchesMajorDirection(item, "法学", "汉语言", "中国语言", "思想政治", "教育", "师范", "行政管理", "公共管理", "政治学", "马克思")) {
                score += 1.6D;
            }
            if (matchesSchoolNature(item, "民办")) {
                score -= 1.8D;
            }
            if (matchesSchoolTags(item, "中外合作")) {
                score -= 1.5D;
            }
        }
        if (signals.stabilityBias) {
            if (item.getTuitionPerYear() != null && item.getTuitionPerYear() >= 30000) {
                score -= 1.2D;
            } else if (item.getTuitionPerYear() != null && item.getTuitionPerYear() >= 20000) {
                score -= 0.6D;
            }
        }
        return score;
    }

    private boolean matchesSchoolNature(CandidateItemDTO item, String keyword) {
        return containsIgnoreCase(item == null ? null : item.getSchoolNature(), keyword)
                || matchesSchoolTags(item, keyword);
    }

    private boolean matchesSchoolLevel(CandidateItemDTO item, String keyword) {
        return containsIgnoreCase(item == null ? null : item.getSchoolLevel(), keyword)
                || matchesSchoolTags(item, keyword);
    }

    private boolean matchesSchoolCategory(CandidateItemDTO item, String... keywords) {
        if (item == null) {
            return false;
        }
        if (containsAny(item.getSchoolCategory(), keywords)) {
            return true;
        }
        for (String keyword : keywords) {
            if (matchesSchoolTags(item, keyword)) {
                return true;
            }
        }
        return false;
    }

    private boolean matchesMajorDirection(CandidateItemDTO item, String... keywords) {
        if (item == null) {
            return false;
        }
        return containsAny(item.getMajorName(), keywords)
                || containsAny(item.getMajorCategory(), keywords)
                || containsAny(item.getMajorDiscipline(), keywords)
                || matchesMajorTags(item, keywords);
    }

    private boolean matchesSchoolTags(CandidateItemDTO item, String keyword) {
        return containsInList(item == null ? null : item.getSchoolBasicTags(), keyword)
                || containsInList(item == null ? null : item.getSchoolRankTags(), keyword)
                || containsInList(item == null ? null : item.getSchoolPopupTags(), keyword);
    }

    private boolean matchesMajorTags(CandidateItemDTO item, String... keywords) {
        for (String keyword : keywords) {
            if (containsInList(item == null ? null : item.getMajorRankTags(), keyword)
                    || containsInList(item == null ? null : item.getMajorPlanTags(), keyword)) {
                return true;
            }
        }
        return false;
    }

    private boolean containsInList(List<String> values, String keyword) {
        for (String value : defaultList(values)) {
            if (containsIgnoreCase(value, keyword)) {
                return true;
            }
        }
        return false;
    }

    private CandidateItemDTO cloneCandidateItem(CandidateItemDTO source) {
        CandidateItemDTO target = new CandidateItemDTO();
        target.setVolunteerId(source.getVolunteerId());
        target.setTier(source.getTier());
        target.setSubTier(source.getSubTier());
        target.setPlanSchoolDataId(source.getPlanSchoolDataId());
        target.setSchoolId(source.getSchoolId());
        target.setSchoolUnitCode(source.getSchoolUnitCode());
        target.setSchoolName(source.getSchoolName());
        target.setDisplaySchoolName(source.getDisplaySchoolName());
        target.setProvinceName(source.getProvinceName());
        target.setCityName(source.getCityName());
        // 区域 ID 与名字同源 ✓：clone 漏抄 ID 会让"ID 优先"在克隆过的候选上直接失效 ✗
        // （组模式初始单元的代表就是克隆来的 ✗ → 单元 `provinceId` 全为 null ✗）
        target.setProvinceId(source.getProvinceId());
        target.setCityId(source.getCityId());
        target.setSchoolBatch(source.getSchoolBatch());
        target.setSchoolLevel(source.getSchoolLevel());
        target.setSchoolNature(source.getSchoolNature());
        target.setSchoolCategory(source.getSchoolCategory());
        target.setSchoolRank(source.getSchoolRank());
        target.setSchoolEnrollRatio(source.getSchoolEnrollRatio());
        target.setBaoyanRatio(source.getBaoyanRatio());
        target.setUpgradeRatio(source.getUpgradeRatio());
        target.setMasterCount(source.getMasterCount());
        target.setDoctorCount(source.getDoctorCount());
        target.setPreferred(source.getPreferred());
        target.setMajorId(source.getMajorId());
        target.setMajorName(source.getMajorName());
        target.setMajorCode(source.getMajorCode());
        target.setMajorCategoryId(source.getMajorCategoryId());
        target.setMajorSubCategoryId(source.getMajorSubCategoryId());
        target.setMajorLevel(source.getMajorLevel());
        target.setMajorDiscipline(source.getMajorDiscipline());
        target.setMajorCategory(source.getMajorCategory());
        target.setMajorTier(source.getMajorTier());
        target.setPlanNum(source.getPlanNum());
        target.setDuration(source.getDuration());
        target.setTuitionPerYear(source.getTuitionPerYear());
        target.setBaseScore(source.getBaseScore());
        target.setIntentScore(source.getIntentScore());
        target.setFinalScore(source.getFinalScore());
        target.setFutureDevelopmentScore(source.getFutureDevelopmentScore());
        target.setAdmissionRatio(source.getAdmissionRatio());
        target.setRankInTier(source.getRankInTier());
        target.setHotIndex(source.getHotIndex());
        target.setSalaryAvg(source.getSalaryAvg());
        target.setMustSubjects(defaultList(source.getMustSubjects()));
        target.setReasonCodes(defaultList(source.getReasonCodes()));
        target.setRiskFlags(defaultList(source.getRiskFlags()));
        target.setSchoolRankTags(defaultList(source.getSchoolRankTags()));
        target.setSchoolBasicTags(defaultList(source.getSchoolBasicTags()));
        target.setSchoolPopupTags(defaultList(source.getSchoolPopupTags()));
        target.setMajorRankTags(defaultList(source.getMajorRankTags()));
        target.setMajorPlanTags(defaultList(source.getMajorPlanTags()));
        target.setSchoolHistoryScores(source.getSchoolHistoryScores() == null ? Lists.newArrayList() : Lists.newArrayList(source.getSchoolHistoryScores()));
        target.setMajorHistoryScores(source.getMajorHistoryScores() == null ? Lists.newArrayList() : Lists.newArrayList(source.getMajorHistoryScores()));
        return target;
    }

    private List<CandidateItemDTO> normalizeCandidateIdentities(CandidatePoolStateDTO candidatePoolState,
                                                                List<CandidateItemDTO> candidates) {
        if (!isMajorMode(candidatePoolState)) {
            return candidates;
        }
        List<CandidateItemDTO> normalized = Lists.newArrayListWithCapacity(candidates == null ? 0 : candidates.size());
        for (CandidateItemDTO candidate : defaultCandidates(candidates)) {
            String canonicalVolunteerId = canonicalMajorVolunteerId(candidate);
            if (Strings.isNullOrEmpty(canonicalVolunteerId)
                    || canonicalVolunteerId.equals(candidate.getVolunteerId())) {
                normalized.add(candidate);
                continue;
            }
            CandidateItemDTO copy = cloneCandidateItem(candidate);
            copy.setVolunteerId(canonicalVolunteerId);
            normalized.add(copy);
        }
        return normalized;
    }

    private String canonicalMajorVolunteerId(CandidateItemDTO candidate) {
        if (candidate == null
                || Strings.isNullOrEmpty(candidate.getPlanSchoolDataId())
                || Strings.isNullOrEmpty(candidate.getMajorId())) {
            return candidate == null ? null : candidate.getVolunteerId();
        }
        return candidate.getPlanSchoolDataId() + "_" + candidate.getMajorId();
    }

    private void fillSchoolFields(CandidateItemDTO item, VolunteerRecommendListResponse.VolunteerSchool school) {
        item.setPlanSchoolDataId(school.getPlanSchoolDataId());
        item.setSchoolId(school.getSchoolId());
        item.setSchoolUnitCode(school.getSchoolUnitCode());
        item.setSchoolName(school.getSchool_name());
        item.setDisplaySchoolName(resolveDisplaySchoolName(school));
        item.setProvinceName(school.getProvince_name());
        item.setCityName(school.getCity_name());
        // 名字旁边的 ID 一起抄 ✓（有 ID 才能"按 ID 相等"判同一个地区 ✓；缺 ID 时匹配走规范化名字兜底 ✓）
        item.setProvinceId(school.getProvince_id());
        item.setCityId(school.getCity_id());
        item.setSchoolBatch(school.getSchool_batch());
        item.setSchoolLevel(school.getSchool_level());
        item.setSchoolNature(school.getSchool_nature());
        item.setSchoolCategory(school.getSchool_category());
        item.setSchoolRank(school.getSchool_rank());
        item.setSchoolEnrollRatio(parseDouble(school.getEnroll_ratio()));
        item.setBaoyanRatio(school.getBaoyan_ratio());
        item.setUpgradeRatio(school.getUpgrade_ratio());
        item.setMasterCount(school.getMaster_count());
        item.setDoctorCount(school.getDoctor_count());
        item.setPreferred(Boolean.TRUE.equals(school.getIs_preferred()));
        item.setSchoolRankTags(defaultList(school.getRankTagList()));
        item.setSchoolBasicTags(defaultList(school.getBasicTagList()));
        item.setSchoolPopupTags(defaultList(school.getPopTagList()));
        item.setSchoolHistoryScores(convertHistoryScores(school.getHistory_score_list()));
    }

    private int countByTier(List<CandidateItemDTO> items, String tier) {
        return (int) items.stream().filter(item -> tier.equals(item.getTier())).count();
    }

    private int countCandidateUnits(List<CandidateItemDTO> items) {
        return (int) defaultCandidates(items).stream()
                .map(this::resolveInitialRecommendationUnitId)
                .filter(Objects::nonNull)
                .distinct()
                .count();
    }

    private int countCandidateUnitsByTier(List<CandidateItemDTO> items, String tier) {
        return (int) defaultCandidates(items).stream()
                .filter(item -> tier.equals(item.getTier()))
                .map(this::resolveInitialRecommendationUnitId)
                .filter(Objects::nonNull)
                .distinct()
                .count();
    }

    private boolean matchesTier(CandidateItemDTO item, CandidatePoolQueryReq req) {
        List<String> tiers = req.getFilters() != null ? req.getFilters().getTiers() : null;
        return tiers == null || tiers.isEmpty() || tiers.contains(item.getTier());
    }

    private boolean matchesProvince(CandidateItemDTO item, CandidatePoolQueryReq req) {
        List<String> provinces = req.getFilters() != null ? req.getFilters().getProvinceNames() : null;
        List<String> negativeProvinces = req.getFilters() != null ? req.getFilters().getNegativeProvinceNames() : null;
        boolean positiveMatched = provinces == null || provinces.isEmpty()
                || provinces.stream().anyMatch(p -> containsIgnoreCase(item.getProvinceName(), p));
        boolean negativeMatched = negativeProvinces != null && !negativeProvinces.isEmpty()
                && negativeProvinces.stream().anyMatch(p -> containsIgnoreCase(item.getProvinceName(), p));
        return positiveMatched && !negativeMatched;
    }

    private boolean matchesCity(CandidateItemDTO item, CandidatePoolQueryReq req) {
        List<String> cities = req.getFilters() != null ? req.getFilters().getCityNames() : null;
        List<String> negativeCities = req.getFilters() != null ? req.getFilters().getNegativeCityNames() : null;
        boolean positiveMatched = cities == null || cities.isEmpty()
                || cities.stream().anyMatch(city -> containsIgnoreCase(item.getCityName(), city));
        boolean negativeMatched = negativeCities != null && !negativeCities.isEmpty()
                && negativeCities.stream().anyMatch(city -> containsIgnoreCase(item.getCityName(), city));
        return positiveMatched && !negativeMatched;
    }

    private boolean matchesSchoolKeyword(CandidateItemDTO item, CandidatePoolQueryReq req) {
        List<String> keywords = req.getFilters() != null ? req.getFilters().getSchoolKeywords() : null;
        List<String> negativeKeywords = req.getFilters() != null ? req.getFilters().getNegativeSchoolKeywords() : null;
        boolean positiveMatched = keywords == null || keywords.isEmpty()
                || keywords.stream().anyMatch(k -> matchesSchoolKeywordValue(item, k));
        boolean negativeMatched = negativeKeywords != null && !negativeKeywords.isEmpty()
                && negativeKeywords.stream().anyMatch(k -> matchesSchoolKeywordValue(item, k));
        return positiveMatched && !negativeMatched;
    }

    private boolean matchesSchoolKeywordValue(CandidateItemDTO item, String keyword) {
        return containsIgnoreCase(resolveDisplaySchoolName(item), keyword)
                || containsIgnoreCase(item.getSchoolName(), keyword);
    }

    private String resolveDisplaySchoolName(CandidateItemDTO item) {
        if (item == null) {
            return null;
        }
        if (!Strings.isNullOrEmpty(item.getDisplaySchoolName())) {
            return item.getDisplaySchoolName();
        }
        if (schoolManager != null && !Strings.isNullOrEmpty(item.getSchoolId())) {
            SchoolVO schoolVO = schoolManager.getSchoolById(item.getSchoolId());
            if (schoolVO != null && !Strings.isNullOrEmpty(schoolVO.getSchoolName())) {
                return schoolVO.getSchoolName();
            }
        }
        return item.getSchoolName();
    }

    private String resolveDisplaySchoolName(VolunteerRecommendListResponse.VolunteerSchool school) {
        if (school == null) {
            return null;
        }
        if (schoolManager != null && !Strings.isNullOrEmpty(school.getSchoolId())) {
            SchoolVO schoolVO = schoolManager.getSchoolById(school.getSchoolId());
            if (schoolVO != null && !Strings.isNullOrEmpty(schoolVO.getSchoolName())) {
                return schoolVO.getSchoolName();
            }
        }
        return school.getSchool_name();
    }

    private boolean matchesMajorKeyword(CandidateItemDTO item, CandidatePoolQueryReq req) {
        List<String> keywords = req.getFilters() != null ? req.getFilters().getMajorKeywords() : null;
        List<String> negativeKeywords = req.getFilters() != null ? req.getFilters().getNegativeMajorKeywords() : null;
        boolean positiveMatched = keywords == null || keywords.isEmpty()
                || keywords.stream().anyMatch(k -> matchesMajorKeywordValue(item, k));
        boolean negativeMatched = negativeKeywords != null && !negativeKeywords.isEmpty()
                && negativeKeywords.stream().anyMatch(k -> matchesMajorKeywordValue(item, k));
        return positiveMatched && !negativeMatched;
    }

    private boolean matchesMajorKeywordValue(CandidateItemDTO item, String keyword) {
        return containsIgnoreCase(item.getMajorName(), keyword)
                || containsIgnoreCase(resolveMajorCategory(item), keyword)
                || containsIgnoreCase(resolveMajorDiscipline(item), keyword);
    }

    private boolean matchesSchoolTags(CandidateItemDTO item, CandidatePoolQueryReq req) {
        List<String> tags = req.getFilters() != null ? req.getFilters().getSchoolTags() : null;
        List<String> negativeTags = req.getFilters() != null ? req.getFilters().getNegativeSchoolTags() : null;
        List<String> sourceTags = collectSchoolFilterTags(item);
        List<String> normalizedPositiveTags = normalizeFilterValues(tags);
        List<String> normalizedNegativeTags = normalizeFilterValues(negativeTags);
        Set<String> normalizedSourceTags = new HashSet<String>(normalizeFilterValues(sourceTags));
        boolean positiveMatched = normalizedPositiveTags.isEmpty()
                || normalizedPositiveTags.stream().anyMatch(normalizedSourceTags::contains);
        boolean negativeMatched = !normalizedNegativeTags.isEmpty()
                && normalizedNegativeTags.stream().anyMatch(normalizedSourceTags::contains);
        return positiveMatched && !negativeMatched;
    }

    private boolean matchesMajorTags(CandidateItemDTO item, CandidatePoolQueryReq req) {
        List<String> tags = req.getFilters() != null ? req.getFilters().getMajorTags() : null;
        List<String> negativeTags = req.getFilters() != null ? req.getFilters().getNegativeMajorTags() : null;
        List<String> sourceTags = collectMajorFilterTags(item);
        List<String> normalizedPositiveTags = normalizeFilterValues(tags);
        List<String> normalizedNegativeTags = normalizeFilterValues(negativeTags);
        Set<String> normalizedSourceTags = new HashSet<String>(normalizeFilterValues(sourceTags));
        boolean positiveMatched = normalizedPositiveTags.isEmpty()
                || normalizedPositiveTags.stream().anyMatch(normalizedSourceTags::contains);
        boolean negativeMatched = !normalizedNegativeTags.isEmpty()
                && normalizedNegativeTags.stream().anyMatch(normalizedSourceTags::contains);
        return positiveMatched && !negativeMatched;
    }

    private Comparator<CandidateItemDTO> buildComparator(String field) {
        String sortField = Strings.isNullOrEmpty(field) ? "finalScore" : field;
        if ("admissionRatio".equalsIgnoreCase(sortField)) {
            return Comparator.comparing(item -> item.getSchoolEnrollRatio() == null ? 0D : item.getSchoolEnrollRatio());
        }
        if ("rankInTier".equalsIgnoreCase(sortField)) {
            return Comparator.comparing(item -> item.getRankInTier() == null ? Integer.MAX_VALUE : item.getRankInTier());
        }
        if ("tuitionPerYear".equalsIgnoreCase(sortField)) {
            return Comparator.comparing(item -> item.getTuitionPerYear() == null ? Integer.MAX_VALUE : item.getTuitionPerYear());
        }
        if ("hotIndex".equalsIgnoreCase(sortField)) {
            return Comparator.comparing(item -> item.getHotIndex() == null ? 0D : item.getHotIndex());
        }
        if ("salaryAvg".equalsIgnoreCase(sortField)) {
            return Comparator.comparing(item -> item.getSalaryAvg() == null ? 0D : item.getSalaryAvg());
        }
        if ("schoolRank".equalsIgnoreCase(sortField)) {
            return Comparator.comparing(item -> item.getSchoolRank() == null ? Integer.MAX_VALUE : item.getSchoolRank());
        }
        return Comparator.comparing(item -> item.getFinalScore() == null ? 0D : item.getFinalScore());
    }

    private List<String> collectSchoolFilterTags(CandidateItemDTO item) {
        List<String> tags = Lists.newArrayList();
        if (item == null) {
            return tags;
        }
        tags.addAll(defaultList(item.getSchoolBasicTags()));
        tags.addAll(defaultList(item.getSchoolRankTags()));
        tags.addAll(defaultList(item.getSchoolPopupTags()));
        tags.add(item.getSchoolBatch());
        tags.add(item.getSchoolNature());
        tags.add(item.getSchoolCategory());
        tags.add(item.getSchoolLevel());
        if (isCooperativeCandidate(item)) {
            tags.add(COOPERATIVE_SCHOOL_TAG);
        }
        return normalizeCandidateSchoolTags(item, tags);
    }

    private List<String> collectMajorFilterTags(CandidateItemDTO item) {
        List<String> tags = Lists.newArrayList();
        if (item == null) {
            return tags;
        }
        tags.add(resolveMajorDiscipline(item));
        tags.add(resolveMajorCategory(item));
        tags.addAll(defaultList(item.getMajorRankTags()));
        tags.addAll(defaultList(item.getMajorPlanTags()));
        tags.addAll(extractConstraintTags(item));
        if (isCooperativeCandidate(item)) {
            tags.add(COOPERATIVE_MAJOR_TAG);
        }
        return tags;
    }

    private boolean isCooperativeCandidate(CandidateItemDTO item) {
        if (item == null) {
            return false;
        }
        List<String> values = Lists.newArrayList();
        values.add(item.getSchoolName());
        values.add(item.getDisplaySchoolName());
        values.add(item.getSchoolNature());
        values.add(item.getSchoolCategory());
        values.add(item.getMajorName());
        values.addAll(defaultList(item.getSchoolBasicTags()));
        values.addAll(defaultList(item.getSchoolRankTags()));
        values.addAll(defaultList(item.getSchoolPopupTags()));
        values.addAll(defaultList(item.getMajorRankTags()));
        values.addAll(defaultList(item.getMajorPlanTags()));
        values.addAll(defaultList(item.getReasonCodes()));
        values.addAll(defaultList(item.getRiskFlags()));

        String joined = values.stream()
                .filter(value -> !Strings.isNullOrEmpty(value))
                .collect(Collectors.joining(" "));
        if (Strings.isNullOrEmpty(joined)) {
            return false;
        }
        if (containsAny(joined,
                COOPERATIVE_SCHOOL_TAG,
                COOPERATIVE_MAJOR_TAG,
                "\u5408\u4f5c\u529e\u5b66",
                "\u4e2d\u5916\u9ad8\u6c34\u5e73",
                "\u4e2d\u5916\u9ad8\u6c34\u5e73\u5927\u5b66\u5b66\u751f\u4ea4\u6d41\u8ba1\u5212",
                "\u5b66\u5206\u4e92\u8ba4",
                "\u6e2f\u6fb3\u53f0\u5730\u533a\u5408\u4f5c\u529e\u5b66")) {
            return true;
        }
        boolean hasForeignSignal = containsAny(joined,
                "\u5916\u65b9\u5927\u5b66",
                "\u5916\u65b9\u5b66\u6821",
                "\u5916\u65b9\u6559\u5b66",
                "\u56fd\u5916\u5927\u5b66",
                "\u5883\u5916\u5927\u5b66",
                "\u6fb3\u5143/\u5b66\u5e74",
                "\u6fb3\u5e01/\u5b66\u5e74");
        boolean hasCooperativeMode = containsAny(joined,
                "2+2",
                "3+1",
                "3+2",
                "4+0",
                "\u8054\u5408\u57f9\u517b",
                "\u53cc\u5b66\u4f4d");
        return hasForeignSignal && hasCooperativeMode;
    }

    private String resolveMajorDiscipline(CandidateItemDTO item) {
        if (item == null) {
            return null;
        }
        if (!Strings.isNullOrEmpty(item.getMajorDiscipline())) {
            return item.getMajorDiscipline();
        }
        MajorExtraDataVO extraData = resolveMajorExtraData(item);
        if (extraData != null && !Strings.isNullOrEmpty(extraData.getFirstCategory())) {
            item.setMajorDiscipline(extraData.getFirstCategory());
            return item.getMajorDiscipline();
        }
        return null;
    }

    private String resolveMajorCategory(CandidateItemDTO item) {
        if (item == null) {
            return null;
        }
        if (!Strings.isNullOrEmpty(item.getMajorCategory())) {
            return item.getMajorCategory();
        }
        MajorExtraDataVO extraData = resolveMajorExtraData(item);
        if (extraData != null && !Strings.isNullOrEmpty(extraData.getSecondCategory())) {
            item.setMajorCategory(extraData.getSecondCategory());
            return item.getMajorCategory();
        }
        return null;
    }

    private List<CandidateItemDTO> enrichCandidateMajorTaxonomyFields(List<CandidateItemDTO> candidates) {
        for (CandidateItemDTO item : defaultCandidates(candidates)) {
            resolveMajorDiscipline(item);
            resolveMajorCategory(item);
        }
        return candidates;
    }

    private MajorExtraDataVO resolveMajorExtraData(CandidateItemDTO item) {
        if (item == null || majorExtraDataManager == null) {
            return null;
        }
        Integer secondCategoryId = parseInteger(item.getMajorSubCategoryId());
        if (secondCategoryId != null) {
            MajorExtraDataVO extraData = majorExtraDataManager.getDetailBySecondCategoryId(secondCategoryId);
            if (extraData != null) {
                return extraData;
            }
        }
        if (!Strings.isNullOrEmpty(item.getMajorCategory())) {
            List<MajorExtraDataVO> categoryMatches = majorExtraDataManager.getBySecondCategory(item.getMajorCategory());
            if (!categoryMatches.isEmpty()) {
                return categoryMatches.get(0);
            }
        }
        return null;
    }

    private Integer parseInteger(String value) {
        if (Strings.isNullOrEmpty(value)) {
            return null;
        }
        try {
            return Integer.parseInt(value.trim());
        } catch (NumberFormatException ex) {
            return null;
        }
    }

    private List<CandidateFilterOptionsDTO.FilterGroupDTO> buildCandidateFilterGroups(List<String> provinceNames,
                                                                                      List<String> cityNames,
                                                                                      List<String> schoolKeywords,
                                                                                      List<String> schoolTags,
                                                                                      List<String> majorTags,
                                                                                      List<String> majorDisciplines,
                                                                                      List<String> majorCategories,
                                                                                      List<String> majorNameKeywords) {
        List<CandidateFilterOptionsDTO.FilterGroupDTO> groups = Lists.newArrayList();
        addFilterGroup(groups, "region.school_province", "院校省份", "provinceNames", provinceNames);
        addFilterGroup(groups, "region.school_city", "院校城市", "cityNames", cityNames);
        addKeywordFilterGroup(groups, "school.name", "院校名称", "schoolKeywords", schoolKeywords);
        addFilterGroup(groups, "school.category", "院校分类", "schoolTags", filterByWhitelist(schoolTags, SCHOOL_CATEGORY_TAGS));
        addFilterGroup(groups, "school.nature", "院校性质", "schoolTags", filterByWhitelist(schoolTags, SCHOOL_NATURE_TAGS));
        addFilterGroup(groups, "school.feature", "院校特色", "schoolTags", filterByWhitelist(schoolTags, SCHOOL_FEATURE_TAGS));
        addFilterGroup(groups, "school.level", "院校层次", "schoolTags", filterByWhitelist(schoolTags, SCHOOL_LEVEL_TAGS));
        addFilterGroup(groups, "major.discipline", "专业门类", "majorTags", majorDisciplines);
        addFilterGroup(groups, "major.category", "专业大类", "majorKeywords", majorCategories);
        addKeywordFilterGroup(groups, "major.name", "专业名称", "majorKeywords", majorNameKeywords);
        addFilterGroup(groups, "admission.type", "招生类型", "majorTags", filterByWhitelist(majorTags, ADMISSION_TYPE_TAGS));
        addFilterGroup(groups, "constraint.limit", "限报要求", "majorTags", filterByWhitelist(majorTags, CONSTRAINT_LIMIT_TAGS));
        addFilterGroup(groups, "school.tag", "院校标签", "schoolTags",
                excludeValues(schoolTags, SCHOOL_CATEGORY_TAGS, SCHOOL_NATURE_TAGS, SCHOOL_FEATURE_TAGS, SCHOOL_LEVEL_TAGS));
        return groups;
    }

    private List<CandidateFilterOptionsDTO.RegionNodeDTO> buildCandidateRegionTree(List<CandidateItemDTO> items,
                                                                                   List<String> provinceNames,
                                                                                   List<String> cityNames) {
        Set<String> allowedProvinces = new HashSet<String>(defaultList(provinceNames));
        Set<String> allowedCities = new HashSet<String>(defaultList(cityNames));
        Map<String, Set<String>> provinceCities = new LinkedHashMap<String, Set<String>>();
        defaultList(provinceNames).stream()
                .filter(this::isEnumLikeFilterOption)
                .sorted()
                .forEach(province -> provinceCities.put(province, new LinkedHashSet<String>()));

        for (CandidateItemDTO item : items == null ? Lists.<CandidateItemDTO>newArrayList() : items) {
            String province = normalizeRegionOption(item.getProvinceName());
            String city = normalizeRegionOption(item.getCityName());
            if (Strings.isNullOrEmpty(province) || Strings.isNullOrEmpty(city)) {
                continue;
            }
            if (!allowedProvinces.contains(province) || !allowedCities.contains(city)) {
                continue;
            }
            provinceCities.computeIfAbsent(province, key -> new LinkedHashSet<String>()).add(city);
        }

        List<CandidateFilterOptionsDTO.RegionNodeDTO> result = Lists.newArrayList();
        for (Map.Entry<String, Set<String>> entry : provinceCities.entrySet()) {
            CandidateFilterOptionsDTO.RegionNodeDTO node = new CandidateFilterOptionsDTO.RegionNodeDTO();
            node.setProvinceName(entry.getKey());
            node.setCityNames(entry.getValue().stream().sorted().collect(Collectors.toList()));
            result.add(node);
        }
        return result;
    }

    private List<CandidateFilterOptionsDTO.MajorDisciplineNodeDTO> buildCandidateMajorTree(List<CandidateItemDTO> items) {
        Map<String, Map<String, Set<String>>> disciplineCategories = new LinkedHashMap<String, Map<String, Set<String>>>();
        for (CandidateItemDTO item : items == null ? Lists.<CandidateItemDTO>newArrayList() : items) {
            String discipline = normalizeKeywordFilterOption(resolveMajorDiscipline(item));
            String category = normalizeKeywordFilterOption(resolveMajorCategory(item));
            String majorName = normalizeMajorNameFilterOption(item.getMajorName());
            if (Strings.isNullOrEmpty(majorName)) {
                continue;
            }
            if (Strings.isNullOrEmpty(discipline)) {
                discipline = OTHER_MAJOR_FILTER_LABEL;
            }
            if (Strings.isNullOrEmpty(category)) {
                category = OTHER_MAJOR_FILTER_LABEL;
            }
            disciplineCategories
                    .computeIfAbsent(discipline, key -> new LinkedHashMap<String, Set<String>>())
                    .computeIfAbsent(category, key -> new LinkedHashSet<String>())
                    .add(majorName);
        }

        List<CandidateFilterOptionsDTO.MajorDisciplineNodeDTO> result = Lists.newArrayList();
        disciplineCategories.entrySet().stream()
                .sorted((left, right) -> compareFilterOptionWithOtherLast(left.getKey(), right.getKey()))
                .forEach(disciplineEntry -> {
                    CandidateFilterOptionsDTO.MajorDisciplineNodeDTO disciplineNode =
                            new CandidateFilterOptionsDTO.MajorDisciplineNodeDTO();
                    disciplineNode.setDisciplineName(disciplineEntry.getKey());
                    List<CandidateFilterOptionsDTO.MajorCategoryNodeDTO> categories = disciplineEntry.getValue().entrySet().stream()
                            .sorted((left, right) -> compareFilterOptionWithOtherLast(left.getKey(), right.getKey()))
                            .map(categoryEntry -> {
                                CandidateFilterOptionsDTO.MajorCategoryNodeDTO categoryNode =
                                        new CandidateFilterOptionsDTO.MajorCategoryNodeDTO();
                                categoryNode.setCategoryName(categoryEntry.getKey());
                                categoryNode.setMajorNames(categoryEntry.getValue().stream().sorted().collect(Collectors.toList()));
                                return categoryNode;
                            })
                            .collect(Collectors.toList());
                    disciplineNode.setCategories(categories);
                    result.add(disciplineNode);
                });
        return result;
    }

    private int compareFilterOptionWithOtherLast(String left, String right) {
        boolean leftOther = OTHER_MAJOR_FILTER_LABEL.equals(left);
        boolean rightOther = OTHER_MAJOR_FILTER_LABEL.equals(right);
        if (leftOther && !rightOther) {
            return 1;
        }
        if (!leftOther && rightOther) {
            return -1;
        }
        return String.valueOf(left).compareTo(String.valueOf(right));
    }

    private String normalizeRegionOption(String value) {
        if (Strings.isNullOrEmpty(value)) {
            return null;
        }
        String normalized = value.trim();
        return isEnumLikeFilterOption(normalized) ? normalized : null;
    }

    private void addFilterGroup(List<CandidateFilterOptionsDTO.FilterGroupDTO> groups,
                                String groupCode,
                                String groupName,
                                String filterField,
                                List<String> values) {
        List<String> normalizedValues = defaultList(values).stream()
                .filter(this::isEnumLikeFilterOption)
                .distinct()
                .sorted()
                .collect(Collectors.toList());
        if (normalizedValues.isEmpty()) {
            return;
        }
        CandidateFilterOptionsDTO.FilterGroupDTO group = new CandidateFilterOptionsDTO.FilterGroupDTO();
        group.setGroupCode(groupCode);
        group.setGroupName(groupName);
        group.setFilterField(filterField);
        group.setValues(normalizedValues);
        groups.add(group);
    }

    private void addKeywordFilterGroup(List<CandidateFilterOptionsDTO.FilterGroupDTO> groups,
                                       String groupCode,
                                       String groupName,
                                       String filterField,
                                       List<String> values) {
        List<String> normalizedValues = defaultList(values).stream()
                .map(this::normalizeKeywordFilterOption)
                .filter(Objects::nonNull)
                .distinct()
                .sorted()
                .collect(Collectors.toList());
        if (normalizedValues.isEmpty()) {
            return;
        }
        CandidateFilterOptionsDTO.FilterGroupDTO group = new CandidateFilterOptionsDTO.FilterGroupDTO();
        group.setGroupCode(groupCode);
        group.setGroupName(groupName);
        group.setFilterField(filterField);
        group.setValues(normalizedValues);
        groups.add(group);
    }

    private String normalizeMajorNameFilterOption(String value) {
        if (Strings.isNullOrEmpty(value)) {
            return null;
        }
        String normalized = value.trim();
        int halfParenIndex = normalized.indexOf('(');
        int fullParenIndex = normalized.indexOf('（');
        int parenIndex = -1;
        if (halfParenIndex >= 0 && fullParenIndex >= 0) {
            parenIndex = Math.min(halfParenIndex, fullParenIndex);
        } else if (halfParenIndex >= 0) {
            parenIndex = halfParenIndex;
        } else if (fullParenIndex >= 0) {
            parenIndex = fullParenIndex;
        }
        if (parenIndex > 0) {
            normalized = normalized.substring(0, parenIndex).trim();
        }
        return normalizeKeywordFilterOption(normalized);
    }

    private String normalizeKeywordFilterOption(String value) {
        if (Strings.isNullOrEmpty(value)) {
            return null;
        }
        String normalized = value.trim();
        if (normalized.isEmpty() || normalized.length() > 80) {
            return null;
        }
        return normalized;
    }

    private List<String> filterByWhitelist(List<String> source, Set<String> whitelist) {
        return defaultList(source).stream()
                .filter(whitelist::contains)
                .distinct()
                .collect(Collectors.toList());
    }

    @SafeVarargs
    private final List<String> excludeValues(List<String> source, Set<String>... excludedSets) {
        return defaultList(source).stream()
                .filter(value -> {
                    for (Set<String> excludedSet : excludedSets) {
                        if (excludedSet.contains(value)) {
                            return false;
                        }
                    }
                    return true;
                })
                .distinct()
                .collect(Collectors.toList());
    }

    private List<String> extractConstraintTags(CandidateItemDTO item) {
        List<String> values = Lists.newArrayList();
        if (item == null) {
            return values;
        }
        if (defaultList(item.getMajorPlanTags()).stream().anyMatch(tag -> containsAny(tag, "色盲", "色弱"))) {
            values.add("色盲色弱");
        }
        if (defaultList(item.getMustSubjects()).stream().anyMatch(tag -> containsAny(tag, "语种"))) {
            values.add("语种要求");
        }
        if (defaultList(item.getMustSubjects()).stream().anyMatch(tag -> containsAny(tag, "单科"))) {
            values.add("单科成绩");
        }
        if (defaultList(item.getMustSubjects()).stream().anyMatch(tag -> containsAny(tag, "性别"))) {
            values.add("性别要求");
        }
        return values;
    }

    private boolean isEnumLikeFilterOption(String value) {
        if (Strings.isNullOrEmpty(value)) {
            return false;
        }
        String normalized = value.trim();
        if (normalized.isEmpty()) {
            return false;
        }
        if (SCHOOL_LEVEL_TAGS.contains(normalized)
                || SCHOOL_FEATURE_TAGS.contains(normalized)
                || SCHOOL_NATURE_TAGS.contains(normalized)
                || SCHOOL_CATEGORY_TAGS.contains(normalized)
                || ADMISSION_TYPE_TAGS.contains(normalized)
                || CONSTRAINT_LIMIT_TAGS.contains(normalized)) {
            return true;
        }
        if (normalized.matches(".*\\d.*")) {
            return false;
        }
        return !normalized.matches(".*(率|排名|指数|分|位次|人数|计划|学费|硕士点|博士点|就业|薪资|保研|升学|年).*");
    }

    private List<String> normalizeFilterValues(List<String> values) {
        return defaultList(values).stream()
                .map(this::normalizeFilterValue)
                .filter(value -> !Strings.isNullOrEmpty(value))
                .distinct()
                .collect(Collectors.toList());
    }

    private String normalizeFilterValue(String value) {
        return Strings.isNullOrEmpty(value) ? null : value.trim().toLowerCase(Locale.ROOT);
    }

    private List<String> normalizeCandidateSchoolTags(CandidateItemDTO item, List<String> rawTags) {
        return defaultList(rawTags).stream()
                .map(value -> value == null ? null : value.trim())
                .filter(value -> !Strings.isNullOrEmpty(value))
                .filter(value -> !isGeoSchoolTag(item, value))
                .distinct()
                .collect(Collectors.toList());
    }

    private boolean isGeoSchoolTag(CandidateItemDTO item, String value) {
        if (item == null || Strings.isNullOrEmpty(value)) {
            return false;
        }
        String normalized = value.trim();
        if (MACRO_REGION_TAGS.contains(normalized)) {
            return true;
        }
        if (normalized.equals(item.getProvinceName()) || normalized.equals(item.getCityName())) {
            return true;
        }
        return normalized.matches(".*(省|市|自治区|特别行政区|自治州|地区|盟|新区|自治县|县)$");
    }

    private List<String> mergeReasons(List<String>... reasonLists) {
        List<String> merged = Lists.newArrayList();
        for (List<String> one : reasonLists) {
            if (one == null) {
                continue;
            }
            for (String tag : one) {
                if (!Strings.isNullOrEmpty(tag) && !merged.contains(tag)) {
                    merged.add(tag);
                }
            }
        }
        return merged;
    }

    private Double parseDouble(String value) {
        if (Strings.isNullOrEmpty(value)) {
            return null;
        }
        try {
            return Double.valueOf(value.replace("%", "").trim());
        } catch (Exception e) {
            log.debug("parseDouble failed: {}", value);
            return null;
        }
    }

    private Integer parseMoney(String value) {
        if (Strings.isNullOrEmpty(value)) {
            return null;
        }
        String digits = value.replaceAll("[^0-9]", "");
        if (Strings.isNullOrEmpty(digits)) {
            return null;
        }
        try {
            return Integer.valueOf(digits);
        } catch (Exception e) {
            log.debug("parseMoney failed: {}", value);
            return null;
        }
    }

    private List<String> extractRiskFlags(Map<String, Object>... algTagMaps) {
        List<String> riskFlags = Lists.newArrayList();
        for (Map<String, Object> algTagMap : algTagMaps) {
            if (algTagMap == null || algTagMap.isEmpty()) {
                continue;
            }
            for (Map.Entry<String, Object> entry : algTagMap.entrySet()) {
                if (entry.getValue() == null) {
                    continue;
                }
                riskFlags.add(entry.getKey() + ":" + String.valueOf(entry.getValue()));
            }
        }
        return riskFlags;
    }

    private Double extractDouble(Map<String, Object> algTagMap, String key) {
        if (algTagMap == null || algTagMap.isEmpty() || Strings.isNullOrEmpty(key)) {
            return null;
        }
        Object value = algTagMap.get(key);
        if (value == null) {
            return null;
        }
        try {
            return Double.valueOf(String.valueOf(value).replace("%", "").trim());
        } catch (Exception e) {
            log.debug("extractDouble failed: key={}, value={}", key, value);
            return null;
        }
    }

    private List<CandidateItemDTO.HistoryScoreItem> convertHistoryScores(List<VolunteerRecommendListResponse.HistoryScore> historyScores) {
        List<CandidateItemDTO.HistoryScoreItem> items = Lists.newArrayList();
        if (historyScores == null) {
            return items;
        }
        for (VolunteerRecommendListResponse.HistoryScore historyScore : historyScores) {
            if (historyScore == null) {
                continue;
            }
            CandidateItemDTO.HistoryScoreItem item = new CandidateItemDTO.HistoryScoreItem();
            item.setYear(historyScore.getYear());
            item.setScore(historyScore.getScore());
            item.setPos(historyScore.getPos());
            item.setPlanNum(historyScore.getPlanNum());
            item.setEnrollNum(historyScore.getEnrollNum());
            items.add(item);
        }
        return items;
    }

    private String legacyMajorVolunteerId(VolunteerRecommendListResponse.VolunteerSchool school,
                                          VolunteerRecommendListResponse.VolunteerMajor major) {
        String planSchoolDataId = school == null ? null : school.getPlanSchoolDataId();
        String majorIdentity = major == null ? null : major.getPlanMajorDataId();
        if (Strings.isNullOrEmpty(majorIdentity) && major != null) {
            majorIdentity = major.getMajorId();
        }
        if (Strings.isNullOrEmpty(majorIdentity) && major != null) {
            majorIdentity = major.getMajorUnitCode();
        }
        if (Strings.isNullOrEmpty(majorIdentity) && major != null) {
            majorIdentity = major.getMajor_name();
        }
        return safeId(planSchoolDataId, majorIdentity, major == null ? null : major.getMajor_name());
    }

    private String safeId(String first, String second, String third) {
        StringBuilder builder = new StringBuilder();
        if (!Strings.isNullOrEmpty(first)) {
            builder.append(first);
        }
        if (!Strings.isNullOrEmpty(second)) {
            if (builder.length() > 0) {
                builder.append("_");
            }
            builder.append(second);
        }
        if (builder.length() == 0 && !Strings.isNullOrEmpty(third)) {
            return third;
        }
        return builder.toString();
    }

    private boolean containsIgnoreCase(String text, String keyword) {
        if (Strings.isNullOrEmpty(keyword)) {
            return true;
        }
        if (Strings.isNullOrEmpty(text)) {
            return false;
        }
        return text.toLowerCase(Locale.ROOT).contains(keyword.toLowerCase(Locale.ROOT));
    }

    private Double rankToScore(Integer rankInTier) {
        if (rankInTier == null || rankInTier <= 0) {
            return null;
        }
        return Math.max(0D, 100D - rankInTier);
    }

    private boolean containsWorkingPlanItem(DraftPlanStateDTO draft, String volunteerId) {
        return WorkingPlanMutationSupport.containsWorkingPlanItem(draft, volunteerId);
    }

    private boolean containsVolunteerId(List<String> volunteerIds, String volunteerId) {
        return WorkingPlanMutationSupport.containsVolunteerId(volunteerIds, volunteerId);
    }

    private OrderedPlanStateDTO ensureOrderedPlanState(PlanningStateDTO state) {
        OrderedPlanStateDTO orderedPlanState = state.getOrderedPlanState();
        if (orderedPlanState.getItems().isEmpty() && !state.getDraftPlanState().getItems().isEmpty()) {
            List<CandidateItemDTO> effectiveCandidates = resolveEffectiveCandidates(null, state.getSessionId(), state, false);
            orderedPlanState.setItems(buildOrderedItemsFromWorkingPlan(
                    state.getDraftPlanState(),
                    state.getCandidatePoolState(),
                    effectiveCandidates,
                    new LinkedHashMap<String, OrderedItemDTO>(),
                    false));
            recalculateOrderedSummary(orderedPlanState, state.getCandidatePoolState());
        }
        return orderedPlanState;
    }

    private DraftPlanReorderReq buildDraftPlanReorderReq(InitialPlanGenerateReq req) {
        DraftPlanReorderReq reorderReq = new DraftPlanReorderReq();
        reorderReq.setForceRegenerate(Boolean.TRUE.equals(req.getForceRegenerate()));
        reorderReq.setRegroupByTier(Boolean.TRUE.equals(req.getRegroupByTier()));
        reorderReq.setAllowAutoComplete(true);
        return reorderReq;
    }

    private ReviewCheckDTO reviewRatioDistribution(PlanningStateDTO state) {
        ReviewCheckDTO check = new ReviewCheckDTO();
        check.setCode("ratio_distribution");
        check.setLevel("info");
        check.setPassed(true);
        check.setSummary("冲稳保区间配比正常");

        int total = isMajorGroupMode(state.getCandidatePoolState())
                ? defaultOrderedUnits(state.getOrderedPlanState().getUnits()).size()
                : state.getOrderedPlanState().getItems().size();
        if (total <= 0) {
            check.setSummary("当前暂无排序结果，暂不做区间配比校验");
            check.setDetail("orderedPlanState.items 为空。");
            return check;
        }

        int sprintCount;
        int protectCount;
        if (isMajorGroupMode(state.getCandidatePoolState())) {
            sprintCount = (int) defaultOrderedUnits(state.getOrderedPlanState().getUnits()).stream()
                    .filter(unit -> "冲".equals(unit.getTier()))
                    .count();
            protectCount = (int) defaultOrderedUnits(state.getOrderedPlanState().getUnits()).stream()
                    .filter(unit -> "保".equals(unit.getTier()))
                    .count();
        } else {
            sprintCount = (int) state.getOrderedPlanState().getItems().stream()
                    .filter(item -> "冲".equals(item.getTier()))
                    .count();
            protectCount = (int) state.getOrderedPlanState().getItems().stream()
                    .filter(item -> "保".equals(item.getTier()))
                    .count();
        }
        double sprintRatio = sprintCount * 1D / total;
        double protectRatio = protectCount * 1D / total;
        Integer expectedSprintCount = expectedTierCount(state.getCandidatePoolState(), "冲");
        Integer expectedProtectCount = expectedTierCount(state.getCandidatePoolState(), "保");
        boolean sprintMeetsExpected = expectedSprintCount != null && sprintCount >= expectedSprintCount;
        boolean protectMeetsExpected = expectedProtectCount != null && protectCount >= expectedProtectCount;
        boolean sprintWithinExpected = expectedSprintCount != null && sprintCount <= expectedSprintCount;

        if (sprintRatio > 0.4D && protectRatio < 0.2D && !protectMeetsExpected) {
            check.setPassed(false);
            check.setLevel("risk");
            check.setReasonCode("protect_tier_missing");
            check.setSummary("冲区占比过高且保区占比过低");
            check.setDetail("冲区占比超过40%，且保区占比低于20%。");
            check.setSuggestedAction("建议减少冲区志愿并补充保区志愿，优先调整到接近3:3:4。");
            return check;
        }
        if (sprintRatio > 0.4D && !sprintWithinExpected) {
            check.setPassed(false);
            check.setLevel("risk");
            check.setReasonCode("sprint_tier_over_limit");
            check.setSummary("冲区占比过高");
            check.setDetail("冲区占比超过40%。");
            check.setSuggestedAction("建议适当减少冲区志愿，补充稳区或保区志愿。");
            return check;
        }
        if (sprintRatio < 0.2D && !sprintMeetsExpected) {
            check.setPassed(false);
            check.setLevel("warn");
            check.setReasonCode("sprint_tier_missing");
            check.setSummary("冲区占比偏低");
            check.setDetail("冲区占比低于20%。");
            check.setSuggestedAction("建议适当增加冲区志愿，提高分数利用率。");
            return check;
        }
        if (protectRatio < 0.2D && !protectMeetsExpected) {
            check.setPassed(false);
            check.setLevel("risk");
            check.setReasonCode("protect_tier_missing");
            check.setSummary("保区占比过低");
            check.setDetail("保区占比低于20%。");
            check.setSuggestedAction("建议补充保区志愿，降低滑档风险。");
        }
        return check;
    }

    private Integer expectedTierCount(CandidatePoolStateDTO candidatePoolState, String tier) {
        if (candidatePoolState == null || candidatePoolState.getRequiredTierCounts() == null) {
            return null;
        }
        Integer value = candidatePoolState.getRequiredTierCounts().get(tier);
        return value == null || value <= 0 ? null : value;
    }

    private ReviewCheckDTO reviewSafetyGuard(PlanningStateDTO state, List<CandidateItemDTO> candidates) {
        ReviewCheckDTO check = new ReviewCheckDTO();
        check.setCode("safety_guard");
        check.setLevel("info");
        check.setPassed(true);

        CandidatePoolStateDTO candidatePoolState = state.getCandidatePoolState();
        Integer userScore = candidatePoolState.getUserScore();
        String sourceProvinceName = candidatePoolState.getSourceProvinceName();
        List<OrderedItemDTO> orderedItems = state.getOrderedPlanState().getItems();

        if (userScore != null && userScore >= 580) {
            check.setSummary("当前兜底方案相对安全");
            check.setDetail("用户分数不低于580，按照当前经验规则视为相对安全。");
            return check;
        }
        if (Strings.isNullOrEmpty(sourceProvinceName)) {
            check.setLevel("warn");
            check.setSummary("缺少生源省份信息，无法完成本省保底校验");
            check.setDetail("candidatePoolState.sourceProvinceName 为空。");
            check.setSuggestedAction("建议补充用户高考省份后重新执行审查。");
            return check;
        }

        int localProtectCount = 0;
        if (isMajorGroupMode(candidatePoolState)) {
            for (OrderedUnitDTO unit : defaultOrderedUnits(state.getOrderedPlanState().getUnits())) {
                if (!"保".equals(unit.getTier())) {
                    continue;
                }
                if (containsIgnoreCase(unit.getProvinceName(), sourceProvinceName)) {
                    localProtectCount++;
                    check.getAffectedUnitIds().add(unit.getUnitId());
                    defaultPlanningUnitMajors(unit.getMajorItems()).stream()
                            .map(PlanningUnitMajorDTO::getVolunteerId)
                            .forEach(check.getAffectedVolunteerIds()::add);
                }
            }
        } else {
            for (OrderedItemDTO orderedItem : orderedItems) {
                if (!"保".equals(orderedItem.getTier())) {
                    continue;
                }
                CandidateItemDTO candidateItem = findCandidate(candidates, orderedItem.getVolunteerId());
                if (candidateItem != null && containsIgnoreCase(candidateItem.getProvinceName(), sourceProvinceName)) {
                    localProtectCount++;
                    check.getAffectedVolunteerIds().add(orderedItem.getVolunteerId());
                }
            }
        }
        if (localProtectCount >= 2) {
            check.setSummary("当前兜底方案相对安全");
            check.setDetail("保区间中本省院校数量不少于2所。");
            return check;
        }

        check.setPassed(false);
        check.setLevel("risk");
        check.setSummary("本省保底志愿数量不足");
        check.setDetail("当前保区间中本省院校数量少于2所。");
        check.setSuggestedAction("建议优先补充本省保底志愿，降低滑档和退档风险。");
        return check;
    }

    private ReviewCheckDTO reviewProbabilityInversion(PlanningStateDTO state, List<CandidateItemDTO> candidates) {
        ReviewCheckDTO check = new ReviewCheckDTO();
        check.setCode("probability_inversion");
        check.setLevel("info");
        check.setPassed(true);
        check.setSummary("当前排序未发现录取概率倒挂");

        if (isMajorGroupMode(state.getCandidatePoolState())) {
            List<OrderedUnitDTO> orderedUnits = defaultOrderedUnits(state.getOrderedPlanState().getUnits());
            for (int i = 1; i < orderedUnits.size(); i++) {
                OrderedUnitDTO previous = orderedUnits.get(i - 1);
                OrderedUnitDTO current = orderedUnits.get(i);
                Double previousRatio = previous.getAdmissionRatio();
                Double currentRatio = current.getAdmissionRatio();
                if (previousRatio != null && currentRatio != null && previousRatio > currentRatio) {
                    check.setPassed(false);
                    check.setLevel("warn");
                    check.setSummary("当前排序存在录取概率倒挂");
                    check.setDetail(String.format("第%d组录取率 %.1f 高于第%d组录取率 %.1f。", i, previousRatio, i + 1, currentRatio));
                    check.setSuggestedAction("建议检查相邻专业组顺序，确认是否符合真实风险梯度。");
                    check.getAffectedUnitIds().add(previous.getUnitId());
                    check.getAffectedUnitIds().add(current.getUnitId());
                    defaultPlanningUnitMajors(previous.getMajorItems()).stream().map(PlanningUnitMajorDTO::getVolunteerId).forEach(check.getAffectedVolunteerIds()::add);
                    defaultPlanningUnitMajors(current.getMajorItems()).stream().map(PlanningUnitMajorDTO::getVolunteerId).forEach(check.getAffectedVolunteerIds()::add);
                    return check;
                }
            }
            return check;
        }

        List<OrderedItemDTO> orderedItems = state.getOrderedPlanState().getItems();
        for (int i = 1; i < orderedItems.size(); i++) {
            OrderedItemDTO previous = orderedItems.get(i - 1);
            OrderedItemDTO current = orderedItems.get(i);
            Double previousRatio = admissionRatioOf(candidates, previous.getVolunteerId());
            Double currentRatio = admissionRatioOf(candidates, current.getVolunteerId());
            if (previousRatio != null && currentRatio != null && previousRatio > currentRatio) {
                check.setPassed(false);
                check.setLevel("warn");
                check.setSummary("当前排序存在录取概率倒挂");
                check.setDetail(String.format("第%d位录取率 %.1f 高于第%d位录取率 %.1f。", i, previousRatio, i + 1, currentRatio));
                check.setSuggestedAction("建议检查相邻志愿顺序，确认是否符合个人真实意向。");
                check.getAffectedVolunteerIds().add(previous.getVolunteerId());
                check.getAffectedVolunteerIds().add(current.getVolunteerId());
                return check;
            }
        }
        return check;
    }

    private ReviewCheckDTO reviewProbabilityGap(PlanningStateDTO state, List<CandidateItemDTO> candidates) {
        ReviewCheckDTO check = new ReviewCheckDTO();
        check.setCode("probability_gap");
        check.setLevel("info");
        check.setPassed(true);
        check.setSummary("当前录取概率梯度基本合理");

        if (isMajorGroupMode(state.getCandidatePoolState())) {
            List<OrderedUnitDTO> orderedUnits = defaultOrderedUnits(state.getOrderedPlanState().getUnits());
            if (orderedUnits.size() <= 1) {
                check.setPassed(false);
                check.setLevel("warn");
                check.setSummary("当前志愿数量过少，无法形成有效梯度");
                check.setDetail("排序结果少于2组。");
                check.setSuggestedAction("建议继续补充志愿，形成合理梯度。");
                return check;
            }
            for (int i = 1; i < orderedUnits.size(); i++) {
                OrderedUnitDTO previous = orderedUnits.get(i - 1);
                OrderedUnitDTO current = orderedUnits.get(i);
                Double previousRatio = previous.getAdmissionRatio();
                Double currentRatio = current.getAdmissionRatio();
                if (previousRatio != null && currentRatio != null && Math.abs(currentRatio - previousRatio) > 8D) {
                    check.setPassed(false);
                    check.setLevel("warn");
                    check.setSummary("当前录取概率梯度存在断层");
                    check.setDetail(String.format("相邻专业组录取率差值超过8：%.1f -> %.1f。", previousRatio, currentRatio));
                    check.setSuggestedAction("建议补充录取概率位于该区间的专业组，降低梯度断层风险。");
                    check.getAffectedUnitIds().add(previous.getUnitId());
                    check.getAffectedUnitIds().add(current.getUnitId());
                    defaultPlanningUnitMajors(previous.getMajorItems()).stream().map(PlanningUnitMajorDTO::getVolunteerId).forEach(check.getAffectedVolunteerIds()::add);
                    defaultPlanningUnitMajors(current.getMajorItems()).stream().map(PlanningUnitMajorDTO::getVolunteerId).forEach(check.getAffectedVolunteerIds()::add);
                    return check;
                }
            }
            return check;
        }

        List<OrderedItemDTO> orderedItems = state.getOrderedPlanState().getItems();
        if (orderedItems.size() <= 1) {
            check.setPassed(false);
            check.setLevel("warn");
            check.setSummary("当前志愿数量过少，无法形成有效梯度");
            check.setDetail("排序结果少于2条。");
            check.setSuggestedAction("建议继续补充志愿，形成合理梯度。");
            return check;
        }
        for (int i = 1; i < orderedItems.size(); i++) {
            OrderedItemDTO previous = orderedItems.get(i - 1);
            OrderedItemDTO current = orderedItems.get(i);
            Double previousRatio = admissionRatioOf(candidates, previous.getVolunteerId());
            Double currentRatio = admissionRatioOf(candidates, current.getVolunteerId());
            if (previousRatio != null && currentRatio != null && Math.abs(currentRatio - previousRatio) > 8D) {
                check.setPassed(false);
                check.setLevel("warn");
                check.setSummary("当前录取概率梯度存在断层");
                check.setDetail(String.format("相邻录取率差值超过8：%.1f -> %.1f。", previousRatio, currentRatio));
                check.setSuggestedAction("建议补充录取概率位于该区间的志愿，降低梯度断层风险。");
                check.getAffectedVolunteerIds().add(previous.getVolunteerId());
                check.getAffectedVolunteerIds().add(current.getVolunteerId());
                return check;
            }
        }
        return check;
    }

    private ReviewCheckDTO reviewCountValidation(PlanningStateDTO state, List<CandidateItemDTO> candidates) {
        ReviewCheckDTO check = new ReviewCheckDTO();
        check.setCode("count_validation");
        check.setLevel("info");
        check.setPassed(true);

        Integer requiredCount = state.getCandidatePoolState().getRequiredCount();
        int currentCount = state.getOrderedPlanState().getItems().size();
        if (isMajorGroupMode(state.getCandidatePoolState())) {
            currentCount = defaultOrderedUnits(state.getOrderedPlanState().getUnits()).size();
        }
        if (requiredCount == null || requiredCount <= 0) {
            check.setLevel("warn");
            check.setSummary("缺少官方数量要求，无法完成数量校验");
            check.setDetail("candidatePoolState.requiredCount 为空。");
            check.setSuggestedAction("建议补充省份批次对应的志愿数量要求后重新执行审查。");
            return check;
        }
        if (currentCount < requiredCount) {
            check.setPassed(false);
            check.setLevel("risk");
            check.setReasonCode("count_missing");
            check.setSummary("当前志愿数量少于官方要求");
            check.setDetail(String.format("当前数量 %d，小于要求数量 %d。", currentCount, requiredCount));
            check.setSuggestedAction("建议通过补偿或手动补选将志愿数量补足。");
            return check;
        }
        if (currentCount > requiredCount) {
            check.setPassed(false);
            check.setLevel("warn");
            check.setReasonCode("count_over_limit");
            check.setSummary("当前志愿数量多于官方要求");
            check.setDetail(String.format("当前数量 %d，大于要求数量 %d。", currentCount, requiredCount));
            check.setSuggestedAction("建议精简志愿数量，避免最终填报时临时删改。");
            return check;
        }

        check.setSummary("当前志愿数量符合官方要求");
        check.setDetail(String.format("当前数量 %d，满足要求数量 %d。", currentCount, requiredCount));
        return check;
    }

    private ReviewCheckDTO reviewGroupInnerSafetyGuard(PlanningStateDTO state, List<CandidateItemDTO> candidates) {
        ReviewCheckDTO check = new ReviewCheckDTO();
        check.setCode("group_inner_safety_guard");
        check.setLevel("info");
        check.setPassed(true);
        check.setSummary("当前组内已包含安全垫专业");

        if (!isMajorGroupMode(state.getCandidatePoolState())) {
            check.setDetail("当前不是专业组模式，无需执行组内安全垫校验。");
            return check;
        }

        Map<String, List<OrderedItemDTO>> grouped = state.getOrderedPlanState().getItems().stream()
                .collect(Collectors.groupingBy(item -> {
                    CandidateItemDTO candidateItem = findCandidate(candidates, item.getVolunteerId());
                    String unitId = resolveInitialRecommendationUnitId(candidateItem);
                    return Strings.isNullOrEmpty(unitId) ? item.getSchoolName() : unitId;
                }, LinkedHashMap::new, Collectors.toList()));

        List<String> missingSafetyUnits = Lists.newArrayList();
        for (Map.Entry<String, List<OrderedItemDTO>> entry : grouped.entrySet()) {
            List<OrderedItemDTO> orderedItems = entry.getValue();
            boolean hasSafetyMajor = false;
            for (OrderedItemDTO item : orderedItems) {
                CandidateItemDTO candidate = findCandidate(candidates, item.getVolunteerId());
                if (candidate != null
                        && candidate.getAdmissionRatio() != null
                        && candidate.getSchoolEnrollRatio() != null
                        && isSafetyMajorRatio(candidate.getAdmissionRatio(), candidate.getSchoolEnrollRatio())) {
                    hasSafetyMajor = true;
                    break;
                }
            }
            if (hasSafetyMajor) {
                continue;
            }
            if (!orderedItems.isEmpty()) {
                missingSafetyUnits.add(orderedItems.get(0).getSchoolName());
                if (!Strings.isNullOrEmpty(entry.getKey()) && !check.getAffectedUnitIds().contains(entry.getKey())) {
                    check.getAffectedUnitIds().add(entry.getKey());
                }
                orderedItems.stream()
                        .map(OrderedItemDTO::getVolunteerId)
                        .forEach(check.getAffectedVolunteerIds()::add);
            }
        }
        if (missingSafetyUnits.isEmpty()) {
            check.setDetail("每个专业组至少保留了一个录取率高于组整体录取率的专业。");
            return check;
        }

        check.setPassed(false);
        check.setLevel("warn");
        check.setSummary("存在专业组缺少组内安全垫专业");
        check.setDetail(String.format("以下专业组当前未保留安全垫专业：%s。", String.join("、", missingSafetyUnits)));
        check.setSuggestedAction("建议在对应专业组内至少保留一个录取率高于组整体录取率的专业。");
        return check;
    }

    private ReviewCheckDTO reviewHighTuition(PlanningStateDTO state, List<CandidateItemDTO> candidates) {
        ReviewCheckDTO check = new ReviewCheckDTO();
        check.setCode("high_tuition");
        check.setLevel("info");
        check.setPassed(true);
        check.setSummary("当前方案未发现高收费专业");

        List<CandidateItemDTO> highTuitionItems = state.getOrderedPlanState().getItems().stream()
                .map(item -> findCandidate(candidates, item.getVolunteerId()))
                .filter(item -> item != null && item.getTuitionPerYear() != null && item.getTuitionPerYear() > 20000)
                .collect(Collectors.toList());
        if (highTuitionItems.isEmpty()) {
            return check;
        }

        check.setPassed(false);
        check.setLevel("warn");
        check.setSummary("当前方案包含高收费专业");
        check.setDetail("检测到学费超过 2w/学年的专业，请结合家庭经济情况综合考虑。");
        check.setSuggestedAction("建议结合家庭经济状况确认是否保留相关志愿。");
        for (CandidateItemDTO item : highTuitionItems) {
            check.getAffectedVolunteerIds().add(item.getVolunteerId());
            addAffectedUnitId(check, item);
        }
        return check;
    }

    private ReviewCheckDTO reviewAdmissionLimit(PlanningStateDTO state, List<CandidateItemDTO> candidates) {
        ReviewCheckDTO check = new ReviewCheckDTO();
        check.setCode("admission_limit");
        check.setLevel("info");
        check.setPassed(true);
        check.setSummary("当前方案未发现明显限报标签");

        Set<String> matchedTags = new HashSet<String>();
        for (OrderedItemDTO orderedItem : state.getOrderedPlanState().getItems()) {
            CandidateItemDTO candidateItem = findCandidate(candidates, orderedItem.getVolunteerId());
            if (candidateItem == null) {
                continue;
            }
            List<String> tags = mergeReasons(candidateItem.getReasonCodes(), candidateItem.getRiskFlags(), candidateItem.getMustSubjects());
            for (String tag : tags) {
                if (containsAny(tag, "色盲", "色弱", "单科", "性别", "语种")) {
                    matchedTags.add(tag);
                    check.getAffectedVolunteerIds().add(orderedItem.getVolunteerId());
                    addAffectedUnitId(check, candidateItem);
                }
            }
        }
        if (matchedTags.isEmpty()) {
            return check;
        }

        check.setPassed(false);
        check.setLevel("warn");
        check.setSummary("当前方案包含限制报考专业");
        check.setDetail(String.format("检测到以下限制标签：%s。", String.join("、", matchedTags)));
        check.setSuggestedAction("建议结合自身身体条件、单科成绩、语种和性别要求谨慎确认。");
        return check;
    }

    private ReviewCheckDTO reviewSpecialEnrollment(PlanningStateDTO state, List<CandidateItemDTO> candidates) {
        ReviewCheckDTO check = new ReviewCheckDTO();
        check.setCode("special_enrollment");
        check.setLevel("info");
        check.setPassed(true);
        check.setSummary("当前方案未发现特殊类型招生标签");

        Set<String> matchedTags = new HashSet<String>();
        for (OrderedItemDTO orderedItem : state.getOrderedPlanState().getItems()) {
            CandidateItemDTO candidateItem = findCandidate(candidates, orderedItem.getVolunteerId());
            if (candidateItem == null) {
                continue;
            }
            for (String tag : mergeReasons(candidateItem.getReasonCodes(), candidateItem.getRiskFlags())) {
                if (containsAny(tag, "专项", "公费", "定向", "免费医学生", "强基", "国家计划", "地方专项", "高校专项")) {
                    matchedTags.add(tag);
                    check.getAffectedVolunteerIds().add(orderedItem.getVolunteerId());
                    addAffectedUnitId(check, candidateItem);
                }
            }
        }
        if (matchedTags.isEmpty()) {
            return check;
        }

        check.setPassed(false);
        check.setLevel("warn");
        check.setSummary("当前方案包含特殊类型招生志愿");
        check.setDetail(String.format("检测到以下特殊类型标签：%s。", String.join("、", matchedTags)));
        check.setSuggestedAction("建议确认自己是否满足对应专项或特殊类型招生条件。");
        return check;
    }

    private ReviewCheckDTO reviewEdgeScore(PlanningStateDTO state) {
        ReviewCheckDTO check = new ReviewCheckDTO();
        check.setCode("edge_score");
        check.setLevel("info");
        check.setPassed(true);
        check.setSummary("当前分数不属于边缘分数区间");

        Integer userScore = state.getCandidatePoolState().getUserScore();
        Integer batchScore = state.getCandidatePoolState().getBatchScore();
        if (userScore == null || batchScore == null) {
            check.setSummary("缺少分数线信息，暂不执行边缘分数校验");
            check.setDetail("candidatePoolState.userScore 或 batchScore 为空。");
            return check;
        }
        if (userScore - batchScore > 30) {
            return check;
        }

        check.setPassed(false);
        check.setLevel("warn");
        check.setSummary("当前分数属于边缘分数区间");
        check.setDetail(String.format("当前分数 %d，距离批次线 %d 分。", userScore, userScore - batchScore));
        check.setSuggestedAction("建议增加稳保院校和省内院校选择，降低滑档风险。");
        return check;
    }

    private ReviewCheckDTO reviewCooperativeProgram(PlanningStateDTO state, List<CandidateItemDTO> candidates) {
        ReviewCheckDTO check = new ReviewCheckDTO();
        check.setCode("cooperative_program");
        check.setLevel("info");
        check.setPassed(true);
        check.setSummary("当前方案未发现中外合作办学项目");

        for (OrderedItemDTO orderedItem : state.getOrderedPlanState().getItems()) {
            CandidateItemDTO candidateItem = findCandidate(candidates, orderedItem.getVolunteerId());
            if (candidateItem == null) {
                continue;
            }
            if (containsAny(candidateItem.getSchoolName(), "中外合作")
                    || containsAny(candidateItem.getMajorName(), "中外合作")
                    || candidateItem.getReasonCodes().stream().anyMatch(tag -> containsAny(tag, "中外合作"))) {
                check.setPassed(false);
                check.setLevel("warn");
                check.setSummary("当前方案包含中外合作办学项目");
                check.setDetail("请仔细核对中外合作办学的学校和专业，确认自己是否能够接受。");
                check.setSuggestedAction("若不接受中外合作办学，可将相关志愿移出方案，或把它作为后续必须避开的报考条件。");
                check.getAffectedVolunteerIds().add(orderedItem.getVolunteerId());
                addAffectedUnitId(check, candidateItem);
            }
        }
        return check;
    }

    private void addAffectedUnitId(ReviewCheckDTO check, CandidateItemDTO candidateItem) {
        if (check == null || candidateItem == null) {
            return;
        }
        String unitId = resolveInitialRecommendationUnitId(candidateItem);
        if (!Strings.isNullOrEmpty(unitId) && !check.getAffectedUnitIds().contains(unitId)) {
            check.getAffectedUnitIds().add(unitId);
        }
    }

    private ReviewCheckDTO reviewMajorGroupSafetyIntentAlignment(PlanningStateDTO state) {
        ReviewCheckDTO check = new ReviewCheckDTO();
        check.setCode("major_group_safety_intent_alignment");
        check.setLevel("info");
        check.setPassed(true);
        check.setSummary("当前专业组托底专业与意向基本一致");

        if (!isMajorGroupMode(state.getCandidatePoolState())) {
            check.setDetail("当前不是专业组模式，无需检查组内托底专业与意向的一致性。");
            return check;
        }

        Map<String, CandidateItemDTO> candidateMap = defaultCandidates(state.getCandidatePoolState() == null
                ? null
                : state.getCandidatePoolState().getItems()).stream()
                .filter(candidate -> !Strings.isNullOrEmpty(candidate.getVolunteerId()))
                .collect(Collectors.toMap(CandidateItemDTO::getVolunteerId, candidate -> candidate, (left, right) -> left, LinkedHashMap::new));
        List<OrderedItemDTO> orderedItems = defaultOrderedItems(state.getOrderedPlanState() == null ? null : state.getOrderedPlanState().getItems());
        if (orderedItems.isEmpty()) {
            check.setDetail("当前方案中暂无专业组数据。");
            return check;
        }

        Map<String, List<CandidateItemDTO>> groupedCandidates = new LinkedHashMap<String, List<CandidateItemDTO>>();
        Map<String, String> unitNameMap = new LinkedHashMap<String, String>();
        for (OrderedItemDTO orderedItem : orderedItems) {
            CandidateItemDTO candidate = candidateMap.get(orderedItem.getVolunteerId());
            if (candidate == null) {
                continue;
            }
            String unitId = resolveInitialRecommendationUnitId(candidate);
            if (Strings.isNullOrEmpty(unitId)) {
                unitId = orderedItem.getSchoolName();
            }
            groupedCandidates.computeIfAbsent(unitId, key -> Lists.newArrayList()).add(candidate);
            unitNameMap.putIfAbsent(unitId, orderedItem.getSchoolName());
        }

        List<String> affectedUnitNames = Lists.newArrayList();
        for (Map.Entry<String, List<CandidateItemDTO>> entry : groupedCandidates.entrySet()) {
            List<CandidateItemDTO> majors = defaultCandidates(entry.getValue());
            if (majors.isEmpty()) {
                continue;
            }
            Double schoolEnrollRatio = majors.stream()
                    .map(CandidateItemDTO::getSchoolEnrollRatio)
                    .filter(Objects::nonNull)
                    .findFirst()
                    .orElse(null);
            if (schoolEnrollRatio == null) {
                continue;
            }
            List<CandidateItemDTO> safetyMajors = majors.stream()
                    .filter(major -> isSafetyMajorRatio(major.getAdmissionRatio(), schoolEnrollRatio))
                    .collect(Collectors.toList());
            if (safetyMajors.isEmpty()) {
                continue;
            }
            boolean anyPreferredMajor = majors.stream().anyMatch(major -> Boolean.TRUE.equals(major.getPreferred()));
            boolean allSafetyMajorsNotPreferred = safetyMajors.stream()
                    .noneMatch(major -> Boolean.TRUE.equals(major.getPreferred()));
            double maxSafetyIntentScore = safetyMajors.stream()
                    .map(CandidateItemDTO::getIntentScore)
                    .filter(Objects::nonNull)
                    .max(Double::compareTo)
                    .orElse(0D);
            double maxNonSafetyIntentScore = majors.stream()
                    .filter(major -> !isSafetyMajorRatio(major.getAdmissionRatio(), schoolEnrollRatio))
                    .map(CandidateItemDTO::getIntentScore)
                    .filter(Objects::nonNull)
                    .max(Double::compareTo)
                    .orElse(maxSafetyIntentScore);
            boolean intentGapLarge = maxNonSafetyIntentScore - maxSafetyIntentScore >= 10D;
            if ((!anyPreferredMajor && !intentGapLarge) || !allSafetyMajorsNotPreferred) {
                continue;
            }
            affectedUnitNames.add(unitNameMap.getOrDefault(entry.getKey(), entry.getKey()));
            if (!Strings.isNullOrEmpty(entry.getKey())) {
                check.getAffectedUnitIds().add(entry.getKey());
            }
            safetyMajors.stream()
                    .map(CandidateItemDTO::getVolunteerId)
                    .filter(id -> !Strings.isNullOrEmpty(id))
                    .forEach(check.getAffectedVolunteerIds()::add);
        }

        if (affectedUnitNames.isEmpty()) {
            check.setDetail("当前各专业组中的托底专业未发现与已选意向明显偏离的情况。");
            return check;
        }

        check.setPassed(false);
        check.setLevel("warn");
        check.setSummary("部分专业组主要依靠非意向专业托底");
        check.setDetail(String.format("以下专业组的托底专业与当前已选意向不完全一致：%s。", String.join("、", affectedUnitNames)));
        check.setSuggestedAction("建议确认这些专业组是否接受用非核心意向专业换取更稳妥的录取安全垫。");
        return check;
    }

    private ReviewCheckDTO buildFixedNoticeCheck(String code, String level, String summary, String detail) {
        ReviewCheckDTO check = new ReviewCheckDTO();
        check.setCode(code);
        check.setLevel(level);
        check.setPassed(true);
        check.setSummary(summary);
        check.setDetail(detail);
        return check;
    }

    private CompensationPreviewDTO buildCompensationPreview(PlanningStateDTO state, List<CandidateItemDTO> candidates) {
        CompensationPreviewDTO preview = new CompensationPreviewDTO();
        preview.setStatus("ready");
        preview.setSourceVersion(state.getVersion());

        Integer requiredCount = state.getCandidatePoolState() == null ? null : state.getCandidatePoolState().getRequiredCount();
        if (requiredCount != null && requiredCount > 0) {
            boolean majorGroupMode = isMajorGroupMode(state.getCandidatePoolState());
            int currentCount = majorGroupMode
                    ? currentOrderedOrDraftUnitCount(state)
                    : currentOrderedOrDraftItemCount(state);
            if (currentCount > requiredCount) {
                preview.setStatus("empty");
                preview.setTotalActions(0);
                return preview;
            }
        }

        if (isMajorGroupMode(state.getCandidatePoolState())) {
            List<PlanningUnitDTO> availableUnits = buildAvailableCompensationUnits(state, candidates);
            CompensationActionDTO totalCountAction = buildTotalCountCompensationForUnits(state, availableUnits);
            if (totalCountAction != null) {
                preview.getActions().add(totalCountAction);
            }

            CompensationActionDTO safetyAction = buildSafetyCompensationForUnits(state, availableUnits);
            if (safetyAction != null) {
                preview.getActions().add(safetyAction);
            }

            CompensationActionDTO ratioAction = buildRatioCompensationForUnits(state, availableUnits);
            if (ratioAction != null) {
                preview.getActions().add(ratioAction);
            }

            CompensationActionDTO gradientAction = buildGradientCompensationForUnits(state, availableUnits);
            if (gradientAction != null) {
                preview.getActions().add(gradientAction);
            }

            removeEmptyCompensationActions(preview);
            if (preview.getActions().isEmpty()) {
                preview.setStatus("empty");
            }
            preview.setTotalActions(preview.getActions().size());
            return preview;
        }

        List<CandidateItemDTO> availableCandidates = buildAvailableCompensationCandidates(state, candidates);

        CompensationActionDTO totalCountAction = buildTotalCountCompensation(state, availableCandidates);
        if (totalCountAction != null) {
            preview.getActions().add(totalCountAction);
        }

        CompensationActionDTO safetyAction = buildSafetyCompensation(state, candidates, availableCandidates);
        if (safetyAction != null) {
            preview.getActions().add(safetyAction);
        }

        CompensationActionDTO ratioAction = buildRatioCompensation(state, availableCandidates);
        if (ratioAction != null) {
            preview.getActions().add(ratioAction);
        }

        CompensationActionDTO gradientAction = buildGradientCompensation(state, candidates, availableCandidates);
        if (gradientAction != null) {
            preview.getActions().add(gradientAction);
        }

        removeEmptyCompensationActions(preview);
        if (preview.getActions().isEmpty()) {
            preview.setStatus("empty");
        }
        preview.setTotalActions(preview.getActions().size());
        return preview;
    }

    private void removeEmptyCompensationActions(CompensationPreviewDTO preview) {
        if (preview == null || preview.getActions() == null) {
            return;
        }
        preview.getActions().removeIf(action ->
                action == null
                        || (defaultList(action.getVolunteerIds()).isEmpty()
                        && defaultList(action.getUnitIds()).isEmpty()));
    }

    private void trimCompensationActionsForRemainingCapacity(PlanningStateDTO state,
                                                             CompensationPreviewDTO preview,
                                                             List<PlanningUnitDTO> availableUnits) {
        trimCompensationActionsForRemainingCapacity(state, preview, availableUnits, true);
    }

    private void trimCompensationActionsForRemainingCapacity(PlanningStateDTO state,
                                                             CompensationPreviewDTO preview,
                                                             List<PlanningUnitDTO> availableUnits,
                                                             boolean keepReplacementActionsWhenFull) {
        if (preview == null || preview.getActions() == null || preview.getActions().isEmpty()
                || state == null || state.getCandidatePoolState() == null) {
            return;
        }
        Integer requiredCount = state.getCandidatePoolState().getRequiredCount();
        if (requiredCount == null || requiredCount <= 0) {
            return;
        }
        boolean majorGroupMode = isMajorGroupMode(state.getCandidatePoolState());
        int currentCount = majorGroupMode
                ? currentOrderedOrDraftUnitCount(state)
                : currentOrderedOrDraftItemCount(state);
        int remainingCapacity = Math.max(requiredCount - currentCount, 0);
        if (currentCount > requiredCount) {
            preview.getActions().clear();
            return;
        }

        Map<String, PlanningUnitDTO> unitById = majorGroupMode && availableUnits != null
                ? availableUnits.stream()
                .filter(unit -> unit != null && !Strings.isNullOrEmpty(unit.getUnitId()))
                .collect(Collectors.toMap(PlanningUnitDTO::getUnitId, unit -> unit, (left, right) -> left, LinkedHashMap::new))
                : new LinkedHashMap<>();

        int remainingBudget = remainingCapacity;
        boolean preserveReplacementPreviewWhenFull = keepReplacementActionsWhenFull && remainingCapacity <= 0;
        Set<String> plannedUnitIds = new LinkedHashSet<String>();
        Set<String> plannedVolunteerIds = new LinkedHashSet<String>();
        for (CompensationActionDTO action : preview.getActions()) {
            if (action == null) {
                continue;
            }
            boolean replacementAction = isReplacementCompensationAction(action);
            if (remainingBudget <= 0) {
                if (!preserveReplacementPreviewWhenFull || !replacementAction) {
                    action.setUnitIds(Lists.newArrayList());
                    action.setVolunteerIds(Lists.newArrayList());
                }
                continue;
            }
            if (remainingBudget <= 1 && isLimitedCapacityOptionalAddAction(action)) {
                action.setUnitIds(Lists.newArrayList());
                action.setVolunteerIds(Lists.newArrayList());
                continue;
            }
            int actionLimit = Math.max(remainingBudget, 0);
            if (majorGroupMode) {
                List<String> keptUnitIds = defaultList(action.getUnitIds()).stream()
                        .filter(id -> !Strings.isNullOrEmpty(id))
                        .filter(id -> !plannedUnitIds.contains(id))
                        .limit(actionLimit)
                        .collect(Collectors.toList());
                action.setUnitIds(keptUnitIds);
                List<String> volunteerIds = keptUnitIds.stream()
                        .map(unitById::get)
                        .filter(Objects::nonNull)
                        .flatMap(unit -> defaultPlanningUnitMajors(unit.getSelectedMajors()).stream())
                        .map(PlanningUnitMajorDTO::getVolunteerId)
                        .filter(id -> !Strings.isNullOrEmpty(id))
                        .collect(Collectors.toList());
                action.setVolunteerIds(volunteerIds);
                plannedUnitIds.addAll(keptUnitIds);
                plannedVolunteerIds.addAll(volunteerIds);
                remainingBudget -= keptUnitIds.size();
                continue;
            }

            List<String> keptVolunteerIds = defaultList(action.getVolunteerIds()).stream()
                    .filter(id -> !Strings.isNullOrEmpty(id))
                    .filter(id -> !plannedVolunteerIds.contains(id))
                    .limit(actionLimit)
                    .collect(Collectors.toList());
            action.setVolunteerIds(keptVolunteerIds);
            plannedVolunteerIds.addAll(keptVolunteerIds);
            remainingBudget -= keptVolunteerIds.size();
        }
    }

    private boolean isReplacementCompensationAction(CompensationActionDTO action) {
        if (action == null || Strings.isNullOrEmpty(action.getType())) {
            return false;
        }
        return RepairProposalTaxonomy.CompensationActionType.REBALANCE_PROTECT_RATIO.equals(action.getType())
                || RepairProposalTaxonomy.CompensationActionType.FILL_PROBABILITY_GAP.equals(action.getType());
    }

    private boolean isLimitedCapacityOptionalAddAction(CompensationActionDTO action) {
        return action != null
                && RepairProposalTaxonomy.CompensationActionType.FILL_PROBABILITY_GAP.equals(action.getType());
    }

    private int currentOrderedOrDraftItemCount(PlanningStateDTO state) {
        return state.getOrderedPlanState().getItems().isEmpty()
                ? state.getDraftPlanState().getItems().size()
                : state.getOrderedPlanState().getItems().size();
    }

    private int currentOrderedOrDraftUnitCount(PlanningStateDTO state) {
        return !defaultOrderedUnits(state.getOrderedPlanState().getUnits()).isEmpty()
                ? defaultOrderedUnits(state.getOrderedPlanState().getUnits()).size()
                : defaultDraftUnits(state.getDraftPlanState().getUnits()).size();
    }

    private List<PlanningUnitDTO> buildAvailableCompensationUnits(PlanningStateDTO state,
                                                                  List<CandidateItemDTO> candidates) {
        Integer requiredMajorCount = state.getCandidatePoolState() == null ? null : state.getCandidatePoolState().getRequiredMajorCount();
        Set<String> selectedUnitIds = defaultOrderedUnits(state.getOrderedPlanState().getUnits()).stream()
                .map(OrderedUnitDTO::getUnitId)
                .filter(id -> !Strings.isNullOrEmpty(id))
                .collect(Collectors.toCollection(LinkedHashSet::new));
        if (selectedUnitIds.isEmpty()) {
            selectedUnitIds.addAll(state.getDraftPlanState().getItems().stream()
                    .map(item -> resolveInitialRecommendationUnitId(findCandidate(candidates, item.getVolunteerId())))
                    .filter(id -> !Strings.isNullOrEmpty(id))
                    .collect(Collectors.toCollection(LinkedHashSet::new)));
        }
        List<CandidateItemDTO> eligibleCandidates = defaultCandidates(candidates).stream()
                .filter(candidate -> RepairCandidateEligibility.isEligibleForConfirmedHardConstraints(candidate, state))
                .collect(Collectors.toList());
        return groupCandidatesToPlanningUnits(eligibleCandidates, requiredMajorCount).stream()
                .filter(unit -> unit != null && !Strings.isNullOrEmpty(unit.getUnitId()))
                .filter(unit -> !selectedUnitIds.contains(unit.getUnitId()))
                .filter(this::isCompensationSafeUnit)
                .sorted(Comparator.comparing((PlanningUnitDTO unit) -> unit.getFinalScore() == null ? 0D : unit.getFinalScore()).reversed())
                .collect(Collectors.toList());
    }

    private List<CandidateItemDTO> buildAvailableCompensationCandidates(PlanningStateDTO state,
                                                                        List<CandidateItemDTO> candidates) {
        if (!isMajorGroupMode(state.getCandidatePoolState())) {
            return defaultCandidates(candidates).stream()
                    .filter(item -> !containsWorkingPlanItem(state.getDraftPlanState(), item.getVolunteerId()))
                    .filter(item -> !containsVolunteerId(state.getDraftPlanState().getBannedVolunteerIds(), item.getVolunteerId()))
                    .filter(this::isCompensationSafeCandidate)
                    .filter(item -> RepairCandidateEligibility.isEligibleForConfirmedHardConstraints(item, state))
                    .collect(Collectors.toList());
        }
        Set<String> selectedUnitIds = state.getDraftPlanState().getItems().stream()
                .map(item -> resolveInitialRecommendationUnitId(findCandidate(candidates, item.getVolunteerId())))
                .filter(unitId -> !Strings.isNullOrEmpty(unitId))
                .collect(Collectors.toCollection(LinkedHashSet::new));
        return groupCandidatesByUnit(candidates).values().stream()
                .map(unitCandidates -> unitCandidates.stream()
                        .filter(this::isCompensationSafeCandidate)
                        .filter(item -> RepairCandidateEligibility.isEligibleForConfirmedHardConstraints(item, state))
                        .sorted(buildMajorGroupInnerCandidateComparator())
                        .collect(Collectors.toList()))
                .filter(unitCandidates -> !unitCandidates.isEmpty())
                .filter(unitCandidates -> !selectedUnitIds.contains(resolveInitialRecommendationUnitId(unitCandidates.get(0))))
                .map(this::buildMajorGroupUnitRepresentative)
                .filter(Objects::nonNull)
                .collect(Collectors.toList());
    }

    private int countDistinctOrderedUnits(List<OrderedItemDTO> orderedItems, List<CandidateItemDTO> candidates) {
        return (int) orderedItems.stream()
                .map(item -> {
                    CandidateItemDTO candidate = findCandidate(candidates, item.getVolunteerId());
                    String unitId = resolveInitialRecommendationUnitId(candidate);
                    if (!Strings.isNullOrEmpty(unitId)) {
                        return unitId;
                    }
                    return Strings.isNullOrEmpty(item.getSchoolName()) ? item.getVolunteerId() : item.getSchoolName();
                })
                .distinct()
                .count();
    }

    private void attachCompensationsToReviewChecks(ReviewStateDTO reviewState, CompensationPreviewDTO compensationPreview) {
        if (reviewState == null || reviewState.getChecks() == null) {
            return;
        }
        Map<String, List<CompensationActionDTO>> grouped = compensationPreview.getActions().stream()
                .filter(action -> !Strings.isNullOrEmpty(action.getSourceCheckCode()))
                .collect(Collectors.groupingBy(CompensationActionDTO::getSourceCheckCode, LinkedHashMap::new, Collectors.toList()));
        for (ReviewCheckDTO check : reviewState.getChecks()) {
            check.setSuggestedCompensations(Lists.newArrayList());
            List<CompensationActionDTO> linked = grouped.get(check.getCode());
            if (linked == null) {
                continue;
            }
            check.getSuggestedCompensations().addAll(linked);
        }
    }

    private void enrichReviewMetadata(ReviewStateDTO reviewState) {
        if (reviewState == null || reviewState.getChecks() == null) {
            return;
        }
        for (ReviewCheckDTO check : reviewState.getChecks()) {
            enrichReviewMetadata(check);
        }
    }

    private void enrichReviewMetadata(ReviewCheckDTO check) {
        if (check == null || Strings.isNullOrEmpty(check.getCode())) {
            return;
        }
        ReviewRuleMetadataDTO metadata = ReviewRuleRegistry.get(check.getCode());
        if (metadata == null) {
            return;
        }
        check.setLabel(metadata.getLabel());
        check.setCategory(metadata.getCategory());
        check.setSeverityDefault(metadata.getSeverityDefault());
        check.setTargetModes(defaultList(metadata.getTargetModes()));
        check.setScopeKind(metadata.getScopeKind());
        check.setFixability(metadata.getFixability());
        check.setSupportedFixStrategies(defaultList(metadata.getSupportedFixStrategies()));
        check.setDefaultFixStrategy(metadata.getDefaultFixStrategy());
        check.setRequiresConfirmation(metadata.getRequiresConfirmation());
        check.setEvidenceSchema(metadata.getEvidenceSchema());
        check.setPostApplyValidationRule(metadata.getPostApplyValidationRule());
    }

    private void normalizeReviewReasonCodes(PlanningStateDTO state, ReviewStateDTO reviewState) {
        if (reviewState == null || reviewState.getChecks() == null) {
            return;
        }
        for (ReviewCheckDTO check : reviewState.getChecks()) {
            normalizeReviewReasonCode(state, check);
        }
    }

    private void normalizeReviewReasonCode(PlanningStateDTO state, ReviewCheckDTO check) {
        if (check == null || !Boolean.FALSE.equals(check.getPassed()) || !Strings.isNullOrEmpty(check.getReasonCode())) {
            return;
        }
        if ("count_validation".equals(check.getCode())) {
            check.setReasonCode(resolveCountValidationReasonCode(state));
            return;
        }
        if ("ratio_distribution".equals(check.getCode())) {
            check.setReasonCode(resolveRatioDistributionReasonCode(state));
        }
    }

    private PlanningStateDTO buildReviewReasonAnalysisState(PlanningStateDTO state) {
        if (state == null || state.getOrderedPlanState() == null || state.getCandidatePoolState() == null) {
            return state;
        }
        if (!isMajorGroupMode(state.getCandidatePoolState())
                || !defaultOrderedUnits(state.getOrderedPlanState().getUnits()).isEmpty()
                || defaultOrderedItems(state.getOrderedPlanState().getItems()).isEmpty()) {
            return state;
        }
        OrderedPlanStateDTO structuralOrderedState = buildStructuralOrderedSnapshot(
                state.getCandidatePoolState(),
                state.getOrderedPlanState(),
                state.getCandidatePoolState().getItems());
        return buildPlanAdjustmentAnalysisState(state, structuralOrderedState);
    }

    private String resolveCountValidationReasonCode(PlanningStateDTO state) {
        CandidatePoolStateDTO candidatePoolState = state == null ? null : state.getCandidatePoolState();
        Integer requiredCount = candidatePoolState == null ? null : candidatePoolState.getRequiredCount();
        if (requiredCount == null || requiredCount <= 0) {
            return null;
        }
        int currentCount = isMajorGroupMode(candidatePoolState)
                ? defaultOrderedUnits(state == null || state.getOrderedPlanState() == null
                ? null : state.getOrderedPlanState().getUnits()).size()
                : defaultOrderedItems(state == null || state.getOrderedPlanState() == null
                ? null : state.getOrderedPlanState().getItems()).size();
        if (currentCount < requiredCount) {
            return "count_missing";
        }
        if (currentCount > requiredCount) {
            return "count_over_limit";
        }
        return null;
    }

    private String resolveRatioDistributionReasonCode(PlanningStateDTO state) {
        CandidatePoolStateDTO candidatePoolState = state == null ? null : state.getCandidatePoolState();
        if (candidatePoolState == null) {
            return null;
        }
        boolean majorGroupMode = isMajorGroupMode(candidatePoolState);
        int total = majorGroupMode
                ? defaultOrderedUnits(state == null || state.getOrderedPlanState() == null
                ? null : state.getOrderedPlanState().getUnits()).size()
                : defaultOrderedItems(state == null || state.getOrderedPlanState() == null
                ? null : state.getOrderedPlanState().getItems()).size();
        if (total <= 0) {
            return null;
        }
        int sprintCount = countOrderedTier(state, "冲", majorGroupMode);
        int protectCount = countOrderedTier(state, "保", majorGroupMode);
        double sprintRatio = sprintCount * 1D / total;
        double protectRatio = protectCount * 1D / total;
        Integer expectedSprintCount = expectedTierCount(candidatePoolState, "冲");
        Integer expectedProtectCount = expectedTierCount(candidatePoolState, "保");
        boolean sprintMeetsExpected = expectedSprintCount != null && sprintCount >= expectedSprintCount;
        boolean protectMeetsExpected = expectedProtectCount != null && protectCount >= expectedProtectCount;
        boolean sprintWithinExpected = expectedSprintCount != null && sprintCount <= expectedSprintCount;

        if (sprintRatio > 0.4D && protectRatio < 0.2D && !protectMeetsExpected) {
            return "protect_tier_missing";
        }
        if (sprintRatio > 0.4D && !sprintWithinExpected) {
            return "sprint_tier_over_limit";
        }
        if (sprintRatio < 0.2D && !sprintMeetsExpected) {
            return "sprint_tier_missing";
        }
        if (protectRatio < 0.2D && !protectMeetsExpected) {
            return "protect_tier_missing";
        }
        return null;
    }

    private int countOrderedTier(PlanningStateDTO state, String tier, boolean majorGroupMode) {
        if (majorGroupMode) {
            return (int) defaultOrderedUnits(state == null || state.getOrderedPlanState() == null
                    ? null : state.getOrderedPlanState().getUnits()).stream()
                    .filter(unit -> unit != null && tier.equals(unit.getTier()))
                    .count();
        }
        return (int) defaultOrderedItems(state == null || state.getOrderedPlanState() == null
                ? null : state.getOrderedPlanState().getItems()).stream()
                .filter(item -> item != null && tier.equals(item.getTier()))
                .count();
    }

    private boolean isRatioDistributionAddSuggestion(ReviewCheckDTO check) {
        if (check == null) {
            return false;
        }
        String reasonCode = check.getReasonCode();
        return "sprint_tier_missing".equals(reasonCode)
                || "protect_tier_missing".equals(reasonCode);
    }

    private boolean isRatioDistributionReplaceSuggestion(ReviewCheckDTO check,
                                                         OrderedPlanStateDTO analysisOrderedState,
                                                         List<CompensationActionDTO> linkedActions,
                                                         PlanningStateDTO analysisState) {
        if (check == null) {
            return false;
        }
        if ("sprint_tier_over_limit".equals(check.getReasonCode())
                || Strings.isNullOrEmpty(check.getReasonCode())) {
            return true;
        }
        if (!isPlanAtOrAboveRequiredCount(analysisOrderedState, analysisState)) {
            return false;
        }
        return linkedActions != null && linkedActions.stream()
                .anyMatch(action -> action != null
                        && RepairProposalTaxonomy.CompensationActionType.REBALANCE_PROTECT_RATIO.equals(action.getType())
                        && (!defaultList(action.getVolunteerIds()).isEmpty()
                        || !defaultList(action.getUnitIds()).isEmpty()));
    }

    private boolean isPlanAtOrAboveRequiredCount(OrderedPlanStateDTO analysisOrderedState,
                                                PlanningStateDTO analysisState) {
        CandidatePoolStateDTO candidatePoolState = analysisState == null ? null : analysisState.getCandidatePoolState();
        Integer requiredCount = candidatePoolState == null ? null : candidatePoolState.getRequiredCount();
        if (requiredCount == null || requiredCount <= 0 || analysisOrderedState == null) {
            return false;
        }
        int currentCount = !defaultOrderedUnits(analysisOrderedState.getUnits()).isEmpty()
                ? defaultOrderedUnits(analysisOrderedState.getUnits()).size()
                : defaultOrderedItems(analysisOrderedState.getItems()).size();
        return currentCount >= requiredCount;
    }

    private void enrichPlanAdjustmentMetadata(PlanAdjustmentStateDTO adjustmentState) {
        if (adjustmentState == null || adjustmentState.getAnalysis() == null
                || adjustmentState.getAnalysis().getRules() == null) {
            return;
        }
        for (PlanAdjustmentRuleResultDTO rule : adjustmentState.getAnalysis().getRules()) {
            enrichPlanAdjustmentMetadata(rule);
        }
    }

    private void enrichPlanAdjustmentMetadata(PlanAdjustmentRuleResultDTO rule) {
        if (rule == null || Strings.isNullOrEmpty(rule.getRuleCode())) {
            return;
        }
        ReviewRuleMetadataDTO metadata = ReviewRuleRegistry.get(rule.getRuleCode());
        if (metadata == null) {
            return;
        }
        rule.setLabel(metadata.getLabel());
        rule.setCategory(metadata.getCategory());
        rule.setScopeKind(metadata.getScopeKind());
        rule.setFixability(metadata.getFixability());
        rule.setSupportedFixStrategies(defaultList(metadata.getSupportedFixStrategies()));
        rule.setDefaultFixStrategy(metadata.getDefaultFixStrategy());
    }

    private FixProposalStateDTO buildFixProposalState(PlanningStateDTO state,
                                                      ReviewStateDTO reviewState,
                                                      CompensationPreviewDTO compensationPreview) {
        FixProposalStateDTO proposalState = RepairProposalStateBuilder.newState(state, reviewState);
        Map<String, List<CompensationActionDTO>> compensationByCheck =
                RepairProposalStateBuilder.groupCompensationActionsByCheck(compensationPreview);
        List<ReviewCheckDTO> checks = reviewState == null || reviewState.getChecks() == null
                ? Lists.newArrayList()
                : reviewState.getChecks();
        for (ReviewCheckDTO check : checks) {
            if (!Boolean.FALSE.equals(check.getPassed())) {
                continue;
            }
            enrichReviewMetadata(check);
            FixProposalDTO proposal = buildFixProposalForReviewCheck(
                    state,
                    check,
                    compensationByCheck.get(check.getCode()),
                    reviewState.getSourceVersion());
            if (proposal != null) {
                proposalState.getProposals().add(proposal);
            }
        }
        proposalState.setTotal(proposalState.getProposals().size());
        proposalState.setStatus(RepairProposalStateBuilder.resolveStateStatus(proposalState.getProposals()));
        return proposalState;
    }

    private FixProposalDTO buildFixProposalForReviewCheck(PlanningStateDTO state,
                                                          ReviewCheckDTO check,
                                                          List<CompensationActionDTO> compensationActions,
                                                          Integer sourceReviewVersion) {
        if (check == null || Strings.isNullOrEmpty(check.getCode())) {
            return null;
        }
        FixProposalDTO proposal = RepairProposalStateBuilder.buildBaseProposal(state, check, compensationActions, sourceReviewVersion);
        if (proposal == null) {
            return null;
        }
        RepairRiskActionBuilder.populateRemoveRiskItemActions(proposal, check, compensationActions,
                removedVolunteerIds -> buildTotalCountCompensationForRemoveRiskItems(state, removedVolunteerIds));
        RepairRiskActionBuilder.populateReplaceRiskItemActions(state, check, proposal);
        RepairReplacementActionBuilder.populateStructuralReplacementActions(state, check, proposal, compensationActions);
        RepairMajorGroupInnerSafetyActionBuilder.populateActions(state, check, proposal);
        if (RepairProposalTaxonomy.isBlockedStatus(proposal.getStatus())) {
            proposal.setRequiresConfirmation(false);
        } else if (RepairProposalTaxonomy.isCannotSatisfyStrategy(proposal.getStrategy())) {
            proposal.setStatus(RepairProposalTaxonomy.Status.BLOCKED);
            proposal.setRequiresConfirmation(false);
            RepairProposalStateBuilder.addBlockingReasonCode(proposal,
                    RepairProposalStateBuilder.resolveBlockingReasonCode(check));
        } else if (RepairProposalTaxonomy.isNoOpStrategy(proposal.getStrategy())) {
            proposal.setStatus(RepairProposalTaxonomy.Status.INFO);
            proposal.setRequiresConfirmation(false);
        } else if (!RepairProposalApplyPolicy.isSupportedStrategy(proposal.getStrategy())) {
            proposal.setStatus(RepairProposalTaxonomy.Status.PREVIEW_ONLY);
        }
        RepairDryRunSimulator.populate(state, proposal, check);
        if (RepairProposalTaxonomy.isCannotSatisfyStrategy(proposal.getStrategy())) {
            proposal.setBlockingReason(proposal.getDryRunResult().getMessage());
            RepairProposalStateBuilder.addBlockingReasonCode(proposal,
                    RepairProposalStateBuilder.resolveBlockingReasonCode(check));
        }
        RepairProposalStateBuilder.populateActionTotals(proposal);
        RepairProposalStateBuilder.suppressInvalidBlockedActionPreview(proposal);
        RepairProposalStateBuilder.populateCandidateShortages(state, check, proposal);
        return proposal;
    }

    private CompensationActionDTO buildTotalCountCompensationForRemoveRiskItems(PlanningStateDTO state,
                                                                               List<String> removedVolunteerIds) {
        if (state == null || state.getCandidatePoolState() == null || removedVolunteerIds == null || removedVolunteerIds.isEmpty()) {
            return null;
        }
        int requiredCount = state.getCandidatePoolState().getRequiredCount() == null
                ? 0 : state.getCandidatePoolState().getRequiredCount();
        if (requiredCount <= 0) {
            return null;
        }
        List<CandidateItemDTO> candidates = defaultCandidates(state.getCandidatePoolState().getItems());
        Set<String> removedSet = new LinkedHashSet<String>(removedVolunteerIds);
        List<DraftItemDTO> remainingDraftItems = defaultDraftItems(state.getDraftPlanState() == null ? null : state.getDraftPlanState().getItems()).stream()
                .filter(item -> item != null && !removedSet.contains(item.getVolunteerId()))
                .collect(Collectors.toList());
        boolean majorGroupMode = isMajorGroupMode(state.getCandidatePoolState());
        int currentCount = countWorkingPlanSummaryTotal(remainingDraftItems, majorGroupMode);
        int gap = requiredCount - currentCount;
        if (gap <= 0) {
            return null;
        }
        Set<String> currentIds = remainingDraftItems.stream()
                .map(DraftItemDTO::getVolunteerId)
                .filter(value -> !Strings.isNullOrEmpty(value))
                .collect(Collectors.toCollection(LinkedHashSet::new));
        List<CandidateItemDTO> availableCandidates = candidates.stream()
                .filter(this::isCompensationSafeCandidate)
                .filter(candidate -> RepairCandidateEligibility.isEligibleForConfirmedHardConstraints(candidate, state))
                .filter(candidate -> !Strings.isNullOrEmpty(candidate.getVolunteerId()))
                .filter(candidate -> !currentIds.contains(candidate.getVolunteerId()))
                .filter(candidate -> !removedSet.contains(candidate.getVolunteerId()))
                .filter(candidate -> !majorGroupMode || !currentDraftContainsUnit(remainingDraftItems, candidate))
                .collect(Collectors.toList());
        RepairCandidateSelector.Selection selection = RepairCandidateSelector.selectTotalCountVolunteerAdditions(
                state,
                availableCandidates,
                gap,
                resolveCompensationShortageTierFromDraftItems(state, remainingDraftItems, majorGroupMode));
        List<String> volunteerIds = selection.getCandidateVolunteerIds();
        if (volunteerIds.isEmpty()) {
            return null;
        }
        CompensationActionDTO action = new CompensationActionDTO();
        action.setType(RepairProposalTaxonomy.CompensationActionType.FILL_TOTAL_COUNT);
        action.setLevel("warn");
        action.setSourceCheckCode("count_validation");
        action.setSummary("移除风险项后补足志愿数量");
        action.setDetail(String.format("移除风险志愿后，建议补充 %d 个候选。", volunteerIds.size()));
        action.setVolunteerIds(volunteerIds);
        return action;
    }

    private boolean currentDraftContainsUnit(List<DraftItemDTO> items, CandidateItemDTO candidate) {
        String unitId = resolveInitialRecommendationUnitId(candidate);
        if (Strings.isNullOrEmpty(unitId)) {
            unitId = candidate == null ? null : candidate.getPlanSchoolDataId();
        }
        if (Strings.isNullOrEmpty(unitId)) {
            return false;
        }
        String targetUnitId = unitId;
        return defaultDraftItems(items).stream()
                .map(this::resolveDraftOrOrderedUnitId)
                .anyMatch(targetUnitId::equals);
    }

    private List<CompensationActionDTO> defaultCompensationActions(List<CompensationActionDTO> values) {
        return values == null ? Lists.newArrayList() : values;
    }

    private CompensationActionDTO buildTotalCountCompensation(PlanningStateDTO state, List<CandidateItemDTO> availableCandidates) {
        RepairCandidateSelector.Selection selection = RepairCandidateSelector.selectTotalCountVolunteerAdditions(state, availableCandidates);
        List<String> volunteerIds = selection.getCandidateVolunteerIds();
        if (volunteerIds.isEmpty()) {
            return null;
        }

        CompensationActionDTO action = new CompensationActionDTO();
        action.setType(RepairProposalTaxonomy.CompensationActionType.FILL_TOTAL_COUNT);
        action.setLevel("risk");
        action.setSourceCheckCode("count_validation");
        action.setSummary("补足志愿总数量");
        action.setDetail(String.format("当前志愿数量不足，建议补充 %d 个候选。", volunteerIds.size()));
        action.setVolunteerIds(volunteerIds);
        return action;
    }

    private CompensationActionDTO buildTotalCountCompensationForUnits(PlanningStateDTO state,
                                                                      List<PlanningUnitDTO> availableUnits) {
        RepairCandidateSelector.Selection selection = RepairCandidateSelector.selectTotalCountUnitAdditions(state, availableUnits);
        if (selection.getCandidateUnitIds().isEmpty()) {
            return null;
        }
        CompensationActionDTO action = new CompensationActionDTO();
        action.setType(RepairProposalTaxonomy.CompensationActionType.FILL_TOTAL_COUNT);
        action.setLevel("risk");
        action.setSourceCheckCode("count_validation");
        action.setSummary("补足志愿总数量");
        action.setDetail(String.format("当前志愿数量不足，建议补充 %d 个专业组。", selection.getCandidateUnitIds().size()));
        action.setUnitIds(selection.getCandidateUnitIds());
        action.setVolunteerIds(selection.getCandidateVolunteerIds());
        return action;
    }

    private String resolveCompensationShortageTierFromDraftItems(PlanningStateDTO state,
                                                                 List<DraftItemDTO> draftItems,
                                                                 boolean majorGroupMode) {
        if (state == null || state.getCandidatePoolState() == null
                || state.getCandidatePoolState().getRequiredTierCounts() == null
                || state.getCandidatePoolState().getRequiredTierCounts().isEmpty()) {
            return null;
        }
        Map<String, Integer> currentCounts = new LinkedHashMap<String, Integer>();
        if (majorGroupMode) {
            Map<String, String> unitTierMap = new LinkedHashMap<String, String>();
            for (DraftItemDTO item : defaultDraftItems(draftItems)) {
                String unitId = resolveDraftOrOrderedUnitId(item);
                if (!Strings.isNullOrEmpty(unitId) && !unitTierMap.containsKey(unitId)) {
                    unitTierMap.put(unitId, item.getTier());
                }
            }
            for (String tier : unitTierMap.values()) {
                currentCounts.merge(Strings.isNullOrEmpty(tier) ? "保" : tier, 1, Integer::sum);
            }
        } else {
            for (DraftItemDTO item : defaultDraftItems(draftItems)) {
                String tier = item == null || Strings.isNullOrEmpty(item.getTier()) ? "保" : item.getTier();
                currentCounts.merge(tier, 1, Integer::sum);
            }
        }
        String shortageTier = null;
        int maxDeficit = 0;
        for (String tier : Lists.newArrayList("保", "稳", "冲")) {
            int target = positiveCount(state.getCandidatePoolState().getRequiredTierCounts().get(tier));
            int current = currentCounts.getOrDefault(tier, 0);
            int deficit = target - current;
            if (deficit > maxDeficit) {
                maxDeficit = deficit;
                shortageTier = tier;
            }
        }
        return shortageTier;
    }

    private CompensationActionDTO buildSafetyCompensation(PlanningStateDTO state,
                                                          List<CandidateItemDTO> candidates,
                                                          List<CandidateItemDTO> availableCandidates) {
        RepairCandidateSelector.Selection selection = RepairCandidateSelector.selectLocalProtectVolunteerAdditions(
                state, candidates, availableCandidates);
        List<String> volunteerIds = selection.getCandidateVolunteerIds();
        if (volunteerIds.isEmpty()) {
            return null;
        }

        CompensationActionDTO action = new CompensationActionDTO();
        action.setType(RepairProposalTaxonomy.CompensationActionType.ADD_LOCAL_PROTECT);
        action.setLevel("risk");
        action.setSourceCheckCode("safety_guard");
        action.setSummary("补充本省保底志愿");
        action.setDetail("当前本省保底志愿不足，建议优先补充本省保区候选。");
        action.setVolunteerIds(volunteerIds);
        return action;
    }

    private CompensationActionDTO buildSafetyCompensationForUnits(PlanningStateDTO state,
                                                                  List<PlanningUnitDTO> availableUnits) {
        RepairCandidateSelector.Selection selection = RepairCandidateSelector.selectLocalProtectUnitAdditions(state, availableUnits);
        if (selection.getCandidateUnitIds().isEmpty()) {
            return null;
        }

        CompensationActionDTO action = new CompensationActionDTO();
        action.setType(RepairProposalTaxonomy.CompensationActionType.ADD_LOCAL_PROTECT);
        action.setLevel("risk");
        action.setSourceCheckCode("safety_guard");
        action.setSummary("补充本省保底志愿");
        action.setDetail("当前本省保底专业组不足，建议优先补充本省保区专业组。");
        action.setUnitIds(selection.getCandidateUnitIds());
        action.setVolunteerIds(selection.getCandidateVolunteerIds());
        return action;
    }

    private CompensationActionDTO buildRatioCompensation(PlanningStateDTO state, List<CandidateItemDTO> availableCandidates) {
        RepairCandidateSelector.Selection selection = RepairCandidateSelector.selectProtectRatioVolunteerAdditions(state, availableCandidates);
        List<String> volunteerIds = selection.getCandidateVolunteerIds();
        if (volunteerIds.isEmpty()) {
            return null;
        }

        CompensationActionDTO action = new CompensationActionDTO();
        action.setType(RepairProposalTaxonomy.CompensationActionType.REBALANCE_PROTECT_RATIO);
        action.setLevel("warn");
        action.setSourceCheckCode("ratio_distribution");
        action.setSummary("补充保区志愿以平衡区间");
        action.setDetail("当前保区占比偏低，建议补充保区候选以改善冲稳保配比。");
        action.setVolunteerIds(volunteerIds);
        return action;
    }

    private CompensationActionDTO buildRatioCompensationForUnits(PlanningStateDTO state,
                                                                 List<PlanningUnitDTO> availableUnits) {
        RepairCandidateSelector.Selection selection = RepairCandidateSelector.selectProtectRatioUnitAdditions(state, availableUnits);
        if (selection.getCandidateUnitIds().isEmpty()) {
            return null;
        }

        CompensationActionDTO action = new CompensationActionDTO();
        action.setType(RepairProposalTaxonomy.CompensationActionType.REBALANCE_PROTECT_RATIO);
        action.setLevel("warn");
        action.setSourceCheckCode("ratio_distribution");
        action.setSummary("补充保区志愿以平衡区间");
        action.setDetail("当前保区专业组占比偏低，建议补充保区专业组以改善冲稳保配比。");
        action.setUnitIds(selection.getCandidateUnitIds());
        action.setVolunteerIds(selection.getCandidateVolunteerIds());
        return action;
    }

    private int currentOrderedOrDraftTierCount(PlanningStateDTO state, String tier) {
        if (state == null) {
            return 0;
        }
        if (state.getOrderedPlanState() != null
                && state.getOrderedPlanState().getItems() != null
                && !state.getOrderedPlanState().getItems().isEmpty()) {
            return (int) state.getOrderedPlanState().getItems().stream()
                    .filter(item -> tier.equals(item.getTier()))
                    .count();
        }
        return (int) defaultDraftItems(state.getDraftPlanState() == null ? null : state.getDraftPlanState().getItems()).stream()
                .filter(item -> tier.equals(item.getTier()))
                .count();
    }

    private int currentOrderedOrDraftUnitTierCount(PlanningStateDTO state, String tier) {
        if (state == null) {
            return 0;
        }
        if (state.getOrderedPlanState() != null
                && !defaultOrderedUnits(state.getOrderedPlanState().getUnits()).isEmpty()) {
            return (int) defaultOrderedUnits(state.getOrderedPlanState().getUnits()).stream()
                    .filter(unit -> tier.equals(unit.getTier()))
                    .count();
        }
        return (int) defaultDraftUnits(state.getDraftPlanState() == null ? null : state.getDraftPlanState().getUnits()).stream()
                .filter(unit -> tier.equals(unit.getTier()))
                .count();
    }

    private CompensationActionDTO buildGradientCompensation(PlanningStateDTO state,
                                                            List<CandidateItemDTO> candidates,
                                                            List<CandidateItemDTO> availableCandidates) {
        RepairCandidateSelector.Selection selection = RepairCandidateSelector.selectProbabilityGapVolunteerAdditions(
                state, candidates, availableCandidates);
        if (selection.getCandidateVolunteerIds().isEmpty()) {
            return null;
        }

        CompensationActionDTO action = new CompensationActionDTO();
        action.setType(RepairProposalTaxonomy.CompensationActionType.FILL_PROBABILITY_GAP);
        action.setLevel("warn");
        action.setSourceCheckCode("probability_gap");
        action.setSummary("补充梯度断层区间的候选");
        action.setDetail(String.format("当前 %.1f 到 %.1f 的录取概率区间存在断层，建议补充中间梯度候选。",
                selection.getRangeMin(), selection.getRangeMax()));
        action.setVolunteerIds(selection.getCandidateVolunteerIds());
        return action;
    }

    private CompensationActionDTO buildGradientCompensationForUnits(PlanningStateDTO state,
                                                                    List<PlanningUnitDTO> availableUnits) {
        RepairCandidateSelector.Selection selection = RepairCandidateSelector.selectProbabilityGapUnitAdditions(state, availableUnits);
        if (selection.getCandidateUnitIds().isEmpty()) {
            return null;
        }

        CompensationActionDTO action = new CompensationActionDTO();
        action.setType(RepairProposalTaxonomy.CompensationActionType.FILL_PROBABILITY_GAP);
        action.setLevel("warn");
        action.setSourceCheckCode("probability_gap");
        action.setSummary("补充梯度断层区间的候选");
        action.setDetail(String.format("当前 %.1f 到 %.1f 的录取概率区间存在断层，建议补充中间梯度专业组。",
                selection.getRangeMin(), selection.getRangeMax()));
        action.setUnitIds(selection.getCandidateUnitIds());
        action.setVolunteerIds(selection.getCandidateVolunteerIds());
        return action;
    }

    private boolean isCompensationSafeUnit(PlanningUnitDTO unit) {
        if (unit == null || !Boolean.TRUE.equals(unit.getHasSafetyMajor())) {
            return false;
        }
        return defaultPlanningUnitMajors(unit.getSelectedMajors()).stream().allMatch(major -> {
            CandidateItemDTO candidate = new CandidateItemDTO();
            candidate.setSchoolName(unit.getSchoolName());
            candidate.setMajorName(major.getMajorName());
            candidate.setReasonCodes(Lists.newArrayList());
            candidate.setRiskFlags(Lists.newArrayList());
            candidate.setMustSubjects(Lists.newArrayList());
            candidate.setTuitionPerYear(major.getTuitionPerYear());
            return isCompensationSafeCandidate(candidate);
        });
    }

    private boolean isCompensationSafeCandidate(CandidateItemDTO item) {
        return RepairCandidateSelector.isCompensationSafeCandidate(item);
    }

    private void recalculateReviewSummary(ReviewStateDTO reviewState) {
        int passedCount = 0;
        int warnCount = 0;
        int riskCount = 0;
        for (ReviewCheckDTO check : reviewState.getChecks()) {
            if (Boolean.TRUE.equals(check.getPassed())) {
                passedCount++;
            }
            if ("warn".equalsIgnoreCase(check.getLevel())) {
                warnCount++;
            }
            if ("risk".equalsIgnoreCase(check.getLevel())) {
                riskCount++;
            }
        }
        int totalCount = reviewState.getChecks().size();
        reviewState.getSummary().setTotal(totalCount);
        reviewState.getSummary().setPassedCount(passedCount);
        reviewState.getSummary().setWarnCount(warnCount);
        reviewState.getSummary().setRiskCount(riskCount);
        reviewState.getSummary().setTotalRuleCount(totalCount);
        reviewState.getSummary().setPassedRuleCount(passedCount);
        reviewState.getSummary().setWarnRuleCount(warnCount);
        reviewState.getSummary().setRiskRuleCount(riskCount);
    }

    private Double admissionRatioOf(List<CandidateItemDTO> candidates, String volunteerId) {
        CandidateItemDTO candidateItem = findCandidate(candidates, volunteerId);
        return candidateItem == null ? null : candidateItem.getAdmissionRatio();
    }

    private boolean containsAny(String text, String... keywords) {
        if (Strings.isNullOrEmpty(text)) {
            return false;
        }
        for (String keyword : keywords) {
            if (containsIgnoreCase(text, keyword)) {
                return true;
            }
        }
        return false;
    }

    private List<OrderedItemDTO> buildOrderedItemsFromWorkingPlan(DraftPlanStateDTO draft,
                                                                  CandidatePoolStateDTO candidatePoolState,
                                                                  List<CandidateItemDTO> candidates,
                                                                  Map<String, OrderedItemDTO> existingItems,
                                                                  boolean regroupByTier) {
        List<DraftItemDTO> draftItems = new ArrayList<DraftItemDTO>(draft.getItems());
        Map<String, CandidateItemDTO> candidateMap = candidates == null
                ? new LinkedHashMap<String, CandidateItemDTO>()
                : candidates.stream()
                .collect(Collectors.toMap(CandidateItemDTO::getVolunteerId, item -> item, (left, right) -> left, LinkedHashMap::new));
        if (regroupByTier) {
            draftItems = draftItems.stream()
                    .sorted(buildDraftOrderedComparator(
                            candidateMap,
                            candidatePoolState == null ? null : candidatePoolState.getSourceProvinceName(),
                            isMajorGroupMode(candidatePoolState)))
                    .collect(Collectors.toList());
        }

        List<OrderedItemDTO> items = new ArrayList<OrderedItemDTO>();
        for (DraftItemDTO draftItem : draftItems) {
            OrderedItemDTO orderedItem = new OrderedItemDTO();
            orderedItem.setVolunteerId(draftItem.getVolunteerId());
            orderedItem.setTier(draftItem.getTier());
            orderedItem.setSchoolName(draftItem.getSchoolName());
            orderedItem.setMajorName(draftItem.getMajorName());
            orderedItem.setLocked(draftItem.getLocked());
            orderedItem.setSource(draftItem.getSource());
            orderedItem.setOrderedBy("system");
            orderedItem.setOrderReason(regroupByTier ? "tier_gradient" : "draft_order");

            OrderedItemDTO existing = existingItems.get(draftItem.getVolunteerId());
            if (existing != null) {
                orderedItem.setPinned(existing.getPinned());
                orderedItem.setPinnedPosition(existing.getPinnedPosition());
                if (!Strings.isNullOrEmpty(existing.getOrderedBy())) {
                    orderedItem.setOrderedBy(existing.getOrderedBy());
                }
                if (!Strings.isNullOrEmpty(existing.getOrderReason())) {
                    orderedItem.setOrderReason(existing.getOrderReason());
                }
            }
            items.add(orderedItem);
        }
        return OrderedPlanPositioningSupport.rebuildItems(items);
    }

    private void replaceWorkingPlanWithInitialRecommendation(PlanningStateDTO state, List<CandidateItemDTO> candidates) {
        DraftPlanStateDTO draft = state.getDraftPlanState();
        draft.setItems(Lists.newArrayList());
        draft.setUnits(Lists.newArrayList());
        if (state.getInitialRecommendationState() == null
                || state.getInitialRecommendationState().getItems() == null
                || state.getInitialRecommendationState().getItems().isEmpty()
                || candidates == null
                || candidates.isEmpty()) {
            return;
        }
        if (isMajorGroupMode(state.getCandidatePoolState())
                && state.getInitialRecommendationState().getUnits() != null
                && !state.getInitialRecommendationState().getUnits().isEmpty()) {
            draft.setUnits(buildDraftUnitsFromPlanningUnits(state.getInitialRecommendationState().getUnits(), "initial_auto"));
            for (DraftUnitDTO unit : defaultDraftUnits(draft.getUnits())) {
                for (PlanningUnitMajorDTO major : defaultPlanningUnitMajors(unit.getMajorItems())) {
                    DraftItemDTO item = new DraftItemDTO();
                    item.setVolunteerId(major.getVolunteerId());
                    item.setTier(unit.getTier());
                    item.setSchoolName(unit.getSchoolName());
                    item.setMajorName(major.getMajorName());
                    item.setSource(unit.getSource());
                    item.setLocked(unit.getLocked());
                    draft.getItems().add(item);
                }
            }
            return;
        }
        Map<String, CandidateItemDTO> candidateMap = candidates.stream()
                .filter(candidate -> !Strings.isNullOrEmpty(candidate.getVolunteerId()))
                .collect(Collectors.toMap(CandidateItemDTO::getVolunteerId,
                        candidate -> candidate,
                        (left, right) -> left,
                        LinkedHashMap::new));
        Set<String> selectedVolunteerIds = new LinkedHashSet<String>();
        for (InitialRecommendationItemDTO recommendationItem : state.getInitialRecommendationState().getItems()) {
            if (recommendationItem == null || Strings.isNullOrEmpty(recommendationItem.getVolunteerId())) {
                continue;
            }
            CandidateItemDTO candidate = candidateMap.get(recommendationItem.getVolunteerId());
            if (candidate == null || !selectedVolunteerIds.add(candidate.getVolunteerId())) {
                continue;
            }
            draft.getItems().add(toAutoDraftItem(candidate));
        }
    }

    private Comparator<CandidateItemDTO> buildAutoDraftCandidateComparator(String sourceProvinceName) {
        return Comparator
                .comparingInt((CandidateItemDTO item) -> tierOrder(item.getTier()))
                .thenComparing((CandidateItemDTO item) -> admissionRatioOf(item), Comparator.nullsLast(Double::compareTo))
                .thenComparingInt((CandidateItemDTO item) -> autoProtectPriority(item, sourceProvinceName))
                .thenComparing((CandidateItemDTO item) -> futureDevelopmentScoreOf(item), Comparator.nullsLast(Comparator.reverseOrder()))
                .thenComparing((CandidateItemDTO item) -> finalScoreOf(item), Comparator.nullsLast(Comparator.reverseOrder()))
                .thenComparing((CandidateItemDTO item) -> rankInTierOf(item), Comparator.nullsLast(Integer::compareTo))
                .thenComparing(CandidateItemDTO::getVolunteerId, Comparator.nullsLast(String::compareTo));
    }

    private void addAutoSelectedByTier(DraftPlanStateDTO draft,
                                       List<CandidateItemDTO> sortedCandidates,
                                       Set<String> selectedVolunteerIds,
                                       Set<String> bannedVolunteerIds,
                                       String tier,
                                       Integer expectedCount) {
        if (expectedCount == null || expectedCount <= 0) {
            return;
        }
        for (CandidateItemDTO candidate : sortedCandidates) {
            long currentTierCount = draft.getItems().stream().filter(item -> tier.equals(item.getTier())).count();
            if (currentTierCount >= expectedCount) {
                break;
            }
            if (!tier.equals(candidate.getTier())) {
                continue;
            }
            if (!canAutoSelectCandidate(candidate, selectedVolunteerIds, bannedVolunteerIds)) {
                continue;
            }
            draft.getItems().add(toAutoDraftItem(candidate));
            selectedVolunteerIds.add(candidate.getVolunteerId());
        }
    }

    /**
     * 约束生效后按档位目标数，从**合格候选**补足工作方案。
     *
     * <p>与"同步"是一对：同步负责删掉不合规的 ✓，补足负责把方案拉回目标规模 ✓——
     * 只有前者时方案只会越改越小，**一次筛空就再也回不来** ✗（2026-09-25 真栈实测：
     * 工作方案被清成 0 行后，此后任何重生成都从空方案出发 ✓）。
     *
     * <p>只追加、不动用户已有条目 ✓（跳过已选与已禁 ✓）。候选由调用方先按约束过滤
     * （`resolveEffectiveCandidates` ✓），所以补进来的天然合规 ✓，随后
     * `generateOrderedPlan` 的同步不会把它们删掉 ✓。
     */
    @Transactional(rollbackFor = Exception.class)
    public PlanningStateDTO refillWorkingPlanByTierTargets(Long tenantId, Long chatSessionId) {
        PlanningStateDTO state = loadPlanningState(chatSessionId);
        DraftPlanStateDTO draft = state.getDraftPlanState();
        CandidatePoolStateDTO pool = state.getCandidatePoolState();
        // 注意：本类的 `defaultList(...)` 是 **String 专用**的 ✗，候选列表要自己判空 ✓。
        List<CandidateItemDTO> poolItems = pool == null || pool.getItems() == null
                ? new ArrayList<CandidateItemDTO>() : pool.getItems();
        if (draft == null || pool == null || poolItems.isEmpty()) {
            state.setSessionId(chatSessionId);
            return state;
        }
        // RETRY_REPLAY：补足是纯内存变换（只追加、幂等），CAS 输 -> 重读最新后重放；耗尽响亮冲突
        applyTierTargetRefill(state, tenantId, chatSessionId);
        return saveWorkingPlanStateWithReplay(chatSessionId, state, "refill_by_tier",
                latest -> applyTierTargetRefill(latest, tenantId, chatSessionId));
    }

    /** 档位目标补足变换（纯内存、只追加；重放安全）。 */
    private void applyTierTargetRefill(PlanningStateDTO state, Long tenantId, Long chatSessionId) {
        DraftPlanStateDTO draft = state.getDraftPlanState();
        CandidatePoolStateDTO pool = state.getCandidatePoolState();
        if (draft == null || pool == null || pool.getItems() == null || pool.getItems().isEmpty()) {
            return;
        }
        List<CandidateItemDTO> effectiveCandidates = resolveEffectiveCandidates(tenantId, chatSessionId, state, true);
        refillWorkingPlanByTier(draft, effectiveCandidates, pool.getRequiredTierCounts());
        syncWorkingPlanUnitsWithItems(draft, effectiveCandidates, pool);
        recalculateWorkingPlanSummary(draft, pool);
    }

    /**
     * 补足本体（package-private：单测直接打这一层 ✓，`PlanningStateServiceRefillTest`）。
     *
     * <p>候选**按池内顺序**使用 ✓（池本身就是推荐顺序，不在这里重排 ✗）；`tierTargets`
     * 取自候选池的 `requiredTierCounts` ✓（会话里就有，如 `{冲13, 稳13, 保19}` ✓）。
     */
    void refillWorkingPlanByTier(DraftPlanStateDTO draft,
                                 List<CandidateItemDTO> candidates,
                                 Map<String, Integer> tierTargets) {
        if (draft == null || tierTargets == null || tierTargets.isEmpty()) {
            return;
        }
        Set<String> selected = new LinkedHashSet<String>();
        for (DraftItemDTO item : defaultDraftItems(draft.getItems())) {
            if (item != null && !Strings.isNullOrEmpty(item.getVolunteerId())) {
                selected.add(item.getVolunteerId());
            }
        }
        Set<String> banned = new LinkedHashSet<String>(defaultList(draft.getBannedVolunteerIds()));
        for (Map.Entry<String, Integer> entry : tierTargets.entrySet()) {
            addAutoSelectedByTier(draft, candidates, selected, banned, entry.getKey(), entry.getValue());
        }
    }

    private boolean canAutoSelectCandidate(CandidateItemDTO candidate,
                                           Set<String> selectedVolunteerIds,
                                           Set<String> bannedVolunteerIds) {
        return candidate != null
                && !Strings.isNullOrEmpty(candidate.getVolunteerId())
                && !selectedVolunteerIds.contains(candidate.getVolunteerId())
                && !bannedVolunteerIds.contains(candidate.getVolunteerId());
    }

    private DraftItemDTO toAutoDraftItem(CandidateItemDTO candidate) {
        return WorkingPlanMutationSupport.buildWorkingPlanItem(candidate, "initial_auto");
    }

    private List<DraftUnitDTO> defaultDraftUnits(List<DraftUnitDTO> units) {
        return units == null ? Lists.newArrayList() : units;
    }

    private List<DraftUnitDTO> buildDraftUnitsFromPlanningUnits(List<PlanningUnitDTO> units, String source) {
        List<DraftUnitDTO> result = Lists.newArrayList();
        for (PlanningUnitDTO unit : units == null ? Lists.<PlanningUnitDTO>newArrayList() : units) {
            DraftUnitDTO draftUnit = new DraftUnitDTO();
            draftUnit.setUnitId(unit.getUnitId());
            draftUnit.setTier(unit.getTier());
            draftUnit.setSchoolName(unit.getSchoolName());
            draftUnit.setSource(source);
            draftUnit.setLocked(false);
            draftUnit.setMajorItems(sortSelectedMajorsForDisplay(unit.getSelectedMajors()));
            result.add(draftUnit);
        }
        return result;
    }

    private void syncWorkingPlanUnitsWithItems(DraftPlanStateDTO draft,
                                         List<CandidateItemDTO> candidates,
                                         CandidatePoolStateDTO candidatePoolState) {
        WorkingPlanMutationSupport.syncWorkingPlanUnitsWithItems(draft, candidates, candidatePoolState);
    }

    private List<OrderedUnitDTO> buildOrderedUnitsFromOrderedItems(List<OrderedItemDTO> items,
                                                                   DraftPlanStateDTO draftPlanState,
                                                                   List<CandidateItemDTO> candidates) {
        Map<String, PlanningUnitMajorDTO> majorMap = new LinkedHashMap<String, PlanningUnitMajorDTO>();
        Map<String, CandidateItemDTO> candidateMap = candidates == null
                ? new LinkedHashMap<String, CandidateItemDTO>()
                : candidates.stream()
                .filter(candidate -> !Strings.isNullOrEmpty(candidate.getVolunteerId()))
                .collect(Collectors.toMap(CandidateItemDTO::getVolunteerId, candidate -> candidate, (left, right) -> left, LinkedHashMap::new));
        CandidateResolver candidateResolver = new CandidateResolver(candidates);
        Map<String, Integer> unitMajorCountMap = buildMajorGroupTotalMajorCountMap(candidates);
        for (DraftUnitDTO draftUnit : defaultDraftUnits(draftPlanState == null ? null : draftPlanState.getUnits())) {
            for (PlanningUnitMajorDTO major : defaultPlanningUnitMajors(draftUnit.getMajorItems())) {
                if (!Strings.isNullOrEmpty(major.getVolunteerId())) {
                    majorMap.put(major.getVolunteerId(), major);
                }
            }
        }

        Map<String, OrderedUnitDTO> unitMap = new LinkedHashMap<String, OrderedUnitDTO>();
        for (OrderedItemDTO item : defaultOrderedItems(items)) {
            String unitId = resolveDraftOrOrderedUnitId(item);
            CandidateItemDTO resolvedCandidate = candidateResolver.resolve(item);
            OrderedUnitDTO unit = unitMap.computeIfAbsent(unitId, key -> {
                OrderedUnitDTO dto = new OrderedUnitDTO();
                dto.setUnitId(key);
                dto.setTier(item.getTier());
                dto.setSchoolName(item.getSchoolName());
                dto.setSource(item.getSource());
                dto.setLocked(item.getLocked());
                dto.setPinned(item.getPinned());
                dto.setPinnedPosition(item.getPinnedPosition());
                dto.setOrderedBy(item.getOrderedBy());
                dto.setOrderReason(item.getOrderReason());
                dto.setPosition(item.getPosition());
                fillOrderedUnitGroupFields(dto, resolvedCandidate, unitMajorCountMap);
                return dto;
            });
            if (Boolean.TRUE.equals(item.getPinned())) {
                unit.setPinned(true);
                if (unit.getPinnedPosition() == null) {
                    unit.setPinnedPosition(item.getPinnedPosition());
                }
            }
            CandidateItemDTO candidate = resolvedCandidate;
            fillOrderedUnitGroupFields(unit, candidate, unitMajorCountMap);
            PlanningUnitMajorDTO major = majorMap.get(item.getVolunteerId());
            if (candidate == null) {
                candidate = candidateMap.get(item.getVolunteerId());
            }
            if (major == null) {
                major = new PlanningUnitMajorDTO();
                major.setVolunteerId(item.getVolunteerId());
                major.setMajorName(item.getMajorName());
                major.setTier(item.getTier());
                major.setSelected(true);
            }
            if (candidate != null) {
                major.setMajorId(candidate.getMajorId());
                major.setMajorCode(candidate.getMajorCode());
                major.setMajorCategoryId(candidate.getMajorCategoryId());
                major.setMajorSubCategoryId(candidate.getMajorSubCategoryId());
                // 分类名随候选带上 ✓：单元侧的专业筛选（`RepairCandidateEligibility`）按这两个名字比对 ✓。
                major.setMajorCategory(candidate.getMajorCategory());
                major.setMajorDiscipline(candidate.getMajorDiscipline());
                major.setAdmissionRatio(candidate.getAdmissionRatio());
                major.setFinalScore(candidate.getFinalScore());
                major.setIntentScore(candidate.getIntentScore());
                major.setPreferred(candidate.getPreferred());
                major.setSafetyMajor(candidate.getAdmissionRatio() != null
                        && candidate.getSchoolEnrollRatio() != null
                        && isSafetyMajorRatio(candidate.getAdmissionRatio(), candidate.getSchoolEnrollRatio()));
                major.setTuitionPerYear(candidate.getTuitionPerYear());
                major.setRankInTier(candidate.getRankInTier());
                major.setReasonCodes(defaultList(candidate.getReasonCodes()));
                major.setMajorPlanTags(defaultList(candidate.getMajorPlanTags()));
            }
            unit.getMajorItems().add(major);
            if (candidate != null) {
                unit.setProvinceName(candidate.getProvinceName());
                unit.setProvinceId(candidate.getProvinceId());
                unit.setCityId(candidate.getCityId());
                unit.setCityName(candidate.getCityName());
                unit.setSchoolLevel(candidate.getSchoolLevel());
                unit.setSchoolNature(candidate.getSchoolNature());
                unit.setSchoolCategory(candidate.getSchoolCategory());
                unit.setAdmissionRatio(candidate.getSchoolEnrollRatio());
                unit.setFinalScore(candidate.getFinalScore());
                unit.setSchoolEnrollRatio(candidate.getSchoolEnrollRatio());
            }
            if (unit.getPosition() == null || (item.getPosition() != null && item.getPosition() < unit.getPosition())) {
                unit.setPosition(item.getPosition());
            }
        }
        for (OrderedUnitDTO unit : unitMap.values()) {
            unit.setMajorItems(sortSelectedMajorsForDisplay(unit.getMajorItems()));
            if (unit.getTotalMajorCount() == null || unit.getTotalMajorCount() <= 0) {
                unit.setTotalMajorCount(defaultPlanningUnitMajors(unit.getMajorItems()).size());
            }
        }
        return Lists.newArrayList(unitMap.values());
    }

    private void fillOrderedUnitGroupFields(OrderedUnitDTO unit,
                                            CandidateItemDTO candidate,
                                            Map<String, Integer> unitMajorCountMap) {
        if (unit == null || candidate == null) {
            return;
        }
        if (Strings.isNullOrEmpty(unit.getPlanSchoolDataId())) {
            unit.setPlanSchoolDataId(candidate.getPlanSchoolDataId());
        }
        if (Strings.isNullOrEmpty(unit.getSchoolId())) {
            unit.setSchoolId(candidate.getSchoolId());
        }
        if (Strings.isNullOrEmpty(unit.getSchoolUnitCode())) {
            unit.setSchoolUnitCode(candidate.getSchoolUnitCode());
        }
        if (Strings.isNullOrEmpty(unit.getSchoolLevel())) {
            unit.setSchoolLevel(candidate.getSchoolLevel());
        }
        if (Strings.isNullOrEmpty(unit.getSchoolNature())) {
            unit.setSchoolNature(candidate.getSchoolNature());
        }
        if (Strings.isNullOrEmpty(unit.getSchoolCategory())) {
            unit.setSchoolCategory(candidate.getSchoolCategory());
        }
        Integer totalMajorCount = resolveMajorGroupTotalMajorCount(candidate, unitMajorCountMap);
        if (totalMajorCount != null && totalMajorCount > 0
                && (unit.getTotalMajorCount() == null || totalMajorCount > unit.getTotalMajorCount())) {
            unit.setTotalMajorCount(totalMajorCount);
        }
    }

    private Map<String, Integer> buildMajorGroupTotalMajorCountMap(List<CandidateItemDTO> candidates) {
        Map<String, Integer> result = new LinkedHashMap<String, Integer>();
        for (CandidateItemDTO candidate : defaultCandidates(candidates)) {
            Set<String> keys = resolveMajorGroupIdentityKeys(candidate);
            for (String key : keys) {
                result.put(key, result.getOrDefault(key, 0) + 1);
            }
        }
        return result;
    }

    private Integer resolveMajorGroupTotalMajorCount(CandidateItemDTO candidate,
                                                     Map<String, Integer> unitMajorCountMap) {
        for (String key : resolveMajorGroupIdentityKeys(candidate)) {
            Integer count = unitMajorCountMap.get(key);
            if (count != null && count > 0) {
                return count;
            }
        }
        return null;
    }

    private Set<String> resolveMajorGroupIdentityKeys(CandidateItemDTO candidate) {
        Set<String> keys = new LinkedHashSet<String>();
        if (candidate == null) {
            return keys;
        }
        addMajorGroupIdentityKey(keys, "planSchoolDataId", candidate.getPlanSchoolDataId());
        addMajorGroupIdentityKey(keys, "schoolUnitCode", candidate.getSchoolUnitCode());
        addMajorGroupIdentityKey(keys, "legacyPrefix", CandidateResolver.legacyVolunteerPrefix(candidate.getVolunteerId()));
        addMajorGroupIdentityKey(keys, "schoolName", candidate.getSchoolName());
        return keys;
    }

    private void addMajorGroupIdentityKey(Set<String> keys, String type, String value) {
        if (!Strings.isNullOrEmpty(value)) {
            keys.add(type + ":" + value.trim());
        }
    }

    private void normalizeMajorGroupUnitMetadata(PlanningStateDTO state) {
        if (state == null || !isMajorGroupMode(state.getCandidatePoolState())) {
            return;
        }
        Map<String, PlanningUnitDTO> initialUnitMap = buildInitialRecommendationUnitMap(
                state.getInitialRecommendationState() == null ? null : state.getInitialRecommendationState().getUnits());
        List<CandidateItemDTO> candidates = defaultCandidates(state.getCandidatePoolState() == null ? null : state.getCandidatePoolState().getItems());
        CandidateResolver candidateResolver = new CandidateResolver(candidates);
        Map<String, Integer> unitMajorCountMap = buildMajorGroupTotalMajorCountMap(candidates);
        normalizeOrderedUnitMetadata(state.getOrderedPlanState(), initialUnitMap, candidateResolver, unitMajorCountMap);
    }

    private Map<String, PlanningUnitDTO> buildInitialRecommendationUnitMap(List<PlanningUnitDTO> units) {
        Map<String, PlanningUnitDTO> result = new LinkedHashMap<String, PlanningUnitDTO>();
        for (PlanningUnitDTO unit : units == null ? Lists.<PlanningUnitDTO>newArrayList() : units) {
            putInitialRecommendationUnit(result, unit == null ? null : unit.getUnitId(), unit);
            putInitialRecommendationUnit(result, unit == null ? null : unit.getPlanSchoolDataId(), unit);
            putInitialRecommendationUnit(result, unit == null ? null : unit.getSchoolName(), unit);
        }
        return result;
    }

    private void putInitialRecommendationUnit(Map<String, PlanningUnitDTO> target,
                                              String key,
                                              PlanningUnitDTO unit) {
        if (!Strings.isNullOrEmpty(key) && unit != null && !target.containsKey(key)) {
            target.put(key, unit);
        }
    }

    private void normalizeOrderedUnitMetadata(OrderedPlanStateDTO orderedPlanState,
                                              Map<String, PlanningUnitDTO> initialUnitMap,
                                              CandidateResolver candidateResolver,
                                              Map<String, Integer> unitMajorCountMap) {
        if (orderedPlanState == null) {
            return;
        }
        for (OrderedUnitDTO unit : defaultOrderedUnits(orderedPlanState.getUnits())) {
            if (unit == null) {
                continue;
            }
            PlanningUnitDTO initialUnit = resolveInitialRecommendationUnit(unit, initialUnitMap);
            fillOrderedUnitGroupFieldsFromInitialUnit(unit, initialUnit);
            for (PlanningUnitMajorDTO major : defaultPlanningUnitMajors(unit.getMajorItems())) {
                CandidateItemDTO candidate = candidateResolver.resolve(major == null ? null : major.getVolunteerId());
                if (candidate != null) {
                    fillOrderedUnitGroupFields(unit, candidate, unitMajorCountMap);
                    break;
                }
            }
            if (unit.getTotalMajorCount() == null || unit.getTotalMajorCount() <= 0) {
                unit.setTotalMajorCount(defaultPlanningUnitMajors(unit.getMajorItems()).size());
            }
        }
    }

    private PlanningUnitDTO resolveInitialRecommendationUnit(OrderedUnitDTO unit,
                                                             Map<String, PlanningUnitDTO> initialUnitMap) {
        if (unit == null || initialUnitMap == null || initialUnitMap.isEmpty()) {
            return null;
        }
        for (String key : Lists.newArrayList(unit.getPlanSchoolDataId(), unit.getUnitId(), unit.getSchoolName())) {
            if (!Strings.isNullOrEmpty(key) && initialUnitMap.containsKey(key)) {
                return initialUnitMap.get(key);
            }
        }
        return null;
    }

    private void fillOrderedUnitGroupFieldsFromInitialUnit(OrderedUnitDTO unit,
                                                           PlanningUnitDTO initialUnit) {
        if (unit == null || initialUnit == null) {
            return;
        }
        if (Strings.isNullOrEmpty(unit.getPlanSchoolDataId())) {
            unit.setPlanSchoolDataId(initialUnit.getPlanSchoolDataId());
        }
        if (Strings.isNullOrEmpty(unit.getSchoolId())) {
            unit.setSchoolId(initialUnit.getSchoolId());
        }
        if (Strings.isNullOrEmpty(unit.getProvinceName())) {
            unit.setProvinceName(initialUnit.getProvinceName());
        }
        if (Strings.isNullOrEmpty(unit.getCityName())) {
            unit.setCityName(initialUnit.getCityName());
        }
        // 同上 ✓：ID 从初始单元带过来 ✓
        if (Strings.isNullOrEmpty(unit.getProvinceId())) {
            unit.setProvinceId(initialUnit.getProvinceId());
        }
        if (Strings.isNullOrEmpty(unit.getCityId())) {
            unit.setCityId(initialUnit.getCityId());
        }
        if (Strings.isNullOrEmpty(unit.getSchoolLevel())) {
            unit.setSchoolLevel(initialUnit.getSchoolLevel());
        }
        if (Strings.isNullOrEmpty(unit.getSchoolNature())) {
            unit.setSchoolNature(initialUnit.getSchoolNature());
        }
        if (Strings.isNullOrEmpty(unit.getSchoolCategory())) {
            unit.setSchoolCategory(initialUnit.getSchoolCategory());
        }
        if (unit.getSchoolEnrollRatio() == null) {
            unit.setSchoolEnrollRatio(initialUnit.getSchoolEnrollRatio());
        }
        if (unit.getAdmissionRatio() == null) {
            unit.setAdmissionRatio(initialUnit.getAdmissionRatio());
        }
        if (unit.getFinalScore() == null) {
            unit.setFinalScore(initialUnit.getFinalScore());
        }
        if (initialUnit.getTotalMajorCount() != null && initialUnit.getTotalMajorCount() > 0
                && (unit.getTotalMajorCount() == null || initialUnit.getTotalMajorCount() > unit.getTotalMajorCount())) {
            unit.setTotalMajorCount(initialUnit.getTotalMajorCount());
        }
    }

    private int autoProtectPriority(CandidateItemDTO item, String sourceProvinceName) {
        if (item == null || !"保".equals(item.getTier()) || Strings.isNullOrEmpty(sourceProvinceName)) {
            return 1;
        }
        return containsIgnoreCase(item.getProvinceName(), sourceProvinceName) ? 0 : 1;
    }

    private Comparator<DraftItemDTO> buildDraftOrderedComparator(Map<String, CandidateItemDTO> candidateMap,
                                                                String sourceProvinceName,
                                                                boolean majorGroupMode) {
        if (majorGroupMode) {
            return Comparator
                    .comparingInt((DraftItemDTO item) -> tierOrder(item.getTier()))
                    .thenComparing((DraftItemDTO item) -> orderedAdmissionRatioOf(candidateMap.get(item.getVolunteerId()), true),
                            Comparator.nullsLast(Double::compareTo))
                    .thenComparingInt((DraftItemDTO item) -> localProtectPriority(item, candidateMap, sourceProvinceName))
                    .thenComparing((DraftItemDTO item) -> futureDevelopmentScoreOf(candidateMap.get(item.getVolunteerId())),
                            Comparator.nullsLast(Comparator.reverseOrder()))
                    .thenComparing((DraftItemDTO item) -> rankInTierOf(candidateMap.get(item.getVolunteerId())),
                            Comparator.nullsLast(Integer::compareTo))
                    .thenComparing((DraftItemDTO item) -> finalScoreOf(candidateMap.get(item.getVolunteerId())),
                            Comparator.nullsLast(Comparator.reverseOrder()))
                    .thenComparing(DraftItemDTO::getVolunteerId, Comparator.nullsLast(String::compareTo));
        }
        return Comparator
                .comparingInt((DraftItemDTO item) -> tierOrder(item.getTier()))
                .thenComparingInt((DraftItemDTO item) -> localProtectPriority(item, candidateMap, sourceProvinceName))
                .thenComparing((DraftItemDTO item) -> orderedAdmissionRatioOf(candidateMap.get(item.getVolunteerId()), false),
                        Comparator.nullsLast(Double::compareTo))
                .thenComparing((DraftItemDTO item) -> futureDevelopmentScoreOf(candidateMap.get(item.getVolunteerId())),
                        Comparator.nullsLast(Comparator.reverseOrder()))
                .thenComparing((DraftItemDTO item) -> rankInTierOf(candidateMap.get(item.getVolunteerId())),
                        Comparator.nullsLast(Integer::compareTo))
                .thenComparing((DraftItemDTO item) -> finalScoreOf(candidateMap.get(item.getVolunteerId())),
                        Comparator.nullsLast(Comparator.reverseOrder()))
                .thenComparing(DraftItemDTO::getVolunteerId, Comparator.nullsLast(String::compareTo));
    }

    private Double admissionRatioOf(CandidateItemDTO item) {
        return item == null ? null : item.getAdmissionRatio();
    }

    private Double orderedAdmissionRatioOf(CandidateItemDTO item, boolean majorGroupMode) {
        if (item == null) {
            return null;
        }
        if (majorGroupMode && item.getSchoolEnrollRatio() != null) {
            return item.getSchoolEnrollRatio();
        }
        return item.getAdmissionRatio();
    }

    private Integer rankInTierOf(CandidateItemDTO item) {
        return item == null ? null : item.getRankInTier();
    }

    private Double finalScoreOf(CandidateItemDTO item) {
        return item == null ? null : item.getFinalScore();
    }

    private Double futureDevelopmentScoreOf(CandidateItemDTO item) {
        return item == null ? null : item.getFutureDevelopmentScore();
    }

    private int localProtectPriority(DraftItemDTO item,
                                     Map<String, CandidateItemDTO> candidateMap,
                                     String sourceProvinceName) {
        if (!"保".equals(item.getTier())) {
            return 1;
        }
        if (Strings.isNullOrEmpty(sourceProvinceName)) {
            return 1;
        }
        CandidateItemDTO candidateItem = candidateMap.get(item.getVolunteerId());
        if (candidateItem == null || Strings.isNullOrEmpty(candidateItem.getProvinceName())) {
            return 1;
        }
        return containsIgnoreCase(candidateItem.getProvinceName(), sourceProvinceName) ? 0 : 1;
    }

    private List<OrderedItemDTO> sortOrderedPlanItems(List<OrderedItemDTO> items,
                                                      List<CandidateItemDTO> candidates,
                                                      String sortField) {
        CandidateResolver candidateResolver = new CandidateResolver(candidates);
        return defaultOrderedItems(items).stream()
                .sorted(buildOrderedItemSortComparator(candidateResolver, sortField))
                .collect(Collectors.toList());
    }

    private List<OrderedItemDTO> sortOrderedPlanByUnit(List<OrderedItemDTO> items,
                                                       OrderedPlanStateDTO orderedPlanState,
                                                       DraftPlanStateDTO draftPlanState,
                                                       List<CandidateItemDTO> candidates,
                                                       String sortField) {
        List<OrderedUnitDTO> units = defaultOrderedUnits(orderedPlanState == null ? null : orderedPlanState.getUnits());
        if (units.isEmpty()) {
            units = buildOrderedUnitsFromOrderedItems(items, draftPlanState, candidates);
        }
        Map<String, List<OrderedItemDTO>> itemGroups = defaultOrderedItems(items).stream()
                .collect(Collectors.groupingBy(this::resolveDraftOrOrderedUnitId, LinkedHashMap::new, Collectors.toList()));
        CandidateResolver candidateResolver = new CandidateResolver(candidates);
        List<OrderedUnitDTO> sortedUnits = units.stream()
                .sorted(buildOrderedUnitSortComparator(candidateResolver, sortField))
                .collect(Collectors.toList());
        List<OrderedItemDTO> result = Lists.newArrayList();
        for (OrderedUnitDTO unit : sortedUnits) {
            result.addAll(itemGroups.getOrDefault(unit.getUnitId(), Lists.newArrayList()));
        }
        return result.isEmpty() ? items : result;
    }

    private Comparator<OrderedItemDTO> buildOrderedItemSortComparator(CandidateResolver candidateResolver,
                                                                      String sortField) {
        return (left, right) -> compareOrderedCandidates(
                left == null ? null : candidateResolver.resolve(left),
                right == null ? null : candidateResolver.resolve(right),
                sortField);
    }

    private Comparator<OrderedUnitDTO> buildOrderedUnitSortComparator(CandidateResolver candidateResolver,
                                                                      String sortField) {
        return (left, right) -> compareOrderedUnits(left, right, candidateResolver, sortField);
    }

    private int compareOrderedSortValues(Double left, Double right, boolean descending) {
        boolean leftMissing = left == null;
        boolean rightMissing = right == null;
        if (leftMissing && rightMissing) {
            return 0;
        }
        if (leftMissing) {
            return 1;
        }
        if (rightMissing) {
            return -1;
        }
        int compared = Double.compare(left, right);
        return descending ? -compared : compared;
    }

    private int compareOrderedCandidates(CandidateItemDTO left, CandidateItemDTO right, String sortField) {
        for (OrderedSortKey key : resolveOrderedSortKeys(sortField)) {
            int compared = compareOrderedSortValues(resolveCandidateSortValue(left, key.field), resolveCandidateSortValue(right, key.field), key.descending);
            if (compared != 0) {
                return compared;
            }
        }
        return compareNullableText(resolveCandidateSchoolGroupKey(left), resolveCandidateSchoolGroupKey(right));
    }

    private int compareOrderedUnits(OrderedUnitDTO left,
                                    OrderedUnitDTO right,
                                    CandidateResolver candidateResolver,
                                    String sortField) {
        for (OrderedSortKey key : resolveOrderedSortKeys(sortField)) {
            int compared = compareOrderedSortValues(resolveUnitSortValue(left, candidateResolver, key.field), resolveUnitSortValue(right, candidateResolver, key.field), key.descending);
            if (compared != 0) {
                return compared;
            }
        }
        return compareNullableText(resolveUnitSchoolGroupKey(left), resolveUnitSchoolGroupKey(right));
    }

    private Double resolveCandidateSortValue(CandidateItemDTO candidate, String sortField) {
        if (candidate == null) {
            return null;
        }
        if ("admissionRatio".equals(sortField)) {
            return candidate.getAdmissionRatio();
        }
        if ("schoolRank".equals(sortField)) {
            return candidate.getSchoolRank() == null ? null : candidate.getSchoolRank().doubleValue();
        }
        return candidate.getFinalScore();
    }

    private Double resolveUnitSortValue(OrderedUnitDTO unit,
                                        CandidateResolver candidateResolver,
                                        String sortField) {
        if (unit == null) {
            return null;
        }
        if ("admissionRatio".equals(sortField)) {
            return unit.getAdmissionRatio() == null ? unit.getSchoolEnrollRatio() : unit.getAdmissionRatio();
        }
        if ("finalScore".equals(sortField)) {
            return unit.getFinalScore();
        }
        return defaultPlanningUnitMajors(unit.getMajorItems()).stream()
                .map(major -> candidateResolver.resolve(major == null ? null : major.getVolunteerId()))
                .filter(Objects::nonNull)
                .map(CandidateItemDTO::getSchoolRank)
                .filter(Objects::nonNull)
                .min(Integer::compareTo)
                .map(Integer::doubleValue)
                .orElse(null);
    }

    private List<OrderedSortKey> resolveOrderedSortKeys(String sortField) {
        List<OrderedSortKey> keys = Lists.newArrayList();
        if ("finalScore".equals(sortField)) {
            keys.add(new OrderedSortKey("finalScore", true));
            keys.add(new OrderedSortKey("admissionRatio", false));
            keys.add(new OrderedSortKey("schoolRank", false));
            return keys;
        }
        if ("schoolRank".equals(sortField)) {
            keys.add(new OrderedSortKey("schoolRank", false));
            keys.add(new OrderedSortKey("admissionRatio", false));
            keys.add(new OrderedSortKey("finalScore", true));
            return keys;
        }
        keys.add(new OrderedSortKey("admissionRatio", false));
        keys.add(new OrderedSortKey("schoolRank", false));
        keys.add(new OrderedSortKey("finalScore", true));
        return keys;
    }

    private String resolveCandidateSchoolGroupKey(CandidateItemDTO candidate) {
        if (candidate == null) {
            return "";
        }
        return firstNonEmpty(candidate.getPlanSchoolDataId(), candidate.getSchoolId(), candidate.getSchoolName());
    }

    private String resolveUnitSchoolGroupKey(OrderedUnitDTO unit) {
        if (unit == null) {
            return "";
        }
        return firstNonEmpty(unit.getUnitId(), unit.getSchoolName());
    }

    private String firstNonEmpty(String... values) {
        for (String value : values) {
            if (!Strings.isNullOrEmpty(value)) {
                return value;
            }
        }
        return "";
    }

    private int compareNullableText(String left, String right) {
        return String.valueOf(left).compareTo(String.valueOf(right));
    }

    private static class OrderedSortKey {
        private final String field;
        private final boolean descending;

        private OrderedSortKey(String field, boolean descending) {
            this.field = field;
            this.descending = descending;
        }
    }

    private Map<String, CandidateItemDTO> buildCandidateMap(List<CandidateItemDTO> candidates) {
        return defaultCandidates(candidates).stream()
                .filter(candidate -> !Strings.isNullOrEmpty(candidate.getVolunteerId()))
                .collect(Collectors.toMap(CandidateItemDTO::getVolunteerId, candidate -> candidate, (left, right) -> left, LinkedHashMap::new));
    }

    private static class WorkspaceCandidateRef {
        private final String volunteerId;
        private final String schoolName;
        private final String majorName;

        private WorkspaceCandidateRef(String volunteerId, String schoolName, String majorName) {
            this.volunteerId = volunteerId;
            this.schoolName = schoolName;
            this.majorName = majorName;
        }

        private String getVolunteerId() {
            return volunteerId;
        }

        private OrderedItemDTO toOrderedItem() {
            OrderedItemDTO item = new OrderedItemDTO();
            item.setVolunteerId(volunteerId);
            item.setSchoolName(schoolName);
            item.setMajorName(majorName);
            return item;
        }
    }

    private static class CandidateResolver {
        private final Map<String, CandidateItemDTO> byVolunteerId = new LinkedHashMap<String, CandidateItemDTO>();
        private final Map<String, CandidateItemDTO> byLegacyVolunteerPrefix = new LinkedHashMap<String, CandidateItemDTO>();
        private final Set<String> duplicatedLegacyVolunteerPrefixes = new HashSet<String>();
        private final Map<String, CandidateItemDTO> bySchoolAndMajor = new LinkedHashMap<String, CandidateItemDTO>();
        private final Set<String> duplicatedSchoolAndMajors = new HashSet<String>();

        private CandidateResolver(List<CandidateItemDTO> candidates) {
            for (CandidateItemDTO candidate : candidates == null ? Lists.<CandidateItemDTO>newArrayList() : candidates) {
                if (candidate == null) {
                    continue;
                }
                putUnique(byVolunteerId, null, candidate.getVolunteerId(), candidate);
                putUnique(byLegacyVolunteerPrefix, duplicatedLegacyVolunteerPrefixes,
                        legacyVolunteerPrefix(candidate.getVolunteerId()), candidate);
                putUnique(bySchoolAndMajor, duplicatedSchoolAndMajors,
                        schoolAndMajorKey(candidate.getSchoolName(), candidate.getMajorName()), candidate);
            }
        }

        private CandidateItemDTO resolve(OrderedItemDTO item) {
            if (item == null) {
                return null;
            }
            CandidateItemDTO candidate = resolve(item.getVolunteerId());
            if (candidate != null) {
                return candidate;
            }
            return resolveBySchoolAndMajor(item.getSchoolName(), item.getMajorName());
        }

        private CandidateItemDTO resolve(String volunteerId) {
            if (Strings.isNullOrEmpty(volunteerId)) {
                return null;
            }
            CandidateItemDTO candidate = byVolunteerId.get(volunteerId);
            if (candidate != null) {
                return candidate;
            }
            String legacyPrefix = legacyVolunteerPrefix(volunteerId);
            if (!Strings.isNullOrEmpty(legacyPrefix) && !duplicatedLegacyVolunteerPrefixes.contains(legacyPrefix)) {
                return byLegacyVolunteerPrefix.get(legacyPrefix);
            }
            return null;
        }

        private CandidateItemDTO resolveBySchoolAndMajor(String schoolName, String majorName) {
            String key = schoolAndMajorKey(schoolName, majorName);
            if (Strings.isNullOrEmpty(key) || duplicatedSchoolAndMajors.contains(key)) {
                return null;
            }
            return bySchoolAndMajor.get(key);
        }

        private static void putUnique(Map<String, CandidateItemDTO> target,
                                      Set<String> duplicates,
                                      String key,
                                      CandidateItemDTO candidate) {
            if (Strings.isNullOrEmpty(key)) {
                return;
            }
            if (target.containsKey(key)) {
                if (duplicates != null) {
                    duplicates.add(key);
                }
                return;
            }
            target.put(key, candidate);
        }

        private static String legacyVolunteerPrefix(String volunteerId) {
            if (Strings.isNullOrEmpty(volunteerId)) {
                return null;
            }
            String[] parts = volunteerId.split("_", -1);
            if (parts.length < 2 || Strings.isNullOrEmpty(parts[0]) || Strings.isNullOrEmpty(parts[1])) {
                return null;
            }
            return parts[0] + "_" + parts[1];
        }

        private static String schoolAndMajorKey(String schoolName, String majorName) {
            if (Strings.isNullOrEmpty(schoolName) || Strings.isNullOrEmpty(majorName)) {
                return null;
            }
            return schoolName.trim() + "\n" + majorName.trim();
        }
    }

    private String normalizeOrderedSortField(String sortField) {
        if ("admissionRatio".equals(sortField) || "schoolRank".equals(sortField) || "finalScore".equals(sortField)) {
            return sortField;
        }
        return "admissionRatio";
    }

    private void markOrderedItemsSortedByUser(OrderedPlanStateDTO orderedPlanState, String sortField) {
        for (OrderedItemDTO item : defaultOrderedItems(orderedPlanState == null ? null : orderedPlanState.getItems())) {
            item.setOrderedBy("user");
            item.setOrderReason("user_sort_" + sortField);
        }
        for (OrderedUnitDTO unit : defaultOrderedUnits(orderedPlanState == null ? null : orderedPlanState.getUnits())) {
            unit.setOrderedBy("user");
            unit.setOrderReason("user_sort_" + sortField);
        }
    }

    private Map<String, Integer> buildOrderedPositionMap(List<OrderedItemDTO> items) {
        Map<String, Integer> result = new LinkedHashMap<String, Integer>();
        for (OrderedItemDTO item : defaultOrderedItems(items)) {
            if (!Strings.isNullOrEmpty(item.getVolunteerId())) {
                result.put(item.getVolunteerId(), item.getPosition());
            }
        }
        return result;
    }

    private List<String> buildOrderedUnitIds(List<OrderedItemDTO> items) {
        List<String> unitIds = Lists.newArrayList();
        for (OrderedItemDTO item : defaultOrderedItems(items)) {
            String unitId = resolveDraftOrOrderedUnitId(item);
            if (!Strings.isNullOrEmpty(unitId) && !unitIds.contains(unitId)) {
                unitIds.add(unitId);
            }
        }
        return unitIds;
    }

    private OrderedItemDTO findOrderedItem(List<OrderedItemDTO> items, String volunteerId) {
        return items.stream().filter(item -> volunteerId.equals(item.getVolunteerId())).findFirst().orElse(null);
    }

    private int tierOrder(String tier) {
        if ("冲".equals(tier)) {
            return 0;
        }
        if ("稳".equals(tier)) {
            return 1;
        }
        if ("保".equals(tier)) {
            return 2;
        }
        return 3;
    }

    private void recalculateOrderedSummary(OrderedPlanStateDTO orderedPlanState, CandidatePoolStateDTO candidatePoolState) {
        boolean majorGroupMode = isMajorGroupMode(candidatePoolState);
        int unitTotal = countOrderedSummaryTotal(orderedPlanState.getItems(), majorGroupMode);
        int targetUnitCount = candidatePoolState != null && candidatePoolState.getRequiredCount() != null
                ? candidatePoolState.getRequiredCount() : 0;
        int sprintUnits = countOrderedTier(orderedPlanState.getItems(), "冲", majorGroupMode);
        int safeUnits = countOrderedTier(orderedPlanState.getItems(), "稳", majorGroupMode);
        int protectUnits = countOrderedTier(orderedPlanState.getItems(), "保", majorGroupMode);
        orderedPlanState.getSummary().setUnitTotal(unitTotal);
        orderedPlanState.getSummary().setTargetUnitCount(targetUnitCount);
        orderedPlanState.getSummary().setTotal(unitTotal);
        orderedPlanState.getSummary().setTargetCount(targetUnitCount);
        orderedPlanState.getSummary().getUnitTierCounts().put("冲", sprintUnits);
        orderedPlanState.getSummary().getUnitTierCounts().put("稳", safeUnits);
        orderedPlanState.getSummary().getUnitTierCounts().put("保", protectUnits);
        orderedPlanState.getSummary().getTierCounts().put("冲", sprintUnits);
        orderedPlanState.getSummary().getTierCounts().put("稳", safeUnits);
        orderedPlanState.getSummary().getTierCounts().put("保", protectUnits);

        boolean sequenceOk = true;
        int previousOrder = -1;
        for (OrderedItemDTO item : orderedPlanState.getItems()) {
            int currentOrder = tierOrder(item.getTier());
            if (currentOrder < previousOrder) {
                sequenceOk = false;
                break;
            }
            previousOrder = currentOrder;
        }
        orderedPlanState.getSummary().setSequenceOk(sequenceOk);
        orderedPlanState.getSummary().setGradientOk(sequenceOk);
        orderedPlanState.getSummary().setSafetyOk(
                orderedPlanState.getSummary().getTierCounts().get("保") != null
                        && orderedPlanState.getSummary().getTierCounts().get("保") > 0);
    }

    private CandidateItemDTO findCandidate(List<CandidateItemDTO> items, String volunteerId) {
        return WorkingPlanMutationSupport.findCandidate(items, volunteerId);
    }

    private void recalculateWorkingPlanSummary(DraftPlanStateDTO draft, CandidatePoolStateDTO candidatePoolState) {
        WorkingPlanMutationSupport.recalculateWorkingPlanSummary(draft, candidatePoolState);
    }

    private void recalculateCandidatePoolSummary(CandidatePoolStateDTO candidatePoolState) {
        if (candidatePoolState == null) {
            return;
        }
        List<CandidateItemDTO> items = defaultCandidates(candidatePoolState.getItems());
        int entryTotal = items.size();
        int unitTotal = countCandidateUnits(items);
        int sprintEntryCount = countByTier(items, "冲");
        int safeEntryCount = countByTier(items, "稳");
        int protectEntryCount = countByTier(items, "保");
        int sprintUnitCount = countCandidateUnitsByTier(items, "冲");
        int safeUnitCount = countCandidateUnitsByTier(items, "稳");
        int protectUnitCount = countCandidateUnitsByTier(items, "保");
        candidatePoolState.getSummary().setEntryTotal(entryTotal);
        candidatePoolState.getSummary().setUnitTotal(unitTotal);
        candidatePoolState.getSummary().setTotal(entryTotal);
        candidatePoolState.getSummary().getEntryTierCounts().put("冲", sprintEntryCount);
        candidatePoolState.getSummary().getEntryTierCounts().put("稳", safeEntryCount);
        candidatePoolState.getSummary().getEntryTierCounts().put("保", protectEntryCount);
        candidatePoolState.getSummary().getUnitTierCounts().put("冲", sprintUnitCount);
        candidatePoolState.getSummary().getUnitTierCounts().put("稳", safeUnitCount);
        candidatePoolState.getSummary().getUnitTierCounts().put("保", protectUnitCount);
        candidatePoolState.getSummary().getTierCounts().put("冲", sprintEntryCount);
        candidatePoolState.getSummary().getTierCounts().put("稳", safeEntryCount);
        candidatePoolState.getSummary().getTierCounts().put("保", protectEntryCount);
    }

    private void populateCandidatePoolSourceSummary(CandidatePoolStateDTO candidatePoolState,
                                                    List<CandidateItemDTO> externalItems,
                                                    List<CandidateItemDTO> normalizedItems) {
        if (candidatePoolState == null) {
            return;
        }
        CandidatePoolStateDTO.SourceSummary sourceSummary = candidatePoolState.getSourceSummary();
        if (sourceSummary == null) {
            sourceSummary = new CandidatePoolStateDTO.SourceSummary();
            candidatePoolState.setSourceSummary(sourceSummary);
        }

        List<CandidateItemDTO> external = defaultCandidates(externalItems);
        List<CandidateItemDTO> normalized = defaultCandidates(normalizedItems);
        sourceSummary.setExternalEntryTotal(external.size());
        sourceSummary.setExternalUnitTotal(countCandidateUnits(external));
        sourceSummary.setExternalEntryTierCounts(buildCandidateEntryTierCounts(external));
        sourceSummary.setExternalUnitTierCounts(buildCandidateUnitTierCounts(external));
        sourceSummary.setNormalizedEntryTotal(normalized.size());
        sourceSummary.setNormalizedUnitTotal(countCandidateUnits(normalized));
        sourceSummary.setNormalizedEntryTierCounts(buildCandidateEntryTierCounts(normalized));
        sourceSummary.setNormalizedUnitTierCounts(buildCandidateUnitTierCounts(normalized));
    }

    private Map<String, Integer> buildCandidateEntryTierCounts(List<CandidateItemDTO> items) {
        Map<String, Integer> counts = new LinkedHashMap<String, Integer>();
        for (String tier : Lists.newArrayList("冲", "稳", "保")) {
            counts.put(tier, countByTier(defaultCandidates(items), tier));
        }
        return counts;
    }

    private Map<String, Integer> buildCandidateUnitTierCounts(List<CandidateItemDTO> items) {
        Map<String, Integer> counts = new LinkedHashMap<String, Integer>();
        for (String tier : Lists.newArrayList("冲", "稳", "保")) {
            counts.put(tier, countCandidateUnitsByTier(defaultCandidates(items), tier));
        }
        return counts;
    }

    private int countWorkingPlanSummaryTotal(List<DraftItemDTO> items, boolean majorGroupMode) {
        if (!majorGroupMode) {
            return items == null ? 0 : items.size();
        }
        return (int) defaultDraftItems(items).stream()
                .map(this::resolveDraftOrOrderedUnitId)
                .filter(Objects::nonNull)
                .distinct()
                .count();
    }

    private int countOrderedSummaryTotal(List<OrderedItemDTO> items, boolean majorGroupMode) {
        if (!majorGroupMode) {
            return items == null ? 0 : items.size();
        }
        return (int) defaultOrderedItems(items).stream()
                .map(this::resolveDraftOrOrderedUnitId)
                .filter(Objects::nonNull)
                .distinct()
                .count();
    }

    private int countOrderedTier(List<OrderedItemDTO> items, String tier, boolean majorGroupMode) {
        if (!majorGroupMode) {
            return (int) defaultOrderedItems(items).stream().filter(item -> tier.equals(item.getTier())).count();
        }
        return (int) defaultOrderedItems(items).stream()
                .filter(item -> tier.equals(item.getTier()))
                .map(this::resolveDraftOrOrderedUnitId)
                .filter(Objects::nonNull)
                .distinct()
                .count();
    }

    private List<DraftItemDTO> defaultDraftItems(List<DraftItemDTO> items) {
        return items == null ? Lists.newArrayList() : items;
    }

    private List<OrderedItemDTO> defaultOrderedItems(List<OrderedItemDTO> items) {
        return items == null ? Lists.newArrayList() : items;
    }

    private List<OrderedUnitDTO> defaultOrderedUnits(List<OrderedUnitDTO> units) {
        return units == null ? Lists.newArrayList() : units;
    }

    private String resolveDraftOrOrderedUnitId(DraftItemDTO item) {
        if (item == null) {
            return null;
        }
        return resolveDraftOrOrderedUnitId(item.getVolunteerId(), item.getSchoolName());
    }

    private String resolveDraftOrOrderedUnitId(OrderedItemDTO item) {
        if (item == null) {
            return null;
        }
        return resolveDraftOrOrderedUnitId(item.getVolunteerId(), item.getSchoolName());
    }

    private String resolveDraftOrOrderedUnitId(String volunteerId, String schoolName) {
        if (!Strings.isNullOrEmpty(volunteerId)) {
            int index = volunteerId.indexOf('_');
            if (index > 0) {
                return volunteerId.substring(0, index);
            }
            return volunteerId;
        }
        return schoolName;
    }

    /**
     * 工作台写入口的**收敛落盘点**（H2：单次 CAS，期望值是 {@code state} 携带的基线；
     * 输赢由返回值交给调用方裁决——用户动作输=响亮冲突，纯内存变换输=重读重放）。
     */
    private boolean saveWorkingPlanState(Long chatSessionId, PlanningStateDTO state, String scene) {
        state.setSessionId(chatSessionId);
        state.setVersion((state.getVersion() == null ? 0 : state.getVersion()) + 1);
        state.setPhase("drafting");
        boolean orderedSynced = syncOrderedPlanWithDraft(state);
        state.getStaleFlags().setOrderedPlan(!orderedSynced);
        ReviewInvalidationPolicy.markPlanStructureStale(state);
        return savePlanningState(chatSessionId, state, scene);
    }

    /** 排序态落盘的收敛点（同上）。 */
    private boolean saveOrderedState(Long chatSessionId, PlanningStateDTO state, String scene) {
        state.setSessionId(chatSessionId);
        state.setVersion((state.getVersion() == null ? 0 : state.getVersion()) + 1);
        state.setPhase("ordered");
        state.getStaleFlags().setOrderedPlan(false);
        ReviewInvalidationPolicy.markPlanStructureStale(state);
        return savePlanningState(chatSessionId, state, scene);
    }

    /**
     * RETRY_REPLAY：CAS 输 → 重读最新 → {@code reapply} 把同一变换重新施加到最新态 → 再 CAS
     * （≤{@value #WRITE_CAS_ATTEMPTS} 次）；重试耗尽**响亮冲突**（40901 语义面），绝不静默丢。
     * 首次尝试由调用方先施加变换并计算副作用（行为事件只记一次）。
     */
    private PlanningStateDTO saveWorkingPlanStateWithReplay(Long chatSessionId,
                                                            PlanningStateDTO state,
                                                            String scene,
                                                            Consumer<PlanningStateDTO> reapply) {
        for (int attempt = 0; attempt < WRITE_CAS_ATTEMPTS; attempt++) {
            if (attempt > 0) {
                reloadPlanningState(chatSessionId, state);
                if (reapply != null) {
                    reapply.accept(state);
                }
            }
            if (saveWorkingPlanState(chatSessionId, state, scene)) {
                return state;
            }
        }
        throw writeCasConflict(scene);
    }

    /** RETRY_REPLAY（排序态收敛点版本）。 */
    private PlanningStateDTO saveOrderedStateWithReplay(Long chatSessionId,
                                                        PlanningStateDTO state,
                                                        String scene,
                                                        Consumer<PlanningStateDTO> reapply) {
        for (int attempt = 0; attempt < WRITE_CAS_ATTEMPTS; attempt++) {
            if (attempt > 0) {
                reloadPlanningState(chatSessionId, state);
                if (reapply != null) {
                    reapply.accept(state);
                }
            }
            if (saveOrderedState(chatSessionId, state, scene)) {
                return state;
            }
        }
        throw writeCasConflict(scene);
    }

    private void applyPlanGenerationMetadata(PlanningStateDTO state,
                                             String mode,
                                             boolean allowAutoComplete,
                                             int respectedPinnedCount,
                                             int preservedManualOrderCount) {
        if (state.getPlanGenerationState() == null) {
            state.setPlanGenerationState(new PlanGenerationStateDTO());
        }
        state.getPlanGenerationState().setMode(mode);
        state.getPlanGenerationState().setSourceVersion(state.getVersion());
        state.getPlanGenerationState().setGeneratedAt(OffsetDateTime.now().toString());
        state.getPlanGenerationState().setUsedOverlayVersion(
                state.getRecommendationOverlayState() == null ? null : state.getRecommendationOverlayState().getSourceVersion());
        state.getPlanGenerationState().setAllowAutoComplete(allowAutoComplete);
        state.getPlanGenerationState().setRespectedPinnedCount(respectedPinnedCount);
        state.getPlanGenerationState().setPreservedManualOrderCount(preservedManualOrderCount);

        OrderedPlanStateDTO orderedPlanState = state.getOrderedPlanState();
        orderedPlanState.setGenerationMode(mode);
        orderedPlanState.setAutoCompleted(allowAutoComplete);
        orderedPlanState.setGradientAdjusted(Boolean.TRUE.equals(orderedPlanState.getSummary().getGradientOk()));
        orderedPlanState.setPreservedPinnedCount(respectedPinnedCount);
        orderedPlanState.setPreservedManualOrderCount(preservedManualOrderCount);
    }

    private int countManualOrderedItems(OrderedPlanStateDTO orderedPlanState) {
        return orderedPlanState == null || orderedPlanState.getItems() == null ? 0
                : (int) orderedPlanState.getItems().stream().filter(item -> "user".equals(item.getOrderedBy())).count();
    }

    private boolean syncOrderedPlanWithDraft(PlanningStateDTO state) {
        OrderedPlanStateDTO orderedPlanState = state.getOrderedPlanState();
        if (orderedPlanState == null || orderedPlanState.getItems() == null) {
            return false;
        }
        if (orderedPlanState.getItems().isEmpty()) {
            if (state.getDraftPlanState() == null || state.getDraftPlanState().getItems() == null
                    || state.getDraftPlanState().getItems().isEmpty()) {
                return false;
            }
            List<CandidateItemDTO> effectiveCandidates = resolveEffectiveCandidates(null, state.getSessionId(), state, false);
            orderedPlanState.setItems(buildOrderedItemsFromWorkingPlan(
                    state.getDraftPlanState(),
                    state.getCandidatePoolState(),
                    effectiveCandidates,
                    new LinkedHashMap<String, OrderedItemDTO>(),
                    false));
            if (isMajorGroupMode(state.getCandidatePoolState())) {
                orderedPlanState.setUnits(buildOrderedUnitsFromOrderedItems(orderedPlanState.getItems(), state.getDraftPlanState(), effectiveCandidates));
            }
            recalculateOrderedSummary(orderedPlanState, state.getCandidatePoolState());
            state.setOrderedPlanState(orderedPlanState);
            return true;
        }

        Map<String, DraftItemDTO> draftItemMap = state.getDraftPlanState().getItems().stream()
                .collect(Collectors.toMap(DraftItemDTO::getVolunteerId, item -> item, (left, right) -> left, LinkedHashMap::new));
        List<OrderedItemDTO> synced = new ArrayList<OrderedItemDTO>();
        for (OrderedItemDTO orderedItem : orderedPlanState.getItems()) {
            DraftItemDTO draftItem = draftItemMap.remove(orderedItem.getVolunteerId());
            if (draftItem == null) {
                continue;
            }
            OrderedItemDTO updated = new OrderedItemDTO();
            updated.setVolunteerId(draftItem.getVolunteerId());
            updated.setTier(draftItem.getTier());
            updated.setSchoolName(draftItem.getSchoolName());
            updated.setMajorName(draftItem.getMajorName());
            updated.setLocked(draftItem.getLocked());
            updated.setSource(draftItem.getSource());
            updated.setOrderedBy(Strings.isNullOrEmpty(orderedItem.getOrderedBy()) ? "user" : orderedItem.getOrderedBy());
            updated.setOrderReason(Strings.isNullOrEmpty(orderedItem.getOrderReason()) ? "draft_sync" : orderedItem.getOrderReason());
            synced.add(updated);
        }

        for (DraftItemDTO draftItem : state.getDraftPlanState().getItems()) {
            if (!draftItemMap.containsKey(draftItem.getVolunteerId())) {
                continue;
            }
            OrderedItemDTO appended = new OrderedItemDTO();
            appended.setVolunteerId(draftItem.getVolunteerId());
            appended.setTier(draftItem.getTier());
            appended.setSchoolName(draftItem.getSchoolName());
            appended.setMajorName(draftItem.getMajorName());
            appended.setLocked(draftItem.getLocked());
            appended.setSource(draftItem.getSource());
            appended.setPinned(false);
            appended.setOrderedBy("system");
            appended.setOrderReason("append_new_draft");
            synced.add(appended);
        }

        orderedPlanState.setItems(OrderedPlanPositioningSupport.rebuildItems(synced));
        if (isMajorGroupMode(state.getCandidatePoolState())) {
            List<CandidateItemDTO> effectiveCandidates = resolveEffectiveCandidates(null, state.getSessionId(), state, false);
            orderedPlanState.setUnits(buildOrderedUnitsFromOrderedItems(orderedPlanState.getItems(), state.getDraftPlanState(), effectiveCandidates));
        }
        recalculateOrderedSummary(orderedPlanState, state.getCandidatePoolState());
        state.setOrderedPlanState(orderedPlanState);
        return true;
    }

    private static class FutureDevelopmentSignals {
        private boolean enabled = false;
        private boolean publicSectorBias = false;
        private boolean stabilityBias = false;
    }
}
