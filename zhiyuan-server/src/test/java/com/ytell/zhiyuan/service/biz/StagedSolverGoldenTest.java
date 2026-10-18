package com.ytell.zhiyuan.service.biz;

import com.alibaba.fastjson.JSON;
import com.google.common.base.Strings;
import com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO;
import com.ytell.zhiyuan.model.dto.planning.CandidatePoolStateDTO;
import com.ytell.zhiyuan.model.dto.planning.CandidateSnapshotDTO;
import com.ytell.zhiyuan.model.dto.planning.CanonicalPlanningObjectiveSetDTO;
import com.ytell.zhiyuan.model.dto.planning.MutationPolicyDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanSolverResultDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;

import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.ArrayList;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * J5.3 golden：拿真实会话的 planningState（可选拆分候选池）跑 staged solver。
 *
 * <p>默认跳过；设置 {@code STAGED_SOLVER_GOLDEN_FILES=state.json[|pool.json],...}
 * 运行。只读文件、不连库。一次跑两遍，验证固定部署内的确定性；不比较旧 solver
 * 选择集（旧路径的 current/available 口径在 runtime 内部，不在此复制）。</p>
 */
@EnabledIfEnvironmentVariable(named = "STAGED_SOLVER_GOLDEN_FILES", matches = ".+")
class StagedSolverGoldenTest {

    private final StagedDeterministicPlanSolver solver = new StagedDeterministicPlanSolver();

    @Test
    void realSessionsProduceDeterministicReadyOrExplainedBlock() throws Exception {
        String raw = System.getenv("STAGED_SOLVER_GOLDEN_FILES");
        StringBuilder report = new StringBuilder();
        for (String item : raw.split(",")) {
            String[] parts = item.split("\\|", -1);
            File stateFile = new File(parts[0].trim());
            File poolFile = parts.length > 1 && !parts[1].trim().isEmpty()
                    ? new File(parts[1].trim()) : null;
            PlanningStateDTO state = JSON.parseObject(
                    new String(Files.readAllBytes(stateFile.toPath()), StandardCharsets.UTF_8),
                    PlanningStateDTO.class);
            assertNotNull(state);
            if (poolFile != null) {
                CandidatePoolStateDTO pool = JSON.parseObject(
                        new String(Files.readAllBytes(poolFile.toPath()), StandardCharsets.UTF_8),
                        CandidatePoolStateDTO.class);
                state.getCandidatePoolState().setItems(pool.getItems());
            }
            runGolden(stateFile.getName(), state, report);
        }
        System.out.println(report);
    }

    private void runGolden(String name, PlanningStateDTO state, StringBuilder report) {
        CandidatePoolStateDTO pool = state.getCandidatePoolState();
        List<CandidateItemDTO> rawPool = pool == null || pool.getItems() == null
                ? new ArrayList<CandidateItemDTO>() : pool.getItems();
        // 运行时进 solver 前会先 normalizeCandidateIdentities 去重；golden 直接喂
        // 原始池，这里保持同一口径（后出现的覆盖先出现的）。
        java.util.Map<String, CandidateItemDTO> byId = new java.util.LinkedHashMap<String, CandidateItemDTO>();
        for (CandidateItemDTO candidate : rawPool) {
            if (candidate != null && !Strings.isNullOrEmpty(candidate.getVolunteerId())) {
                byId.put(candidate.getVolunteerId(), candidate);
            }
        }
        List<CandidateItemDTO> poolItems = new ArrayList<CandidateItemDTO>(byId.values());
        CanonicalPlanningObjectiveSetDTO objectives = PlanningObjectiveCompiler.compileConfirmed(state);
        Integer target = objectives.getTargetCount();
        if (target == null || target <= 0) {
            report.append(name).append(" SKIP no target\n");
            return;
        }
        MutationPolicyDTO policy = new MutationPolicyDTO();
        policy.setAction("FILL");
        policy.setLockExisting(false);
        policy.setCountAsChurn(true);
        policy.setRequireCompensationSafe(true);
        CanonicalPlanningObjectiveSetDTO stagedObjectives = JSON.parseObject(
                JSON.toJSONString(objectives), CanonicalPlanningObjectiveSetDTO.class);
        PlanningObjectiveCompiler.enrichV2(state, stagedObjectives, policy);

        CandidateSnapshotDTO snapshot = CandidateSnapshotBuilder.build(
                state, poolItems, CandidateSnapshotBuilder.CurrentSource.ORDERED_FIRST);
        PlanSolverResultDTO first = solver.solve(snapshot, stagedObjectives, policy).solverResult;
        PlanSolverResultDTO second = solver.solve(snapshot, stagedObjectives, policy).solverResult;

        assertNotNull(first);
        assertTrue("ready".equals(first.getStatus()) || "blocked".equals(first.getStatus()),
                name + " unexpected status=" + first.getStatus());
        if ("blocked".equals(first.getStatus())) {
            String reason = first.getDiagnostics().isEmpty()
                    ? null : first.getDiagnostics().get(0).getReasonCode();
            assertFalse(Strings.isNullOrEmpty(reason), name + " blocked without reason");
            assertFalse("solver_timeout".equals(reason), name + " timed out");
        } else {
            assertEquals(first.getSelectedEntityIds(), second.getSelectedEntityIds(),
                    name + " not deterministic across two runs");
            assertEquals(target.intValue(), first.getSelectedEntityIds().size(),
                    name + " selected size != target");
        }
        report.append(name)
                .append(" pool=").append(poolItems.size())
                .append(" target=").append(target)
                .append(" status=").append(first.getStatus())
                .append(" selected=").append(first.getSelectedEntityIds() == null
                        ? 0 : first.getSelectedEntityIds().size())
                .append(" candidates=").append(first.getCandidateCount())
                .append(" durationMs=").append(first.getDurationMs())
                .append(" reason=").append(first.getDiagnostics().isEmpty()
                        ? null : first.getDiagnostics().get(0).getReasonCode())
                .append('\n');
    }
}
