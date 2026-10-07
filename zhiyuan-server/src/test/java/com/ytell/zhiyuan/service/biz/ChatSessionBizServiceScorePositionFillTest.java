package com.ytell.zhiyuan.service.biz;

import ch.qos.logback.classic.Logger;
import ch.qos.logback.classic.spi.ILoggingEvent;
import ch.qos.logback.core.read.ListAppender;
import com.alibaba.fastjson.JSONObject;
import com.google.common.collect.Lists;
import com.ytell.zhiyuan.common.constants.ChatSessionExtraDataConstants;
import com.ytell.zhiyuan.manager.ProvinceVolunteerStrategyManager;
import com.ytell.zhiyuan.model.dto.CreateSessionReq;
import com.ytell.zhiyuan.model.dto.UpdateScoreDetailRes;
import com.ytell.zhiyuan.model.dto.gaotu.RecommendNumResponse;
import com.ytell.zhiyuan.model.dto.gaotu.req.RecommendNumReq;
import com.ytell.zhiyuan.model.dto.gaotu.req.ScorePositionRangeReq;
import com.ytell.zhiyuan.model.dto.gaotu.res.ScorePositionRangeRes;
import com.ytell.zhiyuan.model.dto.inner.VolunteerSourceDataSnapshot;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateVersionDTO;
import com.ytell.zhiyuan.model.dto.planning.StaleFlagsDTO;
import com.ytell.zhiyuan.model.entity.biz.ChatSession;
import com.ytell.zhiyuan.model.entity.biz.ChatSessionExtraData;
import com.ytell.zhiyuan.model.enums.AuthTypeEnum;
import com.ytell.zhiyuan.model.enums.OperateCheckPoint;
import com.ytell.zhiyuan.model.vo.CheckRightsResVo;
import com.ytell.zhiyuan.service.GaotuService;
import com.ytell.zhiyuan.service.shared.ChatSessionExtraDataSharedService;
import com.ytell.zhiyuan.service.shared.ChatSessionSharedService;
import com.ytell.zhiyuan.common.util.VolunteerFilePathUtil;
import com.ytell.zhiyuan.web.interceptor.UserBaseData;
import com.ytell.zhiyuan.web.interceptor.UserInfoThreadLocalUtil;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.mockito.Mockito;
import org.slf4j.LoggerFactory;
import org.springframework.test.util.ReflectionTestUtils;

import java.io.File;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 建档/补录的**位次缺失保守补齐**（qa 口径：取一分一段的 lowestRank）。
 *
 * <p>补录表单前端自己会调一分一段（`ScoreSupplement` 取 `data.lowestRank` 填 `totalScorePos`），
 * 但对话补录/接口建档这两条路没有这个前端小抄——位次就一直空着。这里按与前端**同源的口径**
 * 在后端补上：`totalScorePos` 为空且分数/年份/省份/科类/批次 level 齐备时向上游要区间，
 * 取**最保守位次 = lowestRank**（同分不可分辨，取区间里最大名次）。</p>
 *
 * <p>四条护栏：①补的是 lowestRank 且请求形状与前端一致；②用户/表单已给的位次不覆盖、不查上游；
 * ③上游没有该省数据（data:null）保持为空、不造数、不抛；④前置缺（如 batch.level）不查上游。
 * 另各补一条：createChatSession 建档入口同样生效；上游异常也不阻塞成绩落库。</p>
 */
public class ChatSessionBizServiceScorePositionFillTest {

    private static final Long TENANT_ID = 1L;
    private static final Long SESSION_ID = 900L;
    private static final Long USER_ID = 7L;

    private ChatSessionBizService service;
    private ChatSessionExtraDataSharedService chatSessionExtraDataSharedService;
    private GaotuService gaotuService;
    private VolunteerSourceDataSyncService volunteerSourceDataSyncService;
    private PlanningStateService planningStateService;
    private ChatSessionSharedService chatSessionSharedService;
    private UserBizService userBizService;

