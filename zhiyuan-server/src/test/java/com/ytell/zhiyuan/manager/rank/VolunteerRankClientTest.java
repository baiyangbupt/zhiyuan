package com.ytell.zhiyuan.manager.rank;

import com.ytell.zhiyuan.model.dto.volunteer.VolunteerSchoolGroup;
import com.ytell.zhiyuan.service.biz.RankReasonMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;

/**
 * P1d 步骤 3：结构化理由在 **rank 边界**（客户端）填好。
 *
 * 放在客户端的理由是"映射只做一次"：所有调用方拿到的组对象都已经带好理由，
 * 不必各自记得去补——漏补一个调用方，那条路上的推荐就会**少一套理由且不报错**。
 */
class VolunteerRankClientTest {

    private VolunteerRankClient client;

    @BeforeEach
    void setUp() {
        client = new VolunteerRankClient();
        ReflectionTestUtils.setField(client, "rankReasonMapper", new RankReasonMapper());
    }

    private static Map<String, Object> factor(String tag, double delta) {
        Map<String, Object> item = new LinkedHashMap<String, Object>();
        item.put("tag", tag);
        item.put("delta", delta);
        return item;
    }

    @Test
    void shouldFillStructuredReasonsAndLeaveTheLegacyRemarkUntouched() {
        VolunteerSchoolGroup group = new VolunteerSchoolGroup();
        group.setCollege_factors(Arrays.asList(
                factor("院校正向加分", 24.0), factor("院校层次正向加分", 8.0)));
        group.setCollege_remark("院校正向加分;院校层次正向加分");

        client.fillReasons(Collections.singletonList(group));

        assertEquals(2, group.getCollegeReasons().size());
        assertEquals("school.positive", group.getCollegeReasons().get(0).getCode());
        assertEquals(24.0, group.getCollegeReasons().get(0).getDelta());
        assertEquals("school.level.positive", group.getCollegeReasons().get(1).getCode());
        // 旧通道是**并存**的：新结构上线不许改到它（前端/导出在用）。
        assertEquals("院校正向加分;院校层次正向加分", group.getCollege_remark());
    }

    @Test
    void shouldLeaveReasonsAbsentWhenRankSendsNoFactors() {
        // rank 没给因子（旧版本、或这一条没有调整）→ 字段保持 null，
        // **不设空列表**：空列表会被下游读成"这一条没有理由"，而真相是"没这个通道"。
        VolunteerSchoolGroup group = new VolunteerSchoolGroup();
        group.setCollege_remark("未知院校减分");

        client.fillReasons(Collections.singletonList(group));

        assertNull(group.getCollegeReasons());
        assertNull(group.getMajorReasons());
    }

    @Test
    void shouldFillBothScopesAndTolerateNullEntries() {
        VolunteerSchoolGroup group = new VolunteerSchoolGroup();
        group.setCollege_factors(Collections.singletonList(factor("城市正向加分", 5.0)));
        group.setMajor_factors(Collections.singletonList(factor("专业正向加分", 2.0)));
        List<VolunteerSchoolGroup> groups = new ArrayList<VolunteerSchoolGroup>();
        groups.add(null);
        groups.add(group);

        client.fillReasons(groups);

        assertEquals("city.positive", group.getCollegeReasons().get(0).getCode());
        assertEquals("major.positive", group.getMajorReasons().get(0).getCode());
    }
}
