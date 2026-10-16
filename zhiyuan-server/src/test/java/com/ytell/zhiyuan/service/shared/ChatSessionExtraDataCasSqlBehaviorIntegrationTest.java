package com.ytell.zhiyuan.service.shared;

import com.ytell.zhiyuan.Application;
import com.ytell.zhiyuan.model.entity.biz.ChatSessionExtraData;
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
import java.util.UUID;
import java.util.concurrent.Callable;
import java.util.concurrent.CyclicBarrier;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * CAS（{@code updateDataValueIfUnchanged}）的**SQL 级行为**真库证据
 * （2026-10-07 独立审查 D1，随 H2 专线补）。
 *
 * <p>为什么非真库不可：CAS 的判据全在 SQL 里——{@code NULL} 的 {@code IS NULL} 分支、
 * 以及（2026-10-16 治本批起）{@code LENGTH(data_value)=? AND MD5(data_value)=?} 的**字节级摘要**
 * 与 Java 侧 UTF-8 编码是否逐字节一致（中文 3 字节、emoji 4 字节、NO PAD）。
 * mock / 假表只能证明"我们拼了这个 where"，证明不了 MySQL 真按这个口径比对；
 * 而 d098da8 把整个读路径的"不覆盖并发写"押在这条 SQL 上——比较口径错了就是静默丢写，
 * 摘要不一致则是所有写静默全输。</p>
 *
 * <p>最后两条是**写路径的钉子**：⑧ 原先是"无条件 updateById 会让后写者整文档覆盖"的现状钉，
 * H2 落地后已**翻转**为"CAS 挡住第二个写者 / 重读合并后两者都在"（不删，保留翻转痕迹），
 * 让"修复确实改变了 SQL 级行为"有据可查。</p>
 *
 * <p>运行方式（隔离库 {@code zhiyuan_codex_local} @ 127.0.0.1:13306，不碰演示库）：
 * <pre>
 *   CONVERSATION_TEST_DB_URL='jdbc:mysql://127.0.0.1:13306/zhiyuan_codex_local?...' \
 *   CONVERSATION_TEST_DB_USER=root CONVERSATION_TEST_DB_PASSWORD=... \
 *   mvn -o -Dtest=ChatSessionExtraDataCasSqlBehaviorIntegrationTest test \
 *       -DargLine="-Xmx1400m -XX:MaxMetaspaceSize=320m"
 * </pre>
 * 缺配置整类 skip，**不记为通过**。{@code -DargLine} 是本机实测需要：这台机器同时跑着
 * 演示栈/codex-local 栈（java 1.7G + mysqld 1.7G + 两个 next-router 2.7G），不压堆上限时
 * Spring 上下文启动就被 OOM killer 杀了（dmesg 有记录，表现是 surefire "forked VM terminated
 * without properly saying goodbye"），不是测试失败。</p>
 */
@SpringBootTest(classes = Application.class)
@ActiveProfiles("local")
@EnabledIfEnvironmentVariable(named = "CONVERSATION_TEST_DB_URL", matches = ".+")
class ChatSessionExtraDataCasSqlBehaviorIntegrationTest {

    @Autowired
    private ChatSessionExtraDataSharedService sharedService;

    @Autowired
    private DataSource dataSource;

    /** 每次跑用独立会话号/键：测试之间不共享状态，也不依赖清库。 */
    private final long sessionId = 999000000L + (System.nanoTime() % 1000000L);
    private final long otherSessionId = sessionId + 1;
    private final String dataKey = "cas_probe_" + UUID.randomUUID().toString().replace("-", "");

    @DynamicPropertySource
    static void isolatedDatasource(DynamicPropertyRegistry registry) {
        registry.add("spring.datasource.dynamic.datasource.master.url", () -> env("CONVERSATION_TEST_DB_URL"));
        registry.add("spring.datasource.dynamic.datasource.master.username", () -> env("CONVERSATION_TEST_DB_USER"));
        registry.add("spring.datasource.dynamic.datasource.master.password", () -> env("CONVERSATION_TEST_DB_PASSWORD"));
        registry.add("spring.flyway.url", () -> env("CONVERSATION_TEST_DB_URL"));
        registry.add("spring.flyway.user", () -> env("CONVERSATION_TEST_DB_USER"));
        registry.add("spring.flyway.password", () -> env("CONVERSATION_TEST_DB_PASSWORD"));
    }