    @BeforeEach
    void setUp() {
        service = new ChatSessionBizService();
        chatSessionExtraDataSharedService = mock(ChatSessionExtraDataSharedService.class);
        planningStateService = mock(PlanningStateService.class);
        volunteerSourceDataSyncService = mock(VolunteerSourceDataSyncService.class);
        gaotuService = mock(GaotuService.class);
        chatSessionSharedService = mock(ChatSessionSharedService.class);
        userBizService = mock(UserBizService.class);

        ReflectionTestUtils.setField(service, "chatSessionExtraDataSharedService", chatSessionExtraDataSharedService);
        ReflectionTestUtils.setField(service, "planningStateService", planningStateService);
        ReflectionTestUtils.setField(service, "volunteerSourceDataSyncService", volunteerSourceDataSyncService);
        ReflectionTestUtils.setField(service, "gaotuService", gaotuService);
        ReflectionTestUtils.setField(service, "chatSessionSharedService", chatSessionSharedService);
        ReflectionTestUtils.setField(service, "userBizService", userBizService);
        ReflectionTestUtils.setField(service, "scoreCatalogService", mock(ScoreCatalogService.class));
        ReflectionTestUtils.setField(service, "volunteerStrategyManager", mock(ProvinceVolunteerStrategyManager.class));

        ConversationAccessService conversationAccessService = mock(ConversationAccessService.class);
        when(conversationAccessService.requireSessionUserId(TENANT_ID, SESSION_ID)).thenReturn(USER_ID);
        ReflectionTestUtils.setField(service, "conversationAccessService", conversationAccessService);

        CheckRightsResVo rights = new CheckRightsResVo();
        rights.setCanOperate(true);
        when(userBizService.checkRights(eq(USER_ID), eq(OperateCheckPoint.CreateSession), any())).thenReturn(rights);
    }

    @AfterEach
    void tearDown() {
        UserInfoThreadLocalUtil.remove();
    }

    // ① 缺位次 + 前置齐 → 补 lowestRank，且请求形状与前端一致、info 日志记全推导要素。
    @Test
    void missingPositionIsFilledWithLowestRankOnScoreUpdate() {
        stubScoreUpdateDependencies();
        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(SESSION_ID, ChatSessionExtraDataConstants.USER_SCORE_KEY))
                .thenReturn(null);
        when(gaotuService.getScorePositionRange(any(ScorePositionRangeReq.class)))
                .thenReturn(positionRange(43000, 43879));

        ListAppender<ILoggingEvent> appender = attachAppender();
        UpdateScoreDetailRes res;
        try {
            res = service.updateScoreDetailForUser(TENANT_ID, SESSION_ID, scoreUpdateRequest(), USER_ID);
        } finally {
            detachAppender(appender);
        }

        assertEquals(Boolean.TRUE, res.getSuccess());

        // 上游拿到的请求形状与前端补录表单一致：areaId/subject(=科类)/dataLevel(=批次 level)/year/score。
        ArgumentCaptor<ScorePositionRangeReq> rangeCaptor = ArgumentCaptor.forClass(ScorePositionRangeReq.class);
        verify(gaotuService).getScorePositionRange(rangeCaptor.capture());
        ScorePositionRangeReq sent = rangeCaptor.getValue();
        assertEquals("330000", sent.getAreaId());
        assertEquals("N", sent.getSubject());
        assertEquals("01", sent.getDataLevel());
        assertEquals("2026", sent.getYear());
        assertEquals("610", sent.getScore());

        // 落库的是保守口径 lowestRank，不是 highestRank。
        JSONObject saved = capturedScoreRow();
        assertEquals(43879, saved.getIntValue("totalScorePos"));

