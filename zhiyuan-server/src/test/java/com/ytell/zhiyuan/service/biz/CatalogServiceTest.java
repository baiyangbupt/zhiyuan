package com.ytell.zhiyuan.service.biz;

import com.ytell.zhiyuan.manager.MajorMappingManager;
import com.ytell.zhiyuan.manager.MajorProfileManager;
import com.ytell.zhiyuan.manager.ProvinceCityManager;
import com.ytell.zhiyuan.manager.SchoolManager;
import com.ytell.zhiyuan.model.dto.MajorInfo;
import com.ytell.zhiyuan.model.dto.MajorMappingResult;
import com.ytell.zhiyuan.model.dto.MajorProfileDto;
import com.ytell.zhiyuan.model.dto.catalog.CatalogFilterTagsTreeDTO;
import com.ytell.zhiyuan.model.dto.catalog.CatalogMajorLookupDTO;
import com.ytell.zhiyuan.model.dto.catalog.CatalogMajorTreeNodeDTO;
import com.ytell.zhiyuan.model.dto.catalog.CatalogRegionTreeNodeDTO;
import com.ytell.zhiyuan.model.dto.catalog.CatalogResponseDTO;
import com.ytell.zhiyuan.model.dto.catalog.CatalogResultTypeEnum;
import com.ytell.zhiyuan.model.vo.ProvinceCityVO;
import com.ytell.zhiyuan.model.vo.SchoolVO;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.Mockito;
import org.springframework.test.util.ReflectionTestUtils;

import java.util.Arrays;
import java.util.Collections;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.Mockito.when;

public class CatalogServiceTest {

    private CatalogService catalogService;
    private SchoolManager schoolManager;
    private MajorMappingManager majorMappingManager;
    private MajorProfileManager majorProfileManager;
    private ProvinceCityManager provinceCityManager;

    @BeforeEach
    void setUp() {
        catalogService = new CatalogService();
        schoolManager = Mockito.mock(SchoolManager.class);
        majorMappingManager = Mockito.mock(MajorMappingManager.class);
        majorProfileManager = Mockito.mock(MajorProfileManager.class);
        provinceCityManager = Mockito.mock(ProvinceCityManager.class);
        ReflectionTestUtils.setField(catalogService, "schoolManager", schoolManager);
        ReflectionTestUtils.setField(catalogService, "majorMappingManager", majorMappingManager);
        ReflectionTestUtils.setField(catalogService, "majorProfileManager", majorProfileManager);
        ReflectionTestUtils.setField(catalogService, "provinceCityManager", provinceCityManager);
        ReflectionTestUtils.setField(catalogService, "catalogVersion", "2026.04.24.1");
        ReflectionTestUtils.setField(catalogService, "schemaVersion", "1.0");
    }

    @Test
    void shouldLookupSchool() {
        SchoolVO school = buildSchool("1", "北京大学", "110000", "北京", "110108", "海淀");
        when(schoolManager.getSchoolByName("北京大学")).thenReturn(school);

        CatalogResponseDTO<?> response = catalogService.lookupSchool("北京大学");

        assertEquals(CatalogResultTypeEnum.EXACT, response.getResultType());
        assertEquals("2026.04.24.1", response.getCatalogVersion());
        Object data = response.getData();
        assertNotNull(data);
        assertEquals("1", ReflectionTestUtils.getField(data, "schoolId"));
        assertEquals("北京大学", ReflectionTestUtils.getField(data, "schoolName"));
        assertEquals("110000", ReflectionTestUtils.getField(data, "provinceCode"));
    }

    @Test
    void shouldReturnEmptyWhenSchoolMissing() {
        when(schoolManager.getSchoolByName("不存在学校")).thenReturn(null);

        CatalogResponseDTO<?> response = catalogService.lookupSchool("不存在学校");

        assertEquals(CatalogResultTypeEnum.EMPTY, response.getResultType());
        assertNull(response.getData());
    }

    @Test
    void shouldRejectBlankSchoolName() {
        assertThrows(IllegalArgumentException.class, () -> catalogService.lookupSchool("  "));
    }

