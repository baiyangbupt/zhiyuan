package com.ytell.zhiyuan.model.vo;

import lombok.Data;

import java.util.List;

/**
 * 省市数据VO
 */
@Data
public class ProvinceCityVO {

    /**
     * 省份ID
     */
    private String id;

    /**
     * 省份名称
     */
    private String label;

    /**
     * 省份拼音前缀
     */
    private String prefix;

    /**
     * 是否启用
     */
    private Boolean isUse;

    /**
     * 是否直辖市
     */
    private Boolean isDirect;

    /**
     * 城市列表
     */
    private List<CityVO> children;

    /**
     * 城市VO
     */
    @Data
    public static class CityVO {

        /**
         * 城市ID
         */
        private String id;

        /**
         * 城市名称
         */
        private String label;

        /**
         * 所属省份ID
         */
        private String parentId;

        /**
         * 是否启用
         */
        private Boolean isUse;
    }
}
