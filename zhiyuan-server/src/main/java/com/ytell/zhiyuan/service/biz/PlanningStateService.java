package com.ytell.zhiyuan.service.biz;

import com.alibaba.fastjson.JSONObject;
import com.google.common.base.Strings;
import com.google.common.collect.Lists;
import com.ytell.zhiyuan.common.constants.ChatSessionExtraDataConstants;
import com.ytell.zhiyuan.common.exception.BusinessException;
import com.ytell.zhiyuan.common.util.ExcelUtil;
import com.ytell.zhiyuan.manager.MajorExtraDataManager;
import com.ytell.zhiyuan.model.dto.CreateSessionReq;
import com.ytell.zhiyuan.model.dto.UserProfileData;
import com.ytell.zhiyuan.model.dto.inner.VolunteerRecommendListResponse;
import com.ytell.zhiyuan.model.dto.planning.*;
import com.ytell.zhiyuan.model.entity.biz.ChatSessionExtraData;
import com.ytell.zhiyuan.model.enums.DataType;
import com.ytell.zhiyuan.model.vo.MajorExtraDataVO;
import com.ytell.zhiyuan.service.shared.ChatSessionExtraDataSharedService;
import com.ytell.zhiyuan.service.volunteer.VolunteerIntervalService;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import java.time.OffsetDateTime;
import java.util.ArrayList;
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
import java.util.stream.Collectors;

@Slf4j
@Service
public class PlanningStateService {

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

    @Autowired
    private ChatSessionExtraDataSharedService chatSessionExtraDataSharedService;

    @Autowired
    private VolunteerBizService volunteerBizService;

    @Autowired
    private VolunteerDataProvider volunteerDataProvider;

    @Autowired
    private PlanningExcelExportBuilder planningExcelExportBuilder;

    @Autowired
    private VolunteerIntervalService volunteerIntervalService;

    @Autowired
    private MajorExtraDataManager majorExtraDataManager;

