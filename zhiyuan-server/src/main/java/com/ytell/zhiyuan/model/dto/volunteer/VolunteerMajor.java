package com.ytell.zhiyuan.model.dto.volunteer;

import lombok.Data;

import java.util.List;

/**
 * 专业数据结构
 */
@Data
public class VolunteerMajor {
    // 专业基础信息
    private String majorId;               // 专业ID
    private String majorName;             // 专业名称
    private String majorUnitCode;         // 专业代码
    private String planMajorDataId;       // 专业招生计划ID
    private String categoryId;            // 专业一级分类
    private String subCategoryId;         // 专业二级分类

    // 专业录取信息
    private Double majorEnrollRatio;      // 专业录取率（数值）
    private String majorEnrollRatioStr;   // 专业录取率（字符串）
    private String majorVolunteerLevel;   // 专业冲稳保等级

    // 其他信息
    private Integer planNum;              // 计划数量
    private Integer score;                // 分数
    private Long pos;                     // 位次
    private String selectInfo;            // 选科要求
    private Boolean isNew;                // 是否新增
    private Boolean isDoubleFirstMajor;   // 是否双一流专业

    private String planMoney;//专业费用

    private String duration;//专业学制

    // 专业历史录取数据（使用简化的数据结构）
    private List<HistoryRecordDTO> historyRecords;

    // 专业评估指标
    private Double gender_index;          // 性别指数
    private Double satisfy_index;         // 专业满意度指数
    private Double salary_avg;            // 平均薪酬指数
    private Double hot_index;             // 专业热度指数
    private Integer evaluate_score;       // 学科评估得分
    private Integer special_score;        // 特色专业得分
    private Integer degree_score;         // 硕博点得分
    private Double major_score_old;       // 专业（类）原始得分
    private Double major_score_new;       // 专业（类）最终得分
    private String major_remark;          // 专业（类）得分调整说明
    private String degree;//#硕博点情况:master;doctor;null
    private String major_level;//#学科评估情况：A+等;null
}