    @Test
    void shouldLookupMajorWithExactMatch() {
        MajorMappingResult mapping = new MajorMappingResult();
        mapping.setThirdLevelId("574");
        mapping.setThirdLevelName("计算机科学与技术");
        mapping.setSecondLevelId("39");
        mapping.setSecondLevelName("计算机类");
        when(majorMappingManager.getThirdLevelIdAndSecondLevelId("计算机科学与技术"))
                .thenReturn(Collections.singletonList(mapping));
        when(majorMappingManager.getMajorInfo("574")).thenReturn(buildMajor("574", "计算机科学与技术", "080901", "39"));
        when(majorMappingManager.getMajorInfo("39")).thenReturn(buildMajor("39", "计算机类", null, "7"));
        when(majorMappingManager.getMajorInfo("7")).thenReturn(buildMajor("7", "工学", null, "0"));

        CatalogResponseDTO<?> response = catalogService.lookupMajor("计算机科学与技术", "本科");

        assertEquals(CatalogResultTypeEnum.EXACT, response.getResultType());
        assertTrue(response.getData() instanceof CatalogMajorLookupDTO);
        CatalogMajorLookupDTO dto = (CatalogMajorLookupDTO) response.getData();
        assertEquals("574", dto.getMajorId());
        assertEquals("39", dto.getSubCategoryId());
        assertEquals("7", dto.getCategoryId());
        assertEquals("本科", dto.getEducationLevel());
    }

    @Test
    void shouldReturnMultiWhenMajorHasMultipleMatches() {
        MajorMappingResult bachelor = new MajorMappingResult();
        bachelor.setThirdLevelId("574");
        bachelor.setThirdLevelName("护理学");
        bachelor.setSecondLevelId("90");
        bachelor.setSecondLevelName("护理学类");
        MajorMappingResult associate = new MajorMappingResult();
        associate.setThirdLevelId("900");
        associate.setThirdLevelName("护理学");
        associate.setSecondLevelId("150");
        associate.setSecondLevelName("护理类");
        when(majorMappingManager.getThirdLevelIdAndSecondLevelId("护理学"))
                .thenReturn(Arrays.asList(bachelor, associate));
        when(majorMappingManager.getMajorInfo("574")).thenReturn(buildMajor("574", "护理学", "101101", "90"));
        when(majorMappingManager.getMajorInfo("90")).thenReturn(buildMajor("90", "护理学类", null, "89"));
        when(majorMappingManager.getMajorInfo("89")).thenReturn(buildMajor("89", "医学", null, "0"));
        when(majorMappingManager.getMajorInfo("900")).thenReturn(buildMajor("900", "护理学", "520201", "150"));
        when(majorMappingManager.getMajorInfo("150")).thenReturn(buildMajor("150", "护理类", null, "106"));
        when(majorMappingManager.getMajorInfo("106")).thenReturn(buildMajor("106", "医药卫生大类", null, "0"));

        CatalogResponseDTO<?> response = catalogService.lookupMajor("护理学", null);

        assertEquals(CatalogResultTypeEnum.MULTI, response.getResultType());
        assertTrue(response.getData() instanceof List);
        assertEquals(2, ((List<?>) response.getData()).size());
    }

    @Test
    void shouldFilterMajorByEducationLevel() {
        MajorMappingResult bachelor = new MajorMappingResult();
        bachelor.setThirdLevelId("574");
        bachelor.setThirdLevelName("护理学");
        bachelor.setSecondLevelId("90");
        bachelor.setSecondLevelName("护理学类");
        MajorMappingResult associate = new MajorMappingResult();
        associate.setThirdLevelId("900");
        associate.setThirdLevelName("护理学");
        associate.setSecondLevelId("150");
        associate.setSecondLevelName("护理类");
        when(majorMappingManager.getThirdLevelIdAndSecondLevelId("护理学"))
                .thenReturn(Arrays.asList(bachelor, associate));
        when(majorMappingManager.getMajorInfo("574")).thenReturn(buildMajor("574", "护理学", "101101", "90"));
        when(majorMappingManager.getMajorInfo("90")).thenReturn(buildMajor("90", "护理学类", null, "89"));
        when(majorMappingManager.getMajorInfo("89")).thenReturn(buildMajor("89", "医学", null, "0"));
        when(majorMappingManager.getMajorInfo("900")).thenReturn(buildMajor("900", "护理学", "520201", "150"));
        when(majorMappingManager.getMajorInfo("150")).thenReturn(buildMajor("150", "护理类", null, "106"));
        when(majorMappingManager.getMajorInfo("106")).thenReturn(buildMajor("106", "医药卫生大类", null, "0"));

        CatalogResponseDTO<?> response = catalogService.lookupMajor("护理学", "本科");

        assertEquals(CatalogResultTypeEnum.EXACT, response.getResultType());
        assertTrue(response.getData() instanceof CatalogMajorLookupDTO);
        CatalogMajorLookupDTO dto = (CatalogMajorLookupDTO) response.getData();
        assertEquals("574", dto.getMajorId());
        assertEquals("本科", dto.getEducationLevel());
    }

