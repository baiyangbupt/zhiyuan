package com.ytell.zhiyuan.service.biz;

import com.google.common.base.Strings;
import com.ytell.zhiyuan.manager.MajorMappingManager;
import com.ytell.zhiyuan.manager.MajorProfileManager;
import com.ytell.zhiyuan.manager.ProvinceCityManager;
import com.ytell.zhiyuan.manager.SchoolManager;
import com.ytell.zhiyuan.model.dto.MajorInfo;
import com.ytell.zhiyuan.model.dto.MajorMappingResult;
import com.ytell.zhiyuan.model.dto.MajorProfileDto;
import com.ytell.zhiyuan.model.dto.catalog.CatalogCityLookupDTO;
import com.ytell.zhiyuan.model.dto.catalog.CatalogFilterTagsTreeDTO;
import com.ytell.zhiyuan.model.dto.catalog.CatalogMajorCategoryLookupDTO;
import com.ytell.zhiyuan.model.dto.catalog.CatalogMajorCategoryNodeDTO;
import com.ytell.zhiyuan.model.dto.catalog.CatalogMajorDisciplineLookupDTO;
import com.ytell.zhiyuan.model.dto.catalog.CatalogMajorLookupDTO;
import com.ytell.zhiyuan.model.dto.catalog.CatalogMajorSearchItemDTO;
import com.ytell.zhiyuan.model.dto.catalog.CatalogMajorTreeNodeDTO;
import com.ytell.zhiyuan.model.dto.catalog.CatalogMatchTypeEnum;
import com.ytell.zhiyuan.model.dto.catalog.CatalogProvinceLookupDTO;
import com.ytell.zhiyuan.model.dto.catalog.CatalogRegionCityNodeDTO;
import com.ytell.zhiyuan.model.dto.catalog.CatalogRegionTreeNodeDTO;
import com.ytell.zhiyuan.model.dto.catalog.CatalogResponseDTO;
import com.ytell.zhiyuan.model.dto.catalog.CatalogResultTypeEnum;
import com.ytell.zhiyuan.model.dto.catalog.CatalogSchoolLookupDTO;
import com.ytell.zhiyuan.model.dto.catalog.CatalogSchoolSearchItemDTO;
import com.ytell.zhiyuan.model.vo.ProvinceCityVO;
import com.ytell.zhiyuan.model.vo.SchoolVO;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.Comparator;
import java.util.List;
import java.util.stream.Collectors;

@Slf4j
@Service
public class CatalogService {

    private static final String DEFAULT_SCHEMA_VERSION = "1.0";
    private static final List<String> SCHOOL_CATEGORY_TAGS = Arrays.asList(
            "综合", "理工", "师范", "财经", "政法", "医药", "语言", "农林", "民族", "体育", "艺术", "军事");
    private static final List<String> SCHOOL_NATURE_TAGS = Arrays.asList("公办", "民办", "中外合作");
    private static final List<String> SCHOOL_FEATURE_TAGS = Arrays.asList("教育部直属", "中央部委", "省会城市");
    private static final List<String> SCHOOL_LEVEL_TAGS = Arrays.asList(
            "本科", "专科", "985", "211", "双一流", "强基", "保研", "国重点", "省重点", "双高计划", "国家级示范", "国家级骨干", "职业本科");
    private static final List<String> ADMISSION_TYPE_TAGS = Arrays.asList(
            "普通类", "中外合作办学", "地方专项", "国家专项", "特色计划", "少数民族", "预科", "定向", "试验班", "实验班", "师范专业", "首年招生");
    private static final List<String> CONSTRAINT_LIMIT_TAGS = Arrays.asList("色盲色弱", "语种要求", "单科成绩", "性别要求");

    @Autowired
    private SchoolManager schoolManager;

    @Autowired
    private MajorMappingManager majorMappingManager;

    @Autowired
    private MajorProfileManager majorProfileManager;

    @Autowired
    private ProvinceCityManager provinceCityManager;

    @Value("${catalog.version:dev}")
    private String catalogVersion;

    @Value("${catalog.schema-version:1.0}")
    private String schemaVersion;

    public CatalogResponseDTO<?> lookupSchool(String name) {
        if (!hasText(name)) {
            throw new IllegalArgumentException("school name is required");
        }
        SchoolVO school = schoolManager.getSchoolByName(name.trim());
        if (school == null) {
            return emptyResponse();
        }
        return exactResponse(toSchoolLookup(school));
    }

