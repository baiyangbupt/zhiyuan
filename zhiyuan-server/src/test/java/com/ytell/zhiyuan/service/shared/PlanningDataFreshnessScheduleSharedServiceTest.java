package com.ytell.zhiyuan.service.shared;

import com.ytell.zhiyuan.model.entity.biz.PlanningDataFreshnessScheduleEntity;
import com.ytell.zhiyuan.model.enums.SessionStatus;
import com.ytell.zhiyuan.service.biz.DataFreshnessSchedulePolicy;
import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;

import java.util.Date;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

class PlanningDataFreshnessScheduleSharedServiceTest {

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
