package com.ytell.zhiyuan.service.biz;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

class EvaluationVersionTest {

    @Test
    void evaluationVersionIsDeterministicAndChangesWithAnyInput() {
        String base = EvaluationVersion.evaluationVersion(
                11, "digest-a", 7, "data-1", EvaluationVersion.objectiveModelVersion());
        String same = EvaluationVersion.evaluationVersion(
                11, "digest-a", 7, "data-1", EvaluationVersion.objectiveModelVersion());

        assertEquals(base, same);
        assertNotEquals(base, EvaluationVersion.evaluationVersion(
                12, "digest-a", 7, "data-1", EvaluationVersion.objectiveModelVersion()));
        assertNotEquals(base, EvaluationVersion.evaluationVersion(
                11, "digest-b", 7, "data-1", EvaluationVersion.objectiveModelVersion()));
        assertNotEquals(base, EvaluationVersion.evaluationVersion(
                11, "digest-a", 8, "data-1", EvaluationVersion.objectiveModelVersion()));
        assertNotEquals(base, EvaluationVersion.evaluationVersion(
                11, "digest-a", 7, "data-2", EvaluationVersion.objectiveModelVersion()));
        assertNotEquals(base, EvaluationVersion.evaluationVersion(
                11, "digest-a", 7, "data-1", "objective-model-v2"));
    }

    @Test
    void incompleteInputsMustNotProduceAnEvaluationVersion() {
        assertNull(EvaluationVersion.evaluationVersion(
                null, "digest", 1, "data", EvaluationVersion.objectiveModelVersion()));
        assertNull(EvaluationVersion.evaluationVersion(
                1, "", 1, "data", EvaluationVersion.objectiveModelVersion()));
        assertNull(EvaluationVersion.evaluationVersion(
                1, "digest", 1, "data", null));
    }

    @Test
    void cacheKeyCarriesTenantSessionVersionAndOverlay() {
        String version = EvaluationVersion.evaluationVersion(
                3, "digest", 2, "d1", EvaluationVersion.objectiveModelVersion());
        String key = EvaluationVersion.cacheKey("t1", "s1", version, "none", "remove:v1");

        assertTrue(key.startsWith("plan-evaluation:t1:s1:" + version));
        assertTrue(key.contains("overlay=none"));
        assertTrue(key.contains("counterfactual=remove:v1"));
        assertNull(EvaluationVersion.cacheKey("t1", "s1", null, "none", ""));
    }
}