    public CatalogResponseDTO<?> lookupMajor(String name, String educationLevel) {
        if (!hasText(name)) {
            throw new IllegalArgumentException("major name is required");
        }
        List<MajorMappingResult> matched = majorMappingManager.getThirdLevelIdAndSecondLevelId(name.trim());
        List<CatalogMajorLookupDTO> data = matched.stream()
                .map(this::toMajorLookup)
                .filter(item -> matchesEducationLevel(item.getCategoryId(), educationLevel))
                .collect(Collectors.toList());
        return toResponse(data);
    }

    public CatalogResponseDTO<?> lookupMajorCategory(String name, String educationLevel) {
        if (!hasText(name)) {
            throw new IllegalArgumentException("major category name is required");
        }
        String subCategoryId = majorMappingManager.getSecondLevelIdByName(name.trim());
        if (!hasText(subCategoryId)) {
            return emptyResponse();
        }
        MajorInfo subCategory = majorMappingManager.getMajorInfo(subCategoryId);
        if (subCategory == null || !matchesEducationLevel(subCategoryId, educationLevel)) {
            return emptyResponse();
        }
        CatalogMajorCategoryLookupDTO dto = new CatalogMajorCategoryLookupDTO();
        dto.setSubCategoryId(subCategory.getId());
        dto.setSubCategoryName(subCategory.getLabel());
        dto.setCategoryId(subCategory.getParentId());
        MajorInfo category = majorMappingManager.getMajorInfo(subCategory.getParentId());
        dto.setCategoryName(category != null ? category.getLabel() : null);
        dto.setEducationLevel(normalizeEducationLevel(subCategory.getId()));
        return exactResponse(dto);
    }

    public CatalogResponseDTO<?> lookupMajorDiscipline(String name, String educationLevel) {
        if (!hasText(name)) {
            throw new IllegalArgumentException("major discipline name is required");
        }
        String categoryId = majorMappingManager.getFirstLevelIdByName(name.trim());
        if (!hasText(categoryId) || !matchesEducationLevel(categoryId, educationLevel)) {
            return emptyResponse();
        }
        MajorInfo category = majorMappingManager.getMajorInfo(categoryId);
        if (category == null) {
            return emptyResponse();
        }
        CatalogMajorDisciplineLookupDTO dto = new CatalogMajorDisciplineLookupDTO();
        dto.setCategoryId(category.getId());
        dto.setCategoryName(category.getLabel());
        dto.setEducationLevel(normalizeEducationLevel(category.getId()));
        return exactResponse(dto);
    }

    public CatalogResponseDTO<?> lookupProvince(String name) {
        if (!hasText(name)) {
            throw new IllegalArgumentException("province name is required");
        }
        ProvinceCityVO province = provinceCityManager.getProvinceByLabel(name.trim());
        if (province == null) {
            return emptyResponse();
        }
        CatalogProvinceLookupDTO dto = new CatalogProvinceLookupDTO();
        dto.setProvinceCode(province.getId());
        dto.setProvinceName(province.getLabel());
        return exactResponse(dto);
    }

    public CatalogResponseDTO<?> lookupCity(String name) {
        if (!hasText(name)) {
            throw new IllegalArgumentException("city name is required");
        }
        ProvinceCityVO.CityVO city = provinceCityManager.getCityByLabel(name.trim());
        if (city == null) {
            return emptyResponse();
        }
        ProvinceCityVO province = provinceCityManager.getProvinceByCityId(city.getId());
        CatalogCityLookupDTO dto = new CatalogCityLookupDTO();
        dto.setCityCode(city.getId());
        dto.setCityName(city.getLabel());
        dto.setProvinceCode(province != null ? province.getId() : null);
        dto.setProvinceName(province != null ? province.getLabel() : null);
        return exactResponse(dto);
    }

    public CatalogResponseDTO<?> searchSchools(String keyword) {
        if (!hasText(keyword)) {
            throw new IllegalArgumentException("school keyword is required");
        }
        List<CatalogSchoolSearchItemDTO> data = schoolManager.searchSchoolsByName(keyword.trim()).stream()
                .map(this::toSchoolSearchItem)
                .collect(Collectors.toList());
        return toResponse(data);
    }

    public CatalogResponseDTO<?> searchMajors(String keyword, String educationLevel) {
        if (!hasText(keyword)) {
            throw new IllegalArgumentException("major keyword is required");
        }
        List<CatalogMajorSearchItemDTO> data = majorProfileManager.getMajorProfilesByName(keyword.trim()).stream()
                .filter(profile -> matchesEducationLevel(profile.getCategoryId(), educationLevel))
                .map(this::toMajorSearchItem)
                .collect(Collectors.toList());
        return toResponse(data);
    }

