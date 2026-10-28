package com.ytell.zhiyuan.web.controller;

import com.ytell.zhiyuan.common.config.GlobalExceptionHandler;
import com.ytell.zhiyuan.common.exception.ConversationAccessException;
import com.ytell.zhiyuan.model.dto.planning.CandidatePoolQueryRes;
import com.ytell.zhiyuan.model.dto.planning.ConversationEvidenceDTO;
import com.ytell.zhiyuan.model.dto.planning.DataFreshnessCheckReq;
import com.ytell.zhiyuan.model.dto.planning.FixProposalApplyReq;
import com.ytell.zhiyuan.model.dto.planning.FixProposalApplyRes;
import com.ytell.zhiyuan.model.dto.planning.PlanningWorkspaceStateRes;
import com.ytell.zhiyuan.model.entity.biz.ChatSession;
import com.ytell.zhiyuan.service.biz.ConversationAccessService;
import com.ytell.zhiyuan.service.biz.EvidenceLedgerService;
import com.ytell.zhiyuan.service.biz.PlanningStateService;
import com.ytell.zhiyuan.web.interceptor.UserBaseData;
import com.ytell.zhiyuan.web.interceptor.UserInfoThreadLocalUtil;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.mockito.Mockito;
import org.springframework.http.MediaType;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import java.util.Arrays;
import java.util.Date;

import static org.hamcrest.Matchers.containsString;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.patch;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * facade 的两条硬规则：ownership 先于一切；合法请求原样委托既有服务。
 */
public class PlanningFacadeControllerTest {

    private static final Long TENANT = 1L;
    private static final Long SESSION = 42L;
    private static final Long PRINCIPAL = 7L;

    private MockMvc mockMvc;
    private ConversationAccessService conversationAccessService;
    private PlanningStateService planningStateService;
    private EvidenceLedgerService evidenceLedgerService;

    @BeforeEach
    void setUp() {
        PlanningFacadeController controller = new PlanningFacadeController();
        conversationAccessService = Mockito.mock(ConversationAccessService.class);
        planningStateService = Mockito.mock(PlanningStateService.class);
        evidenceLedgerService = Mockito.mock(EvidenceLedgerService.class);
        ReflectionTestUtils.setField(controller, "conversationAccessService", conversationAccessService);
        ReflectionTestUtils.setField(controller, "planningStateService", planningStateService);
        ReflectionTestUtils.setField(controller, "evidenceLedgerService", evidenceLedgerService);
        mockMvc = MockMvcBuilders.standaloneSetup(controller)
                .setControllerAdvice(new GlobalExceptionHandler())
                .build();
        UserBaseData principal = new UserBaseData();
        principal.setUserId(PRINCIPAL);
        UserInfoThreadLocalUtil.set(principal);
    }

    @AfterEach
    void tearDown() {
        UserInfoThreadLocalUtil.remove();
    }

    @Test
    void refusesAForeignSessionWithAReal403BeforeTouchingPlanningState() throws Exception {
        when(conversationAccessService.requireOwnedSession(TENANT, SESSION, PRINCIPAL))
                .thenThrow(new ConversationAccessException(403, "session_forbidden"));

        mockMvc.perform(get("/gaotu-assistant-bot/chat/1/planning/session/workspace-state")
                        .param("chatSessionId", "42"))
                .andExpect(status().isForbidden())
                .andExpect(jsonPath("$.code").value(403))
                .andExpect(jsonPath("$.msg").value("session_forbidden"));

        // 归属未过就不能碰业务服务——两个 mock 都不该有交互。
        Mockito.verify(planningStateService, Mockito.never()).getPlanningWorkspaceState(anyLong(), anyLong());
        Mockito.verify(evidenceLedgerService, Mockito.never()).listSessionEvidence(anyLong(), anyLong(), any(Date.class));
    }

