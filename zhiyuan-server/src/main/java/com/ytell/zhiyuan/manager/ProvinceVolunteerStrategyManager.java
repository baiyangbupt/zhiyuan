package com.ytell.zhiyuan.manager;

import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;

import javax.annotation.PostConstruct;
import java.util.Arrays;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

/**
 * 省份志愿填报策略管理器
 * 维护省份与志愿填报策略的映射关系
 * 数据结构：省份代码、省份名称、教育层次、策略
 */
@Slf4j
@Component
public class ProvinceVolunteerStrategyManager {

    private static final String BACHELOR_CODE = "01"; // 本科
    private static final String JUNIOR_COLLEGE_CODE = "02"; // 专科

    /**
     * 省份策略数据缓存 - key: provinceCode + educationLevel, value: strategy
     */
    private final Map<String, String> strategyCache = new ConcurrentHashMap<>();


    /**
     * 策略到省份列表的映射缓存
     */
    private final Map<String, java.util.List<String>> strategyProvinceCache = new ConcurrentHashMap<>();

    /**
     * 初始化省份填报策略数据
     */
    @PostConstruct
    public void init() {
        try {
            loadProvinceVolunteerStrategyData();
            log.info("省份志愿填报策略数据加载完成，共加载 {} 个省份，{} 个策略映射",
                    30, strategyCache.size());
        } catch (Exception e) {
            log.error("加载省份志愿填报策略数据失败", e);
        }
    }