    @AfterEach
    void cleanUp() throws Exception {
        try (Connection connection = dataSource.getConnection();
             PreparedStatement statement = connection.prepareStatement(
                     "DELETE FROM assistant_chat_session_extra_data WHERE chat_session_id IN (?, ?)")) {
            statement.setLong(1, sessionId);
            statement.setLong(2, otherSessionId);
            statement.executeUpdate();
        }
    }

    // ① 行还停在读到的值上 → CAS 赢，且只看自己那一行。
    @Test
    void casWinsWhenTheRowStillHoldsTheValueWeRead() throws Exception {
        insertRow(sessionId, dataKey, "{\"phase\":\"candidate_generated\"}");
        String sameKeyOtherSession = "{\"phase\":\"untouched\"}";
        insertRow(otherSessionId, dataKey, sameKeyOtherSession);

        ChatSessionExtraData row = readRow(sessionId, dataKey);
        boolean won = sharedService.updateDataValueIfUnchanged(row, row.getDataValue(), "{\"phase\":\"ordered\"}");

        assertTrue(won, "行没被并发改过，CAS 必须赢");
        assertEquals("{\"phase\":\"ordered\"}", readValue(sessionId, dataKey));
        assertEquals(sameKeyOtherSession, readValue(otherSessionId, dataKey),
                "CAS 的 where 带 chat_session_id/data_key/data_version：别的会话同键行一个字不许动");
    }

    // ② 别人先写了 → CAS 输，且**不许**把对方的写覆盖掉（读路径"不覆盖并发写"的全部理由）。
    @Test
    void casLosesWhenAnotherWriterChangedTheRowFirst() throws Exception {
        insertRow(sessionId, dataKey, "{\"phase\":\"candidate_generated\"}");
        ChatSessionExtraData staleSnapshot = readRow(sessionId, dataKey);

        // 并发写者（如页面自举）先落盘。
        ChatSessionExtraData live = readRow(sessionId, dataKey);
        assertTrue(sharedService.updateDataValueIfUnchanged(live, live.getDataValue(), "{\"phase\":\"ordered\"}"));

        boolean won = sharedService.updateDataValueIfUnchanged(
                staleSnapshot, staleSnapshot.getDataValue(), "{\"phase\":\"stale_overwrite\"}");

        assertFalse(won, "读到的快照已经不是库里的那份，CAS 必须输");
        assertEquals("{\"phase\":\"ordered\"}", readValue(sessionId, dataKey),
                "输的一方不落盘：并发写的成果必须原样在库里");
    }

    // ③ NULL 走 IS NULL 分支：只对"空壳行"成立，且空壳补值之后第二次 CAS 要输。
    @Test
    void casWithNullExpectationMatchesOnlyTheNullRow() throws Exception {
        insertRow(sessionId, dataKey, null);
        ChatSessionExtraData emptyRow = readRow(sessionId, dataKey);

        assertTrue(sharedService.updateDataValueIfUnchanged(emptyRow, null, "{\"phase\":\"imported\"}"),
                "读到的是 NULL 且库里仍是 NULL → 补值赢");
        assertEquals("{\"phase\":\"imported\"}", readValue(sessionId, dataKey));

        assertFalse(sharedService.updateDataValueIfUnchanged(emptyRow, null, "{\"phase\":\"reimported\"}"),
                "库里已有值，NULL 期望值不许再匹配（否则空壳补值会变成整文档覆盖）");

        // 反向：期望非 NULL、库里是 NULL → 输。
        insertRow(otherSessionId, dataKey, null);
        ChatSessionExtraData nonNullExpectation = readRow(otherSessionId, dataKey);
        assertFalse(sharedService.updateDataValueIfUnchanged(nonNullExpectation, "{\"phase\":\"x\"}", "{\"phase\":\"y\"}"),
                "库里是 NULL、期望非 NULL → 不匹配（IS NULL 与 = 是两条互斥分支）");
        assertEquals(null, readValue(otherSessionId, dataKey));
    }

    // ④ 原样重写（new == expected）：钉住驱动层的"匹配行数"口径，幂等写不该被当成冲突。
    @Test
    void casTreatsAnIdenticalRewriteAsAWin() throws Exception {
        String value = "{\"phase\":\"ordered\",\"version\":3}";
        insertRow(sessionId, dataKey, value);
        ChatSessionExtraData row = readRow(sessionId, dataKey);

        boolean won = sharedService.updateDataValueIfUnchanged(row, row.getDataValue(), value);

        // MySQL Connector/J 默认 useAffectedRows=false（带 CLIENT_FOUND_ROWS）：
        // UPDATE 的 updateCount 是"匹配行数"，值没变也算赢。幂等补写因此不会误报冲突；
        // 代价是 CAS 的 true 只说明"值还是我们读到的"，不说明"行被改动过"。
        assertTrue(won, "同值重写按匹配行数算赢（useAffectedRows=false 的实测口径）");
        assertEquals(value, readValue(sessionId, dataKey));
    }

