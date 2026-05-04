package com.ytell.zhiyuan.model.dto.planning;

import com.google.common.collect.Lists;
import lombok.Data;

import java.util.List;

@Data
public class OperationLogDTO {
    private String type;
    private String operator;
    private String detail;
    private String createdAt;
    private List<String> volunteerIds = Lists.newArrayList();
}
