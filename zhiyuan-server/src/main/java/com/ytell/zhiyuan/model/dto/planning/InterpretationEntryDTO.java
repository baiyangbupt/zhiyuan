package com.ytell.zhiyuan.model.dto.planning;

import lombok.Data;

/**
 * 录取解读的输入/输出条目。
 *
 * <p>`pathTier` 是方案条目自己的档位（来自 OrderedItemDTO.tier），是路径判断的
 * 唯一档位来源；`schoolRatio` 只用于 upside 排序/证据；`majorRatio` 只做组内证据，
 * 不得反向覆盖 pathTier。
 */
@Data
public class InterpretationEntryDTO {

    public static final String LEVEL_UNIT = "unit";
    public static final String LEVEL_VOLUNTEER = "volunteer";

    public static final String TIER_CHONG = "冲";
    public static final String TIER_WEN = "稳";
    public static final String TIER_BAO = "保";
    public static final String TIER_UNKNOWN = "unknown";

    private String level;
    private String id;
    private Integer position;
    private String schoolName;
    private String majorName;
    private String pathTier;
    private Double schoolRatio;
    private Double majorRatio;
}
