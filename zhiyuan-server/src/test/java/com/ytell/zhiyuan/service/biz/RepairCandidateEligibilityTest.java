package com.ytell.zhiyuan.service.biz;

import com.google.common.collect.Lists;
import com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningUnitDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningUnitMajorDTO;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

public class RepairCandidateEligibilityTest {

    @Test
    void shouldRejectCandidateBySchoolNatureScope() {
        PlanningStateDTO state = new PlanningStateDTO();
        state.getConstraintState().getHardConstraints().setMustExcludeSchools(Lists.newArrayList("院校性质:民办"));
        CandidateItemDTO privateCandidate = candidate("民办", "综合", "软件工程");
        CandidateItemDTO publicCandidate = candidate("公办", "综合", "软件工程");

        assertFalse(RepairCandidateEligibility.isEligibleForConfirmedHardConstraints(privateCandidate, state));
        assertTrue(RepairCandidateEligibility.isEligibleForConfirmedHardConstraints(publicCandidate, state));
    }

    @Test
    void shouldRequirePlanningUnitBySchoolNatureScope() {
        PlanningStateDTO state = new PlanningStateDTO();
        state.getConstraintState().getHardConstraints().setMustIncludeSchools(Lists.newArrayList("院校性质:公办"));
        PlanningUnitDTO privateUnit = unit("民办", "财经", "金融学");
        PlanningUnitDTO publicUnit = unit("公办", "财经", "金融学");

        assertFalse(RepairCandidateEligibility.isEligibleForConfirmedHardConstraints(privateUnit, state));
        assertTrue(RepairCandidateEligibility.isEligibleForConfirmedHardConstraints(publicUnit, state));
    }

    @Test
    void shouldRejectCandidateByProgramTypeScope() {
        PlanningStateDTO state = new PlanningStateDTO();
        state.getConstraintState().getHardConstraints().setMustExcludeSchools(Lists.newArrayList("招生类型:中外合作"));
        CandidateItemDTO cooperativeCandidate = candidate("公办", "理工", "软件工程(中外合作办学)");
        cooperativeCandidate.getReasonCodes().add("中外合作办学");
        CandidateItemDTO normalCandidate = candidate("公办", "理工", "软件工程");

        assertFalse(RepairCandidateEligibility.isEligibleForConfirmedHardConstraints(cooperativeCandidate, state));
        assertTrue(RepairCandidateEligibility.isEligibleForConfirmedHardConstraints(normalCandidate, state));
    }

    @Test
    void shouldRejectPlanningUnitByProgramTypeScopeFromMajorTags() {
        PlanningStateDTO state = new PlanningStateDTO();
        state.getConstraintState().getHardConstraints().setMustExcludeSchools(Lists.newArrayList("招生类型:中外合作"));
        PlanningUnitDTO cooperativeUnit = unit("公办", "理工", "软件工程");
        cooperativeUnit.getSelectedMajors().get(0).getReasonCodes().add("中外合作办学");
        PlanningUnitDTO normalUnit = unit("公办", "理工", "软件工程");

        assertFalse(RepairCandidateEligibility.isEligibleForConfirmedHardConstraints(cooperativeUnit, state));
        assertTrue(RepairCandidateEligibility.isEligibleForConfirmedHardConstraints(normalUnit, state));
    }

    @Test
    void shouldRequireCandidateByStrongbaseProgramTypeScope() {
        PlanningStateDTO state = new PlanningStateDTO();
        state.getConstraintState().getHardConstraints().setMustIncludeSchools(Lists.newArrayList("招生类型:强基"));
        CandidateItemDTO strongbaseCandidate = candidate("公办", "综合", "数学与应用数学");
        strongbaseCandidate.getReasonCodes().add("强基计划");
        CandidateItemDTO normalCandidate = candidate("公办", "综合", "数学与应用数学");

        assertTrue(RepairCandidateEligibility.isEligibleForConfirmedHardConstraints(strongbaseCandidate, state));
        assertFalse(RepairCandidateEligibility.isEligibleForConfirmedHardConstraints(normalCandidate, state));
    }

    private CandidateItemDTO candidate(String schoolNature, String schoolCategory, String majorName) {
        CandidateItemDTO candidate = new CandidateItemDTO();
        candidate.setSchoolName("测试大学");
        candidate.setSchoolNature(schoolNature);
        candidate.setSchoolCategory(schoolCategory);
        candidate.setSchoolLevel("本科");
        candidate.setProvinceName("广东");
        candidate.setMajorName(majorName);
        return candidate;
    }

    private PlanningUnitDTO unit(String schoolNature, String schoolCategory, String majorName) {
        PlanningUnitDTO unit = new PlanningUnitDTO();
        unit.setSchoolName("测试大学");
        unit.setSchoolNature(schoolNature);
        unit.setSchoolCategory(schoolCategory);
        unit.setSchoolLevel("本科");
        unit.setProvinceName("广东");
        PlanningUnitMajorDTO major = new PlanningUnitMajorDTO();
        major.setMajorName(majorName);
        unit.setSelectedMajors(Lists.newArrayList(major));
        return unit;
    }
}
