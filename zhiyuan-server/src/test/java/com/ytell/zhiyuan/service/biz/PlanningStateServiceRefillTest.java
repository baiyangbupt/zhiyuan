package com.ytell.zhiyuan.service.biz;

import com.google.common.collect.Lists;
import com.google.common.collect.Maps;
import com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO;
import com.ytell.zhiyuan.model.dto.planning.DraftItemDTO;
import com.ytell.zhiyuan.model.dto.planning.DraftPlanStateDTO;
import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 约束生效后的"补足"（`refillWorkingPlanByTier`）。
 *
 * <p>背景（2026-09-25 真栈实测）：约束路只有"同步"（删掉不合规的 ✗），没有"补足"——
 * 于是一次筛空就再也回不来（工作方案成 0 行后，此后任何重生成都从空方案出发 ✗）。
 * 补足要满足三条：**只追加 ✓、不动用户已有条目 ✓、不重复/不越过已禁 ✓**。
 */
public class PlanningStateServiceRefillTest {

    private final PlanningStateService service = new PlanningStateService();

    @Test
    void shouldAppendUntilTierTargetsAreMet() {
        DraftPlanStateDTO draft = new DraftPlanStateDTO();
        draft.getItems().add(item("v-existing", "冲"));
        List<CandidateItemDTO> candidates = Lists.newArrayList(
                candidate("v-sprint", "冲"), candidate("v-stable", "稳"), candidate("v-protect", "保"));
        Map<String, Integer> targets = Maps.newHashMap();
        targets.put("冲", 2);
        targets.put("稳", 1);

        service.refillWorkingPlanByTier(draft, candidates, targets);

        assertEquals(3, draft.getItems().size());
        assertEquals(2, countTier(draft, "冲"));
        assertEquals(1, countTier(draft, "稳"));
        assertEquals(0, countTier(draft, "保"), "没给目标的档位不补");
        assertEquals("v-existing", draft.getItems().get(0).getVolunteerId(), "已有条目不动、且仍在最前");
    }

    @Test
    void shouldSkipAlreadySelectedAndBannedCandidates() {
        DraftPlanStateDTO draft = new DraftPlanStateDTO();
        draft.getItems().add(item("v-existing", "冲"));
        draft.getBannedVolunteerIds().add("v-banned");
        List<CandidateItemDTO> candidates = Lists.newArrayList(
                candidate("v-banned", "冲"), candidate("v-new", "冲"), candidate("v-existing", "冲"));
        Map<String, Integer> targets = Maps.newHashMap();
        targets.put("冲", 3);

        service.refillWorkingPlanByTier(draft, candidates, targets);

        assertEquals(2, countTier(draft, "冲"), "已禁的不补、已选的不重复");
        assertTrue(draft.getItems().stream().anyMatch(row -> "v-new".equals(row.getVolunteerId())));
        assertTrue(draft.getItems().stream().noneMatch(row -> "v-banned".equals(row.getVolunteerId())));
    }

    @Test
    void shouldLeavePlanUntouchedWhenNoTierTargets() {
        DraftPlanStateDTO draft = new DraftPlanStateDTO();
        draft.getItems().add(item("v-existing", "冲"));

        service.refillWorkingPlanByTier(draft, Lists.newArrayList(candidate("v-sprint", "冲")),
                Maps.newHashMap());

        assertEquals(1, draft.getItems().size());
    }

    private static int countTier(DraftPlanStateDTO draft, String tier) {
        return (int) draft.getItems().stream().filter(row -> tier.equals(row.getTier())).count();
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
