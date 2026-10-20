package com.ytell.zhiyuan.service.biz;

import com.alibaba.fastjson.JSONObject;
import com.ytell.zhiyuan.common.exception.BusinessException;
import com.ytell.zhiyuan.model.dto.planning.FixProposalApplyReq;
import com.ytell.zhiyuan.model.dto.planning.PendingPlanningCommandReq;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import com.ytell.zhiyuan.model.entity.biz.PendingConfirmationEntity;
import com.ytell.zhiyuan.model.entity.biz.PlanningPendingCommandEntity;
import com.ytell.zhiyuan.service.shared.ChatSessionExtraDataSharedService;
import com.ytell.zhiyuan.service.shared.PendingConfirmationSharedService;
import com.ytell.zhiyuan.service.shared.PlanningPendingCommandSharedService;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.Timeout;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.aop.framework.ProxyFactory;
import org.springframework.jdbc.core.BeanPropertyRowMapper;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.transaction.annotation.AnnotationTransactionAttributeSource;
import org.springframework.transaction.interceptor.TransactionInterceptor;

import java.util.Date;
import java.util.List;
import java.util.Properties;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

@EnabledIfEnvironmentVariable(named = "PLANNING_AUDIT_TEST_DB_URL", matches = ".+")
@Timeout(15)
class PlanningCommandFailureTransactionIntegrationTest {
    private JdbcTemplate jdbc;
    private PendingPlanningCommandBizService executor;
    private PendingConfirmationSharedService pendings;
    private PlanningStateService planning;
    private PendingPlanningCommandReq request;
    private String originalFlag;

    @BeforeEach
    void setUp() {
        String url = System.getenv("PLANNING_AUDIT_TEST_DB_URL");
        assertTrue(url.matches("jdbc:mysql://127\\.0\\.0\\.1:13306/zhiyuan_audit_test_[a-zA-Z0-9_]+(?:\\?.*)?"));
        DriverManagerDataSource dataSource = new DriverManagerDataSource(url,
                System.getenv("PLANNING_AUDIT_TEST_DB_USER"), System.getenv("PLANNING_AUDIT_TEST_DB_PASSWORD"));
        Properties connectionProperties = new Properties();
        connectionProperties.setProperty("sessionVariables", "innodb_lock_wait_timeout=3");
        dataSource.setConnectionProperties(connectionProperties);
        jdbc = new JdbcTemplate(dataSource);
        createFixtures();
        originalFlag = System.getProperty(ReviewFixCommandFlags.PROPERTY);
        System.setProperty(ReviewFixCommandFlags.PROPERTY, "true");
        PlanningPendingCommandSharedService commands = mock(PlanningPendingCommandSharedService.class);
        pendings = mock(PendingConfirmationSharedService.class);
        planning = mock(PlanningStateService.class);
        ChatSessionExtraDataSharedService extraData = mock(ChatSessionExtraDataSharedService.class);
        when(commands.getByOperationId(anyString())).thenAnswer(invocation -> {
            String operationId = invocation.getArgument(0);
            List<PlanningPendingCommandEntity> rows = jdbc.query(
                    "SELECT * FROM assistant_planning_pending_command WHERE operation_id=?",
                    BeanPropertyRowMapper.newInstance(PlanningPendingCommandEntity.class), operationId);
            return rows.isEmpty() ? null : rows.get(0);
        });
        when(commands.save(any(PlanningPendingCommandEntity.class))).thenAnswer(invocation -> {
            PlanningPendingCommandEntity record = invocation.getArgument(0);
            return jdbc.update("INSERT INTO assistant_planning_pending_command "
                            + "(tenant_id,chat_session_id,pending_id,operation_id,command_type,expected_plan_version,request_digest,status,result_json) "
                            + "VALUES (?,?,?,?,?,?,?,?,?)", record.getTenantId(), record.getChatSessionId(), record.getPendingId(),
                    record.getOperationId(), record.getCommandType(), record.getExpectedPlanVersion(),
                    record.getRequestDigest(), record.getStatus(), record.getResultJson()) == 1;
        });
        when(pendings.lockCurrent(1L, 101L)).thenAnswer(invocation -> jdbc.queryForObject(
                "SELECT * FROM assistant_chat_session_pending_confirmation WHERE tenant_id=1 AND chat_session_id=101 FOR UPDATE",
                BeanPropertyRowMapper.newInstance(PendingConfirmationEntity.class)));
        when(pendings.compareAndSet(any(), anyLong(), anyString(), anyString())).thenAnswer(invocation -> {
            PendingConfirmationEntity next = invocation.getArgument(0);
            return jdbc.update("UPDATE assistant_chat_session_pending_confirmation SET status=?,revision=?,"
                            + "claim_expires_at=?,result_code=?,resolved_action=?,data_value=? "
                            + "WHERE tenant_id=? AND chat_session_id=? AND revision=? AND pending_id=? AND status=?",
                    next.getStatus(), next.getRevision(), next.getClaimExpiresAt(), next.getResultCode(),
                    next.getResolvedAction(), next.getDataValue(), next.getTenantId(), next.getChatSessionId(),
                    invocation.getArgument(1), invocation.getArgument(2), invocation.getArgument(3)) == 1;
        });
        when(extraData.lockBySessionIdAndDataKey(anyLong(), anyString())).thenAnswer(invocation -> {
            jdbc.queryForObject("SELECT version FROM planning_audit_test_state WHERE session_id=101 FOR UPDATE", Integer.class);
            return null;
        });
        when(planning.loadPlanningStateReadOnly(101L)).thenAnswer(invocation -> {
            PlanningStateDTO state = new PlanningStateDTO();
            state.setVersion(jdbc.queryForObject("SELECT version FROM planning_audit_test_state WHERE session_id=101", Integer.class));
            return state;
        });
        doAnswer(invocation -> {
            jdbc.update("UPDATE planning_audit_test_state SET version=13 WHERE session_id=101");
            throw new BusinessException(40905, "review_fix_postcondition_failed");
        }).when(planning).applyClaimedReviewFixProposal(eq(1L), eq(101L), any());
        DataSourceTransactionManager transactionManager = new DataSourceTransactionManager(dataSource);
        PlanningCommandFailureWriter writer = new PlanningCommandFailureWriter();
        ReflectionTestUtils.setField(writer, "commandSharedService", commands);
        ReflectionTestUtils.setField(writer, "pendingSharedService", pendings);
        PendingPlanningCommandBizService target = new PendingPlanningCommandBizService();
        ReflectionTestUtils.setField(target, "commandSharedService", commands);
        ReflectionTestUtils.setField(target, "pendingSharedService", pendings);
        ReflectionTestUtils.setField(target, "extraDataSharedService", extraData);
        ReflectionTestUtils.setField(target, "planningStateService", planning);
        ReflectionTestUtils.setField(target, "failureWriter", transactionalProxy(writer, transactionManager));
        executor = (PendingPlanningCommandBizService) transactionalProxy(target, transactionManager);
        request = request();
    }

