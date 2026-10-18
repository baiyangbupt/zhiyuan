package com.ytell.zhiyuan.service.biz;

import com.google.common.collect.Lists;
import com.ytell.zhiyuan.model.dto.planning.CandidateFactDTO;
import com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO;
import com.ytell.zhiyuan.model.dto.planning.CandidatePoolStateDTO;
import com.ytell.zhiyuan.model.dto.planning.CandidateSnapshotDTO;
import com.ytell.zhiyuan.model.dto.planning.DraftItemDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedItemDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedUnitDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningUnitMajorDTO;
import org.junit.jupiter.api.Test;

import java.util.Arrays;
import java.util.HashSet;
import java.util.List;
import java.util.Set;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

class CandidateSnapshotBuilderTest {

    @Test
    void volunteerSnapshotMarksCurrentLockedPinnedAndKeepsWorkingPlanFallback() {
        PlanningStateDTO state = state("major");
        state.getCandidatePoolState().setSourceVersion(7);
        state.getCandidatePoolState().setSourceProvinceName("浙江");
        state.getDataFreshnessState().setDataVersion("data-1");
        state.getCandidatePoolState().setItems(Arrays.asList(
                candidate("c1", "u1", "浙江大学", "计算机", "稳", 90D, 80D, 0.7D, 6000),
                candidate("c2", "u2", "杭州电子科技大学", "软件工程", "保", 70D, 65D, 0.8D, 12000)));

        DraftItemDTO draft = new DraftItemDTO();
        draft.setVolunteerId("c1");
        draft.setLocked(true);
        state.getWorkingPlanState().setItems(Lists.newArrayList(draft));

        OrderedItemDTO ordered = new OrderedItemDTO();
        ordered.setVolunteerId("c1");
        ordered.setPinned(true);
        OrderedItemDTO fallback = new OrderedItemDTO();
        fallback.setVolunteerId("c3");
        fallback.setSchoolName("浙江工业大学");
        fallback.setMajorName("自动化");
        fallback.setTier("稳");
        state.getOrderedPlanState().setItems(Lists.newArrayList(ordered, fallback));

        CandidateSnapshotDTO snapshot = CandidateSnapshotBuilder.build(
                state, state.getCandidatePoolState().getItems());

        assertEquals("volunteer", snapshot.getCountMode());
        assertEquals("浙江", snapshot.getSourceProvince());
        assertEquals(3, snapshot.getFacts().size());
        CandidateFactDTO c1 = fact(snapshot, "c1");
        assertTrue(Boolean.TRUE.equals(c1.getCurrent()));
        assertTrue(Boolean.TRUE.equals(c1.getLocked()));
        assertTrue(Boolean.TRUE.equals(c1.getPinned()));
        assertFalse(Boolean.TRUE.equals(fact(snapshot, "c2").getCurrent()));
        CandidateFactDTO c3 = fact(snapshot, "c3");
        assertTrue(Boolean.TRUE.equals(c3.getCurrent()));
        assertTrue(Boolean.TRUE.equals(c3.getEligible()));
        assertEquals("working_plan", c3.getSource());
        assertUniqueStableOrder(snapshot.getFacts());
        assertEquals(64, snapshot.getNormalizationDigest().length());
        assertNotNull(c1.getUtilityComponents());
        assertEquals(100, c1.getUtilityCoverage());
        String json = com.alibaba.fastjson.JSON.toJSONString(snapshot);
        assertFalse(json.contains("utilityScore"));
        assertFalse(json.contains("utilityComponents"));
        assertFalse(json.contains("rawCandidates"));
    }

    @Test
    void unitSnapshotGroupsMajorsAndKeepsUnitFacts() {
        PlanningStateDTO state = state("majorGroup");
        state.getCandidatePoolState().setItems(Arrays.asList(
                candidate("u1_a", "u1", "浙江大学", "计算机", "稳", 90D, 80D, 0.7D, 6000),
                candidate("u1_b", "u1", "浙江大学", "软件工程", "稳", 70D, 70D, 0.6D, 6000)));

        DraftItemDTO draft = new DraftItemDTO();
        draft.setVolunteerId("u1_a");
        draft.setLocked(true);
        state.getWorkingPlanState().setItems(Lists.newArrayList(draft));

        OrderedUnitDTO unit = new OrderedUnitDTO();
        unit.setUnitId("u1");
        unit.setPinned(true);
        unit.setTier("稳");
        PlanningUnitMajorDTO major = new PlanningUnitMajorDTO();
        major.setVolunteerId("u1_a");
        major.setMajorName("计算机");
        unit.setMajorItems(Lists.newArrayList(major));
        state.getOrderedPlanState().setUnits(Lists.newArrayList(unit));

        CandidateSnapshotDTO snapshot = CandidateSnapshotBuilder.build(
                state, state.getCandidatePoolState().getItems());

        assertEquals("unit", snapshot.getCountMode());
        assertEquals(1, snapshot.getFacts().size());
        CandidateFactDTO fact = snapshot.getFacts().get(0);
        assertEquals("u1", fact.getEntityId());
        assertEquals(Arrays.asList("u1_a", "u1_b"), fact.getVolunteerIds());
        assertTrue(Boolean.TRUE.equals(fact.getCurrent()));
        assertTrue(Boolean.TRUE.equals(fact.getLocked()));
        assertTrue(Boolean.TRUE.equals(fact.getPinned()));
        assertTrue(Boolean.TRUE.equals(fact.getUnitAllSafe()));
    }

