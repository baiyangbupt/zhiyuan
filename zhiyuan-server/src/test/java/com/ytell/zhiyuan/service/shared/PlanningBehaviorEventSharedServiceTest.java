package com.ytell.zhiyuan.service.shared;

import com.alibaba.fastjson.JSONObject;
import com.ytell.zhiyuan.model.dto.planning.PlanningBehaviorEventDTO;
import com.ytell.zhiyuan.model.entity.biz.PlanningBehaviorEventEntity;
import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;

import java.util.Arrays;
import java.util.HashMap;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;

public class PlanningBehaviorEventSharedServiceTest {

    @Test
    void shouldMapBehaviorEventPayloadBetweenDtoAndEntity() {
        PlanningBehaviorEventSharedService service = new PlanningBehaviorEventSharedService();
        PlanningBehaviorEventDTO event = new PlanningBehaviorEventDTO();
        event.setEventId("event-1");
        event.setChatSessionId(17L);
        event.setTenantId(1L);
        event.setEventType("plan_item_move");
        event.setMode("majorGroup");
        event.setPlanVersion(12);
        event.setGenerationMode("user_sort");
        event.setVolunteerIds(Arrays.asList("ps1_m1"));
        event.setUnitIds(Arrays.asList("ps1"));
        Map<String, Integer> fromPositions = new HashMap<String, Integer>();
        fromPositions.put("ps1_m1", 3);
        event.setFromPositions(fromPositions);
        Map<String, Integer> toPositions = new HashMap<String, Integer>();
        toPositions.put("ps1_m1", 1);
        event.setToPositions(toPositions);
        event.setTier("稳");
        event.setAdmissionRatio(61.5D);
        event.setSchoolName("学校A");
        event.setMajorName("专业A");
        event.setSortKey("admissionRatio");
        event.setPositiveFeedback(true);
        event.setSnapshotDigest("digest-1");
        event.setEventPayloadJson("{\"source\":\"plan_item\",\"items\":[{\"schoolName\":\"学校A\"}]}");
        event.setCreatedAt("2026-05-21T10:00:00+08:00");

        PlanningBehaviorEventEntity entity = ReflectionTestUtils.invokeMethod(service, "convertToEntity", event);
        assertNotNull(entity);
        assertEquals("digest-1", entity.getSnapshotDigest());
        assertEquals(event.getEventPayloadJson(), entity.getEventPayloadJson());

        PlanningBehaviorEventDTO mapped = ReflectionTestUtils.invokeMethod(service, "convertToDto", entity);
        assertNotNull(mapped);
        assertEquals("plan_item_move", mapped.getEventType());
        assertEquals("majorGroup", mapped.getMode());
        assertEquals("ps1_m1", mapped.getVolunteerIds().get(0));
        assertEquals(Integer.valueOf(3), mapped.getFromPositions().get("ps1_m1"));
        assertEquals(Integer.valueOf(1), mapped.getToPositions().get("ps1_m1"));
        assertEquals("digest-1", mapped.getSnapshotDigest());
        assertEquals("学校A", JSONObject.parseObject(mapped.getEventPayloadJson())
                .getJSONArray("items")
                .getJSONObject(0)
                .getString("schoolName"));
    }
}
