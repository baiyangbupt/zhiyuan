package com.ytell.zhiyuan.model.dto.planning;

import lombok.Data;

import java.util.List;

/**
 * 参与比较的一个招生单元，连同它的**口径身份**。
 *
 * <p>口径字段（年份/省份/批次/招生模式/率单位）必须与实体一起传：
 * `CandidateItemDTO` 里没有它们，而"能不能做数值差"完全取决于口径是否一致。
 * 靠比较方各自猜口径，就会出现"2024 的分数减去 2026 的分数"这种差。
 */
@Data
public class ComparisonEntityDTO {
    private String entityId;
    private String schoolId;
    private String schoolName;
    private String majorId;
    private String majorName;
    private String cityName;

    /** 口径身份。缺失即视为不可比，而不是"默认同口径"。 */
    private Integer admissionYear;
    private String areaId;
    private String batch;
    private String admissionMode;
    private String rateUnit;

    /** 学校口径的录取率。**不等于**该专业的录取率。 */
    private Double schoolEnrollRatio;
    /** 该招生单元口径的录取率（来自对应层级的事实）。 */
    private Double admissionRatio;
    /** 匹配分（Rank 计算的软分），**不是概率**。 */
    private Double finalScore;
    private Integer planNum;
    private Integer tuitionPerYear;
    private List<String> mustSubjects;
    private List<String> riskFlags;
}
