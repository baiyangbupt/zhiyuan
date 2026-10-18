package com.ytell.zhiyuan.service.biz;

import com.ytell.zhiyuan.model.dto.planning.AdmissionInterpretationReq;
import com.ytell.zhiyuan.model.dto.planning.AdmissionInterpretationRes;
import com.ytell.zhiyuan.model.dto.planning.EvaluationEntryRefDTO;
import com.ytell.zhiyuan.model.dto.planning.EvaluationFindingDTO;
import com.ytell.zhiyuan.model.dto.planning.InterpretationEntryDTO;
import com.ytell.zhiyuan.model.dto.planning.LandingScenarioDTO;
import org.junit.jupiter.api.Test;

import java.util.ArrayList;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * J2a：结构/条件情景真值表 + 反事实 remove-only。
 *
 * <p>本测试刻意**不**断言 likelihood/slipRisk；结构覆盖与数据完整度分开。
 */
public class PlanAdmissionInterpretationServiceTest {

    private final PlanAdmissionInterpretationService service = new PlanAdmissionInterpretationService();

    @Test
    void normalGradientDescribesStructureWithoutPrediction() {
        List<InterpretationEntryDTO> entries = new ArrayList<InterpretationEntryDTO>();
        for (int i = 1; i <= 13; i++) {
            entries.add(entry(i, InterpretationEntryDTO.TIER_CHONG, 1.0 + i));
        }
        for (int i = 14; i <= 26; i++) {
            entries.add(entry(i, InterpretationEntryDTO.TIER_WEN, 50.0 + (i - 13)));
        }
        for (int i = 27; i <= 45; i++) {
            entries.add(entry(i, InterpretationEntryDTO.TIER_BAO, 74.0 + (i - 26)));
        }

        AdmissionInterpretationRes res = interpret(entries);

        assertEquals(AdmissionInterpretationRes.STATUS_COMPLETED, res.getStatus());
        assertEquals(14, res.getBaseLanding().getLandingEntry().getPosition());
        assertEquals(LandingScenarioDTO.STRUCTURE_FIRST_STABLE,
                res.getBaseLanding().getStructureStatus());
        assertEquals(13, scenario(res, LandingScenarioDTO.LABEL_UPSIDE).getLandingEntry().getPosition());
        assertEquals(LandingScenarioDTO.STRUCTURE_BEST_REACH,
                scenario(res, LandingScenarioDTO.LABEL_UPSIDE).getStructureStatus());
        assertEquals(45, scenario(res, LandingScenarioDTO.LABEL_DOWNSIDE).getLandingEntry().getPosition());
        assertEquals(LandingScenarioDTO.STRUCTURE_LAST_SAFE,
                scenario(res, LandingScenarioDTO.LABEL_DOWNSIDE).getStructureStatus());
        assertEquals(AdmissionInterpretationRes.SAFETY_HAS_COVER, res.getSafetyCoverage());
        assertNull(scenario(res, LandingScenarioDTO.LABEL_NO_SAFE));
        assertFalse(res.getOrderAnomaly());
        assertEquals(1.0, res.getDataCompleteness(), 0.0001);
        assertEquals(AdmissionInterpretationRes.COMPLETENESS_FULL, res.getDataCompletenessBand());
    }

    @Test
    void noSafeIsStructuralGapNotRiskVerdict() {
        AdmissionInterpretationRes res = interpret(entries(
                entry(1, InterpretationEntryDTO.TIER_CHONG, 30.0),
                entry(2, InterpretationEntryDTO.TIER_WEN, 55.0),
                entry(3, InterpretationEntryDTO.TIER_WEN, 60.0)));

        assertEquals(2, res.getBaseLanding().getLandingEntry().getPosition());
        assertEquals(1, scenario(res, LandingScenarioDTO.LABEL_UPSIDE).getLandingEntry().getPosition());
        assertNull(scenario(res, LandingScenarioDTO.LABEL_DOWNSIDE));
        assertEquals(AdmissionInterpretationRes.SAFETY_NO_COVER, res.getSafetyCoverage());
        LandingScenarioDTO noSafe = scenario(res, LandingScenarioDTO.LABEL_NO_SAFE);
        assertNotNull(noSafe);
        assertEquals(LandingScenarioDTO.STRUCTURE_NO_SAFE, noSafe.getStructureStatus());
    }