    public PlanningStateDTO getPlanningState(Long chatSessionId) {
        PlanningStateDTO state = loadPlanningState(chatSessionId);
        state.setSessionId(chatSessionId);
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

    public PlanningWorkspaceStateRes buildPlanningWorkspaceStateRes(PlanningStateDTO state) {
        PlanningWorkspaceStateRes res = new PlanningWorkspaceStateRes();
        res.setSessionId(state.getSessionId());
        res.setVersion(state.getVersion());
        res.setPhase(state.getPhase());
        res.setStaleFlags(state.getStaleFlags());
        res.setPlanGenerationState(state.getPlanGenerationState());
        res.setCandidatePoolState(buildWorkspaceCandidatePoolState(state));
        res.setCandidateViewState(state.getCandidateViewState());
        res.setDraftPlanState(state.getDraftPlanState());
        res.setOrderedPlanState(state.getOrderedPlanState());
        res.setReviewState(state.getReviewState());
        res.setPendingActions(state.getPendingActions());
        res.setOperationLogs(state.getOperationLogs());
        res.setWorkflowStatus(buildWorkflowStatus(state));
        res.setBehaviorEvents(defaultBehaviorEvents(state.getBehaviorEvents()));
        return res;
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
        target.setSummary(source.getSummary());
        Set<String> workspaceVolunteerIds = collectWorkspaceCandidateVolunteerIds(state);
        if (!workspaceVolunteerIds.isEmpty()) {
            CandidateResolver resolver = new CandidateResolver(mergeOverlayIntoCandidates(source.getItems(), state.getRecommendationOverlayState()));
            target.setItems(workspaceVolunteerIds.stream()
                    .map(volunteerId -> copyCandidateForWorkspaceVolunteerId(resolver.resolve(volunteerId), volunteerId))
                    .filter(Objects::nonNull)
                    .collect(Collectors.collectingAndThen(
                            Collectors.toMap(CandidateItemDTO::getVolunteerId, item -> item, (left, right) -> left, LinkedHashMap::new),
                            map -> Lists.newArrayList(map.values()))));
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

    private PlanningWorkflowStatusDTO buildWorkflowStatus(PlanningStateDTO state) {
        PlanningWorkflowStatusDTO status = new PlanningWorkflowStatusDTO();
        CandidatePoolStateDTO candidatePoolState = state == null ? null : state.getCandidatePoolState();
        String candidateStatus = candidatePoolState == null ? null : candidatePoolState.getStatusCode();
        if (Strings.isNullOrEmpty(candidateStatus) || "not_generated".equals(candidateStatus)) {
            boolean hasGeneratedAt = candidatePoolState != null && !Strings.isNullOrEmpty(candidatePoolState.getGeneratedAt());
            boolean hasSummary = candidatePoolState != null && candidatePoolState.getSummary() != null
                    && valueOrZero(candidatePoolState.getSummary().getTotal()) > 0;
            candidateStatus = hasGeneratedAt || hasSummary ? resolveCandidatePoolStatus(candidatePoolState) : "not_generated";
        }
        applyCandidateWorkflowStatus(status, candidateStatus, candidatePoolState);
        applyPlanWorkflowStatus(status, state);
        applyReviewWorkflowStatus(status, state);
        applyExportWorkflowStatus(status, state);
        return status;
    }

    private void applyCandidateWorkflowStatus(PlanningWorkflowStatusDTO status,
                                              String candidateStatus,
                                              CandidatePoolStateDTO candidatePoolState) {
        status.setCandidateStatus(candidateStatus);
        if ("empty".equals(candidateStatus)) {
            status.setCandidateMessage("当前条件下没有可用志愿候选，请检查专项资格、批次、分数线或筛选条件");
        } else if ("low_count".equals(candidateStatus)) {
            status.setCandidateMessage("当前条件下可用候选偏少，方案选择空间有限");
        } else if ("failed".equals(candidateStatus)) {
            status.setCandidateMessage("候选生成失败，请稍后重试");
        } else if ("ready".equals(candidateStatus)) {
            status.setCandidateMessage("候选池已生成");
        } else {
            status.setCandidateStatus("not_generated");
            status.setCandidateMessage("候选池尚未生成");
        }
        if (candidatePoolState != null && !Strings.isNullOrEmpty(candidatePoolState.getStatusMessage())
                && !"not_generated".equals(candidatePoolState.getStatusCode())) {
            status.setCandidateMessage(candidatePoolState.getStatusMessage());
        }
    }

    private void applyPlanWorkflowStatus(PlanningWorkflowStatusDTO status, PlanningStateDTO state) {
        DraftPlanStateDTO draft = state == null ? null : state.getDraftPlanState();
        OrderedPlanStateDTO ordered = state == null ? null : state.getOrderedPlanState();
        boolean hasDraft = draft != null && draft.getItems() != null && !draft.getItems().isEmpty();
        boolean hasOrdered = ordered != null && ordered.getItems() != null && !ordered.getItems().isEmpty();
        if (ordered != null && "legacy_submitted".equalsIgnoreCase(ordered.getGenerationMode())) {
            status.setPlanStatus("legacy_readonly");
            status.setPlanMessage("历史已确认方案，建议只读查看");
            status.setLegacySubmitted(true);
            status.setLegacyMessage("历史已确认方案，建议只读查看");
            return;
        }
        if (!hasDraft && !hasOrdered) {
            status.setPlanStatus("empty");
            status.setPlanMessage("当前方案为空");
            return;
        }
        if (state != null && state.getStaleFlags() != null && Boolean.TRUE.equals(state.getStaleFlags().getOrderedPlan())) {
            status.setPlanStatus("dirty");
            status.setPlanMessage("方案有待更新调整");
            return;
        }
        if (!hasOrdered) {
            status.setPlanStatus("selected");
            status.setPlanMessage("已加入方案，待生成顺序");
            return;
        }
        if (state != null && state.getStaleFlags() != null && Boolean.TRUE.equals(state.getStaleFlags().getReview())) {
            status.setPlanStatus("pending_review");
            status.setPlanMessage("方案已生成，待审查");
            return;
        }
        ReviewStateDTO review = state == null ? null : state.getReviewState();
        if (review == null || Strings.isNullOrEmpty(review.getReviewedAt())) {
            status.setPlanStatus("pending_review");
            status.setPlanMessage("方案已生成，待审查");
            return;
        }
        status.setPlanStatus("ready");
        status.setPlanMessage("方案已生成");
    }

    private void applyReviewWorkflowStatus(PlanningWorkflowStatusDTO status, PlanningStateDTO state) {
        ReviewStateDTO review = state == null ? null : state.getReviewState();
        if (state != null && state.getStaleFlags() != null && Boolean.TRUE.equals(state.getStaleFlags().getReview())
                && review != null && !Strings.isNullOrEmpty(review.getReviewedAt())) {
            status.setReviewStatus("stale");
            status.setReviewMessage("方案已调整，建议重新审查");
            return;
        }
        if (review == null || Strings.isNullOrEmpty(review.getReviewedAt())) {
            status.setReviewStatus("not_reviewed");
            status.setReviewMessage("方案尚未审查");
            return;
        }
        if ("failed".equalsIgnoreCase(review.getStatus())) {
            status.setReviewStatus("failed");
            status.setReviewMessage("审查暂未完成，请稍后重试");
            return;
        }
        int riskCount = review.getSummary() == null ? 0 : valueOrZero(review.getSummary().getRiskCount());
        int warnCount = review.getSummary() == null ? 0 : valueOrZero(review.getSummary().getWarnCount());
        if (riskCount > 0) {
            status.setReviewStatus("has_risk");
            status.setReviewMessage("审查发现风险，需要查看");
        } else if (warnCount > 0) {
            status.setReviewStatus("has_warning");
            status.setReviewMessage("审查有提醒，建议查看");
        } else {
            status.setReviewStatus("passed");
            status.setReviewMessage("审查通过，暂无明显风险");
        }
    }

    private void applyExportWorkflowStatus(PlanningWorkflowStatusDTO status, PlanningStateDTO state) {
        PlanningBehaviorEventDTO latestExport = findLatestBehaviorEvent(state == null ? null : state.getBehaviorEvents(), "plan_export");
        if (latestExport == null) {
            status.setExportStatus("not_exported");
            status.setExportMessage("方案尚未导出");
            return;
        }
        status.setLastExportedAt(latestExport.getCreatedAt());
        Integer exportVersion = latestExport.getPlanVersion();
        Integer currentVersion = state == null ? null : state.getVersion();
        if (exportVersion != null && currentVersion != null && exportVersion < currentVersion) {
            status.setExportStatus("stale");
            status.setExportMessage("方案已调整，建议重新导出");
        } else {
            status.setExportStatus("exported");
            status.setExportMessage("方案已导出");
        }
    }

    private Set<String> collectWorkspaceCandidateVolunteerIds(PlanningStateDTO state) {
        Set<String> volunteerIds = new LinkedHashSet<String>();
        if (state == null) {
            return volunteerIds;
        }
        DraftPlanStateDTO draft = state.getDraftPlanState();
        for (DraftItemDTO item : defaultDraftItems(draft == null ? null : draft.getItems())) {
            if (!Strings.isNullOrEmpty(item.getVolunteerId())) {
                volunteerIds.add(item.getVolunteerId());
            }
        }
        for (DraftUnitDTO unit : defaultDraftUnits(draft == null ? null : draft.getUnits())) {
            for (PlanningUnitMajorDTO major : defaultPlanningUnitMajors(unit.getMajorItems())) {
                if (!Strings.isNullOrEmpty(major.getVolunteerId())) {
                    volunteerIds.add(major.getVolunteerId());
                }
            }
        }
        OrderedPlanStateDTO ordered = state.getOrderedPlanState();
        for (OrderedItemDTO item : defaultOrderedItems(ordered == null ? null : ordered.getItems())) {
            if (!Strings.isNullOrEmpty(item.getVolunteerId())) {
                volunteerIds.add(item.getVolunteerId());
            }
        }
        for (OrderedUnitDTO unit : defaultOrderedUnits(ordered == null ? null : ordered.getUnits())) {
            for (PlanningUnitMajorDTO major : defaultPlanningUnitMajors(unit.getMajorItems())) {
                if (!Strings.isNullOrEmpty(major.getVolunteerId())) {
                    volunteerIds.add(major.getVolunteerId());
                }
            }
        }
        return volunteerIds;
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
        hydrateProfileState(state.getProfileState(), scoreDetail, userProfileData);
        if (state.getCandidateViewState() == null) {
            state.setCandidateViewState(buildDefaultCandidateViewState(state.getProfileState()));
        }
        if (markStale) {
            return touchAndSavePreference(chatSessionId, state);
        }
        state.setSessionId(chatSessionId);
        savePlanningState(chatSessionId, state);
        return null;
    }

    public CandidateViewStateDTO getCandidateViewState(Long chatSessionId) {
        PlanningStateDTO state = getPlanningState(chatSessionId);
        if (state.getCandidateViewState() == null) {
            state.setCandidateViewState(buildDefaultCandidateViewState(state.getProfileState()));
            state.setSessionId(chatSessionId);
            savePlanningState(chatSessionId, state);
        }
        return state.getCandidateViewState();
    }

    public PlanningStateDTO updateCandidateViewState(Long chatSessionId, CandidateViewStateDTO req) {
        PlanningStateDTO state = loadPlanningState(chatSessionId);
        state.setCandidateViewState(normalizeCandidateViewState(req));
        state.getStaleFlags().setInitialRecommendation(true);
        state.getStaleFlags().setPlanAdjustment(true);
        state.setSessionId(chatSessionId);
        state.setVersion((state.getVersion() == null ? 0 : state.getVersion()) + 1);
        savePlanningState(chatSessionId, state);
        return state;
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
            refreshRecommendationOverlay(tenantId, chatSessionId, state);
        }
        state.setInitialRecommendationState(buildInitialRecommendationState(state));
        state.getStaleFlags().setInitialRecommendation(false);
        state.setSessionId(chatSessionId);
        state.setVersion((state.getVersion() == null ? 0 : state.getVersion()) + 1);
        savePlanningState(chatSessionId, state);
        return state;
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
        state.setPlanAdjustmentState(buildPlanAdjustmentState(state, req));
        state.getStaleFlags().setPlanAdjustment(false);
        state.setSessionId(chatSessionId);
        state.setVersion((state.getVersion() == null ? 0 : state.getVersion()) + 1);
        savePlanningState(chatSessionId, state);
        return state.getPlanAdjustmentState();
    }

    public PlanningStateDTO applyPlanAdjustment(Long tenantId,
                                                Long chatSessionId,
                                                PlanAdjustmentApplyReq req) {
        PlanningStateDTO state = loadPlanningState(chatSessionId);
        if (state.getPlanAdjustmentState() == null) {
            state.setPlanAdjustmentState(new PlanAdjustmentStateDTO());
        }
        state.getPlanAdjustmentState().setStatus("pending_apply");
        state.setSessionId(chatSessionId);
        state.setVersion((state.getVersion() == null ? 0 : state.getVersion()) + 1);
        savePlanningState(chatSessionId, state);
        return state;
    }

    public ConstraintStateDTO getConstraintState(Long chatSessionId) {
        return getPlanningState(chatSessionId).getConstraintState();
    }

    public DraftPlanStateDTO getDraftState(Long chatSessionId) {
        return getPlanningState(chatSessionId).getDraftPlanState();
    }

    public OrderedPlanStateDTO getOrderedPlanState(Long chatSessionId) {
        return getPlanningState(chatSessionId).getOrderedPlanState();
    }

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
        appendBehaviorEvent(state, tenantId, chatSessionId, "plan_export", collectOrderedVolunteerIds(state), true);
        savePlanningState(chatSessionId, state);
        return new ExcelExportResult(excelBytes, generateExcelFileName(userScoreDetail));
    }

    public ReviewStateDTO getReviewState(Long chatSessionId) {
        return getPlanningState(chatSessionId).getReviewState();
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

    public CompensationPreviewDTO previewCompensation(Long tenantId, Long chatSessionId) {
        PlanningStateDTO state = loadPlanningState(chatSessionId);
        List<CandidateItemDTO> effectiveCandidates = resolveEffectiveCandidates(tenantId, chatSessionId, state, true);
        OrderedPlanStateDTO structuralOrderedState = buildStructuralOrderedSnapshot(state.getCandidatePoolState(),
                state.getOrderedPlanState(),
                effectiveCandidates);
        PlanningStateDTO structuralState = buildPlanAdjustmentAnalysisState(state, structuralOrderedState);
        CompensationPreviewDTO preview = buildCompensationPreview(structuralState, effectiveCandidates);
        state.setPendingActions(preview.getActions());
        if (state.getReviewState() != null) {
            state.getReviewState().setCompensationPreview(preview);
            attachCompensationsToReviewChecks(state.getReviewState(), preview);
        }
        state.setSessionId(chatSessionId);
        savePlanningState(chatSessionId, state);
        return preview;
    }

    public PlanningStateVersionDTO updateExplicitProfile(Long chatSessionId, UpdateExplicitProfileReq req) {
        PlanningStateDTO state = loadPlanningState(chatSessionId);
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
        return touchAndSavePreference(chatSessionId, state);
    }

    public PlanningStateVersionDTO updateLatentProfile(Long chatSessionId, UpdateLatentProfileReq req) {
        PlanningStateDTO state = loadPlanningState(chatSessionId);
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
        return touchAndSavePreference(chatSessionId, state);
    }

    public PlanningStateVersionDTO updatePhysicalConstraints(Long chatSessionId, UpdatePhysicalConstraintsReq req) {
        PlanningStateDTO state = loadPlanningState(chatSessionId);
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
        return touchAndSaveConstraint(chatSessionId, state);
    }

    public ConstraintDeriveRes deriveConstraints(Long chatSessionId) {
        PlanningStateDTO state = loadPlanningState(chatSessionId);
        DerivedPreferencesDTO derived = buildDerivedPreferences(state.getProfileState());
        ConstraintStateDTO constraintState = state.getConstraintState();
        constraintState.setDerivedPreferences(derived);
        state.setConstraintState(constraintState);
        PlanningStateVersionDTO versionDTO = touchAndSaveConstraint(chatSessionId, state);

        ConstraintDeriveRes res = new ConstraintDeriveRes();
        res.setVersion(versionDTO.getVersion());
        res.setDerivedPreferences(derived);
        res.setStaleFlags(versionDTO.getStaleFlags());
        return res;
    }

    public PlanningStateDTO generateCandidatePool(Long tenantId, Long chatSessionId, CandidatePoolGenerateReq req) {
        PlanningStateDTO state = loadPlanningState(chatSessionId);
        if (!Boolean.TRUE.equals(req.getForceRegenerate()) && !Boolean.TRUE.equals(state.getStaleFlags().getCandidatePool())
                && state.getCandidatePoolState() != null && state.getCandidatePoolState().getItems() != null
                && !state.getCandidatePoolState().getItems().isEmpty()) {
            state.setSessionId(chatSessionId);
            return state;
        }

        VolunteerRecommendListResponse response = volunteerBizService.recommendVolunteerList(tenantId, chatSessionId, false, false);
        CandidatePoolStateDTO candidatePoolState = new CandidatePoolStateDTO();
        candidatePoolState.setGeneratedAt(OffsetDateTime.now().toString());
        candidatePoolState.setSourceVersion((state.getVersion() == null ? 0 : state.getVersion()) + 1);
        candidatePoolState.setRequiredCount(response.getBaseData() != null ? response.getBaseData().getNeed_count() : null);
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
        candidatePoolState.setItems(items);
        recalculateCandidatePoolSummary(candidatePoolState);
        normalizeRequiredTierCountsByAvailableCapacity(candidatePoolState);
        applyCandidatePoolQualityStatus(state, candidatePoolState);

        state.setCandidatePoolState(candidatePoolState);
        state.setRecommendationOverlayState(buildRecommendationOverlayState(response, state.getVersion()));
        state.setPhase("candidate_generated");
        state.setVersion((state.getVersion() == null ? 0 : state.getVersion()) + 1);
        state.getStaleFlags().setCandidatePool(false);
        state.getStaleFlags().setRecommendationOverlay(false);
        state.getStaleFlags().setInitialRecommendation(true);
        state.getStaleFlags().setOrderedPlan(true);
        state.getStaleFlags().setPlanAdjustment(true);
        state.getStaleFlags().setReview(true);
        savePlanningState(chatSessionId, state);
        state.setSessionId(chatSessionId);
        return state;
    }

    private void applyCandidatePoolQualityStatus(PlanningStateDTO state, CandidatePoolStateDTO candidatePoolState) {
        if (candidatePoolState == null) {
            return;
        }
        String statusCode = resolveCandidatePoolStatus(candidatePoolState);
        candidatePoolState.setStatusCode(statusCode);
        candidatePoolState.setRiskHints(Lists.newArrayList());
        if ("empty".equals(statusCode)) {
            candidatePoolState.setStatusMessage("当前条件下没有可用志愿候选，请检查专项资格、批次、分数线或筛选条件");
            candidatePoolState.getRiskHints().addAll(buildCandidatePoolRiskHints(state, candidatePoolState, true));
        } else if ("low_count".equals(statusCode)) {
            candidatePoolState.setStatusMessage("当前条件下可用候选偏少，方案选择空间有限");
            candidatePoolState.getRiskHints().addAll(buildCandidatePoolRiskHints(state, candidatePoolState, false));
        } else {
            candidatePoolState.setStatusCode("ready");
            candidatePoolState.setStatusMessage("候选池已生成");
        }
    }

    private List<String> buildCandidatePoolRiskHints(PlanningStateDTO state,
                                                     CandidatePoolStateDTO candidatePoolState,
                                                     boolean emptyPool) {
        List<String> hints = Lists.newArrayList();
        int required = resolveRequiredCandidateCount(candidatePoolState);
        int available = isMajorGroupMode(candidatePoolState)
                ? valueOrZero(candidatePoolState.getSummary() == null ? null : candidatePoolState.getSummary().getUnitTotal())
                : valueOrZero(candidatePoolState.getSummary() == null ? null : candidatePoolState.getSummary().getTotal());
        if (required > 0) {
            hints.add(String.format("当前可用候选 %d 个，目标需要 %d 个", available, required));
        }
        appendTierShortageHints(hints, candidatePoolState);
        appendScoreBoundaryHint(hints, candidatePoolState);
        appendHardConstraintHints(hints, state);
        if (hints.isEmpty()) {
            hints.add(emptyPool
                    ? "当前批次、分数线、选科、专项资格或身体限报等硬条件可能导致无可用候选"
                    : "候选不足更可能来自批次、分数线、选科、专项资格或身体限报等硬条件");
        }
        return hints;
    }

    private void appendTierShortageHints(List<String> hints, CandidatePoolStateDTO candidatePoolState) {
        if (candidatePoolState == null || candidatePoolState.getRequiredTierCounts() == null || candidatePoolState.getRequiredTierCounts().isEmpty()
                || candidatePoolState.getSummary() == null) {
            return;
        }
        Map<String, Integer> availableTierCounts = isMajorGroupMode(candidatePoolState)
                ? candidatePoolState.getSummary().getUnitTierCounts()
                : candidatePoolState.getSummary().getTierCounts();
        for (String tier : Lists.newArrayList("冲", "稳", "保")) {
            int required = valueOrZero(candidatePoolState.getRequiredTierCounts().get(tier));
            int available = valueOrZero(availableTierCounts == null ? null : availableTierCounts.get(tier));
            if (required > 0 && available < required) {
                hints.add(String.format("%s区候选不足：当前 %d 个，目标 %d 个", tier, available, required));
            }
        }
    }

    private void appendScoreBoundaryHint(List<String> hints, CandidatePoolStateDTO candidatePoolState) {
        if (candidatePoolState == null || candidatePoolState.getUserScore() == null || candidatePoolState.getBatchScore() == null) {
            return;
        }
        int diff = candidatePoolState.getUserScore() - candidatePoolState.getBatchScore();
        if (diff >= 0 && diff <= 30) {
            hints.add(String.format("当前分数距离批次线 %d 分，可选空间可能偏窄", diff));
        }
    }

    private void appendHardConstraintHints(List<String> hints, PlanningStateDTO state) {
        PhysicalConstraintsDTO physicalConstraints = state == null || state.getProfileState() == null
                ? null : state.getProfileState().getPhysicalConstraints();
        if (physicalConstraints == null) {
            return;
        }
        if (!defaultList(physicalConstraints.getColorVision()).isEmpty()
                || !Strings.isNullOrEmpty(physicalConstraints.getHeight())
                || physicalConstraints.getVision() != null
                && (!Strings.isNullOrEmpty(physicalConstraints.getVision().getLeft())
                || !Strings.isNullOrEmpty(physicalConstraints.getVision().getRight()))) {
            hints.add("已按身体条件和限报要求过滤候选");
        }
        if (!defaultList(physicalConstraints.getSpecialLimits()).isEmpty()) {
            hints.add("已按专项、民族、外方院校等资格条件过滤候选");
        }
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

    private Map<String, Integer> buildRequiredTierCounts(Long chatSessionId, VolunteerRecommendListResponse response) {
        Map<String, Integer> requiredTierCounts = new HashMap<String, Integer>();
        if (response == null || response.getBaseData() == null) {
            return requiredTierCounts;
        }
        Integer requiredCount = response.getBaseData().getNeed_count();
        CreateSessionReq userScoreDetail = resolveTierTargetScoreDetail(chatSessionId, response);
        if (requiredCount != null && requiredCount > 0 && userScoreDetail != null && userScoreDetail.getStrategyType() != null) {
            Map<String, Integer> calculated = volunteerIntervalService.calculateTargetCounts(
                    requiredCount,
                    false,
                    userScoreDetail.getStrategyType());
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
        PlanningStateDTO state = loadPlanningState(chatSessionId);
        if (state.getCandidateViewState() == null) {
            state.setCandidateViewState(buildDefaultCandidateViewState(state.getProfileState()));
        }
        if (shouldRefreshRecommendationOverlay(state)) {
            refreshRecommendationOverlay(tenantId, chatSessionId, state);
        }
        List<CandidateItemDTO> items = mergeOverlayIntoCandidates(
                state.getCandidatePoolState().getItems(),
                state.getRecommendationOverlayState());
        List<CandidateItemDTO> filtered = items.stream()
                .filter(item -> matchesTier(item, req))
                .filter(item -> matchesProvince(item, req))
                .filter(item -> matchesCity(item, req))
                .filter(item -> matchesSchoolKeyword(item, req))
                .filter(item -> matchesMajorKeyword(item, req))
                .filter(item -> matchesSchoolTags(item, req))
                .filter(item -> matchesMajorTags(item, req))
                .collect(Collectors.toList());

        Comparator<CandidateItemDTO> comparator = buildComparator(req.getSort() != null ? req.getSort().getField() : "finalScore");
        if ("asc".equalsIgnoreCase(req.getSort() != null ? req.getSort().getOrder() : "desc")) {
            filtered = filtered.stream().sorted(comparator).collect(Collectors.toList());
        } else {
            filtered = filtered.stream().sorted(comparator.reversed()).collect(Collectors.toList());
        }

        int page = req.getPage() == null || req.getPage() < 1 ? 1 : req.getPage();
        int pageSize = req.getPageSize() == null || req.getPageSize() < 1 ? 20 : req.getPageSize();
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
        return res;
    }

    public CandidateFilterOptionsDTO getCandidateFilterOptions(Long tenantId, Long chatSessionId) {
        PlanningStateDTO state = loadPlanningState(chatSessionId);
        if (shouldRefreshRecommendationOverlay(state)) {
            refreshRecommendationOverlay(tenantId, chatSessionId, state);
        }
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
        List<String> schoolTags = items.stream()
                .flatMap(item -> collectSchoolFilterTags(item).stream())
                .filter(this::isEnumLikeFilterOption)
                .distinct()
                .sorted()
                .collect(Collectors.toList());
        List<String> majorTags = items.stream()
                .flatMap(item -> collectMajorFilterTags(item).stream())
                .filter(this::isEnumLikeFilterOption)
                .distinct()
                .sorted()
                .collect(Collectors.toList());
        dto.setProvinceNames(provinceNames);
        dto.setCityNames(cityNames);
        dto.setMajorKeywords(majorCategories);
        dto.setSchoolTags(schoolTags);
        dto.setMajorTags(majorTags);
        dto.setGroups(buildCandidateFilterGroups(provinceNames, cityNames, schoolTags, majorTags, majorDisciplines, majorCategories));
        return dto;
    }

    public PlanningStateDTO selectDraftItems(Long chatSessionId, DraftSelectReq req) {
        PlanningStateDTO state = loadPlanningState(chatSessionId);
        DraftPlanStateDTO draft = state.getDraftPlanState();
        List<CandidateItemDTO> candidates = resolveEffectiveCandidates(null, chatSessionId, state, false);
        for (String volunteerId : defaultList(req.getVolunteerIds())) {
            if (containsDraftItem(draft, volunteerId) || draft.getBannedVolunteerIds().contains(volunteerId)) {
                continue;
            }
            CandidateItemDTO candidate = findCandidate(candidates, volunteerId);
            if (candidate == null) {
                continue;
            }
            DraftItemDTO item = new DraftItemDTO();
            item.setVolunteerId(candidate.getVolunteerId());
            item.setTier(candidate.getTier());
            item.setSchoolName(candidate.getSchoolName());
            item.setMajorName(candidate.getMajorName());
            item.setSource(req.getSource());
            draft.getItems().add(item);
        }
        syncDraftUnitsWithItems(draft, candidates, state.getCandidatePoolState());
        recalculateDraftSummary(draft, state.getCandidatePoolState());
        appendBehaviorEvent(state, null, chatSessionId, "plan_add", defaultList(req.getVolunteerIds()), false);
        return saveDraftState(chatSessionId, state);
    }

    public PlanningStateDTO removeDraftItems(Long chatSessionId, DraftRemoveReq req) {
        PlanningStateDTO state = loadPlanningState(chatSessionId);
        DraftPlanStateDTO draft = state.getDraftPlanState();
        draft.setItems(draft.getItems().stream()
                .filter(item -> !defaultList(req.getVolunteerIds()).contains(item.getVolunteerId()))
                .collect(Collectors.toList()));
        syncDraftUnitsWithItems(draft, resolveEffectiveCandidates(null, chatSessionId, state, false), state.getCandidatePoolState());
        recalculateDraftSummary(draft, state.getCandidatePoolState());
        appendBehaviorEvent(state, null, chatSessionId, "plan_remove", defaultList(req.getVolunteerIds()), false);
        return saveDraftState(chatSessionId, state);
    }

    public PlanningStateDTO lockDraftItems(Long chatSessionId, DraftLockReq req) {
        PlanningStateDTO state = loadPlanningState(chatSessionId);
        DraftPlanStateDTO draft = state.getDraftPlanState();
        for (DraftItemDTO item : draft.getItems()) {
            if (defaultList(req.getVolunteerIds()).contains(item.getVolunteerId())) {
                item.setLocked(req.getLocked());
            }
        }
        syncDraftUnitsWithItems(draft, resolveEffectiveCandidates(null, chatSessionId, state, false), state.getCandidatePoolState());
        recalculateDraftSummary(draft, state.getCandidatePoolState());
        return saveDraftState(chatSessionId, state);
    }

    public PlanningStateDTO banDraftItems(Long chatSessionId, DraftBanReq req) {
        PlanningStateDTO state = loadPlanningState(chatSessionId);
        DraftPlanStateDTO draft = state.getDraftPlanState();
        for (String volunteerId : defaultList(req.getVolunteerIds())) {
            if (!draft.getBannedVolunteerIds().contains(volunteerId)) {
                draft.getBannedVolunteerIds().add(volunteerId);
            }
        }
        draft.setItems(draft.getItems().stream()
                .filter(item -> !draft.getBannedVolunteerIds().contains(item.getVolunteerId()))
                .collect(Collectors.toList()));
        syncDraftUnitsWithItems(draft, resolveEffectiveCandidates(null, chatSessionId, state, false), state.getCandidatePoolState());
        recalculateDraftSummary(draft, state.getCandidatePoolState());
        return saveDraftState(chatSessionId, state);
    }

    public PlanningStateDTO generateOrderedPlan(Long tenantId, Long chatSessionId, OrderedPlanGenerateReq req) {
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
        List<CandidateItemDTO> effectiveCandidates = resolveEffectiveCandidates(tenantId, chatSessionId, state, true);
        List<OrderedItemDTO> items = buildOrderedItemsFromDraft(state.getDraftPlanState(), state.getCandidatePoolState(), effectiveCandidates, existing,
                Boolean.TRUE.equals(safeReq.getRegroupByTier()));
        orderedPlanState.setItems(items);
        if (isMajorGroupMode(state.getCandidatePoolState())) {
            orderedPlanState.setUnits(buildOrderedUnitsFromOrderedItems(items, state.getDraftPlanState(), effectiveCandidates));
        }
        recalculateOrderedSummary(orderedPlanState, state.getCandidatePoolState());
        state.setOrderedPlanState(orderedPlanState);
        return saveOrderedState(chatSessionId, state);
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

        if (Boolean.TRUE.equals(safeReq.getForceRegenerate())
                || Boolean.TRUE.equals(state.getStaleFlags().getInitialRecommendation())
                || state.getInitialRecommendationState() == null
                || state.getInitialRecommendationState().getItems() == null
                || state.getInitialRecommendationState().getItems().isEmpty()) {
            state.setInitialRecommendationState(buildInitialRecommendationState(state));
            state.getStaleFlags().setInitialRecommendation(false);
        }

        List<CandidateItemDTO> effectiveCandidates = resolveEffectiveCandidates(tenantId, chatSessionId, state, true);
        replaceDraftWithInitialRecommendation(state, effectiveCandidates);
        recalculateDraftSummary(state.getDraftPlanState(), state.getCandidatePoolState());
        state = saveDraftState(chatSessionId, state);
        return reorderDraftPlanInternal(tenantId, chatSessionId, buildDraftPlanReorderReq(safeReq), "initial_auto");
    }

    public PlanningStateDTO reorderDraftPlan(Long tenantId, Long chatSessionId, DraftPlanReorderReq req) {
        return reorderDraftPlanInternal(tenantId, chatSessionId, req, "draft_reorder");
    }

    private PlanningStateDTO reorderDraftPlanInternal(Long tenantId,
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
        state = generateOrderedPlan(tenantId, chatSessionId, generateReq);
        applyPlanGenerationMetadata(state,
                mode,
                Boolean.TRUE.equals(safeReq.getAllowAutoComplete()),
                countPinnedOrderedItems(state.getOrderedPlanState()),
                countManualOrderedItems(state.getOrderedPlanState()));
        if (state.getOrderedPlanState() != null
                && state.getOrderedPlanState().getItems() != null
                && !state.getOrderedPlanState().getItems().isEmpty()) {
            state.setPhase("ordered");
            state.getStaleFlags().setOrderedPlan(false);
        }
        savePlanningState(chatSessionId, state);
        state.setSessionId(chatSessionId);
        return state;
    }

    public PlanningStateDTO moveOrderedItem(Long chatSessionId, OrderedMoveReq req) {
        PlanningStateDTO state = loadPlanningState(chatSessionId);
        OrderedPlanStateDTO orderedPlanState = ensureOrderedPlanState(state);
        List<OrderedItemDTO> current = new ArrayList<OrderedItemDTO>(orderedPlanState.getItems());
        OrderedItemDTO target = findOrderedItem(current, req.getVolunteerId());
        if (target == null) {
            state.setSessionId(chatSessionId);
            return state;
        }
        int currentIndex = current.indexOf(target);
        int targetIndex = resolveMovableTargetIndex(current, currentIndex, req.getTargetPosition());
        if (targetIndex == currentIndex) {
            state.setSessionId(chatSessionId);
            return state;
        }
        current = moveWithinUnlockedSlots(current, currentIndex, targetIndex);
        target.setOrderedBy("user");
        if (Boolean.TRUE.equals(target.getPinned())) {
            target.setPinnedPosition(targetIndex + 1);
            target.setOrderReason("user_move_pinned");
        } else {
            target.setOrderReason("user_move");
        }
        orderedPlanState.setItems(rebuildOrderedItems(current));
        recalculateOrderedSummary(orderedPlanState, state.getCandidatePoolState());
        state.setOrderedPlanState(orderedPlanState);
        state.getStaleFlags().setReview(true);
        state.getStaleFlags().setPlanAdjustment(true);
        appendBehaviorEvent(state, null, chatSessionId, "plan_move", Lists.newArrayList(req.getVolunteerId()), false);
        return saveOrderedState(chatSessionId, state);
    }

    public PlanningStateDTO moveOrderedUnit(Long chatSessionId, OrderedUnitMoveReq req) {
        PlanningStateDTO state = loadPlanningState(chatSessionId);
        OrderedPlanStateDTO orderedPlanState = ensureOrderedPlanState(state);
        List<OrderedItemDTO> current = defaultOrderedItems(orderedPlanState.getItems());
        String unitId = req == null ? null : req.getUnitId();
        if (Strings.isNullOrEmpty(unitId) || current.isEmpty()) {
            state.setSessionId(chatSessionId);
            return state;
        }
        List<OrderedItemDTO> unitItems = current.stream()
                .filter(item -> unitId.equals(resolveDraftOrOrderedUnitId(item)))
                .collect(Collectors.toList());
        if (unitItems.isEmpty()) {
            state.setSessionId(chatSessionId);
            return state;
        }
        List<String> orderedUnitIds = buildOrderedUnitIds(current);
        int currentUnitIndex = orderedUnitIds.indexOf(unitId);
        int targetUnitIndex = normalizeIndex(req.getTargetPosition(), orderedUnitIds.size());
        if (currentUnitIndex < 0 || targetUnitIndex == currentUnitIndex) {
            state.setSessionId(chatSessionId);
            return state;
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
        orderedPlanState.setItems(rebuildOrderedItems(moved));
        orderedPlanState.setUnits(buildOrderedUnitsFromOrderedItems(orderedPlanState.getItems(), state.getDraftPlanState(), candidates));
        recalculateOrderedSummary(orderedPlanState, state.getCandidatePoolState());
        state.setOrderedPlanState(orderedPlanState);
        state.getStaleFlags().setReview(true);
        state.getStaleFlags().setPlanAdjustment(true);
        appendUnitBehaviorEvent(state, chatSessionId, "plan_unit_move", unitId, unitItems);
        return saveOrderedState(chatSessionId, state);
    }

    public PlanningStateDTO removeOrderedUnits(Long chatSessionId, OrderedUnitRemoveReq req) {
        PlanningStateDTO state = loadPlanningState(chatSessionId);
        OrderedPlanStateDTO orderedPlanState = ensureOrderedPlanState(state);
        Set<String> unitIds = new LinkedHashSet<String>(defaultList(req == null ? null : req.getUnitIds()));
        if (unitIds.isEmpty()) {
            state.setSessionId(chatSessionId);
            return state;
        }
        List<OrderedItemDTO> removedItems = defaultOrderedItems(orderedPlanState.getItems()).stream()
                .filter(item -> unitIds.contains(resolveDraftOrOrderedUnitId(item)))
                .collect(Collectors.toList());
        if (removedItems.isEmpty()) {
            state.setSessionId(chatSessionId);
            return state;
        }
        orderedPlanState.setItems(rebuildOrderedItems(defaultOrderedItems(orderedPlanState.getItems()).stream()
                .filter(item -> !unitIds.contains(resolveDraftOrOrderedUnitId(item)))
                .collect(Collectors.toList())));
        DraftPlanStateDTO draft = state.getDraftPlanState();
        draft.setItems(defaultDraftItems(draft.getItems()).stream()
                .filter(item -> !unitIds.contains(resolveDraftOrOrderedUnitId(item)))
                .collect(Collectors.toList()));
        List<CandidateItemDTO> candidates = resolveEffectiveCandidates(null, chatSessionId, state, false);
        syncDraftUnitsWithItems(draft, candidates, state.getCandidatePoolState());
        recalculateDraftSummary(draft, state.getCandidatePoolState());
        orderedPlanState.setUnits(buildOrderedUnitsFromOrderedItems(orderedPlanState.getItems(), draft, candidates));
        recalculateOrderedSummary(orderedPlanState, state.getCandidatePoolState());
        state.setDraftPlanState(draft);
        state.setOrderedPlanState(orderedPlanState);
        state.getStaleFlags().setReview(true);
        state.getStaleFlags().setPlanAdjustment(true);
        for (String unitId : unitIds) {
            List<OrderedItemDTO> removedUnitItems = removedItems.stream()
                    .filter(item -> unitId.equals(resolveDraftOrOrderedUnitId(item)))
                    .collect(Collectors.toList());
            if (!removedUnitItems.isEmpty()) {
                appendUnitBehaviorEvent(state, chatSessionId, "plan_unit_remove", unitId, removedUnitItems);
            }
        }
        return saveOrderedState(chatSessionId, state);
    }

    public PlanningStateDTO sortOrderedPlan(Long chatSessionId, OrderedPlanSortReq req) {
        PlanningStateDTO state = loadPlanningState(chatSessionId);
        OrderedPlanStateDTO orderedPlanState = ensureOrderedPlanState(state);
        List<OrderedItemDTO> current = defaultOrderedItems(orderedPlanState.getItems());
        if (current.isEmpty()) {
            state.setSessionId(chatSessionId);
            return state;
        }
        String sortField = normalizeOrderedSortField(req == null ? null : req.getSortField());
        Map<String, Integer> beforePositions = buildOrderedPositionMap(current);
        List<CandidateItemDTO> candidates = resolveEffectiveCandidates(null, chatSessionId, state, false);
        List<OrderedItemDTO> sorted = isMajorGroupMode(state.getCandidatePoolState())
                ? sortOrderedPlanByUnit(current, orderedPlanState, state.getDraftPlanState(), candidates, sortField)
                : sortOrderedPlanItems(current, candidates, sortField);
        orderedPlanState.setItems(rebuildOrderedItems(sorted));
        orderedPlanState.setUnits(buildOrderedUnitsFromOrderedItems(orderedPlanState.getItems(), state.getDraftPlanState(), candidates));
        recalculateOrderedSummary(orderedPlanState, state.getCandidatePoolState());
        state.setOrderedPlanState(orderedPlanState);
        markOrderedItemsSortedByUser(orderedPlanState, sortField);
        state.getStaleFlags().setReview(true);
        state.getStaleFlags().setPlanAdjustment(true);
        appendPlanSortApplyEvent(state, chatSessionId, sortField, beforePositions, orderedPlanState);
        return saveOrderedState(chatSessionId, state);
    }

    public PlanningStateDTO pinOrderedItem(Long chatSessionId, OrderedPinReq req) {
        PlanningStateDTO state = loadPlanningState(chatSessionId);
        OrderedPlanStateDTO orderedPlanState = ensureOrderedPlanState(state);
        OrderedItemDTO target = findOrderedItem(orderedPlanState.getItems(), req.getVolunteerId());
        if (target == null) {
            state.setSessionId(chatSessionId);
            return state;
        }
        target.setPinned(true);
        target.setPinnedPosition(normalizePosition(req.getTargetPosition(), orderedPlanState.getItems().size()));
        target.setOrderedBy("user");
        target.setOrderReason("user_pin");
        orderedPlanState.setItems(rebuildOrderedItems(orderedPlanState.getItems()));
        recalculateOrderedSummary(orderedPlanState, state.getCandidatePoolState());
        state.setOrderedPlanState(orderedPlanState);
        return saveOrderedState(chatSessionId, state);
    }

    public PlanningStateDTO unpinOrderedItem(Long chatSessionId, OrderedPinReq req) {
        PlanningStateDTO state = loadPlanningState(chatSessionId);
        OrderedPlanStateDTO orderedPlanState = ensureOrderedPlanState(state);
        OrderedItemDTO target = findOrderedItem(orderedPlanState.getItems(), req.getVolunteerId());
        if (target == null) {
            state.setSessionId(chatSessionId);
            return state;
        }
        target.setPinned(false);
        target.setPinnedPosition(null);
        target.setOrderedBy("user");
        target.setOrderReason("user_unpin");
        orderedPlanState.setItems(rebuildOrderedItems(orderedPlanState.getItems()));
        recalculateOrderedSummary(orderedPlanState, state.getCandidatePoolState());
        state.setOrderedPlanState(orderedPlanState);
        return saveOrderedState(chatSessionId, state);
    }

    public OrderedPlanActionRes buildOrderedPlanActionRes(PlanningStateDTO state) {
        OrderedPlanActionRes res = new OrderedPlanActionRes();
        res.setSessionId(state.getSessionId());
        res.setVersion(state.getVersion());
        res.setPhase(state.getPhase());
        res.setStaleFlags(state.getStaleFlags());
        res.setOrderedPlanState(state.getOrderedPlanState());
        return res;
    }

    public ReviewStateDTO runReview(Long tenantId, Long chatSessionId) {
        PlanningStateDTO state = loadPlanningState(chatSessionId);
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
        checks.add(reviewMajorGroupSafetyIntentAlignment(state));
        checks.add(buildFixedNoticeCheck("plan_update_notice", "info", "招生计划代码可能动态更新",
                "填报期间可能存在官方招生计划代码更新，建议同步查阅教育考试院官网。"));
        checks.add(buildFixedNoticeCheck("adjustment_notice", "info", "当前方案存在调剂风险提示",
                "正式填报存在调剂风险，建议结合个人专业偏好谨慎确认是否服从调剂。"));
        reviewState.setChecks(checks);
        CompensationPreviewDTO compensationPreview = buildCompensationPreview(structuralState, effectiveCandidates);
        reviewState.setCompensationPreview(compensationPreview);
        attachCompensationsToReviewChecks(reviewState, compensationPreview);
        recalculateReviewSummary(reviewState);

        state.setReviewState(reviewState);
        state.setPendingActions(compensationPreview.getActions());
        state.setSessionId(chatSessionId);
        state.setVersion((state.getVersion() == null ? 0 : state.getVersion()) + 1);
        state.setPhase("reviewed");
        state.getStaleFlags().setReview(false);
        savePlanningState(chatSessionId, state);
        return reviewState;
    }

    public PlanningStateDTO applyCompensation(Long tenantId, Long chatSessionId, CompensationApplyReq req) {
        PlanningStateDTO state = loadPlanningState(chatSessionId);
        List<CandidateItemDTO> effectiveCandidates = resolveEffectiveCandidates(tenantId, chatSessionId, state, true);
        CompensationPreviewDTO preview = buildCompensationPreview(state, effectiveCandidates);
        state.setPendingActions(Lists.newArrayList());
        if (state.getReviewState() != null) {
            state.getReviewState().setCompensationPreview(preview);
            attachCompensationsToReviewChecks(state.getReviewState(), preview);
        }
        if (preview.getActions().isEmpty()) {
            state.setSessionId(chatSessionId);
            savePlanningState(chatSessionId, state);
            return state;
        }
        DraftPlanStateDTO draft = state.getDraftPlanState();
        List<CandidateItemDTO> candidates = effectiveCandidates;
        List<CompensationActionDTO> appliedActions = Lists.newArrayList();

        for (CompensationActionDTO action : preview.getActions()) {
            boolean applied = false;
            for (String volunteerId : defaultList(action.getVolunteerIds())) {
                if (containsDraftItem(draft, volunteerId) || draft.getBannedVolunteerIds().contains(volunteerId)) {
                    continue;
                }
                CandidateItemDTO candidate = findCandidate(candidates, volunteerId);
                if (candidate == null) {
                    continue;
                }
                DraftItemDTO item = new DraftItemDTO();
                item.setVolunteerId(candidate.getVolunteerId());
                item.setTier(candidate.getTier());
                item.setSchoolName(candidate.getSchoolName());
                item.setMajorName(candidate.getMajorName());
                item.setSource("compensation");
                draft.getItems().add(item);
                applied = true;
            }
            if (applied) {
                appliedActions.add(action);
            }
        }
        syncDraftUnitsWithItems(draft, candidates, state.getCandidatePoolState());
        recalculateDraftSummary(draft, state.getCandidatePoolState());
        appendOperationLogs(state, appliedActions);
        state = saveDraftState(chatSessionId, state);

        CompensationApplyReq safeReq = req == null ? new CompensationApplyReq() : req;
        if (Boolean.TRUE.equals(safeReq.getRegenerateOrderedPlan())) {
            OrderedPlanGenerateReq generateReq = new OrderedPlanGenerateReq();
            generateReq.setForceRegenerate(true);
            generateReq.setRegroupByTier(true);
            state = generateOrderedPlan(tenantId, chatSessionId, generateReq);
        }
        if (Boolean.TRUE.equals(safeReq.getRerunReview())) {
            runReview(tenantId, chatSessionId);
            state = getPlanningState(chatSessionId);
        }
        return state;
    }

    private PlanningStateVersionDTO touchAndSavePreference(Long chatSessionId, PlanningStateDTO state) {
        state.setSessionId(chatSessionId);
        state.setVersion((state.getVersion() == null ? 0 : state.getVersion()) + 1);
        state.setPhase("profile_ready");
        state.getStaleFlags().setRecommendationOverlay(true);
        state.getStaleFlags().setInitialRecommendation(true);
        state.getStaleFlags().setOrderedPlan(true);
        state.getStaleFlags().setPlanAdjustment(true);
        state.getStaleFlags().setReview(true);
        savePlanningState(chatSessionId, state);

        PlanningStateVersionDTO versionDTO = new PlanningStateVersionDTO();
        versionDTO.setVersion(state.getVersion());
        versionDTO.setStaleFlags(state.getStaleFlags());
        return versionDTO;
    }

    private PlanningStateVersionDTO touchAndSaveConstraint(Long chatSessionId, PlanningStateDTO state) {
        state.setSessionId(chatSessionId);
        state.setVersion((state.getVersion() == null ? 0 : state.getVersion()) + 1);
        state.setPhase("profile_ready");
        state.getStaleFlags().setCandidatePool(true);
        state.getStaleFlags().setRecommendationOverlay(true);
        state.getStaleFlags().setInitialRecommendation(true);
        state.getStaleFlags().setOrderedPlan(true);
        state.getStaleFlags().setPlanAdjustment(true);
        state.getStaleFlags().setReview(true);
        savePlanningState(chatSessionId, state);

        PlanningStateVersionDTO versionDTO = new PlanningStateVersionDTO();
        versionDTO.setVersion(state.getVersion());
        versionDTO.setStaleFlags(state.getStaleFlags());
        return versionDTO;
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
        List<CandidateItemDTO> items = Lists.newArrayList();
        if (response != null) {
            items.addAll(flattenCandidates(response.getSprints(), "冲"));
            items.addAll(flattenCandidates(response.getSafes(), "稳"));
            items.addAll(flattenCandidates(response.getProtects(), "保"));
        }
        candidatePoolState.setItems(items);
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
        InitialRecommendationSelectionState selectionState = buildInitialRecommendationSelectionState(state, candidates);
        recommendationState.getSummary().setTotal(selectionState.selected.size());
        recommendationState.getSummary().setLocalProtectCount(countLocalProtectCandidates(selectionState.selected,
                state.getCandidatePoolState().getSourceProvinceName()));
        recommendationState.getSummary().setGapFixCount(selectionState.gapFixCount);
        recommendationState.getSummary().setUnresolvedGapCount(selectionState.unresolvedGapCount);
        recommendationState.getSummary().setUnitCompletionCount(selectionState.unitCompletionCount);
        recommendationState.getSummary().setAppliedRepairCount(selectionState.appliedRepairCount);
        recommendationState.getSummary().setUnresolvedRuleCodes(Lists.newArrayList(selectionState.unresolvedRuleCodes));
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
        compare = buildInitialRecommendationRemovableComparator(null).compare(left.removable, right.removable);
        if (compare != 0) {
            return compare;
        }
        return buildInitialRecommendationCandidateComparator().compare(left.filler, right.filler);
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
        major.setTier(candidate.getTier());
        major.setAdmissionRatio(candidate.getAdmissionRatio());
        major.setFinalScore(candidate.getFinalScore());
        major.setIntentScore(candidate.getIntentScore());
        major.setPreferred(candidate.getPreferred());
        major.setSelected(selected);
        major.setSafetyMajor(safetyMajor);
        major.setTuitionPerYear(candidate.getTuitionPerYear());
        major.setRankInTier(candidate.getRankInTier());
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
            adjustmentState.getAnalysis().getRules().add(buildPlanAdjustmentRuleResult(check, linkedActions));
            if (Boolean.FALSE.equals(check.getPassed()) && !Strings.isNullOrEmpty(check.getSummary())) {
                hitSummaries.add(check.getSummary());
            }
            appendPlanAdjustmentSuggestions(adjustmentState,
                    check,
                    linkedActions,
                    effectiveCandidates,
                    target,
                    analysisOrderedState);
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
            snapshot.setItems(buildOrderedItemsFromDraft(state.getDraftPlanState(),
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
        copy.setTier(source.getTier());
        copy.setSchoolName(source.getSchoolName());
        copy.setProvinceName(source.getProvinceName());
        copy.setCityName(source.getCityName());
        copy.setSource(source.getSource());
        copy.setLocked(source.getLocked());
        copy.setPinned(source.getPinned());
        copy.setPinnedPosition(source.getPinnedPosition());
        copy.setOrderedBy(source.getOrderedBy());
        copy.setOrderReason(source.getOrderReason());
        copy.setAdmissionRatio(source.getAdmissionRatio());
        copy.setFinalScore(source.getFinalScore());
        copy.setSchoolEnrollRatio(source.getSchoolEnrollRatio());
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
        snapshot.setItems(rebuildOrderedItems(Lists.newArrayList(groupedItems.values())));
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
        analysisState.setDraftPlanState(state.getDraftPlanState());
        analysisState.setOrderedPlanState(analysisOrderedState);
        return analysisState;
    }

    private PlanAdjustmentRuleResultDTO buildPlanAdjustmentRuleResult(ReviewCheckDTO check,
                                                                      List<CompensationActionDTO> linkedActions) {
        PlanAdjustmentRuleResultDTO result = new PlanAdjustmentRuleResultDTO();
        result.setRuleCode(check.getCode());
        result.setSeverity(normalizePlanAdjustmentSeverity(check.getLevel()));
        result.setHit(Boolean.FALSE.equals(check.getPassed()));
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
            if (containsAny(check.getSummary(), "冲区占比偏低", "保区占比过低")) {
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
                                                 OrderedPlanStateDTO analysisOrderedState) {
        if (linkedActions != null && !linkedActions.isEmpty()) {
            for (CompensationActionDTO action : linkedActions) {
                adjustmentState.getSuggestions().getAddSuggestions().add(
                        buildAddSuggestionFromCompensation(check, action, candidates, target));
            }
        }
        if (!Boolean.FALSE.equals(check.getPassed())) {
            return;
        }
        if ("ratio_distribution".equals(check.getCode()) && containsAny(check.getSummary(), "冲区占比偏低", "保区占比过低")) {
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
        if ("ratio_distribution".equals(check.getCode()) && containsAny(check.getSummary(), "冲区占比过高")) {
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
            pair.setReasonCodes(Lists.newArrayList(check.getCode(), "fill_probability_gap"));
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
        suggestion.setReasonCodes(Lists.newArrayList(check.getCode(), "rebalance_protect_ratio"));
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
            pair.setReasonCodes(Lists.newArrayList(check.getCode(), "rebalance_protect_ratio"));
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

    private PlanningStateDTO loadPlanningState(Long chatSessionId, boolean allowLegacyImport) {
        ChatSessionExtraData extraData = chatSessionExtraDataSharedService.getBySessionIdAndDataKey(
                chatSessionId, ChatSessionExtraDataConstants.PLANNING_STATE_KEY);
        PlanningStateDTO state;
        if (extraData == null || extraData.getDataValue() == null) {
            state = allowLegacyImport ? tryImportLegacyPlanningState(chatSessionId) : null;
            if (state != null) {
                savePlanningState(chatSessionId, state);
            } else {
                state = new PlanningStateDTO();
                state.setSessionId(chatSessionId);
            }
        } else {
            state = JSONObject.parseObject(extraData.getDataValue(), PlanningStateDTO.class);
        }
        if (state == null) {
            state = new PlanningStateDTO();
        }
        if (state.getProfileState() == null) {
            state.setProfileState(new ProfileStateDTO());
        }
        if (state.getStaleFlags() == null) {
            state.setStaleFlags(new StaleFlagsDTO());
        }
        if (state.getConstraintState() == null) {
            state.setConstraintState(new ConstraintStateDTO());
        }
        if (state.getCandidatePoolState() == null) {
            state.setCandidatePoolState(new CandidatePoolStateDTO());
        }
        if (state.getInitialRecommendationState() == null) {
            state.setInitialRecommendationState(new InitialRecommendationStateDTO());
        }
        if (state.getDraftPlanState() == null) {
            state.setDraftPlanState(new DraftPlanStateDTO());
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
        if (state.getPendingActions() == null) {
            state.setPendingActions(Lists.newArrayList());
        }
        if (state.getOperationLogs() == null) {
            state.setOperationLogs(Lists.newArrayList());
        }
        if (state.getBehaviorEvents() == null) {
            state.setBehaviorEvents(Lists.newArrayList());
        }
        backfillLegacyProfileState(chatSessionId, state);
        boolean planEditCacheNoticeAdded = appendPlanEditCacheNotice(chatSessionId, state);
        backfillLegacySummaryFields(state);
        if (planEditCacheNoticeAdded) {
            savePlanningState(chatSessionId, state);
        }
        return state;
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

        List<CandidateItemDTO> candidates = defaultCandidates(candidatePoolState.getItems());
        List<CandidateItemDTO> preferredCandidates = selectLegacyPreferredCandidates(candidates, candidatePoolState, legacyPlanSource);
        DraftPlanStateDTO draftPlanState = buildLegacyDraftPlanState(preferredCandidates, candidatePoolState, legacyPlanSource.submitted);
        OrderedPlanStateDTO orderedPlanState = buildLegacyOrderedPlanState(draftPlanState, candidatePoolState, candidates, legacyPlanSource);

        state.setDraftPlanState(draftPlanState);
        state.setOrderedPlanState(orderedPlanState);
        state.setCandidateViewState(buildDefaultCandidateViewState(state.getProfileState()));
        state.setPhase(preferredCandidates.isEmpty() ? "candidate_generated" : "ordered");
        state.getStaleFlags().setCandidatePool(false);
        state.getStaleFlags().setRecommendationOverlay(false);
        state.getStaleFlags().setInitialRecommendation(false);
        state.getStaleFlags().setOrderedPlan(false);
        state.getStaleFlags().setPlanAdjustment(true);
        state.getStaleFlags().setReview(true);
        appendLegacyImportLog(state, legacyPlanSource, preferredCandidates);
        return state;
    }

    private CandidatePoolStateDTO buildLegacyCandidatePoolState(Long chatSessionId, VolunteerRecommendListResponse response) {
        CandidatePoolStateDTO candidatePoolState = new CandidatePoolStateDTO();
        candidatePoolState.setGeneratedAt(OffsetDateTime.now().toString());
        candidatePoolState.setSourceVersion(0);
        candidatePoolState.setRequiredCount(response.getBaseData() != null ? response.getBaseData().getNeed_count() : null);
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
        candidatePoolState.setItems(items);
        recalculateCandidatePoolSummary(candidatePoolState);
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
            return preferred;
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
                if (selectedIds.add(candidate.getVolunteerId())) {
                    selected.add(candidate);
                }
            }
        }
        return selected;
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
            DraftItemDTO item = new DraftItemDTO();
            item.setVolunteerId(candidate.getVolunteerId());
            item.setTier(candidate.getTier());
            item.setSchoolName(candidate.getSchoolName());
            item.setMajorName(candidate.getMajorName());
            item.setLocked(submitted);
            item.setSource("legacy_preferred");
            draftPlanState.getItems().add(item);
        }
        syncDraftUnitsWithItems(draftPlanState, preferredCandidates, candidatePoolState);
        recalculateDraftSummary(draftPlanState, candidatePoolState);
        return draftPlanState;
    }

    private OrderedPlanStateDTO buildLegacyOrderedPlanState(DraftPlanStateDTO draftPlanState,
                                                            CandidatePoolStateDTO candidatePoolState,
                                                            List<CandidateItemDTO> candidates,
                                                            LegacyPlanSource legacyPlanSource) {
        OrderedPlanStateDTO orderedPlanState = new OrderedPlanStateDTO();
        List<OrderedItemDTO> orderedItems = buildOrderedItemsFromDraft(
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

    private void savePlanningState(Long chatSessionId, PlanningStateDTO state) {
        String dataValue = JSONObject.toJSONString(state);
        ChatSessionExtraData extraData = chatSessionExtraDataSharedService.getBySessionIdAndDataKey(
                chatSessionId, ChatSessionExtraDataConstants.PLANNING_STATE_KEY);
        if (extraData == null) {
            extraData = new ChatSessionExtraData();
            extraData.setChatSessionId(chatSessionId);
            extraData.setDataKey(ChatSessionExtraDataConstants.PLANNING_STATE_KEY);
            extraData.setDataType(DataType.JSON_OBJECT);
            extraData.setDataVersion(0);
            extraData.setDataValue(dataValue);
            chatSessionExtraDataSharedService.save(extraData);
            return;
        }
        extraData.setDataType(DataType.JSON_OBJECT);
        extraData.setDataValue(dataValue);
        chatSessionExtraDataSharedService.updateById(extraData);
    }

    private List<String> defaultList(List<String> values) {
        return values == null ? Lists.newArrayList() : values;
    }

    private List<PlanningBehaviorEventDTO> defaultBehaviorEvents(List<PlanningBehaviorEventDTO> values) {
        return values == null ? Lists.newArrayList() : values;
    }

    private int valueOrZero(Integer value) {
        return value == null ? 0 : value;
    }

    private String resolveCandidatePoolStatus(CandidatePoolStateDTO candidatePoolState) {
        if (candidatePoolState == null) {
            return "not_generated";
        }
        int effectiveTotal = candidatePoolState.getSummary() == null ? 0 : valueOrZero(candidatePoolState.getSummary().getTotal());
        int effectiveUnitTotal = candidatePoolState.getSummary() == null ? 0 : valueOrZero(candidatePoolState.getSummary().getUnitTotal());
        int required = resolveRequiredCandidateCount(candidatePoolState);
        if (effectiveTotal <= 0 && effectiveUnitTotal <= 0) {
            return "empty";
        }
        if (required > 0) {
            int effective = isMajorGroupMode(candidatePoolState) ? effectiveUnitTotal : effectiveTotal;
            if (effective > 0 && effective < required) {
                return "low_count";
            }
        }
        return "ready";
    }

    private int resolveRequiredCandidateCount(CandidatePoolStateDTO candidatePoolState) {
        if (candidatePoolState == null) {
            return 0;
        }
        if (isMajorGroupMode(candidatePoolState) && candidatePoolState.getRequiredUnitCount() != null) {
            return candidatePoolState.getRequiredUnitCount();
        }
        if (candidatePoolState.getRequiredCount() != null) {
            return candidatePoolState.getRequiredCount();
        }
        if (candidatePoolState.getRequiredUnitCount() != null) {
            return candidatePoolState.getRequiredUnitCount();
        }
        return 0;
    }

    private PlanningBehaviorEventDTO findLatestBehaviorEvent(List<PlanningBehaviorEventDTO> events, String eventType) {
        PlanningBehaviorEventDTO latest = null;
        for (PlanningBehaviorEventDTO event : defaultBehaviorEvents(events)) {
            if (event == null || !Objects.equals(eventType, event.getEventType())) {
                continue;
            }
            if (latest == null || safeString(event.getCreatedAt()).compareTo(safeString(latest.getCreatedAt())) > 0) {
                latest = event;
            }
        }
        return latest;
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

    private void appendBehaviorEvent(PlanningStateDTO state,
                                     Long tenantId,
                                     Long chatSessionId,
                                     String eventType,
                                     List<String> volunteerIds,
                                     boolean positiveFeedback) {
        if (state == null) {
            return;
        }
        if (state.getBehaviorEvents() == null) {
            state.setBehaviorEvents(Lists.newArrayList());
        }
        PlanningBehaviorEventDTO event = new PlanningBehaviorEventDTO();
        event.setEventId(UUID.randomUUID().toString());
        event.setTenantId(tenantId);
        event.setChatSessionId(chatSessionId);
        event.setEventType(eventType);
        event.setPlanVersion(state.getVersion());
        event.setGenerationMode(state.getOrderedPlanState() == null ? null : state.getOrderedPlanState().getGenerationMode());
        event.setVolunteerIds(Lists.newArrayList(defaultList(volunteerIds)));
        event.setPositiveFeedback(positiveFeedback);
        event.setCreatedAt(OffsetDateTime.now().toString());
        state.getBehaviorEvents().add(event);
    }

    private void appendUnitBehaviorEvent(PlanningStateDTO state,
                                         Long chatSessionId,
                                         String eventType,
                                         String unitId,
                                         List<OrderedItemDTO> items) {
        if (state == null || Strings.isNullOrEmpty(unitId)) {
            return;
        }
        if (state.getBehaviorEvents() == null) {
            state.setBehaviorEvents(Lists.newArrayList());
        }
        PlanningBehaviorEventDTO event = new PlanningBehaviorEventDTO();
        event.setEventId(UUID.randomUUID().toString());
        event.setChatSessionId(chatSessionId);
        event.setEventType(eventType);
        event.setPlanVersion(state.getVersion());
        event.setGenerationMode(state.getOrderedPlanState() == null ? null : state.getOrderedPlanState().getGenerationMode());
        event.setUnitIds(Lists.newArrayList(unitId));
        event.setVolunteerIds(defaultOrderedItems(items).stream()
                .map(OrderedItemDTO::getVolunteerId)
                .filter(value -> !Strings.isNullOrEmpty(value))
                .collect(Collectors.toList()));
        event.setPositiveFeedback(false);
        event.setCreatedAt(OffsetDateTime.now().toString());
        state.getBehaviorEvents().add(event);
    }

    private void appendPlanSortApplyEvent(PlanningStateDTO state,
                                          Long chatSessionId,
                                          String sortField,
                                          Map<String, Integer> beforePositions,
                                          OrderedPlanStateDTO orderedPlanState) {
        if (state == null || orderedPlanState == null) {
            return;
        }
        if (state.getBehaviorEvents() == null) {
            state.setBehaviorEvents(Lists.newArrayList());
        }
        PlanningBehaviorEventDTO event = new PlanningBehaviorEventDTO();
        event.setEventId(UUID.randomUUID().toString());
        event.setChatSessionId(chatSessionId);
        event.setEventType("plan_sort_apply");
        event.setPlanVersion(state.getVersion());
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
        event.setCreatedAt(OffsetDateTime.now().toString());
        state.getBehaviorEvents().add(event);
    }

    private String safeString(String value) {
        return value == null ? "" : value;
    }

    private void backfillLegacyProfileState(Long chatSessionId, PlanningStateDTO state) {
        if (state == null || state.getProfileState() == null || !isProfileStateEmpty(state.getProfileState())) {
            return;
        }
        CreateSessionReq scoreDetail = loadScoreDetail(chatSessionId);
        UserProfileData userProfileData = loadUserProfileData(chatSessionId);
        hydrateProfileState(state.getProfileState(), scoreDetail, userProfileData);
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
        if (scoreDetail != null && scoreDetail.getStrengthSubjectList() != null) {
            for (CreateSessionReq.SubjectScore subjectScore : scoreDetail.getStrengthSubjectList()) {
                if (subjectScore != null && !Strings.isNullOrEmpty(subjectScore.getSubjectName())) {
                    values.add(subjectScore.getSubjectName());
                }
            }
        }
        if (values.isEmpty() && userProfileData != null && userProfileData.getStrength_subject_info() != null) {
            values.addAll(defaultList(userProfileData.getStrength_subject_info().getValues()));
        }
        return distinct(values);
    }

    private List<String> extractColorVision(CreateSessionReq scoreDetail) {
        List<String> values = Lists.newArrayList();
        if (scoreDetail == null) {
            return values;
        }
        if (scoreDetail.getColorSistuation() != null) {
            for (String colorVision : scoreDetail.getColorSistuation()) {
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

    private List<CandidateItemDTO> flattenCandidates(List<VolunteerRecommendListResponse.VolunteerSchool> schools, String tier) {
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
                item.setVolunteerId(safeId(school.getPlanSchoolDataId(), major.getPlanMajorDataId(), major.getMajorId()));
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
        VolunteerRecommendListResponse response = volunteerBizService.recommendVolunteerList(tenantId, chatSessionId, false, false);
        state.setRecommendationOverlayState(buildRecommendationOverlayState(response, state.getVersion()));
        state.getStaleFlags().setRecommendationOverlay(false);
        savePlanningState(chatSessionId, state);
    }

    private List<CandidateItemDTO> resolveEffectiveCandidates(Long tenantId,
                                                              Long chatSessionId,
                                                              PlanningStateDTO state,
                                                              boolean refreshOverlayIfNeeded) {
        if (refreshOverlayIfNeeded && tenantId != null && shouldRefreshRecommendationOverlay(state)) {
            refreshRecommendationOverlay(tenantId, chatSessionId, state);
        }
        return mergeOverlayIntoCandidates(
                state.getCandidatePoolState().getItems(),
                state.getRecommendationOverlayState(),
                state);
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
        target.setProvinceName(source.getProvinceName());
        target.setCityName(source.getCityName());
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

    private void fillSchoolFields(CandidateItemDTO item, VolunteerRecommendListResponse.VolunteerSchool school) {
        item.setPlanSchoolDataId(school.getPlanSchoolDataId());
        item.setSchoolId(school.getSchoolId());
        item.setSchoolUnitCode(school.getSchoolUnitCode());
        item.setSchoolName(school.getSchool_name());
        item.setProvinceName(school.getProvince_name());
        item.setCityName(school.getCity_name());
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
                || keywords.stream().anyMatch(k -> containsIgnoreCase(item.getSchoolName(), k));
        boolean negativeMatched = negativeKeywords != null && !negativeKeywords.isEmpty()
                && negativeKeywords.stream().anyMatch(k -> containsIgnoreCase(item.getSchoolName(), k));
        return positiveMatched && !negativeMatched;
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
        return tags;
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

    private MajorExtraDataVO resolveMajorExtraData(CandidateItemDTO item) {
        if (item == null) {
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
                                                                                      List<String> schoolTags,
                                                                                      List<String> majorTags,
                                                                                      List<String> majorDisciplines,
                                                                                      List<String> majorCategories) {
        List<CandidateFilterOptionsDTO.FilterGroupDTO> groups = Lists.newArrayList();
        addFilterGroup(groups, "region.school_province", "院校省份", "provinceNames", provinceNames);
        addFilterGroup(groups, "region.school_city", "院校城市", "cityNames", cityNames);
        addFilterGroup(groups, "school.category", "院校分类", "schoolTags", filterByWhitelist(schoolTags, SCHOOL_CATEGORY_TAGS));
        addFilterGroup(groups, "school.nature", "院校性质", "schoolTags", filterByWhitelist(schoolTags, SCHOOL_NATURE_TAGS));
        addFilterGroup(groups, "school.feature", "院校特色", "schoolTags", filterByWhitelist(schoolTags, SCHOOL_FEATURE_TAGS));
        addFilterGroup(groups, "school.level", "院校层次", "schoolTags", filterByWhitelist(schoolTags, SCHOOL_LEVEL_TAGS));
        addFilterGroup(groups, "major.discipline", "专业门类", "majorTags", majorDisciplines);
        addFilterGroup(groups, "major.category", "专业大类", "majorKeywords", majorCategories);
        addFilterGroup(groups, "admission.type", "招生类型", "majorTags", filterByWhitelist(majorTags, ADMISSION_TYPE_TAGS));
        addFilterGroup(groups, "constraint.limit", "限报要求", "majorTags", filterByWhitelist(majorTags, CONSTRAINT_LIMIT_TAGS));
        addFilterGroup(groups, "school.tag", "院校标签", "schoolTags",
                excludeValues(schoolTags, SCHOOL_CATEGORY_TAGS, SCHOOL_NATURE_TAGS, SCHOOL_FEATURE_TAGS, SCHOOL_LEVEL_TAGS));
        addFilterGroup(groups, "major.tag", "专业标签", "majorTags",
                excludeValues(majorTags, ADMISSION_TYPE_TAGS, CONSTRAINT_LIMIT_TAGS,
                        new HashSet<String>(majorDisciplines), new HashSet<String>(majorCategories)));
        return groups;
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

    private boolean containsDraftItem(DraftPlanStateDTO draft, String volunteerId) {
        return draft.getItems().stream().anyMatch(item -> volunteerId.equals(item.getVolunteerId()));
    }

    private OrderedPlanStateDTO ensureOrderedPlanState(PlanningStateDTO state) {
        OrderedPlanStateDTO orderedPlanState = state.getOrderedPlanState();
        if (orderedPlanState.getItems().isEmpty() && !state.getDraftPlanState().getItems().isEmpty()) {
            List<CandidateItemDTO> effectiveCandidates = resolveEffectiveCandidates(null, state.getSessionId(), state, false);
            orderedPlanState.setItems(buildOrderedItemsFromDraft(
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
            sprintCount = state.getOrderedPlanState().getSummary().getTierCounts().get("冲") == null ? 0
                    : state.getOrderedPlanState().getSummary().getTierCounts().get("冲");
            protectCount = state.getOrderedPlanState().getSummary().getTierCounts().get("保") == null ? 0
                    : state.getOrderedPlanState().getSummary().getTierCounts().get("保");
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
            check.setSummary("冲区占比过高且保区占比过低");
            check.setDetail("冲区占比超过40%，且保区占比低于20%。");
            check.setSuggestedAction("建议减少冲区志愿并补充保区志愿，优先调整到接近3:3:4。");
            return check;
        }
        if (sprintRatio > 0.4D && !sprintWithinExpected) {
            check.setPassed(false);
            check.setLevel("risk");
            check.setSummary("冲区占比过高");
            check.setDetail("冲区占比超过40%。");
            check.setSuggestedAction("建议适当减少冲区志愿，补充稳区或保区志愿。");
            return check;
        }
        if (sprintRatio < 0.2D && !sprintMeetsExpected) {
            check.setPassed(false);
            check.setLevel("warn");
            check.setSummary("冲区占比偏低");
            check.setDetail("冲区占比低于20%。");
            check.setSuggestedAction("建议适当增加冲区志愿，提高分数利用率。");
            return check;
        }
        if (protectRatio < 0.2D && !protectMeetsExpected) {
            check.setPassed(false);
            check.setLevel("risk");
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
            check.setSummary("当前志愿数量少于官方要求");
            check.setDetail(String.format("当前数量 %d，小于要求数量 %d。", currentCount, requiredCount));
            check.setSuggestedAction("建议通过补偿或手动补选将志愿数量补足。");
            return check;
        }
        if (currentCount > requiredCount) {
            check.setPassed(false);
            check.setLevel("warn");
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
                check.setSuggestedAction("若不接受中外合作办学，可将相关志愿移出草稿或加入硬约束。");
                check.getAffectedVolunteerIds().add(orderedItem.getVolunteerId());
            }
        }
        return check;
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

            trimCompensationActionsForRemainingCapacity(state, preview, availableUnits);
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

        trimCompensationActionsForRemainingCapacity(state, preview, null);
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

        for (CompensationActionDTO action : preview.getActions()) {
            if (action == null) {
                continue;
            }
            boolean replacementAction = isReplacementCompensationAction(action);
            if (remainingCapacity > 0 && replacementAction) {
                action.setUnitIds(Lists.newArrayList());
                action.setVolunteerIds(Lists.newArrayList());
                continue;
            }
            if (remainingCapacity <= 1 && isLimitedCapacityOptionalAddAction(action)) {
                action.setUnitIds(Lists.newArrayList());
                action.setVolunteerIds(Lists.newArrayList());
                continue;
            }
            if (remainingCapacity == 0 && !replacementAction) {
                action.setUnitIds(Lists.newArrayList());
                action.setVolunteerIds(Lists.newArrayList());
                continue;
            }
            int actionLimit = replacementAction ? Integer.MAX_VALUE : Math.max(remainingCapacity, 0);
            if (majorGroupMode) {
                List<String> keptUnitIds = defaultList(action.getUnitIds()).stream()
                        .filter(id -> !Strings.isNullOrEmpty(id))
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
                continue;
            }

            List<String> keptVolunteerIds = defaultList(action.getVolunteerIds()).stream()
                    .filter(id -> !Strings.isNullOrEmpty(id))
                    .limit(actionLimit)
                    .collect(Collectors.toList());
            action.setVolunteerIds(keptVolunteerIds);
        }
    }

    private boolean isReplacementCompensationAction(CompensationActionDTO action) {
        if (action == null || Strings.isNullOrEmpty(action.getType())) {
            return false;
        }
        return "rebalance_protect_ratio".equals(action.getType())
                || "replace_probability_gap".equals(action.getType());
    }

    private boolean isLimitedCapacityOptionalAddAction(CompensationActionDTO action) {
        return action != null && "fill_probability_gap".equals(action.getType());
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
        return groupCandidatesToPlanningUnits(candidates, requiredMajorCount).stream()
                .filter(unit -> unit != null && !Strings.isNullOrEmpty(unit.getUnitId()))
                .filter(unit -> !selectedUnitIds.contains(unit.getUnitId()))
                .filter(this::isCompensationSafeUnit)
                .sorted(Comparator.comparing((PlanningUnitDTO unit) -> unit.getFinalScore() == null ? 0D : unit.getFinalScore()).reversed())
                .collect(Collectors.toList());
    }

    private List<CandidateItemDTO> buildAvailableCompensationCandidates(PlanningStateDTO state,
                                                                        List<CandidateItemDTO> candidates) {
        if (!isMajorGroupMode(state.getCandidatePoolState())) {
            return candidates.stream()
                    .filter(item -> !containsDraftItem(state.getDraftPlanState(), item.getVolunteerId()))
                    .filter(item -> !state.getDraftPlanState().getBannedVolunteerIds().contains(item.getVolunteerId()))
                    .filter(this::isCompensationSafeCandidate)
                    .collect(Collectors.toList());
        }
        Set<String> selectedUnitIds = state.getDraftPlanState().getItems().stream()
                .map(item -> resolveInitialRecommendationUnitId(findCandidate(candidates, item.getVolunteerId())))
                .filter(unitId -> !Strings.isNullOrEmpty(unitId))
                .collect(Collectors.toCollection(LinkedHashSet::new));
        return groupCandidatesByUnit(candidates).values().stream()
                .map(unitCandidates -> unitCandidates.stream()
                        .filter(this::isCompensationSafeCandidate)
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

    private CompensationActionDTO buildTotalCountCompensation(PlanningStateDTO state, List<CandidateItemDTO> availableCandidates) {
        Integer requiredCount = state.getCandidatePoolState().getRequiredCount();
        int currentCount = state.getOrderedPlanState().getItems().isEmpty()
                ? state.getDraftPlanState().getItems().size() : state.getOrderedPlanState().getItems().size();
        if (requiredCount == null || requiredCount <= currentCount) {
            return null;
        }
        int gap = requiredCount - currentCount;
        List<String> volunteerIds = availableCandidates.stream()
                .sorted(Comparator.comparing(item -> item.getFinalScore() == null ? 0D : item.getFinalScore(), Comparator.reverseOrder()))
                .limit(gap)
                .map(CandidateItemDTO::getVolunteerId)
                .collect(Collectors.toList());
        if (volunteerIds.isEmpty()) {
            return null;
        }

        CompensationActionDTO action = new CompensationActionDTO();
        action.setType("fill_total_count");
        action.setLevel("risk");
        action.setSourceCheckCode("count_validation");
        action.setSummary("补足志愿总数量");
        action.setDetail(String.format("当前志愿数量不足，建议补充 %d 个候选。", gap));
        action.setVolunteerIds(volunteerIds);
        return action;
    }

    private CompensationActionDTO buildTotalCountCompensationForUnits(PlanningStateDTO state,
                                                                      List<PlanningUnitDTO> availableUnits) {
        Integer requiredCount = state.getCandidatePoolState().getRequiredCount();
        int currentCount = !defaultOrderedUnits(state.getOrderedPlanState().getUnits()).isEmpty()
                ? defaultOrderedUnits(state.getOrderedPlanState().getUnits()).size()
                : defaultDraftUnits(state.getDraftPlanState().getUnits()).size();
        if (requiredCount == null || requiredCount <= currentCount) {
            return null;
        }
        int gap = requiredCount - currentCount;
        List<PlanningUnitDTO> selectedUnits = availableUnits.stream().limit(gap).collect(Collectors.toList());
        if (selectedUnits.isEmpty()) {
            return null;
        }
        CompensationActionDTO action = new CompensationActionDTO();
        action.setType("fill_total_count");
        action.setLevel("risk");
        action.setSourceCheckCode("count_validation");
        action.setSummary("补足志愿总数量");
        action.setDetail(String.format("当前志愿数量不足，建议补充 %d 个专业组。", gap));
        action.setUnitIds(selectedUnits.stream().map(PlanningUnitDTO::getUnitId).collect(Collectors.toList()));
        action.setVolunteerIds(flattenPlanningUnitVolunteerIds(selectedUnits));
        return action;
    }

    private CompensationActionDTO buildSafetyCompensation(PlanningStateDTO state,
                                                          List<CandidateItemDTO> candidates,
                                                          List<CandidateItemDTO> availableCandidates) {
        String sourceProvinceName = state.getCandidatePoolState().getSourceProvinceName();
        Integer userScore = state.getCandidatePoolState().getUserScore();
        if (userScore != null && userScore >= 580) {
            return null;
        }
        if (Strings.isNullOrEmpty(sourceProvinceName)) {
            return null;
        }

        int localProtectCount = 0;
        for (OrderedItemDTO orderedItem : state.getOrderedPlanState().getItems()) {
            if (!"保".equals(orderedItem.getTier())) {
                continue;
            }
            CandidateItemDTO candidateItem = findCandidate(candidates, orderedItem.getVolunteerId());
            if (candidateItem != null && containsIgnoreCase(candidateItem.getProvinceName(), sourceProvinceName)) {
                localProtectCount++;
            }
        }
        if (localProtectCount >= 2) {
            return null;
        }

        int need = 2 - localProtectCount;
        List<String> volunteerIds = availableCandidates.stream()
                .filter(item -> "保".equals(item.getTier()))
                .filter(item -> containsIgnoreCase(item.getProvinceName(), sourceProvinceName))
                .limit(need)
                .map(CandidateItemDTO::getVolunteerId)
                .collect(Collectors.toList());
        if (volunteerIds.isEmpty()) {
            return null;
        }

        CompensationActionDTO action = new CompensationActionDTO();
        action.setType("add_local_protect");
        action.setLevel("risk");
        action.setSourceCheckCode("safety_guard");
        action.setSummary("补充本省保底志愿");
        action.setDetail("当前本省保底志愿不足，建议优先补充本省保区候选。");
        action.setVolunteerIds(volunteerIds);
        return action;
    }

    private CompensationActionDTO buildSafetyCompensationForUnits(PlanningStateDTO state,
                                                                  List<PlanningUnitDTO> availableUnits) {
        String sourceProvinceName = state.getCandidatePoolState().getSourceProvinceName();
        Integer userScore = state.getCandidatePoolState().getUserScore();
        if (userScore != null && userScore >= 580) {
            return null;
        }
        if (Strings.isNullOrEmpty(sourceProvinceName)) {
            return null;
        }

        int localProtectCount = (int) defaultOrderedUnits(state.getOrderedPlanState().getUnits()).stream()
                .filter(unit -> "保".equals(unit.getTier()))
                .filter(unit -> containsIgnoreCase(unit.getProvinceName(), sourceProvinceName))
                .count();
        if (localProtectCount >= 2) {
            return null;
        }

        int need = 2 - localProtectCount;
        List<PlanningUnitDTO> selectedUnits = availableUnits.stream()
                .filter(unit -> "保".equals(unit.getTier()))
                .filter(unit -> containsIgnoreCase(unit.getProvinceName(), sourceProvinceName))
                .limit(need)
                .collect(Collectors.toList());
        if (selectedUnits.isEmpty()) {
            return null;
        }

        CompensationActionDTO action = new CompensationActionDTO();
        action.setType("add_local_protect");
        action.setLevel("risk");
        action.setSourceCheckCode("safety_guard");
        action.setSummary("补充本省保底志愿");
        action.setDetail("当前本省保底专业组不足，建议优先补充本省保区专业组。");
        action.setUnitIds(selectedUnits.stream().map(PlanningUnitDTO::getUnitId).collect(Collectors.toList()));
        action.setVolunteerIds(flattenPlanningUnitVolunteerIds(selectedUnits));
        return action;
    }

    private CompensationActionDTO buildRatioCompensation(PlanningStateDTO state, List<CandidateItemDTO> availableCandidates) {
        int total = state.getOrderedPlanState().getItems().isEmpty()
                ? state.getDraftPlanState().getItems().size() : state.getOrderedPlanState().getItems().size();
        if (total <= 0) {
            return null;
        }
        int protectCount = state.getOrderedPlanState().getSummary().getTierCounts().get("保") == null ? 0
                : state.getOrderedPlanState().getSummary().getTierCounts().get("保");
        double protectRatio = protectCount * 1D / total;
        if (protectRatio >= 0.2D) {
            return null;
        }

        int need = Math.max(1, (int) Math.ceil(total * 0.2D) - protectCount);
        List<String> volunteerIds = availableCandidates.stream()
                .filter(item -> "保".equals(item.getTier()))
                .limit(need)
                .map(CandidateItemDTO::getVolunteerId)
                .collect(Collectors.toList());
        if (volunteerIds.isEmpty()) {
            return null;
        }

        CompensationActionDTO action = new CompensationActionDTO();
        action.setType("rebalance_protect_ratio");
        action.setLevel("warn");
        action.setSourceCheckCode("ratio_distribution");
        action.setSummary("补充保区志愿以平衡区间");
        action.setDetail("当前保区占比偏低，建议补充保区候选以改善冲稳保配比。");
        action.setVolunteerIds(volunteerIds);
        return action;
    }

    private CompensationActionDTO buildRatioCompensationForUnits(PlanningStateDTO state,
                                                                 List<PlanningUnitDTO> availableUnits) {
        int total = defaultOrderedUnits(state.getOrderedPlanState().getUnits()).isEmpty()
                ? defaultDraftUnits(state.getDraftPlanState().getUnits()).size()
                : defaultOrderedUnits(state.getOrderedPlanState().getUnits()).size();
        if (total <= 0) {
            return null;
        }
        int protectCount = (int) defaultOrderedUnits(state.getOrderedPlanState().getUnits()).stream()
                .filter(unit -> "保".equals(unit.getTier()))
                .count();
        double protectRatio = protectCount * 1D / total;
        if (protectRatio >= 0.2D) {
            return null;
        }

        int need = Math.max(1, (int) Math.ceil(total * 0.2D) - protectCount);
        List<PlanningUnitDTO> selectedUnits = availableUnits.stream()
                .filter(unit -> "保".equals(unit.getTier()))
                .limit(need)
                .collect(Collectors.toList());
        if (selectedUnits.isEmpty()) {
            return null;
        }

        CompensationActionDTO action = new CompensationActionDTO();
        action.setType("rebalance_protect_ratio");
        action.setLevel("warn");
        action.setSourceCheckCode("ratio_distribution");
        action.setSummary("补充保区志愿以平衡区间");
        action.setDetail("当前保区专业组占比偏低，建议补充保区专业组以改善冲稳保配比。");
        action.setUnitIds(selectedUnits.stream().map(PlanningUnitDTO::getUnitId).collect(Collectors.toList()));
        action.setVolunteerIds(flattenPlanningUnitVolunteerIds(selectedUnits));
        return action;
    }

    private CompensationActionDTO buildGradientCompensation(PlanningStateDTO state,
                                                            List<CandidateItemDTO> candidates,
                                                            List<CandidateItemDTO> availableCandidates) {
        List<OrderedItemDTO> orderedItems = state.getOrderedPlanState().getItems();
        if (orderedItems.size() <= 1) {
            return null;
        }
        for (int i = 1; i < orderedItems.size(); i++) {
            OrderedItemDTO previous = orderedItems.get(i - 1);
            OrderedItemDTO current = orderedItems.get(i);
            Double previousRatio = admissionRatioOf(candidates, previous.getVolunteerId());
            Double currentRatio = admissionRatioOf(candidates, current.getVolunteerId());
            if (previousRatio == null || currentRatio == null || Math.abs(currentRatio - previousRatio) <= 8D) {
                continue;
            }
            double min = Math.min(previousRatio, currentRatio);
            double max = Math.max(previousRatio, currentRatio);
            double midpoint = (min + max) / 2D;
            List<String> volunteerIds = availableCandidates.stream()
                    .filter(item -> item.getAdmissionRatio() != null)
                    .filter(item -> item.getAdmissionRatio() > min && item.getAdmissionRatio() < max)
                    .sorted(Comparator.comparingDouble(item -> Math.abs(item.getAdmissionRatio() - midpoint)))
                    .limit(2)
                    .map(CandidateItemDTO::getVolunteerId)
                    .collect(Collectors.toList());
            if (volunteerIds.isEmpty()) {
                continue;
            }

            CompensationActionDTO action = new CompensationActionDTO();
            action.setType("fill_probability_gap");
            action.setLevel("warn");
            action.setSourceCheckCode("probability_gap");
            action.setSummary("补充梯度断层区间的候选");
            action.setDetail(String.format("当前 %.1f 到 %.1f 的录取概率区间存在断层，建议补充中间梯度候选。", min, max));
            action.setVolunteerIds(volunteerIds);
            return action;
        }
        return null;
    }

    private CompensationActionDTO buildGradientCompensationForUnits(PlanningStateDTO state,
                                                                    List<PlanningUnitDTO> availableUnits) {
        List<OrderedUnitDTO> orderedUnits = defaultOrderedUnits(state.getOrderedPlanState().getUnits());
        if (orderedUnits.size() <= 1) {
            return null;
        }
        for (int i = 1; i < orderedUnits.size(); i++) {
            OrderedUnitDTO previous = orderedUnits.get(i - 1);
            OrderedUnitDTO current = orderedUnits.get(i);
            Double previousRatio = previous.getAdmissionRatio();
            Double currentRatio = current.getAdmissionRatio();
            if (previousRatio == null || currentRatio == null || Math.abs(currentRatio - previousRatio) <= 8D) {
                continue;
            }
            double min = Math.min(previousRatio, currentRatio);
            double max = Math.max(previousRatio, currentRatio);
            double midpoint = (min + max) / 2D;
            List<PlanningUnitDTO> selectedUnits = availableUnits.stream()
                    .filter(unit -> unit.getAdmissionRatio() != null)
                    .filter(unit -> unit.getAdmissionRatio() > min && unit.getAdmissionRatio() < max)
                    .sorted(Comparator.comparingDouble(unit -> Math.abs(unit.getAdmissionRatio() - midpoint)))
                    .limit(2)
                    .collect(Collectors.toList());
            if (selectedUnits.isEmpty()) {
                continue;
            }

            CompensationActionDTO action = new CompensationActionDTO();
            action.setType("fill_probability_gap");
            action.setLevel("warn");
            action.setSourceCheckCode("probability_gap");
            action.setSummary("补充梯度断层区间的候选");
            action.setDetail(String.format("当前 %.1f 到 %.1f 的录取概率区间存在断层，建议补充中间梯度专业组。", min, max));
            action.setUnitIds(selectedUnits.stream().map(PlanningUnitDTO::getUnitId).collect(Collectors.toList()));
            action.setVolunteerIds(flattenPlanningUnitVolunteerIds(selectedUnits));
            return action;
        }
        return null;
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

    private List<String> flattenPlanningUnitVolunteerIds(List<PlanningUnitDTO> units) {
        return (units == null ? Lists.<PlanningUnitDTO>newArrayList() : units).stream()
                .flatMap(unit -> defaultPlanningUnitMajors(unit.getSelectedMajors()).stream())
                .map(PlanningUnitMajorDTO::getVolunteerId)
                .filter(id -> !Strings.isNullOrEmpty(id))
                .collect(Collectors.toList());
    }

    private boolean isCompensationSafeCandidate(CandidateItemDTO item) {
        if (item == null) {
            return false;
        }
        if (item.getTuitionPerYear() != null && item.getTuitionPerYear() > 20000) {
            return false;
        }
        if (containsAny(item.getSchoolName(), "中外合作") || containsAny(item.getMajorName(), "中外合作")) {
            return false;
        }
        if (item.getReasonCodes().stream().anyMatch(tag -> containsAny(tag, "中外合作", "专项", "公费", "定向", "强基", "高校专项", "地方专项"))) {
            return false;
        }
        if (item.getMustSubjects().stream().anyMatch(tag -> containsAny(tag, "单科", "语种", "性别"))) {
            return false;
        }
        return item.getRiskFlags().stream().noneMatch(tag -> containsAny(tag, "special", "foreign", "limited"));
    }

    private void appendOperationLogs(PlanningStateDTO state, List<CompensationActionDTO> actions) {
        for (CompensationActionDTO action : actions) {
            OperationLogDTO logItem = new OperationLogDTO();
            logItem.setType("compensation_apply");
            logItem.setOperator("system");
            logItem.setCreatedAt(OffsetDateTime.now().toString());
            logItem.setDetail(action.getType() + ":" + action.getSummary());
            logItem.setVolunteerIds(new ArrayList<String>(action.getVolunteerIds()));
            state.getOperationLogs().add(logItem);
        }
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

    private List<OrderedItemDTO> buildOrderedItemsFromDraft(DraftPlanStateDTO draft,
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
        return rebuildOrderedItems(items);
    }

    private void replaceDraftWithInitialRecommendation(PlanningStateDTO state, List<CandidateItemDTO> candidates) {
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

    private boolean canAutoSelectCandidate(CandidateItemDTO candidate,
                                           Set<String> selectedVolunteerIds,
                                           Set<String> bannedVolunteerIds) {
        return candidate != null
                && !Strings.isNullOrEmpty(candidate.getVolunteerId())
                && !selectedVolunteerIds.contains(candidate.getVolunteerId())
                && !bannedVolunteerIds.contains(candidate.getVolunteerId());
    }

    private DraftItemDTO toAutoDraftItem(CandidateItemDTO candidate) {
        DraftItemDTO item = new DraftItemDTO();
        item.setVolunteerId(candidate.getVolunteerId());
        item.setTier(candidate.getTier());
        item.setSchoolName(candidate.getSchoolName());
        item.setMajorName(candidate.getMajorName());
        item.setSource("initial_auto");
        item.setLocked(false);
        return item;
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
            draftUnit.setMajorItems(Lists.newArrayList(defaultPlanningUnitMajors(unit.getSelectedMajors())));
            result.add(draftUnit);
        }
        return result;
    }

    private void syncDraftUnitsWithItems(DraftPlanStateDTO draft,
                                         List<CandidateItemDTO> candidates,
                                         CandidatePoolStateDTO candidatePoolState) {
        if (draft == null) {
            return;
        }
        if (!isMajorGroupMode(candidatePoolState)) {
            draft.setUnits(Lists.newArrayList());
            return;
        }
        Map<String, CandidateItemDTO> candidateMap = candidates == null
                ? new LinkedHashMap<String, CandidateItemDTO>()
                : candidates.stream()
                .filter(candidate -> !Strings.isNullOrEmpty(candidate.getVolunteerId()))
                .collect(Collectors.toMap(CandidateItemDTO::getVolunteerId, candidate -> candidate, (left, right) -> left, LinkedHashMap::new));
        Map<String, DraftUnitDTO> unitMap = new LinkedHashMap<String, DraftUnitDTO>();
        for (DraftItemDTO item : defaultDraftItems(draft.getItems())) {
            CandidateItemDTO candidate = candidateMap.get(item.getVolunteerId());
            String unitId = candidate == null ? resolveDraftOrOrderedUnitId(item) : resolveInitialRecommendationUnitId(candidate);
            DraftUnitDTO unit = unitMap.computeIfAbsent(unitId, key -> {
                DraftUnitDTO dto = new DraftUnitDTO();
                dto.setUnitId(key);
                dto.setTier(candidate == null ? item.getTier() : candidate.getTier());
                dto.setSchoolName(candidate == null ? item.getSchoolName() : candidate.getSchoolName());
                dto.setSource(item.getSource());
                dto.setLocked(item.getLocked());
                return dto;
            });
            PlanningUnitMajorDTO major = new PlanningUnitMajorDTO();
            major.setVolunteerId(item.getVolunteerId());
            major.setMajorName(item.getMajorName());
            major.setTier(item.getTier());
            major.setSelected(true);
            if (candidate != null) {
                major.setMajorId(candidate.getMajorId());
                major.setMajorCode(candidate.getMajorCode());
                major.setMajorCategoryId(candidate.getMajorCategoryId());
                major.setMajorSubCategoryId(candidate.getMajorSubCategoryId());
                major.setAdmissionRatio(candidate.getAdmissionRatio());
                major.setFinalScore(candidate.getFinalScore());
                major.setIntentScore(candidate.getIntentScore());
                major.setPreferred(candidate.getPreferred());
                major.setSafetyMajor(candidate.getAdmissionRatio() != null
                        && candidate.getSchoolEnrollRatio() != null
                        && isSafetyMajorRatio(candidate.getAdmissionRatio(), candidate.getSchoolEnrollRatio()));
                major.setTuitionPerYear(candidate.getTuitionPerYear());
                major.setRankInTier(candidate.getRankInTier());
            }
            unit.getMajorItems().add(major);
            unit.setLocked(Boolean.TRUE.equals(unit.getLocked()) || Boolean.TRUE.equals(item.getLocked()));
        }
        draft.setUnits(Lists.newArrayList(unitMap.values()));
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
                return dto;
            });
            PlanningUnitMajorDTO major = majorMap.get(item.getVolunteerId());
            CandidateItemDTO candidate = candidateMap.get(item.getVolunteerId());
            if (major == null) {
                major = new PlanningUnitMajorDTO();
                major.setVolunteerId(item.getVolunteerId());
                major.setMajorName(item.getMajorName());
                major.setTier(item.getTier());
                major.setSelected(true);
                if (candidate != null) {
                    major.setMajorId(candidate.getMajorId());
                    major.setMajorCode(candidate.getMajorCode());
                    major.setMajorCategoryId(candidate.getMajorCategoryId());
                    major.setMajorSubCategoryId(candidate.getMajorSubCategoryId());
                    major.setAdmissionRatio(candidate.getAdmissionRatio());
                    major.setFinalScore(candidate.getFinalScore());
                    major.setIntentScore(candidate.getIntentScore());
                    major.setPreferred(candidate.getPreferred());
                    major.setSafetyMajor(candidate.getAdmissionRatio() != null
                            && candidate.getSchoolEnrollRatio() != null
                            && isSafetyMajorRatio(candidate.getAdmissionRatio(), candidate.getSchoolEnrollRatio()));
                    major.setTuitionPerYear(candidate.getTuitionPerYear());
                    major.setRankInTier(candidate.getRankInTier());
                }
            }
            unit.getMajorItems().add(major);
            if (candidate != null) {
                unit.setProvinceName(candidate.getProvinceName());
                unit.setCityName(candidate.getCityName());
                unit.setAdmissionRatio(candidate.getSchoolEnrollRatio());
                unit.setFinalScore(candidate.getFinalScore());
                unit.setSchoolEnrollRatio(candidate.getSchoolEnrollRatio());
            }
            if (unit.getPosition() == null || (item.getPosition() != null && item.getPosition() < unit.getPosition())) {
                unit.setPosition(item.getPosition());
            }
            if (Boolean.TRUE.equals(item.getPinned())) {
                unit.setPinned(true);
                if (unit.getPinnedPosition() == null || (item.getPinnedPosition() != null && item.getPinnedPosition() < unit.getPinnedPosition())) {
                    unit.setPinnedPosition(item.getPinnedPosition());
                }
            }
        }
        return Lists.newArrayList(unitMap.values());
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

    private List<OrderedItemDTO> rebuildOrderedItems(List<OrderedItemDTO> items) {
        List<OrderedItemDTO> ordered = new ArrayList<OrderedItemDTO>(items);
        List<OrderedItemDTO> pinnedItems = ordered.stream()
                .filter(item -> Boolean.TRUE.equals(item.getPinned()) && item.getPinnedPosition() != null)
                .sorted(Comparator.comparingInt(item -> normalizePosition(item.getPinnedPosition(), ordered.size())))
                .collect(Collectors.toList());
        List<OrderedItemDTO> floatingItems = ordered.stream()
                .filter(item -> !Boolean.TRUE.equals(item.getPinned()) || item.getPinnedPosition() == null)
                .collect(Collectors.toList());

        List<OrderedItemDTO> result = new ArrayList<OrderedItemDTO>();
        for (int i = 0; i < ordered.size(); i++) {
            result.add(null);
        }
        for (OrderedItemDTO pinnedItem : pinnedItems) {
            int index = normalizeIndex(pinnedItem.getPinnedPosition(), ordered.size());
            while (index < result.size() && result.get(index) != null) {
                index++;
            }
            if (index >= result.size()) {
                index = findLastEmptyIndex(result);
            }
            result.set(index, pinnedItem);
        }
        int floatingIndex = 0;
        for (int i = 0; i < result.size(); i++) {
            if (result.get(i) != null) {
                continue;
            }
            result.set(i, floatingItems.get(floatingIndex++));
        }
        for (int i = 0; i < result.size(); i++) {
            result.get(i).setPosition(i + 1);
        }
        return result;
    }

    private List<OrderedItemDTO> sortOrderedPlanItems(List<OrderedItemDTO> items,
                                                      List<CandidateItemDTO> candidates,
                                                      String sortField) {
        CandidateResolver candidateResolver = new CandidateResolver(candidates);
        List<OrderedItemDTO> floatingItems = defaultOrderedItems(items).stream()
                .filter(item -> !Boolean.TRUE.equals(item.getPinned()) || item.getPinnedPosition() == null)
                .sorted(buildOrderedItemSortComparator(candidateResolver, sortField))
                .collect(Collectors.toList());
        List<OrderedItemDTO> result = Lists.newArrayList();
        int floatingIndex = 0;
        for (OrderedItemDTO item : defaultOrderedItems(items)) {
            if (Boolean.TRUE.equals(item.getPinned()) && item.getPinnedPosition() != null) {
                result.add(item);
            } else {
                result.add(floatingItems.get(floatingIndex++));
            }
        }
        return result;
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
        List<OrderedUnitDTO> floatingUnits = units.stream()
                .filter(unit -> !Boolean.TRUE.equals(unit.getPinned()) || unit.getPinnedPosition() == null)
                .sorted(buildOrderedUnitSortComparator(candidateResolver, sortField))
                .collect(Collectors.toList());
        List<OrderedUnitDTO> sortedUnits = Lists.newArrayList();
        int floatingIndex = 0;
        for (OrderedUnitDTO unit : units) {
            if (Boolean.TRUE.equals(unit.getPinned()) && unit.getPinnedPosition() != null) {
                sortedUnits.add(unit);
            } else {
                sortedUnits.add(floatingUnits.get(floatingIndex++));
            }
        }
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
            if (!Boolean.TRUE.equals(item.getPinned())) {
                item.setOrderedBy("user");
                item.setOrderReason("user_sort_" + sortField);
            }
        }
        for (OrderedUnitDTO unit : defaultOrderedUnits(orderedPlanState == null ? null : orderedPlanState.getUnits())) {
            if (!Boolean.TRUE.equals(unit.getPinned())) {
                unit.setOrderedBy("user");
                unit.setOrderReason("user_sort_" + sortField);
            }
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

    private int resolveMovableTargetIndex(List<OrderedItemDTO> items, int currentIndex, Integer requestedPosition) {
        if (items == null || items.isEmpty() || currentIndex < 0 || currentIndex >= items.size()) {
            return currentIndex;
        }
        int requestedIndex = normalizeIndex(requestedPosition, items.size());
        if (requestedIndex == currentIndex) {
            return currentIndex;
        }
        int direction = requestedIndex > currentIndex ? 1 : -1;
        int targetIndex = requestedIndex;
        while (targetIndex >= 0 && targetIndex < items.size()) {
            OrderedItemDTO candidate = items.get(targetIndex);
            if (!Boolean.TRUE.equals(candidate.getPinned()) || targetIndex == currentIndex) {
                return targetIndex;
            }
            targetIndex += direction;
        }
        return currentIndex;
    }

    private List<OrderedItemDTO> moveWithinUnlockedSlots(List<OrderedItemDTO> items, int fromIndex, int toIndex) {
        if (items == null || items.isEmpty() || fromIndex == toIndex) {
            return items;
        }
        List<OrderedItemDTO> reordered = new ArrayList<OrderedItemDTO>(items);
        OrderedItemDTO target = reordered.remove(fromIndex);
        reordered.add(toIndex, target);
        return reordered;
    }

    private int findLastEmptyIndex(List<OrderedItemDTO> result) {
        for (int i = result.size() - 1; i >= 0; i--) {
            if (result.get(i) == null) {
                return i;
            }
        }
        return Math.max(0, result.size() - 1);
    }

    private OrderedItemDTO findOrderedItem(List<OrderedItemDTO> items, String volunteerId) {
        return items.stream().filter(item -> volunteerId.equals(item.getVolunteerId())).findFirst().orElse(null);
    }

    private int normalizeIndex(Integer position, int size) {
        if (size <= 0) {
            return 0;
        }
        return Math.max(0, Math.min(size - 1, normalizePosition(position, size) - 1));
    }

    private int normalizePosition(Integer position, int size) {
        if (size <= 0) {
            return 1;
        }
        if (position == null || position <= 0) {
            return 1;
        }
        return Math.min(position, size);
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
        return items.stream().filter(item -> volunteerId.equals(item.getVolunteerId())).findFirst().orElse(null);
    }

    private void recalculateDraftSummary(DraftPlanStateDTO draft, CandidatePoolStateDTO candidatePoolState) {
        boolean majorGroupMode = isMajorGroupMode(candidatePoolState);
        int unitTotal = countDraftSummaryTotal(draft.getItems(), majorGroupMode);
        int targetUnitCount = candidatePoolState != null && candidatePoolState.getRequiredCount() != null
                ? candidatePoolState.getRequiredCount() : 0;
        int sprintUnits = countDraftTier(draft.getItems(), "冲", majorGroupMode);
        int safeUnits = countDraftTier(draft.getItems(), "稳", majorGroupMode);
        int protectUnits = countDraftTier(draft.getItems(), "保", majorGroupMode);
        draft.getSummary().setUnitTotal(unitTotal);
        draft.getSummary().setTargetUnitCount(targetUnitCount);
        draft.getSummary().setTotal(unitTotal);
        draft.getSummary().setTargetCount(targetUnitCount);
        draft.getSummary().getUnitTierCounts().put("冲", sprintUnits);
        draft.getSummary().getUnitTierCounts().put("稳", safeUnits);
        draft.getSummary().getUnitTierCounts().put("保", protectUnits);
        draft.getSummary().getTierCounts().put("冲", sprintUnits);
        draft.getSummary().getTierCounts().put("稳", safeUnits);
        draft.getSummary().getTierCounts().put("保", protectUnits);
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

    private int countDraftSummaryTotal(List<DraftItemDTO> items, boolean majorGroupMode) {
        if (!majorGroupMode) {
            return items == null ? 0 : items.size();
        }
        return (int) defaultDraftItems(items).stream()
                .map(this::resolveDraftOrOrderedUnitId)
                .filter(Objects::nonNull)
                .distinct()
                .count();
    }

    private int countDraftTier(List<DraftItemDTO> items, String tier, boolean majorGroupMode) {
        if (!majorGroupMode) {
            return (int) defaultDraftItems(items).stream().filter(item -> tier.equals(item.getTier())).count();
        }
        return (int) defaultDraftItems(items).stream()
                .filter(item -> tier.equals(item.getTier()))
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

    private PlanningStateDTO saveDraftState(Long chatSessionId, PlanningStateDTO state) {
        state.setSessionId(chatSessionId);
        state.setVersion((state.getVersion() == null ? 0 : state.getVersion()) + 1);
        state.setPhase("drafting");
        boolean orderedSynced = syncOrderedPlanWithDraft(state);
        state.getStaleFlags().setOrderedPlan(!orderedSynced);
        state.getStaleFlags().setPlanAdjustment(true);
        state.getStaleFlags().setReview(true);
        savePlanningState(chatSessionId, state);
        return state;
    }

    private PlanningStateDTO saveOrderedState(Long chatSessionId, PlanningStateDTO state) {
        state.setSessionId(chatSessionId);
        state.setVersion((state.getVersion() == null ? 0 : state.getVersion()) + 1);
        state.setPhase("ordered");
        state.getStaleFlags().setOrderedPlan(false);
        state.getStaleFlags().setPlanAdjustment(true);
        state.getStaleFlags().setReview(true);
        savePlanningState(chatSessionId, state);
        return state;
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

    private int countPinnedOrderedItems(OrderedPlanStateDTO orderedPlanState) {
        return orderedPlanState == null || orderedPlanState.getItems() == null ? 0
                : (int) orderedPlanState.getItems().stream().filter(item -> Boolean.TRUE.equals(item.getPinned())).count();
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
            orderedPlanState.setItems(buildOrderedItemsFromDraft(
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
            updated.setPinned(orderedItem.getPinned());
            updated.setPinnedPosition(orderedItem.getPinnedPosition());
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

        orderedPlanState.setItems(rebuildOrderedItems(synced));
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
