package com.ytell.zhiyuan.service.biz;

import com.alibaba.fastjson.JSON;
import com.alibaba.fastjson.JSONArray;
import com.alibaba.fastjson.JSONObject;
import org.junit.jupiter.api.Test;
import org.ojalgo.optimisation.Expression;
import org.ojalgo.optimisation.ExpressionsBasedModel;
import org.ojalgo.optimisation.Optimisation;
import org.ojalgo.optimisation.Variable;

import java.io.InputStream;
import java.math.BigDecimal;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.stream.Collectors;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * Offline benchmark for the 4.1 solver ADR. This class does not connect
 * the candidate algorithm to Proposal generation or production apply.
 */
class PlanSolver410AdrBenchmarkTest {

    private static final String CASE_RESOURCE = "release-4.1.0/plan-solver-adr-cases.json";
    private static final List<String> TIERS = Arrays.asList("sprint", "stable", "protect");

    @Test
    void shouldSolveJointConstraintsDeterministicallyWithPureJavaMipCandidate() throws Exception {
        JSONArray cases = loadCases();
        List<Map<String, Object>> metrics = new ArrayList<Map<String, Object>>();

        for (int caseIndex = 0; caseIndex < cases.size(); caseIndex++) {
            JSONObject fixture = cases.getJSONObject(caseIndex);
            int repeatCount = fixture.getIntValue("repeatCount");
            BenchmarkResult first = solve(fixture);
            assertEquals(fixture.getBooleanValue("expectedFeasible"), first.feasible, fixture.getString("name"));
            if (first.feasible) {
                assertSolution(fixture, first.selectedIndexes);
                assertEquals(
                        fixture.getString("expectedSelectionDigest"),
                        digest(first.selectedIndexes),
                        fixture.getString("name"));
            }
            for (int repeat = 1; repeat < repeatCount; repeat++) {
                BenchmarkResult repeated = solve(fixture);
                assertEquals(first.feasible, repeated.feasible, fixture.getString("name"));
                assertEquals(first.selectedIndexes, repeated.selectedIndexes, fixture.getString("name"));
            }
            metrics.add(first.asMetrics(fixture));
        }

        System.out.println("PLAN_SOLVER_410_ADR_METRICS=" + JSON.toJSONString(metrics));
    }

    private BenchmarkResult solve(JSONObject fixture) {
        int candidateCount = fixture.getIntValue("candidateCount");
        int targetCount = fixture.getIntValue("targetCount");
        int requirementCount = fixture.getIntValue("coverageConstraintCount");
        int minimumCoverage = fixture.getIntValue("minimumCoverage");
        int excludeModulo = fixture.getIntValue("excludeModulo");
        Set<Integer> pinned = integerSet(fixture.getJSONArray("pinnedIndexes"));
        JSONObject tierBounds = fixture.getJSONObject("tierBounds");

        ExpressionsBasedModel model = new ExpressionsBasedModel();
        List<Variable> variables = new ArrayList<Variable>();
        for (int candidate = 0; candidate < candidateCount; candidate++) {
            boolean current = candidate < targetCount;
            long weight = (current ? 0L : 1_000_000L) + candidate + 1L;
            Variable variable = Variable.makeBinary("candidate_" + candidate)
                    .weight(BigDecimal.valueOf(weight));
            if (pinned.contains(candidate)) {
                variable.lower(1).upper(1);
            } else if (excludeModulo > 0 && candidate % excludeModulo == 0) {
                variable.upper(0);
            }
            model.addVariable(variable);
            variables.add(variable);
        }

        Expression total = model.addExpression("target_count").level(targetCount);
        for (Variable variable : variables) {
            total.set(variable, 1);
        }

        for (String tier : TIERS) {
            JSONObject bounds = tierBounds.getJSONObject(tier);
            Expression expression = model.addExpression("tier_" + tier)
                    .lower(bounds.getIntValue("min"))
                    .upper(bounds.getIntValue("max"));
            for (int candidate = 0; candidate < candidateCount; candidate++) {
                if (tier.equals(tier(candidate))) {
                    expression.set(variables.get(candidate), 1);
                }
            }
        }

        for (int requirement = 0; requirement < requirementCount; requirement++) {
            Expression expression = model.addExpression("coverage_" + requirement).lower(minimumCoverage);
            for (int candidate = 0; candidate < candidateCount; candidate++) {
                if (matchesCoverage(candidate, requirement, requirementCount)) {
                    expression.set(variables.get(candidate), 1);
                }
            }
        }

        long started = System.nanoTime();
        Optimisation.Result result = model.minimise();
        long durationNanos = System.nanoTime() - started;
        boolean feasible = result.getState().isFeasible();
        List<Integer> selected = new ArrayList<Integer>();
        if (feasible) {
            for (int candidate = 0; candidate < candidateCount; candidate++) {
                if (result.doubleValue(candidate) > 0.5D) {
                    selected.add(candidate);
                }
            }
        }
        return new BenchmarkResult(feasible, result.getState().toString(), selected, durationNanos, targetCount);
    }

