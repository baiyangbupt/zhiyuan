package com.ytell.zhiyuan.model.dto.planning;

import com.google.common.collect.Lists;
import lombok.Data;

import java.util.List;

@Data
public class ReplacementPairDTO {
    private String fromUnitId;
    private String fromVolunteerId;
    private String toUnitId;
    private String toVolunteerId;
    private List<String> reasonCodes = Lists.newArrayList();
}
