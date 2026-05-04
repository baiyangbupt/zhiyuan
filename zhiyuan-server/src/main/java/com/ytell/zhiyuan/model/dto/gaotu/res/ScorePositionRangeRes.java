package com.ytell.zhiyuan.model.dto.gaotu.res;

import lombok.Data;

/**
 * 根据分数获取位次范围响应结果
 */
@Data
public class ScorePositionRangeRes {
    
    /**
     * 分数
     */
    private String score;
    
    /**
     * 学生人数
     */
    private Integer students;
    
    /**
     * 最高排名（最小位次）
     */
    private Integer highestRank;
    
    /**
     * 最低排名（最大位次）
     */
    private Integer lowestRank;
    
    /**
     * 数据级别
     */
    private String dataLevel;
    
    /**
     * 组标签
     */
    private String groupTag;
}
