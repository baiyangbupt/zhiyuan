package com.ytell.zhiyuan.service.biz;

import com.alibaba.fastjson.JSON;
import com.google.common.collect.Lists;
import com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO;
import com.ytell.zhiyuan.model.dto.planning.CoverageRequirementDTO;
import com.ytell.zhiyuan.model.dto.planning.DraftItemDTO;
import com.ytell.zhiyuan.model.dto.planning.EvaluationFindingDTO;
import com.ytell.zhiyuan.model.dto.planning.FixProposalDTO;
import com.ytell.zhiyuan.model.dto.planning.FrozenReviewPlanDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedItemDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanCommandDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import com.ytell.zhiyuan.model.dto.planning.ReviewStateDTO;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * Search 首个切片：count_target fail → fill_missing_count，复用 user-goal staged solver
 * 生成冻结方案，postcondition 通过后才允许进入确认链。
 */
class SearchReviewPreviewPlannerTest {
    private static final int CURRENT = 80;
    private static final int TARGET = 82;
    private static final int COVERAGE_TARGET = 80;
    private static final int COVERAGE_MIN = 20;

    private final SearchReviewPreviewPlanner planner = new SearchReviewPreviewPlanner();
    private PlanningStateDTO state;
    private EvaluationFindingDTO finding;
    private List<CandidateItemDTO> candidates;