        // 推导有一条 info 日志：原分数/区间/同分人数/采用值。
        assertTrue(appender.list.stream()
                        .anyMatch(event -> event.getFormattedMessage().contains("采用lowestRank=43879")
                                && event.getFormattedMessage().contains("610")
                                && event.getFormattedMessage().contains("43000~43879")
                                && event.getFormattedMessage().contains("880")),
                "推导日志要能还原口径：分数/区间/同分人数/采用值");
    }

    // ② 已有位次（用户/表单给的）→ 不覆盖、不查上游。
    @Test
    void existingPositionIsNeverOverwrittenAndSkipsUpstream() {
        stubScoreUpdateDependencies();
        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(SESSION_ID, ChatSessionExtraDataConstants.USER_SCORE_KEY))
                .thenReturn(null);
        CreateSessionReq req = scoreUpdateRequest();
        req.setTotalScorePos(12000);

        service.updateScoreDetailForUser(TENANT_ID, SESSION_ID, req, USER_ID);

        assertEquals(12000, capturedScoreRow().getIntValue("totalScorePos"), "用户 > 表：原值保留");
        verify(gaotuService, never()).getScorePositionRange(any(ScorePositionRangeReq.class));
    }

    // ③ 上游 data:null（该省没有一分一段）→ 保持为空、不造数、不抛。
    @Test
    void upstreamWithoutDataKeepsPositionEmptyAndDoesNotFail() {
        stubScoreUpdateDependencies();
        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(SESSION_ID, ChatSessionExtraDataConstants.USER_SCORE_KEY))
                .thenReturn(null);
        when(gaotuService.getScorePositionRange(any(ScorePositionRangeReq.class))).thenReturn(null);

        UpdateScoreDetailRes res = service.updateScoreDetailForUser(TENANT_ID, SESSION_ID, scoreUpdateRequest(), USER_ID);

        assertEquals(Boolean.TRUE, res.getSuccess(), "查不到位次不许阻塞成绩落库");
        assertNull(capturedScoreRow().getInteger("totalScorePos"), "data:null 保持为空，不造数");
    }

    // ④ 缺 batch.level → 前置不齐，不查上游。
    @Test
    void missingBatchLevelSkipsUpstreamLookup() {
        stubScoreUpdateDependencies();
        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(SESSION_ID, ChatSessionExtraDataConstants.USER_SCORE_KEY))
                .thenReturn(null);
        CreateSessionReq req = scoreUpdateRequest();
        req.getBatch().setLevel(null);

        service.updateScoreDetailForUser(TENANT_ID, SESSION_ID, req, USER_ID);

        verify(gaotuService, never()).getScorePositionRange(any(ScorePositionRangeReq.class));
        assertNull(capturedScoreRow().getInteger("totalScorePos"));
    }

    // 上游异常（超时/HTTP 错）同样只保持为空：位次是补充信息，不许带崩主链路。
    @Test
    void upstreamExceptionKeepsPositionEmptyAndDoesNotFail() {
        stubScoreUpdateDependencies();
        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(SESSION_ID, ChatSessionExtraDataConstants.USER_SCORE_KEY))
                .thenReturn(null);
        when(gaotuService.getScorePositionRange(any(ScorePositionRangeReq.class)))
                .thenThrow(new RuntimeException("upstream timeout"));

        UpdateScoreDetailRes res = service.updateScoreDetailForUser(TENANT_ID, SESSION_ID, scoreUpdateRequest(), USER_ID);

        assertEquals(Boolean.TRUE, res.getSuccess());
        assertNull(capturedScoreRow().getInteger("totalScorePos"));
    }

    // 建档入口（createChatSession）同样生效：同一条辅助，两处接线。
    @Test
    void createChatSessionAlsoFillsMissingPosition() throws Exception {
        login(USER_ID);
        when(userBizService.checkRights(anyLong(), any(), any())).thenReturn(canOperate(true));
        when(chatSessionSharedService.saveSession(any(ChatSession.class))).thenAnswer(invocation -> {
            ChatSession session = invocation.getArgument(0);
            session.setId(SESSION_ID);
            return session;
        });
        RecommendNumResponse numResponse = new RecommendNumResponse();
        numResponse.setMajorNum(300);
        numResponse.setSchoolNum(120);
        when(gaotuService.getRecommendProgramNum(any(RecommendNumReq.class))).thenReturn(numResponse);
        when(gaotuService.queryAllProgramData(any())).thenReturn(new JSONObject());
        when(gaotuService.getScorePositionRange(any(ScorePositionRangeReq.class)))
                .thenReturn(positionRange(43000, 43879));
        ProvinceVolunteerStrategyManager strategyManager = mock(ProvinceVolunteerStrategyManager.class);
        when(strategyManager.getVolunteerStrategyByProvinceCode("330000", "01")).thenReturn("OTOO");
        ReflectionTestUtils.setField(service, "volunteerStrategyManager", strategyManager);
        VolunteerFilePathUtil filePathUtil = mock(VolunteerFilePathUtil.class);
        File localFile = File.createTempFile("volunteer-score-pos", ".json");
        localFile.deleteOnExit();
        when(filePathUtil.getLocalFilePath(anyLong(), any())).thenReturn(localFile.getAbsolutePath());
        when(filePathUtil.getOssFilePath(anyLong(), any())).thenReturn("oss/900.json");
        ReflectionTestUtils.setField(service, "volunteerFilePathUtil", filePathUtil);
        ReflectionTestUtils.setField(service, "volunteerFileAsyncService", mock(VolunteerFileAsyncService.class));
        ReflectionTestUtils.setField(service, "chatMessageBizService", mock(ChatMessageBizService.class));

        service.createChatSession(TENANT_ID, createSessionRequest());

        ArgumentCaptor<ScorePositionRangeReq> rangeCaptor = ArgumentCaptor.forClass(ScorePositionRangeReq.class);
        verify(gaotuService).getScorePositionRange(rangeCaptor.capture());
        assertEquals("330000", rangeCaptor.getValue().getAreaId());
        assertEquals("N", rangeCaptor.getValue().getSubject());
        assertEquals("01", rangeCaptor.getValue().getDataLevel());

        ArgumentCaptor<ChatSessionExtraData> captor = ArgumentCaptor.forClass(ChatSessionExtraData.class);
        verify(chatSessionExtraDataSharedService, Mockito.atLeastOnce()).save(captor.capture());
        ChatSessionExtraData scoreRow = captor.getAllValues().stream()
                .filter(row -> ChatSessionExtraDataConstants.USER_SCORE_KEY.equals(row.getDataKey()))
                .findFirst()
                .orElseThrow(() -> new AssertionError("建档必须落 userScoreDetail"));
        assertEquals(43879, JSONObject.parseObject(scoreRow.getDataValue()).getIntValue("totalScorePos"));
    }

    // ── 夹具 ──────────────────────────────────────────────────────────────

    private void stubScoreUpdateDependencies() {
        ConversationAccessService conversationAccessService =
                (ConversationAccessService) ReflectionTestUtils.getField(service, "conversationAccessService");
        when(conversationAccessService.requireOwnedSession(TENANT_ID, SESSION_ID, USER_ID)).thenReturn(new ChatSession());

        RecommendNumResponse numResponse = new RecommendNumResponse();
        numResponse.setMajorNum(300);
        numResponse.setSchoolNum(120);
        when(gaotuService.getRecommendProgramNum(any(RecommendNumReq.class))).thenReturn(numResponse);

        ProvinceVolunteerStrategyManager strategyManager =
                (ProvinceVolunteerStrategyManager) ReflectionTestUtils.getField(service, "volunteerStrategyManager");
        when(strategyManager.getVolunteerStrategyByProvinceCode("330000", "01")).thenReturn("OTOO");

        VolunteerSourceDataSnapshot snapshot = new VolunteerSourceDataSnapshot();
        snapshot.setFetchedAt("2026-10-07T10:00:00+08:00");
        when(volunteerSourceDataSyncService.fetchLatestSourceData(TENANT_ID, SESSION_ID, true)).thenReturn(snapshot);

        PlanningStateVersionDTO versionDTO = new PlanningStateVersionDTO();
        versionDTO.setVersion(5);
        versionDTO.setStaleFlags(new StaleFlagsDTO());
        when(planningStateService.applyScoreDetailUpdate(eq(SESSION_ID), any(CreateSessionReq.class), any(), eq(false)))
                .thenReturn(versionDTO);
    }

    private JSONObject capturedScoreRow() {
        ArgumentCaptor<ChatSessionExtraData> captor = ArgumentCaptor.forClass(ChatSessionExtraData.class);
        verify(chatSessionExtraDataSharedService, Mockito.atLeastOnce()).save(captor.capture());
        ChatSessionExtraData scoreRow = captor.getAllValues().stream()
                .filter(row -> ChatSessionExtraDataConstants.USER_SCORE_KEY.equals(row.getDataKey()))
                .findFirst()
                .orElseThrow(() -> new AssertionError("补录必须落 userScoreDetail"));
        return JSONObject.parseObject(scoreRow.getDataValue());
    }

    private ScorePositionRangeRes positionRange(int highestRank, int lowestRank) {
        ScorePositionRangeRes res = new ScorePositionRangeRes();
        res.setScore("610");
        res.setStudents(lowestRank - highestRank + 1);
        res.setHighestRank(highestRank);
        res.setLowestRank(lowestRank);
        res.setDataLevel("01");
        return res;
    }

    private CheckRightsResVo canOperate(boolean canOperate) {
        CheckRightsResVo rights = new CheckRightsResVo();
        rights.setCanOperate(canOperate);
        return rights;
    }

    private void login(Long userId) {
        UserBaseData userBaseData = new UserBaseData();
        userBaseData.setUserId(userId);
        userBaseData.setAuthType(AuthTypeEnum.WEB);
        UserInfoThreadLocalUtil.set(userBaseData);
    }

    private ListAppender<ILoggingEvent> attachAppender() {
        Logger logger = (Logger) LoggerFactory.getLogger(ChatSessionBizService.class);
        ListAppender<ILoggingEvent> appender = new ListAppender<>();
        appender.start();
        logger.addAppender(appender);
        return appender;
    }

    private void detachAppender(ListAppender<ILoggingEvent> appender) {
        Logger logger = (Logger) LoggerFactory.getLogger(ChatSessionBizService.class);
        logger.detachAppender(appender);
    }

    /** 补录草稿：位次**空着**，其余（省份/科类/批次 level/年份/分数）齐备——对话补录的实测形状。 */
    private CreateSessionReq scoreUpdateRequest() {
        CreateSessionReq req = new CreateSessionReq();
        CreateSessionReq.Province province = new CreateSessionReq.Province();
        province.setCode("330000");
        province.setName("浙江省");
        req.setProvince(province);
        CreateSessionReq.SubjectType subjectType = new CreateSessionReq.SubjectType();
        subjectType.setCode("N");
        subjectType.setDesc("综合");
        req.setSubjectType(subjectType);
        CreateSessionReq.PrepareType prepareType = new CreateSessionReq.PrepareType();
        prepareType.setCode("PREDICT");
        prepareType.setDesc("模拟填报");
        req.setPrepareType(prepareType);
        CreateSessionReq.Batch batch = new CreateSessionReq.Batch();
        batch.setCode("17");
        batch.setName("第一段");
        batch.setLevel("01");
        batch.setScore(494F);
        req.setBatch(batch);
        req.setExamYear(2026);
        req.setTotalScore(610);
        CreateSessionReq.SubjectScore physics = new CreateSessionReq.SubjectScore();
        physics.setSubject("01");
        physics.setSubjectName("物理");
        physics.setScore(85);
        CreateSessionReq.SubjectScore chinese = new CreateSessionReq.SubjectScore();
        chinese.setSubject("08");
        chinese.setSubjectName("语文");
        chinese.setScore(112);
        req.setSubjectScoreList(Lists.newArrayList(physics, chinese));
        return req;
    }

    /** 建档请求：同一形状；subjectList 给一份，避免走用户画像兜底。 */
    private CreateSessionReq createSessionRequest() {
        CreateSessionReq req = scoreUpdateRequest();
        CreateSessionReq.SubjectItem item = new CreateSessionReq.SubjectItem();
        item.setValue("01");
        item.setName("物理");
        req.setSubjectList(Lists.newArrayList(item));
        req.setBotId(1L);
        return req;
    }
}
