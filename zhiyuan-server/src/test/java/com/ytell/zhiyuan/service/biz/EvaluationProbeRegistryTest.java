package com.ytell.zhiyuan.service.biz;

import com.ytell.zhiyuan.model.dto.planning.EvaluationProbeMetadataDTO;
import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.Set;
import java.util.stream.Collectors;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

class EvaluationProbeRegistryTest {

    @Test
    void shouldRegisterAllFourteenLegacyChecksAsFifteenProbes() {
        List<EvaluationProbeMetadataDTO> probes = EvaluationProbeRegistry.list();
        Set<String> codes = probes.stream()
                .map(EvaluationProbeMetadataDTO::getCode)
                .collect(Collectors.toSet());

        assertEquals(15, probes.size());
        assertTrue(codes.contains("count_validation_hard"));
        assertTrue(codes.contains("count_target"));
        assertTrue(codes.contains("group_inner_safety_guard"));
        assertTrue(codes.contains("plan_update_notice"));
        assertTrue(codes.contains("adjustment_notice"));
        assertEquals(1, probes.stream()
                .filter(item -> "count_validation_hard".equals(item.getCode())).count());
    }

    @Test
    void groupInnerSafetyMustBeHardBlockAndPolicyMustBeNonFixable() {
        EvaluationProbeMetadataDTO group = EvaluationProbeRegistry.get("group_inner_safety_guard");
        assertNotNull(group);
        assertEquals("hard", group.getLayer());
        assertEquals("hard", group.getRuleStrength());
        assertTrue(group.getAllowedSeverities().contains("block"));

        EvaluationProbeMetadataDTO notice = EvaluationProbeRegistry.get("adjustment_notice");
        assertNotNull(notice);
        assertEquals("policy", notice.getRuleStrength());
        assertEquals("none", notice.getFixability());
        assertEquals(java.util.Arrays.asList("info"), notice.getAllowedSeverities());
    }

    @Test
    void countValidationIsSplitIntoHardAndTargetProbes() {
        EvaluationProbeMetadataDTO hard = EvaluationProbeRegistry.get("count_validation_hard");
        EvaluationProbeMetadataDTO target = EvaluationProbeRegistry.get("count_target");

        assertEquals("count_validation", hard.getSourceCheck());
        assertEquals("count_validation", target.getSourceCheck());
        assertEquals("hard", hard.getRuleStrength());
        assertEquals("soft", target.getRuleStrength());
        assertEquals("structure", target.getLayer());
        assertEquals(java.util.Arrays.asList("block"), hard.getAllowedSeverities());
        assertTrue(target.getAllowedSeverities().contains("action"));
        assertTrue(target.getAllowedSeverities().contains("notice"));
    }
}
