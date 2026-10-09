package com.ytell.zhiyuan.service.biz;

import com.alibaba.fastjson.JSONObject;
import com.google.common.collect.Lists;
import com.ytell.zhiyuan.common.constants.ChatSessionExtraDataConstants;
import com.ytell.zhiyuan.manager.ProvinceVolunteerStrategyManager;
import com.ytell.zhiyuan.model.dto.CreateSessionReq;
import com.ytell.zhiyuan.model.dto.UpdateScoreDetailRes;
import com.ytell.zhiyuan.model.dto.gaotu.RecommendNumResponse;
import com.ytell.zhiyuan.model.dto.gaotu.req.ProgramPageReq;
import com.ytell.zhiyuan.model.dto.gaotu.req.RecommendNumReq;
import com.ytell.zhiyuan.model.dto.inner.VolunteerSourceDataSnapshot;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateVersionDTO;
import com.ytell.zhiyuan.model.dto.planning.StaleFlagsDTO;
import com.ytell.zhiyuan.model.entity.biz.ChatSession;
import com.ytell.zhiyuan.model.entity.biz.ChatSessionExtraData;
import com.ytell.zhiyuan.model.enums.OperateCheckPoint;
import com.ytell.zhiyuan.model.vo.CheckRightsResVo;
import com.ytell.zhiyuan.service.GaotuService;
import com.ytell.zhiyuan.service.shared.ChatSessionExtraDataSharedService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.mockito.Mockito;
import org.springframework.test.util.ReflectionTestUtils;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyBoolean;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 演示环境的 **prepareType 兜底**（`demo.prepare-type-fallback`，默认空=关）。
 *
 * <p>背景（2026-10-08/09 定性）：上游已切 2027 填报季，省策略实时推出来是 VOLUNTEER；
 * 而本地演示会员（如 900002）只有 PREDICT 取数策略 → 补录确认在拉全量志愿数据那一跳
 * 84009「当前策略已失效」。本地让步：配置有值时，缺 prepareType **用兜底值、不走省策略
 * 推导**；默认（不配置）= 与今天逐字节相同。</p>
 *
 * <p>优先级（合并之后看）：请求显式带 &gt; 会话存量已有 → 都保持不动；否则兜底有值 →
 * 兜底；否则 → 省策略推导（现状）。测试盯的是"兜底真的进了请求参数"：断言落到
 * userScoreDetail 的值，并用它拼出取数用的 {@link ProgramPageReq}（与
 * {@code VolunteerSourceDataSyncService.fetchLatestSourceData} 同一个拼装器）。</p>
 */
public class ChatSessionBizServiceScoreUpdatePrepareTypeFallbackTest {

    private static final Long TENANT_ID = 1L;
    private static final Long SESSION_ID = 900L;
    private static final Long USER_ID = 7L;

    private ChatSessionBizService service;
    private ChatSessionExtraDataSharedService chatSessionExtraDataSharedService;
    private GaotuService gaotuService;
    private VolunteerSourceDataSyncService volunteerSourceDataSyncService;
    private PlanningStateService planningStateService;
    private ScoreCatalogService scoreCatalogService;

