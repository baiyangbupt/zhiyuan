package com.ytell.zhiyuan.service.biz;

import com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO;
import com.ytell.zhiyuan.model.dto.planning.HardConstraintsDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import com.ytell.zhiyuan.model.dto.planning.StructureTargetDTO;
import org.junit.jupiter.api.Test;

import java.util.Arrays;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;

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
    void excludedSourceProvinceMakesSafetyFloorNotApplicable() {
        PlanningStateDTO state = state(550, "浙江");
        state.getConstraintState().setHardConstraints(hard("浙江"));

        StructureTargetDTO target = SafetyFloorSupport.build(state);

        assertEquals(0, target.getMinLocalProtect());
        assertEquals("not_applicable", target.getSafetyFloorMode());
        assertEquals("province_excluded", target.getSafetyFloorReasonCode());
        assertFalse(target.getDiagnostics().contains("safety_floor_not_applicable_pending_j54"));
    }

    @Test
    void excludedSourceProvinceUsesSharedRegionIdentityMatching() {
        // 与 RepairCandidateEligibility 同源：规范化身份相等（"浙江省"＝"浙江"），不是双向子串。
        PlanningStateDTO state = state(550, "浙江省");
        state.getConstraintState().setHardConstraints(hard("浙江"));

        StructureTargetDTO target = SafetyFloorSupport.build(state);

        assertEquals(0, target.getMinLocalProtect());
        assertEquals("not_applicable", target.getSafetyFloorMode());
        assertEquals("province_excluded", target.getSafetyFloorReasonCode());
    }

    @Test
    void excludedSourceProvinceIsNotApplicableRegardlessOfScore() {
        PlanningStateDTO state = state(600, "浙江");
        state.getConstraintState().setHardConstraints(hard("浙江"));

        StructureTargetDTO target = SafetyFloorSupport.build(state);

        assertEquals(0, target.getMinLocalProtect());
        assertEquals("not_applicable", target.getSafetyFloorMode());
        assertEquals("province_excluded", target.getSafetyFloorReasonCode());
    }

    @Test
    void excludedSourceProvinceByIdMakesNotApplicable() {
        PlanningStateDTO state = state(550, "浙江");
        HardConstraintsDTO hard = new HardConstraintsDTO();
        hard.setMustExcludeRegionIds(Arrays.asList("330000"));
        state.getConstraintState().setHardConstraints(hard);
        CandidateItemDTO local = new CandidateItemDTO();
        local.setVolunteerId("v1");
        local.setProvinceId("330000");
        local.setProvinceName("浙江");
        state.getCandidatePoolState().getItems().add(local);

        StructureTargetDTO target = SafetyFloorSupport.build(state);

        assertEquals(0, target.getMinLocalProtect());
        assertEquals("not_applicable", target.getSafetyFloorMode());
        assertEquals("province_excluded", target.getSafetyFloorReasonCode());
    }

    @Test
    void nonExcludedProvinceWithLowScoreKeepsNormalFloor() {
        PlanningStateDTO state = state(550, "浙江");
        state.getConstraintState().setHardConstraints(hard("江苏"));

        StructureTargetDTO target = SafetyFloorSupport.build(state);

        assertEquals(2, target.getMinLocalProtect());
        assertEquals("applicable", target.getSafetyFloorMode());
        assertEquals("local_protect_floor", target.getSafetyFloorReasonCode());
    }

    private HardConstraintsDTO hard(String... excludes) {
        HardConstraintsDTO hard = new HardConstraintsDTO();
        hard.setMustExcludeRegions(Arrays.asList(excludes));
        return hard;
    }

    private PlanningStateDTO state(Integer score, String province) {
        PlanningStateDTO state = new PlanningStateDTO();
        state.getCandidatePoolState().setUserScore(score);
        state.getCandidatePoolState().setSourceProvinceName(province);
        return state;
    }
}
