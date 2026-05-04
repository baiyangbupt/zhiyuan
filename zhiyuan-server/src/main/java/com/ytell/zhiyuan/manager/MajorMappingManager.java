package com.ytell.zhiyuan.manager;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ytell.zhiyuan.model.dto.MajorDataResponse;
import com.ytell.zhiyuan.model.dto.MajorInfo;
import com.ytell.zhiyuan.model.dto.MajorMappingResult;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.core.io.ClassPathResource;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;

import javax.annotation.PostConstruct;
import java.io.IOException;
import java.io.InputStream;
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;

/**
 * 专业映射服务
 * 提供专业数据的加载和查询功能
 */
@Slf4j
@Service
public class MajorMappingManager {

    /**
     * 教育层次枚举
     */
    public enum EducationLevel {
        BACHELOR("本科"),
        ASSOCIATE("专科"),
        ALL("全部");

        private final String displayName;

        EducationLevel(String displayName) {
            this.displayName = displayName;
        }

        public String getDisplayName() {
            return displayName;
        }

    }

    /**
     * 三级专业ID -> 二级专业ID的映射
     */
    private final Map<String, String> thirdToSecondMapping = new ConcurrentHashMap<>();
    /**
     * 二级专业ID -> 三级专业ID列表的映射
     */
    private final Map<String, List<String>> secondToThirdMapping = new ConcurrentHashMap<>();
    /**
     * 所有专业信息的映射 (ID -> MajorInfo)
     */
    private final Map<String, MajorInfo> allMajorMapping = new ConcurrentHashMap<>();
    /**
     * 一级专业名称 -> 一级专业ID映射
     */
    private final Map<String, String> firstLevelNameToIdMapping = new ConcurrentHashMap<>();
    /**
     * 二级专业名称 -> 二级专业ID映射
     */
    private final Map<String, String> secondLevelNameToIdMapping = new ConcurrentHashMap<>();
    @Autowired
    private ObjectMapper objectMapper;

    /**
     * 初始化加载专业映射数据
     */
    @PostConstruct
    public void init() {
        log.info("开始初始化专业映射数据...");
        try {
            // 加载本科专业数据
            loadMajorData("bizdata/major_bachelor.json", "本科");

            // 加载专科专业数据
            loadMajorData("bizdata/major_associate.json", "专科");

            log.info("专业映射数据初始化完成，共加载 {} 个专业信息", allMajorMapping.size());
            log.info("三级到二级映射数量: {}", thirdToSecondMapping.size());
            log.info("二级到三级映射数量: {}", secondToThirdMapping.size());

        } catch (Exception e) {
            log.error("加载专业映射数据失败", e);
            throw new RuntimeException("专业映射数据初始化失败", e);
        }
    }

    /**
     * 加载指定的专业数据文件
     */
    private void loadMajorData(String filePath, String type) throws IOException {
        log.info("开始加载{}专业数据: {}", type, filePath);

        ClassPathResource resource = new ClassPathResource(filePath);
        try (InputStream inputStream = resource.getInputStream()) {
            MajorDataResponse response = objectMapper.readValue(inputStream, MajorDataResponse.class);

            if (response.getCode() == 0 && response.getData() != null) {
                for (MajorInfo firstLevel : response.getData()) {
                    processMajorInfo(firstLevel);
                }
                log.info("{}专业数据加载完成", type);
            } else {
                log.warn("{}专业数据格式异常，code: {}", type, response.getCode());
            }
        }
    }