    @Test
    void shouldReturnEmptyWhenMajorMatchesFilteredOutByEducationLevel() {
        MajorMappingResult bachelor = new MajorMappingResult();
        bachelor.setThirdLevelId("574");
        bachelor.setThirdLevelName("护理学");
        bachelor.setSecondLevelId("90");
        bachelor.setSecondLevelName("护理学类");
        when(majorMappingManager.getThirdLevelIdAndSecondLevelId("护理学"))
                .thenReturn(Collections.singletonList(bachelor));
        when(majorMappingManager.getMajorInfo("574")).thenReturn(buildMajor("574", "护理学", "101101", "90"));
        when(majorMappingManager.getMajorInfo("90")).thenReturn(buildMajor("90", "护理学类", null, "89"));
        when(majorMappingManager.getMajorInfo("89")).thenReturn(buildMajor("89", "医学", null, "0"));

        CatalogResponseDTO<?> response = catalogService.lookupMajor("护理学", "专科");

        assertEquals(CatalogResultTypeEnum.EMPTY, response.getResultType());
        assertNull(response.getData());
    }

    @Test
    void shouldLookupMajorCategory() {
        when(majorMappingManager.getSecondLevelIdByName("计算机类")).thenReturn("39");
        when(majorMappingManager.getMajorInfo("39")).thenReturn(buildMajor("39", "计算机类", null, "7"));
        when(majorMappingManager.getMajorInfo("7")).thenReturn(buildMajor("7", "工学", null, "0"));

        CatalogResponseDTO<?> response = catalogService.lookupMajorCategory("计算机类", "本科");

        assertEquals(CatalogResultTypeEnum.EXACT, response.getResultType());
        assertEquals("39", ReflectionTestUtils.getField(response.getData(), "subCategoryId"));
        assertEquals("7", ReflectionTestUtils.getField(response.getData(), "categoryId"));
    }

    @Test
    void shouldReturnEmptyWhenMajorCategoryFilteredByEducationLevel() {
        when(majorMappingManager.getSecondLevelIdByName("计算机类")).thenReturn("39");
        when(majorMappingManager.getMajorInfo("39")).thenReturn(buildMajor("39", "计算机类", null, "7"));

        CatalogResponseDTO<?> response = catalogService.lookupMajorCategory("计算机类", "专科");

        assertEquals(CatalogResultTypeEnum.EMPTY, response.getResultType());
        assertNull(response.getData());
    }

    @Test
    void shouldLookupMajorDiscipline() {
        when(majorMappingManager.getFirstLevelIdByName("工学")).thenReturn("7");
        when(majorMappingManager.getMajorInfo("7")).thenReturn(buildMajor("7", "工学", null, "0"));

        CatalogResponseDTO<?> response = catalogService.lookupMajorDiscipline("工学", "本科");

        assertEquals(CatalogResultTypeEnum.EXACT, response.getResultType());
        assertEquals("7", ReflectionTestUtils.getField(response.getData(), "categoryId"));
        assertEquals("工学", ReflectionTestUtils.getField(response.getData(), "categoryName"));
    }

    @Test
    void shouldReturnEmptyWhenMajorDisciplineFilteredByEducationLevel() {
        when(majorMappingManager.getFirstLevelIdByName("工学")).thenReturn("7");

        CatalogResponseDTO<?> response = catalogService.lookupMajorDiscipline("工学", "专科");

        assertEquals(CatalogResultTypeEnum.EMPTY, response.getResultType());
        assertNull(response.getData());
    }

    @Test
    void shouldLookupProvinceAndCity() {
        ProvinceCityVO province = new ProvinceCityVO();
        province.setId("110000");
        province.setLabel("北京");
        ProvinceCityVO.CityVO city = new ProvinceCityVO.CityVO();
        city.setId("110108");
        city.setLabel("海淀");
        when(provinceCityManager.getProvinceByLabel("北京")).thenReturn(province);
        when(provinceCityManager.getCityByLabel("海淀")).thenReturn(city);
        when(provinceCityManager.getProvinceByCityId("110108")).thenReturn(province);

        CatalogResponseDTO<?> provinceResponse = catalogService.lookupProvince("北京");
        CatalogResponseDTO<?> cityResponse = catalogService.lookupCity("海淀");

        assertEquals(CatalogResultTypeEnum.EXACT, provinceResponse.getResultType());
        assertEquals("110000", ReflectionTestUtils.getField(provinceResponse.getData(), "provinceCode"));
        assertEquals(CatalogResultTypeEnum.EXACT, cityResponse.getResultType());
        assertEquals("110108", ReflectionTestUtils.getField(cityResponse.getData(), "cityCode"));
        assertEquals("110000", ReflectionTestUtils.getField(cityResponse.getData(), "provinceCode"));
    }

