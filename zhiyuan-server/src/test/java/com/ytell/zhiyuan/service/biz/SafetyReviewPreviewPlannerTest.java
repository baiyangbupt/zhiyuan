package com.ytell.zhiyuan.service.biz;

import com.alibaba.fastjson.JSON;
import com.google.common.collect.Lists;
import com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO;
import com.ytell.zhiyuan.model.dto.planning.DraftItemDTO;
import com.ytell.zhiyuan.model.dto.planning.DraftUnitDTO;
import com.ytell.zhiyuan.model.dto.planning.EvaluationFindingDTO;
import com.ytell.zhiyuan.model.dto.planning.FixProposalDTO;
import com.ytell.zhiyuan.model.dto.planning.FrozenReviewPlanDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedItemDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanCommandDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import com.ytell.zhiyuan.model.dto.planning.PriorityRuleDTO;
import com.ytell.zhiyuan.model.dto.planning.ReviewStateDTO;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * Safety 切片：safety_guard fail + add_safety_items → 直接 staged solver 补齐本省保底，
 * 后置条件通过后才允许进入确认链。不经过 UserGoalProposalBuilder。
 */
class SafetyReviewPreviewPlannerTest {
    private static final int TARGET = 80;
    private static final int SAFETY_MIN = 2;
    private static final int LOCAL_CANDIDATES = 3;

    private final SafetyReviewPreviewPlanner planner = new SafetyReviewPreviewPlanner();
    private PlanningStateDTO state;
    private EvaluationFindingDTO finding;
    private List<CandidateItemDTO> candidates;

    @BeforeEach
    void fixture() {
        state = new PlanningStateDTO();
        state.setVersion(11);
        state.getCandidatePoolState().setVolunteerModel("major");
        state.getCandidatePoolState().setRequiredCount(TARGET);
        state.getCandidatePoolState().setSourceProvinceName("浙江");
        state.getConstraintState().getHardPlanningObjectives().setSelectionTargetCount(TARGET);
        candidates = Lists.newArrayList();
        for (int index = 1; index <= TARGET + LOCAL_CANDIDATES; index++) {
            boolean local = index > TARGET;
            CandidateItemDTO candidate = candidate(String.format("v%03d", index), local);
            candidates.add(candidate);
            state.getCandidatePoolState().getItems().add(candidate);
            if (!local) {
                DraftItemDTO selected = new DraftItemDTO();
                selected.setVolunteerId(candidate.getVolunteerId());
                selected.setTier("protect");
                state.getWorkingPlanState().getItems().add(selected);
                OrderedItemDTO ordered = new OrderedItemDTO();
                ordered.setVolunteerId(candidate.getVolunteerId());
                ordered.setTier("protect");
                ordered.setPosition(index);
                state.getOrderedPlanState().getItems().add(ordered);
            }
        }
        finding = new EvaluationFindingDTO();
        finding.setCode("safety_guard");
        finding.setResultStatus("fail");
        finding.setRuleStrength("hard");
        PlanCommandDTO command = new PlanCommandDTO();
        command.setStrategy("add_safety_items");
        command.setApplyStrategy("fill_missing_count");
        command.setSourceStrategy("add_safety_items");
        command.setLevel("volunteer");
        command.setTargetCount(TARGET);
        command.setSafetyMinLocalProtect(SAFETY_MIN);
        command.setEvaluationVersion("before-safety-evaluation");
        command.setCommandDigest("safety-command-digest");
        finding.setSuggestedCommand(command);
    }

