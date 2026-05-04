package com.ytell.zhiyuan.model.dto;

import lombok.Data;

import java.math.BigDecimal;

/**
 * 学校画像数据模型
 *
 * @author gaotu-assistant
 * @date 2024-12-19
 */
@Data
public class SchoolProfileDto {

    /**
     * 学校ID
     */
    private String schoolId;

    /**
     * 学校名称
     */
    private String name;

    /**
     * 省份
     */
    private String province;

    /**
     * 城市
     */
    private String city;

    /**
     * 区县
     */
    private String district;

    /**
     * 主管部门
     */
    private String authority;

    /**
     * 历史主管部门
     */
    private String historicAuthorities;

    /**
     * 历史荣誉
     */
    private String legacyHonor;

    /**
     * 办学层次
     */
    private String level;

    /**
     * 办学性质
     */
    private String nature;

    /**
     * 学校类别
     */
    private String category;

    /**
     * 研究生院
     */
    private String postgraduate;

    /**
     * 录取批次
     */
    private String batch;

    /**
     * 王牌专业
     */
    private String goatMajor;

    /**
     * 历史强势方向
     */
    private String legacyStrongSide;

    /**
     * 历史强势专业
     */
    private String legacyStrongMajor;

    /**
     * 双一流专业
     */
    private String doubleFirstMajor;

    /**
     * 第四轮评估名单
     */
    private String fourthEvaluateRoll;

    /**
     * 地区优势产业
     */
    private String districtFlourishingIndustry;

    /**
     * 城市优势产业
     */
    private String cityFlourishingIndustry;

    /**
     * 招生政策
     */
    private String recruitmentPolicy;

    /**
     * 招生政策来源标题
     */
    private String recruitmentPolicySourceTitle;

    /**
     * 招生政策来源内容
     */
    private String recruitmentPolicySourceContent;

    /**
     * 原城市优势产业
     */
    private String originCityFlourishingIndustry;

    /**
     * 教育排名
     */
    private String eduRank;

    /**
     * 教育特色
     */
    private String eduCharacteristic;

    /**
     * 教育热度
     */
    private String eduHotness;

    /**
     * 教育指数
     */
    private BigDecimal eduIndex;

    /**
     * 高途排名
     */
    private String gaotuRank;

    /**
     * 高途批次
     */
    private String gaotuBatch;

    /**
     * 一级硕士点
     */
    private String firstLevelMasterStation;

    /**
     * 一级博士点
     */
    private String firstLevelDoctorStation;

    /**
     * 专业学位硕士点
     */
    private String professionalDegreeMasterStation;

    /**
     * 专业学位博士点
     */
    private String professionalDegreeDoctorStation;

    /**
     * 升学率
     */
    private String upgradeRatio;

    /**
     * 保研率
     */
    private String postgraduateRecommendRatio;

    /**
     * 院士数量
     */
    private Integer academicianNumber;

    /**
     * 杰出校友数量
     */
    private Integer outstandingAlumniNumber;

    /**
     * 国家特色专业
     */
    private String nationalSpecializedMajor;
}
