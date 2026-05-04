package com.ytell.zhiyuan.manager;

import com.ytell.zhiyuan.model.dto.SchoolProfileDto;
import lombok.extern.slf4j.Slf4j;
import org.apache.poi.ss.usermodel.*;
import org.springframework.core.io.ClassPathResource;
import org.springframework.stereotype.Component;

import javax.annotation.PostConstruct;
import java.io.InputStream;
import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

/**
 * 学校画像数据管理器
 * 用于加载和管理学校画像Excel数据
 *
 * @author gaotu-assistant
 * @date 2024-12-19
 */
@Slf4j
@Component
public class SchoolProfileManager {

    /**
     * Excel文件路径
     */
    private static final String EXCEL_FILE_PATH = "bizdata/school_profile-0903.xlsx";
    /**
     * 学校画像数据缓存 - 以学校名称为key
     */
    private final Map<String, SchoolProfileDto> schoolProfileMap = new ConcurrentHashMap<>();
    /**
     * 学校画像数据缓存 - 以学校ID为key
     */
    private final Map<String, SchoolProfileDto> schoolProfileByIdMap = new ConcurrentHashMap<>();
    /**
     * 学校画像数据列表缓存
     */
    private final List<SchoolProfileDto> schoolProfileList = new ArrayList<>();

    /**
     * 初始化方法，加载Excel数据到内存
     */
    @PostConstruct
    public void init() {
        loadSchoolProfileData();
        log.info("学校画像数据加载完成，共加载 {} 条数据", schoolProfileList.size());
    }

    /**
     * 加载学校画像Excel数据
     */
    private void loadSchoolProfileData() {
        try {
            ClassPathResource resource = new ClassPathResource(EXCEL_FILE_PATH);
            try (InputStream inputStream = resource.getInputStream();
                 Workbook workbook = WorkbookFactory.create(inputStream)) {

                Sheet sheet = workbook.getSheetAt(0);

                // 跳过第一行表头，从第二行开始读取数据
                for (int rowIndex = 1; rowIndex <= sheet.getLastRowNum(); rowIndex++) {
                    Row row = sheet.getRow(rowIndex);
                    if (row == null) {
                        continue;
                    }

                    try {
                        SchoolProfileDto schoolProfile = parseRowToSchoolProfile(row);
                        if (schoolProfile != null && schoolProfile.getName() != null) {
                            schoolProfileList.add(schoolProfile);
                            schoolProfileMap.put(schoolProfile.getName(), schoolProfile);
                            // 如果学校ID不为空，也添加到ID缓存中
                            if (schoolProfile.getSchoolId() != null && !schoolProfile.getSchoolId().trim().isEmpty()) {
                                schoolProfileByIdMap.put(schoolProfile.getSchoolId().trim(), schoolProfile);
                            }
                        }
                    } catch (Exception e) {
                        log.warn("解析第 {} 行数据失败: {}", rowIndex + 1, e.getMessage());
                    }
                }
            }
        } catch (Exception e) {
            log.error("加载学校画像数据失败", e);
            throw new RuntimeException("加载学校画像数据失败", e);
        }
    }

