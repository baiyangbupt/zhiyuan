package com.ytell.zhiyuan.service.volunteer;

import com.ytell.zhiyuan.manager.rank.VolunteerRankClient;
import com.ytell.zhiyuan.model.dto.CreateSessionReq;
import com.ytell.zhiyuan.model.dto.UserProfileData;
import com.ytell.zhiyuan.model.dto.volunteer.VolunteerSchoolGroup;
import com.ytell.zhiyuan.service.biz.VolunteerRequestExecutorManager;
import com.ytell.zhiyuan.service.biz.VolunteerSorterAndMerger;
import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

class VolunteerUnknownExclusionTest {
    @Test
    void unknownProbabilitiesNeverReachRankingOrAutomaticRecommendations() {
        VolunteerSorterAndMerger sorter = new VolunteerSorterAndMerger();
        VolunteerRankClient rankClient = mock(VolunteerRankClient.class);
        VolunteerRequestExecutorManager executorManager = mock(VolunteerRequestExecutorManager.class);
        ExecutorService executor = Executors.newSingleThreadExecutor();
        ReflectionTestUtils.setField(sorter, "volunteerIntervalService", new VolunteerIntervalService());
        ReflectionTestUtils.setField(sorter, "volunteerRankClient", rankClient);
        ReflectionTestUtils.setField(sorter, "executorManager", executorManager);
        when(executorManager.getExecutor()).thenReturn(executor);
        List<VolunteerSchoolGroup> groups = new ArrayList<>();
        for (Double ratio : Arrays.asList(null, Double.NaN, -1D, 101D)) {
            VolunteerSchoolGroup group = new VolunteerSchoolGroup();
            group.setSchoolEnrollRatio(ratio);
            groups.add(group);
        }
        Map<String, Integer> targets = new LinkedHashMap<>();
        targets.put("冲", 10);
        targets.put("稳", 10);
        targets.put("保", 10);
        try {
            Map<String, List<VolunteerSchoolGroup>> result = sorter.sortAndSplitByInterval(
                    groups, new CreateSessionReq(), new UserProfileData(), "OTON", false, targets);
            assertEquals(0, result.values().stream().mapToInt(List::size).sum());
            verifyNoInteractions(rankClient);
        } finally {
            executor.shutdownNow();
        }
    }
}
