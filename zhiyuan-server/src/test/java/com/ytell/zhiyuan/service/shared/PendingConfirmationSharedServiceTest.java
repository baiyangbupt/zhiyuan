package com.ytell.zhiyuan.service.shared;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.conditions.Wrapper;
import com.baomidou.mybatisplus.core.conditions.update.UpdateWrapper;
import com.baomidou.mybatisplus.core.metadata.TableInfoHelper;
import com.ytell.zhiyuan.model.entity.biz.PendingConfirmationEntity;
import org.apache.ibatis.builder.MapperBuilderAssistant;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;

import java.util.Date;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

class PendingConfirmationSharedServiceTest {

    @BeforeAll
    static void initTableInfo() {
        // 纯单元测试没有 MyBatis-Plus 启动引导，lambda 列名解析需要手动装载 TableInfo 缓存
        TableInfoHelper.initTableInfo(
                new MapperBuilderAssistant(new MybatisConfiguration(), ""),
                PendingConfirmationEntity.class);
    }

    @Test
    void compareAndSetShouldWriteEveryColumnExplicitlyIncludingNulls() {
        CapturingSharedService service = new CapturingSharedService();
        PendingConfirmationEntity next = new PendingConfirmationEntity();
        next.setId(9L);
        next.setTenantId(1L);
        next.setChatSessionId(101L);
        next.setPendingId("p-2");
        next.setRevision(4L);
        next.setKind("plan_mutation");
        next.setActionFamily("remove_units");
        next.setStatus("active");
        next.setClaimToken(null);
        next.setClaimExpiresAt(null);
        next.setDataValue("{\"status\":\"active\"}");
        next.setResultCode(null);
        next.setResolvedAction(null);

        boolean updated = service.compareAndSet(next, 3L, "p-1", "active");

        assertTrue(updated);
        String sqlSet = service.captured.getSqlSet();
        // 整行逐列显式 SET（含 null）：旧实现 update(entity, wrapper) 走 NOT_NULL 策略会漏掉 null 字段，
        // 造成已确认行仍带旧 claimToken / 旧 resultCode（如 84009）等残留
        for (String column : new String[]{"pending_id", "revision", "kind", "action_family", "status",
                "claim_token", "claim_expires_at", "data_value", "result_code", "resolved_action"}) {
            assertTrue(sqlSet.contains(column + "="),
                    "SET 子句应显式覆盖列 " + column + "，实际: " + sqlSet);
        }
        // null 字段也必须真正绑定进参数表（4 个 null：claimToken/claimExpiresAt/resultCode/resolvedAction），
        // 而不是被更新策略静默跳过；5 个 WHERE 条件值均非空
        assertEquals(4, service.captured.getParamNameValuePairs().values().stream()
                .filter(value -> value == null).count());
        assertTrue(service.captured.getParamNameValuePairs().containsValue("p-2"));
        assertTrue(service.captured.getParamNameValuePairs().containsValue("active"));
        String sqlSegment = service.captured.getSqlSegment();
        assertTrue(sqlSegment.contains("revision=") || sqlSegment.contains("revision ="),
                "CAS 条件应包含 revision，实际: " + sqlSegment);
        assertTrue(sqlSegment.contains("pending_id=") || sqlSegment.contains("pending_id ="),
                "CAS 条件应包含 pending_id，实际: " + sqlSegment);
        assertTrue(sqlSegment.contains("status=") || sqlSegment.contains("status ="),
                "CAS 条件应包含 status，实际: " + sqlSegment);
    }

    @Test
    void freshActiveShouldPassWithoutExpiryWrite() {
        InMemorySharedService service =
                new InMemorySharedService(entity("active", minutesAgo(5L)));
        ReflectionTestUtils.setField(service, "pendingTtlMinutes", 1440L);

        PendingConfirmationEntity current = service.getCurrent(1L, 101L);

        assertNotNull(current);
        assertEquals("active", current.getStatus());
        assertEquals(Long.valueOf(5L), current.getRevision());
        assertEquals(0, service.updateCalls);
    }

    @Test
    void staleActiveShouldExpireAndActiveOrApplyingShouldReturnNull() {
        InMemorySharedService service =
                new InMemorySharedService(entity("active", minutesAgo(25L * 60L)));
        ReflectionTestUtils.setField(service, "pendingTtlMinutes", 1440L);

        PendingConfirmationEntity current = service.getActiveOrApplying(1L, 101L);

        assertNull(current);
        assertEquals(1, service.updateCalls);
        // 先取 SQL 片段，MyBatis-Plus 在 getSqlSegment() 时才把 WHERE 参数物化进参数表
        String sqlSegment = service.captured.getSqlSegment();
        assertTrue(sqlSegment.contains("status"));
        assertTrue(sqlSegment.contains("revision"));
        assertTrue(sqlSegment.contains("pending_id"));
        // CAS 必须锁住 revision/pendingId/status=active，且落库为 expired
        assertTrue(service.captured.getSqlSet().contains("status="));
        assertTrue(service.captured.getParamNameValuePairs().values().contains("expired"));
        assertTrue(service.captured.getParamNameValuePairs().values().contains("active"));
        assertTrue(service.captured.getParamNameValuePairs().values().contains("p-1"));
    }