    /**
     * 将Excel行数据解析为SchoolProfileDto对象
     * 注意：从索引1开始读取学校ID，从索引2开始读取其他数据
     */
    private SchoolProfileDto parseRowToSchoolProfile(Row row) {
        SchoolProfileDto schoolProfile = new SchoolProfileDto();

        // 从索引1开始读取学校ID
        schoolProfile.setSchoolId(getCellValueAsString(row.getCell(1)));

        // 从第三列开始读取其他数据（索引2开始）
        int colIndex = 2;

        schoolProfile.setName(getCellValueAsString(row.getCell(colIndex++)));
        schoolProfile.setProvince(getCellValueAsString(row.getCell(colIndex++)));
        schoolProfile.setCity(getCellValueAsString(row.getCell(colIndex++)));
        schoolProfile.setDistrict(getCellValueAsString(row.getCell(colIndex++)));
        schoolProfile.setAuthority(getCellValueAsString(row.getCell(colIndex++)));
        schoolProfile.setHistoricAuthorities(getCellValueAsString(row.getCell(colIndex++)));
        schoolProfile.setLegacyHonor(getCellValueAsString(row.getCell(colIndex++)));
        schoolProfile.setLevel(getCellValueAsString(row.getCell(colIndex++)));
        schoolProfile.setNature(getCellValueAsString(row.getCell(colIndex++)));
        schoolProfile.setCategory(getCellValueAsString(row.getCell(colIndex++)));
        schoolProfile.setPostgraduate(getCellValueAsString(row.getCell(colIndex++)));
        schoolProfile.setBatch(getCellValueAsString(row.getCell(colIndex++)));
        schoolProfile.setGoatMajor(getCellValueAsString(row.getCell(colIndex++)));
        schoolProfile.setLegacyStrongSide(getCellValueAsString(row.getCell(colIndex++)));
        schoolProfile.setLegacyStrongMajor(getCellValueAsString(row.getCell(colIndex++)));
        schoolProfile.setDoubleFirstMajor(getCellValueAsString(row.getCell(colIndex++)));
        schoolProfile.setFourthEvaluateRoll(getCellValueAsString(row.getCell(colIndex++)));
        schoolProfile.setDistrictFlourishingIndustry(getCellValueAsString(row.getCell(colIndex++)));
        schoolProfile.setCityFlourishingIndustry(getCellValueAsString(row.getCell(colIndex++)));
        schoolProfile.setRecruitmentPolicy(getCellValueAsString(row.getCell(colIndex++)));
        schoolProfile.setRecruitmentPolicySourceTitle(getCellValueAsString(row.getCell(colIndex++)));
        schoolProfile.setRecruitmentPolicySourceContent(getCellValueAsString(row.getCell(colIndex++)));
        schoolProfile.setOriginCityFlourishingIndustry(getCellValueAsString(row.getCell(colIndex++)));
        schoolProfile.setEduRank(getCellValueAsString(row.getCell(colIndex++)));
        schoolProfile.setEduCharacteristic(getCellValueAsString(row.getCell(colIndex++)));
        schoolProfile.setEduHotness(getCellValueAsString(row.getCell(colIndex++)));
        schoolProfile.setEduIndex(getCellValueAsBigDecimal(row.getCell(colIndex++)));
        schoolProfile.setGaotuRank(getCellValueAsString(row.getCell(colIndex++)));
        schoolProfile.setGaotuBatch(getCellValueAsString(row.getCell(colIndex++)));
        schoolProfile.setFirstLevelMasterStation(getCellValueAsString(row.getCell(colIndex++)));
        schoolProfile.setFirstLevelDoctorStation(getCellValueAsString(row.getCell(colIndex++)));
        schoolProfile.setProfessionalDegreeMasterStation(getCellValueAsString(row.getCell(colIndex++)));
        schoolProfile.setProfessionalDegreeDoctorStation(getCellValueAsString(row.getCell(colIndex++)));
        schoolProfile.setUpgradeRatio(getCellValueAsString(row.getCell(colIndex++)));
        schoolProfile.setPostgraduateRecommendRatio(getCellValueAsString(row.getCell(colIndex++)));
        schoolProfile.setAcademicianNumber(getCellValueAsInteger(row.getCell(colIndex++)));
        schoolProfile.setOutstandingAlumniNumber(getCellValueAsInteger(row.getCell(colIndex++)));
        schoolProfile.setNationalSpecializedMajor(getCellValueAsString(row.getCell(colIndex++)));

        return schoolProfile;
    }

    /**
     * 获取单元格字符串值
     */
    private String getCellValueAsString(Cell cell) {
        if (cell == null) {
            return null;
        }

        switch (cell.getCellType()) {
            case STRING:
                return cell.getStringCellValue().trim();
            case NUMERIC:
                if (DateUtil.isCellDateFormatted(cell)) {
                    return cell.getDateCellValue().toString();
                } else {
                    // 对于数字，检查是否为整数
                    double numericValue = cell.getNumericCellValue();
                    if (numericValue == Math.floor(numericValue)) {
                        return String.valueOf((long) numericValue);
                    } else {
                        return String.valueOf(numericValue);
                    }
                }
            case BOOLEAN:
                return String.valueOf(cell.getBooleanCellValue());
            case FORMULA:
                try {
                    return cell.getStringCellValue().trim();
                } catch (Exception e) {
                    return String.valueOf(cell.getNumericCellValue());
                }
            default:
                return null;
        }
    }

    /**
     * 获取单元格BigDecimal值
     */
    private BigDecimal getCellValueAsBigDecimal(Cell cell) {
        if (cell == null) {
            return null;
        }

        try {
            switch (cell.getCellType()) {
                case NUMERIC:
                    return BigDecimal.valueOf(cell.getNumericCellValue());
                case STRING:
                    String value = cell.getStringCellValue().trim();
                    if (value.isEmpty()) {
                        return null;
                    }
                    return new BigDecimal(value);
                case FORMULA:
                    return BigDecimal.valueOf(cell.getNumericCellValue());
                default:
                    return null;
            }
        } catch (Exception e) {
            return null;
        }
    }