    private void assertSolution(JSONObject fixture, List<Integer> selected) {
        int targetCount = fixture.getIntValue("targetCount");
        int requirementCount = fixture.getIntValue("coverageConstraintCount");
        int minimumCoverage = fixture.getIntValue("minimumCoverage");
        int excludeModulo = fixture.getIntValue("excludeModulo");
        Set<Integer> pinned = integerSet(fixture.getJSONArray("pinnedIndexes"));
        JSONObject tierBounds = fixture.getJSONObject("tierBounds");

        assertEquals(targetCount, selected.size(), fixture.getString("name"));
        assertTrue(selected.containsAll(pinned), fixture.getString("name"));
        for (Integer candidate : selected) {
            if (!pinned.contains(candidate) && excludeModulo > 0) {
                assertFalse(candidate % excludeModulo == 0, fixture.getString("name"));
            }
        }
        for (String tier : TIERS) {
            long count = selected.stream().filter(candidate -> tier.equals(tier(candidate))).count();
            JSONObject bounds = tierBounds.getJSONObject(tier);
            assertTrue(count >= bounds.getIntValue("min"), fixture.getString("name"));
            assertTrue(count <= bounds.getIntValue("max"), fixture.getString("name"));
        }
        for (int requirement = 0; requirement < requirementCount; requirement++) {
            final int required = requirement;
            long count = selected.stream()
                    .filter(candidate -> matchesCoverage(candidate, required, requirementCount))
                    .count();
            assertTrue(count >= minimumCoverage, fixture.getString("name") + " coverage " + requirement);
        }
    }

    private static boolean matchesCoverage(int candidate, int requirement, int requirementCount) {
        int mixed = Math.floorMod(candidate * 37 + requirement * 53 + requirement * requirement * 11, 101);
        return mixed < 28 || candidate % requirementCount == requirement;
    }

    private static String tier(int candidate) {
        return TIERS.get(Math.floorMod(candidate, TIERS.size()));
    }

    private static Set<Integer> integerSet(JSONArray values) {
        if (values == null) {
            return Collections.emptySet();
        }
        return values.stream()
                .map(value -> ((Number) value).intValue())
                .collect(Collectors.toCollection(LinkedHashSet::new));
    }

    private static JSONArray loadCases() {
        InputStream stream = PlanSolver410AdrBenchmarkTest.class.getClassLoader().getResourceAsStream(CASE_RESOURCE);
        assertNotNull(stream, CASE_RESOURCE);
        try (InputStream input = stream) {
            byte[] bytes = new byte[32 * 1024];
            int offset = 0;
            int read;
            while ((read = input.read(bytes, offset, bytes.length - offset)) >= 0) {
                offset += read;
                if (offset == bytes.length) {
                    bytes = Arrays.copyOf(bytes, bytes.length * 2);
                }
            }
            JSONObject payload = JSON.parseObject(new String(bytes, 0, offset, StandardCharsets.UTF_8));
            return payload.getJSONArray("cases");
        } catch (Exception exc) {
            throw new IllegalStateException("cannot load " + CASE_RESOURCE, exc);
        }
    }

    private static String digest(List<Integer> selected) {
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            byte[] encoded = selected.toString().getBytes(StandardCharsets.UTF_8);
            return toHex(digest.digest(encoded));
        } catch (Exception exc) {
            throw new IllegalStateException(exc);
        }
    }

    private static String toHex(byte[] values) {
        StringBuilder result = new StringBuilder(values.length * 2);
        for (byte value : values) {
            result.append(String.format("%02x", value));
        }
        return result.toString();
    }

    private static double nanosToMillis(long value) {
        return Math.round(value / 10_000.0D) / 100.0D;
    }

    private static final class BenchmarkResult {
        private final boolean feasible;
        private final String state;
        private final List<Integer> selectedIndexes;
        private final long durationNanos;
        private final int originalTargetCount;

        private BenchmarkResult(boolean feasible,
                                String state,
                                List<Integer> selectedIndexes,
                                long durationNanos,
                                int originalTargetCount) {
            this.feasible = feasible;
            this.state = state;
            this.selectedIndexes = selectedIndexes;
            this.durationNanos = durationNanos;
            this.originalTargetCount = originalTargetCount;
        }

        private Map<String, Object> asMetrics(JSONObject fixture) {
            Map<String, Object> result = new LinkedHashMap<String, Object>();
            result.put("case", fixture.getString("name"));
            result.put("algorithm", "ojalgo-48.4.2-mip-candidate");
            result.put("candidateCount", fixture.getIntValue("candidateCount"));
            result.put("constraintCount", fixture.getIntValue("coverageConstraintCount") + TIERS.size() + 1);
            result.put("state", state);
            result.put("feasible", feasible);
            result.put("durationMs", nanosToMillis(durationNanos));
            result.put("selectedCount", selectedIndexes.size());
            result.put("churnCount", selectedIndexes.stream().filter(index -> index >= originalTargetCount).count());
            result.put("selectionDigest", digest(selectedIndexes));
            return result;
        }
    }
}
