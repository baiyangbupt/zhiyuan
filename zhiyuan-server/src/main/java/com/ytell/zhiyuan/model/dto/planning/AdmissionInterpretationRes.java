package com.ytell.zhiyuan.model.dto.planning;

import lombok.Data;

import java.util.ArrayList;
import java.util.List;

/** 当前方案的结构与条件情景说明（只读，不是录取预测）。 */
@Data
public class AdmissionInterpretationRes {

    public static final String STATUS_COMPLETED = "completed";
    public static final String STATUS_NO_PLAN = "no_plan";

    public static final String SAFETY_HAS_COVER = "有保底档位";
    public static final String SAFETY_HAS_COVER_DATA_GAP = "保底档位存在、数据不足";
    public static final String SAFETY_NO_COVER = "无保底档位";
    public static final String SAFETY_UNKNOWN = "无法判断";

    public static final String COMPLETENESS_FULL = "完整";
    public static final String COMPLETENESS_PARTIAL = "有缺口";
    public static final String COMPLETENESS_SEVERE = "严重缺口";

    private String status;
    private Integer planVersion;
    private String generatedAt;
    private String admissionMode;
    private List<LandingScenarioDTO> scenarios = new ArrayList<LandingScenarioDTO>();
    private LandingScenarioDTO baseLanding;
    /** 结构覆盖：有/无/数据不足/无法判断；不是滑档概率。 */
    private String safetyCoverage;
    private Double tierCoverage;
    private Double ratioCoverage;
    private Double dataCompleteness;
    private String dataCompletenessBand;
    private Boolean orderAnomaly;
    private List<String> caveats = new ArrayList<String>();
    /** 与 caveats 同序的 structured 版本（旧消费者仍读 caveats）。 */
    private List<InterpretationCaveatDTO> caveatDetails = new ArrayList<InterpretationCaveatDTO>();
}
