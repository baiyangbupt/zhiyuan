package com.ytell.zhiyuan.service.biz;

import com.google.common.collect.Maps;
import com.ytell.zhiyuan.common.util.VolunteerFilePathUtil;
import com.ytell.zhiyuan.model.dto.inner.VolunteerRecommendListResponse;
import com.ytell.zhiyuan.model.dto.inner.VolunteerRecommendListResponse.VolunteerSchool;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Method;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;

/**
 * 测试优选标记(markPreferredSchools)逻辑和摘要文件路径生成
 */
class VolunteerPreferredTest {

    // ---------------------------------------------------------------
    // Helper: 构造带 volunteer_score 的 VolunteerSchool
    // ---------------------------------------------------------------

    private VolunteerSchool createSchool(String name, double volunteerScore) {
        VolunteerSchool school = new VolunteerSchool();
        school.setSchool_name(name);
        Map<String, Object> algTagMap = new HashMap<>();
        algTagMap.put("volunteer_score", volunteerScore);
        school.setAlgTagMap(algTagMap);
        return school;
    }

    // ---------------------------------------------------------------
    // Helper: 通过反射调用 private markPreferredSchools
    // ---------------------------------------------------------------

    private void invokeMarkPreferred(List<VolunteerSchool> schools, int waterline) throws Exception {
        VolunteerResponseBuilder builder = new VolunteerResponseBuilder();
        Method method = VolunteerResponseBuilder.class.getDeclaredMethod(
                "markPreferredSchools", List.class, int.class);
        method.setAccessible(true);
        method.invoke(builder, schools, waterline);
    }

    // ---------------------------------------------------------------
    // 测试 VolunteerSchool 新字段
    // ---------------------------------------------------------------

    @Nested
    @DisplayName("VolunteerSchool 新字段测试")
    class VolunteerSchoolFieldTest {

        @Test
        @DisplayName("rank_in_tier 和 is_preferred 字段存在且可读写")
        void testNewFieldsExist() {
            VolunteerSchool school = new VolunteerSchool();
            assertNull(school.getRank_in_tier());
            assertNull(school.getIs_preferred());

            school.setRank_in_tier(5);
            school.setIs_preferred(true);

            assertEquals(5, school.getRank_in_tier());
            assertTrue(school.getIs_preferred());
        }
    }

    // ---------------------------------------------------------------
    // 测试 markPreferredSchools 核心逻辑
    // ---------------------------------------------------------------

    @Nested
    @DisplayName("markPreferredSchools 逻辑测试")
    class MarkPreferredTest {

        @Test
        @DisplayName("基本排名：按 volunteer_score 降序排名")
        void testBasicRanking() throws Exception {
            VolunteerSchool s1 = createSchool("学校A", 90.0);
            VolunteerSchool s2 = createSchool("学校B", 70.0);
            VolunteerSchool s3 = createSchool("学校C", 80.0);

            // 原始顺序: A(90), B(70), C(80)
            List<VolunteerSchool> schools = new ArrayList<>(Arrays.asList(s1, s2, s3));
            invokeMarkPreferred(schools, 2);

            // 按 score 降序: A=1, C=2, B=3
            assertEquals(1, s1.getRank_in_tier());
            assertEquals(3, s2.getRank_in_tier());
            assertEquals(2, s3.getRank_in_tier());
        }

        @Test
        @DisplayName("waterline 内为优选，外为候补")
        void testPreferredWithinWaterline() throws Exception {
            VolunteerSchool s1 = createSchool("学校A", 90.0);
            VolunteerSchool s2 = createSchool("学校B", 70.0);
            VolunteerSchool s3 = createSchool("学校C", 80.0);

            List<VolunteerSchool> schools = new ArrayList<>(Arrays.asList(s1, s2, s3));
            invokeMarkPreferred(schools, 2);

            // waterline=2, A(rank=1)和C(rank=2)是优选, B(rank=3)不是
            assertTrue(s1.getIs_preferred());
            assertFalse(s2.getIs_preferred());
            assertTrue(s3.getIs_preferred());
        }

        @Test
        @DisplayName("waterline=0 时全部为候补")
        void testWaterlineZero() throws Exception {
            VolunteerSchool s1 = createSchool("学校A", 90.0);
            VolunteerSchool s2 = createSchool("学校B", 70.0);

            List<VolunteerSchool> schools = new ArrayList<>(Arrays.asList(s1, s2));
            invokeMarkPreferred(schools, 0);

            assertFalse(s1.getIs_preferred());
            assertFalse(s2.getIs_preferred());
        }

