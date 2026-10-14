package com.ytell.zhiyuan.common.util;

import com.google.common.collect.Lists;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 选科要求解析器（2026-10-14 选科适配 P0）：不限 / 单科 / 组合码 / 或关系 / 与关系 / 括号 / 技。
 */
public class SubjectRequirementParserTest {

    /** 注意：Lists.newArrayList(单个 Iterable) 会命中 Iterable 重载并拍平一层，必须用本助手。 */
    @SafeVarargs
    private static List<List<String>> options(List<String>... combinations) {
        return Lists.newArrayList(combinations);
    }

    @Test
    void noConstraintAndBlankReturnEmpty() {
        assertTrue(SubjectRequirementParser.parseOptions(null).isEmpty());
        assertTrue(SubjectRequirementParser.parseOptions("").isEmpty());
        assertTrue(SubjectRequirementParser.parseOptions("  ").isEmpty());
        assertTrue(SubjectRequirementParser.parseOptions("不限").isEmpty());
        assertTrue(SubjectRequirementParser.parseCombinationCodes(null).isEmpty());
        assertTrue(SubjectRequirementParser.parseCombinationCodes("").isEmpty());
    }

    @Test
    void singleSubjectAbbreviationAndFullName() {
        assertEquals(options(Lists.newArrayList("物理")),
                SubjectRequirementParser.parseOptions("物"));
        assertEquals(options(Lists.newArrayList("化学")),
                SubjectRequirementParser.parseOptions("化学"));
        assertEquals(options(Lists.newArrayList("历史")),
                SubjectRequirementParser.parseOptions("史"));
    }

    @Test
    void zhejiangTechnologySubjectIsMapped() {
        assertEquals(options(Lists.newArrayList("技术")),
                SubjectRequirementParser.parseOptions("技"));
        assertEquals(options(Lists.newArrayList("技术")),
                SubjectRequirementParser.parseOptions("技术"));
        assertEquals("技术", SubjectRequirementParser.subjectNameForCode("07"));
    }

    @Test
    void andExpressionIsSingleCombination() {
        assertEquals(options(Lists.newArrayList("物理", "化学")),
                SubjectRequirementParser.parseOptions("物和化"));
        assertEquals(options(Lists.newArrayList("物理", "化学", "生物")),
                SubjectRequirementParser.parseOptions("物和化和生"));
        assertEquals(options(Lists.newArrayList("物理", "生物")),
                SubjectRequirementParser.parseOptions("物和生"));
    }

    @Test
    void orExpressionIsAlternativeCombinations() {
        assertEquals(options(Lists.newArrayList("化学"), Lists.newArrayList("生物")),
                SubjectRequirementParser.parseOptions("化或生"));
        assertEquals(options(Lists.newArrayList("物理"), Lists.newArrayList("化学")),
                SubjectRequirementParser.parseOptions("物理或化学"));
        // "和" = 都要 → 单一组合；"或" = 任一 → 备选组合。别把两者混了。
        assertEquals(options(Lists.newArrayList("化学", "生物")),
                SubjectRequirementParser.parseOptions("化和生"));
    }

    @Test
    void andWithOrInsideBracketsExpandsToOptions() {
        assertEquals(
                options(Lists.newArrayList("物理", "化学"), Lists.newArrayList("物理", "生物")),
                SubjectRequirementParser.parseOptions("物和(化或生)"));
        assertEquals(
                options(Lists.newArrayList("物理", "化学"), Lists.newArrayList("物理", "生物")),
                SubjectRequirementParser.parseOptions("物和（化或生）"));
        assertEquals(
                options(Lists.newArrayList("物理", "化学"), Lists.newArrayList("物理", "生物")),
                SubjectRequirementParser.parseOptions("物(化或生)"), "括号前隐式与");
    }

    @Test
    void unknownTokensOrBrokenBracketsFailOpen() {
        assertTrue(SubjectRequirementParser.parseOptions("语种:英语").isEmpty());
        assertTrue(SubjectRequirementParser.parseOptions("物和X").isEmpty());
        assertTrue(SubjectRequirementParser.parseOptions("物和(化或").isEmpty());
    }

    @Test
    void combinationCodesAreParsedTwoDigitsAtATime() {
        // 010205 = 01 物理 + 02 历史 + 05 化学；段间为"或"、段内为"与"。
        assertEquals(
                options(Lists.newArrayList("物理", "历史", "化学"),
                        Lists.newArrayList("物理", "政治", "化学")),
                SubjectRequirementParser.parseCombinationCodes("010205,010305"));
        assertEquals(options(Lists.newArrayList("物理", "化学", "技术")),
                SubjectRequirementParser.parseCombinationCodes("010507"));
        assertEquals(options(Lists.newArrayList("物理", "化学"), Lists.newArrayList("物理", "生物")),
                SubjectRequirementParser.parseCombinationCodes("0105，0106"), "全角逗号同样分段");
    }

    @Test
    void combinationCodesFailOpenOnIllegalInput() {
        assertTrue(SubjectRequirementParser.parseCombinationCodes("0102050").isEmpty(), "奇数位");
        assertTrue(SubjectRequirementParser.parseCombinationCodes("019905").isEmpty(), "未知码");
        assertTrue(SubjectRequirementParser.parseCombinationCodes("不限").isEmpty());
    }

    @Test
    void combinationCodeSemanticsMatchZhejiangSevenChooseThree() {
        // 数据实际形态：select_group 是"合法性枚举"——不限=全部 35 种三元组、单科=含该科的全部枚举。
        List<List<String>> unlimited = SubjectRequirementParser.parseCombinationCodes(
                "010203,010204,010205,010206,010207,010304,010305,010306,010307,010405,"
                        + "010406,010407,010506,010507,010607,020304,020305,020306,020307,"
                        + "020405,020406,020407,020506,020507,020607,030405,030406,030407,"
                        + "030506,030507,030607,040506,040507,040607,050607");
        assertEquals(35, unlimited.size());
        for (List<String> combination : unlimited) {
            assertEquals(3, combination.size());
        }
        List<List<String>> physicsOnly = SubjectRequirementParser.parseCombinationCodes(
                "010203,010204,010205,010206,010207,010304,010305,010306,010307,010405,"
                        + "010406,010407,010506,010507,010607");
        assertEquals(15, physicsOnly.size());
        for (List<String> combination : physicsOnly) {
            assertTrue(combination.contains("物理"));
        }
    }
}
