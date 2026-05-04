package com.ytell.zhiyuan.model.dto;

import lombok.Data;

import java.math.BigDecimal;
import java.util.Date;
import java.util.List;

/**
 * 专业画像数据模型
 *
 * @author gaotu-assistant
 * @date 2024-12-19
 */
@Data
public class MajorProfileDto {
    private String id;

    /**
     * 专业代码
     */
    private String majorCode;

    /**
     * 专业名称
     */
    private String name;

    /**
     * 专业层次
     */
    private String majorLevel;

    /**
     * 类别ID
     */
    private String categoryId;

    /**
     * 子类别ID
     */
    private String subCategoryId;

    /**
     * 文科比例
     */
    private BigDecimal wRatio;

    /**
     * 理科比例
     */
    private BigDecimal lRatio;

    /**
     * 男性比例
     */
    private BigDecimal maleRatio;

    /**
     * 女性比例
     */
    private BigDecimal femaleRatio;

    /**
     * 学制时间
     */
    private String studyTime;

    /**
     * 学位
     */
    private String degree;

    /**
     * 简介信息
     */
    private String synopsisInfo;

    /**
     * 培养目标
     */
    private String trainObjective;

    /**
     * 培养要求
     */
    private String trainDemand;

    /**
     * 学科要求
     */
    private String subjectDemand;

    /**
     * 知识
     */
    private String knowledge;

    /**
     * 研究生
     */
    private String postgraduate;

    /**
     * 课程
     */
    private String course;

    /**
     * 就业方向
     */
    private String jobOrientation;

    /**
     * 公众人物
     */
    private String publicFigure;

    /**
     * 实习
     */
    private String internship;

    /**
     * 资格证书
     */
    private String qualification;

    /**
     * 升学方向
     */
    private String upgradOrientation;

    /**
     * 选择信息
     */
    private String selectInfo;
    private List<List<String>> selectLimit;

    /**
     * 选择群体
     */
    private String selectGroup;

    /**
     * 创建者
     */
    private String createdBy;

    /**
     * 创建时间
     */
    private Date createTime;

    /**
     * 租户代码
     */
    private String tenantCode;

    /**
     * 更新者
     */
    private String updatedBy;

    /**
     * 更新时间
     */
    private Date updateTime;

    /**
     * 学科倾向来源
     */
    private String subjectTendencySource;

    /**
     * 学科倾向
     */
    private String subjectTendency;

    /**
     * 子类别
     */
    private String subCategory;

    /**
     * 类别
     */
    private String category;

    /**
     * 学科分工倾向
     */
    private String subjectDivisionTendency;

    /**
     * 性别倾向
     */
    private String genderTendency;

    /**
     * 性格倾向
     */
    private String personalityTendency;

    /**
     * 毕业倾向
     */
    private String graduateTendency;

    /**
     * 职业
     */
    private String profession;

    /**
     * 行业
     */
    private String industry;

    /**
     * 工作单位
     */
    private String workUnit;

    /**
     * 工作风格
     */
    private String workStyle;

    /**
     * 就业热度权重
     */
    private BigDecimal jobHotnessWeight;

    /**
     * 兴趣倾向
     */
    private String interestTendency;
}