    @Test
    void staleActiveShouldPersistExpiredStatusOnGetCurrent() {
        InMemorySharedService service =
                new InMemorySharedService(entity("active", minutesAgo(25L * 60L)));
        ReflectionTestUtils.setField(service, "pendingTtlMinutes", 1440L);

        PendingConfirmationEntity current = service.getCurrent(1L, 101L);

        assertNotNull(current);
        assertEquals("expired", current.getStatus());
        assertEquals(Long.valueOf(6L), current.getRevision());
        assertEquals("expire", current.getResolvedAction());
        assertTrue(current.getDataValue().contains("\"status\":\"expired\""));
        assertEquals(1, service.updateCalls);
    }

    @Test
    void applyingWithValidClaimShouldNotExpire() {
        PendingConfirmationEntity applying = entity("applying", minutesAgo(25L * 60L));
        applying.setClaimToken("claim-1");
        applying.setClaimExpiresAt(new Date(System.currentTimeMillis() + 300_000L));
        InMemorySharedService service = new InMemorySharedService(applying);
        ReflectionTestUtils.setField(service, "pendingTtlMinutes", 1440L);

        PendingConfirmationEntity current = service.getActiveOrApplying(1L, 101L);

        assertNotNull(current);
        assertEquals("applying", current.getStatus());
        assertEquals("claim-1", current.getClaimToken());
        assertEquals(0, service.updateCalls);
    }

    @Test
    void disabledTtlShouldPassOldActive() {
        InMemorySharedService service =
                new InMemorySharedService(entity("active", minutesAgo(25L * 60L)));
        ReflectionTestUtils.setField(service, "pendingTtlMinutes", 0L);

        PendingConfirmationEntity current = service.getCurrent(1L, 101L);

        assertNotNull(current);
        assertEquals("active", current.getStatus());
        assertEquals(0, service.updateCalls);
    }

    @Test
    void staleActiveShouldFallBackToUpdateTimeWhenCreateTimeMissing() {
        PendingConfirmationEntity stale = entity("active", null);
        stale.setUpdateTime(minutesAgo(25L * 60L));
        InMemorySharedService service = new InMemorySharedService(stale);
        ReflectionTestUtils.setField(service, "pendingTtlMinutes", 1440L);

        PendingConfirmationEntity current = service.getCurrent(1L, 101L);

        assertNotNull(current);
        assertEquals("expired", current.getStatus());
        assertEquals(1, service.updateCalls);
    }

    @Test
    void casConflictShouldReturnActualRowInsteadOfStaleSnapshot() {
        InMemorySharedService service =
                new InMemorySharedService(entity("active", minutesAgo(25L * 60L)));
        service.reloaded = entity("applying", minutesAgo(1L));
        service.casSucceeds = false;
        ReflectionTestUtils.setField(service, "pendingTtlMinutes", 1440L);

        PendingConfirmationEntity current = service.getCurrent(1L, 101L);

        assertNotNull(current);
        assertEquals("applying", current.getStatus());
        assertEquals(1, service.updateCalls);
    }

    private static PendingConfirmationEntity entity(String status, Date createTime) {
        PendingConfirmationEntity entity = new PendingConfirmationEntity();
        entity.setId(9L);
        entity.setTenantId(1L);
        entity.setChatSessionId(101L);
        entity.setPendingId("p-1");
        entity.setRevision(5L);
        entity.setKind("plan_mutation");
        entity.setActionFamily("remove_units");
        entity.setStatus(status);
        entity.setDataValue("{\"pendingId\":\"p-1\",\"status\":\"" + status + "\",\"revision\":5}");
        entity.setCreateTime(createTime);
        return entity;
    }

    private static Date minutesAgo(long minutes) {
        return new Date(System.currentTimeMillis() - minutes * 60_000L);
    }

    private static class CapturingSharedService extends PendingConfirmationSharedService {
        private UpdateWrapper<PendingConfirmationEntity> captured;

        @Override
        public boolean update(PendingConfirmationEntity entity,
                              Wrapper<PendingConfirmationEntity> updateWrapper) {
            this.captured = (UpdateWrapper<PendingConfirmationEntity>) updateWrapper;
            return true;
        }
    }

    /** 内存替身：getOne 返回固定行，update 记录 CAS 条件而不再触库。 */
    private static class InMemorySharedService extends PendingConfirmationSharedService {
        private final PendingConfirmationEntity stored;
        private PendingConfirmationEntity reloaded;
        private int reads;
        private int updateCalls;
        private boolean casSucceeds = true;
        private UpdateWrapper<PendingConfirmationEntity> captured;

        private InMemorySharedService(PendingConfirmationEntity stored) {
            this.stored = stored;
            this.reloaded = stored;
        }

        @Override
        public PendingConfirmationEntity getOne(Wrapper<PendingConfirmationEntity> queryWrapper,
                                                boolean throwEx) {
            this.reads++;
            return this.reads == 1 ? this.stored : this.reloaded;
        }

        @Override
        public boolean update(PendingConfirmationEntity entity,
                              Wrapper<PendingConfirmationEntity> updateWrapper) {
            this.updateCalls++;
            this.captured = (UpdateWrapper<PendingConfirmationEntity>) updateWrapper;
            return this.casSucceeds;
        }
    }
}
