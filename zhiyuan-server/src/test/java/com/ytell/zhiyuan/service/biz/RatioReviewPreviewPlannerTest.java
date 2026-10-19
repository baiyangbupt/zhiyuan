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
import com.ytell.zhiyuan.model.dto.planning.OrderedUnitDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanCommandDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import com.ytell.zhiyuan.model.dto.planning.PriorityRuleDTO;
import com.ytell.zhiyuan.model.dto.planning.ReviewStateDTO;
import com.ytell.zhiyuan.model.dto.planning.TierAllocationConstraintDTO;
import com.ytell.zhiyuan.model.dto.planning.TierCountRangeDTO;
import com.ytell.zhiyuan.model.dto.planning.TierQuotaGoalDTO;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * Ratio 切片：ratio_distribution fail + rebalance_tier_ratio → 直接 staged solver
 * 按已确认配额重配比，后置条件通过后才允许进入确认链。
 */
class RatioReviewPreviewPlannerTest {
    private static final int TARGET = 80;
    private static final int SPRINT = 40;
    private static final int STABLE = 20;
    private static final int PROTECT = 20;

    private final RatioReviewPreviewPlanner planner = new RatioReviewPreviewPlanner();
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
        // ≥580：本省保底不适用，hard 探针保持 pass，专注配比。
        state.getCandidatePoolState().setUserScore(600);
        state.getConstraintState().getHardPlanningObjectives().setSelectionTargetCount(TARGET);
        TierQuotaGoalDTO quota = new TierQuotaGoalDTO();
        quota.setType("exact_counts");
        quota.setSprintCount(SPRINT);
        quota.setStableCount(STABLE);
        quota.setProtectCount(PROTECT);
        state.getConstraintState().getHardPlanningObjectives().setTierQuotaGoal(quota);

        candidates = Lists.newArrayList();
        for (int index = 1; index <= TARGET + STABLE + PROTECT; index++) {
            String tier = index <= TARGET ? "sprint" : index <= TARGET + STABLE ? "stable" : "protect";
            CandidateItemDTO candidate = candidate(String.format("v%03d", index), tier, 90D - index * 0.5D);
            candidates.add(candidate);
            state.getCandidatePoolState().getItems().add(candidate);
            if (index <= TARGET) {
                DraftItemDTO selected = new DraftItemDTO();
                selected.setVolunteerId(candidate.getVolunteerId());
                selected.setTier(tier);
                state.getWorkingPlanState().getItems().add(selected);
                OrderedItemDTO ordered = new OrderedItemDTO();
                ordered.setVolunteerId(candidate.getVolunteerId());
                ordered.setTier(tier);
                ordered.setPosition(index);
                state.getOrderedPlanState().getItems().add(ordered);
            }
        }

