package com.ytell.zhiyuan.service.shared;

import com.ytell.zhiyuan.mapper.PlanningPendingCommandMapper;
import org.apache.ibatis.annotations.Delete;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;

import java.lang.reflect.Method;
import java.util.Arrays;
import java.util.Date;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

public class PlanningPendingCommandSharedServiceTest {

    private PlanningPendingCommandSharedService service;
    private PlanningPendingCommandMapper mapper;

    @BeforeEach
    void setUp() {
        service = new PlanningPendingCommandSharedService();
        mapper = mock(PlanningPendingCommandMapper.class);
        ReflectionTestUtils.setField(service, "baseMapper", mapper);
    }

    @Test
    void shouldCapRetentionDeleteBatchAtFiveThousand() {
        Date cutoff = new Date();
        when(mapper.deleteSucceededUpdatedBefore(cutoff, 5000)).thenReturn(3);

        int deleted = service.deleteSucceededUpdatedBefore(cutoff, 10000);

        assertEquals(3, deleted);
        verify(mapper).deleteSucceededUpdatedBefore(cutoff, 5000);
    }

    @Test
    void shouldRaiseRetentionDeleteBatchToOne() {
        Date cutoff = new Date();

        service.deleteSucceededUpdatedBefore(cutoff, 0);

        verify(mapper).deleteSucceededUpdatedBefore(cutoff, 1);
    }

    @Test
    void shouldRejectMissingRetentionCutoff() {
        assertThrows(IllegalArgumentException.class,
                () -> service.deleteSucceededUpdatedBefore(null, 100));
    }

    @Test
    void retentionDeleteSqlMustOnlyTargetSucceededRows() throws Exception {
        Method method = PlanningPendingCommandMapper.class.getMethod(
                "deleteSucceededUpdatedBefore", Date.class, int.class);
        Delete annotation = method.getAnnotation(Delete.class);
        String sql = String.join(" ", Arrays.asList(annotation.value()));

        assertTrue(sql.contains("status = 'succeeded'"));
        assertTrue(sql.contains("update_time < #{cutoff}"));
        assertTrue(sql.contains("LIMIT #{batchSize}"));
    }
}
