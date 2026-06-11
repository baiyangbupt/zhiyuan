package com.ytell.zhiyuan.model.dto.planning;

import com.alibaba.fastjson.JSONObject;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertSame;

class PlanningStateDTOCompatibilityTest {

    @Test
    void shouldReadLegacyDraftPlanStateIntoWorkingPlanState() {
        String json = "{"
                + "\"sessionId\":1,"
                + "\"draftPlanState\":{"
                + "\"items\":[{\"volunteerId\":\"v1\",\"schoolName\":\"学校A\",\"majorName\":\"专业A\"}],"
                + "\"summary\":{\"total\":1,\"targetCount\":45}"
                + "}"
                + "}";

        PlanningStateDTO state = JSONObject.parseObject(json, PlanningStateDTO.class);

        assertNotNull(state.getWorkingPlanState());
        assertSame(state.getWorkingPlanState(), state.getDraftPlanState());
        assertEquals("v1", state.getWorkingPlanState().getItems().get(0).getVolunteerId());
        assertEquals(Integer.valueOf(1), state.getWorkingPlanState().getSummary().getTotal());
        assertEquals(Integer.valueOf(45), state.getWorkingPlanState().getSummary().getTargetCount());
    }

    @Test
    void shouldSerializeWorkingPlanStateWithLegacyAlias() {
        PlanningStateDTO state = new PlanningStateDTO();
        DraftItemDTO item = new DraftItemDTO();
        item.setVolunteerId("v2");
        item.setSchoolName("学校B");
        item.setMajorName("专业B");
        state.getWorkingPlanState().getItems().add(item);
        state.getWorkingPlanState().getSummary().setTotal(1);

        JSONObject object = JSONObject.parseObject(JSONObject.toJSONString(state));

        assertNotNull(object.getJSONObject("workingPlanState"));
        assertNotNull(object.getJSONObject("draftPlanState"));
        assertEquals("v2", object.getJSONObject("workingPlanState")
                .getJSONArray("items").getJSONObject(0).getString("volunteerId"));
        assertEquals("v2", object.getJSONObject("draftPlanState")
                .getJSONArray("items").getJSONObject(0).getString("volunteerId"));
    }

    @Test
    void shouldNotClearWorkingPlanStateWhenLegacyAliasIsNull() {
        String json = "{"
                + "\"workingPlanState\":{"
                + "\"items\":[{\"volunteerId\":\"v3\",\"schoolName\":\"学校C\",\"majorName\":\"专业C\"}]"
                + "},"
                + "\"draftPlanState\":null"
                + "}";

        PlanningStateDTO state = JSONObject.parseObject(json, PlanningStateDTO.class);

        assertNotNull(state.getWorkingPlanState());
        assertEquals("v3", state.getWorkingPlanState().getItems().get(0).getVolunteerId());
    }
}
