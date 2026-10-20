package com.ytell.zhiyuan.service.biz;

import com.alibaba.fastjson.JSONObject;
import com.ytell.zhiyuan.Application;
import com.ytell.zhiyuan.common.exception.BusinessException;
import com.ytell.zhiyuan.model.dto.inner.PendingConfirmationRes;
import com.ytell.zhiyuan.model.dto.inner.PendingConfirmationResolveReq;
import com.ytell.zhiyuan.model.dto.planning.FixProposalApplyReq;
import com.ytell.zhiyuan.model.dto.planning.FixProposalDTO;
import com.ytell.zhiyuan.model.dto.planning.PendingPlanningCommandReq;
import com.ytell.zhiyuan.model.dto.planning.ReviewFixPrepareReq;
import com.ytell.zhiyuan.model.entity.biz.PlanningPendingCommandEntity;
import com.ytell.zhiyuan.service.shared.PlanningPendingCommandSharedService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Timeout;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.boot.test.mock.mockito.SpyBean;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.scheduling.TaskScheduler;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.atomic.AtomicBoolean;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.doCallRealMethod;

@SpringBootTest(classes = Application.class)
@ActiveProfiles("local")
@EnabledIfEnvironmentVariable(named = "PLANNING_AUDIT_STACK_DB_URL", matches = ".+")
class PlanningCommandFailureStackIntegrationTest {
    private static final long TENANT_ID = 1L;
    private long sessionId;

    @Autowired
    private JdbcTemplate jdbc;
    @Autowired
    private PlanningStateService planningStateService;
    @Autowired
    private PendingConfirmationBizService pendingService;
    @Autowired
    private PendingPlanningCommandBizService commandService;
    @Autowired
    private PlanningPendingCommandSharedService commandSharedService;
    @SpyBean
    private UnifiedPlanPostconditionValidator postconditionValidator;
    @MockBean
    private TaskScheduler taskScheduler;

    @DynamicPropertySource
    static void dedicatedDatabase(DynamicPropertyRegistry properties) {
        String url = System.getenv("PLANNING_AUDIT_STACK_DB_URL");
        if (url == null || !url.matches("jdbc:mysql://127\\.0\\.0\\.1:13306/zhiyuan_audit_stack_[a-zA-Z0-9_]+\\?.*")) {
            throw new IllegalStateException("a dedicated local audit stack database is required");
        }
        properties.add("spring.datasource.dynamic.datasource.master.url", () -> url);
        properties.add("spring.datasource.dynamic.datasource.master.username",
                () -> System.getenv("PLANNING_AUDIT_STACK_DB_USER"));
        properties.add("spring.datasource.dynamic.datasource.master.password",
                () -> System.getenv("PLANNING_AUDIT_STACK_DB_PASSWORD"));
        properties.add("spring.flyway.url", () -> url);
        properties.add("spring.flyway.user", () -> System.getenv("PLANNING_AUDIT_STACK_DB_USER"));
        properties.add("spring.flyway.password", () -> System.getenv("PLANNING_AUDIT_STACK_DB_PASSWORD"));
    }

    @BeforeEach
    void verifyIsolation() {
        assertTrue(jdbc.queryForObject("SELECT DATABASE()", String.class).startsWith("zhiyuan_audit_stack_"));
        doCallRealMethod().when(postconditionValidator).validate(any(), any(), any());
    }

    @ParameterizedTest
    @ValueSource(strings = {"major_direct", "major_count", "group_direct", "group_count"})
    @Timeout(30)
    void shouldRollbackRealPlanWritesAndCommitFailureAudit(String fixtureName) throws Exception {
        resetFixture(fixtureName);
        PendingPlanningCommandReq command = prepareAndClaim(fixtureName);
        String before = planningJson();
        int versionBefore = JSONObject.parseObject(before).getIntValue("version");
        AtomicBoolean realWriteObserved = new AtomicBoolean();
        doAnswer(invocation -> {
            String written = planningJson();
            assertNotEquals(before, written);
            assertTrue(JSONObject.parseObject(written).getIntValue("version") > versionBefore);
            realWriteObserved.set(true);
            throw new BusinessException(40905, "review_fix_postcondition_failed: private-plan-sentinel");
        }).when(postconditionValidator).validate(any(), any(), any());

        BusinessException failure = assertThrows(BusinessException.class,
                () -> commandService.execute(TENANT_ID, sessionId, command));

        assertEquals(40905, failure.getStatus());
        assertTrue(realWriteObserved.get(), "failure must occur after a real MyBatis plan write");
        assertEquals(before, planningJson(), "plan bytes and version must roll back");
        PlanningPendingCommandEntity audit = commandSharedService.getByOperationId(command.getOperationId());
        assertNotNull(audit);
        assertEquals("failed", audit.getStatus());
        JSONObject receipt = JSONObject.parseObject(audit.getResultJson());
        assertEquals(3, receipt.size());
        assertEquals(40905, receipt.getIntValue("errorCode"));
        assertEquals("review_fix_postcondition_failed", receipt.getString("reasonCode"));
        PendingConfirmationRes pending = pendingService.getCurrent(TENANT_ID, sessionId);
        assertEquals(command.getPendingId(), pending.getPendingId());
        assertEquals("expired", pending.getStatus());
        assertEquals("40905", pending.getResultCode());
        assertEquals("40905", pendingService.reconcile(TENANT_ID, sessionId).getResultCode());
    }

