package com.ytell.zhiyuan.service.biz;

import com.ytell.zhiyuan.model.dto.planning.ReviewRuleMetadataDTO;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

public class ReviewRuleRegistryTest {

    @Test
    void shouldExposeMetadataForStructuralRisk() {
        ReviewRuleMetadataDTO metadata = ReviewRuleRegistry.get("probability_gap");

        assertNotNull(metadata);
        assertEquals("录取率梯度断层", metadata.getLabel());
        assertEquals("structure_risk", metadata.getCategory());
        assertEquals("structure", metadata.getScopeKind());
        assertEquals("preview_fixable", metadata.getFixability());
        assertEquals("fill_probability_gap", metadata.getDefaultFixStrategy());
        assertTrue(metadata.getTargetModes().contains("major"));
        assertTrue(metadata.getTargetModes().contains("major_group"));
        assertTrue(metadata.getSupportedFixStrategies().contains("fill_probability_gap"));
        assertTrue(metadata.getRequiresConfirmation());
    }

    @Test
    void shouldExposeMetadataForInformationalNotice() {
        ReviewRuleMetadataDTO metadata = ReviewRuleRegistry.get("plan_update_notice");

        assertNotNull(metadata);
        assertEquals("policy_notice", metadata.getCategory());
        assertEquals("informational", metadata.getScopeKind());
        assertEquals("not_fixable", metadata.getFixability());
        assertFalse(metadata.getRequiresConfirmation());
        assertTrue(metadata.getSupportedFixStrategies().isEmpty());
        assertNull(metadata.getDefaultFixStrategy());
    }

    @Test
    void shouldReturnDefensiveCopies() {
        ReviewRuleMetadataDTO metadata = ReviewRuleRegistry.get("high_tuition");
        metadata.getSupportedFixStrategies().clear();

        ReviewRuleMetadataDTO next = ReviewRuleRegistry.get("high_tuition");

        assertTrue(next.getSupportedFixStrategies().contains("replace_risk_items"));
        assertTrue(next.getSupportedFixStrategies().contains("remove_risk_items"));
    }

    @Test
    void shouldListAuthoritativeRulesWithBackendDefaultStrategy() {
        ReviewRuleMetadataDTO highTuition = ReviewRuleRegistry.list().stream()
                .filter(item -> "high_tuition".equals(item.getCode()))
                .findFirst()
                .orElse(null);

        assertNotNull(highTuition);
        assertEquals("item", highTuition.getScopeKind());
        assertEquals("replace_risk_items", highTuition.getDefaultFixStrategy());
        assertTrue(highTuition.getSupportedFixStrategies().contains("replace_risk_items"));
        assertTrue(highTuition.getSupportedFixStrategies().contains("remove_risk_items"));
    }

    @Test
    void shouldUseNeutralCountValidationLabel() {
        ReviewRuleMetadataDTO metadata = ReviewRuleRegistry.get("count_validation");

        assertNotNull(metadata);
        assertEquals("数量校验", metadata.getLabel());
    }
}
