package com.ytell.zhiyuan.service.biz;

import com.ytell.zhiyuan.model.dto.planning.HardConstraintsDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import com.ytell.zhiyuan.model.dto.planning.StructureTargetDTO;
import org.junit.jupiter.api.Test;

import java.util.Arrays;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

class SafetyFloorSupportTest {

    @Test
    void scoreAtLeast580HasNoLocalFloor() {
        PlanningStateDTO state = state(600, "浙江");
        StructureTargetDTO target = SafetyFloorSupport.build(state);
        assertEquals(0, target.getMinLocalProtect());
        assertEquals("score_ge_580", target.getSafetyFloorReasonCode());
    }

    @Test
    void missingScoreIsTreatedAsAtRiskLikeReview() {
        PlanningStateDTO state = state(null, "浙江");
        StructureTargetDTO target = SafetyFloorSupport.build(state);
        assertEquals(2, target.getMinLocalProtect());
    }

    @Test
    void missingProvinceIsUnknownNotZeroFloor() {
        PlanningStateDTO state = state(550, null);
        StructureTargetDTO target = SafetyFloorSupport.build(state);
        assertEquals(0, target.getMinLocalProtect());
        assertEquals("unknown", target.getSafetyFloorMode());
        assertEquals("province_missing", target.getSafetyFloorReasonCode());
    }

    @Test
    void provinceExclusionIsRecordedButJ54GateKeepsOldFloor() {
        PlanningStateDTO state = state(550, "浙江");
        HardConstraintsDTO hard = new HardConstraintsDTO();
        hard.setMustExcludeRegions(Arrays.asList("浙江"));
        state.getConstraintState().setHardConstraints(hard);

        StructureTargetDTO target = SafetyFloorSupport.build(state);

        assertEquals(2, target.getMinLocalProtect());
        assertEquals("province_excluded_pending_j54", target.getSafetyFloorReasonCode());
        assertTrue(target.getDiagnostics().contains("safety_floor_not_applicable_pending_j54"));
    }

    private PlanningStateDTO state(Integer score, String province) {
        PlanningStateDTO state = new PlanningStateDTO();
        state.getCandidatePoolState().setUserScore(score);
        state.getCandidatePoolState().setSourceProvinceName(province);
        return state;
    }
}
