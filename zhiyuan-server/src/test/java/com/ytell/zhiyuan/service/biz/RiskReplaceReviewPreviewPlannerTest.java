package com.ytell.zhiyuan.service.biz;

import com.alibaba.fastjson.JSON;
import com.google.common.collect.Lists;
import com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO;
import com.ytell.zhiyuan.model.dto.planning.DraftItemDTO;
import com.ytell.zhiyuan.model.dto.planning.DraftUnitDTO;
import com.ytell.zhiyuan.model.dto.planning.EvaluationEntryRefDTO;
import com.ytell.zhiyuan.model.dto.planning.EvaluationFindingDTO;
import com.ytell.zhiyuan.model.dto.planning.FixProposalDTO;
import com.ytell.zhiyuan.model.dto.planning.FrozenReviewPlanDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedItemDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedUnitDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanCommandDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningUnitMajorDTO;
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
 * RiskReplace 切片：风险条目 fail + replace/remove_risk_items →
 * 直接 staged solver 强制移出命中条目并等量补入替代，后置条件通过后才允许
 * 进入确认链。
 */
class RiskReplaceReviewPreviewPlannerTest {
    private static final int TARGET = 80;
    private static final String RISKY = "v001";
    private static final String REPLACEMENT = "v081";

    private final RiskReplaceReviewPreviewPlanner planner = new RiskReplaceReviewPreviewPlanner();
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
        // ≥580：本省保底不适用，safety_guard 保持 pass，专注风险条目替换。
        state.getCandidatePoolState().setUserScore(600);
        state.getConstraintState().getHardPlanningObjectives().setSelectionTargetCount(TARGET);

