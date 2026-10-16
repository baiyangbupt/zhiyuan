package com.ytell.zhiyuan.service.biz;

import com.alibaba.fastjson.JSONObject;
import com.ytell.zhiyuan.common.constants.ChatSessionExtraDataConstants;
import com.ytell.zhiyuan.common.exception.BusinessException;
import com.ytell.zhiyuan.common.exception.ConversationAccessException;
import com.ytell.zhiyuan.manager.ProvinceVolunteerStrategyManager;
import com.ytell.zhiyuan.manager.rank.VolunteerRankClient;
import com.ytell.zhiyuan.model.dto.CreateSessionReq;
import com.ytell.zhiyuan.model.dto.RecommendSubMajorRequest;
import com.ytell.zhiyuan.model.dto.RecommendSubMajorResponse;
import com.ytell.zhiyuan.model.dto.UpdateScoreDetailRes;
import com.ytell.zhiyuan.model.dto.UserProfileData;
import com.ytell.zhiyuan.model.dto.gaotu.RecommendNumResponse;
import com.ytell.zhiyuan.model.dto.gaotu.req.RecommendNumReq;
import com.ytell.zhiyuan.model.dto.inner.ChatSessionExtraDataReq;
import com.ytell.zhiyuan.model.dto.inner.VolunteerSourceDataSnapshot;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateVersionDTO;
import com.ytell.zhiyuan.model.dto.planning.StaleFlagsDTO;
import com.ytell.zhiyuan.model.entity.biz.ChatSession;
import com.ytell.zhiyuan.model.entity.biz.ChatSessionExtraData;
import com.ytell.zhiyuan.model.enums.AuthTypeEnum;
import com.ytell.zhiyuan.model.enums.DataType;
import com.ytell.zhiyuan.model.enums.OperateCheckPoint;
import com.ytell.zhiyuan.model.vo.ChatSessionVo;
import com.ytell.zhiyuan.model.vo.CheckRightsResVo;
import com.ytell.zhiyuan.service.GaotuService;
import com.ytell.zhiyuan.service.shared.ChatSessionExtraDataSharedService;
import com.ytell.zhiyuan.service.shared.ChatSessionSharedService;
import com.ytell.zhiyuan.web.interceptor.UserBaseData;
import com.ytell.zhiyuan.web.interceptor.UserInfoThreadLocalUtil;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.mockito.InOrder;
import org.mockito.Mockito;
import org.springframework.core.task.TaskExecutor;
import org.springframework.test.util.ReflectionTestUtils;

import java.util.ArrayList;
import java.util.List;
import java.util.Queue;
import java.util.concurrent.ConcurrentLinkedQueue;
import java.util.concurrent.RejectedExecutionException;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.argThat;
import static org.mockito.ArgumentMatchers.eq;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.Mockito.inOrder;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

public class ChatSessionBizServiceTest {

    private ChatSessionBizService chatSessionBizService;
    private ChatSessionExtraDataSharedService chatSessionExtraDataSharedService;
    private PlanningStateService planningStateService;
    private VolunteerDataProvider volunteerDataProvider;
    private VolunteerRankClient volunteerRankClient;
    private ConversationAccessService conversationAccessService;
    private VolunteerSourceDataSyncService volunteerSourceDataSyncService;
    private GaotuService gaotuService;
    private ProvinceVolunteerStrategyManager volunteerStrategyManager;
    private UserBizService userBizService;

