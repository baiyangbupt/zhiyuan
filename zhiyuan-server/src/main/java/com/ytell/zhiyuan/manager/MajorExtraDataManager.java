package com.ytell.zhiyuan.manager;

import com.ytell.zhiyuan.model.dto.EmploymentRateDTO;
import com.ytell.zhiyuan.model.dto.SubjectPriorityDTO;
import com.ytell.zhiyuan.model.vo.MajorExtraDataVO;
import lombok.extern.slf4j.Slf4j;
import org.springframework.core.io.ClassPathResource;
import org.springframework.stereotype.Component;
import org.springframework.util.StringUtils;

import javax.annotation.PostConstruct;
import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;
import java.util.stream.Collectors;

/**
 * 专业补充数据管理器
 * 提供专业补充数据的查询功能
 */
@Slf4j
@Component
public class MajorExtraDataManager {

    private static final String MAJOR_EXTRA_DATA_FILE_PATH = "bizdata/major_extra_data.csv";

    /**
     * 所有专业补充数据缓存
     */
    private final List<MajorExtraDataVO> majorExtraDataList = new ArrayList<>();

    /**
     * 按一级分类缓存
     */
    private final Map<String, List<MajorExtraDataVO>> firstCategoryCache = new ConcurrentHashMap<>();

    /**
     * 按二级分类缓存
     */
    private final Map<String, List<MajorExtraDataVO>> secondCategoryCache = new ConcurrentHashMap<>();

    /**
     * 按二级分类ID缓存
     */
    private final Map<Integer, List<MajorExtraDataVO>> secondCategoryIdCache = new ConcurrentHashMap<>();

    /**
     * 按文理报考情况缓存
     */
    private final Map<String, List<MajorExtraDataVO>> artsScienceCache = new ConcurrentHashMap<>();

    /**
     * 按优势地域缓存
     */
    private final Map<String, List<MajorExtraDataVO>> advantageRegionCache = new ConcurrentHashMap<>();

    /**
     * 初始化加载专业补充数据
     */
    @PostConstruct
    public void init() {
        try {
            loadMajorExtraData();
            log.info("专业补充数据加载完成，共加载 {} 条数据", majorExtraDataList.size());
        } catch (Exception e) {
            log.error("加载专业补充数据失败", e);
        }
    }

    /**
     * 加载专业补充数据
     */
    private void loadMajorExtraData() throws IOException {
        ClassPathResource resource = new ClassPathResource(MAJOR_EXTRA_DATA_FILE_PATH);
        try (BufferedReader reader = new BufferedReader(
                new InputStreamReader(resource.getInputStream(), StandardCharsets.UTF_8))) {

            // 读取标题行
            String headerLine = reader.readLine();
            if (headerLine == null || !headerLine.startsWith("first_level_category")) {
                log.error("专业补充数据文件格式不正确，第一行应该是标题行");
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
                // 跳过空行
                if (line.trim().isEmpty()) {
                    continue;
                }

                try {
                    MajorExtraDataVO data = parseMajorExtraDataLine(line, headerMap);
                    if (data != null) {
                        majorExtraDataList.add(data);

                        // 构建缓存
                        buildCaches(data);
                        count++;
                    }
                } catch (Exception e) {
                    log.warn("解析专业补充数据行失败: {}", line, e);
                }
            }
            log.info("成功解析 {} 条专业补充数据", count);
        }
    }

