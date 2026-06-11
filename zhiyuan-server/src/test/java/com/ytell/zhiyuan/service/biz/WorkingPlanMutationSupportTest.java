package com.ytell.zhiyuan.service.biz;

import com.google.common.collect.Lists;
import com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO;
import com.ytell.zhiyuan.model.dto.planning.CandidatePoolStateDTO;
import com.ytell.zhiyuan.model.dto.planning.DraftItemDTO;
import com.ytell.zhiyuan.model.dto.planning.DraftPlanStateDTO;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

public class WorkingPlanMutationSupportTest {

    @Test
    void shouldMatchLegacyVolunteerIdentityWhenCheckingWorkingPlanAndBannedIds() {
        DraftPlanStateDTO draft = new DraftPlanStateDTO();
        draft.getItems().add(draftItem("unit1_major__old", "保"));

        assertTrue(WorkingPlanMutationSupport.containsWorkingPlanItem(draft, "unit1_major__new"));
        assertTrue(WorkingPlanMutationSupport.containsVolunteerId(Lists.newArrayList("unit2_major_a"), "unit2_major_b"));
        assertFalse(WorkingPlanMutationSupport.containsWorkingPlanItem(draft, "unit3_major__new"));
    }

    @Test
    void shouldBuildWorkingPlanItemFromCandidate() {
        CandidateItemDTO candidate = candidate("major_a", "unit_a", "稳", 90D, 60D, 50D);

        DraftItemDTO item = WorkingPlanMutationSupport.buildWorkingPlanItem(candidate, "fix_proposal", true);

        assertEquals("major_a", item.getVolunteerId());
        assertEquals("稳", item.getTier());
        assertEquals("测试大学", item.getSchoolName());
        assertEquals("测试专业major_a", item.getMajorName());
        assertEquals("fix_proposal", item.getSource());
        assertTrue(Boolean.TRUE.equals(item.getLocked()));
    }

    @Test
    void shouldAddWorkingPlanItemOnlyWhenAllowed() {
        DraftPlanStateDTO draft = new DraftPlanStateDTO();
        CandidateItemDTO candidate = candidate("major_a", "unit_a", "稳", 90D, 60D, 50D);

        assertTrue(WorkingPlanMutationSupport.addWorkingPlanItemIfAllowed(draft, candidate, "compensation"));
        assertEquals(1, draft.getItems().size());
        assertEquals("compensation", draft.getItems().get(0).getSource());
        assertFalse(WorkingPlanMutationSupport.addWorkingPlanItemIfAllowed(draft, candidate, "compensation"));

        DraftPlanStateDTO bannedDraft = new DraftPlanStateDTO();
        bannedDraft.getBannedVolunteerIds().add("unit_b_major_1");
        CandidateItemDTO bannedCandidate = candidate("unit_b_major_2", "unit_b", "稳", 80D, 50D, 40D);

        assertFalse(WorkingPlanMutationSupport.addWorkingPlanItemIfAllowed(bannedDraft, bannedCandidate, "compensation"));
        assertTrue(bannedDraft.getItems().isEmpty());
    }

    @Test
    void shouldResolveCandidateByLegacyPrefixOnlyWhenUnambiguous() {
        CandidateItemDTO candidate = candidate("unit_a_major_new", "unit_a", "稳", 90D, 60D, 50D);
        assertEquals(candidate, WorkingPlanMutationSupport.findCandidate(
                Lists.newArrayList(candidate), "unit_a_major_old"));

        CandidateItemDTO duplicate = candidate("unit_a_major_other", "unit_a", "保", 80D, 70D, 40D);
        assertNull(WorkingPlanMutationSupport.findCandidate(Lists.newArrayList(candidate, duplicate), "unit_a_major_old"));
    }

    @Test
    void shouldSyncMajorGroupUnitsAndRecalculateSummaryByUnit() {
        CandidatePoolStateDTO candidatePoolState = new CandidatePoolStateDTO();
        candidatePoolState.setVolunteerModel("majorGroup");
        candidatePoolState.setRequiredCount(2);

        DraftPlanStateDTO draft = new DraftPlanStateDTO();
        draft.getItems().add(draftItem("major_a", "保"));
        draft.getItems().add(draftItem("major_b", "保"));

        CandidateItemDTO candidateA = candidate("major_a", "unit_a", "保", 70D, 60D, 50D);
        CandidateItemDTO candidateB = candidate("major_b", "unit_a", "保", 80D, 40D, 30D);

        WorkingPlanMutationSupport.syncWorkingPlanUnitsWithItems(
                draft, Lists.newArrayList(candidateA, candidateB), candidatePoolState);
        WorkingPlanMutationSupport.recalculateWorkingPlanSummary(draft, candidatePoolState);

        assertEquals(1, draft.getUnits().size());
        assertEquals("unit_a", draft.getUnits().get(0).getUnitId());
        assertEquals(2, draft.getUnits().get(0).getMajorItems().size());
        assertEquals("major_b", draft.getUnits().get(0).getMajorItems().get(0).getVolunteerId());
        assertTrue(Boolean.TRUE.equals(draft.getUnits().get(0).getMajorItems().get(1).getSafetyMajor()));
        assertEquals(Integer.valueOf(1), draft.getSummary().getTotal());
        assertEquals(Integer.valueOf(2), draft.getSummary().getTargetCount());
        assertEquals(Integer.valueOf(1), draft.getSummary().getTierCounts().get("保"));
    }

    private DraftItemDTO draftItem(String volunteerId, String tier) {
        DraftItemDTO item = new DraftItemDTO();
        item.setVolunteerId(volunteerId);
        item.setTier(tier);
        item.setSchoolName("测试大学");
        item.setMajorName("测试专业" + volunteerId);
        return item;
    }

    private CandidateItemDTO candidate(String volunteerId,
                                       String unitId,
                                       String tier,
                                       Double finalScore,
                                       Double admissionRatio,
                                       Double intentScore) {
        CandidateItemDTO candidate = new CandidateItemDTO();
        candidate.setVolunteerId(volunteerId);
        candidate.setPlanSchoolDataId(unitId);
        candidate.setTier(tier);
        candidate.setSchoolName("测试大学");
        candidate.setMajorName("测试专业" + volunteerId);
        candidate.setFinalScore(finalScore);
        candidate.setAdmissionRatio(admissionRatio);
        candidate.setSchoolEnrollRatio(50D);
        candidate.setIntentScore(intentScore);
        return candidate;
    }
}