    @AfterEach
    void restoreFlag() {
        if (originalFlag == null) System.clearProperty(ReviewFixCommandFlags.PROPERTY);
        else System.setProperty(ReviewFixCommandFlags.PROPERTY, originalFlag);
    }

    @Test
    void shouldRollbackPlanButCommitFailedCommandAndPendingInANewTransaction() {
        BusinessException failure = assertThrows(BusinessException.class, () -> executor.execute(1L, 101L, request));

        assertEquals(40905, failure.getStatus());
        assertEquals(12, jdbc.queryForObject("SELECT version FROM planning_audit_test_state WHERE session_id=101", Integer.class));
        assertFailedReceipt(40905);
        assertEquals("expired", jdbc.queryForObject("SELECT status FROM assistant_chat_session_pending_confirmation", String.class));
        assertEquals(4L, jdbc.queryForObject("SELECT revision FROM assistant_chat_session_pending_confirmation", Long.class));
        assertEquals("40905", jdbc.queryForObject("SELECT result_code FROM assistant_chat_session_pending_confirmation", String.class));
    }

    @Test
    void shouldRollbackAuditInsertIfPendingWriteFailsWithoutMaskingOriginalFailure() {
        doThrow(new IllegalStateException("audit pending write unavailable"))
                .when(pendings).compareAndSet(any(), anyLong(), anyString(), anyString());

        BusinessException failure = assertThrows(BusinessException.class, () -> executor.execute(1L, 101L, request));

        assertEquals(40905, failure.getStatus());
        assertEquals(12, jdbc.queryForObject("SELECT version FROM planning_audit_test_state WHERE session_id=101", Integer.class));
        assertEquals(0, jdbc.queryForObject("SELECT COUNT(*) FROM assistant_planning_pending_command", Integer.class));
        assertEquals("applying", jdbc.queryForObject("SELECT status FROM assistant_chat_session_pending_confirmation", String.class));
    }

    @Test
    void shouldAuditPreExecutionVersionConflictWithoutChangingThePlan() {
        jdbc.update("UPDATE planning_audit_test_state SET version=13 WHERE session_id=101");

        BusinessException failure = assertThrows(BusinessException.class, () -> executor.execute(1L, 101L, request));

        assertEquals(40904, failure.getStatus());
        assertEquals(13, jdbc.queryForObject("SELECT version FROM planning_audit_test_state WHERE session_id=101", Integer.class));
        assertFailedReceipt(40904);
    }

