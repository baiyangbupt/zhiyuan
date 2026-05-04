package com.ytell.zhiyuan.model.dto.planning;

import com.google.common.collect.Lists;
import lombok.Data;

import java.util.List;

@Data
public class HardConstraintsDTO {
    private List<String> mustIncludeRegions = Lists.newArrayList();
    private List<String> mustExcludeRegions = Lists.newArrayList();
    private List<String> mustIncludeMajors = Lists.newArrayList();
    private List<String> mustExcludeMajors = Lists.newArrayList();
}
