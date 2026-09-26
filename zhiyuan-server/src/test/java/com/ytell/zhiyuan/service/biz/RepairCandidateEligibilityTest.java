package com.ytell.zhiyuan.service.biz;

import com.google.common.collect.Lists;
import com.ytell.zhiyuan.model.dto.planning.CandidateItemDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningUnitDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningUnitMajorDTO;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

public class RepairCandidateEligibilityTest {

    @Test
    void shouldRejectCandidateBySchoolNatureScope() {
        PlanningStateDTO state = new PlanningStateDTO();
        state.getConstraintState().getHardConstraints().setMustExcludeSchools(Lists.newArrayList("院校性质:民办"));
        CandidateItemDTO privateCandidate = candidate("民办", "综合", "软件工程");
        CandidateItemDTO publicCandidate = candidate("公办", "综合", "软件工程");

        assertFalse(RepairCandidateEligibility.isEligibleForConfirmedHardConstraints(privateCandidate, state));
        assertTrue(RepairCandidateEligibility.isEligibleForConfirmedHardConstraints(publicCandidate, state));
    }

    @Test
    void shouldRequirePlanningUnitBySchoolNatureScope() {
        PlanningStateDTO state = new PlanningStateDTO();
        state.getConstraintState().getHardConstraints().setMustIncludeSchools(Lists.newArrayList("院校性质:公办"));
        PlanningUnitDTO privateUnit = unit("民办", "财经", "金融学");
        PlanningUnitDTO publicUnit = unit("公办", "财经", "金融学");

        assertFalse(RepairCandidateEligibility.isEligibleForConfirmedHardConstraints(privateUnit, state));
        assertTrue(RepairCandidateEligibility.isEligibleForConfirmedHardConstraints(publicUnit, state));
    }

    @Test
    void shouldRejectCandidateByProgramTypeScope() {
        PlanningStateDTO state = new PlanningStateDTO();
        state.getConstraintState().getHardConstraints().setMustExcludeSchools(Lists.newArrayList("招生类型:中外合作"));
        CandidateItemDTO cooperativeCandidate = candidate("公办", "理工", "软件工程(中外合作办学)");
        cooperativeCandidate.getReasonCodes().add("中外合作办学");
        CandidateItemDTO normalCandidate = candidate("公办", "理工", "软件工程");

        assertFalse(RepairCandidateEligibility.isEligibleForConfirmedHardConstraints(cooperativeCandidate, state));
        assertTrue(RepairCandidateEligibility.isEligibleForConfirmedHardConstraints(normalCandidate, state));
    }

    @Test
    void shouldRejectCandidateByProgramTypeInSchoolUnitName() {
        PlanningStateDTO state = new PlanningStateDTO();
        state.getConstraintState().getHardConstraints().setMustExcludeSchools(Lists.newArrayList("招生类型:中外合作"));
        CandidateItemDTO cooperativeCandidate = candidate("公办", "理工", "财务管理");
        cooperativeCandidate.setSchoolName("测试大学第206组(中外合作办学或国际项目)");
        CandidateItemDTO normalCandidate = candidate("公办", "理工", "财务管理");

        assertFalse(RepairCandidateEligibility.isEligibleForConfirmedHardConstraints(cooperativeCandidate, state));
        assertTrue(RepairCandidateEligibility.isEligibleForConfirmedHardConstraints(normalCandidate, state));
    }

    @Test
    void shouldRejectPlanningUnitByProgramTypeScopeFromMajorTags() {
        PlanningStateDTO state = new PlanningStateDTO();
        state.getConstraintState().getHardConstraints().setMustExcludeSchools(Lists.newArrayList("招生类型:中外合作"));
        PlanningUnitDTO cooperativeUnit = unit("公办", "理工", "软件工程");
        cooperativeUnit.getSelectedMajors().get(0).getReasonCodes().add("中外合作办学");
        PlanningUnitDTO normalUnit = unit("公办", "理工", "软件工程");

        assertFalse(RepairCandidateEligibility.isEligibleForConfirmedHardConstraints(cooperativeUnit, state));
        assertTrue(RepairCandidateEligibility.isEligibleForConfirmedHardConstraints(normalUnit, state));
    }

