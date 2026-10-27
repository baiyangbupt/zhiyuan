package com.ytell.zhiyuan.service.biz;

import com.ytell.zhiyuan.common.util.ExcelUtil;
import com.ytell.zhiyuan.model.dto.CreateSessionReq;
import com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedItemDTO;
import com.ytell.zhiyuan.model.dto.planning.OrderedUnitDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningUnitMajorDTO;
import org.junit.jupiter.api.Test;

import java.util.Arrays;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

public class PlanningExcelExportBuilderTest {

    private final PlanningExcelExportBuilder builder = new PlanningExcelExportBuilder();

    @Test
    void shouldBuildMajorSchoolExportRowsPerOrderedMajor() {
        PlanningStateDTO state = new PlanningStateDTO();
        state.getCandidatePoolState().setVolunteerModel("major");

        CandidateItemDTO candidateA = buildCandidate("v1", "s1", "1001", "学校A", "计算机科学与技术", "080901", 12, 8500, "4年", 52d);
        CandidateItemDTO candidateB = buildCandidate("v2", "s1", "1001", "学校A", "软件工程", "080902", 8, 9000, "4年", 49d);
        CandidateItemDTO candidateC = buildCandidate("v3", "s2", "1002", "学校B", "电子信息工程", "080701", 6, 7800, "4年", 68d);
        state.getCandidatePoolState().setItems(Arrays.asList(candidateA, candidateB, candidateC));

        state.getOrderedPlanState().setItems(Arrays.asList(
                buildOrderedItem(1, "v1", "冲", "学校A", "计算机科学与技术"),
                buildOrderedItem(2, "v2", "冲", "学校A", "软件工程"),
                buildOrderedItem(3, "v3", "稳", "学校B", "电子信息工程")
        ));

        PlanningExcelExportBuilder.PlanningExportData exportData = builder.build(state, new CreateSessionReq());

        assertFalse(exportData.isMajorGroupMode());
        assertEquals(3, exportData.getMainList().size());

        ExcelUtil.VolunteerExcelData first = exportData.getMainList().get(0);
        assertEquals(Integer.valueOf(1), first.getIndex());
        assertEquals("1001", first.getSchoolCode());
        assertEquals("学校A", first.getSchoolName());
        assertEquals(1, first.getMajorList().size());
        assertEquals("080901", first.getMajorList().get(0).getMajorCode());

        ExcelUtil.VolunteerExcelData second = exportData.getMainList().get(1);
        assertEquals(Integer.valueOf(2), second.getIndex());
        assertEquals("1001", second.getSchoolCode());
        assertEquals(1, second.getMajorList().size());
        assertEquals("080902", second.getMajorList().get(0).getMajorCode());

        ExcelUtil.VolunteerExcelData third = exportData.getMainList().get(2);
        assertEquals(Integer.valueOf(3), third.getIndex());
        assertEquals("1002", third.getSchoolCode());
        assertEquals(1, third.getMajorList().size());
        assertEquals("080701", third.getMajorList().get(0).getMajorCode());
    }

    @Test
    void exportCarriesSpecialPlanConflictWarning() {
        PlanningStateDTO state = new PlanningStateDTO();
        state.getCandidatePoolState().setVolunteerModel("major");
        state.getCandidatePoolState().setSpecialPlan(false);
        CandidateItemDTO candidate = buildCandidate("v1", "s1", "1001", "学校A", "计算机（国家专项）",
                "080901", 12, 8500, "4年", 52d);
        candidate.setMajorPlanTags(Arrays.asList("国家专项"));
        state.getCandidatePoolState().setItems(Arrays.asList(candidate));
        state.getOrderedPlanState().setItems(Arrays.asList(
                buildOrderedItem(1, "v1", "冲", "学校A", "计算机（国家专项）")));

        PlanningExcelExportBuilder.PlanningExportData exportData = builder.build(state, new CreateSessionReq());

        assertTrue(exportData.getNote().contains("专项资格冲突"));
        assertTrue(exportData.getNote().contains("不能作为正式可报方案"));
    }

