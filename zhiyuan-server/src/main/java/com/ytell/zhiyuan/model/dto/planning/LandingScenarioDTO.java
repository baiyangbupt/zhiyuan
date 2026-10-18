package com.ytell.zhiyuan.model.dto.planning;

import lombok.Data;

import java.util.ArrayList;
import java.util.List;

/**
 * 一条**结构/条件情景**，不是录取概率或落点预测。
 *
 * <p>label：upside/base/downside/no_safe。structureStatus 只描述结构位置，
 * condition 描述该情景成立的前置假设（如“若前序均未满足”），不做风险判定。
 */
@Data
public class LandingScenarioDTO {

    public static final String LABEL_UPSIDE = "upside";
    public static final String LABEL_BASE = "base";
    public static final String LABEL_DOWNSIDE = "downside";
    public static final String LABEL_NO_SAFE = "no_safe";

    public static final String STRUCTURE_FIRST_STABLE = "首个稳/保位置";
    public static final String STRUCTURE_BEST_REACH = "冲档最高校线率位置";
    public static final String STRUCTURE_LAST_SAFE = "最后保底位置";
    public static final String STRUCTURE_NO_SAFE = "无保底档位";
    public static final String STRUCTURE_UNKNOWN = "无法判断";

    public static final String CONDITION_PRIOR_MISSED = "若前序均未满足";
    public static final String CONDITION_REACH_HIT = "若冲档命中";
    public static final String CONDITION_NONE = "无";

    private String scenarioId;
    private String label;
    private String structureStatus;
    private String condition;
    private InterpretationEntryDTO landingEntry;
    private List<InterpretationEntryDTO> path = new ArrayList<InterpretationEntryDTO>();
    private List<String> drivers = new ArrayList<String>();
    private List<String> caveats = new ArrayList<String>();
    private List<String> evidenceRefs = new ArrayList<String>();
}
