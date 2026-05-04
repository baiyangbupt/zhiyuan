package com.ytell.zhiyuan.model.dto.planning;

import com.google.common.collect.Lists;
import lombok.Data;

import java.util.List;

@Data
public class CompensationPreviewDTO {
    private String status = "idle";
    private Integer sourceVersion;
    private Integer totalActions = 0;
    private List<CompensationActionDTO> actions = Lists.newArrayList();
}