    /**
     * 递归处理专业信息，建立映射关系
     */
    private void processMajorInfo(MajorInfo majorInfo) {
        if (majorInfo == null || !StringUtils.hasText(majorInfo.getId())) {
            return;
        }

        // 保存到全量映射中
        allMajorMapping.put(majorInfo.getId(), majorInfo);
        if (StringUtils.hasText(majorInfo.getLabel())) {
            String nameKey = majorInfo.getLabel().trim();
            if (isFirstLevel(majorInfo)) {
                putIfAbsentWithWarn(firstLevelNameToIdMapping, nameKey, majorInfo.getId(), "一级");
            } else if (isSecondLevel(majorInfo)) {
                putIfAbsentWithWarn(secondLevelNameToIdMapping, nameKey, majorInfo.getId(), "二级");
            }
        }

        // 如果有子级专业，递归处理
        if (majorInfo.getChildren() != null && !majorInfo.getChildren().isEmpty()) {
            for (MajorInfo child : majorInfo.getChildren()) {
                processMajorInfo(child);

                // 建立父子映射关系
                if (StringUtils.hasText(child.getParentId())) {
                    // 如果子级有majorCode，说明是三级专业，建立三级到二级的映射
                    if (StringUtils.hasText(child.getMajorCode())) {
                        thirdToSecondMapping.put(child.getId(), child.getParentId());

                        // 建立二级到三级的映射
                        secondToThirdMapping.computeIfAbsent(child.getParentId(), k -> new ArrayList<>())
                                .add(child.getId());
                    }
                }
            }
        }
    }

    /**
     * 根据三级专业ID查询其二级专业ID
     *
     * @param thirdLevelId 三级专业ID
     * @return 二级专业ID，如果未找到返回null
     */
    public String getSecondLevelIdByThirdLevelId(String thirdLevelId) {
        if (!StringUtils.hasText(thirdLevelId)) {
            return null;
        }
        return thirdToSecondMapping.get(thirdLevelId);
    }

    /**
     * 根据二级专业ID查询其所有三级专业ID列表
     *
     * @param secondLevelId 二级专业ID
     * @return 三级专业ID列表，如果未找到返回空列表
     */
    public List<String> getThirdLevelIdsBySecondLevelId(String secondLevelId) {
        if (!StringUtils.hasText(secondLevelId)) {
            return Collections.emptyList();
        }
        return secondToThirdMapping.getOrDefault(secondLevelId, Collections.emptyList());
    }

    /**
     * 根据专业ID获取专业信息
     *
     * @param majorId 专业ID
     * @return 专业信息，如果未找到返回null
     */
    public MajorInfo getMajorInfo(String majorId) {
        if (!StringUtils.hasText(majorId)) {
            return null;
        }
        return allMajorMapping.get(majorId);
    }

    /**
     * 根据三级专业ID获取其完整的专业信息（包含二级专业信息）
     *
     * @param thirdLevelId 三级专业ID
     * @return 包含三级和二级专业信息的Map
     */
    public Map<String, MajorInfo> getCompleteInfoByThirdLevelId(String thirdLevelId) {
        Map<String, MajorInfo> result = new HashMap<>();

        // 获取三级专业信息
        MajorInfo thirdMajor = getMajorInfo(thirdLevelId);
        if (thirdMajor != null) {
            result.put("thirdLevel", thirdMajor);

            // 获取二级专业信息
            String secondLevelId = getSecondLevelIdByThirdLevelId(thirdLevelId);
            if (StringUtils.hasText(secondLevelId)) {
                MajorInfo secondMajor = getMajorInfo(secondLevelId);
                if (secondMajor != null) {
                    result.put("secondLevel", secondMajor);
                }
            }
        }

        return result;
    }

    /**
     * 获取映射统计信息
     */
    public Map<String, Object> getStatistics() {
        Map<String, Object> stats = new HashMap<>();
        stats.put("totalMajors", allMajorMapping.size());
        stats.put("thirdToSecondMappings", thirdToSecondMapping.size());
        stats.put("secondToThirdMappings", secondToThirdMapping.size());
        return stats;
    }

    /**
     * 判断是否为一级专业
     *
     * @param majorInfo 专业信息
     * @return true 表示一级专业
     */
    private boolean isFirstLevel(MajorInfo majorInfo) {
        return majorInfo != null
                && !StringUtils.hasText(majorInfo.getMajorCode())
                && "0".equals(majorInfo.getParentId());
    }