    public CatalogResponseDTO<List<CatalogMajorTreeNodeDTO>> getMajorTree(String educationLevel) {
        MajorMappingManager.EducationLevel level = toEducationLevel(educationLevel);
        List<CatalogMajorTreeNodeDTO> data = new ArrayList<>();
        for (MajorInfo firstLevel : majorMappingManager.getTwoLevelAllMajors(level)) {
            CatalogMajorTreeNodeDTO node = new CatalogMajorTreeNodeDTO();
            node.setCategoryId(firstLevel.getId());
            node.setCategoryName(firstLevel.getLabel());
            if (firstLevel.getChildren() != null) {
                for (MajorInfo secondLevel : firstLevel.getChildren()) {
                    CatalogMajorCategoryNodeDTO child = new CatalogMajorCategoryNodeDTO();
                    child.setSubCategoryId(secondLevel.getId());
                    child.setSubCategoryName(secondLevel.getLabel());
                    node.getChildren().add(child);
                }
            }
            data.add(node);
        }
        return exactResponse(data);
    }

    public CatalogResponseDTO<List<CatalogRegionTreeNodeDTO>> getRegionTree() {
        List<CatalogRegionTreeNodeDTO> data = new ArrayList<>();
        for (ProvinceCityVO province : provinceCityManager.getAllProvinces()) {
            CatalogRegionTreeNodeDTO node = new CatalogRegionTreeNodeDTO();
            node.setProvinceCode(province.getId());
            node.setProvinceName(province.getLabel());
            if (province.getChildren() != null) {
                for (ProvinceCityVO.CityVO city : province.getChildren()) {
                    CatalogRegionCityNodeDTO child = new CatalogRegionCityNodeDTO();
                    child.setCityCode(city.getId());
                    child.setCityName(city.getLabel());
                    node.getChildren().add(child);
                }
            }
            data.add(node);
        }
        return exactResponse(data);
    }

    public CatalogResponseDTO<CatalogFilterTagsTreeDTO> getFilterTagsTree() {
        CatalogFilterTagsTreeDTO data = new CatalogFilterTagsTreeDTO();
        data.getSchool().setCategory(copyAndSort(SCHOOL_CATEGORY_TAGS));
        data.getSchool().setNature(copyAndSort(SCHOOL_NATURE_TAGS));
        data.getSchool().setFeature(copyAndSort(SCHOOL_FEATURE_TAGS));
        data.getSchool().setLevel(copyAndSort(SCHOOL_LEVEL_TAGS));
        data.getAdmission().setType(copyAndSort(ADMISSION_TYPE_TAGS));
        data.getConstraint().setLimit(copyAndSort(CONSTRAINT_LIMIT_TAGS));

        List<CatalogMajorTreeNodeDTO> majorTree = new ArrayList<>();
        for (MajorInfo firstLevel : majorMappingManager.getTwoLevelAllMajors(MajorMappingManager.EducationLevel.ALL)) {
            CatalogMajorTreeNodeDTO node = new CatalogMajorTreeNodeDTO();
            node.setCategoryId(firstLevel.getId());
            node.setCategoryName(firstLevel.getLabel());
            if (firstLevel.getChildren() != null) {
                for (MajorInfo secondLevel : firstLevel.getChildren()) {
                    CatalogMajorCategoryNodeDTO child = new CatalogMajorCategoryNodeDTO();
                    child.setSubCategoryId(secondLevel.getId());
                    child.setSubCategoryName(secondLevel.getLabel());
                    node.getChildren().add(child);
                }
            }
            majorTree.add(node);
        }
        data.getMajor().setCategory(majorTree);
        data.getMajor().setDiscipline(majorTree.stream()
                .map(CatalogMajorTreeNodeDTO::getCategoryName)
                .collect(Collectors.toList()));
        return exactResponse(data);
    }

    private CatalogMajorLookupDTO toMajorLookup(MajorMappingResult result) {
        CatalogMajorLookupDTO dto = new CatalogMajorLookupDTO();
        dto.setMajorId(result.getThirdLevelId());
        dto.setMajorName(result.getThirdLevelName());
        MajorInfo major = majorMappingManager.getMajorInfo(result.getThirdLevelId());
        if (major != null) {
            dto.setMajorUnitCode(major.getMajorCode());
        }
        dto.setSubCategoryId(result.getSecondLevelId());
        dto.setSubCategoryName(result.getSecondLevelName());
        MajorInfo subCategory = majorMappingManager.getMajorInfo(result.getSecondLevelId());
        if (subCategory != null) {
            dto.setCategoryId(subCategory.getParentId());
            MajorInfo category = majorMappingManager.getMajorInfo(subCategory.getParentId());
            dto.setCategoryName(category != null ? category.getLabel() : null);
        }
        dto.setEducationLevel(normalizeEducationLevel(dto.getCategoryId()));
        return dto;
    }

