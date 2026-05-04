package com.ytell.zhiyuan.model.dto.planning;

import com.google.common.collect.Lists;
import lombok.Data;

import java.util.List;

@Data
public class ExplicitProfileDTO {
    private List<String> positiveMajors = Lists.newArrayList();
    private List<String> negativeMajors = Lists.newArrayList();
    private List<String> positiveSchools = Lists.newArrayList();
    private List<String> negativeSchools = Lists.newArrayList();
    private List<String> positiveRegions = Lists.newArrayList();
    private List<String> negativeRegions = Lists.newArrayList();
    private List<String> strengthSubjects = Lists.newArrayList();
}
