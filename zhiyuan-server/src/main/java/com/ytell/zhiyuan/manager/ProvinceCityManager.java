package com.ytell.zhiyuan.manager;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ytell.zhiyuan.model.vo.ProvinceCityResponseVO;
import com.ytell.zhiyuan.model.vo.ProvinceCityVO;
import com.ytell.zhiyuan.model.vo.RegionProvinceVO;
import lombok.extern.slf4j.Slf4j;
import org.springframework.core.io.ClassPathResource;
import org.springframework.stereotype.Component;

import javax.annotation.PostConstruct;
import java.io.IOException;
import java.io.InputStream;
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;
import java.util.stream.Collectors;

/**
 * 省市数据管理器
 * 提供省市数据的查询功能
 */
@Slf4j
@Component
public class ProvinceCityManager {

    private static final String PROVINCE_CITY_FILE_PATH = "bizdata/province_city.json";

    /**
     * 省份数据缓存 - key: 省份ID, value: 省份信息
     */
    private final Map<String, ProvinceCityVO> provinceCacheById = new ConcurrentHashMap<>();

    /**
     * 省份数据缓存 - key: 省份名称, value: 省份信息
     */
    private final Map<String, ProvinceCityVO> provinceCacheByLabel = new ConcurrentHashMap<>();

    /**
     * 城市数据缓存 - key: 城市ID, value: 城市信息
     */
    private final Map<String, ProvinceCityVO.CityVO> cityCacheById = new ConcurrentHashMap<>();

    /**
     * 城市数据缓存 - key: 城市名称, value: 城市信息
     */
    private final Map<String, ProvinceCityVO.CityVO> cityCacheByLabel = new ConcurrentHashMap<>();

    /**
     * 城市到省份的映射缓存 - key: 城市ID, value: 省份信息
     */
    private final Map<String, ProvinceCityVO> cityToProvinceCache = new ConcurrentHashMap<>();

    /**
     * 初始化加载省市数据
     */
    @PostConstruct
    public void init() {
        try {
            loadProvinceCityData();
            log.info("省市数据加载完成，共加载 {} 个省份，{} 个城市",
                    provinceCacheById.size(), cityCacheById.size());
        } catch (Exception e) {
            log.error("加载省市数据失败", e);
        }
    }

    /**
     * 加载省市数据
     */
    private void loadProvinceCityData() throws IOException {
        ClassPathResource resource = new ClassPathResource(PROVINCE_CITY_FILE_PATH);
        try (InputStream inputStream = resource.getInputStream()) {
            ObjectMapper objectMapper = new ObjectMapper();
            ProvinceCityResponseVO response = objectMapper.readValue(inputStream, ProvinceCityResponseVO.class);

            if (response.getData() != null) {
                for (ProvinceCityVO province : response.getData()) {
                    // 缓存省份数据
                    provinceCacheById.put(province.getId(), province);
                    provinceCacheByLabel.put(province.getLabel(), province);

                    // 缓存城市数据
                    if (province.getChildren() != null) {
                        for (ProvinceCityVO.CityVO city : province.getChildren()) {
                            cityCacheById.put(city.getId(), city);
                            cityCacheByLabel.put(city.getLabel(), city);
                            cityToProvinceCache.put(city.getId(), province);
                        }
                    }
                }
            }
        }
    }

    /**
     * 根据省份ID查询省份信息
     *
     * @param provinceId 省份ID
     * @return 省份信息，如果不存在返回null
     */
    public ProvinceCityVO getProvinceById(String provinceId) {
        return provinceCacheById.get(provinceId);
    }

    /**
     * 根据省份名称查询省份信息
     *
     * @param provinceLabel 省份名称
     * @return 省份信息，如果不存在返回null
     */
    public ProvinceCityVO getProvinceByLabel(String provinceLabel) {
        return provinceCacheByLabel.get(provinceLabel);
    }

    /**
     * 根据省份ID查询省份名称
     *
     * @param provinceId 省份ID
     * @return 省份名称，如果不存在返回null
     */
    public String getProvinceLabelById(String provinceId) {
        ProvinceCityVO province = provinceCacheById.get(provinceId);
        return province != null ? province.getLabel() : null;
    }

    /**
     * 根据省份名称查询省份ID
     *
     * @param provinceLabel 省份名称
     * @return 省份ID，如果不存在返回null
     */
    public String getProvinceIdByLabel(String provinceLabel) {
        ProvinceCityVO province = provinceCacheByLabel.get(provinceLabel);
        return province != null ? province.getId() : null;
    }

    /**
     * 根据省份ID查询该省所有城市
     *
     * @param provinceId 省份ID
     * @return 城市列表，如果省份不存在返回空列表
     */
    public List<ProvinceCityVO.CityVO> getCitiesByProvinceId(String provinceId) {
        ProvinceCityVO province = provinceCacheById.get(provinceId);
        return province != null && province.getChildren() != null ?
                new ArrayList<>(province.getChildren()) : new ArrayList<>();
    }

