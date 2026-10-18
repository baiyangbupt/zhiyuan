package com.ytell.zhiyuan.service.biz;

import com.ytell.zhiyuan.model.dto.planning.CandidateFactDTO;
import org.junit.jupiter.api.Test;

import java.util.Arrays;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

class CandidateUtilityScorerTest {

    @Test
    void missingComponentsScoreZeroAndDoNotBeatKnownCandidates() {
        CandidateFactDTO high = fact("high", 90D, 90D, 80D, 80D, 5000);
        CandidateFactDTO low = fact("low", 40D, 40D, 20D, 20D, 18000);
        CandidateFactDTO unknown = fact("unknown", null, null, null, null, null);

        CandidateUtilityScorer.scoreAll(Arrays.asList(high, low, unknown));

        assertTrue(high.getUtilityScore() > low.getUtilityScore());
        assertTrue(low.getUtilityScore() > unknown.getUtilityScore());
        assertEquals(0, unknown.getUtilityScore());
        assertEquals(0, unknown.getUtilityCoverage());
        assertEquals(0, unknown.getUtilityComponents().get("preference"));
        assertEquals(0, unknown.getUtilityComponents().get("cost"));
        assertEquals(100, high.getUtilityCoverage());
    }

    @Test
    void percentileIsDeterministicForTies() {
        CandidateFactDTO first = fact("a", 60D, 60D, 50D, 60D, 10000);
        CandidateFactDTO second = fact("b", 60D, 60D, 50D, 60D, 10000);

        CandidateUtilityScorer.scoreAll(Arrays.asList(first, second));

        assertEquals(first.getUtilityScore(), second.getUtilityScore());
        assertEquals(first.getUtilityComponents(), second.getUtilityComponents());
        // 两个并列值的中位秩是 75，而不是 0 或 100。
        assertEquals(75, first.getUtilityComponents().get("preference"));
    }

    @Test
    void safetyUsesWithinTierPercentile() {
        CandidateFactDTO sprintLow = fact("sprint-low", 90D, 90D, 20D, 80D, 5000);
        sprintLow.setTier("sprint");
        CandidateFactDTO sprintHigh = fact("sprint-high", 90D, 90D, 80D, 80D, 5000);
        sprintHigh.setTier("sprint");
        CandidateFactDTO protectHigh = fact("protect-high", 90D, 90D, 80D, 80D, 5000);
        protectHigh.setTier("protect");

        CandidateUtilityScorer.scoreAll(Arrays.asList(sprintLow, sprintHigh, protectHigh));

        assertTrue(sprintHigh.getUtilityComponents().get("safety")
                > sprintLow.getUtilityComponents().get("safety"));
        // 单独一个保档值没有同档分布，按中性 50 处理。
        assertEquals(50, protectHigh.getUtilityComponents().get("safety"));
    }

    @Test
    void costIsConservativeForUnknownTuitionAndRewardsLowTuition() {
        CandidateFactDTO cheap = fact("cheap", 80D, 80D, 50D, 80D, 0);
        CandidateFactDTO expensive = fact("expensive", 80D, 80D, 50D, 80D, 90000);
        CandidateFactDTO unknown = fact("unknown", 80D, 80D, 50D, 80D, null);

        CandidateUtilityScorer.scoreAll(Arrays.asList(cheap, expensive, unknown));

        assertEquals(100, cheap.getUtilityComponents().get("cost"));
        assertEquals(10, expensive.getUtilityComponents().get("cost"));
        assertEquals(0, unknown.getUtilityComponents().get("cost"));
    }

    private CandidateFactDTO fact(String id,
                                  Double intent,
                                  Double finalScore,
                                  Double admissionRatio,
                                  Double future,
                                  Integer tuition) {
        CandidateFactDTO fact = new CandidateFactDTO();
        fact.setEntityId(id);
        fact.setEligible(true);
        fact.setTier("stable");
        fact.setIntentScore(intent);
        fact.setFinalScore(finalScore);
        fact.setAdmissionRatio(admissionRatio);
        fact.setFutureDevelopmentScore(future);
        fact.setTuitionPerYear(tuition);
        return fact;
    }
}
