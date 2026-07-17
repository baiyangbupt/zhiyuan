package com.ytell.zhiyuan.service.biz;

import com.ytell.zhiyuan.common.exception.BusinessException;
import com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedItemDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedUnitDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningUnitMajorDTO;
import com.ytell.zhiyuan.model.dto.planning.PriorityRuleDTO;
import org.junit.jupiter.api.Test;

import java.util.Arrays;
import java.util.List;
import java.util.stream.Collectors;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

public class PriorityObjectiveEnforcerTest {

    @Test
    void shouldStablePartitionMatchingVolunteersWithinEachTier() {
        PlanningStateDTO state = new PlanningStateDTO();
        state.getCandidatePoolState().setVolunteerModel("major");
        CandidateItemDTO v1 = candidate("v1", "北京", "稳");
        CandidateItemDTO v2 = candidate("v2", "上海", "稳");
        CandidateItemDTO v3 = candidate("v3", "天津", "稳");
        CandidateItemDTO v4 = candidate("v4", "上海", "稳");
        CandidateItemDTO v5 = candidate("v5", "上海", "保");
        CandidateItemDTO v6 = candidate("v6", "河北", "保");
        List<CandidateItemDTO> candidates = Arrays.asList(v1, v2, v3, v4, v5, v6);
        state.getCandidatePoolState().setItems(candidates);
        for (CandidateItemDTO candidate : candidates) {
            state.getOrderedPlanState().getItems().add(ordered(candidate.getVolunteerId(), candidate.getTier()));
        }
        PriorityRuleSupport.persist(state, Arrays.asList(rule("上海")));

        PriorityObjectiveEnforcer.enforce(state, candidates);

        assertEquals(Arrays.asList("v2", "v4", "v1", "v3", "v5", "v6"),
                ids(state.getOrderedPlanState().getItems()));
        assertEquals(Arrays.asList("稳", "稳", "稳", "稳", "保", "保"),
                state.getOrderedPlanState().getItems().stream()
                        .map(OrderedItemDTO::getTier).collect(Collectors.toList()));
        assertEquals("hard_priority_rank_before",
                state.getOrderedPlanState().getItems().get(0).getOrderReason());
        assertTrue(PriorityRuleSupport.isSatisfied(state, candidates, rule("上海")));
    }

    @Test
    void shouldMoveCompleteMajorGroupUnitsAndKeepInnerMajorOrder() {
        PlanningStateDTO state = new PlanningStateDTO();
        state.getCandidatePoolState().setVolunteerModel("majorGroup");
        CandidateItemDTO v1 = candidate("v1", "北京", "稳");
        v1.setPlanSchoolDataId("u1");
        CandidateItemDTO v1b = candidate("v1b", "北京", "稳");
        v1b.setPlanSchoolDataId("u1");
        CandidateItemDTO v2 = candidate("v2", "上海", "稳");
        v2.setPlanSchoolDataId("u2");
        CandidateItemDTO v2b = candidate("v2b", "上海", "稳");
        v2b.setPlanSchoolDataId("u2");
        List<CandidateItemDTO> candidates = Arrays.asList(v1, v1b, v2, v2b);
        state.getCandidatePoolState().setItems(candidates);
        state.getOrderedPlanState().getUnits().add(unit("u1", "北京", "v1", "v1b"));
        state.getOrderedPlanState().getUnits().add(unit("u2", "上海", "v2", "v2b"));
        state.getOrderedPlanState().getItems().add(ordered("v1", "稳"));
        state.getOrderedPlanState().getItems().add(ordered("v1b", "稳"));
        state.getOrderedPlanState().getItems().add(ordered("v2", "稳"));
        state.getOrderedPlanState().getItems().add(ordered("v2b", "稳"));
        PriorityRuleSupport.persist(state, Arrays.asList(rule("上海")));

        PriorityObjectiveEnforcer.enforce(state, candidates);

        assertEquals(Arrays.asList("u2", "u1"), state.getOrderedPlanState().getUnits().stream()
                .map(OrderedUnitDTO::getUnitId).collect(Collectors.toList()));
        assertEquals(Arrays.asList("v2", "v2b", "v1", "v1b"),
                ids(state.getOrderedPlanState().getItems()));
        assertTrue(PriorityRuleSupport.isSatisfied(state, candidates, rule("上海")));
    }

