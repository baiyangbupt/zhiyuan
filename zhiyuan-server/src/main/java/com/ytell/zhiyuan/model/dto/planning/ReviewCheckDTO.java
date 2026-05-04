package com.ytell.zhiyuan.model.dto.planning;

import com.google.common.collect.Lists;
import lombok.Data;

import java.util.List;

@Data
public class ReviewCheckDTO {
    private String code;
    private String level;
    private Boolean passed;
    private String summary;
    private String detail;
    private String suggestedAction;
    private List<String> affectedUnitIds = Lists.newArrayList();
    private List<String> affectedVolunteerIds = Lists.newArrayList();
    private List<CompensationActionDTO> suggestedCompensations = Lists.newArrayList();
}
