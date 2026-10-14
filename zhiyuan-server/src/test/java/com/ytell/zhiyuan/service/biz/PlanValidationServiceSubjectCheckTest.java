package com.ytell.zhiyuan.service.biz;

import com.google.common.collect.Lists;
import com.ytell.zhiyuan.manager.MajorProfileManager;
import com.ytell.zhiyuan.model.dto.MajorProfileDto;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;

import java.util.List;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 方案校验-选科核对（2026-10-14 选科适配 P0）：用**真实画像数据**的 selectLimit 走
 * {@code checkSubjectRequirement}。
 *
 * <p>修复前："化或生 / 物和(化或生)"等要求解析成空 → selectLimit 为空 → 校验恒"满足"
 * （假阳性，全模式）。本测试锁死"要求真实生效"的口径。</p>
 */
public class PlanValidationServiceSubjectCheckTest {

    private static MajorProfileManager manager;
    private static PlanValidationService service;

    @BeforeAll
    static void loadOnce() {
        manager = new MajorProfileManager();
        manager.init();
        service = new PlanValidationService();
    }

    private boolean check(String majorId, String... studentSubjects) {
        MajorProfileDto profile = manager.getMajorProfileById(majorId);
        List<List<String>> selectLimit = profile.getSelectLimit();
        return Boolean.TRUE.equals(ReflectionTestUtils.invokeMethod(
                service, "checkSubjectRequirement", Lists.newArrayList(studentSubjects), selectLimit, majorId));
    }

    @Test
    void emptySelectLimitMeansSatisfied() {
        assertTrue(check("233", "物理", "生物", "化学"), "不限：任何选科都满足");
        assertTrue(check("233", "历史", "地理", "政治"));
    }

    @Test
    void orExpressionRequirementIsNowEnforced() {
        // 药事管理"化或生"：修复前 selectLimit 为空 → 恒满足（假阳性）。
        assertFalse(check("804", "物理", "政治", "历史"), "化/生都没有 → 不满足（修复前恒满足）");
        assertTrue(check("804", "物理", "化学", "生物"));
        assertTrue(check("804", "历史", "生物", "地理"), "有生物即满足");
    }

    @Test
    void nestedAndOrRequirementIsNowEnforced() {
        // 082702 食品质量与安全"物和(化或生)"：物+化 或 物+生。
        MajorProfileDto profile = manager.getMajorProfileByCode("082702");
        assertTrue(checkByLimit(profile, "物理", "生物", "地理"));
        assertTrue(checkByLimit(profile, "物理", "化学", "历史"));
        assertFalse(checkByLimit(profile, "物理", "政治", "历史"), "只有物理，化/生都没有 → 不满足");
        assertFalse(checkByLimit(profile, "化学", "生物", "地理"), "缺物理 → 不满足");
    }

    @Test
    void andExpressionAndSingleSubjectKeepOldSemantics() {
        assertTrue(check("459", "物理", "化学", "生物"));
        assertFalse(check("459", "物理", "生物", "政治"), "物和化：缺化学 → 不满足");
        assertTrue(check("238", "物理", "化学", "生物"), "物 → 物理满足");
        assertFalse(check("238", "历史", "化学", "生物"), "物 → 无物理不满足");
        assertFalse(check("267", "物理", "化学", "生物"), "政 → 无政治不满足");
        assertTrue(check("267", "政治", "历史", "地理"));
    }

    private static boolean checkByLimit(MajorProfileDto profile, String... studentSubjects) {
        return Boolean.TRUE.equals(ReflectionTestUtils.invokeMethod(
                service, "checkSubjectRequirement",
                Lists.newArrayList(studentSubjects), profile.getSelectLimit(), profile.getMajorCode()));
    }
}
