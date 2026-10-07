package com.ytell.zhiyuan.service.biz;

import com.ytell.zhiyuan.manager.rank.VolunteerRankClient;
import com.ytell.zhiyuan.model.dto.CreateSessionReq;
import com.ytell.zhiyuan.model.dto.QueryWeightDto;
import com.ytell.zhiyuan.model.dto.QueryWeightRequest;
import com.ytell.zhiyuan.model.dto.QueryWeightResponse;
import com.ytell.zhiyuan.model.dto.RecommendVolunteerRequest;
import com.ytell.zhiyuan.model.dto.UserProfileData;
import com.ytell.zhiyuan.model.dto.volunteer.VolunteerMajor;
import com.ytell.zhiyuan.model.dto.volunteer.VolunteerSchoolGroup;
import com.ytell.zhiyuan.service.volunteer.VolunteerIntervalService;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.mockito.Mockito;
import org.springframework.test.util.ReflectionTestUtils;

import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertSame;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

public class RankRequestMappingTest {

    private VolunteerAnalysisBizService volunteerAnalysisBizService;
    private VolunteerSorterAndMerger volunteerSorterAndMerger;
    private VolunteerRankClient volunteerRankClient;
    private VolunteerDataProvider volunteerDataProvider;
    private VolunteerUtils volunteerUtils;
    private VolunteerIntervalService volunteerIntervalService;
    private VolunteerRequestExecutorManager executorManager;
    private ExecutorService executorService;

    @BeforeEach
    void setUp() {
        volunteerAnalysisBizService = new VolunteerAnalysisBizService();
        volunteerSorterAndMerger = new VolunteerSorterAndMerger();
        volunteerRankClient = Mockito.mock(VolunteerRankClient.class);
        volunteerDataProvider = Mockito.mock(VolunteerDataProvider.class);
        volunteerUtils = Mockito.mock(VolunteerUtils.class);
        volunteerIntervalService = Mockito.mock(VolunteerIntervalService.class);
        executorManager = Mockito.mock(VolunteerRequestExecutorManager.class);
        executorService = Executors.newSingleThreadExecutor();

        ReflectionTestUtils.setField(volunteerAnalysisBizService, "volunteerRankClient", volunteerRankClient);
        ReflectionTestUtils.setField(volunteerAnalysisBizService, "dataProvider", volunteerDataProvider);
        ReflectionTestUtils.setField(volunteerAnalysisBizService, "utils", volunteerUtils);

        ReflectionTestUtils.setField(volunteerSorterAndMerger, "volunteerRankClient", volunteerRankClient);
        ReflectionTestUtils.setField(volunteerSorterAndMerger, "volunteerIntervalService", volunteerIntervalService);
        ReflectionTestUtils.setField(volunteerSorterAndMerger, "executorManager", executorManager);
    }

    @AfterEach
    void tearDown() {
        if (executorService != null) {
            executorService.shutdownNow();
        }
    }

    @Test
    void shouldPassMergedUserProfileToRankQueryWeight() {
        CreateSessionReq scoreDetail = buildScoreDetail();
        UserProfileData originProfile = new UserProfileData();
        UserProfileData mergedProfile = buildUserProfile();
        QueryWeightResponse response = new QueryWeightResponse();
        response.setType("major");

        when(volunteerDataProvider.getUserScoreDetail(8L)).thenReturn(scoreDetail);
        when(volunteerDataProvider.getUserProfileData(8L)).thenReturn(originProfile);
        when(volunteerUtils.mergeUserProfile(originProfile)).thenReturn(mergedProfile);
        when(volunteerRankClient.queryWeight(any(QueryWeightRequest.class))).thenReturn(response);

        QueryWeightDto queryInfo = new QueryWeightDto();
        queryInfo.setType("major");

        QueryWeightResponse actual = volunteerAnalysisBizService.queryWeight(1L, 8L, queryInfo);

        ArgumentCaptor<QueryWeightRequest> captor = ArgumentCaptor.forClass(QueryWeightRequest.class);
        verify(volunteerRankClient).queryWeight(captor.capture());
        QueryWeightRequest request = captor.getValue();

        assertSame(response, actual);
        assertSame(scoreDetail, request.getStudentinfo());
        assertSame(mergedProfile, request.getProfileinfo());
        assertSame(queryInfo, request.getQueryinfo());
        assertEquals(Collections.singletonList("01"), request.getProfileinfo().getMajor_intent().getLevel1_code());
        assertEquals(Collections.singletonList("0101"), request.getProfileinfo().getMajor_intent().getLevel2_code());
        assertEquals(Collections.singletonList("410000"), request.getProfileinfo().getCity_info().getProvince_code());
        assertEquals(Collections.singletonList("理工院校"), request.getProfileinfo().getTag_info().getValues());
    }

