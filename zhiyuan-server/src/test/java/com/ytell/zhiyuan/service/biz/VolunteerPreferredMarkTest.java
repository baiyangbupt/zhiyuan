package com.ytell.zhiyuan.service.biz;

import com.google.common.collect.Maps;
import com.ytell.zhiyuan.model.dto.inner.VolunteerRecommendListResponse;
import com.ytell.zhiyuan.model.dto.inner.VolunteerRecommendListResponse.VolunteerSchool;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Method;
import java.util.*;

import static org.junit.jupiter.api.Assertions.*;

/**
 * 验证优选标记逻辑：markPreferredSchools 和 getVolunteerScore
 * 由于这两个方法是 VolunteerResponseBuilder 的 private 方法，
 * 这里通过反射进行单元测试。
 */
class VolunteerPreferredMarkTest {

    // ---------------------------------------------------------------------------
    // Helper: create a VolunteerSchool with given volunteer_score in algTagMap
    // ---------------------------------------------------------------------------

    private VolunteerSchool createSchool(String name, double volunteerScore) {
        VolunteerSchool school = new VolunteerSchool();
        school.setSchool_name(name);
        Map<String, Object> algMap = new HashMap<>();
        algMap.put("volunteer_score", volunteerScore);
        school.setAlgTagMap(algMap);
        return school;
    }

    // ---------------------------------------------------------------------------
    // Invoke private methods via reflection
    // ---------------------------------------------------------------------------

    private void invokeMarkPreferredSchools(Object builder, List<VolunteerSchool> schools, int waterline) throws Exception {
        Method method = VolunteerResponseBuilder.class.getDeclaredMethod(
                "markPreferredSchools", List.class, int.class);
        method.setAccessible(true);
        method.invoke(builder, schools, waterline);
    }

    private double invokeGetVolunteerScore(Object builder, VolunteerSchool school) throws Exception {
        Method method = VolunteerResponseBuilder.class.getDeclaredMethod(
                "getVolunteerScore", VolunteerSchool.class);
        method.setAccessible(true);
        return (double) method.invoke(builder, school);
    }

    private VolunteerResponseBuilder createBuilder() {
        // VolunteerResponseBuilder has @Autowired fields but markPreferredSchools
        // and getVolunteerScore don't use them — safe to instantiate directly.
        return new VolunteerResponseBuilder();
    }

    // ---------------------------------------------------------------------------
    // Tests: getVolunteerScore
    // ---------------------------------------------------------------------------

    @Test
    @DisplayName("getVolunteerScore - 正常提取 volunteer_score")
    void testGetVolunteerScore_normal() throws Exception {
        VolunteerResponseBuilder builder = createBuilder();
        VolunteerSchool school = createSchool("北京大学", 92.5);
        assertEquals(92.5, invokeGetVolunteerScore(builder, school), 0.001);
    }

    @Test
    @DisplayName("getVolunteerScore - algTagMap 为 null 返回 0")
    void testGetVolunteerScore_nullMap() throws Exception {
        VolunteerResponseBuilder builder = createBuilder();
        VolunteerSchool school = new VolunteerSchool();
        school.setAlgTagMap(null);
        assertEquals(0.0, invokeGetVolunteerScore(builder, school), 0.001);
    }

    @Test
    @DisplayName("getVolunteerScore - volunteer_score 不存在返回 0")
    void testGetVolunteerScore_missingKey() throws Exception {
        VolunteerResponseBuilder builder = createBuilder();
        VolunteerSchool school = new VolunteerSchool();
        school.setAlgTagMap(new HashMap<>());
        assertEquals(0.0, invokeGetVolunteerScore(builder, school), 0.001);
    }

    // ---------------------------------------------------------------------------
    // Tests: markPreferredSchools - basic ranking
    // ---------------------------------------------------------------------------