    /**
     * 加载省份志愿填报策略数据
     * 直接在代码中定义完整的省份数据结构
     */
    private void loadProvinceVolunteerStrategyData() {
        // 定义省份策略数据：省份代码、省份名称、教育层次、策略
        java.util.List<String[]> provinceStrategyData = Arrays.asList(
            // 北京 - OTON
            new String[]{"110000", "北京", BACHELOR_CODE, "OTON"},
            new String[]{"110000", "北京", JUNIOR_COLLEGE_CODE, "OTON"},

            // 上海 - OTON
            new String[]{"310000", "上海", BACHELOR_CODE, "OTON"},
            new String[]{"310000", "上海", JUNIOR_COLLEGE_CODE, "OTON"},

            // 天津 - OTON
            new String[]{"120000", "天津", BACHELOR_CODE, "OTON"},
            new String[]{"120000", "天津", JUNIOR_COLLEGE_CODE, "OTON"},

            // 重庆 - OTOO
            new String[]{"500000", "重庆", BACHELOR_CODE, "OTOO"},
            new String[]{"500000", "重庆", JUNIOR_COLLEGE_CODE, "OTOO"},

            // 辽宁 - OTOO
            new String[]{"210000", "辽宁", BACHELOR_CODE, "OTOO"},
            new String[]{"210000", "辽宁", JUNIOR_COLLEGE_CODE, "OTOO"},

            // 吉林 - OTON
            new String[]{"220000", "吉林", BACHELOR_CODE, "OTON"},
            new String[]{"220000", "吉林", JUNIOR_COLLEGE_CODE, "OTON"},

            // 黑龙江 - OTON
            new String[]{"230000", "黑龙江", BACHELOR_CODE, "OTON"},
            new String[]{"230000", "黑龙江", JUNIOR_COLLEGE_CODE, "OTON"},

            // 河北 - OTOO
            new String[]{"130000", "河北", BACHELOR_CODE, "OTOO"},
            new String[]{"130000", "河北", JUNIOR_COLLEGE_CODE, "OTOO"},

            // 山东 - OTOO
            new String[]{"370000", "山东", BACHELOR_CODE, "OTOO"},
            new String[]{"370000", "山东", JUNIOR_COLLEGE_CODE, "OTOO"},

            // 浙江 - OTOO
            new String[]{"330000", "浙江", BACHELOR_CODE, "OTOO"},
            new String[]{"330000", "浙江", JUNIOR_COLLEGE_CODE, "OTOO"},

            // 江苏 - OTON
            new String[]{"320000", "江苏", BACHELOR_CODE, "OTON"},
            new String[]{"320000", "江苏", JUNIOR_COLLEGE_CODE, "OTON"},

            // 安徽 - OTON
            new String[]{"340000", "安徽", BACHELOR_CODE, "OTON"},
            new String[]{"340000", "安徽", JUNIOR_COLLEGE_CODE, "OTON"},

            // 江西 - OTON
            new String[]{"360000", "江西", BACHELOR_CODE, "OTON"},
            new String[]{"360000", "江西", JUNIOR_COLLEGE_CODE, "OTON"},

            // 福建 - 特殊策略：本科OTON，专科OTOO
            new String[]{"350000", "福建", BACHELOR_CODE, "OTON"},
            new String[]{"350000", "福建", JUNIOR_COLLEGE_CODE, "OTOO"},

            // 广东 - OTON
            new String[]{"440000", "广东", BACHELOR_CODE, "OTON"},
            new String[]{"440000", "广东", JUNIOR_COLLEGE_CODE, "OTON"},

            // 广西 - OTON
            new String[]{"450000", "广西", BACHELOR_CODE, "OTON"},
            new String[]{"450000", "广西", JUNIOR_COLLEGE_CODE, "OTON"},

            // 海南 - OTON
            new String[]{"460000", "海南", BACHELOR_CODE, "OTON"},
            new String[]{"460000", "海南", JUNIOR_COLLEGE_CODE, "OTON"},

            // 河南 - OTONWL
            new String[]{"410000", "河南", BACHELOR_CODE, "OTONWL"},
            new String[]{"410000", "河南", JUNIOR_COLLEGE_CODE, "OTONWL"},

            // 湖南 - OTON
            new String[]{"430000", "湖南", BACHELOR_CODE, "OTON"},
            new String[]{"430000", "湖南", JUNIOR_COLLEGE_CODE, "OTON"},

            // 湖北 - OTON
            new String[]{"420000", "湖北", BACHELOR_CODE, "OTON"},
            new String[]{"420000", "湖北", JUNIOR_COLLEGE_CODE, "OTON"},

            // 甘肃 - OTON
            new String[]{"620000", "甘肃", BACHELOR_CODE, "OTON"},
            new String[]{"620000", "甘肃", JUNIOR_COLLEGE_CODE, "OTON"},

            // 贵州 - OTOO
            new String[]{"520000", "贵州", BACHELOR_CODE, "OTOO"},
            new String[]{"520000", "贵州", JUNIOR_COLLEGE_CODE, "OTOO"},

            // 云南 - OTONWL
            new String[]{"530000", "云南", BACHELOR_CODE, "OTONWL"},
            new String[]{"530000", "云南", JUNIOR_COLLEGE_CODE, "OTONWL"},

            // 山西 - OTONWL
            new String[]{"140000", "山西", BACHELOR_CODE, "OTONWL"},
            new String[]{"140000", "山西", JUNIOR_COLLEGE_CODE, "OTONWL"},

            // 陕西 - OTONWL
            new String[]{"610000", "陕西", BACHELOR_CODE, "OTONWL"},
            new String[]{"610000", "陕西", JUNIOR_COLLEGE_CODE, "OTONWL"},

            // 四川 - OTONWL
            new String[]{"510000", "四川", BACHELOR_CODE, "OTONWL"},
            new String[]{"510000", "四川", JUNIOR_COLLEGE_CODE, "OTONWL"},

            // 青海 - OTOOWL
            new String[]{"630000", "青海", BACHELOR_CODE, "OTOOWL"},
            new String[]{"630000", "青海", JUNIOR_COLLEGE_CODE, "OTOOWL"},

            // 宁夏 - OTONWL
            new String[]{"640000", "宁夏", BACHELOR_CODE, "OTONWL"},
            new String[]{"640000", "宁夏", JUNIOR_COLLEGE_CODE, "OTONWL"},

            // 内蒙古 - OTONWL
            new String[]{"150000", "内蒙古", BACHELOR_CODE, "OTONWL"},
            new String[]{"150000", "内蒙古", JUNIOR_COLLEGE_CODE, "OTONWL"},

            // 新疆 - OTOA
            new String[]{"650000", "新疆", BACHELOR_CODE, "OTOA"},
            new String[]{"650000", "新疆", JUNIOR_COLLEGE_CODE, "OTOA"}
        );

        // 构建缓存
        for (String[] data : provinceStrategyData) {
            String provinceCode = data[0];
            String provinceName = data[1];
            String educationLevel = data[2];
            String strategy = data[3];

            // 构建策略缓存
            String key = provinceCode + educationLevel;
            strategyCache.put(key, strategy);

            // 构建省份映射缓存
            // 不再需要省份名称到代码的映射

            // 构建策略到省份的反向映射
            strategyProvinceCache.computeIfAbsent(strategy, k -> new java.util.ArrayList<>()).add(provinceName);
        }

        // 去重策略到省份的映射
        for (String strategy : strategyProvinceCache.keySet()) {
            java.util.List<String> provinces = strategyProvinceCache.get(strategy);
            java.util.Set<String> uniqueProvinces = new java.util.HashSet<>(provinces);
            strategyProvinceCache.put(strategy, new java.util.ArrayList<>(uniqueProvinces));
        }
    }

    /**
     * 根据省份代码和教育层次获取填报策略
     *
     * @param provinceCode 省份代码
     * @param educationLevel 教育层次 (01=本科, 02=专科)
     * @return 填报策略，如果不存在返回null
     */
    public String getVolunteerStrategyByProvinceCode(String provinceCode, String educationLevel) {
        if (provinceCode == null || educationLevel == null) {
            return null;
        }
        return strategyCache.get(provinceCode + educationLevel);
    }




}
