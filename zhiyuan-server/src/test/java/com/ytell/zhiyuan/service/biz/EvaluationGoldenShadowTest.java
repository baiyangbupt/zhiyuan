package com.ytell.zhiyuan.service.biz;

import com.alibaba.fastjson.JSON;
import com.ytell.zhiyuan.model.dto.planning.CandidatePoolStateDTO;
import com.ytell.zhiyuan.model.dto.planning.EvaluationContextDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanEvaluationDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import com.ytell.zhiyuan.model.dto.planning.ReviewStateDTO;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.List;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Read-only snapshot comparison using the production evaluation input boundary.
 * EVALUATION_GOLDEN_FILES=state.json[|pool.json],... enables the snapshot runner;
 * the adjacent harness regression tests run without environment variables.
 */
class EvaluationGoldenShadowTest {

    private final ReviewEvaluationMapper mapper = new ReviewEvaluationMapper();

    @Test
    @EnabledIfEnvironmentVariable(named = "EVALUATION_GOLDEN_FILES", matches = ".+")
    void shadowEvaluationExplainsEveryDifference() throws Exception {
        StringBuilder report = new StringBuilder();
        List<Throwable> failures = new ArrayList<>();
        int evaluated = 0;
        int skipped = 0;
        for (String fixture : System.getenv("EVALUATION_GOLDEN_FILES").split(",")) {
            String[] paths = fixture.split("\\|", -1);
            String name = Paths.get(paths[0].trim()).getFileName().toString();
            try {
                assertTrue(paths.length <= 2, "invalid fixture: " + fixture);
                PlanningStateDTO state = JSON.parseObject(read(paths[0]), PlanningStateDTO.class);
                assertNotNull(state, name + ": state");
                if (paths.length == 2 && !paths[1].trim().isEmpty()) {
                    CandidatePoolStateDTO pool = JSON.parseObject(read(paths[1]), CandidatePoolStateDTO.class);
                    assertNotNull(pool, name + ": external pool");
                    assertNotNull(state.getCandidatePoolState(), name + ": pool metadata");
                    state.getCandidatePoolState().setItems(pool.getItems());
                }
                if (assertGolden(state, name, report)) {
                    evaluated++;
                } else {
                    skipped++;
                }
            } catch (Exception | AssertionError failure) {
                report.append("FAIL: ").append(name).append(": ").append(failure).append("\n\n");
                failures.add(failure);
            }
        }
        report.append("SUMMARY evaluated=").append(evaluated).append(" skipped=")
                .append(skipped).append(" failed=").append(failures.size()).append('\n');
        String reportPath = System.getenv("EVALUATION_GOLDEN_REPORT");
        if (reportPath != null && !reportPath.trim().isEmpty()) {
            Files.write(Paths.get(reportPath), report.toString().getBytes(StandardCharsets.UTF_8));
        }
        System.out.println(report);
        assertAll("golden snapshots", failures.stream().map(failure -> () -> { throw failure; }));
        assertTrue(evaluated > 0, "no evaluable snapshots; skips are not a successful comparison");
    }

    boolean assertGolden(PlanningStateDTO state, String name, StringBuilder report) {
        ReviewStateDTO review = state.getReviewState();
        report.append("== ").append(name).append(" ==\n");
        if (review == null || review.getChecks() == null || review.getChecks().isEmpty()) {
            report.append("SKIP: no review checks (reviewSource=")
                    .append(review == null ? null : review.getSourceVersion())
                    .append(", version=").append(state.getVersion()).append(")\n\n");
            return false;
        }
        String stateBefore = JSON.toJSONString(state);
        EvaluationContextDTO context = buildContext(state);
        String contextBefore = JSON.toJSONString(context);
        PlanEvaluationDTO evaluation = mapper.map(review, context);
        report.append("version=").append(state.getVersion()).append(" reviewSource=")
                .append(review.getSourceVersion()).append(" checks=").append(review.getChecks().size())
                .append(" findings=").append(evaluation.getFindings().size()).append('\n');
        EvaluationGoldenOracle.verify(state, context, evaluation, name, report);
        assertEquals(stateBefore, JSON.toJSONString(state), name + ": state mutated");
        assertEquals(contextBefore, JSON.toJSONString(context), name + ": context mutated");
        assertEquals(JSON.toJSONString(evaluation), JSON.toJSONString(mapper.map(review, context)),
                name + ": evaluation must be deterministic");
        report.append("PASS: independently verified derived facts; strict legacy status parity\n\n");
        return true;
    }

    EvaluationContextDTO buildContext(PlanningStateDTO state) {
        return new EvaluationContextBuilder().build(state,
                state.getCandidatePoolState() == null ? null : state.getCandidatePoolState().getItems(),
                state.getReviewState());
    }

    private String read(String path) throws Exception {
        Path file = Paths.get(path.trim());
        return new String(Files.readAllBytes(file), StandardCharsets.UTF_8);
    }
}
