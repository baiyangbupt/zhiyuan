package com.ytell.zhiyuan.model.vo;

import lombok.Data;

import java.util.List;

/**
 * 大区省份数据VO
 */
@Data
public class RegionProvinceVO {

    /**
     * 大区名称（如：华东、华北、华南等）
     */
    private String regionName;

    /**
     * 大区下的省份列表
     */
    private List<ProvinceCityVO> provinces;

    /**
     * 构造函数
     */
    public RegionProvinceVO() {
    }

    /**
     * 构造函数
     *
     * @param regionName 大区名称
     * @param provinces  省份列表
     */
    public RegionProvinceVO(String regionName, List<ProvinceCityVO> provinces) {
        this.regionName = regionName;
        this.provinces = provinces;
    }
}