    @Test
    void shouldSearchSchools() {
        when(schoolManager.searchSchoolsByName("北京"))
                .thenReturn(Arrays.asList(
                        buildSchool("1", "北京大学", "110000", "北京", "110108", "海淀"),
                        buildSchool("2", "北京工业大学", "110000", "北京", "110108", "海淀")
                ));

        CatalogResponseDTO<?> response = catalogService.searchSchools("北京");

        assertEquals(CatalogResultTypeEnum.MULTI, response.getResultType());
        assertEquals(2, ((List<?>) response.getData()).size());
    }

    @Test
    void shouldReturnEmptyWhenSearchSchoolsHasNoMatch() {
        when(schoolManager.searchSchoolsByName("火星")).thenReturn(Collections.emptyList());

        CatalogResponseDTO<?> response = catalogService.searchSchools("火星");

        assertEquals(CatalogResultTypeEnum.EMPTY, response.getResultType());
        assertNull(response.getData());
    }

    @Test
    void shouldSearchMajors() {
        MajorProfileDto profile = new MajorProfileDto();
        profile.setId("574");
        profile.setName("计算机科学与技术");
        profile.setSubCategoryId("39");
        profile.setSubCategory("计算机类");
        profile.setCategoryId("7");
        profile.setCategory("工学");
        when(majorProfileManager.getMajorProfilesByName("计算机"))
                .thenReturn(Collections.singletonList(profile));

        CatalogResponseDTO<?> response = catalogService.searchMajors("计算机", "本科");

        assertEquals(CatalogResultTypeEnum.EXACT, response.getResultType());
        assertNotNull(response.getData());
    }

    @Test
    void shouldFilterSearchMajorsByEducationLevel() {
        MajorProfileDto bachelor = new MajorProfileDto();
        bachelor.setId("574");
        bachelor.setName("护理学");
        bachelor.setSubCategoryId("90");
        bachelor.setSubCategory("护理学类");
        bachelor.setCategoryId("89");
        bachelor.setCategory("医学");
        MajorProfileDto associate = new MajorProfileDto();
        associate.setId("900");
        associate.setName("护理学");
        associate.setSubCategoryId("150");
        associate.setSubCategory("护理类");
        associate.setCategoryId("106");
        associate.setCategory("医药卫生大类");
        when(majorProfileManager.getMajorProfilesByName("护理"))
                .thenReturn(Arrays.asList(bachelor, associate));

        CatalogResponseDTO<?> response = catalogService.searchMajors("护理", "专科");

        assertEquals(CatalogResultTypeEnum.EXACT, response.getResultType());
        assertNotNull(response.getData());
        assertEquals("900", ReflectionTestUtils.getField(response.getData(), "majorId"));
        assertEquals("专科", ReflectionTestUtils.getField(response.getData(), "educationLevel"));
    }

    @Test
    void shouldBuildMajorTree() {
        MajorInfo first = buildMajor("7", "工学", null, "0");
        MajorInfo second = buildMajor("39", "计算机类", null, "7");
        first.setChildren(Collections.singletonList(second));
        when(majorMappingManager.getTwoLevelAllMajors(MajorMappingManager.EducationLevel.BACHELOR))
                .thenReturn(Collections.singletonList(first));

        CatalogResponseDTO<List<CatalogMajorTreeNodeDTO>> response = catalogService.getMajorTree("本科");

        assertEquals(CatalogResultTypeEnum.EXACT, response.getResultType());
        assertEquals(1, response.getData().size());
        assertEquals("7", response.getData().get(0).getCategoryId());
        assertEquals("39", response.getData().get(0).getChildren().get(0).getSubCategoryId());
    }