    @Test
    void currentSourceCanMatchWorkingOrOrderedPlan() {
        PlanningStateDTO state = state("major");
        state.getCandidatePoolState().setItems(Arrays.asList(
                candidate("a", "u1", "学校A", "专业A", "稳", 90D, 80D, 0.7D, 6000),
                candidate("b", "u2", "学校B", "专业B", "稳", 80D, 70D, 0.6D, 6000)));
        DraftItemDTO draft = new DraftItemDTO();
        draft.setVolunteerId("a");
        state.getWorkingPlanState().setItems(Lists.newArrayList(draft));
        OrderedItemDTO ordered = new OrderedItemDTO();
        ordered.setVolunteerId("b");
        state.getOrderedPlanState().setItems(Lists.newArrayList(ordered));

        CandidateSnapshotDTO working = CandidateSnapshotBuilder.build(
                state, state.getCandidatePoolState().getItems(),
                CandidateSnapshotBuilder.CurrentSource.WORKING);
        CandidateSnapshotDTO orderedFirst = CandidateSnapshotBuilder.build(
                state, state.getCandidatePoolState().getItems(),
                CandidateSnapshotBuilder.CurrentSource.ORDERED_FIRST);

        assertTrue(Boolean.TRUE.equals(fact(working, "a").getCurrent()));
        assertFalse(Boolean.TRUE.equals(fact(working, "b").getCurrent()));
        assertTrue(Boolean.TRUE.equals(fact(orderedFirst, "b").getCurrent()));
        assertFalse(Boolean.TRUE.equals(fact(orderedFirst, "a").getCurrent()));
    }

    @Test
    void unitWithConflictingTiersIsRejected() {
        PlanningStateDTO state = state("majorGroup");
        state.getCandidatePoolState().setItems(Arrays.asList(
                candidate("u1_a", "u1", "浙江大学", "计算机", "稳", 90D, 80D, 0.7D, 6000),
                candidate("u1_b", "u1", "浙江大学", "软件工程", "保", 70D, 70D, 0.6D, 6000)));

        com.ytell.zhiyuan.common.exception.BusinessException error =
                org.junit.jupiter.api.Assertions.assertThrows(
                        com.ytell.zhiyuan.common.exception.BusinessException.class,
                        () -> CandidateSnapshotBuilder.build(
                                state, state.getCandidatePoolState().getItems()));
        assertTrue(error.getMessage().contains("tier_fact_conflict"));
    }

    private PlanningStateDTO state(String volunteerModel) {
        PlanningStateDTO state = new PlanningStateDTO();
        CandidatePoolStateDTO pool = state.getCandidatePoolState();
        pool.setVolunteerModel(volunteerModel);
        return state;
    }

    private CandidateItemDTO candidate(String volunteerId,
                                       String unitId,
                                       String school,
                                       String major,
                                       String tier,
                                       Double intent,
                                       Double finalScore,
                                       Double ratio,
                                       Integer tuition) {
        CandidateItemDTO candidate = new CandidateItemDTO();
        candidate.setVolunteerId(volunteerId);
        candidate.setPlanSchoolDataId(unitId);
        candidate.setSchoolId(unitId);
        candidate.setSchoolName(school);
        candidate.setDisplaySchoolName(school);
        candidate.setMajorName(major);
        candidate.setTier(tier);
        candidate.setIntentScore(intent);
        candidate.setFinalScore(finalScore);
        candidate.setFutureDevelopmentScore(finalScore);
        candidate.setAdmissionRatio(ratio);
        candidate.setTuitionPerYear(tuition);
        return candidate;
    }

    private CandidateFactDTO fact(CandidateSnapshotDTO snapshot, String entityId) {
        for (CandidateFactDTO fact : snapshot.getFacts()) {
            if (entityId.equals(fact.getEntityId())) {
                return fact;
            }
        }
        throw new AssertionError("missing fact " + entityId);
    }

    private void assertUniqueStableOrder(List<CandidateFactDTO> facts) {
        Set<Integer> orders = new HashSet<Integer>();
        for (int index = 0; index < facts.size(); index++) {
            assertNotNull(facts.get(index).getStableOrder());
            assertTrue(orders.add(facts.get(index).getStableOrder()));
        }
        for (int index = 0; index < facts.size(); index++) {
            assertEquals(index, facts.get(index).getStableOrder().intValue());
        }
    }
}
