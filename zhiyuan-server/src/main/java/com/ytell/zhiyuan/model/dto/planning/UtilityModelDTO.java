package com.ytell.zhiyuan.model.dto.planning;

import com.google.common.collect.Maps;
import lombok.Data;

import java.util.Map;

/** 效用模型版本与内部权重；不得序列化到用户可见 payload。 */
@Data
public class UtilityModelDTO {
    private String utilityModelVersion = "utility-model-v1";
    private Map<String, Integer> componentWeights = Maps.newLinkedHashMap();
}
