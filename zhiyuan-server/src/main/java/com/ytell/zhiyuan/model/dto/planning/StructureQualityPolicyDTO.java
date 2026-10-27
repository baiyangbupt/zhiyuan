package com.ytell.zhiyuan.model.dto.planning;

import lombok.Data;

/**
 * 结构质量策略：录取率桶集中 + 多样性软约束。
 * 默认 off；由运行时开关或影子服务显式注入。
 */
@Data
public class StructureQualityPolicyDTO {
    private String version = "structure-quality-v1";
    /** off | soft | enforced（enforced 仍不改变省份槽位）。 */
    private String mode = "off";
    /** 同档 unknown/1.0 桶允许占比。 */
    private Double maxUnknownBucketShare = 0.4D;
    /** 同档单桶允许占比。 */
    private Double maxSingleBucketShare = 0.5D;
    /** 最少覆盖的已知桶数（unknown 不算覆盖）。 */
    private Integer minBucketCoverage = 2;
    /** 结构优化允许牺牲的效用上限（相对无约束效用最优值）；默认 3%。 */
    private Double maxUtilityLossRatio = 0.03D;
}