    @Test
    void allReachHasNoBaseOrDownside() {
        AdmissionInterpretationRes res = interpret(entries(
                entry(1, InterpretationEntryDTO.TIER_CHONG, 10.0),
                entry(2, InterpretationEntryDTO.TIER_CHONG, 40.0)));

        assertNull(res.getBaseLanding());
        assertEquals(2, scenario(res, LandingScenarioDTO.LABEL_UPSIDE).getLandingEntry().getPosition());
        assertNull(scenario(res, LandingScenarioDTO.LABEL_DOWNSIDE));
        assertEquals(AdmissionInterpretationRes.SAFETY_NO_COVER, res.getSafetyCoverage());
        assertNotNull(scenario(res, LandingScenarioDTO.LABEL_NO_SAFE));
    }

    @Test
    void allSafeHasNoUpside() {
        AdmissionInterpretationRes res = interpret(entries(
                entry(1, InterpretationEntryDTO.TIER_BAO, 75.0),
                entry(2, InterpretationEntryDTO.TIER_BAO, 90.0)));

        assertEquals(1, res.getBaseLanding().getLandingEntry().getPosition());
        assertNull(scenario(res, LandingScenarioDTO.LABEL_UPSIDE));
        assertEquals(2, scenario(res, LandingScenarioDTO.LABEL_DOWNSIDE).getLandingEntry().getPosition());
        assertEquals(AdmissionInterpretationRes.SAFETY_HAS_COVER, res.getSafetyCoverage());
        assertNull(scenario(res, LandingScenarioDTO.LABEL_NO_SAFE));
    }

    @Test
    void safeBeforeStableIsOrderAnomaly() {
        AdmissionInterpretationRes res = interpret(entries(
                entry(1, InterpretationEntryDTO.TIER_BAO, 90.0),
                entry(2, InterpretationEntryDTO.TIER_CHONG, 30.0),
                entry(3, InterpretationEntryDTO.TIER_WEN, 55.0)));

        assertEquals(1, res.getBaseLanding().getLandingEntry().getPosition());
        assertEquals(2, scenario(res, LandingScenarioDTO.LABEL_UPSIDE).getLandingEntry().getPosition());
        assertEquals(1, scenario(res, LandingScenarioDTO.LABEL_DOWNSIDE).getLandingEntry().getPosition());
        assertEquals(AdmissionInterpretationRes.SAFETY_HAS_COVER, res.getSafetyCoverage());
        assertTrue(res.getOrderAnomaly());
    }

    @Test
    void missingLastSafeRatioIsDataGapNotRisk() {
        AdmissionInterpretationRes res = interpret(entries(
                entry(1, InterpretationEntryDTO.TIER_CHONG, 30.0),
                entry(2, InterpretationEntryDTO.TIER_WEN, 55.0),
                entry(3, InterpretationEntryDTO.TIER_BAO, null)));

        assertEquals(2, res.getBaseLanding().getLandingEntry().getPosition());
        assertEquals(AdmissionInterpretationRes.SAFETY_HAS_COVER_DATA_GAP, res.getSafetyCoverage());
        assertEquals(2.0 / 3.0, res.getRatioCoverage(), 0.0001);
        assertEquals(AdmissionInterpretationRes.COMPLETENESS_PARTIAL, res.getDataCompletenessBand());
        assertNull(scenario(res, LandingScenarioDTO.LABEL_NO_SAFE));
    }

