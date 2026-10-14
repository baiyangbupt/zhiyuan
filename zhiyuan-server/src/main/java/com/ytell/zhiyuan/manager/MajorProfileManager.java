package com.ytell.zhiyuan.manager;

import com.ytell.zhiyuan.common.util.SubjectRequirementParser;
import com.ytell.zhiyuan.model.dto.MajorProfileDto;
import lombok.extern.slf4j.Slf4j;
import org.apache.poi.ss.usermodel.*;
import org.springframework.core.io.ClassPathResource;
import org.springframework.stereotype.Component;

import javax.annotation.PostConstruct;
import java.io.InputStream;
import java.math.BigDecimal;
import java.text.SimpleDateFormat;
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;

/**
 * 专业画像数据管理器
 * 用于加载和管理专业画像Excel数据
 *
 * @author gaotu-assistant
 * @date 2024-12-19
 */
@Slf4j
@Component
public class MajorProfileManager {

    /**
     * Excel文件路径
     */
    private static final String EXCEL_FILE_PATH = "bizdata/major_profile-0615.xlsx";
    /**
     * 日期格式化器
     */
    private static final SimpleDateFormat DATE_FORMAT = new SimpleDateFormat("yyyy-MM-dd HH:mm:ss");
    /**
     * 专业画像数据缓存 - 以专业代码为key
     */
    private final Map<String, MajorProfileDto> majorProfileMap = new ConcurrentHashMap<>();
    private final Map<String, MajorProfileDto> majorProfileMapByName = new ConcurrentHashMap<>();
    private final Map<String, MajorProfileDto> majorProfileMapById = new ConcurrentHashMap<>();
    /**
     * 专业画像数据列表缓存
     */
    private final List<MajorProfileDto> majorProfileList = new ArrayList<>();

    /**
     * 初始化方法，加载Excel数据到内存
     */
    @PostConstruct
    public void init() {
        loadMajorProfileData();
        log.info("专业画像数据加载完成，共加载 {} 条数据", majorProfileList.size());
    }

