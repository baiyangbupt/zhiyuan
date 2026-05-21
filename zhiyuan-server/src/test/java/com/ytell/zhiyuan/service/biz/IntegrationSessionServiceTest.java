package com.ytell.zhiyuan.service.biz;

import com.ytell.zhiyuan.common.exception.BusinessException;
import com.ytell.zhiyuan.mapper.IntegrationSessionRequestMapper;
import com.ytell.zhiyuan.model.dto.CreateSessionReq;
import com.ytell.zhiyuan.model.dto.integration.ExternalGenerationOptionsDTO;
import com.ytell.zhiyuan.model.dto.integration.ExternalSessionInitializeReq;
import com.ytell.zhiyuan.model.dto.integration.ExternalSessionInitializeRes;
import com.ytell.zhiyuan.model.dto.planning.OrderedPlanStateDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningWorkspaceStateRes;
import com.ytell.zhiyuan.model.entity.biz.IntegrationSessionRequest;
import com.ytell.zhiyuan.model.enums.AuthTypeEnum;
import com.ytell.zhiyuan.model.vo.ChatSessionVo;
import com.ytell.zhiyuan.web.interceptor.UserBaseData;
import com.ytell.zhiyuan.web.interceptor.UserInfoThreadLocalUtil;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.mockito.Mockito;
import org.springframework.test.util.ReflectionTestUtils;

import java.util.HashMap;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.*;

public class IntegrationSessionServiceTest {

    private IntegrationSessionService service;
    private IntegrationSessionRequestMapper mapper;
    private ChatSessionBizService chatSessionBizService;
    private PlanningStateService planningStateService;

    @BeforeEach
    void setUp() {
        service = new IntegrationSessionService();
        mapper = Mockito.mock(IntegrationSessionRequestMapper.class);
        chatSessionBizService = Mockito.mock(ChatSessionBizService.class);
        planningStateService = Mockito.mock(PlanningStateService.class);
        ReflectionTestUtils.setField(service, "integrationSessionRequestMapper", mapper);
        ReflectionTestUtils.setField(service, "chatSessionBizService", chatSessionBizService);
        ReflectionTestUtils.setField(service, "planningStateService", planningStateService);

        UserBaseData userBaseData = new UserBaseData();
        userBaseData.setUserId(7L);
        userBaseData.setAuthType(AuthTypeEnum.WEB);
        UserInfoThreadLocalUtil.set(userBaseData);
    }

    @AfterEach
    void tearDown() {
        UserInfoThreadLocalUtil.remove();
    }

    @Test
    void shouldCreateSessionAndGeneratePlan() {
        when(mapper.selectOne(any())).thenReturn(null);
        ChatSessionVo sessionVo = new ChatSessionVo();
        sessionVo.setId(1002L);
        when(chatSessionBizService.createChatSession(eq(1L), any(CreateSessionReq.class))).thenReturn(sessionVo);
        when(planningStateService.getPlanningWorkspaceState(1002L)).thenReturn(buildWorkspaceState());

        ExternalSessionInitializeReq req = buildReq("ext-1");
        req.getCreateSession().setUserName(" 高翔 ");
        req.getReturnOptions().setWebBaseUrl("https://www.gaotuzhiyuan.com");
        ExternalSessionInitializeRes res = service.initializeSession(1L, req);
        assertEquals(1002L, res.getChatSessionId());
        assertEquals("高翔", res.getStudentName());
        assertTrue(res.getSessionUrl().contains("/assistant-pc/sessionDetailV2?chatSessionId=1002"));
        assertEquals(Integer.valueOf(120), res.getPlanning().getCandidateTotal());
        assertEquals(Integer.valueOf(45), res.getPlanning().getOrderedTotal());
        assertEquals(Integer.valueOf(18), res.getPlanning().getTierCounts().get("sprint"));

        verify(chatSessionBizService).createChatSession(eq(1L), any(CreateSessionReq.class));
        verify(planningStateService).generateCandidatePool(eq(1L), eq(1002L), any());
        verify(planningStateService).generateInitialPlan(eq(1L), eq(1002L), any());
        verify(planningStateService).generateOrderedPlan(eq(1L), eq(1002L), any());
        verify(mapper).insert(any(IntegrationSessionRequest.class));
        verify(mapper, atLeastOnce()).updateById(any(IntegrationSessionRequest.class));
    }

    @Test
    void shouldNotReturnBlankStudentName() {
        when(mapper.selectOne(any())).thenReturn(null);
        ChatSessionVo sessionVo = new ChatSessionVo();
        sessionVo.setId(1002L);
        when(chatSessionBizService.createChatSession(eq(1L), any(CreateSessionReq.class))).thenReturn(sessionVo);
        when(planningStateService.getPlanningWorkspaceState(1002L)).thenReturn(buildWorkspaceState());

        ExternalSessionInitializeReq req = buildReq("ext-1");
        req.getCreateSession().setUserName("   ");

        ExternalSessionInitializeRes res = service.initializeSession(1L, req);

        assertNull(res.getStudentName());
    }