    /**
     * 判断是否为二级专业
     *
     * @param majorInfo 专业信息
     * @return true 表示二级专业
     */
    private boolean isSecondLevel(MajorInfo majorInfo) {
        return majorInfo != null
                && !StringUtils.hasText(majorInfo.getMajorCode())
                && StringUtils.hasText(majorInfo.getParentId())
                && !"0".equals(majorInfo.getParentId());
    }

    private void putIfAbsentWithWarn(Map<String, String> targetMap, String key, String newId, String levelName) {
        String existing = targetMap.putIfAbsent(key, newId);
        if (existing != null && !Objects.equals(existing, newId)) {
            log.warn("{}专业名称 [{}] 存在多个不同ID: {}, {}", levelName, key, existing, newId);
        }
    }

    /**
     * 根据一级专业名称获取对应的专业ID
     *
     * @param majorName 一级专业名称
     * @return 一级专业ID，未找到时返回null
     */
    public String getFirstLevelIdByName(String majorName) {
        if (!StringUtils.hasText(majorName)) {
            return null;
        }
        return firstLevelNameToIdMapping.get(majorName.trim());
    }

    /**
     * 根据二级专业名称获取对应的专业ID
     *
     * @param majorName 二级专业名称
     * @return 二级专业ID，未找到时返回null
     */
    public String getSecondLevelIdByName(String majorName) {
        if (!StringUtils.hasText(majorName)) {
            return null;
        }
        return secondLevelNameToIdMapping.get(majorName.trim());
    }

    /**
     * 根据三级专业名字查询三级专业ID以及对应的二级专业ID
     *
     * @param thirdLevelName 三级专业名字
     * @return 包含三级专业ID和二级专业ID的结果列表
     */
    public List<MajorMappingResult> getThirdLevelIdAndSecondLevelId(String thirdLevelName) {
        List<MajorMappingResult> result = new ArrayList<>();

        if (!StringUtils.hasText(thirdLevelName)) {
            return result;
        }

        // 遍历所有专业信息，查找名字匹配的三级专业
        for (Map.Entry<String, MajorInfo> entry : allMajorMapping.entrySet()) {
            MajorInfo majorInfo = entry.getValue();

            // 检查是否为三级专业且名字匹配
            if (StringUtils.hasText(majorInfo.getMajorCode()) &&
                    thirdLevelName.equals(majorInfo.getLabel())) {

                MajorMappingResult item = new MajorMappingResult();
                item.setThirdLevelId(majorInfo.getId());
                item.setThirdLevelName(majorInfo.getLabel());

                // 获取对应的二级专业ID
                String secondLevelId = getSecondLevelIdByThirdLevelId(majorInfo.getId());
                if (StringUtils.hasText(secondLevelId)) {
                    item.setSecondLevelId(secondLevelId);

                    // 获取二级专业名字
                    MajorInfo secondMajor = getMajorInfo(secondLevelId);
                    if (secondMajor != null) {
                        item.setSecondLevelName(secondMajor.getLabel());
                    }
                }

                result.add(item);
            }
        }

        return result;
    }

    /**
     * 根据一级专业名称列表获取专业代码列表
     * 返回的代码列表与输入的名称列表一一对应，找不到的用空字符串占位
     *
     * @param firstLevelNames 一级专业名称列表
     * @return 专业代码列表，与输入列表长度一致
     */
    public List<String> getFirstLevelCodesByNames(List<String> firstLevelNames) {
        List<String> result = new ArrayList<>();

        if (firstLevelNames == null || firstLevelNames.isEmpty()) {
            return result;
        }

        // 创建名称到代码的映射
        Map<String, String> nameToCodeMap = new HashMap<>();

        // 遍历所有专业信息，查找名字匹配的一级专业
        for (Map.Entry<String, MajorInfo> entry : allMajorMapping.entrySet()) {
            MajorInfo majorInfo = entry.getValue();

            // 检查是否为一级专业（没有majorCode且parentId为"0"）且名字匹配
            if (!StringUtils.hasText(majorInfo.getMajorCode()) &&
                    "0".equals(majorInfo.getParentId()) &&
                    firstLevelNames.contains(majorInfo.getLabel())) {
                nameToCodeMap.put(majorInfo.getLabel(), majorInfo.getId());
            }
        }

        // 按照输入顺序构建结果列表，找不到的用空字符串占位
        for (String name : firstLevelNames) {
            result.add(nameToCodeMap.getOrDefault(name, ""));
        }

        return result;
    }