    @Test
    void shouldRequireCandidateByStrongbaseProgramTypeScope() {
        PlanningStateDTO state = new PlanningStateDTO();
        state.getConstraintState().getHardConstraints().setMustIncludeSchools(Lists.newArrayList("招生类型:强基"));
        CandidateItemDTO strongbaseCandidate = candidate("公办", "综合", "数学与应用数学");
        strongbaseCandidate.getReasonCodes().add("强基计划");
        CandidateItemDTO normalCandidate = candidate("公办", "综合", "数学与应用数学");

        assertTrue(RepairCandidateEligibility.isEligibleForConfirmedHardConstraints(strongbaseCandidate, state));
        assertFalse(RepairCandidateEligibility.isEligibleForConfirmedHardConstraints(normalCandidate, state));
    }

    /**
     * 粗粒度分类字段不能被细粒度专业名放大（2026-09-25 真栈缺陷）。
     *
     * <p>实测形态：`mustIncludeMajors=["临床医学"]` 下，池里 599 行 `discipline=医学`
     * 全部被算作命中（其中真正 `category=临床医学类` 的只有 71 行），于是
     * `mustExcludeMajors=["中西医临床医学"]` 又把这 599 行一起排掉 → 方案被排成 0 单元。
     */
    @Test
    void shouldNotMatchCoarseTaxonomyBySubstringWhenRequiringMajor() {
        PlanningStateDTO state = new PlanningStateDTO();
        state.getConstraintState().getHardConstraints().setMustIncludeMajors(Lists.newArrayList("临床医学"));

        CandidateItemDTO clinical = candidate("公办", "医药", "临床医学(五年)");
        clinical.setMajorCategory("临床医学类");
        clinical.setMajorDiscipline("医学");
        CandidateItemDTO traditional = candidate("公办", "医药", "中医学(五年)");
        traditional.setMajorCategory("中医学类");
        traditional.setMajorDiscipline("医学");
        CandidateItemDTO anesthesia = candidate("公办", "医药", "麻醉学(五年)");
        anesthesia.setMajorCategory("临床医学类");
        anesthesia.setMajorDiscipline("医学");

        assertTrue(RepairCandidateEligibility.isEligibleForConfirmedHardConstraints(clinical, state));
        // "医学" 是 "临床医学" 的子串，但那是**门类**字段，不是这个专业本身。
        assertFalse(RepairCandidateEligibility.isEligibleForConfirmedHardConstraints(traditional, state));
        assertFalse(RepairCandidateEligibility.isEligibleForConfirmedHardConstraints(anesthesia, state));
    }

    @Test
    void shouldNotExcludeWholeDisciplineBySubstringWhenExcludingMajor() {
        PlanningStateDTO state = new PlanningStateDTO();
        state.getConstraintState().getHardConstraints()
                .setMustExcludeMajors(Lists.newArrayList("中西医临床医学"));

        CandidateItemDTO clinical = candidate("公办", "医药", "临床医学(五年)");
        clinical.setMajorCategory("临床医学类");
        clinical.setMajorDiscipline("医学");
        CandidateItemDTO integrated = candidate("公办", "医药", "中西医临床医学(五年)");
        integrated.setMajorCategory("中西医结合类");
        integrated.setMajorDiscipline("医学");

        assertTrue(RepairCandidateEligibility.isEligibleForConfirmedHardConstraints(clinical, state));
        assertFalse(RepairCandidateEligibility.isEligibleForConfirmedHardConstraints(integrated, state));
    }

