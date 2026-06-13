package com.ytell.zhiyuan.service.biz;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

public class RepairProposalTaxonomyTest {

    @Test
    void shouldNormalizeLegacyStrategyAliases() {
        assertEquals(RepairProposalTaxonomy.Strategy.FILL_MISSING_COUNT,
                RepairProposalTaxonomy.normalizeStrategy("fill_total_count"));
        assertEquals(RepairProposalTaxonomy.Strategy.ADD_SAFETY_ITEMS,
                RepairProposalTaxonomy.normalizeStrategy("add_local_protect"));
        assertEquals(RepairProposalTaxonomy.Strategy.REBALANCE_TIER_RATIO,
                RepairProposalTaxonomy.normalizeStrategy("rebalance_protect_ratio"));
        assertEquals(RepairProposalTaxonomy.Strategy.REMOVE_RISK_ITEMS,
                RepairProposalTaxonomy.normalizeStrategy("remove_volunteers"));
        assertEquals(RepairProposalTaxonomy.Strategy.CANNOT_SATISFY,
                RepairProposalTaxonomy.normalizeStrategy("blocked"));
    }

    @Test
    void shouldNormalizeProposalSource() {
        assertEquals(RepairProposalTaxonomy.ProposalSource.REVIEW_CHECK,
                RepairProposalTaxonomy.normalizeProposalSource(null));
        assertEquals(RepairProposalTaxonomy.ProposalSource.REVIEW_CHECK,
                RepairProposalTaxonomy.normalizeProposalSource(""));
        assertTrue(RepairProposalTaxonomy.isReviewCheckSource("review_check"));
        assertTrue(RepairProposalTaxonomy.isUserGoalSource("user_goal"));
        assertFalse(RepairProposalTaxonomy.isReviewCheckSource("user_goal"));
    }

    @Test
    void shouldNormalizeLegacyActionAliases() {
        assertEquals(RepairProposalTaxonomy.ActionType.REORDER_VOLUNTEERS,
                RepairProposalTaxonomy.normalizeActionType("sort_ordered_plan"));
        assertEquals(RepairProposalTaxonomy.ActionType.ADD_VOLUNTEERS,
                RepairProposalTaxonomy.normalizeActionType("add_units"));
        assertEquals(RepairProposalTaxonomy.ActionType.REMOVE_VOLUNTEERS,
                RepairProposalTaxonomy.normalizeActionType("remove_units"));
        assertEquals(RepairProposalTaxonomy.ActionType.REPLACE_VOLUNTEERS,
                RepairProposalTaxonomy.normalizeActionType("replace_units"));
    }

    @Test
    void shouldKeepApplyableAndPreviewOnlyStrategiesSeparate() {
        assertTrue(RepairProposalTaxonomy.isApplyableStrategy(RepairProposalTaxonomy.Strategy.FILL_MISSING_COUNT));
        assertTrue(RepairProposalTaxonomy.isApplyableStrategy(RepairProposalTaxonomy.Strategy.REPLACE_RISK_ITEMS));
        assertTrue(RepairProposalTaxonomy.isPreviewOnlyStrategy(RepairProposalTaxonomy.Strategy.REBALANCE_TIER_RATIO));
        assertTrue(RepairProposalTaxonomy.isPreviewOnlyStrategy(RepairProposalTaxonomy.Strategy.FILL_PROBABILITY_GAP));
        assertTrue(RepairProposalTaxonomy.isPreviewOnlyStrategy(RepairProposalTaxonomy.Strategy.ONLY_KEEP_SCOPE));
        assertTrue(RepairProposalTaxonomy.isPreviewOnlyStrategy(RepairProposalTaxonomy.Strategy.MUST_INCLUDE_SCOPE));
        assertTrue(RepairProposalTaxonomy.isPreviewOnlyStrategy(RepairProposalTaxonomy.Strategy.EXCLUDE_SCOPE));
        assertFalse(RepairProposalTaxonomy.isApplyableStrategy(RepairProposalTaxonomy.Strategy.REBALANCE_TIER_RATIO));
        assertFalse(RepairProposalTaxonomy.isApplyableStrategy(RepairProposalTaxonomy.Strategy.ADD_SAFETY_ITEMS));
        assertFalse(RepairProposalTaxonomy.isApplyableStrategy(RepairProposalTaxonomy.Strategy.ONLY_KEEP_SCOPE));
        assertFalse(RepairProposalTaxonomy.isApplyableStrategy(RepairProposalTaxonomy.Strategy.MUST_INCLUDE_SCOPE));
        assertFalse(RepairProposalTaxonomy.isApplyableStrategy(RepairProposalTaxonomy.Strategy.EXCLUDE_SCOPE));
    }

    @Test
    void shouldValidateStrategyActionMapping() {
        assertTrue(RepairProposalTaxonomy.actionAllowedForStrategy(
                RepairProposalTaxonomy.Strategy.REPLACE_RISK_ITEMS,
                RepairProposalTaxonomy.ActionType.REPLACE_VOLUNTEERS));
        assertTrue(RepairProposalTaxonomy.actionAllowedForStrategy(
                RepairProposalTaxonomy.Strategy.REMOVE_RISK_ITEMS,
                RepairProposalTaxonomy.ActionType.FILL_TOTAL_COUNT));
        assertFalse(RepairProposalTaxonomy.actionAllowedForStrategy(
                RepairProposalTaxonomy.Strategy.REBALANCE_TIER_RATIO,
                RepairProposalTaxonomy.ActionType.REMOVE_VOLUNTEERS));
        assertTrue(RepairProposalTaxonomy.actionAllowedForStrategy(
                RepairProposalTaxonomy.Strategy.EXCLUDE_SCOPE,
                RepairProposalTaxonomy.ActionType.REMOVE_VOLUNTEERS));
        assertFalse(RepairProposalTaxonomy.actionAllowedForStrategy(
                RepairProposalTaxonomy.Strategy.EXCLUDE_SCOPE,
                RepairProposalTaxonomy.ActionType.REORDER_VOLUNTEERS));
    }

    @Test
    void shouldMapCompensationActionToRepairStrategy() {
        assertEquals(RepairProposalTaxonomy.Strategy.FILL_MISSING_COUNT,
                RepairProposalTaxonomy.strategyForCompensationActionType(
                        RepairProposalTaxonomy.CompensationActionType.FILL_TOTAL_COUNT));
        assertEquals(RepairProposalTaxonomy.Strategy.REBALANCE_TIER_RATIO,
                RepairProposalTaxonomy.strategyForCompensationActionType(
                        RepairProposalTaxonomy.CompensationActionType.REBALANCE_PROTECT_RATIO));
        assertEquals(RepairProposalTaxonomy.CompensationActionType.REBALANCE_PROTECT_RATIO,
                RepairProposalTaxonomy.compensationActionTypeForStructuralStrategy(
                        RepairProposalTaxonomy.Strategy.REBALANCE_TIER_RATIO));
    }
}