    // ⑤ 口径钉子（2026-10-16 治本批收紧）：CAS 判据从整值 `data_value = ?`（列 collation
    //    utf8mb4_0900_ai_ci，大小写不敏感：只差大小写的并发改动会误判成"没变过"）改为
    //    LENGTH+MD5 **字节级摘要**——大小写差异现在必须算"变过"，旧快照输。
    //    历史痕迹：本用例旧断言是 assertTrue（ci 口径下旧快照能覆盖），随摘要比较一并更正。
    @Test
    void casComparisonIsByteExactSoLetterCaseOnlyChangeIsDetected() throws Exception {
        insertRow(sessionId, dataKey, "{\"prepareType\":\"PREDICT\"}");
        ChatSessionExtraData staleSnapshot = readRow(sessionId, dataKey);

        // 并发写者只改了大小写。
        ChatSessionExtraData live = readRow(sessionId, dataKey);
        assertTrue(sharedService.updateDataValueIfUnchanged(live, live.getDataValue(), "{\"prepareType\":\"predict\"}"));

        boolean won = sharedService.updateDataValueIfUnchanged(
                staleSnapshot, staleSnapshot.getDataValue(), "{\"prepareType\":\"PREDICT\",\"stale\":true}");

        assertFalse(won, "字节级摘要：diff 只差大小写也是'变过'，旧快照必须输（旧 = ? 口径下是误判赢）");
        assertEquals("{\"prepareType\":\"predict\"}", readValue(sessionId, dataKey),
                "并发写者的大小写改动原样在库里，旧快照一个字都没写进去");
    }

    // ⑨ 摘要一致性钉子（治本批的地基，2026-10-16）：CAS 的判据是"列字节的 LENGTH/MD5"，
    //    Java 侧按 UTF-8 编码算摘要——两边必须逐字节一致，否则所有写都会"摘要不符"静默输掉。
    //    用生产同款 JDBC 连接写一条含中文 + emoji 的行，直库取 LENGTH/MD5 与 Java 侧对拍。
    @Test
    void javaSideDigestMatchesMySqlLengthAndMd5ForMultibyteValues() throws Exception {
        String value = "{\"city\":\"杭州\",\"note\":\"选科化学🚀\",\"quoted\":\"a\\/b\"}";
        insertRow(sessionId, dataKey, value);

        byte[] utf8 = value.getBytes(java.nio.charset.StandardCharsets.UTF_8);

        try (Connection connection = dataSource.getConnection();
             PreparedStatement statement = connection.prepareStatement(
                     "SELECT LENGTH(data_value) AS len, MD5(data_value) AS md5 FROM assistant_chat_session_extra_data"
                             + " WHERE chat_session_id = ? AND data_key = ?")) {
            statement.setLong(1, sessionId);
            statement.setString(2, dataKey);
            try (ResultSet resultSet = statement.executeQuery()) {
                assertTrue(resultSet.next());
                assertEquals(utf8.length, resultSet.getInt("len"),
                        "LENGTH(列) 必须等于 Java UTF-8 字节数（中文 3 字节、emoji 4 字节）");
                assertEquals(md5Hex(utf8), resultSet.getString("md5"),
                        "MD5(列) 必须等于 Java UTF-8 摘要——摘要不符会让 CAS 静默全输");
            }
        }

        // 摘要对拍一致之后，CAS 行为必须照常：赢一次，然后同一旧快照输。
        ChatSessionExtraData row = readRow(sessionId, dataKey);
        assertTrue(sharedService.updateDataValueIfUnchanged(row, value, "{\"city\":\"宁波\"}"),
                "摘要口径一致：值还是我们读到的那份 → CAS 赢");
        assertFalse(sharedService.updateDataValueIfUnchanged(row, value, "{\"city\":\"上海\"}"),
                "行已经是新值：旧摘要不许再匹配");
    }

