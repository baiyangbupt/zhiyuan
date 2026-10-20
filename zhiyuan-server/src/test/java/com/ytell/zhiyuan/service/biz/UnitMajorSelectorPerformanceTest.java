package com.ytell.zhiyuan.service.biz;

import com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO;
import org.junit.jupiter.api.Test;

import java.util.ArrayList;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;

/**
 * 600 个专业组（每组 13 个专业）的组内选择预算探针。
 * 计划入口按 unit 逐个求解，因此这里直接压 UnitMajorSelector。
 */
class UnitMajorSelectorPerformanceTest {

    private static final int UNITS = 600;
    private static final int MAJORS = 13;
    private static final int REQUIRED = 6;

    @Test
    void sixHundredGroupsStayWithinSelectionBudget() {
        List<List<CandidateItemDTO>> groups = new ArrayList<List<CandidateItemDTO>>();
        for (int unit = 0; unit < UNITS; unit++) {
            List<CandidateItemDTO> group = new ArrayList<CandidateItemDTO>();
            for (int major = 0; major < MAJORS; major++) {
                CandidateItemDTO candidate = new CandidateItemDTO();
                candidate.setVolunteerId("u" + unit + "-v" + major);
                candidate.setIntentScore((major * 7 + unit) % 100D);
                candidate.setFinalScore((major * 11 + unit) % 100D);
                candidate.setFutureDevelopmentScore((major * 13 + unit) % 100D);
                candidate.setAdmissionRatio(40D + (major * 3) % 50);
                candidate.setSchoolEnrollRatio(55D);
                candidate.setTuitionPerYear(5000 + major * 500);
                candidate.setPreferred(major % 5 == 0);
                group.add(candidate);
            }
            groups.add(group);
        }

        // 预热，排除类加载和 Ojalgo 初始化。
        for (int index = 0; index < 20; index++) {
            UnitMajorSelector.select(groups.get(index), REQUIRED, 55D);
        }

        long started = System.nanoTime();
        int selected = 0;
        for (List<CandidateItemDTO> group : groups) {
            selected += UnitMajorSelector.select(group, REQUIRED, 55D).size();
        }
        long elapsedMs = (System.nanoTime() - started) / 1_000_000L;

        System.out.println("unit major selector: units=" + UNITS
                + " majors=" + MAJORS + " selected=" + selected + " elapsedMs=" + elapsedMs);
        assertEquals(UNITS * REQUIRED, selected);
        org.junit.jupiter.api.Assertions.assertTrue(elapsedMs < 3000L,
                "600 组组内选择耗时 " + elapsedMs + "ms，超出 3s 预算");
    }
}