    @Test
    void shouldRenumberMajorGroupExportRowsContinuously() {
        PlanningStateDTO state = new PlanningStateDTO();
        state.getCandidatePoolState().setVolunteerModel("majorGroup");
        CandidateItemDTO candidateA = buildCandidate("g1m1", "s1", "2001", "专业组A", "专业A1", "080901", 10, 8000, "4年", 61d);
        CandidateItemDTO candidateB = buildCandidate("g2m1", "s2", "2002", "专业组B", "专业B1", "080701", 6, 7600, "4年", 79d);
        state.getCandidatePoolState().setItems(Arrays.asList(candidateA, candidateB));

        OrderedUnitDTO firstUnit = new OrderedUnitDTO();
        firstUnit.setPosition(1);
        firstUnit.setUnitId("ps1");
        firstUnit.setTier("冲");
        firstUnit.setSchoolName("专业组A");
        firstUnit.setMajorItems(Arrays.asList(buildUnitMajor("g1m1", "080901", "专业A1")));

        OrderedUnitDTO secondUnit = new OrderedUnitDTO();
        secondUnit.setPosition(3);
        secondUnit.setUnitId("ps2");
        secondUnit.setTier("稳");
        secondUnit.setSchoolName("专业组B");
        secondUnit.setMajorItems(Arrays.asList(buildUnitMajor("g2m1", "080701", "专业B1")));
        state.getOrderedPlanState().setUnits(Arrays.asList(firstUnit, secondUnit));
        state.getOrderedPlanState().setItems(Arrays.asList(
                buildOrderedItem(1, "g1m1", "冲", "专业组A", "专业A1"),
                buildOrderedItem(3, "g2m1", "稳", "专业组B", "专业B1")
        ));

        PlanningExcelExportBuilder.PlanningExportData exportData = builder.build(state, new CreateSessionReq());

        assertEquals(Integer.valueOf(1), exportData.getMainList().get(0).getIndex());
        assertEquals(Integer.valueOf(2), exportData.getMainList().get(1).getIndex());
    }

    @Test
    void shouldBuildMajorGroupExportRowsFromOrderedUnits() {
        PlanningStateDTO state = new PlanningStateDTO();
        state.getCandidatePoolState().setVolunteerModel("majorGroup");

        CandidateItemDTO candidateA = buildCandidate("g1m1", "s1", "2001", "专业组A", "专业A1", "080901", 10, 8000, "4年", 61d);
        CandidateItemDTO candidateB = buildCandidate("g1m2", "s1", "2001", "专业组A", "专业A2", "080902", 8, 8200, "4年", 54d);
        CandidateItemDTO candidateC = buildCandidate("g2m1", "s2", "2002", "专业组B", "专业B1", "080701", 6, 7600, "4年", 79d);
        state.getCandidatePoolState().setItems(Arrays.asList(candidateA, candidateB, candidateC));

        OrderedUnitDTO firstUnit = new OrderedUnitDTO();
        firstUnit.setPosition(1);
        firstUnit.setUnitId("ps1");
        firstUnit.setTier("冲");
        firstUnit.setSchoolName("专业组A");
        firstUnit.setSchoolEnrollRatio(45d);
        firstUnit.setMajorItems(Arrays.asList(
                buildUnitMajor("g1m2", "080902", "专业A2"),
                buildUnitMajor("g1m1", "080901", "专业A1")
        ));

        OrderedUnitDTO secondUnit = new OrderedUnitDTO();
        secondUnit.setPosition(2);
        secondUnit.setUnitId("ps2");
        secondUnit.setTier("稳");
        secondUnit.setSchoolName("专业组B");
        secondUnit.setSchoolEnrollRatio(70d);
        secondUnit.setMajorItems(Arrays.asList(buildUnitMajor("g2m1", "080701", "专业B1")));
        state.getOrderedPlanState().setUnits(Arrays.asList(firstUnit, secondUnit));
        state.getOrderedPlanState().setItems(Arrays.asList(
                buildOrderedItem(1, "g1m1", "冲", "专业组A", "专业A1"),
                buildOrderedItem(1, "g1m2", "冲", "专业组A", "专业A2"),
                buildOrderedItem(2, "g2m1", "稳", "专业组B", "专业B1")
        ));

        PlanningExcelExportBuilder.PlanningExportData exportData = builder.build(state, new CreateSessionReq());

        assertTrue(exportData.isMajorGroupMode());
        assertEquals(2, exportData.getMainList().size());

        ExcelUtil.VolunteerExcelData first = exportData.getMainList().get(0);
        assertEquals(Integer.valueOf(1), first.getIndex());
        assertEquals("2001", first.getSchoolCode());
        assertEquals("专业组A", first.getSchoolName());
        assertEquals(2, first.getMajorList().size());
        assertEquals("54%", first.getMajorList().get(0).getMajorEnrollRatio());
        assertEquals("61%", first.getMajorList().get(1).getMajorEnrollRatio());
        assertEquals("080902", first.getMajorList().get(0).getMajorCode());
        assertEquals("080901", first.getMajorList().get(1).getMajorCode());
    }