    @Test
    void allRatiosMissingStillDescribesTierStructure() {
        AdmissionInterpretationRes res = interpret(entries(
                entry(1, InterpretationEntryDTO.TIER_CHONG, null),
                entry(2, InterpretationEntryDTO.TIER_WEN, null),
                entry(3, InterpretationEntryDTO.TIER_BAO, null)));

        assertEquals(2, res.getBaseLanding().getLandingEntry().getPosition());
        assertEquals(LandingScenarioDTO.STRUCTURE_BEST_REACH,
                scenario(res, LandingScenarioDTO.LABEL_UPSIDE).getStructureStatus());
        assertEquals(LandingScenarioDTO.STRUCTURE_LAST_SAFE,
                scenario(res, LandingScenarioDTO.LABEL_DOWNSIDE).getStructureStatus());
        assertEquals(AdmissionInterpretationRes.SAFETY_HAS_COVER_DATA_GAP, res.getSafetyCoverage());
        assertEquals(0.0, res.getRatioCoverage(), 0.0001);
        assertEquals(AdmissionInterpretationRes.COMPLETENESS_SEVERE, res.getDataCompletenessBand());
    }

    @Test
    void allUnknownTierHasNoStructureScenario() {
        AdmissionInterpretationRes res = interpret(entries(
                entry(1, InterpretationEntryDTO.TIER_UNKNOWN, 50.0),
                entry(2, InterpretationEntryDTO.TIER_UNKNOWN, 60.0)));

        assertNull(res.getBaseLanding());
        assertNull(scenario(res, LandingScenarioDTO.LABEL_UPSIDE));
        assertNull(scenario(res, LandingScenarioDTO.LABEL_DOWNSIDE));
        assertEquals(AdmissionInterpretationRes.SAFETY_UNKNOWN, res.getSafetyCoverage());
        LandingScenarioDTO noSafe = scenario(res, LandingScenarioDTO.LABEL_NO_SAFE);
        assertNotNull(noSafe);
        assertEquals(LandingScenarioDTO.STRUCTURE_UNKNOWN, noSafe.getStructureStatus());
        assertEquals(AdmissionInterpretationRes.COMPLETENESS_SEVERE, res.getDataCompletenessBand());
    }

    @Test
    void emptyPlanIsNoPlan() {
        AdmissionInterpretationRes res = interpret(new ArrayList<InterpretationEntryDTO>());

        assertEquals(AdmissionInterpretationRes.STATUS_NO_PLAN, res.getStatus());
        assertTrue(res.getScenarios().isEmpty());
        assertEquals(AdmissionInterpretationRes.SAFETY_UNKNOWN, res.getSafetyCoverage());
        assertEquals(AdmissionInterpretationRes.COMPLETENESS_SEVERE, res.getDataCompletenessBand());
    }

    @Test
    void majorModeJoinMissingIsDataGapNotStructureChange() {
        InterpretationEntryDTO reach = entry(1, InterpretationEntryDTO.TIER_CHONG, null);
        reach.setLevel(InterpretationEntryDTO.LEVEL_VOLUNTEER);
        InterpretationEntryDTO stable = entry(2, InterpretationEntryDTO.TIER_WEN, null);
        stable.setLevel(InterpretationEntryDTO.LEVEL_VOLUNTEER);
        InterpretationEntryDTO safe = entry(3, InterpretationEntryDTO.TIER_BAO, null);
        safe.setLevel(InterpretationEntryDTO.LEVEL_VOLUNTEER);

        AdmissionInterpretationRes res = interpret(entries(reach, stable, safe));

        assertEquals(2, res.getBaseLanding().getLandingEntry().getPosition());
        assertEquals(3, scenario(res, LandingScenarioDTO.LABEL_DOWNSIDE).getLandingEntry().getPosition());
        assertEquals(AdmissionInterpretationRes.SAFETY_HAS_COVER_DATA_GAP, res.getSafetyCoverage());
        assertEquals(AdmissionInterpretationRes.COMPLETENESS_SEVERE, res.getDataCompletenessBand());
    }

