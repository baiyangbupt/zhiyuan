package com.ytell.zhiyuan.manager;

import cn.hutool.core.util.NumberUtil;
import com.ytell.zhiyuan.model.dto.SchoolProfileDto;
import com.ytell.zhiyuan.model.vo.SchoolVO;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.core.io.ClassPathResource;
import org.springframework.stereotype.Component;

import javax.annotation.PostConstruct;
import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.stream.Collectors;

/**
 * 学校信息管理器
 * 提供学校信息的查询功能
 */
@Slf4j
@Component
public class SchoolManager {

    private static final String SCHOOL_FILE_PATH = "bizdata/school_info.csv";
    /**
     * 学校数据缓存 - key: 学校ID, value: 学校信息
     */
    private final Map<String, SchoolVO> schoolCacheById = new ConcurrentHashMap<>();
    /**
     * 学校数据缓存 - key: 学校名称, value: 学校信息
     */
    private final Map<String, SchoolVO> schoolCacheByName = new ConcurrentHashMap<>();
    /**
     * 省份学校缓存 - key: 省份名称, value: 学校列表
     */
    private final Map<String, List<SchoolVO>> provinceSchoolCache = new ConcurrentHashMap<>();
    /**
     * 城市学校缓存 - key: 城市名称, value: 学校列表
     */
    private final Map<String, List<SchoolVO>> citySchoolCache = new ConcurrentHashMap<>();
    /**
     * 学校类型缓存 - key: 学校类型, value: 学校列表
     */
    private final Map<String, List<SchoolVO>> schoolTypeCache = new ConcurrentHashMap<>();
    @Autowired
    private ProvinceCityManager provinceCityManager;
    @Autowired
    private SchoolProfileManager schoolProfileManager;

    /**
     * 初始化加载学校数据
     */
    @PostConstruct
    public void init() {
        try {
            loadSchoolData();
            log.info("学校数据加载完成，共加载 {} 所学校", schoolCacheById.size());
        } catch (Exception e) {
            log.error("加载学校数据失败", e);
        }
    }

    /**
     * 加载学校数据
     */
    private void loadSchoolData() throws IOException {
        ClassPathResource resource = new ClassPathResource(SCHOOL_FILE_PATH);
        try (BufferedReader reader = new BufferedReader(
                new InputStreamReader(resource.getInputStream(), StandardCharsets.UTF_8))) {

            // 读取标题行
            String headerLine = reader.readLine();
            if (headerLine == null || !headerLine.startsWith("school_id")) {
                log.error("学校数据文件格式不正确，第一行应该是标题行");
                return;
            }

            // 解析表头，建立列名到索引的映射
            String[] headers = headerLine.split(",");
            Map<String, Integer> headerMap = new HashMap<>();
            for (int i = 0; i < headers.length; i++) {
                headerMap.put(headers[i].trim(), i);
            }

            int count = 0;
            String line;
            while ((line = reader.readLine()) != null) {
                try {
                    SchoolVO school = parseSchoolLine(line, headerMap);
                    if (school != null) {
                        // 缓存学校数据
                        schoolCacheById.put(school.getSchoolId(), school);
                        schoolCacheByName.put(school.getSchoolName(), school);

                        // 缓存省份学校映射
                        provinceSchoolCache.computeIfAbsent(school.getProvince(), k -> new ArrayList<>())
                                .add(school);

                        // 缓存城市学校映射
                        citySchoolCache.computeIfAbsent(school.getCity(), k -> new ArrayList<>())
                                .add(school);

                        // 缓存学校类型映射
                        schoolTypeCache.computeIfAbsent(school.getSchoolType(), k -> new ArrayList<>())
                                .add(school);

                        count++;
                    }
                } catch (Exception e) {
                    log.warn("解析学校数据行失败: {}", line, e);
                }
            }
            log.info("成功解析 {} 条学校数据", count);
        }
    }

