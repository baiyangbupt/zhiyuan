package com.ytell.zhiyuan.service.biz;

import com.ytell.zhiyuan.common.exception.BusinessException;
import com.ytell.zhiyuan.mapper.IntegrationSessionRequestMapper;
import com.ytell.zhiyuan.model.dto.CreateSessionReq;
import com.ytell.zhiyuan.model.dto.integration.ExternalSessionInitializeReq;
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
        req.getReturnOptions().setWebBaseUrl("https://www.gaotuzhiyuan.com");
        assertEquals(1002L, service.initializeSession(1L, req).getChatSessionId());

        verify(chatSessionBizService).createChatSession(eq(1L), any(CreateSessionReq.class));
        verify(planningStateService).generateCandidatePool(eq(1L), eq(1002L), any());
        verify(planningStateService).generateInitialPlan(eq(1L), eq(1002L), any());
        verify(planningStateService).generateOrderedPlan(eq(1L), eq(1002L), any());
        verify(mapper).insert(any(IntegrationSessionRequest.class));
        verify(mapper, atLeastOnce()).updateById(any(IntegrationSessionRequest.class));
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