    @Test
    void twoSafeOneRatioMissingIsDataGapNotRisk() {
        AdmissionInterpretationRes res = interpret(entries(
                entry(1, InterpretationEntryDTO.TIER_CHONG, 30.0),
                entry(2, InterpretationEntryDTO.TIER_WEN, 55.0),
                entry(3, InterpretationEntryDTO.TIER_BAO, null),
                entry(4, InterpretationEntryDTO.TIER_BAO, 90.0)));

        assertEquals(4, scenario(res, LandingScenarioDTO.LABEL_DOWNSIDE).getLandingEntry().getPosition());
        assertEquals(AdmissionInterpretationRes.SAFETY_HAS_COVER, res.getSafetyCoverage());
        assertEquals(AdmissionInterpretationRes.COMPLETENESS_PARTIAL, res.getDataCompletenessBand());
    }

    @Test
    void singleSafeIsStructurallyCovered() {
        AdmissionInterpretationRes res = interpret(entries(
                entry(1, InterpretationEntryDTO.TIER_CHONG, 30.0),
                entry(2, InterpretationEntryDTO.TIER_WEN, 55.0),
                entry(3, InterpretationEntryDTO.TIER_BAO, 80.0)));

        assertEquals(AdmissionInterpretationRes.SAFETY_HAS_COVER, res.getSafetyCoverage());
        assertEquals(AdmissionInterpretationRes.COMPLETENESS_FULL, res.getDataCompletenessBand());
    }

    @Test
    void twoSafeAllKnownIsStructurallyCovered() {
        AdmissionInterpretationRes res = interpret(entries(
                entry(1, InterpretationEntryDTO.TIER_CHONG, 30.0),
                entry(2, InterpretationEntryDTO.TIER_WEN, 55.0),
                entry(3, InterpretationEntryDTO.TIER_BAO, 80.0),
                entry(4, InterpretationEntryDTO.TIER_BAO, 90.0)));

        assertEquals(AdmissionInterpretationRes.SAFETY_HAS_COVER, res.getSafetyCoverage());
        assertEquals(AdmissionInterpretationRes.COMPLETENESS_FULL, res.getDataCompletenessBand());
    }

    @Test
    void removeCounterfactualCanRemoveAllSafetyCoverage() {
        List<InterpretationEntryDTO> entries = entries(
                entry(1, InterpretationEntryDTO.TIER_CHONG, 30.0),
                entry(2, InterpretationEntryDTO.TIER_WEN, 55.0),
                entry(3, InterpretationEntryDTO.TIER_BAO, 80.0),
                entry(4, InterpretationEntryDTO.TIER_BAO, 90.0));
        AdmissionInterpretationReq req = new AdmissionInterpretationReq();
        req.setPlanVersion(7);
        req.setAdmissionMode("major_group");
        AdmissionInterpretationReq.CounterfactualDTO counterfactual =
                new AdmissionInterpretationReq.CounterfactualDTO();
        counterfactual.getRemoveEntryRefs().add(ref("u3"));
        counterfactual.getRemoveEntryRefs().add(ref("u4"));
        req.setCounterfactual(counterfactual);

        AdmissionInterpretationRes res = service.interpret(req, entries);

        assertEquals(AdmissionInterpretationRes.SAFETY_NO_COVER, res.getSafetyCoverage());
        assertNull(scenario(res, LandingScenarioDTO.LABEL_DOWNSIDE));
        assertNotNull(scenario(res, LandingScenarioDTO.LABEL_NO_SAFE));
    }

    @Test
    void scenariosDoNotFabricateComputedEvidenceOrPredictions() {
        AdmissionInterpretationRes res = interpret(entries(
                entry(1, InterpretationEntryDTO.TIER_CHONG, 30.0),
                entry(2, InterpretationEntryDTO.TIER_WEN, 55.0),
                entry(3, InterpretationEntryDTO.TIER_BAO, 80.0)));

        for (LandingScenarioDTO scenario : res.getScenarios()) {
            assertTrue(scenario.getEvidenceRefs().isEmpty());
            assertNotNull(scenario.getStructureStatus());
            assertNotNull(scenario.getCondition());
        }
        assertTrue(res.getCaveats().contains(
                "这是方案结构与条件情景说明，不是录取预测；数据不足不等于风险高或低。"));
    }

