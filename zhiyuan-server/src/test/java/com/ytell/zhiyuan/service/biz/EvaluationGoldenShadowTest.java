package com.ytell.zhiyuan.service.biz;

import com.alibaba.fastjson.JSON;
import com.google.common.base.Strings;
import com.google.common.collect.Lists;
import com.google.common.collect.Maps;
import com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO;
import com.ytell.zhiyuan.model.dto.planning.CandidatePoolStateDTO;
import com.ytell.zhiyuan.model.dto.planning.EvaluationContextDTO;
import com.ytell.zhiyuan.model.dto.planning.EvaluationEntryRefDTO;
import com.ytell.zhiyuan.model.dto.planning.EvaluationFindingDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedItemDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedUnitDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanEvaluationDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningUnitMajorDTO;
import com.ytell.zhiyuan.model.dto.planning.ReviewCheckDTO;
import com.ytell.zhiyuan.model.dto.planning.ReviewStateDTO;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;

import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * J5.0 golden shadow：拿真实会话的 planningState 快照，对比旧 review checks 与
 * 新 PlanEvaluation。默认跳过；设置
 * {@code EVALUATION_GOLDEN_FILES=state.json[|pool.json],...} 运行。
 *
 * <p>本测试只读文件、不连库、不改状态。差异报告写到
 * {@code EVALUATION_GOLDEN_REPORT}（可选）。</p>
 */
@EnabledIfEnvironmentVariable(named = "EVALUATION_GOLDEN_FILES", matches = ".+")
class EvaluationGoldenShadowTest {

    private final ReviewEvaluationMapper mapper = new ReviewEvaluationMapper();

    @Test
    void shadowEvaluationExplainsEveryDifference() throws Exception {
        String raw = System.getenv("EVALUATION_GOLDEN_FILES");
        StringBuilder report = new StringBuilder();
        for (String item : raw.split(",")) {
            String[] parts = item.split("\\|", -1);
            File stateFile = new File(parts[0].trim());
            File poolFile = parts.length > 1 && !parts[1].trim().isEmpty()
                    ? new File(parts[1].trim()) : null;
            PlanningStateDTO state = JSON.parseObject(
                    new String(Files.readAllBytes(stateFile.toPath()), StandardCharsets.UTF_8),
                    PlanningStateDTO.class);
            if (poolFile != null) {
                CandidatePoolStateDTO pool = JSON.parseObject(
                        new String(Files.readAllBytes(poolFile.toPath()), StandardCharsets.UTF_8),
                        CandidatePoolStateDTO.class);
                state.getCandidatePoolState().setItems(pool.getItems());
            }
            assertGolden(state, stateFile.getName(), report);
        }
        String reportPath = System.getenv("EVALUATION_GOLDEN_REPORT");
        if (!Strings.isNullOrEmpty(reportPath)) {
            Files.write(new File(reportPath).toPath(),
                    report.toString().getBytes(StandardCharsets.UTF_8));
        }
        System.out.println(report);
    }

    private void assertGolden(PlanningStateDTO state, String name, StringBuilder report) {
        ReviewStateDTO review = state.getReviewState();
        if (review == null || review.getChecks() == null || review.getChecks().isEmpty()) {
            // 没有审查结果的会话不能做 golden diff；报告里明确标出，不伪装“对比通过”。
            report.append("== ").append(name).append(" ==\n")
                    .append("SKIP: no review checks (reviewSource=")
                    .append(review == null ? null : review.getSourceVersion())
                    .append(", version=").append(state.getVersion()).append(")\n\n");
            return;
        }

        EvaluationContextDTO context = buildContext(state);
        PlanEvaluationDTO evaluation = mapper.map(review, context);

        int expectedFindings = review.getChecks().size() + 1; // count_validation 拆两条
        assertEquals(expectedFindings, evaluation.getFindings().size(),
                name + ": finding count");
        assertEquals("completed", evaluation.getStatus(), name + ": status");
        assertNotNull(evaluation.getEvaluationVersion(), name + ": evaluationVersion");

        report.append("== ").append(name).append(" ==\n")
                .append("version=").append(state.getVersion())
                .append(" reviewSource=").append(review.getSourceVersion())
                .append(" checks=").append(review.getChecks().size())
                .append(" findings=").append(evaluation.getFindings().size())
                .append(" hardFeasible=").append(evaluation.getHardFeasible())
                .append('\n');

        for (ReviewCheckDTO check : review.getChecks()) {
            if ("count_validation".equals(check.getCode())) {
                EvaluationFindingDTO hard = find(evaluation, "count_validation_hard");
                EvaluationFindingDTO target = find(evaluation, "count_target");
                report.append("count_validation -> ")
                        .append(hard.getResultStatus()).append('/').append(hard.getDisplaySeverity())
                        .append(" + ")
                        .append(target.getResultStatus()).append('/').append(target.getDisplaySeverity())
                        .append(" reason=").append(check.getReasonCode()).append('\n');
                continue;
            }
            EvaluationFindingDTO finding = find(evaluation, check.getCode());
            String expected = expectedStatus(check);
            assertEquals(expected, finding.getResultStatus(),
                    name + ": " + check.getCode());
            boolean changed = !expected.equals(checkPassStatus(check));
            // pass 一律映射 info 是设计口径，不算差异；只对 fail/unknown 报 severity 变化。
            boolean severityChanged = !"pass".equals(expected)
                    && !Strings.isNullOrEmpty(check.getSeverity())
                    && !check.getSeverity().equals(finding.getDisplaySeverity());
            if (changed || severityChanged || !"pass".equals(expected)) {
                report.append(check.getCode()).append(": legacy ")
                        .append(checkPassStatus(check))
                        .append('/').append(check.getSeverity())
                        .append(" -> ").append(expected)
                        .append('/').append(finding.getDisplaySeverity())
                        .append(" reason=").append(check.getReasonCode())
                        .append(" summary=").append(check.getSummary())
                        .append('\n');
            }
        }
        report.append('\n');
    }

