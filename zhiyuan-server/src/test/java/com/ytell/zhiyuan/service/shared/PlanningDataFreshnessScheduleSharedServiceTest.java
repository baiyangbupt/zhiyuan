package com.ytell.zhiyuan.service.shared;

import com.ytell.zhiyuan.mapper.PlanningDataFreshnessScheduleMapper;
import com.ytell.zhiyuan.model.entity.biz.PlanningDataFreshnessScheduleEntity;
import com.ytell.zhiyuan.model.enums.SessionStatus;
import com.ytell.zhiyuan.service.biz.DataFreshnessSchedulePolicy;
import org.junit.jupiter.api.Test;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.test.util.ReflectionTestUtils;

import java.util.Date;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertSame;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyBoolean;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class PlanningDataFreshnessScheduleSharedServiceTest {

    @Test
    void shouldFallBackToMergeWhenLazyInsertLosesRace() {
        // 并发首读（workspace-state 懒触达）会同时走 insert，唯一键让一个失败；
        // 失败方应读赢家行合并更新，而不是把 500/code -1 抛给前端。
        PlanningDataFreshnessScheduleSharedService service = new PlanningDataFreshnessScheduleSharedService();
        PlanningDataFreshnessScheduleMapper mapper = mock(PlanningDataFreshnessScheduleMapper.class);
        ReflectionTestUtils.setField(service, "baseMapper", mapper);

        PlanningDataFreshnessScheduleEntity winner = new PlanningDataFreshnessScheduleEntity();
        winner.setId(77L);
        winner.setChatSessionId(900833L);
        winner.setPrepareType("VOLUNTEER");
        winner.setSessionStatus(SessionStatus.GOING.name());
        winner.setSessionCreateTime(new Date());
        winner.setLastAccessedAt(new Date());
        when(mapper.selectOne(any(), anyBoolean())).thenReturn(null, winner);
        when(mapper.insert(any(PlanningDataFreshnessScheduleEntity.class)))
                .thenThrow(new DuplicateKeyException("Duplicate entry"));
        when(mapper.updateById(any(PlanningDataFreshnessScheduleEntity.class))).thenReturn(1);

        PlanningDataFreshnessScheduleEntity incoming = new PlanningDataFreshnessScheduleEntity();
        incoming.setChatSessionId(900833L);
        incoming.setTenantId(1L);
        incoming.setPrepareType("VOLUNTEER");
        incoming.setSessionStatus(SessionStatus.GOING.name());
        incoming.setSessionCreateTime(new Date());
        incoming.setLastAccessedAt(new Date());

        PlanningDataFreshnessScheduleEntity result = service.saveOrUpdateSchedule(incoming);

        assertSame(winner, result);
        assertEquals(1L, result.getTenantId());
        verify(mapper, times(1)).insert(any(PlanningDataFreshnessScheduleEntity.class));
        verify(mapper, times(1)).updateById(any(PlanningDataFreshnessScheduleEntity.class));
    }

    @Test
    void shouldAdvanceNextCheckAtWhenExistingValueIsNotAfterLastCheckedAt() {
        PlanningDataFreshnessScheduleSharedService service = new PlanningDataFreshnessScheduleSharedService();
        Date now = new Date(10L * 24L * 60L * 60L * 1000L);
        PlanningDataFreshnessScheduleEntity entity = new PlanningDataFreshnessScheduleEntity();
        entity.setPrepareType("VOLUNTEER");
        entity.setSessionStatus(SessionStatus.GOING.name());
        entity.setSessionCreateTime(new Date(now.getTime() - 2L * 24L * 60L * 60L * 1000L));
        entity.setLastAccessedAt(new Date(now.getTime() - 60L * 60L * 1000L));
        entity.setLastCheckedAt(now);
        entity.setNextCheckAt(new Date(now.getTime() - 10L * 60L * 1000L));

        ReflectionTestUtils.invokeMethod(service, "fillDefaults", entity, now);

        assertEquals(DataFreshnessSchedulePolicy.RECENT_INTERVAL_MINUTES, entity.getCheckIntervalMinutes());
        assertTrue(entity.getNextCheckAt().after(entity.getLastCheckedAt()));
        assertEquals(now.getTime() + DataFreshnessSchedulePolicy.RECENT_INTERVAL_MINUTES * 60L * 1000L,
                entity.getNextCheckAt().getTime());
    }
}
