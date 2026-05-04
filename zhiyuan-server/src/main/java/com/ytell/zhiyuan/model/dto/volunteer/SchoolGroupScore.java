package com.ytell.zhiyuan.model.dto.volunteer;

import lombok.Data;

import java.util.Map;

/**
 * 专业组得分
 */
@Data
public class SchoolGroupScore {
    private double preferenceScore; // 用户意愿评分（包含院校、专业、地域三个维度）
    private int preferredMajorCount; // 包含用户意愿专业类的数量
    private Map<Integer, Integer> tierDistribution; // 梯队分布
    private double totalEmploymentRate; // 就业率之和
    private double totalScore; // 综合得分
}