    @BeforeEach
    void fixture() {
        state = new PlanningStateDTO();
        state.setVersion(7);
        state.getCandidatePoolState().setVolunteerModel("major");
        state.getCandidatePoolState().setRequiredCount(TARGET);
        state.getCandidatePoolState().setSourceProvinceName("浙江");
        state.getConstraintState().getHardPlanningObjectives().setSelectionTargetCount(TARGET);
        candidates = Lists.newArrayList();
        for (int index = 1; index <= CURRENT + 4; index++) {
            CandidateItemDTO candidate = candidate(String.format("v%03d", index));
            candidates.add(candidate);
            state.getCandidatePoolState().getItems().add(candidate);
            if (index <= CURRENT) {
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
        finding.setCode("count_target");
        finding.setResultStatus("fail");
        PlanCommandDTO command = new PlanCommandDTO();
        command.setStrategy("fill_missing_count");
        command.setSourceStrategy("count_target");
        command.setLevel("volunteer");
        command.setTargetCount(TARGET);
        command.setEvaluationVersion("before-evaluation");
        command.setCommandDigest("command-digest");
        finding.setSuggestedCommand(command);
    }

    @org.junit.jupiter.params.ParameterizedTest
    @org.junit.jupiter.params.provider.ValueSource(booleans = {false, true})
    void countFillCannotRemoveCompliantCurrentItemsToMeetSafetyFloor(boolean hasSatisfiedCoverage) {
        state.getCandidatePoolState().setRequiredCount(CURRENT + 1);
        state.getConstraintState().getHardPlanningObjectives().setSelectionTargetCount(CURRENT + 1);
        finding.getSuggestedCommand().setTargetCount(CURRENT + 1);
        for (int index = 0; index < CURRENT; index++) {
            candidates.get(index).setProvinceName("江苏");
        }
        if (hasSatisfiedCoverage) {
            CoverageRequirementDTO coverage = new CoverageRequirementDTO();
            coverage.setDomain("region");
            coverage.setKey("province");
            coverage.setValues(Lists.newArrayList("江苏"));
            coverage.setMinCount(1);
            state.getConstraintState().getHardPlanningObjectives().getCoverageRequirements().add(coverage);
        }
        String baseline = JSON.toJSONString(state);

        FixProposalDTO proposal = planner.plan(state, candidates, finding,
                after -> review("pass", SafetyFloorSupport.countLocalProtect(after, candidates) >= 2
                        ? "pass" : "fail"), true);

        assertNotReady(proposal);
        assertNull(proposal.getFrozenReviewPlan());
        assertEquals(baseline, JSON.toJSONString(state));
    }

    @Test
    void freezesSolverSelectionForCountTargetAndPassesPostcondition() {
        String baseline = JSON.toJSONString(state);
        FixProposalDTO proposal = plan(false);

        assertEquals("preview_only", proposal.getStatus());
        assertFalse(proposal.getRequiresConfirmation());
        assertEquals("review_check", proposal.getProposalSource());
        assertNotNull(proposal.getSolverResult());
        assertEquals("ready", proposal.getSolverResult().getStatus());
        assertEquals(TARGET, proposal.getSolverResult().getSelectedEntityIds().size());
        assertNotNull(proposal.getCanonicalObjectiveDigest());
        assertTrue(proposal.getFindingPostcondition().getSatisfied());
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
        assertNotNull(proposal.getPreviewDigest());
        assertNotNull(proposal.getPlanContentDigest());
        assertEquals(baseline, JSON.toJSONString(state), "规划器不得修改输入状态");
    }

    @Test
    void confirmableModePromotesFrozenFillToReady() {
        FixProposalDTO proposal = plan(true);

        assertEquals("ready", proposal.getStatus());
        assertTrue(proposal.getRequiresConfirmation());
        assertEquals("ready", proposal.getDryRunResult().getStatus());
        assertTrue(finding.getSuggestedCommand().getExecutable());
        assertEquals(Integer.valueOf(7), proposal.getSourceVersionGuard());
        assertNull(proposal.getBlockingReason());
        assertFalse(proposal.getBlockingReasonCodes().contains("review_fix_prepare_unavailable"));
        assertNotNull(proposal.getFrozenReviewPlan());
        assertEquals(TARGET, proposal.getSolverResult().getSelectedEntityIds().size());
    }

    @Test
    void rejectsNonCountTargetFindingsWithoutProposal() {
        finding.setCode("probability_inversion");
        finding.getSuggestedCommand().setStrategy("sort_by_probability");
        assertNull(plan(false));
        finding.setCode("count_target");
        finding.setResultStatus("pass");
        assertNull(plan(false));
        finding.setResultStatus("fail");
        finding.getSuggestedCommand().setStrategy("add_safety_items");
        assertNull(plan(false));
        finding.getSuggestedCommand().setStrategy("fill_missing_count");
        finding.getSuggestedCommand().setTargetCount(null);
        assertNoFrozen(plan(false), "review_fix_search_no_change");
    }

    @Test
    void rejectsUnitModeWithoutUnitCarriersAndUnsupportedSelections() {
        state.getCandidatePoolState().setVolunteerModel("majorGroup");
        // 组模式已由 GroupSearchReviewPreviewPlannerTest 覆盖；本夹具没有 unit 载体，
        // 因此 unit 分支必须拒绝而不是退回 item 模式物化。
        assertNoFrozen(plan(false), "review_fix_selection_incomplete");
        state.getCandidatePoolState().setVolunteerModel("major");
        state.getOrderedPlanState().getItems().get(0).setPinned(true);
        assertNoFrozen(plan(false), "review_fix_selection_incomplete");
        state.getOrderedPlanState().getItems().get(0).setPinned(null);
        state.getWorkingPlanState().getItems().get(0).setLocked(true);
        assertNoFrozen(plan(false), "review_fix_selection_incomplete");
    }

    @Test
    void blockedWhenTargetDoesNotIncreaseOrPostconditionFails() {
        finding.getSuggestedCommand().setTargetCount(CURRENT);
        assertNoFrozen(plan(false), "review_fix_search_no_change");
        finding.getSuggestedCommand().setTargetCount(TARGET);
        FixProposalDTO failed = planner.plan(state, candidates, finding,
                after -> review("fail", "pass"), false);
        assertNoFrozen(failed, "repair_goal_unreachable");
        FixProposalDTO hard = planner.plan(state, candidates, finding,
                after -> review("pass", "fail"), false);
        assertNoFrozen(hard, "hard_constraints_unsatisfied");
        FixProposalDTO unavailable = planner.plan(state, candidates, finding,
                after -> new ReviewStateDTO(), false);
        assertNoFrozen(unavailable, "review_fix_evaluation_unavailable");
    }

    @Test
    void reevaluationSeesTheMaterializedEightyTwoAndInputStaysUntouched() {
        String baseline = JSON.toJSONString(state);
        FixProposalDTO proposal = planner.plan(state, candidates, finding, after -> {
            assertEquals(TARGET, after.getWorkingPlanState().getItems().size());
            assertEquals(TARGET, after.getOrderedPlanState().getItems().size());
            assertEquals(TARGET - CURRENT, (int) after.getOrderedPlanState().getItems().stream()
                    .filter(item -> "review_fix".equals(item.getSource())).count());
            after.getWorkingPlanState().getItems().clear();
            return review("pass", "pass");
        }, false);
        assertNotNull(proposal.getFrozenReviewPlan());
        assertEquals(baseline, JSON.toJSONString(state), "reevaluate 也只拿到副本");
    }

    @Test
    void freezesCoverageFillAtUnchangedTargetAndPassesCoveragePostcondition() {
        useCoverageFixture();
        String baseline = JSON.toJSONString(state);
        Map<String, CandidateItemDTO> byId = new LinkedHashMap<String, CandidateItemDTO>();
        for (CandidateItemDTO candidate : candidates) {
            byId.put(candidate.getVolunteerId(), candidate);
        }

        FixProposalDTO proposal = planner.plan(state, candidates, finding, after -> {
            List<OrderedItemDTO> selected = after.getOrderedPlanState().getItems();
            assertEquals(COVERAGE_TARGET, selected.size());
            long zhejiang = selected.stream()
                    .map(item -> byId.get(item.getVolunteerId()))
                    .filter(candidate -> candidate != null && "浙江".equals(candidate.getProvinceName()))
                    .count();
            assertTrue(zhejiang >= COVERAGE_MIN, "materialized selection must satisfy coverage");
            return coverageReview((int) zhejiang);
        }, true);

        assertEquals("ready", proposal.getStatus());
        assertTrue(proposal.getRequiresConfirmation());
        assertEquals("fill_missing_count", proposal.getStrategy());
        assertEquals("coverage:0", proposal.getFindingCode());
        assertTrue(proposal.getSourceCheckCodes().contains("coverage:0"));
        assertTrue(proposal.getSourceCheckCodes().contains("coverage"));
        assertNotNull(proposal.getSolverResult());
        assertEquals(COVERAGE_TARGET, proposal.getSolverResult().getSelectedEntityIds().size());
        assertTrue(proposal.getFindingPostcondition().getSatisfied());
        assertEquals("coverage:0", proposal.getFindingPostcondition().getFindingCode());

        FrozenReviewPlanDTO frozen = proposal.getFrozenReviewPlan();
        assertNotNull(frozen);
        assertEquals(COVERAGE_TARGET, frozen.getSelectedEntityIds().size());
        assertEquals(COVERAGE_TARGET, frozen.getOrderedEntityIds().size());
        assertEquals(COVERAGE_TARGET, frozen.getWorkingPlan().getItems().size());
        assertEquals(COVERAGE_TARGET, frozen.getOrderedPlan().getItems().size());
        long zhejiangSelected = frozen.getSelectedFacts().stream()
                .filter(candidate -> candidate != null && "浙江".equals(candidate.getProvinceName()))
                .count();
        assertTrue(zhejiangSelected >= COVERAGE_MIN);
        assertNotNull(proposal.getPreviewDigest());
        assertNotNull(proposal.getPlanContentDigest());
        assertEquals(baseline, JSON.toJSONString(state), "规划器不得修改输入状态");
    }

    @Test
    void coverageFindingWithoutRequirementsOrInvalidTargetIsIgnored() {
        useCoverageFixture();
        finding.getSuggestedCommand().setCoverageRequirements(Lists.<CoverageRequirementDTO>newArrayList());
        assertNoFrozen(plan(false), "review_fix_coverage_unavailable");
        useCoverageFixture();
        finding.getSuggestedCommand().setTargetCount(null);
        assertNull(plan(false), "coverage mode requires a positive target count");
        useCoverageFixture();
        finding.getSuggestedCommand().setApplyStrategy(null);
        finding.getSuggestedCommand().setStrategy("fill_missing_count");
        assertNull(plan(false), "coverage mode requires must_include_scope or applyStrategy=fill_missing_count");
    }

    private void useCoverageFixture() {
        state = new PlanningStateDTO();
        state.setVersion(9);
        state.getCandidatePoolState().setVolunteerModel("major");
        state.getCandidatePoolState().setRequiredCount(COVERAGE_TARGET);
        state.getCandidatePoolState().setSourceProvinceName("浙江");
        state.getConstraintState().getHardPlanningObjectives().setSelectionTargetCount(COVERAGE_TARGET);
        state.getConstraintState().getHardPlanningObjectives().getCoverageRequirements()
                .add(coverageRequirement());

        candidates = Lists.newArrayList();
        for (int index = 1; index <= COVERAGE_TARGET + 30; index++) {
            // 存量 80 条里只有 10 条浙江（>= 本省保底 2，< 覆盖下限 20）；
            // 候选池尾部额外提供 30 条浙江用于等量替换。
            boolean zhejiang = index <= 10 || index > COVERAGE_TARGET;
            CandidateItemDTO candidate = candidate(String.format("c%03d", index), zhejiang);
            candidates.add(candidate);
            state.getCandidatePoolState().getItems().add(candidate);
            if (index <= COVERAGE_TARGET) {
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
        finding.setCode("coverage:0");
        finding.setResultStatus("fail");
        PlanCommandDTO command = new PlanCommandDTO();
        command.setStrategy("must_include_scope");
        command.setApplyStrategy("fill_missing_count");
        command.setSourceStrategy("coverage");
        command.setLevel("volunteer");
        command.setTargetCount(COVERAGE_TARGET);
        command.setCoverageRequirements(Lists.newArrayList(coverageRequirement()));
        command.setEvaluationVersion("before-evaluation");
        command.setCommandDigest("coverage-command-digest");
        finding.setSuggestedCommand(command);
    }

    private CoverageRequirementDTO coverageRequirement() {
        CoverageRequirementDTO requirement = new CoverageRequirementDTO();
        requirement.setDomain("region");
        requirement.setKey("province");
        requirement.setValues(Lists.newArrayList("浙江"));
        requirement.setMinCount(COVERAGE_MIN);
        return requirement;
    }

    private ReviewStateDTO coverageReview(int coverageMatched) {
        ReviewStateDTO review = new ReviewStateDTO();
        review.setEvaluationStatus("completed");
        review.setEvaluationVersion("after-coverage-evaluation");
        review.setProbesRun(4);
        review.setHardFeasible(true);
        EvaluationFindingDTO count = new EvaluationFindingDTO();
        count.setCode("count_validation_hard");
        count.setResultStatus("pass");
        count.setRuleStrength("hard");
        EvaluationFindingDTO safety = new EvaluationFindingDTO();
        safety.setCode("safety_guard");
        safety.setResultStatus("pass");
        safety.setRuleStrength("hard");
        EvaluationFindingDTO coverage = new EvaluationFindingDTO();
        coverage.setCode("coverage:0");
        coverage.setResultStatus(coverageMatched >= COVERAGE_MIN ? "pass" : "fail");
        coverage.setRuleStrength("soft");
        EvaluationFindingDTO target = new EvaluationFindingDTO();
        target.setCode("count_target");
        target.setResultStatus("pass");
        target.setRuleStrength("soft");
        review.setFindings(Lists.newArrayList(count, safety, coverage, target));
        return review;
    }

    private FixProposalDTO plan(boolean confirmable) {
        return planner.plan(state, candidates, finding,
                after -> review("pass", "pass"), confirmable);
    }

    private void assertNoFrozen(FixProposalDTO proposal, String reason) {
        assertNotNull(proposal);
        assertNotReady(proposal);
        assertEquals(reason, proposal.getBlockingReason());
        assertNull(proposal.getFrozenReviewPlan());
    }

    private void assertNotReady(FixProposalDTO proposal) {
        assertFalse("ready".equals(proposal.getStatus()));
        assertFalse(proposal.getRequiresConfirmation());
    }

    private ReviewStateDTO review(String status, String hardStatus) {
        ReviewStateDTO review = new ReviewStateDTO();
        review.setEvaluationStatus("completed");
        review.setEvaluationVersion("after-evaluation");
        review.setProbesRun(2);
        review.setHardFeasible("pass".equals(hardStatus));
        EvaluationFindingDTO probe = new EvaluationFindingDTO();
        probe.setCode("count_target");
        probe.setResultStatus(status);
        probe.setRuleStrength("soft");
        EvaluationFindingDTO hard = new EvaluationFindingDTO();
        hard.setCode("count_validation_hard");
        hard.setResultStatus(hardStatus);
        hard.setRuleStrength("hard");
        review.setFindings(Lists.newArrayList(probe, hard));
        return review;
    }

    private CandidateItemDTO candidate(String id) {
        return candidate(id, true);
    }

    private CandidateItemDTO candidate(String id, boolean zhejiang) {
        CandidateItemDTO candidate = new CandidateItemDTO();
        candidate.setVolunteerId(id);
        candidate.setSchoolName("学校" + id);
        candidate.setMajorName("专业" + id);
        candidate.setTier("protect");
        candidate.setProvinceName(zhejiang ? "浙江" : "江苏");
        candidate.setAdmissionRatio(50D);
        candidate.setSchoolEnrollRatio(50D);
        candidate.setFinalScore(80D);
        candidate.setIntentScore(40D);
        return candidate;
    }
}