    /**
     * 根据二级专业名称列表获取专业代码列表
     * 返回的代码列表与输入的名称列表一一对应，找不到的用空字符串占位
     *
     * @param secondLevelNames 二级专业名称列表
     * @return 专业代码列表，与输入列表长度一致
     */
    public List<String> getSecondLevelCodesByNames(List<String> secondLevelNames) {
        List<String> result = new ArrayList<>();

        if (secondLevelNames == null || secondLevelNames.isEmpty()) {
            return result;
        }

        // 创建名称到代码的映射
        Map<String, String> nameToCodeMap = new HashMap<>();

        // 遍历所有专业信息，查找名字匹配的二级专业
        for (Map.Entry<String, MajorInfo> entry : allMajorMapping.entrySet()) {
            MajorInfo majorInfo = entry.getValue();

            // 检查是否为二级专业（没有majorCode且parentId不为"0"）且名字匹配
            if (!StringUtils.hasText(majorInfo.getMajorCode()) &&
                    StringUtils.hasText(majorInfo.getParentId()) &&
                    !"0".equals(majorInfo.getParentId()) &&
                    secondLevelNames.contains(majorInfo.getLabel())) {
                nameToCodeMap.put(majorInfo.getLabel(), majorInfo.getId());
            }
        }

        // 按照输入顺序构建结果列表，找不到的用空字符串占位
        for (String name : secondLevelNames) {
            result.add(nameToCodeMap.getOrDefault(name, ""));
        }

        return result;
    }

    /**
     * 返回全部一级、二级专业。用于用户选择一级，然后选择二级专业。
     * 默认返回本科专业数据
     * 
     * @return 包含所有本科一级专业及其下属二级专业的列表
     */
    public List<MajorInfo> getTwoLevelAllMajors() {
        return getTwoLevelAllMajors(EducationLevel.BACHELOR);
    }