        @Test
        @DisplayName("waterline >= 列表大小时全部为优选")
        void testWaterlineExceedsSize() throws Exception {
            VolunteerSchool s1 = createSchool("学校A", 90.0);
            VolunteerSchool s2 = createSchool("学校B", 70.0);

            List<VolunteerSchool> schools = new ArrayList<>(Arrays.asList(s1, s2));
            invokeMarkPreferred(schools, 10);

            assertTrue(s1.getIs_preferred());
            assertTrue(s2.getIs_preferred());
            assertEquals(1, s1.getRank_in_tier());
            assertEquals(2, s2.getRank_in_tier());
        }

        @Test
        @DisplayName("空列表不抛异常")
        void testEmptyList() throws Exception {
            List<VolunteerSchool> schools = new ArrayList<>();
            invokeMarkPreferred(schools, 5);
            assertTrue(schools.isEmpty());
        }

        @Test
        @DisplayName("null 列表不抛异常")
        void testNullList() throws Exception {
            invokeMarkPreferred(null, 5);
            // 不抛异常即通过
        }

        @Test
        @DisplayName("不改变原始列表顺序")
        void testOriginalOrderPreserved() throws Exception {
            VolunteerSchool s1 = createSchool("学校A", 30.0);
            VolunteerSchool s2 = createSchool("学校B", 90.0);
            VolunteerSchool s3 = createSchool("学校C", 60.0);

            List<VolunteerSchool> schools = new ArrayList<>(Arrays.asList(s1, s2, s3));
            invokeMarkPreferred(schools, 2);

            // 原始顺序不变
            assertSame(s1, schools.get(0));
            assertSame(s2, schools.get(1));
            assertSame(s3, schools.get(2));
        }

        @Test
        @DisplayName("algTagMap 为空时 volunteer_score 视为 0")
        void testNullAlgTagMap() throws Exception {
            VolunteerSchool s1 = createSchool("学校A", 50.0);
            VolunteerSchool s2 = new VolunteerSchool();
            s2.setSchool_name("学校B");
            s2.setAlgTagMap(null);

            List<VolunteerSchool> schools = new ArrayList<>(Arrays.asList(s1, s2));
            invokeMarkPreferred(schools, 1);

            // A(50) > B(0), so A=rank1(preferred), B=rank2(not)
            assertEquals(1, s1.getRank_in_tier());
            assertTrue(s1.getIs_preferred());
            assertEquals(2, s2.getRank_in_tier());
            assertFalse(s2.getIs_preferred());
        }

        @Test
        @DisplayName("相同 volunteer_score 的学校都能获得排名")
        void testTiedScores() throws Exception {
            VolunteerSchool s1 = createSchool("学校A", 80.0);
            VolunteerSchool s2 = createSchool("学校B", 80.0);
            VolunteerSchool s3 = createSchool("学校C", 80.0);

            List<VolunteerSchool> schools = new ArrayList<>(Arrays.asList(s1, s2, s3));
            invokeMarkPreferred(schools, 2);

            // 全部 score 相同，排名应为 1, 2, 3（稳定排序的顺序取决于实现）
            assertNotNull(s1.getRank_in_tier());
            assertNotNull(s2.getRank_in_tier());
            assertNotNull(s3.getRank_in_tier());
            // 前两名是优选
            long preferredCount = schools.stream()
                    .filter(VolunteerSchool::getIs_preferred).count();
            assertEquals(2, preferredCount);
        }
    }

    // ---------------------------------------------------------------
    // 测试 VolunteerFilePathUtil 新枚举值
    // ---------------------------------------------------------------

    @Nested
    @DisplayName("VolunteerFilePathUtil 摘要类型测试")
    class FilePathUtilTest {

        @Test
        @DisplayName("TEMP_SUMMARY 枚举值存在且后缀正确")
        void testTempSummarySuffix() {
            VolunteerFilePathUtil.VolunteerFileType type = VolunteerFilePathUtil.VolunteerFileType.TEMP_SUMMARY;
            assertEquals("_temp_summary", type.getSuffix());
            assertEquals("临时推荐摘要", type.getDescription());
        }

        @Test
        @DisplayName("FINAL_SUMMARY 枚举值存在且后缀正确")
        void testFinalSummarySuffix() {
            VolunteerFilePathUtil.VolunteerFileType type = VolunteerFilePathUtil.VolunteerFileType.FINAL_SUMMARY;
            assertEquals("_final_summary", type.getSuffix());
            assertEquals("最终提交摘要", type.getDescription());
        }

        @Test
        @DisplayName("所有枚举值后缀不重复")
        void testUniqueSuffixes() {
            VolunteerFilePathUtil.VolunteerFileType[] values = VolunteerFilePathUtil.VolunteerFileType.values();
            long distinctSuffixes = Arrays.stream(values)
                    .map(VolunteerFilePathUtil.VolunteerFileType::getSuffix)
                    .distinct()
                    .count();
            assertEquals(values.length, distinctSuffixes, "枚举值的后缀应该唯一");
        }
    }
}
