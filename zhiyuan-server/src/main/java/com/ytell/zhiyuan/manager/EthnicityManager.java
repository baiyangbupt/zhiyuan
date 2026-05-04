package com.ytell.zhiyuan.manager;

import com.ytell.zhiyuan.model.vo.EthnicityVO;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;

import javax.annotation.PostConstruct;
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;
import java.util.stream.Collectors;

/**
 * 民族数据管理器
 * 提供民族数据的查询功能
 */
@Slf4j
@Component
public class EthnicityManager {

    /**
     * 民族数据缓存 - key: 民族代码, value: 民族信息
     */
    private final Map<String, EthnicityVO> ethnicityCacheByCode = new ConcurrentHashMap<>();

    /**
     * 民族数据缓存 - key: 民族名称, value: 民族信息
     */
    private final Map<String, EthnicityVO> ethnicityCacheByName = new ConcurrentHashMap<>();

    /**
     * 初始化加载民族数据
     */
    @PostConstruct
    public void init() {
        try {
            loadEthnicityData();
            log.info("民族数据加载完成，共加载 {} 个民族", ethnicityCacheByCode.size());
        } catch (Exception e) {
            log.error("加载民族数据失败", e);
        }
    }

    /**
     * 加载民族数据
     * 这里使用硬编码的方式提供民族列表，实际项目中可以从数据库或配置文件加载
     */
    private void loadEthnicityData() {
        List<EthnicityVO> ethnicities = Arrays.asList(
            // 汉族 - 不是少数民族
            new EthnicityVO("01", "汉族", false),
            
            // 少数民族
            new EthnicityVO("02", "蒙古族", true),
            new EthnicityVO("03", "回族", true),
            new EthnicityVO("04", "藏族", true),
            new EthnicityVO("05", "维吾尔族", true),
            new EthnicityVO("06", "苗族", true),
            new EthnicityVO("07", "彝族", true),
            new EthnicityVO("08", "壮族", true),
            new EthnicityVO("09", "布依族", true),
            new EthnicityVO("10", "朝鲜族", true),
            new EthnicityVO("11", "满族", true),
            new EthnicityVO("12", "侗族", true),
            new EthnicityVO("13", "瑶族", true),
            new EthnicityVO("14", "白族", true),
            new EthnicityVO("15", "土家族", true),
            new EthnicityVO("16", "哈尼族", true),
            new EthnicityVO("17", "哈萨克族", true),
            new EthnicityVO("18", "傣族", true),
            new EthnicityVO("19", "黎族", true),
            new EthnicityVO("20", "傈僳族", true),
            new EthnicityVO("21", "佤族", true),
            new EthnicityVO("22", "畲族", true),
            new EthnicityVO("23", "高山族", true),
            new EthnicityVO("24", "拉祜族", true),
            new EthnicityVO("25", "水族", true),
            new EthnicityVO("26", "东乡族", true),
            new EthnicityVO("27", "纳西族", true),
            new EthnicityVO("28", "景颇族", true),
            new EthnicityVO("29", "柯尔克孜族", true),
            new EthnicityVO("30", "土族", true),
            new EthnicityVO("31", "达斡尔族", true),
            new EthnicityVO("32", "仫佬族", true),
            new EthnicityVO("33", "羌族", true),
            new EthnicityVO("34", "布朗族", true),
            new EthnicityVO("35", "撒拉族", true),
            new EthnicityVO("36", "毛南族", true),
            new EthnicityVO("37", "仡佬族", true),
            new EthnicityVO("38", "锡伯族", true),
            new EthnicityVO("39", "阿昌族", true),
            new EthnicityVO("40", "普米族", true),
            new EthnicityVO("41", "塔吉克族", true),
            new EthnicityVO("42", "怒族", true),
            new EthnicityVO("43", "乌孜别克族", true),
            new EthnicityVO("44", "俄罗斯族", true),
            new EthnicityVO("45", "鄂温克族", true),
            new EthnicityVO("46", "德昂族", true),
            new EthnicityVO("47", "保安族", true),
            new EthnicityVO("48", "裕固族", true),
            new EthnicityVO("49", "京族", true),
            new EthnicityVO("50", "塔塔尔族", true),
            new EthnicityVO("51", "独龙族", true),
            new EthnicityVO("52", "鄂伦春族", true),
            new EthnicityVO("53", "赫哲族", true),
            new EthnicityVO("54", "门巴族", true),
            new EthnicityVO("55", "珞巴族", true),
            new EthnicityVO("56", "基诺族", true)
        );

        // 缓存民族数据
        for (EthnicityVO ethnicity : ethnicities) {
            ethnicityCacheByCode.put(ethnicity.getCode(), ethnicity);
            ethnicityCacheByName.put(ethnicity.getName(), ethnicity);
        }
    }

    /**
     * 根据民族代码查询民族信息
     *
     * @param code 民族代码
     * @return 民族信息，如果不存在返回null
     */
    public EthnicityVO getEthnicityByCode(String code) {
        return ethnicityCacheByCode.get(code);
    }

    /**
     * 根据民族名称查询民族信息
     *
     * @param name 民族名称
     * @return 民族信息，如果不存在返回null
     */
    public EthnicityVO getEthnicityByName(String name) {
        return ethnicityCacheByName.get(name);
    }

    /**
     * 获取所有民族信息
     *
     * @return 所有民族信息列表（按code排序）
     */
    public List<EthnicityVO> getAllEthnicities() {
        return ethnicityCacheByCode.values().stream()
                .sorted(Comparator.comparing(EthnicityVO::getCode))
                .collect(Collectors.toList());
    }

    /**
     * 获取所有少数民族信息
     *
     * @return 少数民族信息列表
     */
    public List<EthnicityVO> getMinorityEthnicities() {
        List<EthnicityVO> result = new ArrayList<>();
        for (EthnicityVO ethnicity : ethnicityCacheByCode.values()) {
            if (ethnicity.getIsMinority() != null && ethnicity.getIsMinority()) {
                result.add(ethnicity);
            }
        }
        return result;
    }

    /**
     * 检查民族代码是否存在
     *
     * @param code 民族代码
     * @return 是否存在
     */
    public boolean isEthnicityCodeExists(String code) {
        return ethnicityCacheByCode.containsKey(code);
    }

    /**
     * 检查民族名称是否存在
     *
     * @param name 民族名称
     * @return 是否存在
     */
    public boolean isEthnicityNameExists(String name) {
        return ethnicityCacheByName.containsKey(name);
    }

    /**
     * 判断是否为少数民族
     *
     * @param ethnicityCode 民族代码
     * @return 是否为少数民族
     */
    public boolean isMinority(String ethnicityCode) {
        EthnicityVO ethnicity = ethnicityCacheByCode.get(ethnicityCode);
        return ethnicity != null && ethnicity.getIsMinority() != null && ethnicity.getIsMinority();
    }

    /**
     * 判断是否为少数民族（根据民族名称）
     *
     * @param ethnicityName 民族名称
     * @return 是否为少数民族
     */
    public boolean isMinorityByName(String ethnicityName) {
        EthnicityVO ethnicity = ethnicityCacheByName.get(ethnicityName);
        return ethnicity != null && ethnicity.getIsMinority() != null && ethnicity.getIsMinority();
    }
}
