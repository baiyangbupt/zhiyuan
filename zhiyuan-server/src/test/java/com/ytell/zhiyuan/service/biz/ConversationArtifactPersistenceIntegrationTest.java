package com.ytell.zhiyuan.service.biz;

import com.ytell.zhiyuan.Application;
import com.ytell.zhiyuan.common.exception.BusinessException;
import com.ytell.zhiyuan.model.dto.planning.ArtifactDTO;
import com.ytell.zhiyuan.model.entity.biz.ConversationProposalRequestEntity;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;

import javax.sql.DataSource;
import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.Statement;
import java.util.ArrayList;
import java.util.Calendar;
import java.util.Date;
import java.util.List;
import java.util.UUID;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 产物与 prepare 记录的**真库**证据。
 *
 * <p>为什么必须有这一层：mock/假表能证明分支走对了，证明不了"SQL 的 where 真的
 * 过滤掉了跨租户"，也证明不了"重启之后数据还在"——而这两件事正是把它们落库的
 * 全部理由。缺配置时整类 skip，**不记为通过**。
 *
 * <p>运行方式（隔离库）：
 * <pre>
 *   CONVERSATION_TEST_DB_URL=jdbc:mysql://127.0.0.1:13306/zhiyuan_codex_local?...
 *   CONVERSATION_TEST_DB_USER=root
 *   CONVERSATION_TEST_DB_PASSWORD=...
 *   mvn -o -Dtest=ConversationArtifactPersistenceIntegrationTest test
 * </pre>
 */
@SpringBootTest(classes = Application.class)
@ActiveProfiles("local")
@EnabledIfEnvironmentVariable(named = "CONVERSATION_TEST_DB_URL", matches = ".+")
class ConversationArtifactPersistenceIntegrationTest {

    @Autowired
    private ConversationArtifactService artifactService;

    @Autowired
    private ConversationProposalRequestService requestService;

    @Autowired
    private DataSource dataSource;

    /** 每次跑用独立租户/会话，测试之间不共享状态，也不依赖清库。 */
    private final long tenantId = 900000L + (System.nanoTime() % 100000L);
    private final long sessionId = 800000L + (System.nanoTime() % 100000L);
    private final long otherSessionId = sessionId + 1;

    private final List<String> createdArtifacts = new ArrayList<>();
    private final List<String> createdRequests = new ArrayList<>();

    @DynamicPropertySource
    static void isolatedDatasource(DynamicPropertyRegistry registry) {
        // 用 @DynamicPropertySource 而不是改 application-local.yml：
        // 那会把测试库指到共享实例上，而"隔离"是这一层的全部前提。
        registry.add("spring.datasource.dynamic.datasource.master.url", () -> env("CONVERSATION_TEST_DB_URL"));
        registry.add("spring.datasource.dynamic.datasource.master.username", () -> env("CONVERSATION_TEST_DB_USER"));
        registry.add("spring.datasource.dynamic.datasource.master.password", () -> env("CONVERSATION_TEST_DB_PASSWORD"));
        registry.add("spring.flyway.url", () -> env("CONVERSATION_TEST_DB_URL"));
        registry.add("spring.flyway.user", () -> env("CONVERSATION_TEST_DB_USER"));
        registry.add("spring.flyway.password", () -> env("CONVERSATION_TEST_DB_PASSWORD"));
    }

    @AfterEach
    void cleanUp() throws Exception {
        // 只删本次 runId 造的数据，不动库里别的东西。
        try (Connection connection = dataSource.getConnection()) {
            for (String artifactId : createdArtifacts) {
                try (PreparedStatement statement = connection.prepareStatement(
                        "DELETE FROM assistant_conversation_artifact WHERE artifact_id = ?")) {
                    statement.setString(1, artifactId);
                    statement.executeUpdate();
                }
            }
            for (String requestId : createdRequests) {
                try (PreparedStatement statement = connection.prepareStatement(
                        "DELETE FROM assistant_conversation_proposal_request WHERE request_id = ?")) {
                    statement.setString(1, requestId);
                    statement.executeUpdate();
                }
            }
        }
    }

    @Test
    void migrationsCreatedTheTables() throws Exception {
        // 这一条同时把"迁移真的能建表"钉住了：编译通过 ≠ 建得起来。
        assertTrue(tableExists("assistant_conversation_artifact"), "V16 没有建出产物表");
        assertTrue(tableExists("assistant_conversation_proposal_request"), "V17 没有建出 prepare 记录表");
    }

    @Test
    void artifactSurvivesAnIndependentConnection() throws Exception {
        String artifactId = artifactService.put(tenantId, sessionId, "candidate",
                payload("school-1"), null, tomorrow());
        createdArtifacts.add(artifactId);

        // 换一条**独立 JDBC 连接**去读：证明数据在库里，而不是在 ORM 会话缓存里。
        // 这是"重启后还能读到"能做到的最接近的验证。
        try (Connection connection = dataSource.getConnection();
             PreparedStatement statement = connection.prepareStatement(
                     "SELECT payload_digest, payload_json FROM assistant_conversation_artifact WHERE artifact_id = ?")) {
            statement.setString(1, artifactId);
            try (ResultSet resultSet = statement.executeQuery()) {
                assertTrue(resultSet.next(), "产物没有落库");
                assertEquals(ConversationArtifactService.digest(resultSet.getString("payload_json")),
                        resultSet.getString("payload_digest"));
            }
        }
    }