    @Test
    void freezesSolverSelectionForSafetyAndPassesPostcondition() {
        String baseline = JSON.toJSONString(state);
        FixProposalDTO proposal = plan(false);

        assertEquals("preview_only", proposal.getStatus());
        assertFalse(proposal.getRequiresConfirmation());
        assertEquals("review_check", proposal.getProposalSource());
        assertEquals("fill_missing_count", proposal.getStrategy());
        assertEquals("add_safety_items", proposal.getSourceStrategy());
        assertEquals("safety_guard", proposal.getFindingCode());
        assertEquals("本省保底补齐预览", proposal.getTitle());
        assertTrue(proposal.getSourceCheckCodes().contains("safety_guard"));
        assertNotNull(proposal.getSolverResult());
        assertEquals("ready", proposal.getSolverResult().getStatus());
        assertEquals(TARGET, proposal.getSolverResult().getSelectedEntityIds().size());
        assertTrue(localProtectCount(proposal.getSolverResult().getSelectedEntityIds()) >= SAFETY_MIN,
                "solver 必须选中至少 2 条本省保底");
        assertEquals(PlanningObjectiveCompiler.compileConfirmed(state).getObjectiveDigest(),
                proposal.getCanonicalObjectiveDigest(), "proposal 元数据保持 pre-enrich digest");
        assertNotNull(proposal.getHardObjectiveVersion());
        assertNotNull(proposal.getSolverInputDigest());
        assertTrue(proposal.getFindingPostcondition().getSatisfied());
        assertEquals("safety_guard", proposal.getFindingPostcondition().getFindingCode());
        assertEquals("review_fix_prepare_unavailable", proposal.getBlockingReason());

        FrozenReviewPlanDTO frozen = proposal.getFrozenReviewPlan();
        assertNotNull(frozen);
        assertEquals(TARGET, frozen.getSelectedEntityIds().size());
        assertEquals(TARGET, frozen.getOrderedEntityIds().size());
        assertEquals(TARGET, frozen.getWorkingPlan().getItems().size());
        assertEquals(TARGET, frozen.getOrderedPlan().getItems().size());
        assertEquals(TARGET, frozen.getSelectedFacts().size());
        for (int index = 0; index < TARGET; index++) {
            assertEquals(Integer.valueOf(index + 1),
                    frozen.getOrderedPlan().getItems().get(index).getPosition());
            assertEquals(frozen.getOrderedEntityIds().get(index),
                    frozen.getOrderedPlan().getItems().get(index).getVolunteerId());
        }
        assertEquals(DirectReviewPreviewPlanner.factsDigestForEntities(
                        frozen.getSelectedEntityIds(), candidates),
                frozen.getFactsDigest());
        assertTrue(localProtectCount(frozen.getSelectedEntityIds()) >= SAFETY_MIN);
        assertNotNull(proposal.getPreviewDigest());
        assertNotNull(proposal.getPlanContentDigest());
        assertEquals(baseline, JSON.toJSONString(state), "规划器不得修改输入状态");
    }

    @Test
    void confirmableModePromotesFrozenSafetyFillToReady() {
        FixProposalDTO proposal = plan(true);

        assertEquals("ready", proposal.getStatus());
        assertTrue(proposal.getRequiresConfirmation());
        assertEquals("ready", proposal.getDryRunResult().getStatus());
        assertTrue(finding.getSuggestedCommand().getExecutable());
        assertEquals(Integer.valueOf(11), proposal.getSourceVersionGuard());
        assertNull(proposal.getBlockingReason());
        assertFalse(proposal.getBlockingReasonCodes().contains("review_fix_prepare_unavailable"));
        assertNotNull(proposal.getFrozenReviewPlan());
        assertEquals(TARGET, proposal.getSolverResult().getSelectedEntityIds().size());
    }

    @Test
    void rejectsNonSafetyFindingsAndCommandsWithoutGuard() {
        finding.setCode("count_target");
        assertNull(plan(false));
        finding.setCode("safety_guard");
        finding.setResultStatus("pass");
        assertNull(plan(false));
        finding.setResultStatus("fail");
        finding.getSuggestedCommand().setStrategy("fill_missing_count");
        assertNull(plan(false));
        finding.getSuggestedCommand().setStrategy("add_safety_items");
        finding.getSuggestedCommand().setSafetyMinLocalProtect(null);
        assertNull(plan(false));
        finding.getSuggestedCommand().setSafetyMinLocalProtect(0);
        assertNull(plan(false));
        finding.getSuggestedCommand().setSafetyMinLocalProtect(SAFETY_MIN);
        finding.getSuggestedCommand().setTargetCount(null);
        assertNull(plan(false));
        finding.getSuggestedCommand().setTargetCount(0);
        assertNull(plan(false));
        finding.getSuggestedCommand().setTargetCount(TARGET);
        finding.getSuggestedCommand().setEvaluationVersion(null);
        assertNull(plan(false));
    }

    @Test
    void rejectsUnitModeUnitsPriorityRulesAndLocks() {
        state.getCandidatePoolState().setVolunteerModel("majorGroup");
        assertNull(plan(false));
        state.getCandidatePoolState().setVolunteerModel("major");
        state.getWorkingPlanState().getUnits().add(new DraftUnitDTO());
        assertNull(plan(false));
        state.getWorkingPlanState().getUnits().clear();
        PriorityRuleDTO rule = new PriorityRuleDTO();
        rule.setDomain("region");
        rule.setKey("province");
        rule.setValues(Lists.newArrayList("浙江"));
        state.getConstraintState().getHardPlanningObjectives().getPriorityRules().add(rule);
        assertNull(plan(false));
        state.getConstraintState().getHardPlanningObjectives().getPriorityRules().clear();
        state.getOrderedPlanState().getItems().get(0).setPinned(true);
        assertNull(plan(false));
        state.getOrderedPlanState().getItems().get(0).setPinned(null);
        state.getWorkingPlanState().getItems().get(0).setLocked(true);
        assertNull(plan(false));
        state.getWorkingPlanState().getItems().get(0).setLocked(null);
        state.getOrderedPlanState().getItems().get(1).setPosition(5);
        assertNull(plan(false));
    }

