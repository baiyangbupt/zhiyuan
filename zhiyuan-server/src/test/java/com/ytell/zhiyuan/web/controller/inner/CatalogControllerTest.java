package com.ytell.zhiyuan.web.controller.inner;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ytell.zhiyuan.model.dto.catalog.CatalogFilterTagsTreeDTO;
import com.ytell.zhiyuan.model.dto.catalog.CatalogMajorLookupDTO;
import com.ytell.zhiyuan.model.dto.catalog.CatalogMajorTreeNodeDTO;
import com.ytell.zhiyuan.model.dto.catalog.CatalogResponseDTO;
import com.ytell.zhiyuan.model.dto.catalog.CatalogResultTypeEnum;
import com.ytell.zhiyuan.model.dto.catalog.CatalogSchoolLookupDTO;
import com.ytell.zhiyuan.service.biz.CatalogService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.Mockito;
import org.springframework.http.converter.json.MappingJackson2HttpMessageConverter;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import java.util.Collections;

import static org.mockito.Mockito.doReturn;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

public class CatalogControllerTest {

    private MockMvc mockMvc;
    private CatalogService catalogService;

    @BeforeEach
    void setUp() {
        CatalogController controller = new CatalogController();
        catalogService = Mockito.mock(CatalogService.class);
        ReflectionTestUtils.setField(controller, "catalogService", catalogService);
        mockMvc = MockMvcBuilders.standaloneSetup(controller)
                .setMessageConverters(new MappingJackson2HttpMessageConverter(new ObjectMapper()))
                .build();
    }

    @Test
    void shouldLookupSchool() throws Exception {
        CatalogSchoolLookupDTO dto = new CatalogSchoolLookupDTO();
        dto.setSchoolId("1");
        dto.setSchoolName("北京大学");
        dto.setProvinceCode("110000");
        CatalogResponseDTO<?> response = exactResponse(dto);
        doReturn(response).when(catalogService).lookupSchool("北京大学");

        mockMvc.perform(get("/gaotu-assistant-bot/inner/catalog/lookup/school")
                        .param("name", "北京大学"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.resultType").value("exact"))
                .andExpect(jsonPath("$.data.schoolId").value("1"))
                .andExpect(jsonPath("$.data.schoolName").value("北京大学"))
                .andExpect(jsonPath("$.data.provinceCode").value("110000"));
    }

    @Test
    void shouldLookupMajorTree() throws Exception {
        CatalogMajorTreeNodeDTO node = new CatalogMajorTreeNodeDTO();
        node.setCategoryId("7");
        node.setCategoryName("工学");
        node.setChildren(Collections.singletonList(new com.ytell.zhiyuan.model.dto.catalog.CatalogMajorCategoryNodeDTO()));
        node.getChildren().get(0).setSubCategoryId("39");
        node.getChildren().get(0).setSubCategoryName("计算机类");
        CatalogResponseDTO<?> response = exactResponse(Collections.singletonList(node));
        doReturn(response).when(catalogService).getMajorTree("本科");

        mockMvc.perform(get("/gaotu-assistant-bot/inner/catalog/tree/major")
                        .param("educationLevel", "本科"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.catalogVersion").value("2026.04.24.1"))
                .andExpect(jsonPath("$.schemaVersion").value("1.0"))
                .andExpect(jsonPath("$.resultType").value("exact"))
                .andExpect(jsonPath("$.data[0].categoryId").value("7"))
                .andExpect(jsonPath("$.data[0].categoryName").value("工学"))
                .andExpect(jsonPath("$.data[0].children[0].subCategoryId").value("39"))
                .andExpect(jsonPath("$.data[0].children[0].subCategoryName").value("计算机类"));
    }

    @Test
    void shouldReturnFilterTagsTree() throws Exception {
        CatalogFilterTagsTreeDTO dto = new CatalogFilterTagsTreeDTO();
        dto.getSchool().setCategory(Collections.singletonList("理工"));
        dto.getAdmission().setType(Collections.singletonList("普通类"));
        CatalogMajorTreeNodeDTO majorNode = new CatalogMajorTreeNodeDTO();
        majorNode.setCategoryId("7");
        majorNode.setCategoryName("工学");
        majorNode.setChildren(Collections.singletonList(new com.ytell.zhiyuan.model.dto.catalog.CatalogMajorCategoryNodeDTO()));
        majorNode.getChildren().get(0).setSubCategoryId("39");
        majorNode.getChildren().get(0).setSubCategoryName("计算机类");
        dto.getMajor().setDiscipline(Collections.singletonList("工学"));
        dto.getMajor().setCategory(Collections.singletonList(majorNode));
        dto.getConstraint().setLimit(Collections.singletonList("语种要求"));
        when(catalogService.getFilterTagsTree()).thenReturn(exactResponse(dto));

        mockMvc.perform(get("/gaotu-assistant-bot/inner/catalog/tree/filter-tags"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.catalogVersion").value("2026.04.24.1"))
                .andExpect(jsonPath("$.schemaVersion").value("1.0"))
                .andExpect(jsonPath("$.resultType").value("exact"))
                .andExpect(jsonPath("$.data.school.category[0]").value("理工"))
                .andExpect(jsonPath("$.data.major.discipline[0]").value("工学"))
                .andExpect(jsonPath("$.data.major.category[0].categoryId").value("7"))
                .andExpect(jsonPath("$.data.major.category[0].children[0].subCategoryId").value("39"))
                .andExpect(jsonPath("$.data.admission.type[0]").value("普通类"))
                .andExpect(jsonPath("$.data.constraint.limit[0]").value("语种要求"));
    }

    @Test
    void shouldLookupMajor() throws Exception {
        CatalogMajorLookupDTO dto = new CatalogMajorLookupDTO();
        dto.setMajorId("574");
        dto.setMajorName("计算机科学与技术");
        dto.setSubCategoryId("39");
        dto.setCategoryId("7");
        dto.setEducationLevel("本科");
        doReturn(exactResponse(dto)).when(catalogService).lookupMajor("计算机科学与技术", "本科");

        mockMvc.perform(get("/gaotu-assistant-bot/inner/catalog/lookup/major")
                        .param("name", "计算机科学与技术")
                        .param("educationLevel", "本科"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.resultType").value("exact"))
                .andExpect(jsonPath("$.data.majorId").value("574"))
                .andExpect(jsonPath("$.data.categoryId").value("7"))
                .andExpect(jsonPath("$.data.educationLevel").value("本科"));
    }

    @Test
    void shouldReturnBadRequestWhenLookupSchoolNameMissing() throws Exception {
        mockMvc.perform(get("/gaotu-assistant-bot/inner/catalog/lookup/school"))
                .andExpect(status().isBadRequest());
    }

    @Test
    void shouldReturnBadRequestWhenSearchMajorKeywordMissing() throws Exception {
        mockMvc.perform(get("/gaotu-assistant-bot/inner/catalog/search/major"))
                .andExpect(status().isBadRequest());
    }

    private <T> CatalogResponseDTO<T> exactResponse(T data) {
        CatalogResponseDTO<T> response = new CatalogResponseDTO<>();
        response.setCatalogVersion("2026.04.24.1");
        response.setSchemaVersion("1.0");
        response.setResultType(CatalogResultTypeEnum.EXACT);
        response.setData(data);
        return response;
    }
}
