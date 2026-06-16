package com.ytell.zhiyuan.service.biz;

import com.google.common.collect.Lists;
import com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO;
import com.ytell.zhiyuan.model.dto.planning.CompensationActionDTO;
import com.ytell.zhiyuan.model.dto.planning.DraftItemDTO;
import com.ytell.zhiyuan.model.dto.planning.FixProposalActionDTO;
import com.ytell.zhiyuan.model.dto.planning.FixProposalDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import com.ytell.zhiyuan.model.dto.planning.ReplacementPairDTO;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

public class RepairApplyMutationBuilderTest {

    @Test
    void shouldApplyWorkingPlanAdditionActionsWithLegacyCandidateResolutionAndBannedSkip() {
        PlanningStateDTO state = new PlanningStateDTO();
        state.getWorkingPlanState().getBannedVolunteerIds().add("unit_b_major_old");
        CompensationActionDTO action = compensationAction("fill_total_count",
                Lists.newArrayList("unit_a_major_old", "unit_b_major_new"));

        RepairApplyMutationBuilder.MutationResult result = RepairApplyMutationBuilder.applyWorkingPlanAdditionActions(
                state,
                Lists.newArrayList(
                        candidate("unit_a_major_new", "unit_a", "稳", 70D, 40D),
                        candidate("unit_b_major_candidate", "unit_b", "保", 80D, 60D)),
                Lists.newArrayList(action));

        assertEquals(1, state.getWorkingPlanState().getItems().size());
        assertEquals("unit_a_major_new", state.getWorkingPlanState().getItems().get(0).getVolunteerId());
        assertEquals(Lists.newArrayList("unit_a_major_new"), result.getAddedVolunteerIds());
        assertEquals(1, result.getAppliedCompensationActions().size());
        assertEquals("fix_add_items", state.getOperationLogs().get(0).getType());
    }

    @Test
    void shouldRemoveRiskItemsAndFillMissingCountInWorkingPlan() {
        PlanningStateDTO state = new PlanningStateDTO();
        state.getWorkingPlanState().getItems().add(draftItem("risk_1", "冲"));
        state.getWorkingPlanState().getItems().add(draftItem("safe_1", "稳"));
        state.getCandidatePoolState().setRequiredCount(2);

        FixProposalDTO proposal = new FixProposalDTO();
        proposal.setTitle("移除风险志愿并补足数量");
        proposal.setAffectedVolunteerIds(Lists.newArrayList("risk_1"));
        FixProposalActionDTO remove = new FixProposalActionDTO();
        remove.setActionType("remove_volunteers");
        remove.setVolunteerIds(Lists.newArrayList("risk_1"));
        FixProposalActionDTO add = new FixProposalActionDTO();
        add.setActionType("fill_total_count");
        add.setVolunteerIds(Lists.newArrayList("fill_1"));
        proposal.setActions(Lists.newArrayList(remove, add));

        RepairApplyMutationBuilder.MutationResult result = RepairApplyMutationBuilder.applyRemoveRiskItems(
                state,
                Lists.newArrayList(
                        candidate("risk_1", "risk_unit", "冲", 30D, 5D),
                        candidate("safe_1", "safe_unit", "稳", 70D, 50D),
                        candidate("fill_1", "fill_unit", "保", 80D, 70D)),
                proposal);

        assertEquals(Lists.newArrayList("risk_1"), result.getRemovedVolunteerIds());
        assertEquals(Lists.newArrayList("fill_1"), result.getAddedVolunteerIds());
        assertEquals(2, state.getWorkingPlanState().getItems().size());
        assertEquals(Integer.valueOf(2), state.getWorkingPlanState().getSummary().getTotal());
        assertTrue(state.getWorkingPlanState().getItems().stream().noneMatch(item -> "risk_1".equals(item.getVolunteerId())));
        assertTrue(state.getWorkingPlanState().getItems().stream().anyMatch(item -> "fill_1".equals(item.getVolunteerId())));
        assertEquals("fix_add_items", state.getOperationLogs().get(0).getType());
        assertEquals("fix_remove_risk_items", state.getOperationLogs().get(1).getType());
    }