    @Test
    void shouldAuditUnexpectedFailureWithoutStoringExceptionContents() {
        doAnswer(invocation -> {
            jdbc.update("UPDATE planning_audit_test_state SET version=13 WHERE session_id=101");
            throw new IllegalStateException("private plan and credentials");
        }).when(planning).applyClaimedReviewFixProposal(eq(1L), eq(101L), any());

        assertThrows(IllegalStateException.class, () -> executor.execute(1L, 101L, request));

        assertEquals(12, jdbc.queryForObject("SELECT version FROM planning_audit_test_state WHERE session_id=101", Integer.class));
        assertFailedReceipt(500);
        assertFalse(jdbc.queryForObject("SELECT result_json FROM assistant_planning_pending_command", String.class).contains("private"));
    }

    private Object transactionalProxy(Object target, DataSourceTransactionManager manager) {
        ProxyFactory factory = new ProxyFactory(target);
        factory.setProxyTargetClass(true);
        factory.addAdvice(new TransactionInterceptor(manager, new AnnotationTransactionAttributeSource()));
        return factory.getProxy();
    }

    private void assertFailedReceipt(int errorCode) {
        assertEquals("failed", jdbc.queryForObject("SELECT status FROM assistant_planning_pending_command", String.class));
        JSONObject receipt = JSONObject.parseObject(jdbc.queryForObject("SELECT result_json FROM assistant_planning_pending_command", String.class));
        assertEquals(errorCode, receipt.getIntValue("errorCode"));
    }

    private PendingPlanningCommandReq request() {
        PendingPlanningCommandReq value = new PendingPlanningCommandReq();
        value.setOperationId("review-operation");
        value.setPendingId("review-pending");
        value.setClaimToken("review-claim");
        value.setExpectedPlanVersion(12);
        value.setCommandType(PendingPlanningCommandBizService.APPLY_PLAN_CHANGE_PROPOSAL);
        FixProposalApplyReq apply = new FixProposalApplyReq();
        apply.setProposalId("review-proposal");
        apply.setSourceVersionGuard(12);
        apply.setCommandDigest("command-digest");
        apply.setPreviewDigest("preview-digest");
        apply.setEvaluationVersion("evaluation-version");
        value.setProposalApply(apply);
        return value;
    }

    private void createFixtures() {
        jdbc.execute("CREATE TABLE IF NOT EXISTS assistant_planning_pending_command (id BIGINT AUTO_INCREMENT PRIMARY KEY,"
                + "tenant_id BIGINT,chat_session_id BIGINT,pending_id VARCHAR(64),operation_id VARCHAR(64) UNIQUE,"
                + "command_type VARCHAR(64),expected_plan_version INT,request_digest VARCHAR(64),status VARCHAR(32),result_json LONGTEXT) ENGINE=InnoDB");
        jdbc.execute("CREATE TABLE IF NOT EXISTS assistant_chat_session_pending_confirmation (id BIGINT AUTO_INCREMENT PRIMARY KEY,"
                + "tenant_id BIGINT,chat_session_id BIGINT UNIQUE,pending_id VARCHAR(64),revision BIGINT,status VARCHAR(32),"
                + "claim_token VARCHAR(64),claim_expires_at DATETIME,result_code VARCHAR(64),resolved_action VARCHAR(32),data_value LONGTEXT) ENGINE=InnoDB");
        jdbc.execute("CREATE TABLE IF NOT EXISTS planning_audit_test_state (session_id BIGINT PRIMARY KEY,version INT) ENGINE=InnoDB");
        jdbc.update("DELETE FROM assistant_planning_pending_command WHERE chat_session_id=101");
        jdbc.update("DELETE FROM assistant_chat_session_pending_confirmation WHERE chat_session_id=101");
        jdbc.update("DELETE FROM planning_audit_test_state WHERE session_id=101");
        jdbc.update("INSERT INTO planning_audit_test_state VALUES (101,12)");
        JSONObject payload = new JSONObject(true);
        payload.put("operationId", "review-operation");
        payload.put("proposalId", "review-proposal");
        payload.put("proposalSource", "review_check");
        payload.put("sourceVersion", 12);
        payload.put("commandDigest", "command-digest");
        payload.put("previewDigest", "preview-digest");
        payload.put("evaluationVersion", "evaluation-version");
        jdbc.update("INSERT INTO assistant_chat_session_pending_confirmation "
                        + "(tenant_id,chat_session_id,pending_id,revision,status,claim_token,claim_expires_at,data_value) VALUES (1,101,?,3,'applying',?,?,?)",
                "review-pending", "review-claim", new Date(System.currentTimeMillis() + 120_000L), payload.toJSONString());
    }
}
