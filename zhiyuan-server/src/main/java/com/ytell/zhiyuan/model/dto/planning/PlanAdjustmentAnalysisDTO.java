package com.ytell.zhiyuan.model.dto.planning;

import com.google.common.collect.Lists;
import lombok.Data;

import java.util.List;

@Data
public class PlanAdjustmentAnalysisDTO {
    private String summaryText;
    private List<PlanAdjustmentRuleResultDTO> rules = Lists.newArrayList();
}