    @Test
    void returnsNoProposalWhenPostconditionFailsOrReevaluationUnavailable() {
        assertNull(planner.plan(state, candidates, finding,
                after -> safetyReview("fail"), false));
        assertNull(planner.plan(state, candidates, finding,
                after -> safetyReview("pass", "fail"), false));
        assertNull(planner.plan(state, candidates, finding,
                after -> new ReviewStateDTO(), false));
    }

    @Test
    void reevaluationSeesEightyEntriesWithLocalProtectAndInputStaysUntouched() {
        String baseline = JSON.toJSONString(state);
        FixProposalDTO proposal = planner.plan(state, candidates, finding, after -> {
            assertEquals(TARGET, after.getWorkingPlanState().getItems().size());
            assertEquals(TARGET, after.getOrderedPlanState().getItems().size());
            List<String> ids = Lists.newArrayList();
            for (OrderedItemDTO item : after.getOrderedPlanState().getItems()) {
                ids.add(item.getVolunteerId());
            }
            assertTrue(localProtectCount(ids) >= SAFETY_MIN, "物化后的排序态必须含本省保底");
            for (int index = 0; index < TARGET; index++) {
                assertEquals(Integer.valueOf(index + 1),
                        after.getOrderedPlanState().getItems().get(index).getPosition());
            }
            after.getWorkingPlanState().getItems().clear();
            return safetyReview("pass");
        }, false);
        assertNotNull(proposal.getFrozenReviewPlan());
        assertEquals(TARGET, proposal.getFrozenReviewPlan().getWorkingPlan().getItems().size());
        assertEquals(baseline, JSON.toJSONString(state), "reevaluate 也只拿到副本");
    }

    private FixProposalDTO plan(boolean confirmable) {
        return planner.plan(state, candidates, finding,
                after -> safetyReview("pass"), confirmable);
    }

    private void assertNoFrozen(FixProposalDTO proposal, String reason) {
        assertNotNull(proposal);
        assertFalse("ready".equals(proposal.getStatus()));
        assertFalse(proposal.getRequiresConfirmation());
        assertEquals(reason, proposal.getBlockingReason());
        assertNull(proposal.getFrozenReviewPlan());
    }

    private ReviewStateDTO safetyReview(String safetyStatus) {
        return safetyReview(safetyStatus, "pass");
    }

    private ReviewStateDTO safetyReview(String safetyStatus, String hardStatus) {
        ReviewStateDTO review = new ReviewStateDTO();
        review.setEvaluationStatus("completed");
        review.setEvaluationVersion("after-safety-evaluation");
        review.setProbesRun(2);
        review.setHardFeasible("pass".equals(hardStatus));
        EvaluationFindingDTO safety = new EvaluationFindingDTO();
        safety.setCode("safety_guard");
        safety.setResultStatus(safetyStatus);
        safety.setRuleStrength("hard");
        EvaluationFindingDTO count = new EvaluationFindingDTO();
        count.setCode("count_validation_hard");
        count.setResultStatus(hardStatus);
        count.setRuleStrength("hard");
        review.setFindings(Lists.newArrayList(safety, count));
        return review;
    }

    private long localProtectCount(List<String> ids) {
        return ids.stream().map(this::candidateById)
                .filter(candidate -> candidate != null && "浙江".equals(candidate.getProvinceName())
                        && "protect".equals(candidate.getTier()))
                .count();
    }

    private CandidateItemDTO candidateById(String id) {
        for (CandidateItemDTO candidate : candidates) {
            if (candidate.getVolunteerId().equals(id)) {
                return candidate;
            }
        }
        return null;
    }

    private CandidateItemDTO candidate(String id, boolean local) {
        CandidateItemDTO candidate = new CandidateItemDTO();
        candidate.setVolunteerId(id);
        candidate.setSchoolName("学校" + id);
        candidate.setMajorName("专业" + id);
        candidate.setTier("protect");
        candidate.setProvinceName(local ? "浙江" : "江苏");
        candidate.setAdmissionRatio(local ? 30D : 50D);
        candidate.setSchoolEnrollRatio(local ? 30D : 50D);
        candidate.setFinalScore(80D);
        candidate.setIntentScore(40D);
        return candidate;
    }
}
