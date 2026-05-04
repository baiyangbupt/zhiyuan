package com.ytell.zhiyuan.model.dto.planning;

import com.google.common.collect.Lists;
import lombok.Data;

import java.util.List;

@Data
public class FutureDevelopmentDTO {
    private List<String> careerTypes = Lists.newArrayList();
    private List<String> industryPreferences = Lists.newArrayList();
    private List<String> workStylePreferences = Lists.newArrayList();
    private List<String> organizationPreferences = Lists.newArrayList();
    private List<String> lifeStylePreferences = Lists.newArrayList();
    private String stabilityVsIncome;
}
