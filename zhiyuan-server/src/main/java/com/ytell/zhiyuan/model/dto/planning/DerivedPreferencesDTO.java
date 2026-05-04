package com.ytell.zhiyuan.model.dto.planning;

import com.google.common.collect.Lists;
import lombok.Data;

import java.util.List;

@Data
public class DerivedPreferencesDTO {
    private List<String> recommendedMajorClusters = Lists.newArrayList();
    private String riskToleranceInferred;
    private String tuitionFlexibilityInferred;
    private List<String> employmentOrientationInferred = Lists.newArrayList();
}