    @Test
    void shouldBuildMajorTreeWithDefaultBachelorLevel() {
        MajorInfo first = buildMajor("7", "工学", null, "0");
        when(majorMappingManager.getTwoLevelAllMajors(MajorMappingManager.EducationLevel.BACHELOR))
                .thenReturn(Collections.singletonList(first));

        CatalogResponseDTO<List<CatalogMajorTreeNodeDTO>> response = catalogService.getMajorTree(null);

        assertEquals(CatalogResultTypeEnum.EXACT, response.getResultType());
        assertEquals(1, response.getData().size());
    }

    @Test
    void shouldBuildRegionTree() {
        ProvinceCityVO province = new ProvinceCityVO();
        province.setId("110000");
        province.setLabel("北京");
        ProvinceCityVO.CityVO city = new ProvinceCityVO.CityVO();
        city.setId("110108");
        city.setLabel("海淀");
        province.setChildren(Collections.singletonList(city));
        when(provinceCityManager.getAllProvinces()).thenReturn(Collections.singletonList(province));

        CatalogResponseDTO<List<CatalogRegionTreeNodeDTO>> response = catalogService.getRegionTree();

        assertEquals(CatalogResultTypeEnum.EXACT, response.getResultType());
        assertEquals(1, response.getData().size());
        assertEquals("110000", response.getData().get(0).getProvinceCode());
        assertEquals("110108", response.getData().get(0).getChildren().get(0).getCityCode());
    }

    @Test
    void shouldBuildFilterTagsTree() {
        MajorInfo discipline = buildMajor("7", "工学", null, "0");
        MajorInfo category = buildMajor("39", "计算机类", null, "7");
        discipline.setChildren(Collections.singletonList(category));
        when(majorMappingManager.getTwoLevelAllMajors(MajorMappingManager.EducationLevel.ALL))
                .thenReturn(Collections.singletonList(discipline));

        CatalogResponseDTO<CatalogFilterTagsTreeDTO> response = catalogService.getFilterTagsTree();

        assertEquals(CatalogResultTypeEnum.EXACT, response.getResultType());
        assertNotNull(response.getData());
        assertEquals(Collections.singletonList("工学"), response.getData().getMajor().getDiscipline());
        assertEquals(1, response.getData().getMajor().getCategory().size());
        assertEquals("7", response.getData().getMajor().getCategory().get(0).getCategoryId());
        assertTrue(response.getData().getSchool().getNature().contains("公办"));
        assertTrue(response.getData().getAdmission().getType().contains("普通类"));
        assertTrue(response.getData().getConstraint().getLimit().contains("语种要求"));
    }

    @Test
    void shouldBuildFilterTagsTreeWithSortedSchoolEnumsAndAllMajorTree() {
        MajorInfo bachelor = buildMajor("7", "工学", null, "0");
        MajorInfo bachelorCategory = buildMajor("39", "计算机类", null, "7");
        bachelor.setChildren(Collections.singletonList(bachelorCategory));
        MajorInfo associate = buildMajor("106", "医药卫生大类", null, "0");
        MajorInfo associateCategory = buildMajor("150", "护理类", null, "106");
        associate.setChildren(Collections.singletonList(associateCategory));
        when(majorMappingManager.getTwoLevelAllMajors(MajorMappingManager.EducationLevel.ALL))
                .thenReturn(Arrays.asList(bachelor, associate));

        CatalogResponseDTO<CatalogFilterTagsTreeDTO> response = catalogService.getFilterTagsTree();

        assertEquals(CatalogResultTypeEnum.EXACT, response.getResultType());
        assertEquals(Arrays.asList("工学", "医药卫生大类"), response.getData().getMajor().getDiscipline());
        assertEquals("211", response.getData().getSchool().getLevel().get(0));
        assertTrue(response.getData().getSchool().getCategory().contains("综合"));
        assertEquals("150", response.getData().getMajor().getCategory().get(1).getChildren().get(0).getSubCategoryId());
    }

    private SchoolVO buildSchool(String schoolId, String name, String provinceId, String provinceName, String cityId, String cityName) {
        SchoolVO school = new SchoolVO();
        school.setSchoolId(schoolId);
        school.setSchoolName(name);
        school.setProvinceId(provinceId);
        school.setProvince(provinceName);
        school.setCityId(cityId);
        school.setCity(cityName);
        return school;
    }

    private MajorInfo buildMajor(String id, String label, String majorCode, String parentId) {
        MajorInfo info = new MajorInfo();
        info.setId(id);
        info.setLabel(label);
        info.setMajorCode(majorCode);
        info.setParentId(parentId);
        return info;
    }
}
