package com.ytell.zhiyuan.model.dto;

import lombok.Data;

/**
 * 专业类概述数据传输对象
 * 用于存储专业类的详细信息
 *
 * @author gaotu-assistant
 * @date 2024-12-19
 */
@Data
public class MajorCategoryProfileDto {

    /**
     * 专业类ID
     */
    private String majorCategoryId;

    /**
     * 专业类
     */
    private String majorCategory;

    /**
     * 专业概述
     */
    private String majorOverview;

    /**
     * 学习课程
     */
    private String studyCourses;

    /**
     * 就业方向
     */
    private String employmentDirection;

    /**
     * 薪资情况
     */
    private String salaryStatus;

    /**
     * 就业地域
     */
    private String employmentRegion;
}
