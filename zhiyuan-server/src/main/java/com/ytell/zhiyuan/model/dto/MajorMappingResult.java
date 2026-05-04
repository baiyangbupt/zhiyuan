package com.ytell.zhiyuan.model.dto;

import lombok.Data;

/**
 * 专业映射查询结果DTO
 */
@Data
public class MajorMappingResult {

    /**
     * 三级专业ID
     */
    private String thirdLevelId;

    /**
     * 三级专业名称
     */
    private String thirdLevelName;

    /**
     * 二级专业ID
     */
    private String secondLevelId;

    /**
     * 二级专业名称
     */
    private String secondLevelName;
} 