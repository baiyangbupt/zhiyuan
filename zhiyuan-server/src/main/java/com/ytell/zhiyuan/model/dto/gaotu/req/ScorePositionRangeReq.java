package com.ytell.zhiyuan.model.dto.gaotu.req;

import lombok.Data;

/**
 * 根据分数获取位次范围请求参数
 */
@Data
public class ScorePositionRangeReq {
    
    /**
     * 地区ID（如：370000代表山东）
     */
    private String areaId;
    
    /**
     * 科目类型（N表示新高考）
     */
    private String subject;
    
    /**
     * 数据级别（01表示省级）
     */
    private String dataLevel;
    
    /**
     * 年份（如：2026）
     */
    private String year;
    
    /**
     * 分数
     */
    private String score;
}