    @Test
    void shouldRejectPinnedConflictInsteadOfPartiallyReordering() {
        PlanningStateDTO state = new PlanningStateDTO();
        CandidateItemDTO v1 = candidate("v1", "北京", "稳");
        CandidateItemDTO v2 = candidate("v2", "上海", "稳");
        List<CandidateItemDTO> candidates = Arrays.asList(v1, v2);
        state.getCandidatePoolState().setItems(candidates);
        OrderedItemDTO pinned = ordered("v1", "稳");
        pinned.setPinned(true);
        pinned.setPinnedPosition(1);
        state.getOrderedPlanState().getItems().add(pinned);
        state.getOrderedPlanState().getItems().add(ordered("v2", "稳"));
        PriorityRuleSupport.persist(state, Arrays.asList(rule("上海")));

        BusinessException error = assertThrows(BusinessException.class,
                () -> PriorityObjectiveEnforcer.enforce(state, candidates));

        assertTrue(error.getMessage().contains("固定位置"));
        assertEquals(Arrays.asList("v1", "v2"), ids(state.getOrderedPlanState().getItems()));
    }

    @Test
    void shouldNotReportSatisfiedWhenAnyPlanItemHasNoTier() {
        PlanningStateDTO state = new PlanningStateDTO();
        CandidateItemDTO v1 = candidate("v1", "上海", null);
        state.getCandidatePoolState().setItems(Arrays.asList(v1));
        state.getOrderedPlanState().getItems().add(ordered("v1", null));

        assertFalse(PriorityRuleSupport.isSatisfied(state, Arrays.asList(v1), rule("上海")));
    }

    @Test
    void shouldReplacePreviousSingletonPriorityRuleWhenPersistingNewOne() {
        PlanningStateDTO state = new PlanningStateDTO();
        PriorityRuleSupport.persist(state, Arrays.asList(rule("上海")));

        PriorityRuleSupport.persist(state, Arrays.asList(rule("湖南")));

        assertEquals(1, PriorityRuleSupport.confirmedRules(state).size());
        assertEquals(Arrays.asList("湖南"),
                PriorityRuleSupport.confirmedRules(state).get(0).getValues());
    }

    private CandidateItemDTO candidate(String id, String province, String tier) {
        CandidateItemDTO candidate = new CandidateItemDTO();
        candidate.setVolunteerId(id);
        candidate.setProvinceName(province);
        candidate.setSchoolName(province + "学校");
        candidate.setMajorName("专业" + id);
        candidate.setTier(tier);
        return candidate;
    }

    private OrderedItemDTO ordered(String id, String tier) {
        OrderedItemDTO item = new OrderedItemDTO();
        item.setVolunteerId(id);
        item.setTier(tier);
        item.setSchoolName("学校" + id);
        item.setMajorName("专业" + id);
        item.setPinned(false);
        return item;
    }

    private OrderedUnitDTO unit(String id, String province, String... volunteerIds) {
        OrderedUnitDTO unit = new OrderedUnitDTO();
        unit.setUnitId(id);
        unit.setTier("稳");
        unit.setProvinceName(province);
        unit.setSchoolName(province + "学校");
        for (String volunteerId : volunteerIds) {
            PlanningUnitMajorDTO major = new PlanningUnitMajorDTO();
            major.setVolunteerId(volunteerId);
            major.setMajorName("专业" + volunteerId);
            unit.getMajorItems().add(major);
        }
        return unit;
    }

    private PriorityRuleDTO rule(String province) {
        PriorityRuleDTO rule = new PriorityRuleDTO();
        rule.setDomain("region");
        rule.setKey("province");
        rule.setValues(Arrays.asList(province));
        rule.setOrderingTarget("rank_before");
        rule.setScope("within_tier");
        return rule;
    }

    private List<String> ids(List<OrderedItemDTO> items) {
        return items.stream().map(OrderedItemDTO::getVolunteerId).collect(Collectors.toList());
    }
}
