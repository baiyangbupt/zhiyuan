package com.ytell.zhiyuan.model.vo;

import lombok.Data;

/**
 * 学校信息VO
 */
@Data
public class SchoolVO {

    /**
     * 标准院校ID
     */
    private String schoolId;

    /**
     * 标准院校名称
     */
    private String schoolName;

    /**
     * 院校省份
     */
    private String province;

    /**
     * 院校城市
     */
    private String city;

    /**
     * 院校省份ID
     */
    private String provinceId;

    /**
     * 院校城市ID
     */
    private String cityId;

    /**
     * 学校隶属
     */
    private String affiliation;

    /**
     * 学校类型
     */
    private String schoolType;

    /**
     * 学校标签
     */
    private String schoolTags;

    /**
     * 公办民办
     */
    private String ownership;

    /**
     * 本科专科
     */
    private String educationLevel;

    /**
     * 学校排名
     */
    private Integer schoolRank;
}