    @Test
    void shouldApplyMajorGroupInnerSafetyAndRecalculateUnitSummary() {
        PlanningStateDTO state = new PlanningStateDTO();
        state.getCandidatePoolState().setVolunteerModel("majorGroup");
        state.getCandidatePoolState().setRequiredCount(1);
        state.getWorkingPlanState().getItems().add(draftItem("unit_a_bad", "冲"));

        FixProposalDTO proposal = new FixProposalDTO();
        proposal.setTitle("补充专业组内安全专业");
        FixProposalActionDTO action = new FixProposalActionDTO();
        action.setActionType("adjust_major_group_inner_safety");
        action.setRemoveVolunteerIds(Lists.newArrayList("unit_a_bad"));
        action.setCandidateVolunteerIds(Lists.newArrayList("unit_a_safe"));
        proposal.setActions(Lists.newArrayList(action));

        RepairApplyMutationBuilder.MutationResult result = RepairApplyMutationBuilder.applyMajorGroupInnerSafety(
                state,
                Lists.newArrayList(
                        candidate("unit_a_bad", "unit_a", "冲", 30D, 20D),
                        candidate("unit_a_safe", "unit_a", "保", 80D, 60D)),
                proposal);

        assertEquals(Lists.newArrayList("unit_a_bad"), result.getRemovedVolunteerIds());
        assertEquals(Lists.newArrayList("unit_a_safe"), result.getAddedVolunteerIds());
        assertEquals(1, state.getWorkingPlanState().getItems().size());
        assertEquals("unit_a_safe", state.getWorkingPlanState().getItems().get(0).getVolunteerId());
        assertEquals(1, state.getWorkingPlanState().getUnits().size());
        assertEquals(Integer.valueOf(1), state.getWorkingPlanState().getSummary().getTotal());
        assertTrue(Boolean.TRUE.equals(state.getWorkingPlanState().getUnits().get(0).getMajorItems().get(0).getSafetyMajor()));
        assertEquals("fix_major_group_inner_safety", state.getOperationLogs().get(0).getType());
    }

    @Test
    void shouldApplyReplaceVolunteersAtomicallyInProfessionalMode() {
        PlanningStateDTO state = new PlanningStateDTO();
        state.getCandidatePoolState().setRequiredCount(2);
        state.getWorkingPlanState().getItems().add(draftItem("risk_1", "冲"));
        state.getWorkingPlanState().getItems().add(draftItem("safe_1", "稳"));

        FixProposalDTO proposal = replaceProposal("替换风险志愿",
                Lists.newArrayList("risk_1"), Lists.newArrayList("replacement_1"));

        RepairApplyMutationBuilder.MutationResult result = RepairApplyMutationBuilder.applyReplaceVolunteers(
                state,
                Lists.newArrayList(
                        candidate("risk_1", "risk_unit", "冲", 30D, 5D),
                        candidate("safe_1", "safe_unit", "稳", 70D, 50D),
                        candidate("replacement_1", "replacement_unit", "冲", 75D, 45D)),
                proposal);

        assertEquals("applied", result.getStatus());
        assertEquals(Lists.newArrayList("risk_1"), result.getRemovedVolunteerIds());
        assertEquals(Lists.newArrayList("replacement_1"), result.getAddedVolunteerIds());
        assertEquals(2, state.getWorkingPlanState().getItems().size());
        assertTrue(state.getWorkingPlanState().getItems().stream().noneMatch(item -> "risk_1".equals(item.getVolunteerId())));
        assertTrue(state.getWorkingPlanState().getItems().stream().anyMatch(item -> "replacement_1".equals(item.getVolunteerId())));
        assertEquals("fix_replace_volunteers", state.getOperationLogs().get(0).getType());
    }

