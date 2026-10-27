package com.ytell.zhiyuan.model.dto.planning;

import lombok.Data;

/**
 * 审查能力的可用性投影。
 *
 * <p>与历史审查结果分开：即使存储里仍有旧的 summary/findings，paused 时对外也必须先读
 * 这里。{@code mode=paused} 表示本轮没有运行质量评价，不能解释成“审查通过”。</p>
 */
@Data
public class ReviewAvailabilityDTO {
    private String mode = "active";
    private String reasonCode;
    private String policyVersion;
}
