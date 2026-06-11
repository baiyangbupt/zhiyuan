package com.ytell.zhiyuan.service.biz;

import com.google.common.collect.Lists;
import com.ytell.zhiyuan.model.dto.planning.CandidatePoolStateDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

public class CandidatePoolQualityStatusBuilderTest {

    @Test
    void shouldApplyEmptyStatusWithFallbackHint() {
        PlanningStateDTO state = new PlanningStateDTO();
        CandidatePoolStateDTO candidatePoolState = new CandidatePoolStateDTO();
        candidatePoolState.setRequiredCount(3);

        CandidatePoolQualityStatusBuilder.apply(state, candidatePoolState);

        assertEquals("empty", candidatePoolState.getStatusCode());
        assertEquals("当前可用于规划的候选池暂无可用志愿，请核验专项资格、批次、分数线、选科或身体限报等条件",
                candidatePoolState.getStatusMessage());
        assertTrue(candidatePoolState.getRiskHints().contains("当前可用候选 0 个，目标需要 3 个"));
    }

    @Test
    void shouldApplyMajorGroupLowCountStatusWithUnitAndConstraintHints() {
        PlanningStateDTO state = new PlanningStateDTO();
        state.getProfileState().getPhysicalConstraints().getColorVision().add("色弱");
        state.getProfileState().getPhysicalConstraints().getSpecialLimits().add("专项资格");

        CandidatePoolStateDTO candidatePoolState = new CandidatePoolStateDTO();
        candidatePoolState.setVolunteerModel("majorGroup");
        candidatePoolState.setRequiredUnitCount(5);
        candidatePoolState.setRequiredCount(30);
        candidatePoolState.getSummary().setUnitTotal(3);
        candidatePoolState.getSummary().setTotal(18);
        candidatePoolState.getRequiredTierCounts().put("保", 2);
        candidatePoolState.getSummary().getUnitTierCounts().put("保", 1);
        candidatePoolState.setUserScore(515);
        candidatePoolState.setBatchScore(500);

        CandidatePoolQualityStatusBuilder.apply(state, candidatePoolState);

        assertEquals("low_count", candidatePoolState.getStatusCode());
        assertEquals("当前可用于规划的候选偏少，方案选择空间有限", candidatePoolState.getStatusMessage());
        assertTrue(candidatePoolState.getRiskHints().contains("当前可用候选 3 个，目标需要 5 个"));
        assertTrue(candidatePoolState.getRiskHints().contains("保区候选不足：当前 1 个，目标 2 个"));
        assertTrue(candidatePoolState.getRiskHints().contains("当前分数距离批次线 15 分，可选空间可能偏窄"));
        assertTrue(candidatePoolState.getRiskHints().contains("身体条件和限报要求可能会限制可用候选，需要结合招生要求核验"));
        assertTrue(candidatePoolState.getRiskHints().contains("专项、民族、外方院校等资格条件可能会限制可用候选，需要核验资格条件"));
        assertTrue(candidatePoolState.getRiskHints().stream().noneMatch(hint -> hint.startsWith("已按")));
    }

    @Test
    void shouldApplyReadyStatusAndClearOldHints() {
        CandidatePoolStateDTO candidatePoolState = new CandidatePoolStateDTO();
        candidatePoolState.setVolunteerModel("major");
        candidatePoolState.setRequiredCount(2);
        candidatePoolState.getSummary().setTotal(3);
        candidatePoolState.setRiskHints(Lists.newArrayList("旧提示"));

        CandidatePoolQualityStatusBuilder.apply(new PlanningStateDTO(), candidatePoolState);

        assertEquals("ready", candidatePoolState.getStatusCode());
        assertEquals("候选池已生成", candidatePoolState.getStatusMessage());
        assertTrue(candidatePoolState.getRiskHints().isEmpty());
    }
}
