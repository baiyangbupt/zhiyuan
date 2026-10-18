package com.ytell.zhiyuan.model.dto.planning;

import com.google.common.collect.Lists;
import lombok.Data;

import java.util.List;

/** J5.3 软结构目标：档位锚 + 本省保底缺口。 */
@Data
public class StructureTargetDTO {
    private TierCountsDTO tierAnchor;
    private Integer minLocalProtect = 0;
    /** applicable | not_applicable | unknown */
    private String safetyFloorMode = "applicable";
    private String safetyFloorReasonCode;
    private List<String> diagnostics = Lists.newArrayList();
}