    @ParameterizedTest
    @ValueSource(strings = {"major_direct", "major_count", "group_direct", "group_count"})
    @Timeout(30)
    void shouldStillCommitAndReplaySuccessfulRealCommands(String fixtureName) throws Exception {
        resetFixture(fixtureName);
        PendingPlanningCommandReq command = prepareAndClaim(fixtureName);
        int versionBefore = JSONObject.parseObject(planningJson()).getIntValue("version");

        com.ytell.zhiyuan.model.dto.planning.PlanChangePostconditionReportDTO report =
                commandService.execute(TENANT_ID, sessionId, command).getPostconditionReport();
        assertTrue(Boolean.TRUE.equals(report.getSatisfied()));
        String after = planningJson();
        assertTrue(JSONObject.parseObject(after).getIntValue("version") > versionBefore);
        assertEquals("succeeded", commandSharedService.getByOperationId(command.getOperationId()).getStatus());
        commandService.execute(TENANT_ID, sessionId, command);
        assertEquals(after, planningJson(), "successful replay must not write the plan again");
    }

    private PendingPlanningCommandReq prepareAndClaim(String fixtureName) {
        FixProposalDTO proposal = planningStateService.previewReviewFixProposals(TENANT_ID, sessionId)
                .getProposals().stream()
                .filter(item -> "ready".equals(item.getStatus())
                        && Boolean.TRUE.equals(item.getRequiresConfirmation())
                        && (fixtureName.endsWith("direct")
                        ? "probability_inversion".equals(item.getFindingCode())
                        : "count_target".equals(item.getFindingCode())))
                .findFirst().orElseThrow(() -> new AssertionError("missing ready review proposal"));
        ReviewFixPrepareReq prepare = new ReviewFixPrepareReq();
        prepare.setProposalId(proposal.getProposalId());
        prepare.setSourceVersionGuard(proposal.getSourceVersion());
        prepare.setCommandDigest(proposal.getCommandDigest());
        prepare.setPreviewDigest(proposal.getPreviewDigest());
        prepare.setEvaluationVersion(proposal.getEvaluationVersion());
        planningStateService.prepareReviewFixProposal(TENANT_ID, sessionId,
                "audit-stack-" + UUID.randomUUID(), "audit-stack-digest", prepare);
        PendingConfirmationRes pending = pendingService.getCurrent(TENANT_ID, sessionId);
        PendingConfirmationResolveReq claim = new PendingConfirmationResolveReq();
        claim.setChatSessionId(sessionId);
        claim.setPendingId(pending.getPendingId());
        claim.setExpectedRevision(pending.getRevision());
        claim.setAction("confirm");
        claim.setClaimToken(UUID.randomUUID().toString());
        PendingConfirmationRes claimed = pendingService.resolve(TENANT_ID, claim);
        assertEquals("applying", claimed.getStatus());
        Map<String, Object> data = claimed.getDataValue();
        FixProposalApplyReq apply = new FixProposalApplyReq();
        apply.setProposalSource(String.valueOf(data.get("proposalSource")));
        apply.setProposalId(String.valueOf(data.get("proposalId")));
        apply.setSourceVersionGuard(proposal.getSourceVersion());
        apply.setCommandDigest(String.valueOf(data.get("commandDigest")));
        apply.setPreviewDigest(String.valueOf(data.get("previewDigest")));
        apply.setEvaluationVersion(String.valueOf(data.get("evaluationVersion")));
        apply.setRegenerateOrderedPlan(true);
        apply.setRerunReview(true);
        PendingPlanningCommandReq command = new PendingPlanningCommandReq();
        command.setPendingId(claimed.getPendingId());
        command.setClaimToken(claim.getClaimToken());
        command.setOperationId(String.valueOf(data.get("operationId")));
        command.setExpectedPlanVersion(proposal.getSourceVersion());
        command.setCommandType(PendingPlanningCommandBizService.APPLY_PLAN_CHANGE_PROPOSAL);
        command.setProposalApply(apply);
        return command;
    }

    private void resetFixture(String fixtureName) throws Exception {
        sessionId = fixtureName.startsWith("group") ? 900045L : 900700L;
        JSONObject fixtures = JSONObject.parseObject(new String(Files.readAllBytes(Paths.get(
                System.getenv("PLANNING_AUDIT_STACK_FIXTURE"))), StandardCharsets.UTF_8));
        JSONObject state = fixtures.getJSONObject(fixtureName);
        assertNotNull(state);
        state.put("sessionId", sessionId);
        for (String table : new String[]{"assistant_chat_session_pending_confirmation",
                "assistant_planning_pending_command", "assistant_conversation_proposal_request"}) {
            jdbc.update("DELETE FROM " + table + " WHERE chat_session_id = ?", sessionId);
        }
        assertEquals(1, jdbc.update("UPDATE assistant_chat_session_extra_data SET data_value = ? "
                + "WHERE chat_session_id = ? AND data_key = 'planningState'", state.toJSONString(), sessionId));
        jdbc.update("UPDATE assistant_chat_session_extra_data SET data_value = ? "
                + "WHERE chat_session_id = ? AND data_key = 'planningCandidatePool'",
                state.getJSONObject("candidatePoolState").toJSONString(), sessionId);
    }

    private String planningJson() {
        return jdbc.queryForObject("SELECT data_value FROM assistant_chat_session_extra_data "
                + "WHERE chat_session_id = ? AND data_key = 'planningState'", String.class, sessionId);
    }
}