    @Test
    void shouldApplyReplaceVolunteersByUnitInMajorGroupMode() {
        PlanningStateDTO state = new PlanningStateDTO();
        state.getCandidatePoolState().setVolunteerModel("majorGroup");
        state.getCandidatePoolState().setRequiredCount(1);
        state.getWorkingPlanState().getItems().add(draftItem("unita_m1", "冲"));
        state.getWorkingPlanState().getItems().add(draftItem("unita_m2", "冲"));

        FixProposalDTO proposal = replaceProposal("替换风险专业组",
                Lists.newArrayList("unita_m1", "unita_m2"),
                Lists.newArrayList("unitb_m1", "unitb_m2"));

        RepairApplyMutationBuilder.MutationResult result = RepairApplyMutationBuilder.applyReplaceVolunteers(
                state,
                Lists.newArrayList(
                        candidate("unita_m1", "unit_a", "冲", 30D, 5D),
                        candidate("unita_m2", "unit_a", "冲", 35D, 8D),
                        candidate("unitb_m1", "unit_b", "冲", 70D, 45D),
                        candidate("unitb_m2", "unit_b", "冲", 72D, 48D)),
                proposal);

        assertEquals("applied", result.getStatus());
        assertEquals(2, result.getRemovedVolunteerIds().size());
        assertEquals(2, result.getAddedVolunteerIds().size());
        assertEquals(2, state.getWorkingPlanState().getItems().size());
        assertEquals(1, state.getWorkingPlanState().getUnits().size());
        assertEquals("unit_b", state.getWorkingPlanState().getUnits().get(0).getUnitId());
        assertEquals(Integer.valueOf(1), state.getWorkingPlanState().getSummary().getTotal());
    }

    @Test
    void shouldApplyReplaceVolunteersFromReplacementPairsOnlyInProfessionalMode() {
        PlanningStateDTO state = new PlanningStateDTO();
        state.getCandidatePoolState().setRequiredCount(2);
        state.getWorkingPlanState().getItems().add(draftItem("risk_1", "冲"));
        state.getWorkingPlanState().getItems().add(draftItem("safe_1", "稳"));

        FixProposalDTO proposal = pairOnlyReplaceProposal("替换风险志愿",
                "risk_1", "replacement_1");

        RepairApplyMutationBuilder.MutationResult result = RepairApplyMutationBuilder.applyReplaceVolunteers(
                state,
                Lists.newArrayList(
                        candidate("risk_1", "risk_unit", "冲", 30D, 5D),
                        candidate("safe_1", "safe_unit", "稳", 70D, 50D),
                        candidate("replacement_1", "replacement_unit", "冲", 75D, 45D)),
                proposal);

        assertEquals("applied", result.getStatus());
        assertEquals(Lists.newArrayList("risk_1"), result.getRemovedVolunteerIds());
        assertEquals(Lists.newArrayList("replacement_1"), result.getAddedVolunteerIds());
        assertEquals(2, state.getWorkingPlanState().getItems().size());
        assertTrue(state.getWorkingPlanState().getItems().stream().noneMatch(item -> "risk_1".equals(item.getVolunteerId())));
        assertTrue(state.getWorkingPlanState().getItems().stream().anyMatch(item -> "replacement_1".equals(item.getVolunteerId())));
        assertEquals("fix_replace_volunteers", state.getOperationLogs().get(0).getType());
    }