    /**
     * 根据省份名称查询该省所有城市
     *
     * @param provinceLabel 省份名称
     * @return 城市列表，如果省份不存在返回空列表
     */
    public List<ProvinceCityVO.CityVO> getCitiesByProvinceLabel(String provinceLabel) {
        ProvinceCityVO province = provinceCacheByLabel.get(provinceLabel);
        return province != null && province.getChildren() != null ?
                new ArrayList<>(province.getChildren()) : new ArrayList<>();
    }

    /**
     * 根据省份ID查询该省所有城市的ID和名称
     *
     * @param provinceId 省份ID
     * @return 城市ID和名称的映射，如果省份不存在返回空映射
     */
    public Map<String, String> getCityIdLabelMapByProvinceId(String provinceId) {
        List<ProvinceCityVO.CityVO> cities = getCitiesByProvinceId(provinceId);
        return cities.stream()
                .collect(Collectors.toMap(
                        ProvinceCityVO.CityVO::getId,
                        ProvinceCityVO.CityVO::getLabel,
                        (existing, replacement) -> existing
                ));
    }

    /**
     * 根据省份名称查询该省所有城市的ID和名称
     *
     * @param provinceLabel 省份名称
     * @return 城市ID和名称的映射，如果省份不存在返回空映射
     */
    public Map<String, String> getCityIdLabelMapByProvinceLabel(String provinceLabel) {
        List<ProvinceCityVO.CityVO> cities = getCitiesByProvinceLabel(provinceLabel);
        return cities.stream()
                .collect(Collectors.toMap(
                        ProvinceCityVO.CityVO::getId,
                        ProvinceCityVO.CityVO::getLabel,
                        (existing, replacement) -> existing
                ));
    }

    /**
     * 根据城市ID查询城市信息
     *
     * @param cityId 城市ID
     * @return 城市信息，如果不存在返回null
     */
    public ProvinceCityVO.CityVO getCityById(String cityId) {
        return cityCacheById.get(cityId);
    }

    /**
     * 根据城市名称查询城市信息
     *
     * @param cityLabel 城市名称
     * @return 城市信息，如果不存在返回null
     */
    public ProvinceCityVO.CityVO getCityByLabel(String cityLabel) {
        return cityCacheByLabel.get(cityLabel);
    }

    /**
     * 根据城市ID查询城市名称
     *
     * @param cityId 城市ID
     * @return 城市名称，如果不存在返回null
     */
    public String getCityLabelById(String cityId) {
        ProvinceCityVO.CityVO city = cityCacheById.get(cityId);
        return city != null ? city.getLabel() : null;
    }

    /**
     * 根据城市名称查询城市ID
     *
     * @param cityLabel 城市名称
     * @return 城市ID，如果不存在返回null
     */
    public String getCityIdByLabel(String cityLabel) {
        ProvinceCityVO.CityVO city = cityCacheByLabel.get(cityLabel);
        return city != null ? city.getId() : null;
    }

    /**
     * 根据城市ID查询所在省份信息
     *
     * @param cityId 城市ID
     * @return 省份信息，如果城市不存在返回null
     */
    public ProvinceCityVO getProvinceByCityId(String cityId) {
        return cityToProvinceCache.get(cityId);
    }

    /**
     * 根据城市名称查询所在省份信息
     *
     * @param cityLabel 城市名称
     * @return 省份信息，如果城市不存在返回null
     */
    public ProvinceCityVO getProvinceByCityLabel(String cityLabel) {
        ProvinceCityVO.CityVO city = cityCacheByLabel.get(cityLabel);
        return city != null ? cityToProvinceCache.get(city.getId()) : null;
    }

    /**
     * 根据城市ID查询所在省份ID
     *
     * @param cityId 城市ID
     * @return 省份ID，如果城市不存在返回null
     */
    public String getProvinceIdByCityId(String cityId) {
        ProvinceCityVO province = cityToProvinceCache.get(cityId);
        return province != null ? province.getId() : null;
    }

    /**
     * 根据城市名称查询所在省份ID
     *
     * @param cityLabel 城市名称
     * @return 省份ID，如果城市不存在返回null
     */
    public String getProvinceIdByCityLabel(String cityLabel) {
        ProvinceCityVO.CityVO city = cityCacheByLabel.get(cityLabel);
        return city != null ? cityToProvinceCache.get(city.getId()).getId() : null;
    }

    /**
     * 根据城市ID查询所在省份名称
     *
     * @param cityId 城市ID
     * @return 省份名称，如果城市不存在返回null
     */
    public String getProvinceLabelByCityId(String cityId) {
        ProvinceCityVO province = cityToProvinceCache.get(cityId);
        return province != null ? province.getLabel() : null;
    }

