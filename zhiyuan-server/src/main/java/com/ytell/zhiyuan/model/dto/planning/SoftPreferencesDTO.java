package com.ytell.zhiyuan.model.dto.planning;

import com.google.common.collect.Lists;
import lombok.Data;

import java.util.List;

@Data
public class SoftPreferencesDTO {
    private List<String> preferRegions = Lists.newArrayList();
    private List<String> preferMajors = Lists.newArrayList();
    private List<String> preferSchools = Lists.newArrayList();
    private List<String> avoidRegions = Lists.newArrayList();
    private List<String> avoidMajors = Lists.newArrayList();
    private List<String> avoidSchools = Lists.newArrayList();
    private String riskStyle;
}
