package com.ytell.zhiyuan.service.biz;

import com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO;
import com.ytell.zhiyuan.model.dto.planning.HardConstraintsDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedItemDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import com.ytell.zhiyuan.model.dto.planning.ReviewCheckDTO;
import org.junit.jupiter.api.Test;

import java.util.Arrays;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

class ReviewSafetyGuardTest {

    @Test
    void excludedSourceProvinceMakesGuardPass() {
        PlanningStateDTO state = state(550, "浙江");
        state.getOrderedPlanState().getItems().add(ordered("v1", "保"));
        state.getCandidatePoolState().getItems().add(candidate("v1", "浙江"));
        state.getConstraintState().setHardConstraints(hard("浙江", null));

        ReviewCheckDTO check = ReviewSafetyGuard.evaluate(
                state, state.getCandidatePoolState().getItems());

        assertTrue(Boolean.TRUE.equals(check.getPassed()));
        assertEquals("info", check.getLevel());
        assertTrue(check.getSummary().contains("不适用"));
    }

    @Test
    void excludedSourceProvinceByIdMakesGuardPass() {
        PlanningStateDTO state = state(550, "浙江");
        state.getOrderedPlanState().getItems().add(ordered("v1", "保"));
        CandidateItemDTO local = candidate("v1", "浙江");
        local.setProvinceId("330000");
        state.getCandidatePoolState().getItems().add(local);
        state.getConstraintState().setHardConstraints(hard(null, "330000"));

        ReviewCheckDTO check = ReviewSafetyGuard.evaluate(
                state, state.getCandidatePoolState().getItems());

        assertTrue(Boolean.TRUE.equals(check.getPassed()));
        assertTrue(check.getSummary().contains("不适用"));
    }

    @Test
    void lowScoreNeedsTwoLocalProtectItems() {
        PlanningStateDTO state = state(550, "浙江");
        state.getOrderedPlanState().getItems().add(ordered("v1", "保"));
        state.getCandidatePoolState().getItems().add(candidate("v1", "浙江"));

        ReviewCheckDTO check = ReviewSafetyGuard.evaluate(
                state, state.getCandidatePoolState().getItems());

        assertFalse(Boolean.TRUE.equals(check.getPassed()));
        assertEquals("risk", check.getLevel());
        assertTrue(check.getDetail().contains("少于2所"));
    }

    @Test
    void twoLocalProtectItemsPass() {
        PlanningStateDTO state = state(550, "浙江");
        state.getOrderedPlanState().getItems().add(ordered("v1", "保"));
        state.getOrderedPlanState().getItems().add(ordered("v2", "保"));
        state.getCandidatePoolState().getItems().add(candidate("v1", "浙江"));
        state.getCandidatePoolState().getItems().add(candidate("v2", "浙江省"));

        ReviewCheckDTO check = ReviewSafetyGuard.evaluate(
                state, state.getCandidatePoolState().getItems());

        assertTrue(Boolean.TRUE.equals(check.getPassed()));
        assertTrue(check.getDetail().contains("不少于2所"));
    }

    @Test
    void scoreAtLeast580PassesWithoutLocalProtect() {
        PlanningStateDTO state = state(600, "浙江");

        ReviewCheckDTO check = ReviewSafetyGuard.evaluate(
                state, state.getCandidatePoolState().getItems());

        assertTrue(Boolean.TRUE.equals(check.getPassed()));
        assertEquals("info", check.getLevel());
    }

    @Test
    void missingProvinceStaysWarn() {
        PlanningStateDTO state = state(550, null);

        ReviewCheckDTO check = ReviewSafetyGuard.evaluate(
                state, state.getCandidatePoolState().getItems());

        assertTrue(Boolean.TRUE.equals(check.getPassed()));
        assertEquals("warn", check.getLevel());
    }

    private PlanningStateDTO state(Integer score, String province) {
        PlanningStateDTO state = new PlanningStateDTO();
        state.getCandidatePoolState().setVolunteerModel("major");
        state.getCandidatePoolState().setUserScore(score);
        state.getCandidatePoolState().setSourceProvinceName(province);
        return state;
    }

    private CandidateItemDTO candidate(String volunteerId, String province) {
        CandidateItemDTO candidate = new CandidateItemDTO();
        candidate.setVolunteerId(volunteerId);
        candidate.setProvinceName(province);
        return candidate;
    }

    private OrderedItemDTO ordered(String volunteerId, String tier) {
        OrderedItemDTO item = new OrderedItemDTO();
        item.setVolunteerId(volunteerId);
        item.setTier(tier);
        return item;
    }

    private HardConstraintsDTO hard(String excludedName, String excludedId) {
        HardConstraintsDTO hard = new HardConstraintsDTO();
        if (excludedName != null) {
            hard.setMustExcludeRegions(Arrays.asList(excludedName));
        }
        if (excludedId != null) {
            hard.setMustExcludeRegionIds(Arrays.asList(excludedId));
        }
        return hard;
    }
}
