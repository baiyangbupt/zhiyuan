package com.ytell.zhiyuan.model.dto.planning;

import com.google.common.collect.Lists;
import lombok.Data;

import java.util.List;

@Data
public class CoverageRequirementDTO {
    private String domain;
    private String key;
    private List<String> values = Lists.newArrayList();
    private Integer minCount = 1;
}