    // ⑩ 大值钉子：38.4MB 现场的形状（MB 级值）。CAS 走摘要比较（WHERE 侧参数 ~36B），
    //    写入照旧成功；行变了之后旧快照照旧输。
    @Test
    void casStillWinsForMultiMegabyteValues() throws Exception {
        StringBuilder big = new StringBuilder(4 * 1024 * 1024);
        big.append("{\"items\":[");
        for (int i = 0; big.length() < 4 * 1024 * 1024; i++) {
            if (i > 0) {
                big.append(',');
            }
            big.append("{\"volunteerId\":\"v").append(i).append("\",\"school\":\"浙江大学-").append(i).append("\"}");
        }
        big.append("]}");
        String value = big.toString();
        insertRow(sessionId, dataKey, value);

        ChatSessionExtraData row = readRow(sessionId, dataKey);
        String newValue = value.substring(0, value.length() - 2) + ",\"phase\":\"ordered\"}]}";
        assertTrue(sharedService.updateDataValueIfUnchanged(row, value, newValue), "MB 级值 CAS 必须赢");
        assertEquals(newValue, readValue(sessionId, dataKey));
        assertFalse(sharedService.updateDataValueIfUnchanged(row, value, "{\"phase\":\"stale\"}"),
                "大值也一样：行已变，旧摘要输");
    }

    // ⑥ collation 钉子：同列是 NO PAD——差异只在末尾空格时**不匹配**（CAS 会输，方向是安全的）。
    @Test
    void casComparisonTreatsTrailingSpacesAsDifferent() throws Exception {
        insertRow(sessionId, dataKey, "{\"phase\":\"ordered\"}  ");
        ChatSessionExtraData snapshot = readRow(sessionId, dataKey);

        assertFalse(sharedService.updateDataValueIfUnchanged(
                        snapshot, "{\"phase\":\"ordered\"}", "{\"phase\":\"x\"}"),
                "实测：utf8mb4_0900_ai_ci 是 NO PAD，尾随空格不同即不匹配（不会把带空格的写当'没变过'）");
        assertEquals("{\"phase\":\"ordered\"}  ", readValue(sessionId, dataKey));
    }

    // ⑦ 真并发：两个写者都读到同一快照、各自 CAS，恰有一个赢；库里的最终值必须整体等于赢家那份
    //    （不会有 A 的字段 + B 的字段的混合体）。
    @Test
    void twoConcurrentCasWritersExactlyOneWins() throws Exception {
        insertRow(sessionId, dataKey, "{\"phase\":\"candidate_generated\",\"version\":1}");

        final String writerA = "{\"phase\":\"ordered\",\"by\":\"A\"}";
        final String writerB = "{\"phase\":\"draft\",\"by\":\"B\"}";
        CyclicBarrier bothRead = new CyclicBarrier(2);
        ExecutorService pool = Executors.newFixedThreadPool(2);
        try {
            Callable<Boolean> taskA = casTask(bothRead, writerA);
            Callable<Boolean> taskB = casTask(bothRead, writerB);
            Future<Boolean> a = pool.submit(taskA);
            Future<Boolean> b = pool.submit(taskB);

            boolean wonA = a.get(30, TimeUnit.SECONDS);
            boolean wonB = b.get(30, TimeUnit.SECONDS);

            assertTrue(wonA ^ wonB, "两个写者恰有一个赢（实测 A=" + wonA + " B=" + wonB + "）");
            assertEquals(wonA ? writerA : writerB, readValue(sessionId, dataKey),
                    "库里的值是赢家那份整文档，不存在两个写者字段级混合");
        } finally {
            pool.shutdownNow();
        }
    }

    private Callable<Boolean> casTask(final CyclicBarrier bothRead, final String newValue) {
        return () -> {
            ChatSessionExtraData row = sharedService.getBySessionIdAndDataKey(sessionId, dataKey);
            String expected = row.getDataValue();
            bothRead.await(30, TimeUnit.SECONDS); // 两边都先读到同一份快照，再各写各的
            return sharedService.updateDataValueIfUnchanged(row, expected, newValue);
        };
    }