    /**
     * 加载专业画像Excel数据
     */
    private void loadMajorProfileData() {
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
                        MajorProfileDto majorProfile = parseRowToMajorProfile(row);
                        if (majorProfile != null && majorProfile.getMajorCode() != null) {
                            majorProfileList.add(majorProfile);
                            majorProfileMap.put(majorProfile.getMajorCode(), majorProfile);
                            majorProfileMapByName.put(majorProfile.getName(), majorProfile);
                            if (majorProfile.getId() != null) {
                                majorProfileMapById.put(majorProfile.getId(), majorProfile);
                            }
                        }
                    } catch (Exception e) {
                        log.warn("解析第 {} 行数据失败: {}", rowIndex + 1, e.getMessage());
                    }
                }
            }
        } catch (Exception e) {
            log.error("加载专业画像数据失败", e);
            throw new RuntimeException("加载专业画像数据失败", e);
        }
    }

    /**
     * 将Excel行数据解析为MajorProfileDto对象
     */
    private MajorProfileDto parseRowToMajorProfile(Row row) {
        MajorProfileDto majorProfile = new MajorProfileDto();

        // 从第二列开始读取数据（索引1开始）
        int colIndex = 1;

        // 读取id字段
        majorProfile.setId(getCellValueAsString(row.getCell(colIndex++)));

        majorProfile.setMajorCode(getCellValueAsString(row.getCell(colIndex++)));
        majorProfile.setName(getCellValueAsString(row.getCell(colIndex++)));
        majorProfile.setMajorLevel(getCellValueAsString(row.getCell(colIndex++)));
        majorProfile.setCategoryId(getCellValueAsString(row.getCell(colIndex++)));
        majorProfile.setSubCategoryId(getCellValueAsString(row.getCell(colIndex++)));
        majorProfile.setWRatio(getCellValueAsBigDecimal(row.getCell(colIndex++)));
        majorProfile.setLRatio(getCellValueAsBigDecimal(row.getCell(colIndex++)));
        majorProfile.setMaleRatio(getCellValueAsBigDecimal(row.getCell(colIndex++)));
        majorProfile.setFemaleRatio(getCellValueAsBigDecimal(row.getCell(colIndex++)));
        majorProfile.setStudyTime(getCellValueAsString(row.getCell(colIndex++)));
        majorProfile.setDegree(getCellValueAsString(row.getCell(colIndex++)));
        majorProfile.setSynopsisInfo(getCellValueAsString(row.getCell(colIndex++)));
        majorProfile.setTrainObjective(getCellValueAsString(row.getCell(colIndex++)));
        majorProfile.setTrainDemand(getCellValueAsString(row.getCell(colIndex++)));
        majorProfile.setSubjectDemand(getCellValueAsString(row.getCell(colIndex++)));
        majorProfile.setKnowledge(getCellValueAsString(row.getCell(colIndex++)));
        majorProfile.setPostgraduate(getCellValueAsString(row.getCell(colIndex++)));
        majorProfile.setCourse(getCellValueAsString(row.getCell(colIndex++)));
        majorProfile.setJobOrientation(getCellValueAsString(row.getCell(colIndex++)));
        majorProfile.setPublicFigure(getCellValueAsString(row.getCell(colIndex++)));
        majorProfile.setInternship(getCellValueAsString(row.getCell(colIndex++)));
        majorProfile.setQualification(getCellValueAsString(row.getCell(colIndex++)));
        majorProfile.setUpgradOrientation(getCellValueAsString(row.getCell(colIndex++)));
        String selectInfo = getCellValueAsString(row.getCell(colIndex++));
        majorProfile.setSelectInfo(selectInfo);
        String selectGroup = getCellValueAsString(row.getCell(colIndex++));
        majorProfile.setSelectGroup(selectGroup);
        majorProfile.setSelectLimit(convertSelectInfoToSelectLimit(selectInfo, selectGroup));
        majorProfile.setCreatedBy(getCellValueAsString(row.getCell(colIndex++)));
        majorProfile.setCreateTime(getCellValueAsDate(row.getCell(colIndex++)));
        majorProfile.setTenantCode(getCellValueAsString(row.getCell(colIndex++)));
        majorProfile.setUpdatedBy(getCellValueAsString(row.getCell(colIndex++)));
        majorProfile.setUpdateTime(getCellValueAsDate(row.getCell(colIndex++)));
        majorProfile.setSubjectTendencySource(getCellValueAsString(row.getCell(colIndex++)));
        majorProfile.setSubjectTendency(getCellValueAsString(row.getCell(colIndex++)));
        majorProfile.setSubCategory(getCellValueAsString(row.getCell(colIndex++)));
        majorProfile.setCategory(getCellValueAsString(row.getCell(colIndex++)));
        majorProfile.setSubjectDivisionTendency(getCellValueAsString(row.getCell(colIndex++)));
        majorProfile.setGenderTendency(getCellValueAsString(row.getCell(colIndex++)));
        majorProfile.setPersonalityTendency(getCellValueAsString(row.getCell(colIndex++)));
        majorProfile.setGraduateTendency(getCellValueAsString(row.getCell(colIndex++)));
        majorProfile.setProfession(getCellValueAsString(row.getCell(colIndex++)));
        majorProfile.setIndustry(getCellValueAsString(row.getCell(colIndex++)));
        majorProfile.setWorkUnit(getCellValueAsString(row.getCell(colIndex++)));
        majorProfile.setWorkStyle(getCellValueAsString(row.getCell(colIndex++)));
        majorProfile.setJobHotnessWeight(getCellValueAsBigDecimal(row.getCell(colIndex++)));
        majorProfile.setInterestTendency(getCellValueAsString(row.getCell(colIndex++)));

        return majorProfile;
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
                    return DATE_FORMAT.format(cell.getDateCellValue());
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
     * 获取单元格Date值
     */
    private Date getCellValueAsDate(Cell cell) {
        if (cell == null) {
            return null;
        }

        try {
            switch (cell.getCellType()) {
                case NUMERIC:
                    if (DateUtil.isCellDateFormatted(cell)) {
                        return cell.getDateCellValue();
                    } else {
                        return null;
                    }
                case STRING:
                    String value = cell.getStringCellValue().trim();
                    if (value.isEmpty()) {
                        return null;
                    }
                    return DATE_FORMAT.parse(value);
                default:
                    return null;
            }
        } catch (Exception e) {
            return null;
        }
    }

    /**
     * 根据专业代码获取专业画像信息
     */
    public MajorProfileDto getMajorProfileByCode(String majorCode) {
        if (majorCode == null || majorCode.trim().isEmpty()) {
            return null;
        }
        return majorProfileMap.get(majorCode.trim());
    }

    /**
     * 根据ID获取专业画像信息
     */
    public MajorProfileDto getMajorProfileById(String id) {
        if (id == null || id.trim().isEmpty()) {
            return null;
        }
        return majorProfileMapById.get(id.trim());
    }

    /**
     * 根据专业名称获取专业画像信息
     */
    public MajorProfileDto getMajorProfileByName(String name) {
        if (name == null || name.trim().isEmpty()) {
            return null;
        }
        return majorProfileMapByName.get(name.trim());
    }

    /**
     * 获取所有专业画像数据
     */
    public List<MajorProfileDto> getAllMajorProfiles() {
        return new ArrayList<>(majorProfileList);
    }

    /**
     * 根据专业名称模糊查询专业画像
     */
    public List<MajorProfileDto> getMajorProfilesByName(String name) {
        if (name == null || name.trim().isEmpty()) {
            return new ArrayList<>();
        }

        String searchName = name.trim().toLowerCase();
        return majorProfileList.stream()
                .filter(profile -> profile.getName() != null &&
                        profile.getName().toLowerCase().contains(searchName))
                .collect(ArrayList::new, (list, item) -> list.add(item), (list1, list2) -> list1.addAll(list2));
    }

    /**
     * 根据类别ID获取专业画像列表
     */
    public List<MajorProfileDto> getMajorProfilesByCategoryId(String categoryId) {
        if (categoryId == null || categoryId.trim().isEmpty()) {
            return new ArrayList<>();
        }

        return majorProfileList.stream()
                .filter(profile -> categoryId.equals(profile.getCategoryId()))
                .collect(ArrayList::new, (list, item) -> list.add(item), (list1, list2) -> list1.addAll(list2));
    }

    /**
     * 根据专业层次获取专业画像列表
     */
    public List<MajorProfileDto> getMajorProfilesByLevel(String majorLevel) {
        if (majorLevel == null || majorLevel.trim().isEmpty()) {
            return new ArrayList<>();
        }

        return majorProfileList.stream()
                .filter(profile -> majorLevel.equals(profile.getMajorLevel()))
                .collect(ArrayList::new, (list, item) -> list.add(item), (list1, list2) -> list1.addAll(list2));
    }

    /**
     * 获取专业画像数据总数
     */
    public int getMajorProfileCount() {
        return majorProfileList.size();
    }

    /**
     * 将 selectInfo / selectGroup 转换为 selectLimit（二维列表：外层"或"、内层"与"）。
     *
     * <p>2026-10-14 修复（选科适配 P0）：此前只认自然语言里少数形态，且"或"表达式
     * （如"化或生"）解析成空 → {@code selectLimit} 恒空 → 选科校验恒"满足"（假阳性，全模式）。
     * 现在统一走 {@link SubjectRequirementParser}：</p>
     * <ol>
     *   <li>selectInfo 本身就是两位组合码（如 {@code 010205,010305}）→ 按码解析；
     *       数据里组合码在 selectGroup 列（如 010205→物理+历史+化学），selectInfo 兜底同路；</li>
     *   <li>自然语言（物 / 物和化 / 化或生 / 物和(化或生) / 物理或化学）→ 按 和=与、或=或 解析；</li>
     *   <li>selectInfo 非空且非"不限"、但自然语言解析不出时，退回 selectGroup 组合码。</li>
     * </ol>
     * <p>"不限"或空 → 空列表（无选科限制）。</p>
     *
     * @param selectInfo  原始选科限制信息（自然语言/组合码）
     * @param selectGroup 组合码列（两位一组、逗号分隔的合法组合枚举）
     * @return 转换后的选科限制列表；解析不出时为空列表（不硬猜）
     */
    private List<List<String>> convertSelectInfoToSelectLimit(String selectInfo, String selectGroup) {
        List<List<String>> byCodes = SubjectRequirementParser.parseCombinationCodes(selectInfo);
        if (!byCodes.isEmpty()) {
            return byCodes;
        }
        List<List<String>> byText = SubjectRequirementParser.parseOptions(selectInfo);
        if (!byText.isEmpty()) {
            return byText;
        }
        String info = selectInfo == null ? "" : selectInfo.trim();
        boolean explicitlyNoConstraint = info.isEmpty() || info.contains("不限");
        if (!explicitlyNoConstraint) {
            List<List<String>> fallback = SubjectRequirementParser.parseCombinationCodes(selectGroup);
            if (!fallback.isEmpty()) {
                return fallback;
            }
        }
        return new ArrayList<>();
    }
}