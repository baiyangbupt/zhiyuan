package com.ytell.zhiyuan.model.dto.planning;

import com.google.common.collect.Maps;
import lombok.Data;

import java.util.Map;

/**
 * 方案结构指标（只作为评价输出/展示，不允许拿它反算 probe）。
 * item 与 unit 两套计数必须分开：group 模式看 unit，major 模式看 item。
 */
@Data
public class StructureVectorDTO {
    private Integer unitCount = 0;
    private Integer itemCount = 0;
    private Map<String, Integer> tierCounts = Maps.newLinkedHashMap();
    private Map<String, Integer> unitTierCounts = Maps.newLinkedHashMap();
    private Integer localSafetyUnitCount = 0;
    private Double adjacentRatioDeltaMax = 0D;
    private Integer highTuitionCount = 0;
    private Integer cooperativeCount = 0;
    private Integer specialEnrollmentCount = 0;
    private Integer admissionLimitCount = 0;
}