    @Test
    void shouldNormalizeCreateSessionDefaultsBeforeCreatingSession() {
        when(mapper.selectOne(any())).thenReturn(null);
        ChatSessionVo sessionVo = new ChatSessionVo();
        sessionVo.setId(1002L);
        when(chatSessionBizService.createChatSession(eq(1L), any(CreateSessionReq.class))).thenReturn(sessionVo);
        when(planningStateService.getPlanningWorkspaceState(1002L)).thenReturn(buildWorkspaceState());

        ExternalSessionInitializeReq req = buildReq("ext-1");

        service.initializeSession(1L, req);

        verify(chatSessionBizService).normalizeCreateSessionDefaults(req.getCreateSession());
        verify(chatSessionBizService).createChatSession(eq(1L), eq(req.getCreateSession()));
    }

    @Test
    void shouldReturnExistingSessionWhenIdempotentRequestSucceeded() {
        ExternalSessionInitializeReq req = buildReq("ext-1");
        IntegrationSessionRequest existing = new IntegrationSessionRequest();
        existing.setStatus("SUCCESS");
        existing.setChatSessionId(1002L);
        existing.setRequestHash(invokeHash(req));
        when(mapper.selectOne(any())).thenReturn(existing);
        when(planningStateService.getPlanningWorkspaceState(1002L)).thenReturn(buildWorkspaceState());

        assertFalse(service.initializeSession(1L, req).getCreated());
        verify(chatSessionBizService, never()).createChatSession(any(), any());
    }

    @Test
    void shouldRejectProcessingIdempotentRequest() {
        ExternalSessionInitializeReq req = buildReq("ext-1");
        IntegrationSessionRequest existing = new IntegrationSessionRequest();
        existing.setStatus("PROCESSING");
        existing.setRequestHash(invokeHash(req));
        when(mapper.selectOne(any())).thenReturn(existing);

        BusinessException exception = assertThrows(BusinessException.class, () -> service.initializeSession(1L, req));
        assertEquals("同一externalRequestId正在处理中", exception.getMessage());
        verify(chatSessionBizService, never()).createChatSession(any(), any());
    }

    @Test
    void shouldRejectSameExternalRequestIdWithDifferentPayload() {
        ExternalSessionInitializeReq req = buildReq("ext-1");
        IntegrationSessionRequest existing = new IntegrationSessionRequest();
        existing.setStatus("SUCCESS");
        existing.setChatSessionId(1002L);
        existing.setRequestHash("different");
        when(mapper.selectOne(any())).thenReturn(existing);

        BusinessException exception = assertThrows(BusinessException.class, () -> service.initializeSession(1L, req));
        assertTrue(exception.getMessage().contains("externalRequestId"));
    }

    @Test
    void shouldRequireAuthorizedUser() {
        UserInfoThreadLocalUtil.remove();
        BusinessException exception = assertThrows(BusinessException.class, () -> service.initializeSession(1L, buildReq("ext-1")));
        assertEquals("不合法请求", exception.getMessage());
    }

    @Test
    void shouldValidateRequiredParameters() {
        BusinessException nullReq = assertThrows(BusinessException.class, () -> service.initializeSession(1L, null));
        assertEquals("请求不能为空", nullReq.getMessage());

        ExternalSessionInitializeReq missingExternalId = buildReq(null);
        BusinessException missingExternalIdError = assertThrows(BusinessException.class,
                () -> service.initializeSession(1L, missingExternalId));
        assertEquals("externalRequestId不能为空", missingExternalIdError.getMessage());

        ExternalSessionInitializeReq missingCreateSession = buildReq("ext-1");
        missingCreateSession.setCreateSession(null);
        BusinessException missingCreateSessionError = assertThrows(BusinessException.class,
                () -> service.initializeSession(1L, missingCreateSession));
        assertEquals("createSession不能为空", missingCreateSessionError.getMessage());
    }

    @Test
    void shouldRecordAuthorizedUserInIdempotentRecord() {
        when(mapper.selectOne(any())).thenReturn(null);
        ChatSessionVo sessionVo = new ChatSessionVo();
        sessionVo.setId(1002L);
        when(chatSessionBizService.createChatSession(eq(1L), any(CreateSessionReq.class))).thenReturn(sessionVo);
        when(planningStateService.getPlanningWorkspaceState(1002L)).thenReturn(buildWorkspaceState());

        service.initializeSession(1L, buildReq("ext-1"));

        ArgumentCaptor<IntegrationSessionRequest> captor = ArgumentCaptor.forClass(IntegrationSessionRequest.class);
        verify(mapper).insert(captor.capture());
        assertEquals(7L, captor.getValue().getUserId());
        assertEquals("WEB", captor.getValue().getPlatform());
    }

