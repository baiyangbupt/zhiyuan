package com.ytell.zhiyuan.service.biz;

import com.alibaba.fastjson.JSON;
import com.ytell.zhiyuan.model.dto.planning.CandidatePoolStateDTO;
import com.ytell.zhiyuan.model.dto.planning.EvaluationContextDTO;
import com.ytell.zhiyuan.model.dto.planning.EvaluationFindingDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanEvaluationDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;

import static org.junit.jupiter.api.Assertions.*;

@EnabledIfEnvironmentVariable(named = "EVALUATION_GOLDEN_FILES", matches = ".+")
class ReviewCommandGoldenTest {
    @Test
    void snapshotCommandsAreDeterministicAndDoNotMutateEvaluationInputs() throws Exception {
        ReviewEvaluationMapper mapper = new ReviewEvaluationMapper();
        int evaluated = 0;
        int skipped = 0;
        for (String fixture : System.getenv("EVALUATION_GOLDEN_FILES").split(",")) {
            String[] paths = fixture.split("\\|", -1);
            PlanningStateDTO state = JSON.parseObject(read(paths[0]), PlanningStateDTO.class);
            if (paths.length > 1 && !paths[1].trim().isEmpty()) {
                state.setCandidatePoolState(JSON.parseObject(read(paths[1]), CandidatePoolStateDTO.class));
            }
            if (state.getReviewState() == null || state.getReviewState().getChecks().isEmpty()) {
                System.out.println("J55 command fixture skipped (no review): " + paths[0]);
                skipped++;
                continue;
            }
            String baseline = JSON.toJSONString(state);
            EvaluationContextDTO context = new EvaluationContextBuilder().build(state,
                    state.getCandidatePoolState().getItems(), state.getReviewState());
            String contextBaseline = JSON.toJSONString(context);
            PlanEvaluationDTO first = mapper.map(state.getReviewState(), context);
            PlanEvaluationDTO second = mapper.map(state.getReviewState(), context);
            assertEquals(JSON.toJSONString(first), JSON.toJSONString(second), paths[0]);
            assertEquals(baseline, JSON.toJSONString(state), paths[0]);
            assertEquals(contextBaseline, JSON.toJSONString(context), paths[0]);
            for (EvaluationFindingDTO finding : first.getFindings()) {
                if (!"fail".equals(finding.getResultStatus())) {
                    assertNull(finding.getObjectiveDelta(), finding.getCode());
                    assertNull(finding.getSuggestedCommand(), finding.getCode());
                }
                if (finding.getSuggestedCommand() != null) {
                    assertFalse(finding.getSuggestedCommand().getExecutable());
                    assertEquals(first.getEvaluationVersion(), finding.getSuggestedCommand().getEvaluationVersion());
                    assertNotNull(finding.getSuggestedCommand().getCommandDigest());
                    assertEquals(finding.getObjectiveDelta().getStrategy(), finding.getSuggestedCommand().getStrategy());
                }
            }
            evaluated++;
        }
        assertTrue(evaluated > 0);
        System.out.println("J55 command fixtures evaluated=" + evaluated + ", skipped=" + skipped);
    }

    private String read(String path) throws Exception {
        return new String(Files.readAllBytes(Paths.get(path.trim())), StandardCharsets.UTF_8);
    }
}