    private String checkPassStatus(ReviewCheckDTO check) {
        return Boolean.FALSE.equals(check.getPassed()) ? "fail" : "pass";
    }

    private String expectedStatus(ReviewCheckDTO check) {
        if (Boolean.TRUE.equals(check.getPassed())
                && "warn".equals(check.getLevel())
                && !"info".equals(check.getSeverity())) {
            return "unknown";
        }
        return checkPassStatus(check);
    }

    private EvaluationFindingDTO find(PlanEvaluationDTO evaluation, String code) {
        return evaluation.getFindings().stream()
                .filter(item -> code.equals(item.getCode()))
                .findFirst()
                .orElseThrow(() -> new AssertionError("missing finding " + code));
    }

    private EvaluationContextDTO buildContext(PlanningStateDTO state) {
        CandidatePoolStateDTO pool = state.getCandidatePoolState();
        Map<String, CandidateItemDTO> byVolunteer = Maps.newHashMap();
        for (CandidateItemDTO candidate : safeList(pool.getItems())) {
            if (candidate != null && !Strings.isNullOrEmpty(candidate.getVolunteerId())) {
                byVolunteer.put(candidate.getVolunteerId(), candidate);
            }
        }
        boolean groupMode = "majorGroup".equalsIgnoreCase(pool.getVolunteerModel())
                || !safeList(state.getOrderedPlanState().getUnits()).isEmpty();
        List<EvaluationEntryRefDTO> entries = Lists.newArrayList();
        if (groupMode) {
            for (OrderedUnitDTO unit : safeList(state.getOrderedPlanState().getUnits())) {
                EvaluationEntryRefDTO entry = new EvaluationEntryRefDTO();
                entry.setLevel("unit");
                entry.setId(unit.getUnitId());
                entry.setPosition(unit.getPosition());
                entry.setSchoolName(unit.getSchoolName());
                entry.setProvinceName(unit.getProvinceName());
                entry.setPathTier(unit.getTier());
                entry.setSchoolRatio(unit.getSchoolEnrollRatio());
                entry.setMajorRatio(unit.getAdmissionRatio());
                Integer tuition = null;
                List<String> flags = Lists.newArrayList();
                for (PlanningUnitMajorDTO major : safeList(unit.getMajorItems())) {
                    CandidateItemDTO candidate = byVolunteer.get(major.getVolunteerId());
                    if (candidate == null) {
                        continue;
                    }
                    if (candidate.getTuitionPerYear() != null) {
                        tuition = tuition == null ? candidate.getTuitionPerYear()
                                : Math.max(tuition, candidate.getTuitionPerYear());
                    }
                    for (String flag : safeList(candidate.getRiskFlags())) {
                        if (!flags.contains(flag)) {
                            flags.add(flag);
                        }
                    }
                }
                entry.setTuitionPerYear(tuition);
                entry.setRiskFlags(flags);
                entries.add(entry);
            }
        } else {
            for (OrderedItemDTO item : safeList(state.getOrderedPlanState().getItems())) {
                CandidateItemDTO candidate = byVolunteer.get(item.getVolunteerId());
                EvaluationEntryRefDTO entry = new EvaluationEntryRefDTO();
                entry.setLevel("volunteer");
                entry.setId(item.getVolunteerId());
                entry.setPosition(item.getPosition());
                entry.setSchoolName(item.getSchoolName());
                entry.setMajorName(item.getMajorName());
                entry.setPathTier(item.getTier());
                if (candidate != null) {
                    entry.setProvinceName(candidate.getProvinceName());
                    entry.setSchoolRatio(candidate.getSchoolEnrollRatio());
                    entry.setMajorRatio(candidate.getAdmissionRatio());
                    entry.setTuitionPerYear(candidate.getTuitionPerYear());
                    entry.setRiskFlags(Lists.newArrayList(safeList(candidate.getRiskFlags())));
                }
                entries.add(entry);
            }
        }

        EvaluationContextDTO context = new EvaluationContextDTO();
        context.setEntries(entries);
        context.setSelectionTargetCount(selectionTargetCount(state));
        context.setRequiredCount(pool.getRequiredCount());
        context.setRequiredTierCounts(pool.getRequiredTierCounts());
        context.setAdmissionMode(groupMode ? "major_group" : "major");
        context.setSourceProvince(pool.getSourceProvinceName());
        context.setUserScore(pool.getUserScore());
        context.setCandidateSourceVersion(pool.getSourceVersion());
        context.setEvaluatedStateVersion(reviewSource(state));
        context.setPlanContentDigest(EvaluationVersion.sha256(
                JSON.toJSONString(state.getOrderedPlanState())));
        context.setDataVersion(state.getDataFreshnessState().getDataVersion());
        return context;
    }

    private Integer selectionTargetCount(PlanningStateDTO state) {
        if (state.getConstraintState() == null
                || state.getConstraintState().getHardPlanningObjectives() == null) {
            return null;
        }
        Integer target = state.getConstraintState().getHardPlanningObjectives()
                .getSelectionTargetCount();
        return target != null && target > 0 ? target : null;
    }

    private Integer reviewSource(PlanningStateDTO state) {
        return state.getReviewState() != null && state.getReviewState().getSourceVersion() != null
                ? state.getReviewState().getSourceVersion() : state.getVersion();
    }

    private static <T> List<T> safeList(List<T> value) {
        return value == null ? Lists.newArrayList() : value;
    }
}
