package com.ytell.zhiyuan.model.dto.planning;

import com.google.common.collect.Lists;
import lombok.Data;

import java.util.List;

@Data
public class FamilyContextDTO {
    private String financialLevel;
    private String tuitionTolerance;
    private List<String> familyExpectations = Lists.newArrayList();
    private List<String> parentOccupations = Lists.newArrayList();
    private List<String> resourceSupportTags = Lists.newArrayList();
}
