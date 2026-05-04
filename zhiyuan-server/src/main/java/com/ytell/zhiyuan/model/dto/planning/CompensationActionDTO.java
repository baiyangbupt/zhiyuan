package com.ytell.zhiyuan.model.dto.planning;

import com.google.common.collect.Lists;
import lombok.Data;

import java.util.List;

@Data
public class CompensationActionDTO {
    private String type;
    private String level;
    private String summary;
    private String detail;
    private String sourceCheckCode;
    private List<String> unitIds = Lists.newArrayList();
    private List<String> volunteerIds = Lists.newArrayList();
}