    @Test
    void shouldApplyReplaceVolunteersFromReplacementPairsOnlyInMajorGroupMode() {
        PlanningStateDTO state = new PlanningStateDTO();
        state.getCandidatePoolState().setVolunteerModel("majorGroup");
        state.getCandidatePoolState().setRequiredCount(1);
        state.getWorkingPlanState().getItems().add(draftItem("unita_m1", "冲"));
        state.getWorkingPlanState().getItems().add(draftItem("unita_m2", "冲"));

        FixProposalDTO proposal = new FixProposalDTO();
        proposal.setTitle("替换风险专业组");
        FixProposalActionDTO action = new FixProposalActionDTO();
        action.setActionType("replace_volunteers");
        action.getReplacementPairs().add(replacementPair("unita_m1", "unitb_m1"));
        action.getReplacementPairs().add(replacementPair("unita_m2", "unitb_m2"));
        proposal.setActions(Lists.newArrayList(action));

        RepairApplyMutationBuilder.MutationResult result = RepairApplyMutationBuilder.applyReplaceVolunteers(
                state,
                Lists.newArrayList(
                        candidate("unita_m1", "unit_a", "冲", 30D, 5D),
                        candidate("unita_m2", "unit_a", "冲", 35D, 8D),
                        candidate("unitb_m1", "unit_b", "冲", 70D, 45D),
                        candidate("unitb_m2", "unit_b", "冲", 72D, 48D)),
                proposal);

        assertEquals("applied", result.getStatus());
        assertEquals(2, result.getRemovedVolunteerIds().size());
        assertEquals(2, result.getAddedVolunteerIds().size());
        assertEquals(2, state.getWorkingPlanState().getItems().size());
        assertEquals(1, state.getWorkingPlanState().getUnits().size());
        assertEquals("unit_b", state.getWorkingPlanState().getUnits().get(0).getUnitId());
        assertEquals(Integer.valueOf(1), state.getWorkingPlanState().getSummary().getTotal());
    }

    @Test
    void shouldBlockReplaceVolunteersWithoutChangingPlanWhenCandidateIsBanned() {
        PlanningStateDTO state = new PlanningStateDTO();
        state.getWorkingPlanState().getItems().add(draftItem("risk_1", "冲"));
        state.getWorkingPlanState().getBannedVolunteerIds().add("replacement_1");
        FixProposalDTO proposal = replaceProposal("替换风险志愿",
                Lists.newArrayList("risk_1"), Lists.newArrayList("replacement_1"));

        RepairApplyMutationBuilder.MutationResult result = RepairApplyMutationBuilder.applyReplaceVolunteers(
                state,
                Lists.newArrayList(
                        candidate("risk_1", "risk_unit", "冲", 30D, 5D),
                        candidate("replacement_1", "replacement_unit", "冲", 75D, 45D)),
                proposal);

        assertEquals("blocked", result.getStatus());
        assertEquals(1, state.getWorkingPlanState().getItems().size());
        assertEquals("risk_1", state.getWorkingPlanState().getItems().get(0).getVolunteerId());
        assertTrue(state.getOperationLogs().isEmpty());
    }

    @Test
    void shouldBlockReplaceVolunteersWithoutChangingPlanWhenReplacementAlreadyRemainsInPlan() {
        PlanningStateDTO state = new PlanningStateDTO();
        state.getWorkingPlanState().getItems().add(draftItem("risk_1", "冲"));
        state.getWorkingPlanState().getItems().add(draftItem("safe_1", "稳"));
        FixProposalDTO proposal = replaceProposal("替换风险志愿",
                Lists.newArrayList("risk_1"), Lists.newArrayList("safe_1"));

        RepairApplyMutationBuilder.MutationResult result = RepairApplyMutationBuilder.applyReplaceVolunteers(
                state,
                Lists.newArrayList(
                        candidate("risk_1", "risk_unit", "冲", 30D, 5D),
                        candidate("safe_1", "safe_unit", "稳", 70D, 50D)),
                proposal);

        assertEquals("blocked", result.getStatus());
        assertEquals(2, state.getWorkingPlanState().getItems().size());
        assertTrue(state.getWorkingPlanState().getItems().stream().anyMatch(item -> "risk_1".equals(item.getVolunteerId())));
        assertTrue(state.getWorkingPlanState().getItems().stream().anyMatch(item -> "safe_1".equals(item.getVolunteerId())));
        assertTrue(state.getOperationLogs().isEmpty());
    }

