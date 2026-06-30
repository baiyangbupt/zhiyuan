package com.ytell.zhiyuan.service.biz;

import com.google.common.collect.Lists;
import com.ytell.zhiyuan.model.dto.planning.FixProposalActionDTO;
import com.ytell.zhiyuan.model.dto.planning.FixProposalDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import com.ytell.zhiyuan.model.dto.planning.RepairReportDTO;
import com.ytell.zhiyuan.model.dto.planning.ReplacementPairDTO;
import com.ytell.zhiyuan.model.dto.planning.ReviewCheckDTO;
import com.ytell.zhiyuan.model.dto.planning.ReviewSummaryDTO;

import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;

final class RepairReportBuilder {

    private RepairReportBuilder() {
    }

    static RepairReportDTO build(FixProposalDTO proposal,
                                 ReviewSummaryDTO beforeReviewSummary,
                                 PlanningStateDTO resultState) {
        RepairReportDTO report = new RepairReportDTO();
        if (proposal == null) {
            report.setStatus("unknown");
            report.getWarnings().add("缺少修复建议信息，无法生成完整修复报告。");
            return report;
        }
        report.setStrategy(proposal.getStrategy());
        report.setProposalId(proposal.getProposalId());
        report.setProposalTitle(proposal.getTitle());
        report.setProposalSummary(proposal.getSummary());
        report.setProposalImpact(proposal.getImpact());
        report.setSourceVersion(proposal.getSourceVersion());
        report.setResultVersion(resultState == null ? null : resultState.getVersion());
        report.setSourceReviewVersion(proposal.getSourceReviewVersion());
        report.setResultReviewVersion(resultState == null || resultState.getReviewState() == null
                ? null : resultState.getReviewState().getSourceVersion());
        report.setSourceCheckCodes(defaultList(proposal.getSourceCheckCodes()));
        report.setAppliedActionCount(proposal.getActions() == null ? 0 : proposal.getActions().size());
        report.setAffectedUnitCount(defaultList(proposal.getAffectedUnitIds()).size());
        report.setAffectedVolunteerCount(defaultList(proposal.getAffectedVolunteerIds()).size());
        report.getActionDetails().addAll(convertActionDetails(proposal));
        if (proposal.getDryRunResult() != null) {
            report.setDryRunStatus(proposal.getDryRunResult().getStatus());
            report.setDryRunMessage(proposal.getDryRunResult().getMessage());
            report.setAddedUnitCount(proposal.getDryRunResult().getAddUnitCount());
            report.setAddedVolunteerCount(proposal.getDryRunResult().getAddVolunteerCount());
            report.setRemovedUnitCount(proposal.getDryRunResult().getRemoveUnitCount());
            report.setRemovedVolunteerCount(proposal.getDryRunResult().getRemoveVolunteerCount());
            report.getWarnings().addAll(defaultList(proposal.getDryRunResult().getWarnings()));
        }
        populateReviewSummary(report, beforeReviewSummary, resultState);
        report.setPostValidationPassed(resolvePostValidationPassed(proposal, resultState));
        report.getMessages().add(buildMessage(proposal, report));
        if (!Boolean.TRUE.equals(report.getPostValidationPassed())) {
            report.getWarnings().add("修复后仍存在相关风险或审查结果未刷新，需要继续检查。");
        }
        return report;
    }

    private static List<RepairReportDTO.ActionDetail> convertActionDetails(FixProposalDTO proposal) {
        List<RepairReportDTO.ActionDetail> details = Lists.newArrayList();
        if (proposal == null || proposal.getActions() == null) {
            return details;
        }
        for (FixProposalActionDTO action : proposal.getActions()) {
            if (action == null) {
                continue;
            }
            RepairReportDTO.ActionDetail detail = new RepairReportDTO.ActionDetail();
            detail.setActionType(action.getActionType());
            detail.setSourceCheckCode(action.getSourceCheckCode());
            detail.setSummary(action.getSummary());
            detail.setDetail(action.getDetail());
            detail.setUnitIds(defaultList(action.getUnitIds()));
            detail.setVolunteerIds(defaultList(action.getVolunteerIds()));
            detail.setRemoveUnitIds(defaultList(action.getRemoveUnitIds()));
            detail.setRemoveVolunteerIds(defaultList(action.getRemoveVolunteerIds()));
            detail.setCandidateUnitIds(defaultList(action.getCandidateUnitIds()));
            detail.setCandidateVolunteerIds(defaultList(action.getCandidateVolunteerIds()));
            detail.setReplacementPairs(action.getReplacementPairs() == null
                    ? Lists.<ReplacementPairDTO>newArrayList()
                    : Lists.newArrayList(action.getReplacementPairs()));
            detail.setTotalUnitCount(action.getTotalUnitCount());
            detail.setTotalVolunteerCount(action.getTotalVolunteerCount());
            detail.setTotalReplacementPairCount(action.getTotalReplacementPairCount());
            details.add(detail);
        }
        return details;
    }

    private static void populateReviewSummary(RepairReportDTO report,
                                              ReviewSummaryDTO beforeSummary,
                                              PlanningStateDTO resultState) {
        ReviewSummaryDTO afterSummary = resultState == null || resultState.getReviewState() == null
                ? null : resultState.getReviewState().getSummary();
        report.setBeforeRiskCount(beforeSummary == null ? 0 : defaultInt(beforeSummary.getRiskCount()));
        report.setBeforeWarnCount(beforeSummary == null ? 0 : defaultInt(beforeSummary.getWarnCount()));
        report.setAfterRiskCount(afterSummary == null ? 0 : defaultInt(afterSummary.getRiskCount()));
        report.setAfterWarnCount(afterSummary == null ? 0 : defaultInt(afterSummary.getWarnCount()));
    }

    private static Boolean resolvePostValidationPassed(FixProposalDTO proposal, PlanningStateDTO resultState) {
        if (resultState == null || resultState.getReviewState() == null || resultState.getReviewState().getChecks() == null) {
            return false;
        }
        Set<String> sourceCodes = new LinkedHashSet<String>(defaultList(proposal.getSourceCheckCodes()));
        if (sourceCodes.isEmpty()) {
            return null;
        }
        for (ReviewCheckDTO check : resultState.getReviewState().getChecks()) {
            if (check != null && sourceCodes.contains(check.getCode()) && Boolean.FALSE.equals(check.getPassed())) {
                return false;
            }
        }
        return true;
    }

    private static String buildMessage(FixProposalDTO proposal, RepairReportDTO report) {
        String strategy = RepairProposalTaxonomy.normalizeStrategy(proposal.getStrategy());
        if (RepairProposalTaxonomy.Strategy.SORT_BY_PROBABILITY.equals(strategy)) {
            return "已按录取率重新整理当前方案顺序，并完成复验。";
        }
        if (RepairProposalTaxonomy.Strategy.FILL_MISSING_COUNT.equals(strategy)) {
            return String.format("已补充 %d 条志愿，并刷新当前方案状态。", defaultInt(report.getAddedVolunteerCount()));
        }
        if (RepairProposalTaxonomy.Strategy.ADJUST_MAJOR_GROUP_INNER_SAFETY.equals(strategy)) {
            return String.format("已调整 %d 个组内专业，并刷新当前方案状态。",
                    defaultInt(report.getAddedVolunteerCount()) + defaultInt(report.getRemovedVolunteerCount()));
        }
        return "已应用修复建议，并刷新当前方案状态。";
    }

    private static int defaultInt(Integer value) {
        return value == null ? 0 : value;
    }

    private static <T> List<T> defaultList(List<T> values) {
        return values == null ? Lists.newArrayList() : values;
    }
}
