package com.ytell.zhiyuan.model.dto.planning;

import lombok.Data;

/**
 * J5.3 P4 可选的多样性软惩罚配置。
 *
 * <p>默认 {@code mode=off}：求解器不建任何分组变量/约束，行为与未引入
 * 该字段完全一致。{@code mode=soft} 时在 utility 最优集合内最小化
 * “超出分组 cap 的实体数”，再按 stableOrder 做次级平局。</p>
 */
@Data
public class DiversityPolicyDTO {
    /** off | soft；默认 off。 */
    private String mode = "off";
    /** 地域（provinceName）分组 cap 占比；默认 0.4。 */
    private Double regionShare = 0.4D;
    /** 专业类（majorCategoryId）分组 cap 占比；默认 0.4。 */
    private Double majorCategoryShare = 0.4D;
    /** 院校层次（schoolLevel）分组 cap 占比；默认 0.6。 */
    private Double schoolLevelShare = 0.6D;
    /** 参与约束的分组数上限；超过按 (candidateCount ↓, key ↑) 截断。 */
    private Integer maxGroups = 32;
}
