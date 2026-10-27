package com.ytell.zhiyuan.model.dto.planning;

import com.alibaba.fastjson.annotation.JSONField;
import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Data;

@Data
public class OrderedPlanGenerateReq {
    private Boolean forceRegenerate = false;
    private Boolean regroupByTier = false;
    /**
     * 仅 initial_auto 使用：把初始数量目标临时交给 staged solver；
     * 不写入 constraintState，不作为 durable 用户目标。
     */
    private Integer initialSelectionTargetCount;
    /** initial_auto 专用：开启初始方案内容护栏（风险标签/条目膨胀/preferred 丢失）。 */
    private Boolean initialMode = false;
    /** 纯删除收敛：允许保留尚未清掉的存量专项冲突项；新增/补齐/替换不得使用。 */
    @JSONField(deserialize = false)
    @JsonProperty(access = JsonProperty.Access.READ_ONLY)
    private Boolean allowExistingSpecialPlanConflicts = false;
}
