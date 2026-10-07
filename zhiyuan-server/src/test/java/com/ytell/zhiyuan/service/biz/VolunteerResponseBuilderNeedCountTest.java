package com.ytell.zhiyuan.service.biz;

import com.ytell.zhiyuan.model.dto.CreateSessionReq;
import com.ytell.zhiyuan.model.dto.inner.VolunteerRecommendListResponse;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Method;
import java.util.ArrayList;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;

/**
 * setIntervalCounts 的 need_count 兜底：成绩行缺 volunteerCount（老会话/legacy 草稿未补录）时
 * 不再在"专业+院校/院校专业组"任一分支 NPE 成 code -1，而是 need_count 缺省（null）。
 * setIntervalCounts 是 private 方法，按本仓库既有做法反射直测。
 */
class VolunteerResponseBuilderNeedCountTest {

    @Test
    void shouldNotNpeWhenBuildingIntervalCountsWithoutVolunteerCount() throws Exception {
        VolunteerResponseBuilder builder = new VolunteerResponseBuilder();
        Method method = VolunteerResponseBuilder.class.getDeclaredMethod("setIntervalCounts",
                VolunteerRecommendListResponse.BaseData.class,
                List.class, List.class, List.class, String.class, CreateSessionReq.class);
        method.setAccessible(true);

        List<VolunteerRecommendListResponse.VolunteerSchool> empty = new ArrayList<>();
        CreateSessionReq scoreDetail = new CreateSessionReq();
        scoreDetail.setVolunteerCount(null);

        // 专业+院校（OTOO）分支：修复前 userScoreDetail.getVolunteerCount().getMajorCount() → NPE
        VolunteerRecommendListResponse.BaseData majorMode = new VolunteerRecommendListResponse.BaseData();
        method.invoke(builder, majorMode, empty, empty, empty, "OTOO", scoreDetail);
        assertNull(majorMode.getNeed_count());
        assertEquals(0, majorMode.getTotal_count());

        // 院校专业组（OTON）分支：修复前 getVolunteerCount().getSchoolCount() → NPE
        VolunteerRecommendListResponse.BaseData groupMode = new VolunteerRecommendListResponse.BaseData();
        method.invoke(builder, groupMode, empty, empty, empty, "OTON", scoreDetail);
        assertNull(groupMode.getNeed_count());
        assertEquals(0, groupMode.getTotal_count());
    }

    @Test
    void shouldKeepNeedCountWhenVolunteerCountPresent() throws Exception {
        VolunteerResponseBuilder builder = new VolunteerResponseBuilder();
        Method method = VolunteerResponseBuilder.class.getDeclaredMethod("setIntervalCounts",
                VolunteerRecommendListResponse.BaseData.class,
                List.class, List.class, List.class, String.class, CreateSessionReq.class);
        method.setAccessible(true);

        CreateSessionReq.VolunteerCount volunteerCount = new CreateSessionReq.VolunteerCount();
        volunteerCount.setMajorCount(96);
        volunteerCount.setSchoolCount(45);
        CreateSessionReq scoreDetail = new CreateSessionReq();
        scoreDetail.setVolunteerCount(volunteerCount);
        List<VolunteerRecommendListResponse.VolunteerSchool> empty = new ArrayList<>();

        VolunteerRecommendListResponse.BaseData majorMode = new VolunteerRecommendListResponse.BaseData();
        method.invoke(builder, majorMode, empty, empty, empty, "OTOO", scoreDetail);
        assertEquals(Integer.valueOf(96), majorMode.getNeed_count());

        VolunteerRecommendListResponse.BaseData groupMode = new VolunteerRecommendListResponse.BaseData();
        method.invoke(builder, groupMode, empty, empty, empty, "OTON", scoreDetail);
        assertEquals(Integer.valueOf(45), groupMode.getNeed_count());
    }
}
