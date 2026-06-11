package com.ytell.zhiyuan.service.biz;

import com.google.common.collect.Lists;
import com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO;
import com.ytell.zhiyuan.model.dto.planning.DraftItemDTO;
import com.ytell.zhiyuan.model.dto.planning.FixProposalDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import com.ytell.zhiyuan.model.dto.planning.ReviewCheckDTO;
import org.junit.jupiter.api.Test;

import java.util.Arrays;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

public class RepairMajorGroupInnerSafetyActionBuilderTest {

    @Test
    void shouldBuildReplacementActionWhenSelectedMajorsAtRequiredCount() {
        PlanningStateDTO state = baseState();
        state.getCandidatePoolState().setRequiredMajorCount(1);
        state.getWorkingPlanState().getItems().add(workingItem("unitA_weak", "稳"));
        state.getCandidatePoolState().setItems(Arrays.asList(
                candidate("unitA_weak", "unitA", 30D, 45D, 80D, 70D),
                candidate("unitA_safe", "unitA", 70D, 55D, 50D, 65D)));

        ReviewCheckDTO check = check("unitA");
        FixProposalDTO proposal = proposal();

        RepairMajorGroupInnerSafetyActionBuilder.populateActions(state, check, proposal);

        assertEquals(1, proposal.getActions().size());
        assertEquals("adjust_major_group_inner_safety", proposal.getActions().get(0).getActionType());
        assertEquals("替换组内安全垫专业", proposal.getActions().get(0).getSummary());
        assertEquals(Lists.newArrayList("unitA_weak"), proposal.getActions().get(0).getRemoveVolunteerIds());
        assertEquals(Lists.newArrayList("unitA_safe"), proposal.getActions().get(0).getCandidateVolunteerIds());
        assertEquals("unitA_weak", proposal.getActions().get(0).getReplacementPairs().get(0).getFromVolunteerId());
        assertEquals("unitA_safe", proposal.getActions().get(0).getReplacementPairs().get(0).getToVolunteerId());
        assertEquals("ready", proposal.getStatus());
    }

    @Test
    void shouldBlockWhenOnlyPartialUnitsCanBeResolved() {
        PlanningStateDTO state = baseState();
        state.getCandidatePoolState().setRequiredMajorCount(2);
        state.getWorkingPlanState().getItems().add(workingItem("unitA_weak", "稳"));
        state.getWorkingPlanState().getItems().add(workingItem("unitB_weak", "稳"));
        state.getCandidatePoolState().setItems(Arrays.asList(
                candidate("unitA_weak", "unitA", 30D, 45D, 80D, 70D),
                candidate("unitA_safe", "unitA", 70D, 55D, 50D, 65D),
                candidate("unitB_weak", "unitB", 30D, 40D, 80D, 70D)));

        ReviewCheckDTO check = new ReviewCheckDTO();
        check.setCode("group_inner_safety_guard");
        check.setAffectedUnitIds(Lists.newArrayList("unitA", "unitB"));
        FixProposalDTO proposal = proposal();

        RepairMajorGroupInnerSafetyActionBuilder.populateActions(state, check, proposal);

        assertEquals(1, proposal.getActions().size());
        assertEquals("blocked", proposal.getStatus());
        assertEquals("只有部分专业组找到了安全垫专业，暂不自动应用。", proposal.getBlockingReason());
        assertEquals(Lists.newArrayList("partial_major_group_safety_candidate_missing"), proposal.getBlockingReasonCodes());
        assertTrue(proposal.getDryRunResult().getWarnings().stream()
                .anyMatch(warning -> warning.contains("仍有 1 个专业组")));
    }

    private PlanningStateDTO baseState() {
        PlanningStateDTO state = new PlanningStateDTO();
        state.getCandidatePoolState().setVolunteerModel("majorGroup");
        return state;
    }

    private ReviewCheckDTO check(String unitId) {
        ReviewCheckDTO check = new ReviewCheckDTO();
        check.setCode("group_inner_safety_guard");
        check.setAffectedUnitIds(Lists.newArrayList(unitId));
        return check;
    }

    private FixProposalDTO proposal() {
        FixProposalDTO proposal = new FixProposalDTO();
        proposal.setStrategy("adjust_major_group_inner_safety");
        return proposal;
    }

    private DraftItemDTO workingItem(String volunteerId, String tier) {
        DraftItemDTO item = new DraftItemDTO();
        item.setVolunteerId(volunteerId);
        item.setTier(tier);
        item.setSchoolName("学校" + volunteerId);
        item.setMajorName("专业" + volunteerId);
        return item;
    }

    private CandidateItemDTO candidate(String volunteerId,
                                       String unitId,
                                       Double finalScore,
                                       Double admissionRatio,
                                       Double schoolEnrollRatio,
                                       Double intentScore) {
        CandidateItemDTO candidate = new CandidateItemDTO();
        candidate.setVolunteerId(volunteerId);
        candidate.setPlanSchoolDataId(unitId);
        candidate.setTier("稳");
        candidate.setSchoolName("学校" + unitId);
        candidate.setMajorName("专业" + volunteerId);
        candidate.setFinalScore(finalScore);
        candidate.setAdmissionRatio(admissionRatio);
        candidate.setSchoolEnrollRatio(schoolEnrollRatio);
        candidate.setIntentScore(intentScore);
        return candidate;
    }
}
