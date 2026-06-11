package com.ytell.zhiyuan.service.biz;

import com.google.common.collect.Lists;
import com.ytell.zhiyuan.model.dto.planning.FixProposalActionDTO;
import com.ytell.zhiyuan.model.dto.planning.FixProposalDTO;
import com.ytell.zhiyuan.model.dto.planning.FixProposalDryRunResultDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import com.ytell.zhiyuan.model.dto.planning.RepairReportDTO;
import com.ytell.zhiyuan.model.dto.planning.ReviewCheckDTO;
import com.ytell.zhiyuan.model.dto.planning.ReviewSummaryDTO;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

public class RepairReportBuilderTest {

    @Test
    void shouldBuildAppliedReportWithActionDetailsAndPostValidation() {
        FixProposalDTO proposal = new FixProposalDTO();
        proposal.setProposalId("proposal-1");
        proposal.setStrategy("fill_missing_count");
        proposal.setTitle("修复数量缺口");
        proposal.setSummary("当前志愿数量少于官方要求。");
        proposal.setImpact("预计补充 1 条志愿；当前问题涉及 0 个专业组、1 条志愿。");
        proposal.setSourceVersion(3);
        proposal.setSourceReviewVersion(2);
        proposal.setSourceCheckCodes(Lists.newArrayList("count_validation"));
        proposal.setAffectedVolunteerIds(Lists.newArrayList("v1"));

        FixProposalActionDTO action = new FixProposalActionDTO();
        action.setActionType("fill_total_count");
        action.setVolunteerIds(Lists.newArrayList("v2"));
        proposal.getActions().add(action);

        FixProposalDryRunResultDTO dryRun = proposal.getDryRunResult();
        dryRun.setStatus("ready");
        dryRun.setMessage("已生成可预览的修复方案，应用前仍需要用户确认。");
        dryRun.setAddVolunteerCount(1);
        dryRun.setRemoveVolunteerCount(0);
        dryRun.getWarnings().add("新增项需要额外确认。");

        ReviewSummaryDTO before = new ReviewSummaryDTO();
        before.setRiskCount(1);
        before.setWarnCount(2);

        PlanningStateDTO resultState = new PlanningStateDTO();
        resultState.setVersion(4);
        resultState.getReviewState().setSourceVersion(4);
        resultState.getReviewState().getSummary().setRiskCount(0);
        resultState.getReviewState().getSummary().setWarnCount(1);
        ReviewCheckDTO check = new ReviewCheckDTO();
        check.setCode("count_validation");
        check.setPassed(true);
        resultState.getReviewState().getChecks().add(check);

        RepairReportDTO report = RepairReportBuilder.build(proposal, before, resultState);

        assertEquals("fill_missing_count", report.getStrategy());
        assertEquals("proposal-1", report.getProposalId());
        assertEquals("修复数量缺口", report.getProposalTitle());
        assertEquals("当前志愿数量少于官方要求。", report.getProposalSummary());
        assertEquals("预计补充 1 条志愿；当前问题涉及 0 个专业组、1 条志愿。", report.getProposalImpact());
        assertEquals(Integer.valueOf(3), report.getSourceVersion());
        assertEquals(Integer.valueOf(4), report.getResultVersion());
        assertEquals("ready", report.getDryRunStatus());
        assertEquals("已生成可预览的修复方案，应用前仍需要用户确认。", report.getDryRunMessage());
        assertEquals(Integer.valueOf(1), report.getAddedVolunteerCount());
        assertEquals(Integer.valueOf(1), report.getAffectedVolunteerCount());
        assertEquals(Integer.valueOf(1), report.getBeforeRiskCount());
        assertEquals(Integer.valueOf(0), report.getAfterRiskCount());
        assertTrue(Boolean.TRUE.equals(report.getPostValidationPassed()));
        assertEquals(1, report.getActionDetails().size());
        assertEquals("fill_total_count", report.getActionDetails().get(0).getActionType());
        assertTrue(report.getMessages().stream().anyMatch(message -> message.contains("已补充 1 条志愿")));
        assertTrue(report.getWarnings().stream().anyMatch(message -> message.contains("新增项需要额外确认")));
    }
}
