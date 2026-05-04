package com.ytell.zhiyuan.model.dto.planning;

import com.google.common.collect.Lists;
import lombok.Data;

import java.util.List;

@Data
public class DraftUnitDTO {
    private String unitId;
    private String tier;
    private String schoolName;
    private String source;
    private Boolean locked = false;
    private List<PlanningUnitMajorDTO> majorItems = Lists.newArrayList();
}
