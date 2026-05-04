package com.ytell.zhiyuan.model.dto.planning;

import com.google.common.collect.Lists;
import lombok.Data;

import java.util.List;

@Data
public class OrderedUnitDTO {
    private Integer position;
    private String unitId;
    private String tier;
    private String schoolName;
    private String provinceName;
    private String cityName;
    private String source;
    private Boolean locked = false;
    private Boolean pinned = false;
    private Integer pinnedPosition;
    private String orderedBy;
    private String orderReason;
    private Double admissionRatio;
    private Double finalScore;
    private Double schoolEnrollRatio;
    private List<PlanningUnitMajorDTO> majorItems = Lists.newArrayList();
}
