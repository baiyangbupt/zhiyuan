package com.ytell.zhiyuan.manager;

import com.google.common.collect.Lists;
import com.ytell.zhiyuan.model.dto.MajorProfileDto;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 专业画像加载 + selectLimit 转换（2026-10-14 选科适配 P0）：
 * 用真实 classpath 的 major_profile-0615.xlsx 验证"不限/单科/与/或/嵌套"等真实形态全部被解析，
 * 且 不限/空 保持空列表（无约束）。修复前"化或生"类要求 selectLimit 恒空 → 选科校验假阳性。
 */
public class MajorProfileManagerTest {

    private static MajorProfileManager manager;

    @BeforeAll
    static void loadOnce() {
        manager = new MajorProfileManager();
        manager.init();
    }

    /** 注意：Lists.newArrayList(单个 Iterable) 会命中 Iterable 重载并拍平一层，必须用本助手。 */
    @SafeVarargs
    private static List<List<String>> options(List<String>... combinations) {
        return Lists.newArrayList(combinations);
    }

    private List<List<String>> selectLimitOf(String id) {
        MajorProfileDto profile = manager.getMajorProfileById(id);
        assertNotNull(profile, "id=" + id + " 应存在");
        return profile.getSelectLimit();
    }

    @Test
    void everyRowIsLoadedAndLimitsMatchRequirementRows() {
        int total = manager.getMajorProfileCount();
        assertEquals(1617, total, "0615 画像共 1617 行");
        int withLimit = 0;
        for (MajorProfileDto profile : manager.getAllMajorProfiles()) {
            if (profile.getSelectLimit() != null && !profile.getSelectLimit().isEmpty()) {
                withLimit++;
            }
        }
        // 数据形态：不限 303 行 + 空 876 行均无约束；其余 438 行都有可解析要求。
        assertEquals(438, withLimit, "每一条有实质要求的行都必须解析出 selectLimit");
    }

    @Test
    void unlimitedRowHasEmptyLimit() {
        assertEquals("不限", manager.getMajorProfileById("233").getSelectInfo());
        assertTrue(selectLimitOf("233").isEmpty(), "不限 → 空列表（无选科限制）");
    }

    @Test
    void singleSubjectRowsMapToSingleSubject() {
        assertEquals(options(Lists.newArrayList("物理")), selectLimitOf("238"));
        assertEquals(options(Lists.newArrayList("政治")), selectLimitOf("267"));
        assertEquals(options(Lists.newArrayList("生物")), selectLimitOf("762"));
    }

    @Test
    void andExpressionRowBecomesOneCombination() {
        assertEquals(options(Lists.newArrayList("物理", "化学")), selectLimitOf("459"));
        assertEquals(options(Lists.newArrayList("物理", "化学")), selectLimitOf("574"),
                "计算机科学与技术：与线上 selectLimit=[['物理','化学']] 口径一致");
    }

    @Test
    void orExpressionRowBecomesAlternativeCombinations() {
        // 药事管理"化或生"：修复前解析为空（假阳性），现在为两条备选。
        assertEquals(options(Lists.newArrayList("化学"), Lists.newArrayList("生物")),
                selectLimitOf("804"));
    }

    @Test
    void nestedAndOrRowExpandsToOptions() {
        MajorProfileDto profile = manager.getMajorProfileByCode("082702");
        assertNotNull(profile);
        assertEquals("食品质量与安全", profile.getName());
        assertEquals("物和(化或生)", profile.getSelectInfo());
        assertEquals(
                options(Lists.newArrayList("物理", "化学"), Lists.newArrayList("物理", "生物")),
                profile.getSelectLimit());
    }

    @Test
    void emptyRequirementRowStaysEmpty() {
        MajorProfileDto profile = manager.getMajorProfileByCode("490102");
        assertNotNull(profile);
        assertTrue(profile.getSelectInfo() == null || profile.getSelectInfo().trim().isEmpty(),
                "该行 select_info 为空");
        assertTrue(profile.getSelectLimit().isEmpty(), "无要求 → 空列表（不硬猜）");
    }
}