    @BeforeEach
    void setUp() {
        service = new ChatSessionBizService();
        chatSessionExtraDataSharedService = mock(ChatSessionExtraDataSharedService.class);
        planningStateService = mock(PlanningStateService.class);
        volunteerSourceDataSyncService = mock(VolunteerSourceDataSyncService.class);
        gaotuService = mock(GaotuService.class);
        scoreCatalogService = mock(ScoreCatalogService.class);
        UserBizService userBizService = mock(UserBizService.class);

        ReflectionTestUtils.setField(service, "chatSessionExtraDataSharedService", chatSessionExtraDataSharedService);
        ReflectionTestUtils.setField(service, "planningStateService", planningStateService);
        ReflectionTestUtils.setField(service, "volunteerSourceDataSyncService", volunteerSourceDataSyncService);
        ReflectionTestUtils.setField(service, "gaotuService", gaotuService);
        ReflectionTestUtils.setField(service, "scoreCatalogService", scoreCatalogService);
        ReflectionTestUtils.setField(service, "userBizService", userBizService);
        ReflectionTestUtils.setField(service, "volunteerStrategyManager", mock(ProvinceVolunteerStrategyManager.class));
        // 单科成绩会推导出 strengthSubjectList → hasProfileIntent 为真 → 画像同步要走一道，
        // 画像读取打桩成空（与空档案会话现状一致）。
        ReflectionTestUtils.setField(service, "volunteerDataProvider", mock(VolunteerDataProvider.class));

        ConversationAccessService conversationAccessService = mock(ConversationAccessService.class);
        when(conversationAccessService.requireOwnedSession(TENANT_ID, SESSION_ID, USER_ID)).thenReturn(new ChatSession());
        ReflectionTestUtils.setField(service, "conversationAccessService", conversationAccessService);

        CheckRightsResVo rights = new CheckRightsResVo();
        rights.setCanOperate(Boolean.TRUE);
        when(userBizService.checkRights(eq(USER_ID), eq(OperateCheckPoint.CreateSession), any())).thenReturn(rights);

        RecommendNumResponse numResponse = new RecommendNumResponse();
        numResponse.setMajorNum(300);
        numResponse.setSchoolNum(120);
        when(gaotuService.getRecommendProgramNum(any(RecommendNumReq.class))).thenReturn(numResponse);

        ProvinceVolunteerStrategyManager strategyManager =
                (ProvinceVolunteerStrategyManager) ReflectionTestUtils.getField(service, "volunteerStrategyManager");
        when(strategyManager.getVolunteerStrategyByProvinceCode("330000", "01")).thenReturn("OTOO");

        VolunteerSourceDataSnapshot snapshot = new VolunteerSourceDataSnapshot();
        snapshot.setFetchedAt("2026-10-09T10:00:00+08:00");
        when(volunteerSourceDataSyncService.fetchLatestSourceData(TENANT_ID, SESSION_ID, true)).thenReturn(snapshot);

        PlanningStateVersionDTO versionDTO = new PlanningStateVersionDTO();
        versionDTO.setVersion(6);
        versionDTO.setStaleFlags(new StaleFlagsDTO());
        when(planningStateService.applyScoreDetailUpdate(eq(SESSION_ID), any(CreateSessionReq.class), any(), anyBoolean()))
                .thenReturn(versionDTO);

        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(SESSION_ID, ChatSessionExtraDataConstants.USER_SCORE_KEY))
                .thenReturn(null);
    }

    /** ① 兜底开 + 缺 prepareType → 用兜底值；且一路进到取数请求参数（ProgramPageReq.prepareType）。 */
    @Test
    void fallbackOnFillsMissingPrepareTypeAllTheWayIntoTheFetchRequestParams() {
        ReflectionTestUtils.setField(service, "prepareTypeFallback", "PREDICT");
        // 省策略此刻的口径：VOLUNTEER（2027 填报季）——兜底必须压过它，否则就是原故障现场。
        when(scoreCatalogService.provinceDefaultsOrNull("330000")).thenReturn(provinceDefaults("N", "综合", "VOLUNTEER", "智能填报"));

        UpdateScoreDetailRes res = service.updateScoreDetailForUser(TENANT_ID, SESSION_ID, scoreUpdateRequest(), USER_ID);

        assertEquals(Boolean.TRUE, res.getSuccess());
        JSONObject saved = capturedScoreRow();

        // 落库的（=取数请求读的那份）是兜底值，不是省策略推出来的 VOLUNTEER。
        assertEquals("PREDICT", saved.getJSONObject("prepareType").getString("code"));
        assertEquals("模拟填报", saved.getJSONObject("prepareType").getString("desc"));
        // 科类仍按省策略补齐（兜底只接管 prepareType）。
        assertEquals("N", saved.getJSONObject("subjectType").getString("code"));

        // 真正拼一遍上游取数请求：prepareType 参数就是兜底值（与 fetchLatestSourceData 同一拼装器）。
        VolunteerSourceDataSyncService syncService = new VolunteerSourceDataSyncService();
        ChatSession session = new ChatSession();
        session.setUserId(900002L);
        CreateSessionReq persisted = JSONObject.parseObject(saved.toJSONString(), CreateSessionReq.class);
        ProgramPageReq upstream = ReflectionTestUtils.invokeMethod(syncService, "toProgramQuery", session, persisted);
        assertNotNull(upstream);
        assertEquals("PREDICT", upstream.getPrepareType(), "兜底值必须进到取数请求参数，不能只停在日志里");
    }

    /** ② 兜底关（默认）→ 仍走省策略推导，行为与今天完全一致。 */
    @Test
    void fallbackOffKeepsProvincePolicyDerivationAsToday() {
        // 不设 prepareTypeFallback：空 = 关（生产默认）。
        when(scoreCatalogService.provinceDefaultsOrNull("330000")).thenReturn(provinceDefaults("N", "综合", "VOLUNTEER", "智能填报"));

        service.updateScoreDetailForUser(TENANT_ID, SESSION_ID, scoreUpdateRequest(), USER_ID);

        JSONObject saved = capturedScoreRow();
        assertEquals("VOLUNTEER", saved.getJSONObject("prepareType").getString("code"),
                "兜底关时保持现状：省策略推导");
    }

    /** ③ 请求显式带 prepareType（草稿合并后已非空）→ 兜底不上场、也不查省策略。 */
    @Test
    void explicitPrepareTypeIsNeverOverwrittenByTheFallback() {
        ReflectionTestUtils.setField(service, "prepareTypeFallback", "PREDICT");
        CreateSessionReq req = scoreUpdateRequest();
        CreateSessionReq.SubjectType subjectType = new CreateSessionReq.SubjectType();
        subjectType.setCode("N");
        subjectType.setDesc("综合");
        req.setSubjectType(subjectType);
        req.setPrepareType(prepareType("VOLUNTEER", "智能填报"));

        service.updateScoreDetailForUser(TENANT_ID, SESSION_ID, req, USER_ID);

        JSONObject saved = capturedScoreRow();
        assertEquals("VOLUNTEER", saved.getJSONObject("prepareType").getString("code"), "显式值优先级最高");
        verify(scoreCatalogService, never()).provinceDefaultsOrNull(any());
    }

    /** ④ 会话存量口径已有（既有 userScoreDetail 行带 prepareType）→ 保持现状不动，兜底不覆盖。 */
    @Test
    void sessionStoredPrepareTypeIsKeptEvenWithFallbackOn() {
        ReflectionTestUtils.setField(service, "prepareTypeFallback", "PREDICT");
        CreateSessionReq stored = scoreUpdateRequest();
        CreateSessionReq.SubjectType subjectType = new CreateSessionReq.SubjectType();
        subjectType.setCode("N");
        subjectType.setDesc("综合");
        stored.setSubjectType(subjectType);
        stored.setPrepareType(prepareType("PREDICT", "模拟填报"));
        ChatSessionExtraData existing = new ChatSessionExtraData();
        existing.setChatSessionId(SESSION_ID);
        existing.setDataKey(ChatSessionExtraDataConstants.USER_SCORE_KEY);
        existing.setDataValue(JSONObject.toJSONString(stored));
        when(chatSessionExtraDataSharedService.getBySessionIdAndDataKey(SESSION_ID, ChatSessionExtraDataConstants.USER_SCORE_KEY))
                .thenReturn(existing);

        CreateSessionReq increment = new CreateSessionReq();
        increment.setTotalScore(620);
        service.updateScoreDetailForUser(TENANT_ID, SESSION_ID, increment, USER_ID);

        ArgumentCaptor<ChatSessionExtraData> captor = ArgumentCaptor.forClass(ChatSessionExtraData.class);
        verify(chatSessionExtraDataSharedService, Mockito.atLeastOnce()).updateById(captor.capture());
        ChatSessionExtraData scoreRow = captor.getAllValues().stream()
                .filter(row -> ChatSessionExtraDataConstants.USER_SCORE_KEY.equals(row.getDataKey()))
                .findFirst()
                .orElseThrow(() -> new AssertionError("补录必须更新 userScoreDetail"));
        JSONObject updated = JSONObject.parseObject(scoreRow.getDataValue());
        assertEquals("PREDICT", updated.getJSONObject("prepareType").getString("code"),
                "存量行的 prepareType（这里铺的是 PREDICT）原样保留");
        assertEquals(620, updated.getIntValue("totalScore"));
        verify(scoreCatalogService, never()).provinceDefaultsOrNull(any());
    }

    // ── 夹具 ──────────────────────────────────────────────────────────────

    private JSONObject capturedScoreRow() {
        ArgumentCaptor<ChatSessionExtraData> captor = ArgumentCaptor.forClass(ChatSessionExtraData.class);
        verify(chatSessionExtraDataSharedService, Mockito.atLeastOnce()).save(captor.capture());
        ChatSessionExtraData scoreRow = captor.getAllValues().stream()
                .filter(row -> ChatSessionExtraDataConstants.USER_SCORE_KEY.equals(row.getDataKey()))
                .findFirst()
                .orElseThrow(() -> new AssertionError("补录必须落 userScoreDetail"));
        return JSONObject.parseObject(scoreRow.getDataValue());
    }

    private ScoreCatalogService.ProvinceDefaults provinceDefaults(String subjectTypeCode, String subjectTypeDesc,
                                                                  String prepareTypeCode, String prepareTypeDesc) {
        ScoreCatalogService.ProvinceDefaults defaults = new ScoreCatalogService.ProvinceDefaults();
        if (subjectTypeCode != null) {
            CreateSessionReq.SubjectType subjectType = new CreateSessionReq.SubjectType();
            subjectType.setCode(subjectTypeCode);
            subjectType.setDesc(subjectTypeDesc);
            defaults.setSubjectType(subjectType);
        }
        defaults.setPrepareType(prepareType(prepareTypeCode, prepareTypeDesc));
        return defaults;
    }

    private CreateSessionReq.PrepareType prepareType(String code, String desc) {
        CreateSessionReq.PrepareType prepareType = new CreateSessionReq.PrepareType();
        prepareType.setCode(code);
        prepareType.setDesc(desc);
        return prepareType;
    }

    /** 补录草稿：省份/批次/位次齐备，**缺 prepareType**（上游切季后模型补录的实测形状）。 */
    private CreateSessionReq scoreUpdateRequest() {
        CreateSessionReq req = new CreateSessionReq();
        CreateSessionReq.Province province = new CreateSessionReq.Province();
        province.setCode("330000");
        province.setName("浙江省");
        req.setProvince(province);
        CreateSessionReq.Batch batch = new CreateSessionReq.Batch();
        batch.setCode("17");
        batch.setName("第一段");
        batch.setLevel("01");
        batch.setScore(494F);
        req.setBatch(batch);
        req.setExamYear(2026);
        req.setTotalScore(610);
        req.setTotalScorePos(12000);
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
}