    /**
     * 获取单元格Integer值
     */
    private Integer getCellValueAsInteger(Cell cell) {
        if (cell == null) {
            return null;
        }

        try {
            switch (cell.getCellType()) {
                case NUMERIC:
                    return (int) cell.getNumericCellValue();
                case STRING:
                    String value = cell.getStringCellValue().trim();
                    if (value.isEmpty()) {
                        return null;
                    }
                    return Integer.parseInt(value);
                case FORMULA:
                    return (int) cell.getNumericCellValue();
                default:
                    return null;
            }
        } catch (Exception e) {
            return null;
        }
    }

    /**
     * 根据学校名称获取学校画像信息
     */
    public SchoolProfileDto getSchoolProfileByName(String name) {
        if (name == null || name.trim().isEmpty()) {
            return null;
        }
        return schoolProfileMap.get(name.trim());
    }

    /**
     * 根据学校ID获取学校画像信息
     */
    public SchoolProfileDto getSchoolProfileById(String schoolId) {
        if (schoolId == null || schoolId.trim().isEmpty()) {
            return new SchoolProfileDto();
        }
        return schoolProfileByIdMap.getOrDefault(schoolId.trim(),new SchoolProfileDto());
    }

    /**
     * 获取所有学校画像数据
     */
    public List<SchoolProfileDto> getAllSchoolProfiles() {
        return new ArrayList<>(schoolProfileList);
    }

    /**
     * 根据学校名称模糊查询学校画像
     */
    public List<SchoolProfileDto> getSchoolProfilesByName(String name) {
        if (name == null || name.trim().isEmpty()) {
            return new ArrayList<>();
        }

        String searchName = name.trim().toLowerCase();
        return schoolProfileList.stream()
                .filter(profile -> profile.getName() != null &&
                        profile.getName().toLowerCase().contains(searchName))
                .collect(ArrayList::new, (list, item) -> list.add(item), (list1, list2) -> list1.addAll(list2));
    }

    /**
     * 根据省份获取学校画像列表
     */
    public List<SchoolProfileDto> getSchoolProfilesByProvince(String province) {
        if (province == null || province.trim().isEmpty()) {
            return new ArrayList<>();
        }

        return schoolProfileList.stream()
                .filter(profile -> province.equals(profile.getProvince()))
                .collect(ArrayList::new, (list, item) -> list.add(item), (list1, list2) -> list1.addAll(list2));
    }

    /**
     * 根据城市获取学校画像列表
     */
    public List<SchoolProfileDto> getSchoolProfilesByCity(String city) {
        if (city == null || city.trim().isEmpty()) {
            return new ArrayList<>();
        }

        return schoolProfileList.stream()
                .filter(profile -> city.equals(profile.getCity()))
                .collect(ArrayList::new, (list, item) -> list.add(item), (list1, list2) -> list1.addAll(list2));
    }

    /**
     * 根据办学层次获取学校画像列表
     */
    public List<SchoolProfileDto> getSchoolProfilesByLevel(String level) {
        if (level == null || level.trim().isEmpty()) {
            return new ArrayList<>();
        }

        return schoolProfileList.stream()
                .filter(profile -> level.equals(profile.getLevel()))
                .collect(ArrayList::new, (list, item) -> list.add(item), (list1, list2) -> list1.addAll(list2));
    }

    /**
     * 根据办学性质获取学校画像列表
     */
    public List<SchoolProfileDto> getSchoolProfilesByNature(String nature) {
        if (nature == null || nature.trim().isEmpty()) {
            return new ArrayList<>();
        }

        return schoolProfileList.stream()
                .filter(profile -> nature.equals(profile.getNature()))
                .collect(ArrayList::new, (list, item) -> list.add(item), (list1, list2) -> list1.addAll(list2));
    }

    /**
     * 根据学校类别获取学校画像列表
     */
    public List<SchoolProfileDto> getSchoolProfilesByCategory(String category) {
        if (category == null || category.trim().isEmpty()) {
            return new ArrayList<>();
        }

        return schoolProfileList.stream()
                .filter(profile -> category.equals(profile.getCategory()))
                .collect(ArrayList::new, (list, item) -> list.add(item), (list1, list2) -> list1.addAll(list2));
    }

    /**
     * 根据录取批次获取学校画像列表
     */
    public List<SchoolProfileDto> getSchoolProfilesByBatch(String batch) {
        if (batch == null || batch.trim().isEmpty()) {
            return new ArrayList<>();
        }

        return schoolProfileList.stream()
                .filter(profile -> batch.equals(profile.getBatch()))
                .collect(ArrayList::new, (list, item) -> list.add(item), (list1, list2) -> list1.addAll(list2));
    }

    /**
     * 获取学校画像数据总数
     */
    public int getSchoolProfileCount() {
        return schoolProfileList.size();
    }
}