    @Test
    void anotherTenantCannotReadTheArtifact() {
        String artifactId = artifactService.put(tenantId, sessionId, "candidate",
                payload("school-1"), null, tomorrow());
        createdArtifacts.add(artifactId);

        BusinessException crossTenant = assertThrows(BusinessException.class,
                () -> artifactService.getOwned(tenantId + 777, sessionId, artifactId));
        BusinessException crossSession = assertThrows(BusinessException.class,
                () -> artifactService.getOwned(tenantId, otherSessionId, artifactId));

        // 这条只有在**真 SQL**上才有意义：mock 里 where 根本不会被执行。
        assertEquals(404, crossTenant.getStatus());
        assertEquals(404, crossSession.getStatus());
    }

    @Test
    void expiredRowIsRefusedOnARealRow() throws Exception {
        String artifactId = artifactService.put(tenantId, sessionId, "candidate",
                payload("school-1"), null, tomorrow());
        createdArtifacts.add(artifactId);

        // 直接把过期时间改到过去：验证读取路径真的看了这一列。
        try (Connection connection = dataSource.getConnection();
             PreparedStatement statement = connection.prepareStatement(
                     "UPDATE assistant_conversation_artifact SET expires_at = ? WHERE artifact_id = ?")) {
            statement.setTimestamp(1, new java.sql.Timestamp(System.currentTimeMillis() - 60_000));
            statement.setString(2, artifactId);
            statement.executeUpdate();
        }

        assertEquals(410, assertThrows(BusinessException.class,
                () -> artifactService.getOwned(tenantId, sessionId, artifactId)).getStatus());
    }

    @Test
    void tamperedRowIsRefusedOnARealRow() throws Exception {
        String artifactId = artifactService.put(tenantId, sessionId, "candidate",
                payload("school-1"), null, tomorrow());
        createdArtifacts.add(artifactId);

        try (Connection connection = dataSource.getConnection();
             PreparedStatement statement = connection.prepareStatement(
                     "UPDATE assistant_conversation_artifact SET payload_json = ? WHERE artifact_id = ?")) {
            statement.setString(1, "{\"items\":[],\"injected\":true}");
            statement.setString(2, artifactId);
            statement.executeUpdate();
        }

        BusinessException ex = assertThrows(BusinessException.class,
                () -> artifactService.getOwned(tenantId, sessionId, artifactId));
        assertEquals("artifact_digest_mismatch", ex.getMessage());
    }

    @Test
    void duplicatePrepareRequestIsRejectedByTheUniqueKeyNotByApplicationCode() throws Exception {
        String requestId = "req-" + UUID.randomUUID();
        createdRequests.add(requestId);

        ConversationProposalRequestService.PrepareOutcome outcome =
                new ConversationProposalRequestService.PrepareOutcome("pending-1", "op-1", "{}");
        requestService.prepareOnce(tenantId, sessionId, requestId, "digest-1", null, () -> outcome);

        // 绕过服务直接插一条同 key 的记录：如果唯一键没建出来，这条会成功，
        // 而并发防线就只剩应用代码——那正是它防不住的东西。
        try (Connection connection = dataSource.getConnection();
             PreparedStatement statement = connection.prepareStatement(
                     "INSERT INTO assistant_conversation_proposal_request "
                             + "(tenant_id, chat_session_id, request_id, request_digest, status) VALUES (?, ?, ?, ?, ?)")) {
            statement.setLong(1, tenantId);
            statement.setLong(2, sessionId);
            statement.setString(3, requestId);
            statement.setString(4, "digest-2");
            statement.setString(5, "prepared");
            assertThrows(java.sql.SQLIntegrityConstraintViolationException.class,
                    statement::executeUpdate);
        }
    }

    @Test
    void retryingPrepareOnTheRealTableReturnsTheOriginalRow() {
        String requestId = "req-" + UUID.randomUUID();
        createdRequests.add(requestId);
        ConversationProposalRequestService.PrepareOutcome outcome =
                new ConversationProposalRequestService.PrepareOutcome("pending-9", "op-9", "{\"v\":1}");

        requestService.prepareOnce(tenantId, sessionId, requestId, "digest-9", null, () -> outcome);
        com.ytell.zhiyuan.model.dto.planning.PrepareResultDTO retry = requestService.prepareOnce(tenantId, sessionId, requestId, "digest-9", null, () -> {
            throw new AssertionError("真表上重发也不该重新执行 prepareWork");
        });

        assertEquals("prepared", retry.getStatus());
        assertEquals("op-9", retry.getOperationId());

        ConversationProposalRequestEntity row = requestService.find(tenantId, sessionId, requestId);
        assertNotNull(row);
        assertEquals("pending-9", row.getPendingId());
    }

    private boolean tableExists(String tableName) throws Exception {
        try (Connection connection = dataSource.getConnection();
             Statement statement = connection.createStatement();
             ResultSet resultSet = statement.executeQuery(
                     "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = DATABASE()"
                             + " AND table_name = '" + tableName + "'")) {
            return resultSet.next() && resultSet.getInt(1) > 0;
        }
    }

    private static com.alibaba.fastjson.JSONObject payload(String schoolId) {
        com.alibaba.fastjson.JSONArray items = new com.alibaba.fastjson.JSONArray();
        com.alibaba.fastjson.JSONObject item = new com.alibaba.fastjson.JSONObject();
        item.put("schoolId", schoolId);
        items.add(item);
        com.alibaba.fastjson.JSONObject payload = new com.alibaba.fastjson.JSONObject();
        payload.put("items", items);
        return payload;
    }

    private static Date tomorrow() {
        Calendar calendar = Calendar.getInstance();
        calendar.add(Calendar.DAY_OF_MONTH, 1);
        return calendar.getTime();
    }

    private static String env(String name) {
        String value = System.getenv(name);
        if (value == null || value.isEmpty()) {
            throw new IllegalStateException(name + " is not set");
        }
        return value;
    }
}