        finding = new EvaluationFindingDTO();
        finding.setCode("ratio_distribution");
        finding.setResultStatus("fail");
        finding.setRuleStrength("soft");
        finding.setReasonCode("sprint_tier_over_limit");
        PlanCommandDTO command = new PlanCommandDTO();
        command.setStrategy("rebalance_tier_ratio");
        command.setApplyStrategy("fill_missing_count");
        command.setSourceStrategy("rebalance_tier_ratio");
        command.setSourceCheck("ratio_distribution");
        command.setLevel("volunteer");
        command.setTargetCount(TARGET);
        command.setTierConstraint(quotaConstraint());
        command.setEvaluationVersion("before-ratio-evaluation");
        command.setCommandDigest("ratio-command-digest");
        finding.setSuggestedCommand(command);
    }

    @Test
    void freezesSolverSelectionForRatioAndPassesPostcondition() {
        String baseline = JSON.toJSONString(state);
        FixProposalDTO proposal = plan(false);

        assertNotNull(proposal);
        assertEquals("preview_only", proposal.getStatus());
        assertFalse(proposal.getRequiresConfirmation());
        assertEquals("review_check", proposal.getProposalSource());
        assertEquals("fill_missing_count", proposal.getStrategy());
        assertEquals("rebalance_tier_ratio", proposal.getSourceStrategy());
        assertEquals("ratio_distribution", proposal.getFindingCode());
        assertEquals("冲稳保配比调整预览", proposal.getTitle());
        assertTrue(proposal.getSourceCheckCodes().contains("ratio_distribution"));
        assertNotNull(proposal.getSolverResult());
        assertEquals("ready", proposal.getSolverResult().getStatus());
        assertEquals(TARGET, proposal.getSolverResult().getSelectedEntityIds().size());
        assertTierCounts(proposal.getSolverResult().getSelectedEntityIds());
        assertTierCounts(proposal.getSolverResult().getOrderedEntityIds());
        assertEquals(SPRINT, proposal.getSolverResult().getHistoricalTierAnchor().getSprintCount());
        assertEquals(STABLE, proposal.getSolverResult().getHistoricalTierAnchor().getStableCount());
        assertEquals(PROTECT, proposal.getSolverResult().getHistoricalTierAnchor().getProtectCount());
        assertEquals(SPRINT, proposal.getSolverResult().getResolvedTierCounts().getSprintCount());
        assertEquals(STABLE, proposal.getSolverResult().getResolvedTierCounts().getStableCount());
        assertEquals(PROTECT, proposal.getSolverResult().getResolvedTierCounts().getProtectCount());
        assertEquals(PlanningObjectiveCompiler.compileConfirmed(state).getObjectiveDigest(),
                proposal.getCanonicalObjectiveDigest(), "proposal 元数据保持 pre-enrich digest");
        assertNotNull(proposal.getHardObjectiveVersion());
        assertNotNull(proposal.getSolverInputDigest());
        assertTrue(proposal.getFindingPostcondition().getSatisfied());
        assertEquals("ratio_distribution", proposal.getFindingPostcondition().getFindingCode());
        assertEquals("review_fix_prepare_unavailable", proposal.getBlockingReason());
        assertEquals(STABLE + PROTECT, proposal.getAddedCount(), "从候选池补入稳/保缺口");
        assertEquals(SPRINT, proposal.getRemovedCount(), "移出超额的冲档");

        FrozenReviewPlanDTO frozen = proposal.getFrozenReviewPlan();
        assertNotNull(frozen);
        assertEquals(TARGET, frozen.getSelectedEntityIds().size());
        assertEquals(TARGET, frozen.getOrderedEntityIds().size());
        assertEquals(TARGET, frozen.getWorkingPlan().getItems().size());
        assertEquals(TARGET, frozen.getOrderedPlan().getItems().size());
        assertEquals(TARGET, frozen.getSelectedFacts().size());
        assertTierCounts(frozen.getSelectedEntityIds());
        assertTierCounts(frozen.getOrderedEntityIds());
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
    void confirmableModePromotesFrozenRatioFillToReady() {
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
    void rejectsNonRatioFindingsAndCommandsWithoutTierConstraint() {
        finding.setCode("count_target");
        assertNull(plan(false));
        finding.setCode("ratio_distribution");
        finding.setResultStatus("pass");
        assertNull(plan(false));
        finding.setResultStatus("fail");
        finding.getSuggestedCommand().setStrategy("fill_missing_count");
        assertNull(plan(false));
        finding.getSuggestedCommand().setStrategy("rebalance_tier_ratio");
        finding.getSuggestedCommand().setTierConstraint(null);
        assertNull(plan(false));
        finding.getSuggestedCommand().setTierConstraint(quotaConstraint());
        finding.getSuggestedCommand().setTargetCount(null);
        assertNull(plan(false));
        finding.getSuggestedCommand().setTargetCount(0);
        assertNull(plan(false));
        finding.getSuggestedCommand().setTargetCount(TARGET);
        finding.getSuggestedCommand().setEvaluationVersion(null);
        assertNull(plan(false));
        finding.getSuggestedCommand().setEvaluationVersion("before-ratio-evaluation");
        finding.getSuggestedCommand().setCommandDigest(null);
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
        state.getOrderedPlanState().getUnits().add(new OrderedUnitDTO());
        assertNull(plan(false));
        state.getOrderedPlanState().getUnits().clear();
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
        state.getOrderedPlanState().getItems().get(0).setPinnedPosition(2);
        assertNull(plan(false));
        state.getOrderedPlanState().getItems().get(0).setPinnedPosition(null);
        state.getWorkingPlanState().getItems().get(0).setLocked(true);
        assertNull(plan(false));
        state.getWorkingPlanState().getItems().get(0).setLocked(null);
        state.getOrderedPlanState().getItems().get(1).setPosition(5);
        assertNull(plan(false));
        state.getOrderedPlanState().getItems().get(1).setPosition(2);
        state.getWorkingPlanState().getItems().remove(state.getWorkingPlanState().getItems().size() - 1);
        assertNull(plan(false));
    }

    @Test
    void returnsNoProposalWhenPostconditionFailsOrReevaluationUnavailable() {
        assertNull(planner.plan(state, candidates, finding,
                after -> ratioReview("soft", "fail", "pass"), false));
        assertNull(planner.plan(state, candidates, finding,
                after -> ratioReview("soft", "pass", "fail"), false));
        assertNull(planner.plan(state, candidates, finding,
                after -> new ReviewStateDTO(), false));
    }

    @Test
    void reevaluationSeesRebalancedOrderAndInputStaysUntouched() {
        String baseline = JSON.toJSONString(state);
        FixProposalDTO proposal = planner.plan(state, candidates, finding, after -> {
            assertEquals(TARGET, after.getWorkingPlanState().getItems().size());
            assertEquals(TARGET, after.getOrderedPlanState().getItems().size());
            List<String> ids = Lists.newArrayList();
            for (OrderedItemDTO item : after.getOrderedPlanState().getItems()) {
                ids.add(item.getVolunteerId());
            }
            assertTierCounts(ids);
            for (int index = 0; index < TARGET; index++) {
                assertEquals(Integer.valueOf(index + 1),
                        after.getOrderedPlanState().getItems().get(index).getPosition());
            }
            after.getWorkingPlanState().getItems().clear();
            return ratioReview("soft", "pass", "pass");
        }, false);
        assertNotNull(proposal);
        assertNotNull(proposal.getFrozenReviewPlan());
        assertEquals(TARGET, proposal.getFrozenReviewPlan().getWorkingPlan().getItems().size());
        assertEquals(baseline, JSON.toJSONString(state), "reevaluate 也只拿到副本");
    }

    private FixProposalDTO plan(boolean confirmable) {
        return planner.plan(state, candidates, finding,
                after -> ratioReview("soft", "pass", "pass"), confirmable);
    }

    /** ratio 是否算 confirmed goal 取决于 threshold 里的 sprintActual（与真实探针一致）。 */
    private ReviewStateDTO ratioReview(String ratioStrength, String ratioStatus, String hardStatus) {
        ReviewStateDTO review = new ReviewStateDTO();
        review.setEvaluationStatus("completed");
        review.setEvaluationVersion("after-ratio-evaluation");
        review.setProbesRun(2);
        review.setHardFeasible("pass".equals(hardStatus));
        EvaluationFindingDTO ratio = new EvaluationFindingDTO();
        ratio.setCode("ratio_distribution");
        ratio.setResultStatus(ratioStatus);
        ratio.setRuleStrength(ratioStrength);
        ratio.getThreshold().put("sprintActual", SPRINT);
        ratio.getThreshold().put("stableActual", STABLE);
        ratio.getThreshold().put("protectActual", PROTECT);
        EvaluationFindingDTO count = new EvaluationFindingDTO();
        count.setCode("count_validation_hard");
        count.setResultStatus(hardStatus);
        count.setRuleStrength("hard");
        review.setFindings(Lists.newArrayList(ratio, count));
        return review;
    }

    private void assertTierCounts(List<String> ids) {
        int sprint = 0;
        int stable = 0;
        int protect = 0;
        for (String id : ids) {
            CandidateItemDTO candidate = candidateById(id);
            assertNotNull(candidate, "solver 选中了候选池外的条目：" + id);
            if ("sprint".equals(candidate.getTier())) {
                sprint++;
            } else if ("stable".equals(candidate.getTier())) {
                stable++;
            } else if ("protect".equals(candidate.getTier())) {
                protect++;
            }
        }
        assertEquals(SPRINT, sprint, "冲档数量必须等于已确认配额");
        assertEquals(STABLE, stable, "稳档数量必须等于已确认配额");
        assertEquals(PROTECT, protect, "保档数量必须等于已确认配额");
    }

    private CandidateItemDTO candidateById(String id) {
        for (CandidateItemDTO candidate : candidates) {
            if (candidate.getVolunteerId().equals(id)) {
                return candidate;
            }
        }
        return null;
    }

    private CandidateItemDTO candidate(String id, String tier, double ratio) {
        CandidateItemDTO candidate = new CandidateItemDTO();
        candidate.setVolunteerId(id);
        candidate.setSchoolName("学校" + id);
        candidate.setMajorName("专业" + id);
        candidate.setTier(tier);
        candidate.setProvinceName("浙江");
        candidate.setAdmissionRatio(ratio);
        candidate.setSchoolEnrollRatio(ratio);
        candidate.setFinalScore(80D);
        candidate.setIntentScore(40D);
        return candidate;
    }

    private TierAllocationConstraintDTO quotaConstraint() {
        TierAllocationConstraintDTO constraint = new TierAllocationConstraintDTO();
        constraint.setType("exact_counts");
        constraint.setSourceType("exact_counts");
        constraint.setSprint(range(SPRINT));
        constraint.setStable(range(STABLE));
        constraint.setProtect(range(PROTECT));
        return constraint;
    }

    private TierCountRangeDTO range(int count) {
        TierCountRangeDTO range = new TierCountRangeDTO();
        range.setMinCount(count);
        range.setMaxCount(count);
        return range;
    }
}