    @Test
    @DisplayName("markPreferredSchools - 按 volunteer_score 降序排名")
    void testMarkPreferred_ranking() throws Exception {
        VolunteerResponseBuilder builder = createBuilder();

        VolunteerSchool s1 = createSchool("A大学", 80.0);
        VolunteerSchool s2 = createSchool("B大学", 95.0);
        VolunteerSchool s3 = createSchool("C大学", 60.0);
        VolunteerSchool s4 = createSchool("D大学", 90.0);

        List<VolunteerSchool> schools = new ArrayList<>(Arrays.asList(s1, s2, s3, s4));
        invokeMarkPreferredSchools(builder, schools, 2);

        // B(95) -> rank 1, D(90) -> rank 2, A(80) -> rank 3, C(60) -> rank 4
        assertEquals(3, s1.getRank_in_tier());  // A: 80 -> rank 3
        assertEquals(1, s2.getRank_in_tier());  // B: 95 -> rank 1
        assertEquals(4, s3.getRank_in_tier());  // C: 60 -> rank 4
        assertEquals(2, s4.getRank_in_tier());  // D: 90 -> rank 2
    }

    @Test
    @DisplayName("markPreferredSchools - waterline=2 时前2名优选")
    void testMarkPreferred_waterline() throws Exception {
        VolunteerResponseBuilder builder = createBuilder();

        VolunteerSchool s1 = createSchool("A大学", 80.0);
        VolunteerSchool s2 = createSchool("B大学", 95.0);
        VolunteerSchool s3 = createSchool("C大学", 60.0);
        VolunteerSchool s4 = createSchool("D大学", 90.0);

        List<VolunteerSchool> schools = new ArrayList<>(Arrays.asList(s1, s2, s3, s4));
        invokeMarkPreferredSchools(builder, schools, 2);

        // B(rank 1) and D(rank 2) should be preferred
        assertFalse(s1.getIs_preferred());   // A: rank 3, not preferred
        assertTrue(s2.getIs_preferred());    // B: rank 1, preferred
        assertFalse(s3.getIs_preferred());   // C: rank 4, not preferred
        assertTrue(s4.getIs_preferred());    // D: rank 2, preferred
    }

    // ---------------------------------------------------------------------------
    // Tests: markPreferredSchools - edge cases
    // ---------------------------------------------------------------------------

    @Test
    @DisplayName("markPreferredSchools - 空列表不报错")
    void testMarkPreferred_emptyList() throws Exception {
        VolunteerResponseBuilder builder = createBuilder();
        List<VolunteerSchool> schools = new ArrayList<>();
        // Should not throw
        invokeMarkPreferredSchools(builder, schools, 5);
    }

    @Test
    @DisplayName("markPreferredSchools - null 列表不报错")
    void testMarkPreferred_nullList() throws Exception {
        VolunteerResponseBuilder builder = createBuilder();
        // Should not throw
        invokeMarkPreferredSchools(builder, null, 5);
    }

    @Test
    @DisplayName("markPreferredSchools - waterline=0 时全部非优选")
    void testMarkPreferred_zeroWaterline() throws Exception {
        VolunteerResponseBuilder builder = createBuilder();

        VolunteerSchool s1 = createSchool("A大学", 95.0);
        VolunteerSchool s2 = createSchool("B大学", 80.0);

        List<VolunteerSchool> schools = new ArrayList<>(Arrays.asList(s1, s2));
        invokeMarkPreferredSchools(builder, schools, 0);

        assertFalse(s1.getIs_preferred());
        assertFalse(s2.getIs_preferred());
        assertEquals(1, s1.getRank_in_tier());
        assertEquals(2, s2.getRank_in_tier());
    }

    @Test
    @DisplayName("markPreferredSchools - waterline >= 列表长度时全部优选")
    void testMarkPreferred_waterlineExceedsSize() throws Exception {
        VolunteerResponseBuilder builder = createBuilder();

        VolunteerSchool s1 = createSchool("A大学", 95.0);
        VolunteerSchool s2 = createSchool("B大学", 80.0);

        List<VolunteerSchool> schools = new ArrayList<>(Arrays.asList(s1, s2));
        invokeMarkPreferredSchools(builder, schools, 10);

        assertTrue(s1.getIs_preferred());
        assertTrue(s2.getIs_preferred());
    }