    @Test
    void delegatesWorkspaceStateForTheOwnerWithTheThreadLocalPrincipal() throws Exception {
        ChatSession session = new ChatSession();
        session.setId(SESSION);
        when(conversationAccessService.requireOwnedSession(TENANT, SESSION, PRINCIPAL)).thenReturn(session);
        PlanningWorkspaceStateRes res = new PlanningWorkspaceStateRes();
        res.setSessionId(SESSION);
        res.setPhase("ordered");
        when(planningStateService.getPlanningWorkspaceState(TENANT, SESSION)).thenReturn(res);

        mockMvc.perform(get("/gaotu-assistant-bot/chat/1/planning/session/workspace-state")
                        .param("chatSessionId", "42"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(0))
                .andExpect(jsonPath("$.data.sessionId").value(42))
                .andExpect(jsonPath("$.data.phase").value("ordered"));

        // principal 来自登录态线程缓存，不来自请求参数。
        Mockito.verify(conversationAccessService).requireOwnedSession(TENANT, SESSION, PRINCIPAL);
        Mockito.verify(planningStateService).getPlanningWorkspaceState(TENANT, SESSION);
    }

    @Test
    void returnsAMissingPrincipalAsAReal401() throws Exception {
        UserInfoThreadLocalUtil.remove();

        mockMvc.perform(get("/gaotu-assistant-bot/chat/1/planning/session/workspace-state")
                        .param("chatSessionId", "42"))
                .andExpect(status().isUnauthorized())
                .andExpect(jsonPath("$.code").value(401));

        Mockito.verify(conversationAccessService, Mockito.never())
                .requireOwnedSession(anyLong(), anyLong(), anyLong());
    }

    @Test
    void delegatesCandidatePoolQueryBodyUnchanged() throws Exception {
        when(conversationAccessService.requireOwnedSession(TENANT, SESSION, PRINCIPAL)).thenReturn(new ChatSession());
        when(planningStateService.queryCandidatePool(eq(TENANT), eq(SESSION), any()))
                .thenReturn(new CandidatePoolQueryRes());

        mockMvc.perform(post("/gaotu-assistant-bot/chat/1/planning/session/candidate-pool/query")
                        .param("chatSessionId", "42")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"page\":1,\"pageSize\":20}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(0));

        Mockito.verify(planningStateService).queryCandidatePool(eq(TENANT), eq(SESSION), any());
    }

    @Test
    void toleratesAnEmptyBodyWhereTheInnerEndpointDoes() throws Exception {
        when(conversationAccessService.requireOwnedSession(TENANT, SESSION, PRINCIPAL)).thenReturn(new ChatSession());
        when(planningStateService.checkDataFreshness(eq(TENANT), eq(SESSION), any(DataFreshnessCheckReq.class)))
                .thenReturn(null);

        mockMvc.perform(post("/gaotu-assistant-bot/chat/1/planning/session/data-freshness/check")
                        .param("chatSessionId", "42"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(0));

        // 与 inner 一致：空 body 也要补一个空请求对象，不能把 null 传给服务。
        Mockito.verify(planningStateService).checkDataFreshness(eq(TENANT), eq(SESSION), any(DataFreshnessCheckReq.class));
    }

    @Test
    void passesTheSourceVersionGuardThroughUnchanged() throws Exception {
        when(conversationAccessService.requireOwnedSession(TENANT, SESSION, PRINCIPAL)).thenReturn(new ChatSession());
        when(planningStateService.applyFixProposal(eq(TENANT), eq(SESSION), any(FixProposalApplyReq.class)))
                .thenReturn(new FixProposalApplyRes());

        mockMvc.perform(post("/gaotu-assistant-bot/chat/1/planning/session/fix-proposals/apply")
                        .param("chatSessionId", "42")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"proposalId\":\"p1\",\"sourceVersionGuard\":3,\"rerunReview\":false}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(0));

        // CAS 判断在服务层（40904 等），facade 不得改写守卫值。
        ArgumentCaptor<FixProposalApplyReq> captor = ArgumentCaptor.forClass(FixProposalApplyReq.class);
        Mockito.verify(planningStateService).applyFixProposal(eq(TENANT), eq(SESSION), captor.capture());
        assertEquals("p1", captor.getValue().getProposalId());
        assertEquals(Integer.valueOf(3), captor.getValue().getSourceVersionGuard());
        assertEquals(Boolean.FALSE, captor.getValue().getRerunReview());
    }

    @Test
    void refusesDirectUserGoalApplyBeforeCallingPlanningService() throws Exception {
        when(conversationAccessService.requireOwnedSession(TENANT, SESSION, PRINCIPAL)).thenReturn(new ChatSession());

        mockMvc.perform(post("/gaotu-assistant-bot/chat/1/planning/session/fix-proposals/apply")
                        .param("chatSessionId", "42")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"proposalId\":\"p1\",\"proposalSource\":\"user_goal\",\"sourceVersionGuard\":3}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(409))
                .andExpect(jsonPath("$.msg").value("user_goal_requires_confirmation"));

        Mockito.verify(planningStateService, Mockito.never())
                .applyFixProposal(eq(TENANT), eq(SESSION), any(FixProposalApplyReq.class));
    }

    @Test
    void keepsTheExportContentDispositionHeaders() throws Exception {
        when(conversationAccessService.requireOwnedSession(TENANT, SESSION, PRINCIPAL)).thenReturn(new ChatSession());
        when(planningStateService.exportOrderedPlan(TENANT, SESSION))
                .thenReturn(new PlanningStateService.ExcelExportResult(new byte[]{1, 2, 3}, "志愿方案.xlsx"));

        mockMvc.perform(post("/gaotu-assistant-bot/chat/1/planning/session/ordered-plan/export")
                        .param("chatSessionId", "42"))
                .andExpect(status().isOk())
                .andExpect(header().string("Content-Disposition", containsString("attachment;")))
                .andExpect(header().string("Content-Disposition", containsString("filename*=UTF-8''")))
                .andExpect(header().string("Cache-Control", containsString("no-store")))
                .andExpect(content().bytes(new byte[]{1, 2, 3}));
    }

    @Test
    void evidenceIsLookedUpWithinTheSessionOnly() throws Exception {
        when(conversationAccessService.requireOwnedSession(TENANT, SESSION, PRINCIPAL)).thenReturn(new ChatSession());
        ConversationEvidenceDTO mine = evidence("ev_01MINE");
        ConversationEvidenceDTO sibling = evidence("ev_01SIBLING");
        when(evidenceLedgerService.listSessionEvidence(eq(TENANT), eq(SESSION), any(Date.class)))
                .thenReturn(Arrays.asList(mine, sibling));

        mockMvc.perform(get("/gaotu-assistant-bot/chat/1/planning/session/evidence")
                        .param("chatSessionId", "42")
                        .param("evidenceId", "ev_01MINE"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.code").value(0))
                .andExpect(jsonPath("$.data.evidenceId").value("ev_01MINE"));

        // 查询只按 (tenant, session) 发起，evidenceId 绝不进入查询条件。
        Mockito.verify(evidenceLedgerService).listSessionEvidence(eq(TENANT), eq(SESSION), any(Date.class));
    }

    @Test
    void evidenceFromAnotherSessionIsNotFoundJustLikeAnUnknownId() throws Exception {
        when(conversationAccessService.requireOwnedSession(TENANT, SESSION, PRINCIPAL)).thenReturn(new ChatSession());
        when(evidenceLedgerService.listSessionEvidence(eq(TENANT), eq(SESSION), any(Date.class)))
                .thenReturn(Arrays.asList(evidence("ev_01MINE")));

        mockMvc.perform(get("/gaotu-assistant-bot/chat/1/planning/session/evidence")
                        .param("chatSessionId", "42")
                        .param("evidenceId", "ev_01ANOTHERSESSION"))
                .andExpect(status().isNotFound())
                .andExpect(jsonPath("$.code").value(404))
                .andExpect(jsonPath("$.msg").value("evidence_not_found"));
    }

    @Test
    void evidenceRequestForAForeignSessionIs403BeforeTheLedgerIsTouched() throws Exception {
        when(conversationAccessService.requireOwnedSession(TENANT, SESSION, PRINCIPAL))
                .thenThrow(new ConversationAccessException(403, "session_forbidden"));

        mockMvc.perform(get("/gaotu-assistant-bot/chat/1/planning/session/evidence")
                        .param("chatSessionId", "42")
                        .param("evidenceId", "ev_01MINE"))
                .andExpect(status().isForbidden())
                .andExpect(jsonPath("$.code").value(403));

        Mockito.verify(evidenceLedgerService, Mockito.never()).listSessionEvidence(anyLong(), anyLong(), any(Date.class));
    }

    @Test
    void candidateViewStatePatchStillRequiresOwnership() throws Exception {
        when(conversationAccessService.requireOwnedSession(TENANT, SESSION, PRINCIPAL))
                .thenThrow(new ConversationAccessException(403, "session_forbidden"));

        mockMvc.perform(patch("/gaotu-assistant-bot/chat/1/planning/session/candidate-view-state")
                        .param("chatSessionId", "42")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"viewMode\":\"ordered\"}"))
                .andExpect(status().isForbidden())
                .andExpect(jsonPath("$.code").value(403));
    }

    @Test
    void deadInnerEndpointsAreNotExposedOnTheFacade() throws Exception {
        when(conversationAccessService.requireOwnedSession(TENANT, SESSION, PRINCIPAL)).thenReturn(new ChatSession());

        mockMvc.perform(get("/gaotu-assistant-bot/chat/1/planning/session/state")
                        .param("chatSessionId", "42"))
                .andExpect(status().isNotFound());
        mockMvc.perform(post("/gaotu-assistant-bot/chat/1/planning/session/working-plan/lock")
                        .param("chatSessionId", "42")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"volunteerIds\":[\"v1\"],\"locked\":true}"))
                .andExpect(status().isNotFound());
    }

    private static ConversationEvidenceDTO evidence(String evidenceId) {
        ConversationEvidenceDTO dto = new ConversationEvidenceDTO();
        dto.setEvidenceId(evidenceId);
        dto.setSourceLevel("authoritative");
        dto.setDataVersion("v1");
        return dto;
    }
}