    /**
     * 根据城市名称查询所在省份名称
     *
     * @param cityLabel 城市名称
     * @return 省份名称，如果城市不存在返回null
     */
    public String getProvinceLabelByCityLabel(String cityLabel) {
        ProvinceCityVO.CityVO city = cityCacheByLabel.get(cityLabel);
        return city != null ? cityToProvinceCache.get(city.getId()).getLabel() : null;
    }

    /**
     * 获取所有省份信息
     *
     * @return 所有省份信息列表
     */
    public List<ProvinceCityVO> getAllProvinces() {
        List<ProvinceCityVO> list = new ArrayList<>(provinceCacheById.values());
        //按照首字母字典排序
        list.sort(Comparator.comparing(ProvinceCityVO::getPrefix));
        return list;

    }

    /**
     * 获取所有城市信息
     *
     * @return 所有城市信息列表
     */
    public List<ProvinceCityVO.CityVO> getAllCities() {
        return new ArrayList<>(cityCacheById.values());
    }

    /**
     * 检查省份是否存在
     *
     * @param provinceId 省份ID
     * @return 是否存在
     */
    public boolean isProvinceExists(String provinceId) {
        return provinceCacheById.containsKey(provinceId);
    }

    /**
     * 检查城市是否存在
     *
     * @param cityId 城市ID
     * @return 是否存在
     */
    public boolean isCityExists(String cityId) {
        return cityCacheById.containsKey(cityId);
    }

    /**
     * 根据省份名称列表获取省份代码列表
     * 返回的省份代码列表与输入的名称列表一一对应，找不到的用空字符串占位
     *
     * @param provinceLabels 省份名称列表
     * @return 省份代码列表，与输入列表长度一致
     */
    public List<String> getProvinceByLabelList(List<String> provinceLabels) {
        List<String> result = new ArrayList<>();

        if (provinceLabels == null || provinceLabels.isEmpty()) {
            return result;
        }

        // 按照输入顺序构建结果列表，找不到的用空字符串占位
        for (String label : provinceLabels) {
            ProvinceCityVO province = provinceCacheByLabel.get(label);
            if (province != null && province.getId() != null) {
                result.add(province.getId());
            } else {
                result.add(""); // 用空字符串占位
            }
        }

        return result;
    }

    /**
     * 获取按大区分组的省份列表
     * 父节点是大区名称（如：华东、华北、华南等），子节点是对应的省份列表
     *
     * @return 大区省份列表
     */
    public List<RegionProvinceVO> getRegionProvinceList() {
        // 定义各大区对应的省份
        Map<String, List<String>> regionProvinceMap = new HashMap<>();
        
        // 华东地区
        regionProvinceMap.put("华东", Arrays.asList(
                "上海", "江苏", "浙江", "安徽", "福建", "江西", "山东"
        ));
        
        // 华北地区
        regionProvinceMap.put("华北", Arrays.asList(
                "北京", "天津", "河北", "山西", "内蒙古"
        ));
        
        // 华南地区
        regionProvinceMap.put("华南", Arrays.asList(
                "广东", "广西", "海南"
        ));
        
        // 华中地区
        regionProvinceMap.put("华中", Arrays.asList(
                "河南", "湖北", "湖南"
        ));
        
        // 西南地区
        regionProvinceMap.put("西南", Arrays.asList(
                "重庆", "四川", "贵州", "云南", "西藏"
        ));
        
        // 西北地区
        regionProvinceMap.put("西北", Arrays.asList(
                "陕西", "甘肃", "青海", "宁夏", "新疆"
        ));
        
        // 东北地区
        regionProvinceMap.put("东北", Arrays.asList(
                "辽宁", "吉林", "黑龙江"
        ));
        

        List<RegionProvinceVO> result = new ArrayList<>();
        
        // 按大区顺序构建结果
        List<String> regionOrder = Arrays.asList(
                "华东", "华北", "华南", "华中", "西南", "西北", "东北"
        );
        
        for (String regionName : regionOrder) {
            List<String> provinceNames = regionProvinceMap.get(regionName);
            if (provinceNames != null && !provinceNames.isEmpty()) {
                List<ProvinceCityVO> provinces = new ArrayList<>();
                
                // 根据省份名称获取省份信息
                for (String provinceName : provinceNames) {
                    ProvinceCityVO province = provinceCacheByLabel.get(provinceName);
                    if (province != null) {
                        provinces.add(province);
                    }
                }
                
                // 按省份名称排序
                provinces.sort(Comparator.comparing(ProvinceCityVO::getLabel));
                
                result.add(new RegionProvinceVO(regionName, provinces));
            }
        }
        
        return result;
    }

}