    @Test
    @DisplayName("markPreferredSchools - 不改变原列表顺序")
    void testMarkPreferred_preservesOriginalOrder() throws Exception {
        VolunteerResponseBuilder builder = createBuilder();

        VolunteerSchool s1 = createSchool("第一个", 30.0);
        VolunteerSchool s2 = createSchool("第二个", 90.0);
        VolunteerSchool s3 = createSchool("第三个", 60.0);

        List<VolunteerSchool> schools = new ArrayList<>(Arrays.asList(s1, s2, s3));
        invokeMarkPreferredSchools(builder, schools, 2);

        // Original order should be preserved
        assertEquals("第一个", schools.get(0).getSchool_name());
        assertEquals("第二个", schools.get(1).getSchool_name());
        assertEquals("第三个", schools.get(2).getSchool_name());
    }

    @Test
    @DisplayName("markPreferredSchools - 相同 score 也能正确排名")
    void testMarkPreferred_sameScore() throws Exception {
        VolunteerResponseBuilder builder = createBuilder();

        VolunteerSchool s1 = createSchool("A大学", 80.0);
        VolunteerSchool s2 = createSchool("B大学", 80.0);
        VolunteerSchool s3 = createSchool("C大学", 80.0);

        List<VolunteerSchool> schools = new ArrayList<>(Arrays.asList(s1, s2, s3));
        invokeMarkPreferredSchools(builder, schools, 2);

        // All have the same score, ranks should be 1, 2, 3 (in sort order)
        Set<Integer> ranks = new HashSet<>();
        ranks.add(s1.getRank_in_tier());
        ranks.add(s2.getRank_in_tier());
        ranks.add(s3.getRank_in_tier());
        assertEquals(new HashSet<>(Arrays.asList(1, 2, 3)), ranks);

        // Exactly 2 should be preferred
        long preferredCount = schools.stream().filter(VolunteerSchool::getIs_preferred).count();
        assertEquals(2, preferredCount);
    }

    // ---------------------------------------------------------------------------
    // Tests: VolunteerSchool new fields
    // ---------------------------------------------------------------------------

    @Test
    @DisplayName("VolunteerSchool - rank_in_tier 和 is_preferred 字段可读写")
    void testVolunteerSchool_newFields() {
        VolunteerSchool school = new VolunteerSchool();

        // Default values should be null
        assertNull(school.getRank_in_tier());
        assertNull(school.getIs_preferred());

        // Set and read
        school.setRank_in_tier(5);
        school.setIs_preferred(true);
        assertEquals(5, school.getRank_in_tier());
        assertTrue(school.getIs_preferred());
    }

    // ---------------------------------------------------------------------------
    // Tests: VolunteerFilePathUtil enum values
    // ---------------------------------------------------------------------------

    @Test
    @DisplayName("VolunteerFileType - 新增 TEMP_SUMMARY 和 FINAL_SUMMARY 枚举值")
    void testFileTypeEnums() {
        com.ytell.zhiyuan.common.util.VolunteerFilePathUtil.VolunteerFileType tempSummary =
                com.ytell.zhiyuan.common.util.VolunteerFilePathUtil.VolunteerFileType.TEMP_SUMMARY;
        com.ytell.zhiyuan.common.util.VolunteerFilePathUtil.VolunteerFileType finalSummary =
                com.ytell.zhiyuan.common.util.VolunteerFilePathUtil.VolunteerFileType.FINAL_SUMMARY;

        assertEquals("_temp_summary", tempSummary.getSuffix());
        assertEquals("_final_summary", finalSummary.getSuffix());
        assertEquals("临时推荐摘要", tempSummary.getDescription());
        assertEquals("最终提交摘要", finalSummary.getDescription());
    }
}