    @BeforeEach
    void setUp() {
        chatSessionBizService = new ChatSessionBizService();
        chatSessionExtraDataSharedService = Mockito.mock(ChatSessionExtraDataSharedService.class);
        planningStateService = Mockito.mock(PlanningStateService.class);
        volunteerDataProvider = Mockito.mock(VolunteerDataProvider.class);
        volunteerRankClient = Mockito.mock(VolunteerRankClient.class);
        conversationAccessService = Mockito.mock(ConversationAccessService.class);
        volunteerSourceDataSyncService = Mockito.mock(VolunteerSourceDataSyncService.class);
        gaotuService = Mockito.mock(GaotuService.class);
        volunteerStrategyManager = Mockito.mock(ProvinceVolunteerStrategyManager.class);
        userBizService = Mockito.mock(UserBizService.class);

        ReflectionTestUtils.setField(chatSessionBizService, "chatSessionExtraDataSharedService", chatSessionExtraDataSharedService);
        ReflectionTestUtils.setField(chatSessionBizService, "planningStateService", planningStateService);
        // 画像同步已移出请求路径（走专用池）：单测默认用"同线程执行"的替身，让既有断言保持确定性；
        // 要验证"请求不等同步"的用例自行换成受控 executor（见 shouldNotBlockProfileSaveOnPlanningProfileSync）。
        ReflectionTestUtils.setField(chatSessionBizService, "planningProfileSyncExecutor", (TaskExecutor) Runnable::run);
        ReflectionTestUtils.setField(chatSessionBizService, "volunteerDataProvider", volunteerDataProvider);
        ReflectionTestUtils.setField(chatSessionBizService, "volunteerRankClient", volunteerRankClient);
        ReflectionTestUtils.setField(chatSessionBizService, "conversationAccessService", conversationAccessService);
        ReflectionTestUtils.setField(chatSessionBizService, "volunteerSourceDataSyncService", volunteerSourceDataSyncService);
        ReflectionTestUtils.setField(chatSessionBizService, "gaotuService", gaotuService);
        ReflectionTestUtils.setField(chatSessionBizService, "volunteerStrategyManager", volunteerStrategyManager);
        ReflectionTestUtils.setField(chatSessionBizService, "userBizService", userBizService);
        // 补录缺省（科类/填报类型）从省策略推导——本类用例走不到推导后的分支，
        // 桩回 null（= 推导不出来），保持各用例原有的校验/兜底行为。
        ReflectionTestUtils.setField(chatSessionBizService, "scoreCatalogService",
                Mockito.mock(ScoreCatalogService.class));
    }

    @Test
    void shouldSyncPlanningStateWhenSavingUserProfile() {
        ChatSessionExtraDataReq req = new ChatSessionExtraDataReq();
        req.setChatSessionId(6L);
        req.setDataKey(ChatSessionExtraDataConstants.USER_PROFILE_KEY);
        req.setDataType(DataType.JSON_OBJECT);

        UserProfileData userProfileData = new UserProfileData();
        userProfileData.getNegative_city_info().setProvince(java.util.Arrays.asList("北京"));
        req.setDataValue(userProfileData);

        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKeyAndVersion(6L, ChatSessionExtraDataConstants.USER_PROFILE_KEY, 0))
                .thenReturn(null);
        when(volunteerDataProvider.getUserScoreDetail(6L)).thenReturn(new CreateSessionReq());

        chatSessionBizService.addOrUpdateSessionExtraData(1L, req);