    @Test
    void shouldPassUnifiedProfileFieldsToRankWhenSortingIntervals() {
        VolunteerSchoolGroup group = buildVolunteerSchoolGroup();
        Map<String, List<VolunteerSchoolGroup>> intervalMap = new LinkedHashMap<>();
        intervalMap.put("冲1", Collections.singletonList(group));
        intervalMap.put("冲2", Collections.emptyList());
        intervalMap.put("冲3", Collections.emptyList());
        intervalMap.put("稳1", Collections.emptyList());
        intervalMap.put("稳2", Collections.emptyList());
        intervalMap.put("稳3", Collections.emptyList());
        intervalMap.put("保1", Collections.emptyList());
        intervalMap.put("保2", Collections.emptyList());
        intervalMap.put("保3", Collections.emptyList());

        CreateSessionReq scoreDetail = buildScoreDetail();
        UserProfileData mergedProfile = buildUserProfile();

        when(volunteerIntervalService.divideVolunteers(any(List.class), Mockito.eq(true))).thenReturn(intervalMap);
        when(executorManager.getExecutor()).thenReturn(executorService);
        when(volunteerRankClient.getRecommendVolunteer(any(RecommendVolunteerRequest.class)))
                .thenAnswer(invocation -> invocation.getArgument(0, RecommendVolunteerRequest.class).getVolunteerinfo());

        Map<String, Integer> targetCountMap = new LinkedHashMap<>();
        targetCountMap.put("冲", 1);
        targetCountMap.put("稳", 0);
        targetCountMap.put("保", 0);

        Map<String, List<VolunteerSchoolGroup>> result = volunteerSorterAndMerger.sortAndSplitByInterval(
                Collections.singletonList(group),
                scoreDetail,
                mergedProfile,
                "OTOO",
                false,
                targetCountMap
        );

        ArgumentCaptor<RecommendVolunteerRequest> captor = ArgumentCaptor.forClass(RecommendVolunteerRequest.class);
        verify(volunteerRankClient).getRecommendVolunteer(captor.capture());
        RecommendVolunteerRequest request = captor.getValue();

        assertSame(scoreDetail, request.getStudentinfo());
        assertSame(mergedProfile, request.getProfileinfo());
        assertEquals(Collections.singletonList(group), request.getVolunteerinfo());
        assertEquals(1, result.get("冲").size());
        assertEquals("2001", request.getVolunteerinfo().get(0).getMajorList().get(0).getSubCategoryId());
        assertEquals(Collections.singletonList("01"), request.getProfileinfo().getMajor_intent().getLevel1_code());
        assertEquals(Collections.singletonList("0101"), request.getProfileinfo().getMajor_intent().getLevel2_code());
        assertEquals(Collections.singletonList("410000"), request.getProfileinfo().getCity_info().getProvince_code());
        assertEquals(Collections.singletonList("双一流院校"), request.getProfileinfo().getNegative_tag_info().getValues());
    }

