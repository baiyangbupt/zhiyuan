package com.ytell.zhiyuan.service.biz;

import com.google.common.collect.Lists;
import com.ytell.zhiyuan.common.exception.BusinessException;
import com.ytell.zhiyuan.model.dto.CreateSessionReq;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import com.ytell.zhiyuan.model.dto.planning.ScoreUpdatePreviewDTO;
import com.ytell.zhiyuan.model.vo.CheckRightsResVo;
import com.ytell.zhiyuan.service.shared.ChatSessionExtraDataSharedService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 补录草稿缺**科类/填报类型**时按省策略推导缺省（2026-10-06 实测定性的两个洞）：
 *
 * <p>①科类：空会话补录时模型缺科类编码，而两张编码表都不含科类——草稿一路走到合并校验的
 * 110「请选择选科类型后再创建会话」，卡片永远出不来（10041946 实跑读数）。</p>
 *
 * <p>②填报类型：草稿缺 prepareType 时落 VOLUNTEER（智能填报），但上游策略是按省签发的——
 * 实测 900005/浙江 只有 PREDICT（模拟填报）有效，VOLUNTEER 在 execute 拉全量志愿数据时
 * 直接 84009「当前策略已失效，请刷新页面」，确认了也不生效（10041946 实测回包）。</p>
 *
 * <p>口径：单科类省份补唯一科类、策略自带 prepareType 直接采用（前端口径同源）；多科类
 * 省份不替用户挑（保持 110）；草稿/既有成绩已带的**不覆盖**，且不发生多余的策略查询。</p>
 */
public class ChatSessionBizServiceScoreUpdateProvinceDefaultsTest {

    private ChatSessionBizService service;
    private ScoreCatalogService scoreCatalogService;

    @BeforeEach
    void setUp() {
        service = new ChatSessionBizService();
        ConversationAccessService conversationAccessService = mock(ConversationAccessService.class);
        when(conversationAccessService.requireSessionUserId(1L, 2L)).thenReturn(7L);
        ReflectionTestUtils.setField(service, "conversationAccessService", conversationAccessService);
        // 空会话：没有既有的 userScoreDetail 行。
        ChatSessionExtraDataSharedService extraDataSharedService = mock(ChatSessionExtraDataSharedService.class);
        ReflectionTestUtils.setField(service, "chatSessionExtraDataSharedService", extraDataSharedService);

        UserBizService userBizService = mock(UserBizService.class);
        CheckRightsResVo rights = new CheckRightsResVo();
        rights.setCanOperate(Boolean.TRUE);
        when(userBizService.checkRights(any(), any(), any())).thenReturn(rights);
        ReflectionTestUtils.setField(service, "userBizService", userBizService);

        PlanningStateService planningStateService = mock(PlanningStateService.class);
        PlanningStateDTO state = new PlanningStateDTO();
        state.setSessionId(2L);
        state.setVersion(5);
        when(planningStateService.getPlanningState(2L)).thenReturn(state);
        ReflectionTestUtils.setField(service, "planningStateService", planningStateService);

        scoreCatalogService = mock(ScoreCatalogService.class);
        ReflectionTestUtils.setField(service, "scoreCatalogService", scoreCatalogService);
    }

    @Test
    void missingSubjectTypeAndPrepareTypeAreFilledFromTheProvincePolicyInOneLookup() {
        when(scoreCatalogService.provinceDefaultsOrNull("330000")).thenReturn(defaults("N", "综合", "PREDICT", "模拟填报"));

        ScoreUpdatePreviewDTO preview = service.previewScoreUpdate(1L, 2L, baseRequest());

        assertEquals("ready", preview.getStatus(), "缺科类/填报类型不再卡住：单科类省份要能出卡");
        assertEquals("综合", preview.getSummary().get("subjectType"));
        assertEquals("N", preview.getSummary().get("subjectTypeCode"));
        // 两个缺省一次策略查询里取齐（不为一件事拉两趟上游）。
        verify(scoreCatalogService).provinceDefaultsOrNull("330000");
    }

    @Test
    void missingSubjectTypeOnAMultiTypeProvinceStillFailsWithTheActionable110() {
        // 江苏 WL/LS：推导不出唯一科类 → 不替用户挑（prepareType 照旧能取）。
        when(scoreCatalogService.provinceDefaultsOrNull("320000")).thenReturn(defaults(null, null, "VOLUNTEER", "智能填报"));
        CreateSessionReq req = baseRequest();
        req.getProvince().setCode("320000");
        req.getProvince().setName("江苏省");

        BusinessException error = assertThrows(BusinessException.class,
                () -> service.previewScoreUpdate(1L, 2L, req));

        assertEquals(110, error.getStatus());
        assertEquals("请选择选科类型后再创建会话", error.getMessage(),
                "多科类省份保持原行为：校验报缺，而不是猜一个");
    }

    @Test
    void suppliedSubjectTypeAndPrepareTypeAreNeverOverwrittenAndSkipThePolicyLookup() {
        CreateSessionReq req = baseRequest();
        req.setSubjectType(subjectType("WL", "物理"));
        req.setPrepareType(prepareType("VOLUNTEER", "智能填报"));

        ScoreUpdatePreviewDTO preview = service.previewScoreUpdate(1L, 2L, req);

        // 草稿自带科类（模型/表单给的那份）：摘要用原值，且不产生策略查询。
        assertEquals("物理", preview.getSummary().get("subjectType"));
        assertEquals("WL", preview.getSummary().get("subjectTypeCode"));
        verify(scoreCatalogService, never()).provinceDefaultsOrNull(any());
    }

    private ScoreCatalogService.ProvinceDefaults defaults(String subjectTypeCode, String subjectTypeDesc,
                                                          String prepareTypeCode, String prepareTypeDesc) {
        ScoreCatalogService.ProvinceDefaults defaults = new ScoreCatalogService.ProvinceDefaults();
        if (subjectTypeCode != null) {
            defaults.setSubjectType(subjectType(subjectTypeCode, subjectTypeDesc));
        }
        defaults.setPrepareType(prepareType(prepareTypeCode, prepareTypeDesc));
        return defaults;
    }

    private CreateSessionReq.SubjectType subjectType(String code, String desc) {
        CreateSessionReq.SubjectType subjectType = new CreateSessionReq.SubjectType();
        subjectType.setCode(code);
        subjectType.setDesc(desc);
        return subjectType;
    }

    private CreateSessionReq.PrepareType prepareType(String code, String desc) {
        CreateSessionReq.PrepareType prepareType = new CreateSessionReq.PrepareType();
        prepareType.setCode(code);
        prepareType.setDesc(desc);
        return prepareType;
    }

    /** 空会话的补录草稿：省份/批次/总分/各科齐备，**缺科类与填报类型**（模型实测的形状）。 */
    private CreateSessionReq baseRequest() {
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
        req.setTotalScore(610);
        req.setExamYear(2026);
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