    /**
     * 返回指定学历层次的全部一级、二级专业。用于用户选择一级，然后选择二级专业。
     * 
     * @param educationLevel 学历层次枚举 (BACHELOR/ASSOCIATE/ALL)
     * @return 包含指定学历层次所有一级专业及其下属二级专业的列表
     */
    public List<MajorInfo> getTwoLevelAllMajors(EducationLevel educationLevel) {
        List<MajorInfo> result = new ArrayList<>();
        
        if (educationLevel == null) {
            log.warn("学历层次参数为空，使用默认本科");
            educationLevel = EducationLevel.BACHELOR;
        }
        
        // 遍历所有专业信息，查找一级专业
        for (Map.Entry<String, MajorInfo> entry : allMajorMapping.entrySet()) {
            MajorInfo majorInfo = entry.getValue();
            
            // 检查是否为一级专业（没有majorCode且parentId为"0"）
            if (!StringUtils.hasText(majorInfo.getMajorCode()) && 
                "0".equals(majorInfo.getParentId())) {
                
                // 根据学历层次过滤专业
                if (!isMatchEducationLevel(majorInfo.getId(), educationLevel)) {
                    continue;
                }
                
                // 创建一级专业的副本，避免修改原始数据
                MajorInfo firstLevel = new MajorInfo();
                firstLevel.setId(majorInfo.getId());
                firstLevel.setLabel(majorInfo.getLabel());
                firstLevel.setMajorCode(majorInfo.getMajorCode());
                firstLevel.setParentId(majorInfo.getParentId());
                firstLevel.setAttention(majorInfo.isAttention());
                
                // 获取该一级专业下的所有二级专业
                List<MajorInfo> secondLevelMajors = new ArrayList<>();
                if (majorInfo.getChildren() != null) {
                    for (MajorInfo child : majorInfo.getChildren()) {
                        // 二级专业：没有majorCode且parentId不为"0"（指向一级专业）
                        if (!StringUtils.hasText(child.getMajorCode()) && 
                            StringUtils.hasText(child.getParentId()) && 
                            !"0".equals(child.getParentId())) {
                            
                            // 创建二级专业的副本，不包含三级专业信息
                            MajorInfo secondLevel = new MajorInfo();
                            secondLevel.setId(child.getId());
                            secondLevel.setLabel(child.getLabel());
                            secondLevel.setMajorCode(child.getMajorCode());
                            secondLevel.setParentId(child.getParentId());
                            secondLevel.setAttention(child.isAttention());
                            // 不设置children，因为只需要返回二级专业
                            
                            secondLevelMajors.add(secondLevel);
                        }
                    }
                }
                
                // 设置一级专业的二级专业列表
                firstLevel.setChildren(secondLevelMajors);
                result.add(firstLevel);
            }
        }
        
        // 按照专业ID排序，保持原有的分类顺序
        result.sort(this::compareByMajorId);
        
        // 对每个一级专业下的二级专业也按ID排序
        result.forEach(firstLevel -> {
            if (firstLevel.getChildren() != null) {
                firstLevel.getChildren().sort(this::compareByMajorId);
            }
        });
        
        log.info("获取{}两级专业数据完成，一级专业数量: {}", educationLevel.getDisplayName(), result.size());
        
        // 调试信息：打印前几个一级专业的信息
        if (result.size() > 0) {
            log.info("{}前3个一级专业示例:", educationLevel.getDisplayName());
            for (int i = 0; i < Math.min(3, result.size()); i++) {
                MajorInfo major = result.get(i);
                log.info("  - {} (ID: {}, 二级专业数量: {})", 
                    major.getLabel(), 
                    major.getId(), 
                    major.getChildren() != null ? major.getChildren().size() : 0);
            }
        } else {
            log.warn("未找到任何{}一级专业数据！", educationLevel.getDisplayName());
        }
        
        return result;
    }


    /**
     * 判断专业ID是否匹配指定的学历层次
     * 
     * @param majorId 专业ID
     * @param educationLevel 学历层次枚举
     * @return 是否匹配
     */
    private boolean isMatchEducationLevel(String majorId, EducationLevel educationLevel) {
        if (!StringUtils.hasText(majorId) || educationLevel == null) {
            return false;
        }
        
        // 如果是"全部"，则匹配所有专业
        if (educationLevel == EducationLevel.ALL) {
            return true;
        }
        
        try {
            int id = Integer.parseInt(majorId);
            
            // 根据数据分析：
            // 本科专业ID范围：1-105 (从哲学1开始到艺术学105)
            // 专科专业ID范围：106+ (从农林牧渔大类106开始)
            if (educationLevel == EducationLevel.BACHELOR) {
                return id >= 1 && id <= 105;
            } else if (educationLevel == EducationLevel.ASSOCIATE) {
                return id >= 106;
            }
        } catch (NumberFormatException e) {
            log.warn("专业ID格式错误: {}", majorId);
        }
        
        return false;
    }

    /**
     * 按照专业ID进行比较排序的方法
     * 
     * @param a 专业信息A
     * @param b 专业信息B
     * @return 比较结果
     */
    private int compareByMajorId(MajorInfo a, MajorInfo b) {
        try {
            return Integer.compare(Integer.parseInt(a.getId()), Integer.parseInt(b.getId()));
        } catch (NumberFormatException e) {
            // 如果ID不是数字，则按字符串排序
            return a.getId().compareTo(b.getId());
        }
    }
}