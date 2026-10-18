package com.ytell.zhiyuan.service.biz;

import com.google.common.collect.Lists;
import com.ytell.zhiyuan.model.dto.planning.EvaluationContextDTO;
import com.ytell.zhiyuan.model.dto.planning.EvaluationEntryRefDTO;
import com.ytell.zhiyuan.model.dto.planning.StructureVectorDTO;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;

class PlanStructureEvaluatorTest {

    @Test
    void countsUnitsItemsTiersSafetyTuitionAndFlags() {
        EvaluationContextDTO context = new EvaluationContextDTO();
        context.setSourceProvince("浙江");
        context.setEntries(Lists.newArrayList(
                entry("unit", "保", "浙江", 65000, Lists.newArrayList("cooperative_program"), 0.5D),
                entry("unit", "保", "江苏", 30000, Lists.newArrayList(), 0.7D),
                entry("volunteer", "稳", "浙江", 30000, Lists.newArrayList("special_enrollment"), 0.6D)));

        StructureVectorDTO structure = PlanStructureEvaluator.build(context);

        assertEquals(2, structure.getUnitCount());
        assertEquals(1, structure.getItemCount());
        assertEquals(Integer.valueOf(2), structure.getUnitTierCounts().get("保"));
        assertEquals(Integer.valueOf(1), structure.getTierCounts().get("稳"));
        assertEquals(1, structure.getLocalSafetyUnitCount());
        // 统一用户可见 20k 口径后，65000/30000 均计入。
        assertEquals(3, structure.getHighTuitionCount());
        assertEquals(1, structure.getCooperativeCount());
        assertEquals(1, structure.getSpecialEnrollmentCount());
        assertEquals(0.2D, structure.getAdjacentRatioDeltaMax(), 1e-9D);
    }

    @Test
    void countsHighTuitionOnlyAboveUserFacingThreshold() {
        EvaluationContextDTO context = new EvaluationContextDTO();
        context.setEntries(Lists.newArrayList(
                entry("unit", "稳", "浙江", 20000, Lists.newArrayList(), 0.5D),
                entry("unit", "稳", "浙江", 20001, Lists.newArrayList(), 0.6D)));

        StructureVectorDTO structure = PlanStructureEvaluator.build(context);

        assertEquals(1, structure.getHighTuitionCount());
    }

    private EvaluationEntryRefDTO entry(String level, String tier, String province,
                                        Integer tuition, java.util.List<String> flags,
                                        Double ratio) {
        EvaluationEntryRefDTO entry = new EvaluationEntryRefDTO();
        entry.setLevel(level);
        entry.setPathTier(tier);
        entry.setProvinceName(province);
        entry.setTuitionPerYear(tuition);
        entry.setRiskFlags(flags);
        entry.setMajorRatio(ratio);
        return entry;
    }
}