        candidates = Lists.newArrayList();
        for (int index = 1; index <= TARGET + 1; index++) {
            CandidateItemDTO candidate = candidate(String.format("v%03d", index),
                    index == 1 ? 30000 : 5000);
            candidates.add(candidate);
            state.getCandidatePoolState().getItems().add(candidate);
            if (index <= TARGET) {
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
        finding.setCode("high_tuition");
        finding.setResultStatus("fail");
        finding.setRuleStrength("soft");
        finding.setReasonCode("high_tuition");
        PlanCommandDTO command = new PlanCommandDTO();
        command.setStrategy("replace_risk_items");
        command.setApplyStrategy("fill_missing_count");
        command.setSourceStrategy("replace_risk_items");
        command.setSourceCheck("high_tuition");
        command.setLevel("volunteer");
        command.setTargetCount(TARGET);
        command.getForcedRemoveTargets().add(ref("volunteer", RISKY));
        command.setEvaluationVersion("before-risk-evaluation");
        command.setCommandDigest("risk-command-digest");
        finding.setSuggestedCommand(command);
    }

    @Test
    void freezesForcedRemoveReplacementAndPassesPostcondition() {
        String baseline = JSON.toJSONString(state);
        FixProposalDTO proposal = plan(false);

        assertNotNull(proposal);
        assertEquals("preview_only", proposal.getStatus());
        assertFalse(proposal.getRequiresConfirmation());
        assertEquals("review_check", proposal.getProposalSource());
        assertEquals("fill_missing_count", proposal.getStrategy());
        assertEquals("replace_risk_items", proposal.getSourceStrategy());
        assertEquals("high_tuition", proposal.getFindingCode());
        assertEquals("风险条目替换预览", proposal.getTitle());
        assertTrue(proposal.getSourceCheckCodes().contains("high_tuition"));
        assertNotNull(proposal.getSolverResult());
        assertEquals("ready", proposal.getSolverResult().getStatus());
        assertEquals(TARGET, proposal.getSolverResult().getSelectedEntityIds().size());
        assertTrue(proposal.getSolverResult().getRemoveEntityIds().contains(RISKY),
                "forcedRemove 条目必须被 solver 移出");
        assertFalse(proposal.getSolverResult().getSelectedEntityIds().contains(RISKY));
        assertTrue(proposal.getSolverResult().getAddEntityIds().contains(REPLACEMENT));
        assertEquals(PlanningObjectiveCompiler.compileConfirmed(state).getObjectiveDigest(),
                proposal.getCanonicalObjectiveDigest(), "proposal 元数据保持 pre-enrich digest");
        assertNotNull(proposal.getHardObjectiveVersion());
        assertNotNull(proposal.getSolverInputDigest());
        assertTrue(proposal.getFindingPostcondition().getSatisfied());
        assertEquals("high_tuition", proposal.getFindingPostcondition().getFindingCode());
        assertEquals("review_fix_prepare_unavailable", proposal.getBlockingReason());
        assertEquals(1, proposal.getRemovedCount());
        assertEquals(1, proposal.getAddedCount());

        FrozenReviewPlanDTO frozen = proposal.getFrozenReviewPlan();
        assertNotNull(frozen);
        assertEquals(TARGET, frozen.getSelectedEntityIds().size());
        assertEquals(TARGET, frozen.getOrderedEntityIds().size());
        assertEquals(TARGET, frozen.getWorkingPlan().getItems().size());
        assertEquals(TARGET, frozen.getOrderedPlan().getItems().size());
        assertEquals(TARGET, frozen.getSelectedFacts().size());
        assertFalse(frozen.getSelectedEntityIds().contains(RISKY));
        assertTrue(frozen.getSelectedEntityIds().contains(REPLACEMENT));
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
    void confirmableModePromotesFrozenRiskReplacementToReady() {
        FixProposalDTO proposal = plan(true);

        assertNotNull(proposal);
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
    void removeStrategyWithoutTargetCountKeepsCurrentSelectionSize() {
        finding.setCode("special_enrollment");
        finding.getSuggestedCommand().setStrategy("remove_risk_items");
        finding.getSuggestedCommand().setApplyStrategy("remove_risk_items");
        finding.getSuggestedCommand().setSourceStrategy("remove_risk_items");
        finding.getSuggestedCommand().setSourceCheck("special_enrollment");
        finding.getSuggestedCommand().setTargetCount(null);

        FixProposalDTO proposal = plan(false);

        assertNotNull(proposal);
        assertEquals("风险条目移除预览", proposal.getTitle());
        assertEquals(TARGET, proposal.getSolverResult().getSelectedEntityIds().size(),
                "targetCount 为空时按当前工作草案条数保持总数");
        assertTrue(proposal.getSolverResult().getRemoveEntityIds().contains(RISKY));
    }

    @Test
    void acceptsAllFourRiskFindingCodes() {
        for (String code : Lists.newArrayList("high_tuition", "cooperative_program",
                "admission_limit", "special_enrollment")) {
            finding.setCode(code);
            finding.getSuggestedCommand().setSourceCheck(code);
            finding.getSuggestedCommand().setStrategy("special_enrollment".equals(code)
                    || "admission_limit".equals(code) ? "remove_risk_items" : "replace_risk_items");
            finding.getSuggestedCommand().setSourceStrategy(finding.getSuggestedCommand().getStrategy());
            FixProposalDTO proposal = planner.plan(state, candidates, finding,
                    after -> riskReview(code, "pass", "pass"), false);
            assertNotNull(proposal, code + " 必须产出 RiskReplace 提案");
            assertEquals(code, proposal.getFindingCode());
            assertEquals("fill_missing_count", proposal.getStrategy());
        }
    }

    @Test
    void rejectsUnsupportedModeUnitsPriorityRulesAndLocks() {
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
        state.getOrderedPlanState().getItems().get(1).setPinned(true);
        assertNull(plan(false));
        state.getOrderedPlanState().getItems().get(1).setPinned(null);
        state.getOrderedPlanState().getItems().get(1).setPinnedPosition(2);
        assertNull(plan(false));
        state.getOrderedPlanState().getItems().get(1).setPinnedPosition(null);
        state.getWorkingPlanState().getItems().get(0).setLocked(true);
        assertNull(plan(false));
        state.getWorkingPlanState().getItems().get(0).setLocked(null);
        state.getOrderedPlanState().getItems().get(1).setPosition(5);
        assertNull(plan(false));
    }

    @Test
    void rejectsInvalidForcedRemoveRefs() {
        finding.getSuggestedCommand().getForcedRemoveTargets().clear();
        assertNull(plan(false), "空 forcedRemoveTargets 必须拒绝");
        finding.getSuggestedCommand().getForcedRemoveTargets().add(ref("volunteer", RISKY));

        finding.getSuggestedCommand().getForcedRemoveTargets().get(0).setLevel("unit");
        assertNull(plan(false), "非 volunteer 粒度必须拒绝");
        finding.getSuggestedCommand().getForcedRemoveTargets().get(0).setLevel("volunteer");

        finding.getSuggestedCommand().getForcedRemoveTargets().get(0).setId("missing");
        assertNull(plan(false), "候选池不存在的引用必须拒绝");
        finding.getSuggestedCommand().getForcedRemoveTargets().get(0).setId(REPLACEMENT);
        assertNull(plan(false), "不在当前选择里的引用必须拒绝");
        finding.getSuggestedCommand().getForcedRemoveTargets().get(0).setId(RISKY);
        finding.getSuggestedCommand().getForcedRemoveTargets().add(ref("volunteer", RISKY));
        assertNull(plan(false), "重复引用必须拒绝");
    }

    @Test
    void rejectsNonRiskFindingsWrongStatusStrategyAndInvalidTargets() {
        finding.setCode("count_target");
        assertNull(plan(false));
        finding.setCode("high_tuition");
        finding.setResultStatus("pass");
        assertNull(plan(false));
        finding.setResultStatus("fail");
        finding.getSuggestedCommand().setStrategy("fill_missing_count");
        assertNull(plan(false));
        finding.getSuggestedCommand().setStrategy("replace_risk_items");
        finding.getSuggestedCommand().setTargetCount(0);
        assertNull(plan(false));
        finding.getSuggestedCommand().setTargetCount(TARGET + 2);
        assertNull(plan(false), "候选不足时必须拒绝");
        finding.getSuggestedCommand().setTargetCount(TARGET);
        finding.getSuggestedCommand().setEvaluationVersion(null);
        assertNull(plan(false));
        finding.getSuggestedCommand().setEvaluationVersion("before-risk-evaluation");
        finding.getSuggestedCommand().setCommandDigest(null);
        assertNull(plan(false));
    }

    @Test
    void returnsNoProposalWhenPostconditionFailsOrReevaluationUnavailable() {
        assertNull(planner.plan(state, candidates, finding,
                after -> riskReview("high_tuition", "fail", "pass"), false));
        assertNull(planner.plan(state, candidates, finding,
                after -> riskReview("high_tuition", "pass", "fail"), false));
        assertNull(planner.plan(state, candidates, finding,
                after -> new ReviewStateDTO(), false));
    }

    @Test
    void reevaluationSeesReplacementAndInputStaysUntouched() {
        String baseline = JSON.toJSONString(state);
        FixProposalDTO proposal = planner.plan(state, candidates, finding, after -> {
            assertEquals(TARGET, after.getWorkingPlanState().getItems().size());
            assertEquals(TARGET, after.getOrderedPlanState().getItems().size());
            for (OrderedItemDTO item : after.getOrderedPlanState().getItems()) {
                assertFalse(RISKY.equals(item.getVolunteerId()), "物化后的排序态必须移出风险条目");
            }
            after.getWorkingPlanState().getItems().clear();
            return riskReview("high_tuition", "pass", "pass");
        }, false);
        assertNotNull(proposal);
        assertNotNull(proposal.getFrozenReviewPlan());
        assertEquals(TARGET, proposal.getFrozenReviewPlan().getWorkingPlan().getItems().size());
        assertEquals(baseline, JSON.toJSONString(state), "reevaluate 也只拿到副本");
    }

    @Test
    void replacesRiskyGroupUnitWithUnitFactsAndActions() {
        groupFixture();
        String baseline = JSON.toJSONString(state);

        FixProposalDTO proposal = planner.plan(state, candidates, finding,
                after -> riskReview("high_tuition", "pass", "pass"), true);

        assertNotNull(proposal);
        assertEquals("ready", proposal.getStatus());
        assertTrue(proposal.getRequiresConfirmation());
        assertEquals("fill_missing_count", proposal.getStrategy());
        assertEquals("replace_risk_items", proposal.getSourceStrategy());
        assertEquals(4, proposal.getSolverResult().getSelectedEntityIds().size());
        assertTrue(proposal.getSolverResult().getRemoveEntityIds().contains("u001"));
        assertFalse(proposal.getSolverResult().getSelectedEntityIds().contains("u001"));
        assertTrue(proposal.getSolverResult().getAddEntityIds().contains("u005"));
        assertEquals(1, proposal.getRemovedCount());
        assertEquals(1, proposal.getAddedUnitCount());
        assertEquals(Integer.valueOf(4), proposal.getDryRunResult().getBeforeUnitTotal());
        assertEquals(Integer.valueOf(4), proposal.getDryRunResult().getAfterUnitTotal());

        FrozenReviewPlanDTO frozen = proposal.getFrozenReviewPlan();
        assertNotNull(frozen);
        assertEquals(4, frozen.getSelectedEntityIds().size());
        assertEquals(4, frozen.getOrderedEntityIds().size());
        assertEquals(4, frozen.getOrderedPlan().getUnits().size());
        assertEquals(4, frozen.getWorkingPlan().getUnits().size());
        assertEquals(4, frozen.getSelectedFacts().size());
        for (int index = 0; index < frozen.getOrderedPlan().getUnits().size(); index++) {
            assertEquals(Integer.valueOf(index + 1),
                    frozen.getOrderedPlan().getUnits().get(index).getPosition());
            assertEquals(frozen.getOrderedEntityIds().get(index),
                    frozen.getOrderedPlan().getUnits().get(index).getUnitId());
        }
        assertEquals(DirectReviewPreviewPlanner.digestJson(DirectReviewPreviewPlanner.factsForUnits(
                        frozen.getSelectedEntityIds(), frozen.getOrderedPlan().getUnits(), candidates)),
                frozen.getFactsDigest());

        boolean sawUnitRemove = false;
        for (com.ytell.zhiyuan.model.dto.planning.FixProposalActionDTO action : proposal.getActions()) {
            if ("unit".equals(action.getLevel()) && action.getRemoveUnitIds().contains("u001")) {
                sawUnitRemove = true;
                assertTrue(action.getRemoveVolunteerIds().contains("u001-v1"));
            }
        }
        assertTrue(sawUnitRemove, "组模式风险替换必须产出 unit 级移出动作");
        assertEquals(baseline, JSON.toJSONString(state), "规划器不得修改输入状态");
    }

    @Test
    void rejectsGroupRefsWithoutUnitLevelAndUnstableUnitList() {
        groupFixture();
        finding.getSuggestedCommand().getForcedRemoveTargets().get(0).setLevel("volunteer");
        assertNull(plan(false), "组模式强制移出必须是 unit 粒度");
        finding.getSuggestedCommand().getForcedRemoveTargets().get(0).setLevel("unit");

        state.getOrderedPlanState().getUnits().get(1).setPosition(1);
        assertNull(plan(false), "位置必须严格递增");
        state.getOrderedPlanState().getUnits().get(1).setPosition(2);
        state.getOrderedPlanState().getUnits().get(2).setUnitId("malformed");
        assertNull(plan(false), "unit id 必须在候选池中存在");
        state.getOrderedPlanState().getUnits().get(2).setUnitId("u003");

        PriorityRuleDTO rule = new PriorityRuleDTO();
        rule.setDomain("region");
        rule.setKey("province");
        rule.setValues(Lists.newArrayList("江苏"));
        state.getConstraintState().getHardPlanningObjectives().getPriorityRules().add(rule);
        assertNull(plan(false));
        state.getConstraintState().getHardPlanningObjectives().getPriorityRules().clear();

        assertNull(planner.plan(state, candidates, finding,
                after -> riskReview("high_tuition", "fail", "pass"), false));
    }

    /**
     * 组模式风险切片：4 个现有专业组，u001 组内专业高收费；候选池另有
     * u005/u006 两个可替代组，目标数 4 不变。
     */
    private void groupFixture() {
        state = new PlanningStateDTO();
        state.setVersion(12);
        state.setPhase("ordered");
        state.getCandidatePoolState().setVolunteerModel("majorGroup");
        state.getCandidatePoolState().setRequiredCount(4);
        state.getCandidatePoolState().setSourceProvinceName("江苏");
        state.getCandidatePoolState().setUserScore(600);
        state.getConstraintState().getHardPlanningObjectives().setSelectionTargetCount(4);

        candidates = Lists.newArrayList();
        for (int unitIndex = 1; unitIndex <= 6; unitIndex++) {
            String unitId = String.format("u%03d", unitIndex);
            boolean current = unitIndex <= 4;
            String schoolName = "学校" + unitIndex + "第01组";
            int tuition = unitIndex == 1 ? 30000 : 5000;
            String volunteerId = unitId + "-v1";

            CandidateItemDTO candidate = new CandidateItemDTO();
            candidate.setVolunteerId(volunteerId);
            candidate.setPlanSchoolDataId(unitId);
            candidate.setSchoolId("s" + unitId);
            candidate.setSchoolName(schoolName);
            candidate.setDisplaySchoolName(schoolName);
            candidate.setMajorName("专业" + unitIndex);
            candidate.setTier("protect");
            candidate.setProvinceName("江苏");
            candidate.setAdmissionRatio(70D);
            candidate.setSchoolEnrollRatio(60D);
            candidate.setFinalScore(80D);
            candidate.setIntentScore(40D);
            candidate.setTuitionPerYear(tuition);
            candidates.add(candidate);
            state.getCandidatePoolState().getItems().add(candidate);
            if (!current) {
                continue;
            }

            DraftUnitDTO workingUnit = new DraftUnitDTO();
            workingUnit.setUnitId(unitId);
            workingUnit.setTier("protect");
            workingUnit.setSchoolName(schoolName);
            OrderedUnitDTO orderedUnit = new OrderedUnitDTO();
            orderedUnit.setUnitId(unitId);
            orderedUnit.setPosition(unitIndex);
            orderedUnit.setTier("protect");
            orderedUnit.setSchoolName(schoolName);
            orderedUnit.setProvinceName("江苏");
            orderedUnit.setAdmissionRatio(70D);
            orderedUnit.setSchoolEnrollRatio(60D);

            DraftItemDTO selected = new DraftItemDTO();
            selected.setVolunteerId(volunteerId);
            selected.setTier("protect");
            selected.setSchoolName(schoolName);
            selected.setMajorName(candidate.getMajorName());
            state.getWorkingPlanState().getItems().add(selected);

            PlanningUnitMajorDTO workingMajor = new PlanningUnitMajorDTO();
            workingMajor.setVolunteerId(volunteerId);
            workingMajor.setMajorName(candidate.getMajorName());
            workingMajor.setTier("protect");
            workingUnit.getMajorItems().add(workingMajor);

            OrderedItemDTO ordered = new OrderedItemDTO();
            ordered.setVolunteerId(volunteerId);
            ordered.setTier("protect");
            ordered.setSchoolName(schoolName);
            ordered.setMajorName(candidate.getMajorName());
            ordered.setPosition(unitIndex);
            state.getOrderedPlanState().getItems().add(ordered);

            PlanningUnitMajorDTO orderedMajor = new PlanningUnitMajorDTO();
            orderedMajor.setVolunteerId(volunteerId);
            orderedMajor.setMajorName(candidate.getMajorName());
            orderedMajor.setTier("protect");
            orderedUnit.getMajorItems().add(orderedMajor);

            state.getWorkingPlanState().getUnits().add(workingUnit);
            state.getOrderedPlanState().getUnits().add(orderedUnit);
        }

        finding = new EvaluationFindingDTO();
        finding.setCode("high_tuition");
        finding.setResultStatus("fail");
        finding.setRuleStrength("soft");
        finding.setReasonCode("high_tuition");
        PlanCommandDTO command = new PlanCommandDTO();
        command.setStrategy("replace_risk_items");
        command.setApplyStrategy("fill_missing_count");
        command.setSourceStrategy("replace_risk_items");
        command.setSourceCheck("high_tuition");
        command.setLevel("unit");
        command.setTargetCount(4);
        command.getForcedRemoveTargets().add(ref("unit", "u001"));
        command.setEvaluationVersion("before-group-risk-evaluation");
        command.setCommandDigest("group-risk-command-digest");
        finding.setSuggestedCommand(command);
    }

    private FixProposalDTO plan(boolean confirmable) {
        String code = finding.getCode();
        return planner.plan(state, candidates, finding,
                after -> riskReview(code, "pass", "pass"), confirmable);
    }

    private ReviewStateDTO riskReview(String code, String riskStatus, String hardStatus) {
        ReviewStateDTO review = new ReviewStateDTO();
        review.setEvaluationStatus("completed");
        review.setEvaluationVersion("after-risk-evaluation");
        review.setProbesRun(2);
        review.setHardFeasible("pass".equals(hardStatus));
        EvaluationFindingDTO risk = new EvaluationFindingDTO();
        risk.setCode(code);
        risk.setResultStatus(riskStatus);
        risk.setRuleStrength("admission_limit".equals(code) ? "hard" : "soft");
        EvaluationFindingDTO count = new EvaluationFindingDTO();
        count.setCode("count_validation_hard");
        count.setResultStatus(hardStatus);
        count.setRuleStrength("hard");
        review.setFindings(Lists.newArrayList(risk, count));
        return review;
    }

    private EvaluationEntryRefDTO ref(String level, String id) {
        EvaluationEntryRefDTO ref = new EvaluationEntryRefDTO();
        ref.setLevel(level);
        ref.setId(id);
        return ref;
    }

    private CandidateItemDTO candidate(String id, int tuition) {
        CandidateItemDTO candidate = new CandidateItemDTO();
        candidate.setVolunteerId(id);
        candidate.setSchoolName("学校" + id);
        candidate.setMajorName("专业" + id);
        candidate.setTier("protect");
        candidate.setProvinceName("浙江");
        candidate.setTuitionPerYear(tuition);
        candidate.setAdmissionRatio(50D);
        candidate.setSchoolEnrollRatio(50D);
        candidate.setFinalScore(80D);
        candidate.setIntentScore(40D);
        return candidate;
    }
}