    /**
     * 解析CSV行数据
     */
    private MajorExtraDataVO parseMajorExtraDataLine(String line, Map<String, Integer> headerMap) {
        if (line == null || line.trim().isEmpty()) {
            return null;
        }

        String[] fields = line.split(",", -1); // -1 保留空字段
        if (fields.length < 10) {
            log.warn("专业补充数据行字段数量不足: {}", line);
            return null;
        }

        MajorExtraDataVO data = new MajorExtraDataVO();

        // 使用表头映射获取字段值
        data.setFirstCategory(getFieldValue(fields, headerMap, "first_level_category"));

        // 解析文理报考情况，按"、"分割
        String artsScienceStr = getFieldValue(fields, headerMap, "admission_type");
        if (StringUtils.hasText(artsScienceStr)) {
            data.setArtsScience(Arrays.asList(artsScienceStr.split("、")));
        } else {
            data.setArtsScience(new ArrayList<>());
        }

        data.setSecondCategory(getFieldValue(fields, headerMap, "second_level_category"));
        data.setSubjectPriority(parseSubjectPriority(getFieldValue(fields, headerMap, "subject_priority")));
        data.setRemark(getFieldValue(fields, headerMap, "remarks"));
        data.setEmploymentRate(parseEmploymentRate(
                getFieldValue(fields, headerMap, "employment_rate_2023"),
                getFieldValue(fields, headerMap, "employment_rate_2024")
        ));

        // 解析优势地域，按"、"分割
        String advantageRegionsStr = getFieldValue(fields, headerMap, "advantageous_regions");
        if (StringUtils.hasText(advantageRegionsStr)) {
            data.setAdvantageRegions(Arrays.asList(advantageRegionsStr.split("、")));
        } else {
            data.setAdvantageRegions(new ArrayList<>());
        }

        // 解析一级分类ID
        String firstCategoryIdStr = getFieldValue(fields, headerMap, "first_level_category_id");
        if (StringUtils.hasText(firstCategoryIdStr)) {
            try {
                data.setFirstCategoryId(Integer.parseInt(firstCategoryIdStr));
            } catch (NumberFormatException e) {
                log.warn("解析一级分类ID失败: {}", firstCategoryIdStr);
            }
        }

        // 解析二级分类ID
        String secondCategoryIdStr = getFieldValue(fields, headerMap, "second_level_category_id");
        if (StringUtils.hasText(secondCategoryIdStr)) {
            try {
                data.setSecondCategoryId(Integer.parseInt(secondCategoryIdStr));
            } catch (NumberFormatException e) {
                log.warn("解析二级分类ID失败: {}", secondCategoryIdStr);
            }
        }

        return data;
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
     * 解析学科优先级字符串
     * 格式：政治（0.7）、历史（0.3）
     * 返回：List<SubjectPriorityDTO>
     */
    private List<SubjectPriorityDTO> parseSubjectPriority(String subjectPriorityStr) {
        List<SubjectPriorityDTO> result = new ArrayList<>();

        if (!StringUtils.hasText(subjectPriorityStr)) {
            return result;
        }

        try {
            // 按"、"分割多个学科
            String[] subjects = subjectPriorityStr.split("、");
            for (String subject : subjects) {
                subject = subject.trim();
                if (subject.isEmpty()) {
                    continue;
                }

                // 查找括号中的权重
                int leftBracket = subject.indexOf('（');
                int rightBracket = subject.indexOf('）');

                if (leftBracket > 0 && rightBracket > leftBracket) {
                    String subjectName = subject.substring(0, leftBracket).trim();
                    String ratioStr = subject.substring(leftBracket + 1, rightBracket).trim();

                    try {
                        Double ratio = Double.parseDouble(ratioStr);
                        result.add(new SubjectPriorityDTO(subjectName, ratio));
                    } catch (NumberFormatException e) {
                        log.warn("解析学科权重失败: {}", ratioStr);
                        // 如果权重解析失败，设置为默认值1.0
                        result.add(new SubjectPriorityDTO(subjectName, 1.0));
                    }
                } else {
                    // 如果没有括号，设置为默认权重1.0
                    result.add(new SubjectPriorityDTO(subject, 1.0));
                }
            }
        } catch (Exception e) {
            log.error("解析学科优先级失败: {}", subjectPriorityStr, e);
        }

        return result;
    }

    /**
     * 解析就业率信息
     * 将2023年和2024年的就业率合并为一个数组
     */
    private List<EmploymentRateDTO> parseEmploymentRate(String rate2023, String rate2024) {
        List<EmploymentRateDTO> result = new ArrayList<>();

        // 添加2023年就业率
        if (StringUtils.hasText(rate2023)) {
            result.add(new EmploymentRateDTO(2023, rate2023.trim()));
        }

        // 添加2024年就业率
        if (StringUtils.hasText(rate2024)) {
            result.add(new EmploymentRateDTO(2024, rate2024.trim()));
        }

        return result;
    }

    /**
     * 构建各种缓存
     */
    private void buildCaches(MajorExtraDataVO data) {
        // 按一级分类缓存
        firstCategoryCache.computeIfAbsent(data.getFirstCategory(), k -> new ArrayList<>()).add(data);

        // 按二级分类缓存
        secondCategoryCache.computeIfAbsent(data.getSecondCategory(), k -> new ArrayList<>()).add(data);

        // 按二级分类ID缓存
        if (data.getSecondCategoryId() != null) {
            secondCategoryIdCache.computeIfAbsent(data.getSecondCategoryId(), k -> new ArrayList<>()).add(data);
        }

        // 按文理报考情况缓存
        if (data.getArtsScience() != null) {
            for (String artsScience : data.getArtsScience()) {
                artsScienceCache.computeIfAbsent(artsScience.trim(), k -> new ArrayList<>()).add(data);
            }
        }

        // 按优势地域缓存
        if (data.getAdvantageRegions() != null) {
            for (String region : data.getAdvantageRegions()) {
                advantageRegionCache.computeIfAbsent(region.trim(), k -> new ArrayList<>()).add(data);
            }
        }
    }

    /**
     * 多条件查询专业补充数据
     *
     * @param artsScienceList 文理报考情况列表（可选）
     * @param subjectList     优势学科列表（可选）
     * @param regionList      优势地域列表（可选）
     * @return 符合条件的专业补充数据列表
     */
    public List<MajorExtraDataVO> searchMajorExtraData(List<String> artsScienceList,
                                                       List<String> subjectList,
                                                       List<String> regionList) {
        // 如果所有条件都为空，返回所有数据
        if ((artsScienceList == null || artsScienceList.isEmpty()) &&
                (subjectList == null || subjectList.isEmpty()) &&
                (regionList == null || regionList.isEmpty())) {
            return new ArrayList<>(majorExtraDataList);
        }

        return majorExtraDataList.stream()
                .filter(data -> matchArtsScience(data, artsScienceList))
                .filter(data -> matchSubject(data, subjectList))
                .filter(data -> matchRegion(data, regionList))
                .collect(Collectors.toList());
    }

    /**
     * 匹配文理报考情况
     */
    private boolean matchArtsScience(MajorExtraDataVO data, List<String> artsScienceList) {
        if (artsScienceList == null || artsScienceList.isEmpty()) {
            return true;
        }

        if (data.getArtsScience() == null || data.getArtsScience().isEmpty()) {
            return false;
        }

        // 检查是否有交集
        return data.getArtsScience().stream()
                .anyMatch(artsScience -> artsScienceList.contains(artsScience.trim()));
    }

    /**
     * 匹配优势学科（从学科优先级字段中匹配）
     */
    private boolean matchSubject(MajorExtraDataVO data, List<String> subjectList) {
        if (subjectList == null || subjectList.isEmpty()) {
            return true;
        }

        if (data.getSubjectPriority() == null || data.getSubjectPriority().isEmpty()) {
            return false;
        }

        // 检查学科优先级中是否包含任一指定学科
        return subjectList.stream()
                .anyMatch(subject -> data.getSubjectPriority().stream()
                        .anyMatch(priority -> priority.getSubject().equals(subject.trim())));
    }

    /**
     * 匹配优势地域
     */
    private boolean matchRegion(MajorExtraDataVO data, List<String> regionList) {
        if (regionList == null || regionList.isEmpty()) {
            return true;
        }

        if (data.getAdvantageRegions() == null || data.getAdvantageRegions().isEmpty()) {
            return false;
        }

        // 检查是否有交集
        return data.getAdvantageRegions().stream()
                .anyMatch(region -> regionList.contains(region.trim()));
    }

    /**
     * 根据一级分类查询专业补充数据
     *
     * @param firstCategory 一级分类
     * @return 该一级分类的专业补充数据列表
     */
    public List<MajorExtraDataVO> getByFirstCategory(String firstCategory) {
        if (!StringUtils.hasText(firstCategory)) {
            return new ArrayList<>();
        }

        List<MajorExtraDataVO> result = firstCategoryCache.get(firstCategory.trim());
        return result != null ? new ArrayList<>(result) : new ArrayList<>();
    }

    /**
     * 根据二级分类查询专业补充数据
     *
     * @param secondCategory 二级分类
     * @return 该二级分类的专业补充数据列表
     */
    public List<MajorExtraDataVO> getBySecondCategory(String secondCategory) {
        if (!StringUtils.hasText(secondCategory)) {
            return new ArrayList<>();
        }

        List<MajorExtraDataVO> result = secondCategoryCache.get(secondCategory.trim());
        return result != null ? new ArrayList<>(result) : new ArrayList<>();
    }

    /**
     * 根据文理报考情况查询专业补充数据
     *
     * @param artsScience 文理报考情况
     * @return 该文理报考情况的专业补充数据列表
     */
    public List<MajorExtraDataVO> getByArtsScience(String artsScience) {
        if (!StringUtils.hasText(artsScience)) {
            return new ArrayList<>();
        }

        List<MajorExtraDataVO> result = artsScienceCache.get(artsScience.trim());
        return result != null ? new ArrayList<>(result) : new ArrayList<>();
    }

    /**
     * 根据优势地域查询专业补充数据
     *
     * @param region 优势地域
     * @return 该优势地域的专业补充数据列表
     */
    public List<MajorExtraDataVO> getByAdvantageRegion(String region) {
        if (!StringUtils.hasText(region)) {
            return new ArrayList<>();
        }

        List<MajorExtraDataVO> result = advantageRegionCache.get(region.trim());
        return result != null ? new ArrayList<>(result) : new ArrayList<>();
    }

    /**
     * 获取所有专业补充数据
     *
     * @return 所有专业补充数据列表
     */
    public List<MajorExtraDataVO> getAllMajorExtraData() {
        return new ArrayList<>(majorExtraDataList);
    }

    /**
     * 获取所有一级分类
     *
     * @return 所有一级分类列表
     */
    public List<String> getAllFirstCategories() {
        return new ArrayList<>(firstCategoryCache.keySet());
    }

    /**
     * 获取所有二级分类
     *
     * @return 所有二级分类列表
     */
    public List<String> getAllSecondCategories() {
        return new ArrayList<>(secondCategoryCache.keySet());
    }

    /**
     * 获取所有二级分类ID
     *
     * @return 所有二级分类ID列表
     */
    public List<Integer> getAllSecondCategoryIds() {
        return new ArrayList<>(secondCategoryIdCache.keySet());
    }

    /**
     * 获取所有文理报考情况
     *
     * @return 所有文理报考情况列表
     */
    public List<String> getAllArtsScience() {
        return new ArrayList<>(artsScienceCache.keySet());
    }

    /**
     * 获取所有优势地域
     *
     * @return 所有优势地域列表
     */
    public List<String> getAllAdvantageRegions() {
        return new ArrayList<>(advantageRegionCache.keySet());
    }

    /**
     * 获取专业补充数据总数
     *
     * @return 专业补充数据总数
     */
    public int getTotalCount() {
        return majorExtraDataList.size();
    }

    /**
     * 根据二级分类ID查询专业补充数据
     *
     * @param secondCategoryId 二级分类ID
     * @return 该二级分类ID的专业补充数据列表
     */
    public List<MajorExtraDataVO> getBySecondCategoryId(Integer secondCategoryId) {
        if (secondCategoryId == null) {
            return new ArrayList<>();
        }

        List<MajorExtraDataVO> result = secondCategoryIdCache.get(secondCategoryId);
        return result != null ? new ArrayList<>(result) : new ArrayList<>();
    }

    /**
     * 根据二级分类ID查询单个专业补充数据详情
     *
     * @param secondCategoryId 二级分类ID
     * @return 该二级分类ID的专业补充数据详情，如果不存在返回null
     */
    public MajorExtraDataVO getDetailBySecondCategoryId(Integer secondCategoryId) {
        if (secondCategoryId == null) {
            return null;
        }

        List<MajorExtraDataVO> result = secondCategoryIdCache.get(secondCategoryId);
        if (result != null && !result.isEmpty()) {
            return result.get(0); // 返回第一个匹配的数据
        }
        return null;
    }

}
