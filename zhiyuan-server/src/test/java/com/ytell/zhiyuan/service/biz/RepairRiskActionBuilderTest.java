package com.ytell.zhiyuan.service.biz;

import com.google.common.collect.Lists;
import com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO;
import com.ytell.zhiyuan.model.dto.planning.CompensationActionDTO;
import com.ytell.zhiyuan.model.dto.planning.DraftItemDTO;
import com.ytell.zhiyuan.model.dto.planning.FixProposalDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import com.ytell.zhiyuan.model.dto.planning.ReviewCheckDTO;
import org.junit.jupiter.api.Test;

import java.util.Arrays;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

public class RepairRiskActionBuilderTest {

    @Test
    void shouldPopulateRemoveRiskActionAndFallbackFillAction() {
        ReviewCheckDTO check = new ReviewCheckDTO();
        check.setCode("high_tuition");
        check.setLevel("warn");
        check.setAffectedVolunteerIds(Lists.newArrayList("risk_1", "risk_1"));
        check.setAffectedUnitIds(Lists.newArrayList("unit_1"));
        FixProposalDTO proposal = new FixProposalDTO();
        proposal.setStrategy("remove_risk_items");

        RepairRiskActionBuilder.populateRemoveRiskItemActions(
                proposal,
                check,
                Lists.newArrayList(),
                removedVolunteerIds -> {
                    CompensationActionDTO action = new CompensationActionDTO();
                    action.setType("fill_total_count");
                    action.setLevel("warn");
                    action.setSourceCheckCode("count_validation");
                    action.setSummary("补足数量");
                    action.setVolunteerIds(Lists.newArrayList("safe_1"));
                    assertEquals(Lists.newArrayList("risk_1"), removedVolunteerIds);
                    return action;
                });

        assertEquals(2, proposal.getActions().size());
        assertEquals("remove_volunteers", proposal.getActions().get(0).getActionType());
        assertEquals(Lists.newArrayList("risk_1"), proposal.getActions().get(0).getVolunteerIds());
        assertEquals(Lists.newArrayList("unit_1"), proposal.getActions().get(0).getUnitIds());
        assertEquals("fill_total_count", proposal.getActions().get(1).getActionType());
        assertEquals(Lists.newArrayList("safe_1"), proposal.getActions().get(1).getVolunteerIds());
    }

    @Test
    void shouldPopulatePartialReplaceRiskActionsWithWarning() {
        PlanningStateDTO state = new PlanningStateDTO();
        state.getCandidatePoolState().setVolunteerModel("major");
        state.getWorkingPlanState().getItems().add(workingItem("risk_1", "稳"));
        state.getWorkingPlanState().getItems().add(workingItem("risk_2", "稳"));
        CandidateItemDTO risk1 = candidate("risk_1", "稳", 20D, 40D);
        CandidateItemDTO risk2 = candidate("risk_2", "稳", 22D, 42D);
        CandidateItemDTO safe = candidate("safe_1", "稳", 70D, 60D);
        risk1.setMajorCategory("工商管理类");
        risk2.setMajorCategory("工商管理类");
        safe.setMajorCategory("工商管理类");
        state.getCandidatePoolState().setItems(Arrays.asList(risk1, risk2, safe));

        ReviewCheckDTO check = new ReviewCheckDTO();
        check.setCode("high_tuition");
        check.setLevel("warn");
        check.setAffectedVolunteerIds(Lists.newArrayList("risk_1", "risk_2"));
        FixProposalDTO proposal = new FixProposalDTO();
        proposal.setStrategy("replace_risk_items");

        RepairRiskActionBuilder.populateReplaceRiskItemActions(state, check, proposal);

        assertEquals(1, proposal.getActions().size());
        assertEquals("replace_volunteers", proposal.getActions().get(0).getActionType());
        assertEquals("risk_1", proposal.getActions().get(0).getReplacementPairs().get(0).getFromVolunteerId());
        assertEquals("safe_1", proposal.getActions().get(0).getReplacementPairs().get(0).getToVolunteerId());
        assertEquals("preview_only", proposal.getStatus());
        assertTrue(proposal.getDryRunResult().getWarnings().stream()
                .anyMatch(warning -> warning.contains("部分风险志愿")));
    }

    private DraftItemDTO workingItem(String volunteerId, String tier) {
        DraftItemDTO item = new DraftItemDTO();
        item.setVolunteerId(volunteerId);
        item.setTier(tier);
        item.setSchoolName("学校" + volunteerId);
        item.setMajorName("专业" + volunteerId);
        return item;
    }

    private CandidateItemDTO candidate(String volunteerId, String tier, Double finalScore, Double admissionRatio) {
        CandidateItemDTO candidate = new CandidateItemDTO();
        candidate.setVolunteerId(volunteerId);
        candidate.setTier(tier);
        candidate.setPlanSchoolDataId("unit_" + volunteerId);
        candidate.setSchoolName("学校" + volunteerId);
        candidate.setMajorName("专业" + volunteerId);
        candidate.setFinalScore(finalScore);
        candidate.setAdmissionRatio(admissionRatio);
        return candidate;
    }
}
