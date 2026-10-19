package com.ytell.zhiyuan.service.biz;

import com.google.common.collect.Lists;
import com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO;
import com.ytell.zhiyuan.model.dto.planning.CandidatePoolStateDTO;
import com.ytell.zhiyuan.model.dto.planning.DraftItemDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import org.junit.jupiter.api.Test;
import org.mockito.Mockito;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 约束生效后的"补足"：分阶段 solver 是唯一路径，不存在 legacy 贪心回退。
 *
 * <p>背景（2026-09-25 真栈实测）：约束路只有"同步"（删掉不合规的 ✗），没有"补足"——
 * 于是一次筛空就再也回不来（工作方案成 0 行后，此后任何重生成都从空方案出发 ✗）。
 * 补足要满足三条：**只追加 ✓、不动用户已有条目 ✓、不重复/不越过已禁 ✓**。
 */
public class PlanningStateServiceRefillTest {

    private final PlanningStateService service = new PlanningStateService();

    @Test
    void stagedRefillAppendsOnlyMissingTierItems() {
        PlanningStateDTO state = stateWithSingleExistingSprintItem();
        CandidatePoolStateDTO pool = state.getCandidatePoolState();
        pool.setRequiredCount(2);
        pool.getRequiredTierCounts().put("冲", 2);
        CandidateItemDTO existing = pool.getItems().get(0);
        CandidateItemDTO missing = candidate("v-new", "冲");
        pool.getItems().add(missing);

        boolean applied = service.refillWithStagedSolver(
                state, 1L, 1L, Lists.newArrayList(existing, missing), pool);

        assertTrue(applied, "staged refill should apply");
        assertEquals(2, state.getDraftPlanState().getItems().size());
        assertTrue(state.getDraftPlanState().getItems().stream()
                .anyMatch(row -> "v-new".equals(row.getVolunteerId())));
    }

    /**
     * 旧路径/灰度门控已删除：补足无条件走分阶段 solver，没有 greedy 回退。
     */
    @Test
    void applyTierTargetRefillAlwaysUsesStagedSolver() {
        PlanningStateService spy = Mockito.spy(new PlanningStateService());
        PlanningStateDTO state = stateWithSingleExistingSprintItem();
        CandidatePoolStateDTO pool = state.getCandidatePoolState();
        pool.setRequiredCount(2);
        pool.getRequiredTierCounts().put("冲", 2);
        pool.getItems().add(candidate("v-new", "冲"));

        Mockito.doReturn(true).when(spy).refillWithStagedSolver(
                Mockito.same(state), Mockito.isNull(), Mockito.isNull(),
                Mockito.anyList(), Mockito.same(pool));

        boolean applied = spy.applyTierTargetRefill(state, null, null);

        assertTrue(applied, "staged solver result should drive the refill");
        Mockito.verify(spy).refillWithStagedSolver(
                Mockito.same(state), Mockito.isNull(), Mockito.isNull(),
                Mockito.anyList(), Mockito.same(pool));
    }

    /** solver 返回 false（已无缺口）时：补足返回 false，工作方案保持不变、不写盘。 */
    @Test
    void applyTierTargetRefillReturnsFalseAndLeavesPlanUnchangedWhenNoGap() {
        PlanningStateDTO state = stateWithSingleExistingSprintItem();
        state.getCandidatePoolState().getRequiredTierCounts().put("冲", 1);

        boolean applied = service.applyTierTargetRefill(state, null, null);

        assertFalse(applied, "no gap means nothing was applied");
        assertEquals(1, state.getDraftPlanState().getItems().size());
        assertEquals("v-existing", state.getDraftPlanState().getItems().get(0).getVolunteerId());
        assertTrue(state.getDraftPlanState().getUnits().isEmpty());
    }

    /** solver 无法达到目标（候选不足）：返回 false，不做 legacy 贪心兜底，工作方案原样返回。 */
    @Test
    void applyTierTargetRefillReturnsFalseWithoutLegacyFallbackWhenSolverCannotReachTarget() {
        PlanningStateDTO state = stateWithSingleExistingSprintItem();
        state.getCandidatePoolState().getRequiredTierCounts().put("冲", 2);

        boolean applied = service.applyTierTargetRefill(state, null, null);

        assertFalse(applied, "staged solver cannot satisfy the target");
        assertEquals(1, state.getDraftPlanState().getItems().size(),
                "no legacy greedy rows may be added");
        assertEquals("v-existing", state.getDraftPlanState().getItems().get(0).getVolunteerId());
    }

    private static PlanningStateDTO stateWithSingleExistingSprintItem() {
        PlanningStateDTO state = new PlanningStateDTO();
        CandidatePoolStateDTO pool = state.getCandidatePoolState();
        pool.setItems(Lists.newArrayList(candidate("v-existing", "冲")));
        DraftItemDTO draftItem = item("v-existing", "冲");
        state.getWorkingPlanState().getItems().add(draftItem);
        return state;
    }

    private static DraftItemDTO item(String volunteerId, String tier) {
        DraftItemDTO item = new DraftItemDTO();
        item.setVolunteerId(volunteerId);
        item.setTier(tier);
        return item;
    }

    private static CandidateItemDTO candidate(String volunteerId, String tier) {
        CandidateItemDTO candidate = new CandidateItemDTO();
        candidate.setVolunteerId(volunteerId);
        candidate.setTier(tier);
        candidate.setSchoolName("测试大学");
        candidate.setMajorName("测试专业");
        return candidate;
    }
}