    private CatalogSchoolLookupDTO toSchoolLookup(SchoolVO school) {
        CatalogSchoolLookupDTO dto = new CatalogSchoolLookupDTO();
        dto.setSchoolId(school.getSchoolId());
        dto.setSchoolName(school.getSchoolName());
        dto.setSchoolUnitCode(null);
        dto.setProvinceCode(school.getProvinceId());
        dto.setProvinceName(school.getProvince());
        dto.setCityCode(school.getCityId());
        dto.setCityName(school.getCity());
        return dto;
    }

    private CatalogSchoolSearchItemDTO toSchoolSearchItem(SchoolVO school) {
        CatalogSchoolSearchItemDTO dto = new CatalogSchoolSearchItemDTO();
        dto.setMatchType(CatalogMatchTypeEnum.FUZZY);
        dto.setSchoolId(school.getSchoolId());
        dto.setSchoolName(school.getSchoolName());
        return dto;
    }

    private List<String> copyAndSort(List<String> values) {
        return values.stream()
                .sorted(Comparator.naturalOrder())
                .collect(Collectors.toList());
    }

    private CatalogMajorSearchItemDTO toMajorSearchItem(MajorProfileDto profile) {
        CatalogMajorSearchItemDTO dto = new CatalogMajorSearchItemDTO();
        dto.setMatchType(CatalogMatchTypeEnum.FUZZY);
        dto.setMajorId(profile.getId());
        dto.setMajorName(profile.getName());
        dto.setSubCategoryId(profile.getSubCategoryId());
        dto.setSubCategoryName(profile.getSubCategory());
        dto.setCategoryId(profile.getCategoryId());
        dto.setCategoryName(profile.getCategory());
        dto.setEducationLevel(normalizeEducationLevel(profile.getCategoryId()));
        return dto;
    }

    private CatalogResponseDTO<?> toResponse(List<?> data) {
        if (data == null || data.isEmpty()) {
            return emptyResponse();
        }
        if (data.size() == 1) {
            return exactResponse(data.get(0));
        }
        return multiResponse(data);
    }

    private <T> CatalogResponseDTO<T> exactResponse(T data) {
        CatalogResponseDTO<T> response = baseResponse();
        response.setResultType(CatalogResultTypeEnum.EXACT);
        response.setData(data);
        return response;
    }

    private <T> CatalogResponseDTO<T> multiResponse(T data) {
        CatalogResponseDTO<T> response = baseResponse();
        response.setResultType(CatalogResultTypeEnum.MULTI);
        response.setData(data);
        return response;
    }

    private CatalogResponseDTO<Object> emptyResponse() {
        CatalogResponseDTO<Object> response = baseResponse();
        response.setResultType(CatalogResultTypeEnum.EMPTY);
        response.setData(null);
        return response;
    }

    private <T> CatalogResponseDTO<T> baseResponse() {
        CatalogResponseDTO<T> response = new CatalogResponseDTO<>();
        response.setCatalogVersion(catalogVersion);
        response.setSchemaVersion(Strings.isNullOrEmpty(schemaVersion) ? DEFAULT_SCHEMA_VERSION : schemaVersion);
        return response;
    }

    private MajorMappingManager.EducationLevel toEducationLevel(String educationLevel) {
        if (!hasText(educationLevel) || "本科".equals(educationLevel.trim())) {
            return MajorMappingManager.EducationLevel.BACHELOR;
        }
        if ("专科".equals(educationLevel.trim())) {
            return MajorMappingManager.EducationLevel.ASSOCIATE;
        }
        return MajorMappingManager.EducationLevel.ALL;
    }

    private boolean matchesEducationLevel(String categoryId, String educationLevel) {
        if (!hasText(educationLevel) || !hasText(categoryId)) {
            return true;
        }
        return educationLevel.trim().equals(normalizeEducationLevel(categoryId));
    }

    private String normalizeEducationLevel(String categoryId) {
        if (!hasText(categoryId)) {
            return null;
        }
        try {
            int id = Integer.parseInt(categoryId);
            return id >= 106 ? "专科" : "本科";
        } catch (NumberFormatException e) {
            log.warn("catalog education level parse failed: categoryId={}", categoryId);
            return null;
        }
    }

    private boolean hasText(String value) {
        return !Strings.isNullOrEmpty(value) && !value.trim().isEmpty();
    }
}
