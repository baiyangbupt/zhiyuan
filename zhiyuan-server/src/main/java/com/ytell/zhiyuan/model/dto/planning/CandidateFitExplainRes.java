package com.ytell.zhiyuan.model.dto.planning;

import com.google.common.collect.Lists;
import lombok.Data;

import java.util.List;

/**
 * 适配性解释（只读）响应：**某一个**候选的匹配点、风险与维度状态。
 *
 * <p>契约上最要紧的四点：</p>
 * <ul>
 *   <li>{@code matched} 里的每一条都带 {@code source}——**只引用带 source 的条目**
 *       是下游的硬规则：没有来源的"匹配"就是模型自己编的，不许说；</li>
 *   <li>{@code risks.flags}/{@code risks.reasonCodes} 是候选行
 *       {@code riskFlags}/{@code reasonCodes} 的**逐字透传**（不改写、不翻译），
 *       {@code risks.facts} 只放候选行里的**事实陈述**（tier / rankInTier）；</li>
 *   <li>{@code probability} 恒为 {@code status=unavailable} + 原因（无权威概率源）：
 *       本切片**不产出任何录取概率数字**，"适配"（偏好/约束匹配度）与"概率"
 *       是两件事，不能混说；</li>
 *   <li>{@code limitations} 汇总"哪里不可用/不可算"（缺画像字段、缺候选字段、
 *       entity 不存在等），而不是用 500 表达。</li>
 * </ul>
 */
@Data
public class CandidateFitExplainRes {

    /** 请求回显：候选池实体 ID（= volunteerId）。 */
    private String entityId;

    /** 候选行是否在候选池里找到。false 时 matched/risks/dimensions 均为空，
     *  原因进 {@code limitations}（entity_not_found:<id> / candidate_source_unavailable）。 */
    private boolean found;

    /** 候选行身份回显（找得到时才有）：院校名 / 专业名 / 档位。 */
    private String schoolName;
    private String majorName;
    private String tier;

    /** 会话规划版本（只读断言用：解释不改变它）。 */
    private Integer profileVersion;

    /** 匹配点：每条都带 source（来源字段对），供下游原样引用。 */
    private List<MatchedPoint> matched = Lists.newArrayList();

    /** 风险：候选行风险标志的逐字透传 + 事实陈述。 */
    private Risks risks = new Risks();

    /** 维度状态：选科要求 / 地域 / 专业意向 / 院校意向 / 学费区间。 */
    private List<Dimension> fitDimensions = Lists.newArrayList();

    /** 概率：恒 unavailable（无权威概率源）——禁止输出录取概率。 */
    private Probability probability = new Probability();

    private List<String> limitations = Lists.newArrayList();

    /**
     * 一条匹配点。{@code source} 为**来源字段对**（`A vs B`，两边都是响应/状态里的
     * 真实字段路径，如 `candidate.mustSubjects vs userScoreDetail.subjectList`）：
     * 下游只允许引用带 source 的条目，不得把无来源的"匹配"说给用户。
     */
    @Data
    public static class MatchedPoint {
        /** 维度名：subject_requirement / region_preference / major_intent / school_intent / tuition_range。 */
        private String dimension;
        /** 事实陈述（含具体取值），供转述；不含任何概率/预测。 */
        private String statement;
        /** 来源字段对（`候选行字段 vs 会话字段`）。**必填**：没有来源的匹配点不会出现在这里。 */
        private String source;
    }

    /** 风险区：候选行自带标志的逐字透传 + 事实。 */
    @Data
    public static class Risks {
        /** 候选行 `riskFlags` 逐字透传（不改写、不翻译、不增删）。 */
        private List<String> flags = Lists.newArrayList();
        /** 候选行 `reasonCodes` 逐字透传。 */
        private List<String> reasonCodes = Lists.newArrayList();
        /** 候选行里的事实陈述（tier / rankInTier），不做任何推断。 */
        private List<RiskFact> facts = Lists.newArrayList();
    }

    /** 一条事实：{@code field} 为候选行字段名，{@code value} 为原值字符串。 */
    @Data
    public static class RiskFact {
        private String field;
        private String value;

        public RiskFact() {
        }

        public RiskFact(String field, String value) {
            this.field = field;
            this.value = value;
        }
    }

    /**
     * 一个维度的适配状态。
     *
     * <p>状态取值：{@code matched}（命中至少一条正向偏好/约束）、{@code conflict}
     * （命中负向/排除项）、{@code no_match}（有偏好但没有命中）、{@code unknown}
     * （有一侧字段缺失，算不了——原因进 limitations）、{@code not_applicable}
     * （这一侧本来就没有可评估的内容，如候选无选科要求）。</p>
     */
    @Data
    public static class Dimension {
        private String dimension;
        private String status;
        /** 人话说明（含具体取值或缺少哪一项），不带概率。 */
        private String detail;
    }

    /**
     * 概率（恒不可用）。
     *
     * <p>{@code status} 固定 {@code unavailable}、{@code reason} 固定
     * {@code no_authoritative_probability_source}：本服务**没有任何权威概率来源**，
     * 宁可如实说不可用，也不估算。适配（匹配度）由 matched/fitDimensions 表达，
     * 与概率分开讲。</p>
     */
    @Data
    public static class Probability {
        private String status = "unavailable";
        private String reason = "no_authoritative_probability_source";
    }
}