    @Test
    void shouldSkipMajorTruncationWhenVolunteerCountMissing() {
        // 成绩行缺 volunteerCount（老会话/legacy 草稿未补录）时，专业截断的"目标专业数"拿不到；
        // 修复前这里直接 getVolunteerCount().getMajorCount() → NPE 成 code -1，
        // 修复后退化为"跳过专业截断（全量保留）"。
        VolunteerMajor major1 = new VolunteerMajor();
        major1.setMajorId("1001");
        major1.setSubCategoryId("2001");
        VolunteerMajor major2 = new VolunteerMajor();
        major2.setMajorId("1002");
        major2.setSubCategoryId("2002");
        VolunteerSchoolGroup group = buildVolunteerSchoolGroup();
        group.setMajorList(java.util.Arrays.asList(major1, major2));

        Map<String, List<VolunteerSchoolGroup>> intervalMap = new LinkedHashMap<>();
        intervalMap.put("冲1", Collections.singletonList(group));
        intervalMap.put("冲2", Collections.emptyList());
        intervalMap.put("冲3", Collections.emptyList());
        intervalMap.put("稳1", Collections.emptyList());
        intervalMap.put("稳2", Collections.emptyList());
        intervalMap.put("稳3", Collections.emptyList());
        intervalMap.put("保1", Collections.emptyList());
        intervalMap.put("保2", Collections.emptyList());
        intervalMap.put("保3", Collections.emptyList());

        CreateSessionReq scoreDetail = buildScoreDetail();
        scoreDetail.setVolunteerCount(null);
        UserProfileData mergedProfile = buildUserProfile();

        when(volunteerIntervalService.divideVolunteers(any(List.class), Mockito.eq(true))).thenReturn(intervalMap);
        when(executorManager.getExecutor()).thenReturn(executorService);
        when(volunteerRankClient.getRecommendVolunteer(any(RecommendVolunteerRequest.class)))
                .thenAnswer(invocation -> invocation.getArgument(0, RecommendVolunteerRequest.class).getVolunteerinfo());

        Map<String, Integer> targetCountMap = new LinkedHashMap<>();
        targetCountMap.put("冲", 1);
        targetCountMap.put("稳", 0);
        targetCountMap.put("保", 0);

        Map<String, List<VolunteerSchoolGroup>> result = volunteerSorterAndMerger.sortAndSplitByInterval(
                Collections.singletonList(group),
                scoreDetail,
                mergedProfile,
                "OTON",
                false,
                targetCountMap
        );

        assertEquals(1, result.get("冲").size());
        assertEquals(2, result.get("冲").get(0).getMajorList().size());
    }

    private CreateSessionReq buildScoreDetail() {
        CreateSessionReq scoreDetail = new CreateSessionReq();
        scoreDetail.setFilterType("1");

        CreateSessionReq.Province province = new CreateSessionReq.Province();
        province.setCode("410000");
        province.setName("河南");
        scoreDetail.setProvince(province);

        CreateSessionReq.VolunteerCount volunteerCount = new CreateSessionReq.VolunteerCount();
        volunteerCount.setSchoolCount(1);
        volunteerCount.setMajorCount(1);
        scoreDetail.setVolunteerCount(volunteerCount);
        return scoreDetail;
    }

    private UserProfileData buildUserProfile() {
        UserProfileData profile = new UserProfileData();
        profile.getMajor_intent().setLevel1(Collections.singletonList("工学"));
        profile.getMajor_intent().setLevel1_code(Collections.singletonList("01"));
        profile.getMajor_intent().setLevel2(Collections.singletonList("计算机类"));
        profile.getMajor_intent().setLevel2_code(Collections.singletonList("0101"));
        profile.getMajor_intent().setLevel3(Collections.singletonList("软件工程"));
        profile.getMajor_intent().setLevel3_code(Collections.singletonList("080902"));
        profile.getCity_info().setProvince(Collections.singletonList("河南"));
        profile.getCity_info().setProvince_code(Collections.singletonList("410000"));
        profile.getCity_info().setCity(Collections.singletonList("郑州"));
        profile.getCity_info().setCity_code(Collections.singletonList("410100"));
        profile.getTag_info().setValues(Collections.singletonList("理工院校"));
        profile.getNegative_tag_info().setValues(Collections.singletonList("双一流院校"));
        return profile;
    }

    private VolunteerSchoolGroup buildVolunteerSchoolGroup() {
        VolunteerMajor major = new VolunteerMajor();
        major.setMajorId("1001");
        major.setCategoryId("01");
        major.setSubCategoryId("2001");

        VolunteerSchoolGroup group = new VolunteerSchoolGroup();
        group.setPlanSchoolDataId("ps1");
        group.setSchoolId("s1");
        group.setProvinceId("410000");
        group.setCityId("410100");
        group.setMajorList(Collections.singletonList(major));
        return group;
    }
}