        verify(chatSessionExtraDataSharedService).save(any(ChatSessionExtraData.class));
        verify(planningStateService).syncProfileStateFromLegacy(eq(6L), any(CreateSessionReq.class), any(UserProfileData.class), eq(true));
    }

    @Test
    void shouldNotSyncPlanningStateWhenSavingNonProfileExtraData() {
        ChatSessionExtraDataReq req = new ChatSessionExtraDataReq();
        req.setChatSessionId(6L);
        req.setDataKey("planEditCache");
        req.setDataType(DataType.JSON_OBJECT);
        req.setDataValue(java.util.Collections.singletonMap("foo", "bar"));

        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKeyAndVersion(6L, "planEditCache", 0))
                .thenReturn(null);

        chatSessionBizService.addOrUpdateSessionExtraData(1L, req);

        verify(chatSessionExtraDataSharedService).save(any(ChatSessionExtraData.class));
        verify(planningStateService, never()).syncProfileStateFromLegacy(any(Long.class), any(CreateSessionReq.class), any(UserProfileData.class), eq(true));
    }

    /**
     * 画像保存**不等**规划态同步（2026-10-16 review §五-52）：请求路径只做落库 + 投递，
     * 池里任务在请求返回后才被消费。这里用"只记录不执行"的 executor 替身钉住"不等"。
     */
    @Test
    void shouldNotBlockProfileSaveOnPlanningProfileSync() {
        Queue<Runnable> pendingSyncTasks = new ConcurrentLinkedQueue<>();
        ReflectionTestUtils.setField(chatSessionBizService, "planningProfileSyncExecutor",
                (TaskExecutor) pendingSyncTasks::add);

        ChatSessionExtraDataReq req = buildUserProfileReq();
        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKeyAndVersion(
                6L, ChatSessionExtraDataConstants.USER_PROFILE_KEY, 0)).thenReturn(null);
        when(volunteerDataProvider.getUserScoreDetail(6L)).thenReturn(new CreateSessionReq());

        chatSessionBizService.addOrUpdateSessionExtraData(1L, req);

        verify(chatSessionExtraDataSharedService).save(any(ChatSessionExtraData.class));
        assertEquals(1, pendingSyncTasks.size(), "画像落库后同步任务必须已投递到专用池");
        verify(planningStateService, never()).syncProfileStateFromLegacy(
                any(Long.class), any(CreateSessionReq.class), any(UserProfileData.class), eq(true));

        pendingSyncTasks.poll().run();
        verify(planningStateService).syncProfileStateFromLegacy(
                eq(6L), any(CreateSessionReq.class), any(UserProfileData.class), eq(true));
    }

    /** 同步任务抛异常只吞掉记 WARN：画像保存已经成功，绝不把请求翻成假失败（agent 10s 超时旧现场）。 */
    @Test
    void shouldSwallowProfileSyncFailureAndKeepSaveSuccessful() {
        when(planningStateService.syncProfileStateFromLegacy(any(Long.class), any(), any(), eq(true)))
                .thenThrow(new IllegalStateException("planningState 38MB 读/写超时"));
        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKeyAndVersion(
                6L, ChatSessionExtraDataConstants.USER_PROFILE_KEY, 0)).thenReturn(null);
        when(volunteerDataProvider.getUserScoreDetail(6L)).thenReturn(new CreateSessionReq());

        ChatSessionExtraData saved = chatSessionBizService.addOrUpdateSessionExtraData(1L, buildUserProfileReq());

        assertNotNull(saved, "画像保存必须成功返回，不受同步失败影响");
        verify(chatSessionExtraDataSharedService).save(any(ChatSessionExtraData.class));
        verify(planningStateService).syncProfileStateFromLegacy(
                eq(6L), any(CreateSessionReq.class), any(UserProfileData.class), eq(true));
    }

    /** 同步池拒绝（队列满）也只记 WARN：异常绝不抖回画像保存请求。 */
    @Test
    void shouldKeepProfileSaveSuccessfulWhenSyncPoolRejects() {
        ReflectionTestUtils.setField(chatSessionBizService, "planningProfileSyncExecutor",
                (TaskExecutor) task -> {
                    throw new RejectedExecutionException("profile sync queue full");
                });
        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKeyAndVersion(
                6L, ChatSessionExtraDataConstants.USER_PROFILE_KEY, 0)).thenReturn(null);

        ChatSessionExtraData saved = chatSessionBizService.addOrUpdateSessionExtraData(1L, buildUserProfileReq());

        assertNotNull(saved);
        verify(chatSessionExtraDataSharedService).save(any(ChatSessionExtraData.class));
        verify(planningStateService, never()).syncProfileStateFromLegacy(
                any(Long.class), any(CreateSessionReq.class), any(UserProfileData.class), eq(true));
    }

    private ChatSessionExtraDataReq buildUserProfileReq() {
        ChatSessionExtraDataReq req = new ChatSessionExtraDataReq();
        req.setChatSessionId(6L);
        req.setDataKey(ChatSessionExtraDataConstants.USER_PROFILE_KEY);
        req.setDataType(DataType.JSON_OBJECT);
        UserProfileData userProfileData = new UserProfileData();
        userProfileData.getNegative_city_info().setProvince(java.util.Arrays.asList("北京"));
        req.setDataValue(userProfileData);
        return req;
    }

    @Test
    void shouldDefaultPrepareTypeToVolunteerWhenMissing() {
        CreateSessionReq req = new CreateSessionReq();

        chatSessionBizService.normalizeCreateSessionDefaults(req);

        assertNotNull(req.getPrepareType());
        assertEquals("VOLUNTEER", req.getPrepareType().getCode());
        assertEquals("智能填报", req.getPrepareType().getDesc());
    }

    @Test
    void shouldCreateEmptySessionWithoutCollectedInfoWhenDraft() {
        // 空会话：省份/批次/选科/成绩一个都不给，也必须建得出来——
        // 那几项本来就是对话要采集的信息，不是建会话的前提。
        UserBaseData userBaseData = new UserBaseData();
        userBaseData.setUserId(7L);
        userBaseData.setAuthType(AuthTypeEnum.WEB);
        UserInfoThreadLocalUtil.set(userBaseData);

        ChatSessionSharedService chatSessionSharedService = Mockito.mock(ChatSessionSharedService.class);
        UserBizService userBizService = Mockito.mock(UserBizService.class);
        ReflectionTestUtils.setField(chatSessionBizService, "chatSessionSharedService", chatSessionSharedService);
        ReflectionTestUtils.setField(chatSessionBizService, "userBizService", userBizService);

        CheckRightsResVo rights = new CheckRightsResVo();
        rights.setCanOperate(true);
        when(userBizService.checkRights(eq(7L), eq(OperateCheckPoint.CreateSession), any()))
                .thenReturn(rights);
        when(chatSessionSharedService.saveSession(any(ChatSession.class))).thenAnswer(invocation -> {
            ChatSession session = invocation.getArgument(0);
            session.setId(900L);
            return session;
        });

        CreateSessionReq req = new CreateSessionReq();
        req.setBotId(1L);
        req.setDraft(Boolean.TRUE);

        ChatSessionVo vo = chatSessionBizService.createChatSession(1L, req);

        assertEquals(900L, vo.getId());
        // 空会话连欢迎语都不发：会话一旦带上占位信息，模型就不会再问缺什么。
        verify(chatSessionExtraDataSharedService, never())
                .save(any(ChatSessionExtraData.class));
        verify(chatSessionSharedService, never()).pageSession(any(), any());
        UserInfoThreadLocalUtil.remove();
    }

    @Test
    void shouldStillCheckRightsForEmptySession() {
        // 空会话也是会话：判据不该因为信息空着而放宽。
        UserBaseData userBaseData = new UserBaseData();
        userBaseData.setUserId(7L);
        userBaseData.setAuthType(AuthTypeEnum.WEB);
        UserInfoThreadLocalUtil.set(userBaseData);

        ChatSessionSharedService chatSessionSharedService = Mockito.mock(ChatSessionSharedService.class);
        UserBizService userBizService = Mockito.mock(UserBizService.class);
        ReflectionTestUtils.setField(chatSessionBizService, "chatSessionSharedService", chatSessionSharedService);
        ReflectionTestUtils.setField(chatSessionBizService, "userBizService", userBizService);

        CheckRightsResVo rights = new CheckRightsResVo();
        rights.setCanOperate(false);
        rights.setReason("智能填报需要权益");
        when(userBizService.checkRights(eq(7L), eq(OperateCheckPoint.CreateSession), any()))
                .thenReturn(rights);

        CreateSessionReq req = new CreateSessionReq();
        req.setBotId(1L);
        req.setDraft(Boolean.TRUE);

        BusinessException exception = assertThrows(BusinessException.class,
                () -> chatSessionBizService.createChatSession(1L, req));

        assertEquals("智能填报需要权益", exception.getMessage());
        verify(chatSessionSharedService, never()).saveSession(any(ChatSession.class));
        UserInfoThreadLocalUtil.remove();
    }

    @Test
    void shouldRejectCreateSessionWhenBatchMissing() {
        CreateSessionReq req = new CreateSessionReq();
        CreateSessionReq.PrepareType prepareType = new CreateSessionReq.PrepareType();
        prepareType.setCode("VOLUNTEER");
        req.setPrepareType(prepareType);

        BusinessException exception = assertThrows(BusinessException.class,
                () -> chatSessionBizService.createChatSession(1L, req));

        assertEquals("请选择批次后再创建会话", exception.getMessage());
    }

    @Test
    void shouldFillDefaultSexStrategyTypeAndPrepareTypeWhenMissing() {
        CreateSessionReq req = new CreateSessionReq();

        chatSessionBizService.normalizeCreateSessionDefaults(req);

        assertNotNull(req.getSex());
        assertEquals("female", req.getSex().getCode());
        assertEquals("女", req.getSex().getName());
        assertNotNull(req.getPrepareType());
        assertEquals("VOLUNTEER", req.getPrepareType().getCode());
        assertEquals("智能填报", req.getPrepareType().getDesc());
        assertNotNull(req.getStrategyType());
        assertEquals("cautious", req.getStrategyType().getCode());
        assertEquals("稳妥型", req.getStrategyType().getName());
    }

    @Test
    void shouldReturnEmptyMajorRecommendWhenRankUnavailable() {
        when(volunteerRankClient.getRecommendSubMajor(any(RecommendSubMajorRequest.class)))
                .thenThrow(new RuntimeException("rank unavailable"));

        List<RecommendSubMajorResponse.MajorRecommendItem> result = chatSessionBizService.recommendMajor(new CreateSessionReq());

        assertNotNull(result);
        assertEquals(0, result.size());
    }

    @Test
    void shouldLimitMajorRecommendToEightItems() {
        RecommendSubMajorResponse response = new RecommendSubMajorResponse();
        List<RecommendSubMajorResponse.MajorRecommendItem> items = new ArrayList<>();
        for (int i = 0; i < 10; i++) {
            RecommendSubMajorResponse.MajorRecommendItem item = new RecommendSubMajorResponse.MajorRecommendItem();
            item.setMajorId(String.valueOf(i));
            item.setMajor("专业" + i);
            items.add(item);
        }
        response.setReconmandlist(items);
        when(volunteerRankClient.getRecommendSubMajor(any(RecommendSubMajorRequest.class))).thenReturn(response);

        List<RecommendSubMajorResponse.MajorRecommendItem> result = chatSessionBizService.recommendMajor(new CreateSessionReq());

        assertEquals(8, result.size());
        assertEquals("专业0", result.get(0).getMajor());
        assertEquals("专业7", result.get(7).getMajor());
    }

    // ---------- 空会话（draft）同会话补录成绩 ----------

    private static final long TENANT_ID = 1L;
    private static final long SESSION_ID = 900L;
    private static final long USER_ID = 7L;

    private void login(Long userId) {
        UserBaseData userBaseData = new UserBaseData();
        userBaseData.setUserId(userId);
        userBaseData.setAuthType(AuthTypeEnum.WEB);
        UserInfoThreadLocalUtil.set(userBaseData);
    }

    private CreateSessionReq scoreUpdateReq() {
        CreateSessionReq req = new CreateSessionReq();
        CreateSessionReq.Province province = new CreateSessionReq.Province();
        province.setCode("330000");
        province.setName("浙江");
        req.setProvince(province);
        req.setExamYear(2026);

        CreateSessionReq.Batch batch = new CreateSessionReq.Batch();
        batch.setCode("1");
        batch.setName("本科");
        batch.setLevel("本科");
        batch.setScore(600F);
        req.setBatch(batch);

        CreateSessionReq.SubjectType subjectType = new CreateSessionReq.SubjectType();
        subjectType.setCode("WL");
        subjectType.setDesc("物理");
        req.setSubjectType(subjectType);

        List<CreateSessionReq.SubjectScore> subjectScores = new ArrayList<>();
        CreateSessionReq.SubjectScore physics = new CreateSessionReq.SubjectScore();
        physics.setSubject("01");
        physics.setSubjectName("物理");
        physics.setScore(92);
        subjectScores.add(physics);
        req.setSubjectScoreList(subjectScores);

        req.setTotalScore(650);
        req.setTotalScorePos(12000);
        return req;
    }

    /** 补录成功路径的公共桩：归属通过 + 权益通过 + 志愿数量/模式 + 志愿数据拉取 + 规划状态。 */
    private void stubSuccessfulScoreUpdateDependencies() {
        when(conversationAccessService.requireOwnedSession(TENANT_ID, SESSION_ID, USER_ID))
                .thenReturn(new ChatSession());

        CheckRightsResVo rights = new CheckRightsResVo();
        rights.setCanOperate(true);
        when(userBizService.checkRights(eq(USER_ID), eq(OperateCheckPoint.CreateSession), any())).thenReturn(rights);

        RecommendNumResponse numResponse = new RecommendNumResponse();
        numResponse.setMajorNum(300);
        numResponse.setSchoolNum(120);
        when(gaotuService.getRecommendProgramNum(any(RecommendNumReq.class))).thenReturn(numResponse);
        when(volunteerStrategyManager.getVolunteerStrategyByProvinceCode("330000", "本科")).thenReturn("OTOO");

        VolunteerSourceDataSnapshot snapshot = new VolunteerSourceDataSnapshot();
        snapshot.setFetchedAt("2026-10-06T10:00:00+08:00");
        when(volunteerSourceDataSyncService.fetchLatestSourceData(TENANT_ID, SESSION_ID, true)).thenReturn(snapshot);

        PlanningStateVersionDTO versionDTO = new PlanningStateVersionDTO();
        versionDTO.setVersion(5);
        versionDTO.setStaleFlags(new StaleFlagsDTO());
        when(planningStateService.applyScoreDetailUpdate(eq(SESSION_ID), any(CreateSessionReq.class), any(), eq(false)))
                .thenReturn(versionDTO);
    }

    @Test
    void shouldFillScoreDetailIntoEmptySessionAndReportVersionAndReload() {
        login(USER_ID);
        stubSuccessfulScoreUpdateDependencies();
        // 空会话：userScoreDetail 行不存在 → insert。
        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(SESSION_ID, ChatSessionExtraDataConstants.USER_SCORE_KEY))
                .thenReturn(null);

        UpdateScoreDetailRes res = chatSessionBizService.updateScoreDetail(TENANT_ID, SESSION_ID, scoreUpdateReq());

        assertEquals(Boolean.TRUE, res.getSuccess());
        assertEquals(SESSION_ID, res.getChatSessionId());
        assertEquals(5, res.getPlanningVersion());
        assertEquals(Boolean.TRUE, res.getRequiresWorkspaceReload());
        assertEquals(Boolean.TRUE, res.getVolunteerSourceDataSynced());
        assertEquals("2026-10-06T10:00:00+08:00", res.getVolunteerSourceDataFetchedAt());

        ArgumentCaptor<ChatSessionExtraData> captor = ArgumentCaptor.forClass(ChatSessionExtraData.class);
        verify(chatSessionExtraDataSharedService).save(captor.capture());
        ChatSessionExtraData saved = captor.getValue();
        assertEquals(ChatSessionExtraDataConstants.USER_SCORE_KEY, saved.getDataKey());
        JSONObject dataValue = JSONObject.parseObject(saved.getDataValue());
        assertEquals(650, dataValue.getIntValue("totalScore"));
        assertEquals(12000, dataValue.getIntValue("totalScorePos"));
        assertEquals("330000", dataValue.getJSONObject("province").getString("code"));
        // 空会话建会话时故意没做的两件事：填报数量/模式与志愿数据文件，补录时补齐。
        assertEquals(300, dataValue.getJSONObject("volunteerCount").getIntValue("majorCount"));
        assertEquals("OTOO", dataValue.getString("volunteerDetailModel"));
        assertEquals("major", dataValue.getString("volunteerModel"));

        // 顺序：成绩先落库，志愿数据拉取在后（该服务自己也读 userScoreDetail，缺行会 404）。
        InOrder inOrder = inOrder(chatSessionExtraDataSharedService, volunteerSourceDataSyncService, planningStateService);
        inOrder.verify(chatSessionExtraDataSharedService).save(any(ChatSessionExtraData.class));
        inOrder.verify(volunteerSourceDataSyncService).fetchLatestSourceData(TENANT_ID, SESSION_ID, true);
        inOrder.verify(planningStateService).applyScoreDetailUpdate(eq(SESSION_ID), any(CreateSessionReq.class), any(), eq(false));
        UserInfoThreadLocalUtil.remove();
    }

    @Test
    void shouldMergeScoreUpdateIntoExistingDetailWithoutLosingPrepareTypeOrIntent() {
        login(USER_ID);
        stubSuccessfulScoreUpdateDependencies();

        CreateSessionReq existing = new CreateSessionReq();
        CreateSessionReq.PrepareType prepareType = new CreateSessionReq.PrepareType();
        prepareType.setCode("PREDICT");
        prepareType.setDesc("模拟填报");
        existing.setPrepareType(prepareType);
        List<CreateSessionReq.PreferredMajor> preferredMajors = new ArrayList<>();
        CreateSessionReq.PreferredMajor major = new CreateSessionReq.PreferredMajor();
        major.setMajorSubId("0809");
        major.setMajorSubName("计算机类");
        preferredMajors.add(major);
        existing.setPreferredMajors(preferredMajors);
        CreateSessionReq.TuitionRange tuitionRange = new CreateSessionReq.TuitionRange();
        tuitionRange.setMin(5000);
        tuitionRange.setMax(8000);
        existing.setTuitionRange(tuitionRange);

        ChatSessionExtraData existingRow = new ChatSessionExtraData();
        existingRow.setId(66L);
        existingRow.setChatSessionId(SESSION_ID);
        existingRow.setDataKey(ChatSessionExtraDataConstants.USER_SCORE_KEY);
        existingRow.setDataValue(JSONObject.toJSONString(existing));
        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(SESSION_ID, ChatSessionExtraDataConstants.USER_SCORE_KEY))
                .thenReturn(existingRow);

        // 已存在的画像行：userprofile 有值，userInitProfile 没有。
        UserProfileData existingProfile = new UserProfileData();
        existingProfile.getMajor_intent().setLevel2(java.util.Arrays.asList("既有意向"));
        when(volunteerDataProvider.getUserProfileData(SESSION_ID)).thenReturn(existingProfile);

        UpdateScoreDetailRes res = chatSessionBizService.updateScoreDetail(TENANT_ID, SESSION_ID, scoreUpdateReq());

        assertEquals(Boolean.TRUE, res.getSuccess());
        // 补录只带成绩字段：既有 prepareType/意向/学费区间一个都不能丢，totalScore 换成新值。
        assertEquals("PREDICT", existingRow.getDataValue() == null ? null
                : JSONObject.parseObject(existingRow.getDataValue()).getJSONObject("prepareType").getString("code"));
        ArgumentCaptor<ChatSessionExtraData> captor = ArgumentCaptor.forClass(ChatSessionExtraData.class);
        verify(chatSessionExtraDataSharedService).updateById(captor.capture());
        JSONObject merged = JSONObject.parseObject(captor.getValue().getDataValue());
        assertEquals("PREDICT", merged.getJSONObject("prepareType").getString("code"));
        assertEquals("计算机类", merged.getJSONArray("preferredMajors").getJSONObject(0).getString("majorSubName"));
        assertEquals(5000, merged.getJSONObject("tuitionRange").getIntValue("min"));
        assertEquals(650, merged.getIntValue("totalScore"));
        assertEquals(SESSION_ID, captor.getValue().getChatSessionId());
        // 成绩行是 update 而不是 insert（save 只用于画像行）。
        verify(chatSessionExtraDataSharedService, never()).save(
                argThat(row -> ChatSessionExtraDataConstants.USER_SCORE_KEY.equals(row.getDataKey())));

        // 合并进来的意向/优势学科触发画像同步（既有非空值保留），规划状态按"偏好也变了"失效。
        verify(planningStateService).applyScoreDetailUpdate(eq(SESSION_ID), any(CreateSessionReq.class), any(UserProfileData.class), eq(true));
        ArgumentCaptor<ChatSessionExtraData> profileCaptor = ArgumentCaptor.forClass(ChatSessionExtraData.class);
        verify(chatSessionExtraDataSharedService, times(2)).save(profileCaptor.capture());
        boolean profileWritten = profileCaptor.getAllValues().stream()
                .anyMatch(row -> ChatSessionExtraDataConstants.USER_PROFILE_KEY.equals(row.getDataKey()));
        assertTrue(profileWritten, "应同步 userprofile");
        UserInfoThreadLocalUtil.remove();
    }

    @Test
    void shouldRejectScoreUpdateWhenRequiredFieldsMissing() {
        login(USER_ID);
        CreateSessionReq req = scoreUpdateReq();
        req.setBatch(null);

        BusinessException exception = assertThrows(BusinessException.class,
                () -> chatSessionBizService.updateScoreDetail(TENANT_ID, SESSION_ID, req));

        assertEquals("请选择批次后再创建会话", exception.getMessage());
        // 校验不过：不落库、不拉数据、不动规划状态。
        verify(chatSessionExtraDataSharedService, never()).save(any(ChatSessionExtraData.class));
        verify(chatSessionExtraDataSharedService, never()).updateById(any(ChatSessionExtraData.class));
        verify(volunteerSourceDataSyncService, never()).fetchLatestSourceData(anyLong(), anyLong(), eq(true));
        verify(planningStateService, never()).applyScoreDetailUpdate(anyLong(), any(), any(), eq(false));
        UserInfoThreadLocalUtil.remove();
    }

    @Test
    void shouldRejectScoreUpdateWhenSessionNotOwned() {
        login(USER_ID);
        when(conversationAccessService.requireOwnedSession(TENANT_ID, SESSION_ID, USER_ID))
                .thenThrow(new ConversationAccessException(403, "session_forbidden"));

        ConversationAccessException exception = assertThrows(ConversationAccessException.class,
                () -> chatSessionBizService.updateScoreDetail(TENANT_ID, SESSION_ID, scoreUpdateReq()));

        assertEquals(403, exception.getStatus());
        verify(chatSessionExtraDataSharedService, never()).save(any(ChatSessionExtraData.class));
        verify(chatSessionExtraDataSharedService, never()).updateById(any(ChatSessionExtraData.class));
        verify(volunteerSourceDataSyncService, never()).fetchLatestSourceData(anyLong(), anyLong(), eq(true));
        UserInfoThreadLocalUtil.remove();
    }
}