    /**
     * 解析CSV行数据
     */
    private SchoolVO parseSchoolLine(String line, Map<String, Integer> headerMap) {
        if (line == null || line.trim().isEmpty()) {
            return null;
        }

        String[] fields = line.split(",");
        if (fields.length < 9) {
            log.warn("学校数据行字段数量不足: {}", line);
            return null;
        }

        SchoolVO school = new SchoolVO();

        // 使用表头映射获取字段值
        school.setSchoolId(getFieldValue(fields, headerMap, "school_id"));
        school.setSchoolName(getFieldValue(fields, headerMap, "school_name"));
        school.setProvince(getFieldValue(fields, headerMap, "province"));
        school.setCity(getFieldValue(fields, headerMap, "city"));
        school.setAffiliation(getFieldValue(fields, headerMap, "affiliation"));
        school.setSchoolType(getFieldValue(fields, headerMap, "school_type"));
        school.setSchoolTags(getFieldValue(fields, headerMap, "school_tags"));
        school.setOwnership(getFieldValue(fields, headerMap, "ownership"));
        school.setEducationLevel(getFieldValue(fields, headerMap, "education_level"));

        // 设置省份和城市ID
        String provinceName = school.getProvince();
        String cityName = school.getCity();
        if (provinceName != null && !provinceName.isEmpty()) {
            school.setProvinceId(provinceCityManager.getProvinceIdByLabel(provinceName));
        }
        if (cityName != null && !cityName.isEmpty()) {
            school.setCityId(provinceCityManager.getCityIdByLabel(cityName));
        }

        // 这里的学校
        // 当前暂时基于学校标签生成临时排名
        SchoolProfileDto schoolProfileDto = schoolProfileManager.getSchoolProfileById(school.getSchoolId());
        school.setSchoolRank(NumberUtil.isNumber(schoolProfileDto.getGaotuRank()) ? Integer.valueOf(schoolProfileDto.getGaotuRank()) : null);
        return school;
    }

    /**
     * 根据表头名获取字段值
     */
    private String getFieldValue(String[] fields, Map<String, Integer> headerMap, String headerName) {
        Integer index = headerMap.get(headerName);
        if (index != null && index < fields.length) {
            return fields[index].trim();
        }
        log.warn("未找到表头: {}", headerName);
        return "";
    }

    /**
     * 根据学校ID查询学校信息
     *
     * @param schoolId 学校ID
     * @return 学校信息，如果不存在返回null
     */
    public SchoolVO getSchoolById(String schoolId) {
        return schoolCacheById.get(schoolId);
    }

    /**
     * 根据学校名称查询学校信息
     *
     * @param schoolName 学校名称
     * @return 学校信息，如果不存在返回null
     */
    public SchoolVO getSchoolByName(String schoolName) {
        return schoolCacheByName.get(schoolName);
    }

    /**
     * 根据学校名称模糊查询学校信息
     *
     * @param schoolName 学校名称（支持模糊匹配）
     * @return 匹配的学校列表
     */
    public List<SchoolVO> searchSchoolsByName(String schoolName) {
        if (schoolName == null || schoolName.trim().isEmpty()) {
            return new ArrayList<>();
        }

        String searchName = schoolName.trim();
        return schoolCacheByName.values().stream()
                .filter(school -> school.getSchoolName().contains(searchName))
                .collect(Collectors.toList());
    }

    /**
     * 根据省份查询学校列表
     *
     * @param province 省份名称
     * @return 该省份的学校列表
     */
    public List<SchoolVO> getSchoolsByProvince(String province) {
        if (province == null || province.trim().isEmpty()) {
            return new ArrayList<>();
        }

        List<SchoolVO> schools = provinceSchoolCache.get(province.trim());
        return schools != null ? new ArrayList<>(schools) : new ArrayList<>();
    }

    /**
     * 根据城市查询学校列表
     *
     * @param city 城市名称
     * @return 该城市的学校列表
     */
    public List<SchoolVO> getSchoolsByCity(String city) {
        if (city == null || city.trim().isEmpty()) {
            return new ArrayList<>();
        }

        List<SchoolVO> schools = citySchoolCache.get(city.trim());
        return schools != null ? new ArrayList<>(schools) : new ArrayList<>();
    }