    @Test
    void shouldBlockReplaceVolunteersWithoutChangingPlanWhenRemoveSourceIsMissing() {
        PlanningStateDTO state = new PlanningStateDTO();
        state.getWorkingPlanState().getItems().add(draftItem("safe_1", "稳"));
        FixProposalDTO proposal = replaceProposal("替换风险志愿",
                Lists.newArrayList("risk_1"), Lists.newArrayList("replacement_1"));

        RepairApplyMutationBuilder.MutationResult result = RepairApplyMutationBuilder.applyReplaceVolunteers(
                state,
                Lists.newArrayList(
                        candidate("safe_1", "safe_unit", "稳", 70D, 50D),
                        candidate("replacement_1", "replacement_unit", "冲", 75D, 45D)),
                proposal);

        assertEquals("blocked", result.getStatus());
        assertEquals(1, state.getWorkingPlanState().getItems().size());
        assertEquals("safe_1", state.getWorkingPlanState().getItems().get(0).getVolunteerId());
        assertTrue(state.getOperationLogs().isEmpty());
    }

    @Test
    void shouldBlockReplaceVolunteersWithoutChangingPlanWhenReplacementCandidateIsMissing() {
        PlanningStateDTO state = new PlanningStateDTO();
        state.getWorkingPlanState().getItems().add(draftItem("risk_1", "冲"));
        FixProposalDTO proposal = replaceProposal("替换风险志愿",
                Lists.newArrayList("risk_1"), Lists.newArrayList("replacement_1"));

        RepairApplyMutationBuilder.MutationResult result = RepairApplyMutationBuilder.applyReplaceVolunteers(
                state,
                Lists.newArrayList(candidate("risk_1", "risk_unit", "冲", 30D, 5D)),
                proposal);

        assertEquals("blocked", result.getStatus());
        assertEquals(1, state.getWorkingPlanState().getItems().size());
        assertEquals("risk_1", state.getWorkingPlanState().getItems().get(0).getVolunteerId());
        assertTrue(state.getOperationLogs().isEmpty());
    }

    @Test
    void shouldBlockReplaceVolunteersWithoutChangingPlanWhenPairCountsDoNotMatch() {
        PlanningStateDTO state = new PlanningStateDTO();
        state.getWorkingPlanState().getItems().add(draftItem("risk_1", "冲"));
        state.getWorkingPlanState().getItems().add(draftItem("risk_2", "冲"));
        FixProposalDTO proposal = replaceProposal("替换风险志愿",
                Lists.newArrayList("risk_1", "risk_2"), Lists.newArrayList("replacement_1"));

        RepairApplyMutationBuilder.MutationResult result = RepairApplyMutationBuilder.applyReplaceVolunteers(
                state,
                Lists.newArrayList(
                        candidate("risk_1", "risk_unit_1", "冲", 30D, 5D),
                        candidate("risk_2", "risk_unit_2", "冲", 35D, 8D),
                        candidate("replacement_1", "replacement_unit", "稳", 75D, 45D)),
                proposal);

        assertEquals("blocked", result.getStatus());
        assertEquals(2, state.getWorkingPlanState().getItems().size());
        assertTrue(state.getWorkingPlanState().getItems().stream().anyMatch(item -> "risk_1".equals(item.getVolunteerId())));
        assertTrue(state.getWorkingPlanState().getItems().stream().anyMatch(item -> "risk_2".equals(item.getVolunteerId())));
        assertTrue(state.getOperationLogs().isEmpty());
    }

