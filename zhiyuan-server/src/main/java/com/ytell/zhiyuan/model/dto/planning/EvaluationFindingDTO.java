package com.ytell.zhiyuan.model.dto.planning;

import com.google.common.collect.Lists;
import com.google.common.collect.Maps;
import lombok.Data;

import java.util.List;
import java.util.Map;

/**
 * 评价结论（J5.0 目标态）。四个字段各管一件事：
 * resultStatus=评价结果；ruleStrength=规则/用户强度；displaySeverity=展示严重度；
 * fixability=是否有可用修复。禁止用旧 check 名批量推断 layer/strength。
 */
@Data
public class EvaluationFindingDTO {
    private String code;
    private String layer;
    private String resultStatus;
    private String ruleStrength;
    private String displaySeverity;
    private String fixability;
    private String metric;
    private Map<String, Object> threshold = Maps.newLinkedHashMap();
    private String summary;
    private List<EvaluationEntryRefDTO> affectedEntryRefs = Lists.newArrayList();
    private ObjectiveDeltaDTO objectiveDelta;
    /**
     * 目标态应由 ActionCompiler 从 objectiveDelta 编译；J5.0 影子阶段恒为 null，
     * 避免出现“delta 与 command 两套修复”的分叉。
     */
    private Object suggestedCommand;
    private String source = "probe";
    private String reasonCode;
}