    /**
     * 根据学校类型查询学校列表
     *
     * @param schoolType 学校类型
     * @return 该类型的学校列表
     */
    public List<SchoolVO> getSchoolsByType(String schoolType) {
        if (schoolType == null || schoolType.trim().isEmpty()) {
            return new ArrayList<>();
        }

        List<SchoolVO> schools = schoolTypeCache.get(schoolType.trim());
        return schools != null ? new ArrayList<>(schools) : new ArrayList<>();
    }

    /**
     * 根据公办民办查询学校列表
     *
     * @param ownership 公办民办
     * @return 该属性的学校列表
     */
    public List<SchoolVO> getSchoolsByOwnership(String ownership) {
        if (ownership == null || ownership.trim().isEmpty()) {
            return new ArrayList<>();
        }

        String searchOwnership = ownership.trim();
        return schoolCacheById.values().stream()
                .filter(school -> searchOwnership.equals(school.getOwnership()))
                .collect(Collectors.toList());
    }

    /**
     * 根据本科专科查询学校列表
     *
     * @param educationLevel 本科专科
     * @return 该教育层次的学校列表
     */
    public List<SchoolVO> getSchoolsByEducationLevel(String educationLevel) {
        if (educationLevel == null || educationLevel.trim().isEmpty()) {
            return new ArrayList<>();
        }

        String searchLevel = educationLevel.trim();
        return schoolCacheById.values().stream()
                .filter(school -> searchLevel.equals(school.getEducationLevel()))
                .collect(Collectors.toList());
    }

    /**
     * 根据学校标签查询学校列表
     *
     * @param tag 学校标签
     * @return 包含该标签的学校列表
     */
    public List<SchoolVO> getSchoolsByTag(String tag) {
        if (tag == null || tag.trim().isEmpty()) {
            return new ArrayList<>();
        }

        String searchTag = tag.trim();
        return schoolCacheById.values().stream()
                .filter(school -> school.getSchoolTags() != null &&
                        school.getSchoolTags().contains(searchTag))
                .collect(Collectors.toList());
    }

    /**
     * 获取所有省份列表
     *
     * @return 所有省份名称列表
     */
    public List<String> getAllProvinces() {
        return new ArrayList<>(provinceSchoolCache.keySet());
    }

    /**
     * 获取所有城市列表
     *
     * @return 所有城市名称列表
     */
    public List<String> getAllCities() {
        return new ArrayList<>(citySchoolCache.keySet());
    }

    /**
     * 获取所有学校类型列表
     *
     * @return 所有学校类型列表
     */
    public List<String> getAllSchoolTypes() {
        return new ArrayList<>(schoolTypeCache.keySet());
    }

    /**
     * 获取所有学校信息
     *
     * @return 所有学校信息列表
     */
    public List<SchoolVO> getAllSchools() {
        return new ArrayList<>(schoolCacheById.values());
    }

    /**
     * 获取学校总数
     *
     * @return 学校总数
     */
    public int getTotalSchoolCount() {
        return schoolCacheById.size();
    }

    /**
     * 复合查询：根据多个条件查询学校
     *
     * @param province       省份（可选）
     * @param city           城市（可选）
     * @param schoolType     学校类型（可选）
     * @param ownership      公办民办（可选）
     * @param educationLevel 本科专科（可选）
     * @return 符合条件的学校列表
     */
    public List<SchoolVO> searchSchools(String province, String city, String schoolType,
                                        String ownership, String educationLevel) {
        return schoolCacheById.values().stream()
                .filter(school -> (province == null || province.trim().isEmpty() ||
                        province.trim().equals(school.getProvince())))
                .filter(school -> (city == null || city.trim().isEmpty() ||
                        city.trim().equals(school.getCity())))
                .filter(school -> (schoolType == null || schoolType.trim().isEmpty() ||
                        schoolType.trim().equals(school.getSchoolType())))
                .filter(school -> (ownership == null || ownership.trim().isEmpty() ||
                        ownership.trim().equals(school.getOwnership())))
                .filter(school -> (educationLevel == null || educationLevel.trim().isEmpty() ||
                        educationLevel.trim().equals(school.getEducationLevel())))
                .collect(Collectors.toList());
    }
}
