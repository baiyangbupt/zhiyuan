package com.ytell.zhiyuan.service.biz;

import com.google.common.collect.Lists;
import com.ytell.zhiyuan.model.dto.planning.UpdateConstraintStateReq;
import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;

import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;

/**
 * **身份 ID** 并入硬约束的规矩：去重 ✓、同一值不得同时出现在两侧 ✓
 * （区域 ✓／专业 ✓ 用同一个 `mergeHardIdGroup` ✓——规矩一致，"ID 优先、名字兜底"才不打架 ✓）。
 *
 * <p>背景：区域 ID 那条（2026-09-25）当时**没有单测** ✗，只靠真栈读数 ✓；
 * 专业 ID 接入时补上，顺带给区域那条一起上一道闸 ✓。
 */
public class PlanningStateServiceHardConstraintIdMergeTest {

    private final PlanningStateService service = new PlanningStateService();

    @Test
    void shouldMergeMajorIdsWithDedupe() {
        List<String> positive = Lists.newArrayList("774");
        List<String> negative = Lists.newArrayList();

        merge(group(Lists.newArrayList("774", "774", "248"), Lists.newArrayList()), positive, negative);

        assertEquals(Lists.newArrayList("774", "248"), positive, "同一 ID 重复下发只留一条");
        assertEquals(0, negative.size());
    }

    @Test
    void shouldKeepMajorIdsOffBothSidesWhenTheyConflict() {
        List<String> positive = Lists.newArrayList("774");
        List<String> negative = Lists.newArrayList();

        // 同一个 ID 这次要"要"、下次要"排除"：后一条必须把前一条从对面摘掉 ✓
        merge(group(Lists.newArrayList(), Lists.newArrayList("774")), positive, negative);

        assertEquals(0, positive.size(), "同一个 ID 不能既包含又排除");
        assertEquals(Lists.newArrayList("774"), negative);
    }

    @Test
    void shouldMergeRegionIdsByTheSameRules() {
        List<String> positive = Lists.newArrayList("110000");
        List<String> negative = Lists.newArrayList();

        merge(group(Lists.newArrayList("110000", "120000"), Lists.newArrayList("120000")), positive, negative);

        assertEquals(Lists.newArrayList("110000"), positive);
        assertEquals(0, negative.size(), "出现在正侧的值要从负侧摘掉");
    }

    private static UpdateConstraintStateReq.PreferenceGroup group(List<String> positive, List<String> negative) {
        UpdateConstraintStateReq.PreferenceGroup group = new UpdateConstraintStateReq.PreferenceGroup();
        group.setPositive(positive);
        group.setNegative(negative);
        return group;
    }

    private void merge(UpdateConstraintStateReq.PreferenceGroup group,
                       List<String> hardPositive,
                       List<String> hardNegative) {
        ReflectionTestUtils.invokeMethod(service, "mergeHardIdGroup", group, hardPositive, hardNegative);
    }
}
