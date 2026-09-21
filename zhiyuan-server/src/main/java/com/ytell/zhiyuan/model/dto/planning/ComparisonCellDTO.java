package com.ytell.zhiyuan.model.dto.planning;

import lombok.Data;

/**
 * 比较矩阵的一个单元格。
 *
 * <p>每个格子自带**来源与口径**：同一张表里混着不同年份/省份的数据时，
 * 没有来源的格子无法被核对，而核对不了的数字和没有数字一样没用。
 */
@Data
public class ComparisonCellDTO {
    private String entityId;
    private String dimension;
    private Object value;
    private String unit;
    /** 这一格的值从哪来：字段路径或来源系统。 */
    private String source;
    /** 非空表示这格**没有值**，值是"不可用"而不是零。 */
    private String unavailableReason;
}
