package com.ytell.zhiyuan.service.shared;

import com.baomidou.mybatisplus.core.MybatisConfiguration;
import com.baomidou.mybatisplus.core.conditions.Wrapper;
import com.baomidou.mybatisplus.core.conditions.update.UpdateWrapper;
import com.baomidou.mybatisplus.core.metadata.TableInfoHelper;
import com.ytell.zhiyuan.model.entity.biz.PendingConfirmationEntity;
import org.apache.ibatis.builder.MapperBuilderAssistant;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
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

    private static class CapturingSharedService extends PendingConfirmationSharedService {
        private UpdateWrapper<PendingConfirmationEntity> captured;

        @Override
        public boolean update(PendingConfirmationEntity entity,
                              Wrapper<PendingConfirmationEntity> updateWrapper) {
            this.captured = (UpdateWrapper<PendingConfirmationEntity>) updateWrapper;
            return true;
        }
    }
}