    @Test
    void findingsEnrichDriversAndCaveatsWithoutProbability() {
        List<InterpretationEntryDTO> entries = new ArrayList<InterpretationEntryDTO>();
        for (int i = 1; i <= 13; i++) {
            entries.add(entry(i, InterpretationEntryDTO.TIER_CHONG, 1.0 + i));
        }
        for (int i = 14; i <= 26; i++) {
            entries.add(entry(i, InterpretationEntryDTO.TIER_WEN, 50.0 + (i - 13)));
        }
        for (int i = 27; i <= 45; i++) {
            entries.add(entry(i, InterpretationEntryDTO.TIER_BAO, 74.0 + (i - 26)));
        }
        EvaluationFindingDTO hard = new EvaluationFindingDTO();
        hard.setCode("safety_guard");
        hard.setLayer("hard");
        hard.setRuleStrength("hard");
        hard.setResultStatus("fail");
        hard.setDisplaySeverity("block");
        hard.setSummary("本省保底不足");
        EvaluationEntryRefDTO ref = new EvaluationEntryRefDTO();
        ref.setLevel("unit");
        ref.setId("u14");
        hard.getAffectedEntryRefs().add(ref);
        EvaluationFindingDTO passed = new EvaluationFindingDTO();
        passed.setCode("ratio_distribution");
        passed.setResultStatus("pass");
        passed.getAffectedEntryRefs().add(ref);

        AdmissionInterpretationReq req = new AdmissionInterpretationReq();
        req.setPlanVersion(7);
        req.setAdmissionMode("major_group");
        AdmissionInterpretationRes res = service.interpret(
                req, entries, java.util.Arrays.asList(hard, passed));

        assertTrue(res.getBaseLanding().getDrivers().stream()
                .anyMatch(line -> line.contains("审查：本省保底不足")));
        assertTrue(res.getCaveats().stream()
                .anyMatch(line -> line.contains("审查：本省保底不足")));
        assertFalse(res.getCaveats().stream().anyMatch(line -> line.contains("比例")));
        assertFalse(res.getCaveats().stream().anyMatch(line -> line.contains("概率")));
    }

    private AdmissionInterpretationRes interpret(List<InterpretationEntryDTO> entries) {
        AdmissionInterpretationReq req = new AdmissionInterpretationReq();
        req.setPlanVersion(7);
        req.setAdmissionMode("major_group");
        return service.interpret(req, entries);
    }

    private AdmissionInterpretationReq.EntryRefDTO ref(String id) {
        AdmissionInterpretationReq.EntryRefDTO ref = new AdmissionInterpretationReq.EntryRefDTO();
        ref.setLevel(InterpretationEntryDTO.LEVEL_UNIT);
        ref.setId(id);
        return ref;
    }

    private List<InterpretationEntryDTO> entries(InterpretationEntryDTO... items) {
        List<InterpretationEntryDTO> result = new ArrayList<InterpretationEntryDTO>();
        for (InterpretationEntryDTO item : items) {
            result.add(item);
        }
        return result;
    }

    private InterpretationEntryDTO entry(int position, String tier, Double ratio) {
        InterpretationEntryDTO entry = new InterpretationEntryDTO();
        entry.setLevel(InterpretationEntryDTO.LEVEL_UNIT);
        entry.setId("u" + position);
        entry.setPosition(position);
        entry.setSchoolName("S" + position);
        entry.setMajorName("M" + position);
        entry.setPathTier(tier);
        entry.setSchoolRatio(ratio);
        return entry;
    }

    private LandingScenarioDTO scenario(AdmissionInterpretationRes res, String label) {
        for (LandingScenarioDTO scenario : res.getScenarios()) {
            if (label.equals(scenario.getLabel())) {
                assertNotNull(scenario);
                return scenario;
            }
        }
        return null;
    }
}
