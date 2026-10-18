package com.ytell.zhiyuan.service.biz;

import com.alibaba.fastjson.JSON;
import com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO;
import com.ytell.zhiyuan.model.dto.planning.CandidateSnapshotDTO;
import com.ytell.zhiyuan.model.dto.planning.CanonicalPlanningObjectiveSetDTO;
import com.ytell.zhiyuan.model.dto.planning.MutationPolicyDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanSolverResultDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;

/**
 * S0a 运行时影子：旧 solver 结果照旧生效，新分阶段 solver 只计算并记录差异。
 *
 * <p>默认关闭：`-Dsolver.v2.shadow=true` 或环境变量
 * `SOLVER_V2_SHADOW=true`。异常一律吞掉并降级，不能影响旧路径。</p>
 */
final class SolverShadowSupport {

    private static final Logger LOG = LoggerFactory.getLogger(SolverShadowSupport.class);
    private static final StagedDeterministicPlanSolver STAGED = new StagedDeterministicPlanSolver();

    private SolverShadowSupport() {
    }

    static boolean enabled() {
        String value = System.getProperty("solver.v2.shadow");
        if (value == null) {
            value = System.getenv("SOLVER_V2_SHADOW");
        }
        return "true".equalsIgnoreCase(value) || "1".equals(value);
    }

    /**
     * P4 灰度：`-Dsolver.v2.diversity=true` 或环境变量
     * `SOLVER_V2_DIVERSITY=true` 时，enrichV2 写入 soft 多样性策略；默认关闭。
     */
    static boolean diversityEnabled() {
        String value = System.getProperty("solver.v2.diversity");
        if (value == null) {
            value = System.getenv("SOLVER_V2_DIVERSITY");
        }
        return "true".equalsIgnoreCase(value) || "1".equals(value);
    }

    /** S1 灰度：`solver.v2.paths=fill,initial` 的逗号列表；默认空=旧路径。 */
    static boolean pathEnabled(String path) {
        String value = System.getProperty("solver.v2.paths");
        if (value == null) {
            value = System.getenv("SOLVER_V2_PATHS");
        }
        if (value == null || path == null) {
            return false;
        }
        for (String item : value.split(",")) {
            if (path.equalsIgnoreCase(item.trim())) {
                return true;
            }
        }
        return false;
    }

    static void shadowSelection(PlanningStateDTO state,
                                List<CandidateItemDTO> effectiveCandidates,
                                CanonicalPlanningObjectiveSetDTO objectives,
                                PlanSolverResultDTO legacyResult) {
        if (!enabled() || state == null || objectives == null) {
            return;
        }
        try {
            CandidateSnapshotDTO snapshot = CandidateSnapshotBuilder.build(state, effectiveCandidates);
            MutationPolicyDTO policy = new MutationPolicyDTO();
            policy.setAction("FILL");
            policy.setLockExisting(false);
            policy.setCountAsChurn(true);
            CanonicalPlanningObjectiveSetDTO shadowObjectives = JSON.parseObject(
                    JSON.toJSONString(objectives), CanonicalPlanningObjectiveSetDTO.class);
            PlanningObjectiveCompiler.enrichV2(state, shadowObjectives, policy);
            StagedDeterministicPlanSolver.Result staged = STAGED.solve(
                    snapshot, shadowObjectives, policy);
            logDiff(state, snapshot, legacyResult, staged.solverResult);
        } catch (Throwable ex) {
            // shadow 不能影响旧路径；只记录一次简短告警。
            LOG.warn("solver.shadow failed version={} sourceVersion={} error={}",
                    state.getVersion(), sourceVersion(state), ex.getClass().getSimpleName());
            LOG.debug("solver.shadow failure detail", ex);
        }
    }

    private static void logDiff(PlanningStateDTO state,
                                CandidateSnapshotDTO snapshot,
                                PlanSolverResultDTO legacy,
                                PlanSolverResultDTO staged) {
        Set<String> legacyIds = new LinkedHashSet<String>(legacy == null
                ? java.util.Collections.<String>emptyList() : legacy.getSelectedEntityIds());
        Set<String> stagedIds = new LinkedHashSet<String>(staged == null
                ? java.util.Collections.<String>emptyList() : staged.getSelectedEntityIds());
        java.util.List<String> onlyLegacyIds = new java.util.ArrayList<String>();
        for (String id : legacyIds) {
            if (!stagedIds.contains(id)) {
                onlyLegacyIds.add(id);
            }
        }
        java.util.List<String> onlyStagedIds = new java.util.ArrayList<String>();
        for (String id : stagedIds) {
            if (!legacyIds.contains(id)) {
                onlyStagedIds.add(id);
            }
        }
        boolean hardRegression = legacy != null && "ready".equals(legacy.getStatus())
                && (staged == null || !"ready".equals(staged.getStatus()));
        String line = "solver.shadow version=" + state.getVersion()
                + " sourceVersion=" + sourceVersion(state)
                + " snapshotFacts=" + (snapshot == null || snapshot.getFacts() == null
                ? 0 : snapshot.getFacts().size())
                + " legacy=" + (legacy == null ? "null" : legacy.getStatus())
                + " staged=" + (staged == null ? "null" : staged.getStatus())
                + " legacyCount=" + legacyIds.size()
                + " stagedCount=" + stagedIds.size()
                + " onlyLegacy=" + onlyLegacyIds.size()
                + " onlyStaged=" + onlyStagedIds.size()
                + " onlyLegacyIds=" + preview(onlyLegacyIds)
                + " onlyStagedIds=" + preview(onlyStagedIds)
                + " legacyDigest=" + (legacy == null ? null : legacy.getInputDigest())
                + " stagedDigest=" + (staged == null ? null : staged.getInputDigest());
        if (hardRegression || !"ready".equals(staged == null ? null : staged.getStatus())) {
            LOG.warn(line);
        } else {
            LOG.info(line);
        }
    }

    private static String preview(java.util.List<String> ids) {
        if (ids == null || ids.isEmpty()) {
            return "[]";
        }
        int limit = Math.min(ids.size(), 8);
        return ids.subList(0, limit).toString() + (ids.size() > limit ? "...+" + (ids.size() - limit) : "");
    }

    private static Integer sourceVersion(PlanningStateDTO state) {
        return state.getCandidatePoolState() == null
                ? null : state.getCandidatePoolState().getSourceVersion();
    }
}
