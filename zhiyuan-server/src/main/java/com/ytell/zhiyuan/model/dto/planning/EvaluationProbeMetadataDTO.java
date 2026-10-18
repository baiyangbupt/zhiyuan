package com.ytell.zhiyuan.model.dto.planning;

import com.google.common.collect.Lists;
import lombok.Data;

import java.util.List;

/** Probe 元数据（注册表条目）。只描述口径，不执行规则。 */
@Data
public class EvaluationProbeMetadataDTO {
    private String code;
    private String label;
    /** hard / structure / soft */
    private String layer;
    /** hard / soft / policy */
    private String ruleStrength;
    /** 该 probe 允许出现的 displaySeverity 集合。 */
    private List<String> allowedSeverities = Lists.newArrayList();
    private String metric;
    /** unit / item / structure / plan */
    private String scope;
    /** none / preview_fixable / manual */
    private String fixability;
    /** 旧 check code；count 拆分时写来源。 */
    private String sourceCheck;
    private String probeVersion;
}
