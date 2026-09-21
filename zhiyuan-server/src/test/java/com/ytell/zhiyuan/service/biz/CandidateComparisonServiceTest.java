package com.ytell.zhiyuan.service.biz;

import com.ytell.zhiyuan.common.exception.BusinessException;
import com.ytell.zhiyuan.model.dto.planning.CandidateComparisonDTO;
import com.ytell.zhiyuan.model.dto.planning.ComparisonCellDTO;
import com.ytell.zhiyuan.model.dto.planning.ComparisonEntityDTO;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import java.util.Arrays;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

public class CandidateComparisonServiceTest {

    private CandidateComparisonService service;

    @BeforeEach
    void setUp() {
        service = new CandidateComparisonService();
    }

    @Test
    void numericDimensionsAreUnavailableWhenScopesDiffer() {
        ComparisonEntityDTO left = entity("e1", 2025, "31", "本科批", "major", "percent");
        ComparisonEntityDTO right = entity("e2", 2026, "31", "本科批", "major", "percent");

        CandidateComparisonDTO result = service.compare(Arrays.asList(left, right), null);

        // 2025 的位次减 2026 的位次是一个方向不明的差——整列不可比，而不是逐格提示。
        assertTrue(result.getUnavailableDimensions().contains("planNum"));
        assertTrue(result.getUnavailableDimensions().contains("admissionRatio"));
        assertTrue(result.getUnavailableDimensions().contains("tuitionPerYear"));
        assertTrue(result.getLimitations().contains("comparison_scope_mismatch"));
        // 名称类维度不受口径影响，仍然可用。
        assertTrue(!result.getUnavailableDimensions().contains("cityName"));
    }

    @Test
    void sameScopeProducesRealValues() {
        ComparisonEntityDTO left = entity("e1", 2026, "31", "本科批", "major", "percent");
        ComparisonEntityDTO right = entity("e2", 2026, "31", "本科批", "major", "percent");

        CandidateComparisonDTO result = service.compare(Arrays.asList(left, right), null);

        assertTrue(result.getUnavailableDimensions().isEmpty());
        List<ComparisonCellDTO> ratioCells = cellsFor(result, "admissionRatio");
        assertEquals(2, ratioCells.size());
        assertEquals(45.0, ratioCells.get(0).getValue());
        assertEquals("percent", ratioCells.get(0).getUnit());
        // 每格自带来源：没有来源的格子无法被核对。
        assertEquals("entity.admissionRatio", ratioCells.get(0).getSource());
    }

    @Test
    void aMissingValueStaysNullAndSaysWhy() {
        ComparisonEntityDTO left = entity("e1", 2026, "31", "本科批", "major", "percent");
        ComparisonEntityDTO right = entity("e2", 2026, "31", "本科批", "major", "percent");
        right.setTuitionPerYear(null);

        CandidateComparisonDTO result = service.compare(Arrays.asList(left, right), null);

        ComparisonCellDTO cell = cellsFor(result, "tuitionPerYear").get(1);
        // 缺失补零之后"没有数据"看起来像"更便宜"——方向性错误。
        assertNull(cell.getValue());
        assertEquals("tuition_missing", cell.getUnavailableReason());
    }

    @Test
    void aMissingScopeFieldIsNotTreatedAsMatching() {
        ComparisonEntityDTO left = entity("e1", 2026, "31", "本科批", "major", "percent");
        ComparisonEntityDTO right = entity("e2", 2026, null, "本科批", "major", "percent");

        // "不知道口径是否相同"不等于"相同"。
        assertTrue(!CandidateComparisonService.comparable(left, right));
        CandidateComparisonDTO result = service.compare(Arrays.asList(left, right), null);
        assertTrue(result.getUnavailableDimensions().contains("admissionRatio"));
    }

    @Test
    void schoolLevelRateAndUnitLevelRateAreDifferentDimensions() {
        ComparisonEntityDTO left = entity("e1", 2026, "31", "本科批", "major", "percent");
        left.setSchoolEnrollRatio(72.0);
        left.setAdmissionRatio(45.0);
        ComparisonEntityDTO right = entity("e2", 2026, "31", "本科批", "major", "percent");

        CandidateComparisonDTO result = service.compare(Arrays.asList(left, right), null);

        // 学校口径与单元口径是两列、两来源；用学校率顶替单元率会让
        // "这个专业组有多难"变成一个用别的数据回答的问题。
        assertEquals(72.0, cellsFor(result, "schoolEnrollRatio").get(0).getValue());
        assertEquals(45.0, cellsFor(result, "admissionRatio").get(0).getValue());
        assertEquals("entity.schoolEnrollRatio", cellsFor(result, "schoolEnrollRatio").get(0).getSource());
    }

    @Test
    void fitScoreIsASeparateDimensionFromProbability() {
        ComparisonEntityDTO left = entity("e1", 2026, "31", "本科批", "major", "percent");
        left.setFinalScore(88.5);
        ComparisonEntityDTO right = entity("e2", 2026, "31", "本科批", "major", "percent");

        CandidateComparisonDTO result = service.compare(Arrays.asList(left, right), null);

        // 匹配分与概率是两个维度、两个单位。合成一个字段会让"这所学校适合我"
        // 被读成"我大概率能上"——那是两个完全不同的问题。
        assertEquals("score", cellsFor(result, "finalScore").get(0).getUnit());
        assertEquals("percent", cellsFor(result, "admissionRatio").get(0).getUnit());
        assertEquals(88.5, cellsFor(result, "finalScore").get(0).getValue());
        assertEquals("entity.finalScore", cellsFor(result, "finalScore").get(0).getSource());
    }

    @Test
    void entityCountAndDimensionsAreBounded() {
        ComparisonEntityDTO e1 = entity("e1", 2026, "31", "本科批", "major", "percent");

        assertEquals(400, assertThrows(BusinessException.class,
                () -> service.compare(Arrays.asList(e1), null)).getStatus());
        assertEquals(400, assertThrows(BusinessException.class,
                () -> service.compare(Arrays.asList(e1, e1, e1, e1, e1, e1), null)).getStatus());
        assertEquals(400, assertThrows(BusinessException.class,
                () -> service.compare(Arrays.asList(e1, e1), Arrays.asList("secretField"))).getStatus());
    }

    private static List<ComparisonCellDTO> cellsFor(CandidateComparisonDTO result, String dimension) {
        List<ComparisonCellDTO> matched = new java.util.ArrayList<ComparisonCellDTO>();
        for (ComparisonCellDTO cell : result.getCells()) {
            if (dimension.equals(cell.getDimension())) {
                matched.add(cell);
            }
        }
        return matched;
    }

    private static ComparisonEntityDTO entity(String id, Integer year, String areaId, String batch,
                                              String mode, String rateUnit) {
        ComparisonEntityDTO entity = new ComparisonEntityDTO();
        entity.setEntityId(id);
        entity.setSchoolId("s-" + id);
        entity.setSchoolName("学校" + id);
        entity.setMajorId("m-" + id);
        entity.setCityName("杭州");
        entity.setAdmissionYear(year);
        entity.setAreaId(areaId);
        entity.setBatch(batch);
        entity.setAdmissionMode(mode);
        entity.setRateUnit(rateUnit);
        entity.setAdmissionRatio(45.0);
        entity.setFinalScore(80.0);
        entity.setPlanNum(20);
        entity.setTuitionPerYear(6000);
        return entity;
    }
}