    @Test
    void shouldBlockReplaceVolunteersWithoutChangingPlanWhenReplacementPairIsIncomplete() {
        PlanningStateDTO state = new PlanningStateDTO();
        state.getWorkingPlanState().getItems().add(draftItem("risk_1", "冲"));
        FixProposalDTO proposal = new FixProposalDTO();
        proposal.setTitle("替换风险志愿");
        FixProposalActionDTO action = new FixProposalActionDTO();
        action.setActionType("replace_volunteers");
        ReplacementPairDTO pair = new ReplacementPairDTO();
        pair.setFromVolunteerId("risk_1");
        action.getReplacementPairs().add(pair);
        proposal.setActions(Lists.newArrayList(action));

        RepairApplyMutationBuilder.MutationResult result = RepairApplyMutationBuilder.applyReplaceVolunteers(
                state,
                Lists.newArrayList(candidate("risk_1", "risk_unit", "冲", 30D, 5D)),
                proposal);

        assertEquals("blocked", result.getStatus());
        assertEquals(1, state.getWorkingPlanState().getItems().size());
        assertEquals("risk_1", state.getWorkingPlanState().getItems().get(0).getVolunteerId());
        assertTrue(state.getOperationLogs().isEmpty());
    }

    private CompensationActionDTO compensationAction(String type, java.util.List<String> volunteerIds) {
        CompensationActionDTO action = new CompensationActionDTO();
        action.setType(type);
        action.setSummary("补充候选");
        action.setVolunteerIds(volunteerIds);
        return action;
    }

    private DraftItemDTO draftItem(String volunteerId, String tier) {
        DraftItemDTO item = new DraftItemDTO();
        item.setVolunteerId(volunteerId);
        item.setTier(tier);
        item.setSchoolName("测试大学");
        item.setMajorName("测试专业" + volunteerId);
        return item;
    }

    private FixProposalDTO replaceProposal(String title,
                                           java.util.List<String> removeIds,
                                           java.util.List<String> addIds) {
        FixProposalDTO proposal = new FixProposalDTO();
        proposal.setTitle(title);
        FixProposalActionDTO action = new FixProposalActionDTO();
        action.setActionType("replace_volunteers");
        action.setRemoveVolunteerIds(removeIds);
        action.setCandidateVolunteerIds(addIds);
        int pairCount = Math.min(removeIds.size(), addIds.size());
        for (int i = 0; i < pairCount; i++) {
            ReplacementPairDTO pair = new ReplacementPairDTO();
            pair.setFromVolunteerId(removeIds.get(i));
            pair.setToVolunteerId(addIds.get(i));
            action.getReplacementPairs().add(pair);
        }
        proposal.setActions(Lists.newArrayList(action));
        return proposal;
    }

    private FixProposalDTO pairOnlyReplaceProposal(String title,
                                                   String removeId,
                                                   String addId) {
        FixProposalDTO proposal = new FixProposalDTO();
        proposal.setTitle(title);
        FixProposalActionDTO action = new FixProposalActionDTO();
        action.setActionType("replace_volunteers");
        action.getReplacementPairs().add(replacementPair(removeId, addId));
        proposal.setActions(Lists.newArrayList(action));
        return proposal;
    }

    private ReplacementPairDTO replacementPair(String removeId, String addId) {
        ReplacementPairDTO pair = new ReplacementPairDTO();
        pair.setFromVolunteerId(removeId);
        pair.setToVolunteerId(addId);
        return pair;
    }

    private CandidateItemDTO candidate(String volunteerId,
                                       String unitId,
                                       String tier,
                                       Double finalScore,
                                       Double admissionRatio) {
        CandidateItemDTO candidate = new CandidateItemDTO();
        candidate.setVolunteerId(volunteerId);
        candidate.setPlanSchoolDataId(unitId);
        candidate.setTier(tier);
        candidate.setSchoolName("测试大学");
        candidate.setMajorName("测试专业" + volunteerId);
        candidate.setFinalScore(finalScore);
        candidate.setAdmissionRatio(admissionRatio);
        candidate.setSchoolEnrollRatio(50D);
        candidate.setIntentScore(50D);
        return candidate;
    }
}
