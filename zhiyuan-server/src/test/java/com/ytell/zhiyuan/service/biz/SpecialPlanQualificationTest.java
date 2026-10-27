package com.ytell.zhiyuan.service.biz;

import com.google.common.collect.Lists;
import com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO;
import com.ytell.zhiyuan.model.dto.planning.CandidatePoolStateDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedItemDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedUnitDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningUnitMajorDTO;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

class SpecialPlanQualificationTest {

    @Test
    void filtersOnlyKnownConflictsWhenUserExplicitlyHasNoSpecialPlan() {
        CandidateItemDTO conflict = candidate("v1", "计算机（国家专项）", Lists.newArrayList());
        CandidateItemDTO clean = candidate("v2", "计算机", Lists.newArrayList());

        java.util.List<CandidateItemDTO> filtered = SpecialPlanQualification.filterKnownConflicts(
                Lists.newArrayList(conflict, clean), Boolean.FALSE);

        assertFalse(filtered.contains(conflict));
        assertTrue(filtered.contains(clean));
        assertTrue(SpecialPlanQualification.filterKnownConflicts(
                Lists.newArrayList(conflict), null).contains(conflict));
    }

    @Test
    void formalTagsOnOrderedUnitAreInheritedForConflictCheck() {
        PlanningStateDTO state = new PlanningStateDTO();
        CandidatePoolStateDTO pool = new CandidatePoolStateDTO();
        pool.setSpecialPlan(false);
        state.setCandidatePoolState(pool);
        OrderedUnitDTO unit = new OrderedUnitDTO();
        unit.setUnitId("u1");
        unit.setSchoolName("某大学");
        PlanningUnitMajorDTO major = new PlanningUnitMajorDTO();
        major.setMajorName("计算机");
        major.setMajorPlanTags(Lists.newArrayList("地方专项"));
        unit.getMajorItems().add(major);
        state.getOrderedPlanState().getUnits().add(unit);

        assertTrue(SpecialPlanQualification.stateHasConflict(state));
    }

    @Test
    void unknownSpecialPlanDoesNotEnterNewSelection() {
        PlanningStateDTO state = new PlanningStateDTO();
        CandidatePoolStateDTO pool = new CandidatePoolStateDTO();
        pool.setSpecialPlan(null);
        state.setCandidatePoolState(pool);
        OrderedItemDTO item = new OrderedItemDTO();
        item.setVolunteerId("v1");
        item.setMajorName("计算机（国家专项）");
        state.getOrderedPlanState().getItems().add(item);

        assertTrue(SpecialPlanQualification.stateHasUnknownSpecialPlan(state));
        assertTrue(SpecialPlanQualification.blocksNewSelection(state));
    }

    @Test
    void stateGateDetectsConflictThatPureRemoveMustNotUse() {
        PlanningStateDTO state = new PlanningStateDTO();
        CandidatePoolStateDTO pool = new CandidatePoolStateDTO();
        pool.setSpecialPlan(false);
        state.setCandidatePoolState(pool);
        OrderedItemDTO item = new OrderedItemDTO();
        item.setVolunteerId("v1");
        item.setMajorName("计算机（高校专项）");
        state.getOrderedPlanState().getItems().add(item);

        assertTrue(SpecialPlanQualification.stateHasConflict(state));
    }

    private CandidateItemDTO candidate(String id, String majorName, java.util.List<String> tags) {
        CandidateItemDTO item = new CandidateItemDTO();
        item.setVolunteerId(id);
        item.setMajorName(majorName);
        item.setMajorPlanTags(tags);
        return item;
    }
}
