package com.ytell.zhiyuan.service.biz;

import com.alibaba.fastjson.JSON;
import com.google.common.collect.Lists;
import com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO;
import com.ytell.zhiyuan.model.dto.planning.DraftItemDTO;
import com.ytell.zhiyuan.model.dto.planning.DraftUnitDTO;
import com.ytell.zhiyuan.model.dto.planning.EvaluationFindingDTO;
import com.ytell.zhiyuan.model.dto.planning.FixProposalDTO;
import com.ytell.zhiyuan.model.dto.planning.FixProposalActionDTO;
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

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

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
    private static final int GROUP_UNITS = 44;
    private static final int GROUP_EXTRA_UNITS = 2;
    private static final int GROUP_MAJORS_PER_UNIT = 2;

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

    // ── 组模式（专业单元）本省保底切片 ───────────────────────────────────────

    @Test
    void groupSafetyFreezesFortyFourUnitsWithTwoLocalProtectUnits() {
        groupFixture();
        String baseline = JSON.toJSONString(state);

        FixProposalDTO proposal = planner.plan(state, candidates, finding, after -> {
            assertEquals(GROUP_UNITS, after.getOrderedPlanState().getUnits().size(),
                    "目标数按 unit 计");
            assertEquals(GROUP_UNITS * GROUP_MAJORS_PER_UNIT,
                    after.getOrderedPlanState().getItems().size());
            assertEquals(GROUP_UNITS, after.getWorkingPlanState().getUnits().size());
            assertEquals(GROUP_UNITS * GROUP_MAJORS_PER_UNIT,
                    after.getWorkingPlanState().getItems().size());
            assertTrue(localProtectUnitCount(orderedUnitIds(after)) >= SAFETY_MIN,
                    "物化后的排序态必须含 2 个本省保底专业组");
            for (int index = 0; index < GROUP_UNITS; index++) {
                assertEquals(Integer.valueOf(index + 1),
                        after.getOrderedPlanState().getUnits().get(index).getPosition());
            }
            return safetyReview("pass");
        }, true);

        assertEquals("ready", proposal.getStatus());
        assertTrue(proposal.getRequiresConfirmation());
        assertEquals("fill_missing_count", proposal.getStrategy());
        assertEquals("add_safety_items", proposal.getSourceStrategy());
        assertEquals("safety_guard", proposal.getFindingCode());
        assertEquals(Integer.valueOf(7), proposal.getSourceVersionGuard());
        assertEquals("ready", proposal.getSolverResult().getStatus());
        assertEquals(GROUP_UNITS, proposal.getSolverResult().getSelectedEntityIds().size());
        assertTrue(localProtectUnitCount(proposal.getSolverResult().getSelectedEntityIds())
                >= SAFETY_MIN);
        assertEquals(Integer.valueOf(GROUP_UNITS), proposal.getTargetCountBefore());
        assertEquals(Integer.valueOf(GROUP_UNITS), proposal.getTargetCountAfter());
        assertEquals(Integer.valueOf(SAFETY_MIN), proposal.getAddedUnitCount());
        assertEquals(Integer.valueOf(SAFETY_MIN), proposal.getRemovedCount());
        assertTrue(proposal.getFindingPostcondition().getSatisfied());
        assertEquals("safety_guard", proposal.getFindingPostcondition().getFindingCode());

        assertFalse(proposal.getActions().isEmpty());
        boolean sawRemove = false;
        boolean sawAdd = false;
        for (FixProposalActionDTO action : proposal.getActions()) {
            assertEquals("unit", action.getLevel());
            if ("remove_volunteers".equals(action.getActionType())) {
                sawRemove = true;
                assertEquals(SAFETY_MIN, action.getRemoveUnitIds().size());
            }
            if ("fill_total_count".equals(action.getActionType())) {
                sawAdd = true;
                assertEquals(SAFETY_MIN, action.getUnitIds().size());
                assertEquals(SAFETY_MIN, action.getCandidateUnitIds().size());
            }
        }
        assertTrue(sawRemove && sawAdd, "组模式必须同时给出 unit 级移出与补入动作");
        assertEquals(Integer.valueOf(GROUP_UNITS), proposal.getDryRunResult().getBeforeUnitTotal());
        assertEquals(Integer.valueOf(GROUP_UNITS), proposal.getDryRunResult().getAfterUnitTotal());
        assertEquals(GROUP_UNITS, proposal.getDryRunResult().getBeforeUnitIds().size());
        assertEquals(GROUP_UNITS, proposal.getDryRunResult().getAfterUnitIds().size());
        assertEquals(Integer.valueOf(SAFETY_MIN), proposal.getDryRunResult().getAddUnitCount());
        assertEquals(Integer.valueOf(SAFETY_MIN), proposal.getDryRunResult().getRemoveUnitCount());

        FrozenReviewPlanDTO frozen = proposal.getFrozenReviewPlan();
        assertNotNull(frozen);
        assertEquals(GROUP_UNITS, frozen.getSelectedEntityIds().size());
        assertEquals(GROUP_UNITS, frozen.getOrderedEntityIds().size());
        assertEquals(GROUP_UNITS, frozen.getWorkingPlan().getUnits().size());
        assertEquals(GROUP_UNITS, frozen.getOrderedPlan().getUnits().size());
        assertEquals(GROUP_UNITS * GROUP_MAJORS_PER_UNIT,
                frozen.getWorkingPlan().getItems().size());
        assertEquals(GROUP_UNITS * GROUP_MAJORS_PER_UNIT,
                frozen.getOrderedPlan().getItems().size());
        assertEquals(GROUP_UNITS * GROUP_MAJORS_PER_UNIT, frozen.getSelectedFacts().size());
        assertEquals(frozen.getOrderedEntityIds(), frozen.getOrderedPlan().getUnits().stream()
                .map(OrderedUnitDTO::getUnitId).collect(java.util.stream.Collectors.toList()));
        for (int index = 0; index < GROUP_UNITS; index++) {
            assertEquals(Integer.valueOf(index + 1),
                    frozen.getOrderedPlan().getUnits().get(index).getPosition());
        }
        for (int index = 0; index < GROUP_UNITS * GROUP_MAJORS_PER_UNIT; index++) {
            assertEquals(Integer.valueOf(index + 1),
                    frozen.getOrderedPlan().getItems().get(index).getPosition());
        }
        assertTrue(localProtectUnitCount(frozen.getSelectedEntityIds()) >= SAFETY_MIN);
        assertEquals(DirectReviewPreviewPlanner.factsDigestForUnits(
                        frozen.getSelectedEntityIds(), frozen.getOrderedPlan().getUnits(), candidates),
                frozen.getFactsDigest());
        assertNotNull(proposal.getPreviewDigest());
        assertNotNull(proposal.getPlanContentDigest());
        assertEquals(baseline, JSON.toJSONString(state), "规划器不得修改输入状态");
    }

    @Test
    void groupSafetyDetectsUnitModeFromOrderedUnitsWhenVolunteerModelIsMissing() {
        groupFixture();
        state.getCandidatePoolState().setVolunteerModel(null);

        FixProposalDTO proposal = planner.plan(state, candidates, finding,
                after -> safetyReview("pass"), true);

        assertEquals("ready", proposal.getStatus());
        assertNotNull(proposal.getFrozenReviewPlan());
        assertEquals(GROUP_UNITS, proposal.getFrozenReviewPlan().getOrderedPlan().getUnits().size());
        assertTrue(localProtectUnitCount(
                proposal.getFrozenReviewPlan().getSelectedEntityIds()) >= SAFETY_MIN);
    }

    @Test
    void groupSafetyAcceptsSparsePositionsAndMissingWorkingUnits() {
        groupFixture();
        for (int index = 0; index < state.getOrderedPlanState().getUnits().size(); index++) {
            state.getOrderedPlanState().getUnits().get(index).setPosition((index + 1) * 2);
        }
        state.getWorkingPlanState().getUnits().clear();

        FixProposalDTO proposal = planner.plan(state, candidates, finding,
                after -> safetyReview("pass"), true);

        assertEquals("ready", proposal.getStatus());
        assertNotNull(proposal.getFrozenReviewPlan());
        assertEquals(GROUP_UNITS, proposal.getFrozenReviewPlan().getOrderedPlan().getUnits().size());
    }

    @Test
    void groupSafetyRejectsLocksPinsPriorityRulesAndMalformedUnits() {
        groupFixture();
        state.getOrderedPlanState().getUnits().get(0).setPinned(true);
        assertNull(plan(false));
        state.getOrderedPlanState().getUnits().get(0).setPinned(null);
        state.getOrderedPlanState().getUnits().get(0).setLocked(true);
        assertNull(plan(false));
        state.getOrderedPlanState().getUnits().get(0).setLocked(null);
        state.getOrderedPlanState().getUnits().get(0).setPinnedPosition(3);
        assertNull(plan(false));
        state.getOrderedPlanState().getUnits().get(0).setPinnedPosition(null);

        PriorityRuleDTO rule = new PriorityRuleDTO();
        rule.setDomain("region");
        rule.setKey("province");
        rule.setValues(Lists.newArrayList("江西"));
        state.getConstraintState().getHardPlanningObjectives().getPriorityRules().add(rule);
        assertNull(plan(false));
        state.getConstraintState().getHardPlanningObjectives().getPriorityRules().clear();

        state.getOrderedPlanState().getUnits().get(1).setPosition(1);
        assertNull(plan(false), "位置必须严格递增");
        state.getOrderedPlanState().getUnits().get(1).setPosition(2);
        state.getOrderedPlanState().getUnits().get(2).setUnitId("u001");
        assertNull(plan(false), "unitId 必须唯一");
        state.getOrderedPlanState().getUnits().get(2).setUnitId("u003");
        state.getOrderedPlanState().getUnits().clear();
        assertNull(plan(false), "没有 ordered units 时不得退回志愿口径");
    }

    /**
     * 组模式安全切片：44 个现有专业组全部是外省冲刺（0 个本省保底），候选池额外
     * 提供 2 个江西 protect 专业组；目标数 44 不变，靠等量替换满足保底 2 组。
     */
    private void groupFixture() {
        state = new PlanningStateDTO();
        state.setVersion(7);
        state.setPhase("ordered");
        state.getCandidatePoolState().setVolunteerModel("majorGroup");
        state.getCandidatePoolState().setRequiredCount(GROUP_UNITS);
        state.getCandidatePoolState().setSourceProvinceName("江西");
        state.getCandidatePoolState().setUserScore(550);
        state.getConstraintState().getHardPlanningObjectives().setSelectionTargetCount(GROUP_UNITS);

        candidates = Lists.newArrayList();
        for (int unitIndex = 1; unitIndex <= GROUP_UNITS + GROUP_EXTRA_UNITS; unitIndex++) {
            String unitId = String.format("u%03d", unitIndex);
            boolean current = unitIndex <= GROUP_UNITS;
            boolean local = unitIndex > GROUP_UNITS;
            String tier = local ? "protect" : "sprint";
            String province = local ? "江西" : "江苏";
            String schoolName = "学校" + unitIndex + "第01组";

            DraftUnitDTO workingUnit = current ? new DraftUnitDTO() : null;
            if (workingUnit != null) {
                workingUnit.setUnitId(unitId);
                workingUnit.setTier(tier);
                workingUnit.setSchoolName(schoolName);
            }
            OrderedUnitDTO orderedUnit = current ? new OrderedUnitDTO() : null;
            if (orderedUnit != null) {
                orderedUnit.setUnitId(unitId);
                orderedUnit.setPosition(unitIndex);
                orderedUnit.setTier(tier);
                orderedUnit.setSchoolName(schoolName);
                orderedUnit.setProvinceName(province);
                orderedUnit.setAdmissionRatio(70D);
                orderedUnit.setSchoolEnrollRatio(60D);
                orderedUnit.setTotalMajorCount(GROUP_MAJORS_PER_UNIT);
            }
            for (int majorIndex = 1; majorIndex <= GROUP_MAJORS_PER_UNIT; majorIndex++) {
                String volunteerId = unitId + "-v" + majorIndex;
                CandidateItemDTO candidate = new CandidateItemDTO();
                candidate.setVolunteerId(volunteerId);
                candidate.setPlanSchoolDataId(unitId);
                candidate.setSchoolId("s" + unitId);
                candidate.setSchoolName(schoolName);
                candidate.setDisplaySchoolName(schoolName);
                candidate.setMajorName("专业" + unitIndex + "-" + majorIndex);
                candidate.setMajorCategory("工学");
                candidate.setTier(tier);
                candidate.setProvinceName(province);
                candidate.setAdmissionRatio(70D);
                candidate.setSchoolEnrollRatio(60D);
                candidate.setFinalScore(80D);
                candidate.setIntentScore(40D);
                candidate.setTuitionPerYear(5000);
                candidates.add(candidate);
                state.getCandidatePoolState().getItems().add(candidate);
                if (!current) {
                    continue;
                }
                DraftItemDTO selected = new DraftItemDTO();
                selected.setVolunteerId(volunteerId);
                selected.setTier(tier);
                selected.setSchoolName(schoolName);
                selected.setMajorName(candidate.getMajorName());
                state.getWorkingPlanState().getItems().add(selected);

                PlanningUnitMajorDTO workingMajor = new PlanningUnitMajorDTO();
                workingMajor.setVolunteerId(volunteerId);
                workingMajor.setMajorName(candidate.getMajorName());
                workingMajor.setTier(tier);
                workingUnit.getMajorItems().add(workingMajor);

                OrderedItemDTO ordered = new OrderedItemDTO();
                ordered.setVolunteerId(volunteerId);
                ordered.setTier(tier);
                ordered.setSchoolName(schoolName);
                ordered.setMajorName(candidate.getMajorName());
                ordered.setPosition(state.getOrderedPlanState().getItems().size() + 1);
                state.getOrderedPlanState().getItems().add(ordered);

                PlanningUnitMajorDTO orderedMajor = new PlanningUnitMajorDTO();
                orderedMajor.setVolunteerId(volunteerId);
                orderedMajor.setMajorName(candidate.getMajorName());
                orderedMajor.setTier(tier);
                orderedUnit.getMajorItems().add(orderedMajor);
            }
            if (workingUnit != null) {
                state.getWorkingPlanState().getUnits().add(workingUnit);
                state.getOrderedPlanState().getUnits().add(orderedUnit);
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
        command.setLevel("unit");
        command.setTargetCount(GROUP_UNITS);
        command.setSafetyMinLocalProtect(SAFETY_MIN);
        command.setEvaluationVersion("before-group-safety-evaluation");
        command.setCommandDigest("group-safety-command-digest");
        finding.setSuggestedCommand(command);
    }

    private List<String> orderedUnitIds(PlanningStateDTO current) {
        List<String> ids = Lists.newArrayList();
        for (OrderedUnitDTO unit : current.getOrderedPlanState().getUnits()) {
            ids.add(unit.getUnitId());
        }
        return ids;
    }

    private long localProtectUnitCount(List<String> unitIds) {
        long count = 0;
        for (String unitId : unitIds) {
            for (CandidateItemDTO candidate : candidates) {
                if (unitId.equals(candidate.getPlanSchoolDataId())) {
                    if ("protect".equals(candidate.getTier())
                            && "江西".equals(candidate.getProvinceName())) {
                        count++;
                    }
                    break;
                }
            }
        }
        return count;
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
