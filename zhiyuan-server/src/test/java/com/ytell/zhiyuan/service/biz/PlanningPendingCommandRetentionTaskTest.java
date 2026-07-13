package com.ytell.zhiyuan.service.biz;

import com.ytell.zhiyuan.common.config.PlanningPendingCommandRetentionProperties;
import com.ytell.zhiyuan.service.shared.PlanningPendingCommandSharedService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.test.util.ReflectionTestUtils;

import java.util.Date;

import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

public class PlanningPendingCommandRetentionTaskTest {

    private PlanningPendingCommandRetentionTask task;
    private PlanningPendingCommandRetentionProperties properties;
    private PlanningPendingCommandSharedService commandSharedService;

    @BeforeEach
    void setUp() {
        task = new PlanningPendingCommandRetentionTask();
        properties = new PlanningPendingCommandRetentionProperties();
        commandSharedService = mock(PlanningPendingCommandSharedService.class);
        ReflectionTestUtils.setField(task, "properties", properties);
        ReflectionTestUtils.setField(task, "commandSharedService", commandSharedService);
    }

    @Test
    void shouldSkipWhenRetentionIsDisabled() {
        properties.setEnabled(false);

        task.run();

        verify(commandSharedService, never()).deleteSucceededUpdatedBefore(any(), anyInt());
    }

    @Test
    void shouldDeleteOneBoundedBatchOlderThanRetentionWindow() {
        properties.setEnabled(true);
        properties.setRetentionDays(7);
        properties.setBatchSize(250);
        when(commandSharedService.deleteSucceededUpdatedBefore(any(), anyInt())).thenReturn(12);
        long before = System.currentTimeMillis() - 7L * 24L * 60L * 60L * 1000L;

        task.run();

        long after = System.currentTimeMillis() - 7L * 24L * 60L * 60L * 1000L;
        ArgumentCaptor<Date> cutoff = ArgumentCaptor.forClass(Date.class);
        verify(commandSharedService).deleteSucceededUpdatedBefore(cutoff.capture(), org.mockito.ArgumentMatchers.eq(250));
        assertTrue(cutoff.getValue().getTime() >= before);
        assertTrue(cutoff.getValue().getTime() <= after);
    }

    @Test
    void shouldReleaseRunGuardAfterFailure() {
        properties.setEnabled(true);
        when(commandSharedService.deleteSucceededUpdatedBefore(any(), anyInt()))
                .thenThrow(new IllegalStateException("database unavailable"))
                .thenReturn(0);

        task.run();
        task.run();

        verify(commandSharedService, org.mockito.Mockito.times(2))
                .deleteSucceededUpdatedBefore(any(), anyInt());
    }
}
