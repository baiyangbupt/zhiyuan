package com.ytell.zhiyuan.manager;

import com.google.common.base.Strings;
import com.ytell.zhiyuan.model.dto.MajorCategoryProfileDto;
import lombok.extern.slf4j.Slf4j;
import org.apache.poi.ss.usermodel.*;
import org.springframework.core.io.ClassPathResource;
import org.springframework.stereotype.Component;

import javax.annotation.PostConstruct;
import javax.annotation.Resource;
import java.io.InputStream;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.concurrent.ConcurrentHashMap;

/**
 * 专业类概述数据管理器
 * 用于加载和管理专业类概述Excel数据
 *
 * @author gaotu-assistant
 * @date 2024-12-19
 */
@Slf4j
@Component
public class MajorCategoryProfileManager {

    /**
     * Excel文件路径
     */
    private static final String EXCEL_FILE_PATH = "bizdata/major_category_profile.xlsx";
    /**
     * 专业类概述数据缓存 - 以专业类名称为key
     */
    private final Map<String, MajorCategoryProfileDto> majorCategoryProfileMap = new ConcurrentHashMap<>();
    /**
     * 专业类概述数据缓存 - 以专业类ID为key
     */
    private final Map<String, MajorCategoryProfileDto> majorCategoryProfileIdMap = new ConcurrentHashMap<>();
    /**
     * 专业类概述数据列表缓存
     */
    private final List<MajorCategoryProfileDto> majorCategoryProfileList = new ArrayList<>();
    @Resource
    private MajorMappingManager majorMappingManager;

    /**
     * 初始化方法，加载Excel数据到内存
     */
    @PostConstruct
    public void init() {
        loadMajorCategoryProfileData();
        log.info("专业类概述数据加载完成，共加载 {} 条数据", majorCategoryProfileList.size());
    }

    /**
     * 加载专业类概述Excel数据
     */
    private void loadMajorCategoryProfileData() {
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
                        MajorCategoryProfileDto majorCategoryProfile = parseRowToMajorCategoryProfile(row);
                        if (majorCategoryProfile != null && majorCategoryProfile.getMajorCategory() != null) {
                            String majorName = majorCategoryProfile.getMajorCategory().trim();
                            if (!majorName.isEmpty()) {
                                String majorId = majorMappingManager.getSecondLevelIdByName(majorName);
                                if (!Strings.isNullOrEmpty(majorId)) {
                                    majorCategoryProfile.setMajorCategoryId(majorId);
                                    majorCategoryProfileIdMap.put(majorId, majorCategoryProfile);
                                } else {
                                    log.warn("未在 MajorMappingManager 中找到专业类 [{}] 的ID", majorName);
                                }
                                majorCategoryProfileList.add(majorCategoryProfile);
                                majorCategoryProfileMap.put(majorName, majorCategoryProfile);
                            }
                        }
                    } catch (Exception e) {
                        log.warn("解析第 {} 行数据失败: {}", rowIndex + 1, e.getMessage());
                    }
                }
            }
        } catch (Exception e) {
            log.error("加载专业类概述数据失败", e);
            throw new RuntimeException("加载专业类概述数据失败", e);
        }
    }

    /**
     * 将Excel行数据解析为MajorCategoryProfileDto对象
     * 注意：跳过第一列，从第二列开始读取
     */
    private MajorCategoryProfileDto parseRowToMajorCategoryProfile(Row row) {
        MajorCategoryProfileDto majorCategoryProfile = new MajorCategoryProfileDto();

        // 从第二列开始读取数据（索引1开始）
        int colIndex = 1;

        majorCategoryProfile.setMajorCategory(getCellValueAsString(row.getCell(colIndex++)));
        majorCategoryProfile.setMajorOverview(getCellValueAsString(row.getCell(colIndex++)));
        majorCategoryProfile.setStudyCourses(getCellValueAsString(row.getCell(colIndex++)));
        majorCategoryProfile.setEmploymentDirection(getCellValueAsString(row.getCell(colIndex++)));
        majorCategoryProfile.setSalaryStatus(getCellValueAsString(row.getCell(colIndex++)));
        majorCategoryProfile.setEmploymentRegion(getCellValueAsString(row.getCell(colIndex++)));

        return majorCategoryProfile;
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

    public MajorCategoryProfileDto getMajorCategoryProfile(String name,String id) {
        MajorCategoryProfileDto res=null;
        if(!Strings.isNullOrEmpty(id)) {
            res= getMajorCategoryProfileById(id);
        }
        if(!Strings.isNullOrEmpty(name)&&res==null) {
            res= getMajorCategoryProfileByName(name);
        }
        return res;
    }

    /**
     * 根据专业类Id获取专业类概述信息
     */
    public MajorCategoryProfileDto getMajorCategoryProfileById(String id) {
        if (Strings.isNullOrEmpty(id)) {
            return null;
        }
        return majorCategoryProfileIdMap.get(id.trim());
    }

    /**
     * 根据专业类名称获取专业类概述信息
     */
    public MajorCategoryProfileDto getMajorCategoryProfileByName(String majorCategory) {
        if (majorCategory == null || majorCategory.trim().isEmpty()) {
            return null;
        }
        return majorCategoryProfileMap.get(majorCategory.trim());
    }

    /**
     * 获取所有专业类概述数据
     */
    public List<MajorCategoryProfileDto> getAllMajorCategoryProfiles() {
        return new ArrayList<>(majorCategoryProfileList);
    }

    /**
     * 根据专业类名称模糊查询专业类概述
     */
    public List<MajorCategoryProfileDto> getMajorCategoryProfilesByName(String majorCategory) {
        if (majorCategory == null || majorCategory.trim().isEmpty()) {
            return new ArrayList<>();
        }

        String searchName = majorCategory.trim().toLowerCase();
        return majorCategoryProfileList.stream()
                .filter(profile -> profile.getMajorCategory() != null &&
                        profile.getMajorCategory().toLowerCase().contains(searchName))
                .collect(ArrayList::new, (list, item) -> list.add(item), (list1, list2) -> list1.addAll(list2));
    }

    /**
     * 检查指定专业类是否存在
     */
    public boolean existsMajorCategory(String majorCategory) {
        if (majorCategory == null || majorCategory.trim().isEmpty()) {
            return false;
        }
        return majorCategoryProfileMap.containsKey(majorCategory.trim());
    }

    /**
     * 获取专业类概述数据总数
     */
    public int getMajorCategoryProfileCount() {
        return majorCategoryProfileList.size();
    }

    /**
     * 获取所有专业类名称列表
     */
    public List<String> getAllMajorCategoryNames() {
        return majorCategoryProfileList.stream()
                .map(MajorCategoryProfileDto::getMajorCategory)
                .filter(Objects::nonNull)
                .collect(ArrayList::new, (list, item) -> list.add(item), (list1, list2) -> list1.addAll(list2));
    }
}