    /**
     * 区域：**ID 优先、名字兜底** ✓（2026-09-25 用户裁决的"区域按 ID"✓）。
     *
     * <p>真栈形态：候选的名字来自志愿文件（`area.data`/`city.data` ✓），ID 来自同一条的
     * `area.key`/`city.key` ✓——两者本该一致；但名字会因**写法/口径**不同而误判 ✗
     * （"北京市" vs "北京" ✓、"北京"是省级却被按市级找 ✗），ID 不会 ✓。
     */
    @Test
    void shouldMatchRegionByIdWhenBothSidesHaveIds() {
        PlanningStateDTO state = new PlanningStateDTO();
        state.getConstraintState().getHardConstraints()
                .setMustIncludeRegionIds(Lists.newArrayList("110000"));
        CandidateItemDTO beijing = candidate("公办", "综合", "计算机科学与技术");
        // 名字写成另一种形态（规范化后也不等于约束里的名字 ✗）——**只看 ID 就应当命中** ✓
        beijing.setProvinceName("北京市");
        beijing.setProvinceId("110000");
        CandidateItemDTO tianjin = candidate("公办", "综合", "计算机科学与技术");
        tianjin.setProvinceName("天津");
        tianjin.setProvinceId("120000");

        assertTrue(RepairCandidateEligibility.isEligibleForConfirmedHardConstraints(beijing, state));
        assertFalse(RepairCandidateEligibility.isEligibleForConfirmedHardConstraints(tianjin, state));
    }

    /** 冲突时**以 ID 为准** ✓：名字对得上、ID 对不上 → 排除 ✓（名字是弱证据 ✗）。 */
    @Test
    void shouldLetRegionIdWinOverNameWhenTheyConflict() {
        PlanningStateDTO state = new PlanningStateDTO();
        state.getConstraintState().getHardConstraints()
                .setMustIncludeRegionIds(Lists.newArrayList("110000"));
        CandidateItemDTO impostor = candidate("公办", "综合", "计算机科学与技术");
        impostor.setProvinceName("北京");
        impostor.setProvinceId("999999");

        assertFalse(RepairCandidateEligibility.isEligibleForConfirmedHardConstraints(impostor, state));
    }

    /** 缺 ID 回退名字 ✓：**不能**因为候选没带 ID 就把它判死 ✗。 */
    @Test
    void shouldFallBackToRegionNameWhenCandidateHasNoId() {
        PlanningStateDTO state = new PlanningStateDTO();
        state.getConstraintState().getHardConstraints()
                .setMustIncludeRegionIds(Lists.newArrayList("110000"));
        CandidateItemDTO noId = candidate("公办", "综合", "计算机科学与技术");
        noId.setProvinceName("北京");

        assertTrue(RepairCandidateEligibility.isEligibleForConfirmedHardConstraints(noId, state));
    }

    /**
     * 专业：**ID 优先、名字兜底** ✓（与区域同一条规矩 ✓，"专业按 ID"）。
     *
     * <p>真栈词汇表核对（2026-09-26）：池里 1008 条真 `majorId` 与目录
     * `/catalog/lookup/major` **同一套** ✓（临床医学 `774` ✓、低空技术与工程 `15223549801738240` ✓），
     * 446 条是 `"0"`＝大类/试验班 ✗（没有单一专业身份 ✓）。
     */
    @Test
    void shouldMatchMajorByIdWhenBothSidesHaveIds() {
        PlanningStateDTO state = new PlanningStateDTO();
        state.getConstraintState().getHardConstraints()
                .setMustIncludeMajorIds(Lists.newArrayList("774"));
        // 名字写成长形态（子串也命中 ✓，但这条要走 ID ✓）+ 一个真·别的专业 ✓
        CandidateItemDTO clinical = candidate("公办", "综合", "临床医学(五年)");
        clinical.setMajorId("774");
        CandidateItemDTO finance = candidate("公办", "综合", "临床医学(五年)");
        finance.setMajorId("248");

        assertTrue(RepairCandidateEligibility.isEligibleForConfirmedHardConstraints(clinical, state));
        assertFalse(RepairCandidateEligibility.isEligibleForConfirmedHardConstraints(finance, state));
    }