    @Test
    void shouldRespectGenerationOptions() {
        when(mapper.selectOne(any())).thenReturn(null);
        ChatSessionVo sessionVo = new ChatSessionVo();
        sessionVo.setId(1002L);
        when(chatSessionBizService.createChatSession(eq(1L), any(CreateSessionReq.class))).thenReturn(sessionVo);
        when(planningStateService.getPlanningWorkspaceState(1002L)).thenReturn(buildWorkspaceState());

        ExternalSessionInitializeReq req = buildReq("ext-1");
        ExternalGenerationOptionsDTO options = new ExternalGenerationOptionsDTO();
        options.setGenerateCandidatePool(false);
        options.setGenerateInitialPlan(false);
        options.setGenerateOrderedPlan(false);
        req.setGenerationOptions(options);

        service.initializeSession(1L, req);

        verify(planningStateService, never()).generateCandidatePool(any(), any(), any());
        verify(planningStateService, never()).generateInitialPlan(any(), any(), any());
        verify(planningStateService, never()).generateOrderedPlan(any(), any(), any());
        verify(planningStateService).getPlanningWorkspaceState(1002L);
    }

    @Test
    void shouldSkipWorkspaceStateWhenReturnWorkspaceStateDisabled() {
        when(mapper.selectOne(any())).thenReturn(null);
        ChatSessionVo sessionVo = new ChatSessionVo();
        sessionVo.setId(1002L);
        when(chatSessionBizService.createChatSession(eq(1L), any(CreateSessionReq.class))).thenReturn(sessionVo);

        ExternalSessionInitializeReq req = buildReq("ext-1");
        req.getGenerationOptions().setReturnWorkspaceState(false);

        ExternalSessionInitializeRes res = service.initializeSession(1L, req);

        assertEquals(1002L, res.getChatSessionId());
        assertNull(res.getPlanning().getPhase());
        verify(planningStateService, never()).getPlanningWorkspaceState(any());
    }

    @Test
    void shouldBuildRootPathUrlWhenRequested() {
        when(mapper.selectOne(any())).thenReturn(null);
        ChatSessionVo sessionVo = new ChatSessionVo();
        sessionVo.setId(1002L);
        when(chatSessionBizService.createChatSession(eq(1L), any(CreateSessionReq.class))).thenReturn(sessionVo);
        when(planningStateService.getPlanningWorkspaceState(1002L)).thenReturn(buildWorkspaceState());

        ExternalSessionInitializeReq req = buildReq("ext-1");
        req.getReturnOptions().setWebBaseUrl("https://zhiyuan.ytell.cn/");
        req.getReturnOptions().setPathMode("root");

        ExternalSessionInitializeRes res = service.initializeSession(1L, req);

        assertEquals("https://zhiyuan.ytell.cn/sessionDetailV2?chatSessionId=1002", res.getSessionUrl());
        assertEquals("https://zhiyuan.ytell.cn/sessionDetailLegacy?chatSessionId=1002", res.getLegacySessionUrl());
    }

    @Test
    void shouldMarkFailedWhenSessionCreationFails() {
        when(mapper.selectOne(any())).thenReturn(null);
        when(chatSessionBizService.createChatSession(eq(1L), any(CreateSessionReq.class)))
                .thenThrow(new BusinessException(110, "创建失败"));

        BusinessException exception = assertThrows(BusinessException.class, () -> service.initializeSession(1L, buildReq("ext-1")));
        assertEquals("创建失败", exception.getMessage());

        ArgumentCaptor<IntegrationSessionRequest> captor = ArgumentCaptor.forClass(IntegrationSessionRequest.class);
        verify(mapper, atLeastOnce()).updateById(captor.capture());
        IntegrationSessionRequest lastUpdate = captor.getAllValues().get(captor.getAllValues().size() - 1);
        assertEquals("FAILED", lastUpdate.getStatus());
        assertEquals("创建失败", lastUpdate.getErrorMessage());
    }

    private ExternalSessionInitializeReq buildReq(String externalRequestId) {
        ExternalSessionInitializeReq req = new ExternalSessionInitializeReq();
        req.setExternalRequestId(externalRequestId);
        req.setCreateSession(new CreateSessionReq());
        return req;
    }

    private PlanningWorkspaceStateRes buildWorkspaceState() {
        PlanningWorkspaceStateRes workspaceState = new PlanningWorkspaceStateRes();
        workspaceState.setPhase("ordered");
        workspaceState.setVersion(3);
        workspaceState.getCandidatePoolState().getSummary().setUnitTotal(120);
        workspaceState.getDraftPlanState().getSummary().setUnitTotal(45);
        OrderedPlanStateDTO.Summary summary = workspaceState.getOrderedPlanState().getSummary();
        summary.setUnitTotal(45);
        summary.setUnitTierCounts(new HashMap<String, Integer>());
        summary.getUnitTierCounts().put("sprint", 18);
        return workspaceState;
    }

    private String invokeHash(ExternalSessionInitializeReq req) {
        return (String) ReflectionTestUtils.invokeMethod(service, "hashRequest", req);
    }
}