    @Test
    void shouldResolveLegacyMajorSchoolVolunteerIdWhenExporting() {
        PlanningStateDTO state = new PlanningStateDTO();
        state.getCandidatePoolState().setVolunteerModel("major");
        CandidateItemDTO candidate = buildCandidate(
                "ps1_school1_planMajor1",
                "school1",
                "3001",
                "学校A",
                "会计学",
                "120203",
                12,
                6800,
                "4年",
                52d);
        state.getCandidatePoolState().setItems(Arrays.asList(candidate));
        state.getOrderedPlanState().setItems(Arrays.asList(
                buildOrderedItem(1, "ps1_school1_legacyMajor1", "稳", "学校A", "会计学")
        ));

        PlanningExcelExportBuilder.PlanningExportData exportData = builder.build(state, new CreateSessionReq());

        assertEquals(1, exportData.getMainList().size());
        ExcelUtil.VolunteerExcelData row = exportData.getMainList().get(0);
        assertEquals("3001", row.getSchoolCode());
        assertEquals("学校A", row.getSchoolName());
        assertEquals(1, row.getMajorList().size());
        assertEquals("120203", row.getMajorList().get(0).getMajorCode());
        assertEquals("会计学", row.getMajorList().get(0).getMajorName());
    }

    @Test
    void shouldResolveLegacyMajorGroupVolunteerIdWhenExportingUnits() {
        PlanningStateDTO state = new PlanningStateDTO();
        state.getCandidatePoolState().setVolunteerModel("majorGroup");
        CandidateItemDTO candidate = buildCandidate(
                "ps1_school1_planMajor1",
                "school1",
                "3001",
                "学校A第01组",
                "会计学",
                "120203",
                12,
                6800,
                "4年",
                52d);
        state.getCandidatePoolState().setItems(Arrays.asList(candidate));

        OrderedUnitDTO unit = new OrderedUnitDTO();
        unit.setPosition(1);
        unit.setUnitId("ps1");
        unit.setTier("稳");
        unit.setSchoolName("学校A第01组");
        unit.setSchoolEnrollRatio(60d);
        unit.setMajorItems(Arrays.asList(buildUnitMajor("ps1_school1_legacyMajor1", "120203", "会计学")));
        state.getOrderedPlanState().setUnits(Arrays.asList(unit));
        state.getOrderedPlanState().setItems(Arrays.asList(
                buildOrderedItem(1, "ps1_school1_legacyMajor1", "稳", "学校A第01组", "会计学")
        ));

        PlanningExcelExportBuilder.PlanningExportData exportData = builder.build(state, new CreateSessionReq());

        assertTrue(exportData.isMajorGroupMode());
        assertEquals(1, exportData.getMainList().size());
        ExcelUtil.VolunteerExcelData row = exportData.getMainList().get(0);
        assertEquals("3001", row.getSchoolCode());
        assertEquals("学校A第01组", row.getSchoolName());
        assertEquals("60", row.getEnrollRatio());
        assertEquals(1, row.getMajorList().size());
        assertEquals("120203", row.getMajorList().get(0).getMajorCode());
        assertEquals("52%", row.getMajorList().get(0).getMajorEnrollRatio());
    }

    private CandidateItemDTO buildCandidate(String volunteerId,
                                            String schoolId,
                                            String schoolUnitCode,
                                            String schoolName,
                                            String majorName,
                                            String majorCode,
                                            int planNum,
                                            int tuition,
                                            String duration,
                                            double admissionRatio) {
        CandidateItemDTO item = new CandidateItemDTO();
        item.setVolunteerId(volunteerId);
        item.setSchoolId(schoolId);
        item.setPlanSchoolDataId("ps_" + schoolId);
        item.setSchoolUnitCode(schoolUnitCode);
        item.setSchoolName(schoolName);
        item.setProvinceName("北京");
        item.setCityName("北京");
        item.setSchoolLevel("本科");
        item.setSchoolNature("公办");
        item.setSchoolCategory("理工");
        item.setSchoolRank(100);
        item.setMajorName(majorName);
        item.setMajorCode(majorCode);
        item.setPlanNum(planNum);
        item.setTuitionPerYear(tuition);
        item.setDuration(duration);
        item.setAdmissionRatio(admissionRatio);
        item.setMustSubjects(Arrays.asList("物理", "化学"));
        CandidateItemDTO.HistoryScoreItem history = new CandidateItemDTO.HistoryScoreItem();
        history.setEnrollNum(planNum);
        history.setScore(600);
        history.setPos(10000);
        item.setMajorHistoryScores(Arrays.asList(history));
        return item;
    }

    private OrderedItemDTO buildOrderedItem(int position,
                                            String volunteerId,
                                            String tier,
                                            String schoolName,
                                            String majorName) {
        OrderedItemDTO item = new OrderedItemDTO();
        item.setPosition(position);
        item.setVolunteerId(volunteerId);
        item.setTier(tier);
        item.setSchoolName(schoolName);
        item.setMajorName(majorName);
        return item;
    }

    private PlanningUnitMajorDTO buildUnitMajor(String volunteerId, String majorCode, String majorName) {
        PlanningUnitMajorDTO major = new PlanningUnitMajorDTO();
        major.setVolunteerId(volunteerId);
        major.setMajorCode(majorCode);
        major.setMajorName(majorName);
        return major;
    }
}