    /** 冲突时**以 ID 为准** ✓：名字像、ID 不是 → 排除 ✓（名字是弱证据 ✗）。 */
    @Test
    void shouldLetMajorIdWinOverNameWhenTheyConflict() {
        PlanningStateDTO state = new PlanningStateDTO();
        state.getConstraintState().getHardConstraints()
                .setMustIncludeMajorIds(Lists.newArrayList("774"));
        CandidateItemDTO impostor = candidate("公办", "综合", "临床医学(五年)");
        impostor.setMajorId("248");

        assertFalse(RepairCandidateEligibility.isEligibleForConfirmedHardConstraints(impostor, state));
    }

    /** `majorId="0"`＝大类/试验班 ✗ → 当作**缺 ID** ✓：名字兜底留住它 ✓，**不能判死** ✗。 */
    @Test
    void shouldFallBackToMajorNameWhenMajorIdIsBlankSentinel() {
        PlanningStateDTO state = new PlanningStateDTO();
        state.getConstraintState().getHardConstraints()
                .setMustIncludeMajorIds(Lists.newArrayList("774"));
        CandidateItemDTO group = candidate("公办", "综合", "医学试验班(临床医学，药学)");
        group.setMajorId("0");

        assertTrue(RepairCandidateEligibility.isEligibleForConfirmedHardConstraints(group, state));
    }

    /** 排除侧同理 ✓：ID 命中即排 ✓（名字里没有那个专业也照排 ✓）。 */
    @Test
    void shouldExcludeCandidateByMajorId() {
        PlanningStateDTO state = new PlanningStateDTO();
        state.getConstraintState().getHardConstraints()
                .setMustExcludeMajorIds(Lists.newArrayList("774"));
        CandidateItemDTO clinical = candidate("公办", "综合", "临床医学(五年)");
        clinical.setMajorId("774");

        assertFalse(RepairCandidateEligibility.isEligibleForConfirmedHardConstraints(clinical, state));
    }

    /** 单元侧（组模式的匹配对象 ✓）同样 ID 优先 ✓。 */
    @Test
    void shouldMatchPlanningUnitMajorById() {
        PlanningStateDTO state = new PlanningStateDTO();
        state.getConstraintState().getHardConstraints()
                .setMustIncludeMajorIds(Lists.newArrayList("774"));
        PlanningUnitDTO unit = unit("公办", "综合", "临床医学(五年)");
        unit.getSelectedMajors().get(0).setMajorId("774");

        assertTrue(RepairCandidateEligibility.isEligibleForConfirmedHardConstraints(unit, state));
    }

    private CandidateItemDTO candidate(String schoolNature, String schoolCategory, String majorName) {
        CandidateItemDTO candidate = new CandidateItemDTO();
        candidate.setSchoolName("测试大学");
        candidate.setSchoolNature(schoolNature);
        candidate.setSchoolCategory(schoolCategory);
        candidate.setSchoolLevel("本科");
        candidate.setProvinceName("广东");
        candidate.setMajorName(majorName);
        return candidate;
    }

    private PlanningUnitDTO unit(String schoolNature, String schoolCategory, String majorName) {
        PlanningUnitDTO unit = new PlanningUnitDTO();
        unit.setSchoolName("测试大学");
        unit.setSchoolNature(schoolNature);
        unit.setSchoolCategory(schoolCategory);
        unit.setSchoolLevel("本科");
        unit.setProvinceName("广东");
        PlanningUnitMajorDTO major = new PlanningUnitMajorDTO();
        major.setMajorName(majorName);
        unit.setSelectedMajors(Lists.newArrayList(major));
        return unit;
    }
}
