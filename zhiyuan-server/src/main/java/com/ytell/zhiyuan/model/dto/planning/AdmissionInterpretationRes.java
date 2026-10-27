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

    public static final String TIER_SEQUENCE_DEFAULT = "default";
    public static final String TIER_SEQUENCE_INVERTED = "inverted";
    public static final String TIER_SEQUENCE_UNKNOWN = "unknown";
    public static final String TIER_SEQUENCE_ABSENT = "absent";

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
    /** 实际档位序列（冲/稳/保/unknown）；与是否用户主动排序分开表达。 */
    private List<String> tierSequence = new ArrayList<String>();
    /** default | inverted | unknown | absent。 */
    private String tierSequenceStatus;
    /** true/false 只表示已确认的用户排序；本轮没有来源时为 null（未知）。 */
    private Boolean userOrderRespected;
    /** 审查能力可用性；paused 时说明本解读不含质量审查结论。 */
    private ReviewAvailabilityDTO reviewAvailability;
    private List<String> caveats = new ArrayList<String>();
    /** 与 caveats 同序的 structured 版本（旧消费者仍读 caveats）。 */
    private List<InterpretationCaveatDTO> caveatDetails = new ArrayList<InterpretationCaveatDTO>();
}