    // ⑧ 写路径的钉子（**H2 已落地，本条的断言已从"无条件 updateById 让后写者整文档覆盖"
    //    翻转为"H2 之后 CAS 挡住第二个写者 / 重读合并后两者都在"——不删，保留翻转痕迹）：
    //    savePlanningState 现在走 updateDataValueIfUnchanged；输的一方由站点策略
    //    重读重放/重读合并，绝不整文档覆盖最新行。
    @Test
    void casWritePathBlocksSecondWriterAndMergeKeepsBoth() throws Exception {
        insertRow(sessionId, dataKey, "{\"phase\":\"candidate_generated\",\"draftCount\":0}");

        ChatSessionExtraData snapshotA = readRow(sessionId, dataKey);
        ChatSessionExtraData snapshotB = readRow(sessionId, dataKey);

        // A 先落盘：它把这行推到 ordered（真实链路里是"页面自举生成方案"）——基线仍是最新，CAS 赢。
        String valueA = "{\"phase\":\"ordered\",\"draftCount\":132,\"by\":\"A\"}";
        assertTrue(sharedService.updateDataValueIfUnchanged(snapshotA, snapshotA.getDataValue(), valueA));

        // B 后落盘：它手里还是 candidate_generated 那份旧快照（真实链路里是延迟到达的补录/overlay/补写），
        // CAS 必须输——H2 之前这里是无条件 updateById，会把 A 的 ordered/132 整体冲掉。
        String valueB = "{\"phase\":\"candidate_generated\",\"draftCount\":0,\"by\":\"B\"}";
        assertFalse(sharedService.updateDataValueIfUnchanged(snapshotB, snapshotB.getDataValue(), valueB),
                "B 的基线已经过期，CAS 必须挡住第二个写者");
        assertEquals(valueA, readValue(sessionId, dataKey), "A 的成果原样在库里，B 一个字都没写进去");
        assertFalse(readValue(sessionId, dataKey).contains("\"by\":\"B\""));

        // B 按站点策略重读最新、只把自己的域合并上去（MERGE_LATEST / RETRY_REPLAY 的形状）：
        // 重读后的期望值 = A 刚写的那份 → CAS 赢，两者都在（不再有"丢一份"的必然）。
        ChatSessionExtraData liveB = readRow(sessionId, dataKey);
        String mergedValue = "{\"phase\":\"ordered\",\"draftCount\":132,\"by\":\"A\",\"mergedBy\":\"B\"}";
        assertTrue(sharedService.updateDataValueIfUnchanged(liveB, liveB.getDataValue(), mergedValue));
        String finalValue = readValue(sessionId, dataKey);
        assertTrue(finalValue.contains("\"by\":\"A\""), "A 的字段在重读合并后仍幸存");
        assertTrue(finalValue.contains("\"mergedBy\":\"B\""), "B 的合并也落盘了——两个写者都不丢");
    }

    // ── 夹具：真表写入/读取都绕过服务层，用独立连接看清库里到底存了什么 ──────────

    private void insertRow(long sessionId, String dataKey, String dataValue) throws Exception {
        try (Connection connection = dataSource.getConnection();
             PreparedStatement statement = connection.prepareStatement(
                     "INSERT INTO assistant_chat_session_extra_data "
                             + "(chat_session_id, data_key, data_type, data_value, data_version) VALUES (?, ?, 5, ?, 0)")) {
            statement.setLong(1, sessionId);
            statement.setString(2, dataKey);
            if (dataValue == null) {
                statement.setNull(3, java.sql.Types.LONGVARCHAR);
            } else {
                statement.setString(3, dataValue);
            }
            statement.executeUpdate();
        }
    }

    private ChatSessionExtraData readRow(long sessionId, String dataKey) {
        ChatSessionExtraData row = sharedService.getBySessionIdAndDataKey(sessionId, dataKey);
        assertTrue(row != null && row.getId() != null, "夹具行没插进去：chatSessionId=" + sessionId + " key=" + dataKey);
        return row;
    }

    /** 独立 JDBC 连接直读 data_value：证的是"库里是什么"，不是 ORM 会话缓存里是什么。 */
    private String readValue(long sessionId, String dataKey) throws Exception {
        try (Connection connection = dataSource.getConnection();
             PreparedStatement statement = connection.prepareStatement(
                     "SELECT data_value FROM assistant_chat_session_extra_data WHERE chat_session_id = ? AND data_key = ?")) {
            statement.setLong(1, sessionId);
            statement.setString(2, dataKey);
            try (ResultSet resultSet = statement.executeQuery()) {
                assertTrue(resultSet.next(), "行不见了：chatSessionId=" + sessionId + " key=" + dataKey);
                return resultSet.getString(1);
            }
        }
    }

    private static String env(String name) {
        String value = System.getenv(name);
        if (value == null || value.isEmpty()) {
            throw new IllegalStateException(name + " is not set");
        }
        return value;
    }

    /** 与生产实现同口径的摘要（小写十六进制 MD5）：对拍 Java 侧与 MySQL {@code MD5()}。 */
    private static String md5Hex(byte[] bytes) throws Exception {
        byte[] digest = java.security.MessageDigest.getInstance("MD5").digest(bytes);
        StringBuilder hex = new StringBuilder(digest.length * 2);
        for (byte b : digest) {
            hex.append(String.format("%02x", b & 0xFF));
        }
        return hex.toString();
    }
}
