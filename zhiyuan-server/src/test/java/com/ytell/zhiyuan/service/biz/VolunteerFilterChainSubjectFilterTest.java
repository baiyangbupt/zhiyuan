package com.ytell.zhiyuan.service.biz;

import com.google.common.collect.Lists;
import com.ytell.zhiyuan.model.dto.inner.UserIntentQueryReq;
import com.ytell.zhiyuan.model.dto.volunteer.VolunteerMajor;
import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 候选池选科过滤（2026-10-14 选科适配 P0）。
 *
 * <p>三个修复点：① "物理或化学"这类或表达式此前整体当单一科目 → 整条专业被误杀；
 * ② 不认识"技/技术"（浙江）→ 需要技术科目的专业无条件保留；
 * ③ "化或生"等嵌套/或要求与"物和化"口径不一。判定语义：任一组合满足即保留；</p>
 * <p>解析不出（含"不限"、空、非科目取值）→ 不过滤（fail-open，不把"解析不了"当"不满足"）。</p>
 */
public class VolunteerFilterChainSubjectFilterTest {

    private final VolunteerFilterChain chain = new VolunteerFilterChain();

    private boolean filtered(String selectInfo, String... userSubjects) {
        UserIntentQueryReq req = new UserIntentQueryReq();
        req.setSubjects(Lists.newArrayList(userSubjects));
        VolunteerMajor major = new VolunteerMajor();
        major.setSelectInfo(selectInfo);
        return Boolean.TRUE.equals(ReflectionTestUtils.invokeMethod(chain, "isSubjectFiltered", req, major));
    }

    @Test
    void andExpressionKeepsOnlyWhenAllSubjectsPresent() {
        assertFalse(filtered("物和化", "物理", "化学", "生物"), "物理+化学 → 保留");
        assertTrue(filtered("物和化", "物理"), "缺化学 → 过滤");
        assertTrue(filtered("物和化", "化学"), "缺物理 → 过滤");
    }

    @Test
    void orExpressionIsEvaluatedInsteadOfKillingTheWholeMajor() {
        // 修复前："物理或化学"当单科名 → 谁都匹配不上 → 整条专业被误杀。
        assertFalse(filtered("物理或化学", "物理"), "有物理即满足 → 保留");
        assertFalse(filtered("物理或化学", "化学"), "有化学即满足 → 保留");
        assertTrue(filtered("物理或化学", "历史", "生物"), "两科都缺 → 过滤");
    }

    @Test
    void zhejiangTechnologySubjectIsRecognized() {
        // 修复前：requireTypes 为空（技被跳过）→ 永远保留。
        assertFalse(filtered("技", "物理", "化学", "技术"), "浙江：有技术科 → 保留");
        assertFalse(filtered("技术", "物理", "化学", "技术"));
        assertTrue(filtered("技", "物理", "化学", "生物"), "无技术科 → 过滤");
        assertTrue(filtered("物和技", "物理"), "物和技：缺技术 → 过滤");
        assertFalse(filtered("物和技", "物理", "技术"), "物和技：两科都有 → 保留");
    }

    @Test
    void nestedAndOrExpressionExpandsToOptions() {
        // 物和(化或生)：物+化 或 物+生 都可。
        assertFalse(filtered("物和(化或生)", "物理", "生物"));
        assertFalse(filtered("物和(化或生)", "物理", "化学"));
        assertTrue(filtered("物和(化或生)", "物理"), "只有物理，化/生都没有 → 过滤");
        assertTrue(filtered("物和(化或生)", "化学", "生物"), "缺物理 → 过滤");
    }

    @Test
    void orExpressionWithSingleSubjectKeepsEitherAlternative() {
        assertFalse(filtered("化或生", "生物"));
        assertFalse(filtered("化或生", "化学"));
        assertTrue(filtered("化或生", "物理", "政治", "历史"), "化学/生物都没有 → 过滤");
    }

    @Test
    void singleSubjectAndAliasFormsAreCovered() {
        assertFalse(filtered("物", "物理", "化学"));
        assertTrue(filtered("物", "化学", "生物"));
        assertFalse(filtered("史", "历史", "地理", "政治"), "史=历史：组合口径");
        assertFalse(filtered("政", "政治", "地理"), "政=政治");
        assertTrue(filtered("政", "地理", "历史"));
    }

    @Test
    void unlimitedAndEmptyRequirementsNeverFilter() {
        assertFalse(filtered("不限", "物理"));
        assertFalse(filtered("", "物理"));
        assertFalse(filtered(null, "物理"));
        assertFalse(filtered("   ", "物理"));
    }

    @Test
    void unparsableRequirementFailsOpenAndEmptyUserSubjectsNeverFilter() {
        assertFalse(filtered("语种:英语", "物理"), "解析不了 → 不当作不满足");
        assertFalse(filtered("物和X", "物理"));
        assertFalse(filtered("物和化"), "用户无选科信息 → 不过滤（数据不完整保护）");
        UserIntentQueryReq req = new UserIntentQueryReq();
        req.setSubjects(null);
        VolunteerMajor major = new VolunteerMajor();
        major.setSelectInfo("物和化");
        assertFalse(Boolean.TRUE.equals(ReflectionTestUtils.invokeMethod(chain, "isSubjectFiltered", req, major)));
    }
}
