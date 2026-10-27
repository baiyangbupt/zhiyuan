package com.ytell.zhiyuan.service.biz;

import com.google.common.collect.Lists;
import com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO;
import com.ytell.zhiyuan.model.dto.planning.CandidatePoolStateDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

class SpecialPlanRequirementSupportTest {

    @Test
    void explicitSpecialPlanNameConflictsWithUserNoSpecial() {
        CandidateItemDTO item = candidate("计算机（国家专项）", Lists.newArrayList());

        SpecialPlanRequirementSupport.Requirement requirement =
                SpecialPlanRequirementSupport.requirement(item);

        assertTrue(requirement.anyExplicit());
        assertTrue(SpecialPlanRequirementSupport.conflictsWithNoSpecial(false, requirement));
        assertFalse(SpecialPlanRequirementSupport.conflictsWithNoSpecial(true, requirement));
        assertFalse(SpecialPlanRequirementSupport.conflictsWithNoSpecial(null, requirement));
    }

    @Test
    void planTagAloneIsEnoughForConflict() {
        CandidateItemDTO item = candidate("计算机", Lists.newArrayList("地方专项"));

        assertTrue(SpecialPlanRequirementSupport.conflictsWithNoSpecial(
                false, SpecialPlanRequirementSupport.requirement(item)));
    }

    @Test
    void ambiguousSpecialWordIsUnknownAndDoesNotBecomeAConflict() {
        CandidateItemDTO item = candidate("定向培养专项", Lists.newArrayList());

        SpecialPlanRequirementSupport.Requirement requirement =
                SpecialPlanRequirementSupport.requirement(item);

        assertTrue(requirement.isUnknown());
        assertFalse(SpecialPlanRequirementSupport.conflictsWithNoSpecial(false, requirement));
    }

    @Test
    void ambiguousQualificationTagsRemainUnknownRatherThanExplicitSpecialPlans() {
        for (String tag : Lists.newArrayList("公费定向", "定向培养", "公费师范生", "楚怡工匠")) {
            SpecialPlanRequirementSupport.Requirement requirement =
                    SpecialPlanRequirementSupport.requirement(candidate("计算机", Lists.newArrayList(tag)));

            assertTrue(requirement.isUnknown(), tag);
            assertFalse(requirement.anyExplicit(), tag);
            assertFalse(SpecialPlanRequirementSupport.conflictsWithNoSpecial(false, requirement), tag);
        }
    }

    @Test
    void negatedPlanTagsDoNotInventQualificationRequirements() {
        for (String tag : Lists.newArrayList("非专项计划", "非专项", "非专项招生", "非定向", "非定向就业", "非公费",
                "非国家专项", "非地方专项", "非高校专项")) {
            SpecialPlanRequirementSupport.Requirement requirement =
                    SpecialPlanRequirementSupport.requirement(candidate("计算机", Lists.newArrayList(tag)));

            assertFalse(requirement.anyExplicit(), tag);
            assertFalse(requirement.isUnknown(), tag);
            assertFalse(requirement.evidenceConflict(), tag);
        }
    }

    @Test
    void negatedTagDoesNotEraseIndependentExplicitRequirement() {
        SpecialPlanRequirementSupport.Requirement requirement = SpecialPlanRequirementSupport.requirement(
                candidate("计算机（国家专项）", Lists.newArrayList("非专项计划")));

        assertTrue(requirement.anyExplicit());
        assertTrue(requirement.evidenceConflict());
        assertTrue(SpecialPlanRequirementSupport.conflictsWithNoSpecial(false, requirement));
    }

    @Test
    void formalOrdinaryTagAndSpecialNameAreEvidenceConflict() {
        CandidateItemDTO item = candidate("地方专项计划", Lists.newArrayList("普通类"));

        SpecialPlanRequirementSupport.Requirement requirement =
                SpecialPlanRequirementSupport.requirement(item);

        assertTrue(requirement.evidenceConflict());
        assertTrue(SpecialPlanRequirementSupport.conflictsWithNoSpecial(false, requirement));
    }

    private CandidateItemDTO candidate(String majorName, java.util.List<String> tags) {
        CandidateItemDTO item = new CandidateItemDTO();
        item.setVolunteerId("v1");
        item.setMajorName(majorName);
        item.setMajorPlanTags(tags);
        return item;
    }
}
