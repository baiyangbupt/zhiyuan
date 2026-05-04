package com.ytell.zhiyuan.web.controller.inner;

import com.ytell.zhiyuan.manager.ProvinceCityManager;
import com.ytell.zhiyuan.model.vo.ProvinceCityVO;
import io.swagger.annotations.Api;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;
import java.util.Map;

/**
 * 省市数据控制器
 * 提供省市数据查询接口
 */
@RestController
@RequestMapping("/gaotu-assistant-bot/inner/province-city")
@Api(tags = "内部使用接口")

public class ProvinceCityController {

    @Autowired
    private ProvinceCityManager provinceCityManager;

    /**
     * 根据省份ID查询省份信息
     */
    @GetMapping("/province/id")
    public ProvinceCityVO getProvinceById(@RequestParam String provinceId) {
        return provinceCityManager.getProvinceById(provinceId);
    }

    /**
     * 根据省份名称查询省份信息
     */
    @GetMapping("/province/name")
    public ProvinceCityVO getProvinceByName(@RequestParam String provinceName) {
        return provinceCityManager.getProvinceByLabel(provinceName);
    }

    /**
     * 根据省份ID查询省份名称
     */
    @GetMapping("/province/label")
    public String getProvinceLabelById(@RequestParam String provinceId) {
        return provinceCityManager.getProvinceLabelById(provinceId);
    }

    /**
     * 根据省份名称查询省份ID
     */
    @GetMapping("/province/id-by-name")
    public String getProvinceIdByName(@RequestParam String provinceName) {
        return provinceCityManager.getProvinceIdByLabel(provinceName);
    }

    /**
     * 根据省份ID查询该省所有城市
     */
    @GetMapping("/cities/province-id")
    public List<ProvinceCityVO.CityVO> getCitiesByProvinceId(@RequestParam String provinceId) {
        return provinceCityManager.getCitiesByProvinceId(provinceId);
    }

    /**
     * 根据省份名称查询该省所有城市
     */
    @GetMapping("/cities/province-name")
    public List<ProvinceCityVO.CityVO> getCitiesByProvinceName(@RequestParam String provinceName) {
        return provinceCityManager.getCitiesByProvinceLabel(provinceName);
    }

    /**
     * 根据省份ID查询该省所有城市的ID和名称
     */
    @GetMapping("/cities/map/province-id")
    public Map<String, String> getCityIdLabelMapByProvinceId(@RequestParam String provinceId) {
        return provinceCityManager.getCityIdLabelMapByProvinceId(provinceId);
    }

    /**
     * 根据省份名称查询该省所有城市的ID和名称
     */
    @GetMapping("/cities/map/province-name")
    public Map<String, String> getCityIdLabelMapByProvinceName(@RequestParam String provinceName) {
        return provinceCityManager.getCityIdLabelMapByProvinceLabel(provinceName);
    }

    /**
     * 根据城市ID查询城市信息
     */
    @GetMapping("/city/id")
    public ProvinceCityVO.CityVO getCityById(@RequestParam String cityId) {
        return provinceCityManager.getCityById(cityId);
    }

    /**
     * 根据城市名称查询城市信息
     */
    @GetMapping("/city/name")
    public ProvinceCityVO.CityVO getCityByName(@RequestParam String cityName) {
        return provinceCityManager.getCityByLabel(cityName);
    }

    /**
     * 根据城市ID查询城市名称
     */
    @GetMapping("/city/label")
    public String getCityLabelById(@RequestParam String cityId) {
        return provinceCityManager.getCityLabelById(cityId);
    }

    /**
     * 根据城市名称查询城市ID
     */
    @GetMapping("/city/id-by-name")
    public String getCityIdByName(@RequestParam String cityName) {
        return provinceCityManager.getCityIdByLabel(cityName);
    }

    /**
     * 根据城市ID查询所在省份信息
     */
    @GetMapping("/city/province-by-id")
    public ProvinceCityVO getProvinceByCityId(@RequestParam String cityId) {
        return provinceCityManager.getProvinceByCityId(cityId);
    }

    /**
     * 根据城市名称查询所在省份信息
     */
    @GetMapping("/city/province-by-name")
    public ProvinceCityVO getProvinceByCityName(@RequestParam String cityName) {
        return provinceCityManager.getProvinceByCityLabel(cityName);
    }

    /**
     * 根据城市ID查询所在省份ID
     */
    @GetMapping("/city/province-id")
    public String getProvinceIdByCityId(@RequestParam String cityId) {
        return provinceCityManager.getProvinceIdByCityId(cityId);
    }

    /**
     * 根据城市名称查询所在省份ID
     */
    @GetMapping("/city/province-id-by-name")
    public String getProvinceIdByCityName(@RequestParam String cityName) {
        return provinceCityManager.getProvinceIdByCityLabel(cityName);
    }

    /**
     * 根据城市ID查询所在省份名称
     */
    @GetMapping("/city/province-label")
    public String getProvinceLabelByCityId(@RequestParam String cityId) {
        return provinceCityManager.getProvinceLabelByCityId(cityId);
    }

    /**
     * 根据城市名称查询所在省份名称
     */
    @GetMapping("/city/province-label-by-name")
    public String getProvinceLabelByCityName(@RequestParam String cityName) {
        return provinceCityManager.getProvinceLabelByCityLabel(cityName);
    }

    /**
     * 获取所有省份信息
     */
    @GetMapping("/provinces/all")
    public List<ProvinceCityVO> getAllProvinces() {
        return provinceCityManager.getAllProvinces();
    }

    /**
     * 获取所有城市信息
     */
    @GetMapping("/cities/all")
    public List<ProvinceCityVO.CityVO> getAllCities() {
        return provinceCityManager.getAllCities();
    }

    /**
     * 检查省份是否存在
     */
    @GetMapping("/province/exists")
    public boolean isProvinceExists(@RequestParam String provinceId) {
        return provinceCityManager.isProvinceExists(provinceId);
    }

    /**
     * 检查城市是否存在
     */
    @GetMapping("/city/exists")
    public boolean isCityExists(@RequestParam String cityId) {
        return provinceCityManager.isCityExists(cityId);
    }
}
