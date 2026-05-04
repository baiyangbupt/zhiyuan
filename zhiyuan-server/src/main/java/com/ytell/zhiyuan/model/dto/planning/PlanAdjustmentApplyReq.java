package com.ytell.zhiyuan.model.dto.planning;

import com.google.common.collect.Lists;
import lombok.Data;

import java.util.List;

@Data
public class PlanAdjustmentApplyReq {
    private List<String> suggestionIds = Lists.newArrayList();
    private String applyMode = "reorder_only";
}
