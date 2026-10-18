package com.ytell.zhiyuan.service.biz;

import com.alibaba.fastjson.JSON;
import com.alibaba.fastjson.JSONArray;
import com.alibaba.fastjson.JSONObject;
import com.ytell.zhiyuan.model.dto.planning.CandidateSnapshotDTO;
import com.ytell.zhiyuan.model.dto.planning.CanonicalPlanningObjectiveSetDTO;
import com.ytell.zhiyuan.model.dto.planning.MutationPolicyDTO;
import org.junit.jupiter.api.Test;

import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;

/** S0a 仓库内确定性 fixture：不回连数据库，不依赖外部 32MB 池。 */
class StagedSolverFixtureTest {

    private static final List<String> CASES = Arrays.asList(
            "release-5.3/j53-solver-shadow/safety-before-churn.json",
            "release-5.3/j53-solver-shadow/utility-generate.json");

    private final StagedDeterministicPlanSolver solver = new StagedDeterministicPlanSolver();

    @Test
    void fixturesProduceDeterministicSelectionAndLevels() throws Exception {
        for (String path : CASES) {
            JSONObject fixture = load(path);
            CandidateSnapshotDTO snapshot = fixture.getJSONObject("snapshot")
                    .toJavaObject(CandidateSnapshotDTO.class);
            CanonicalPlanningObjectiveSetDTO objectives = fixture.getJSONObject("objectives")
                    .toJavaObject(CanonicalPlanningObjectiveSetDTO.class);
            MutationPolicyDTO policy = fixture.getJSONObject("policy")
                    .toJavaObject(MutationPolicyDTO.class);
            JSONObject expected = fixture.getJSONObject("expected");

            for (int run = 0; run < 3; run++) {
                StagedDeterministicPlanSolver.Result result = solver.solve(snapshot, objectives, policy);
                assertEquals("ready", result.solverResult.getStatus(),
                        path + " diagnostics=" + result.solverResult.getDiagnostics());
                assertEquals(strings(expected.getJSONArray("selectedEntityIds")),
                        result.solverResult.getSelectedEntityIds(), path);
                JSONObject levels = expected.getJSONObject("levels");
                for (Map.Entry<String, Object> entry : levels.entrySet()) {
                    assertEquals(((Number) entry.getValue()).longValue(),
                            level(result, entry.getKey()), path + " level=" + entry.getKey());
                }
            }
        }
    }

    private JSONObject load(String path) throws Exception {
        InputStream stream = getClass().getClassLoader().getResourceAsStream(path);
        assertNotNull(stream, path);
        byte[] bytes = new byte[stream.available()];
        int read = stream.read(bytes);
        stream.close();
        return JSON.parseObject(new String(bytes, 0, read, StandardCharsets.UTF_8));
    }

    private List<String> strings(JSONArray values) {
        List<String> result = new ArrayList<String>();
        for (int index = 0; index < values.size(); index++) {
            result.add(values.getString(index));
        }
        return result;
    }

    private long level(StagedDeterministicPlanSolver.Result result, String name) {
        for (StagedDeterministicPlanSolver.ObjectiveLevel level : result.levels) {
            if (name.equals(level.level)) {
                return level.value;
            }
        }
        throw new AssertionError("missing level " + name);
    }
}
