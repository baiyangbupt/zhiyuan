package com.ytell.zhiyuan.model.dto.planning;

import lombok.Data;

@Data
public class ReviewSummaryDTO {
    private Integer totalRuleCount = 0;
    private Integer passedRuleCount = 0;
    private Integer warnRuleCount = 0;
    private Integer riskRuleCount = 0;
    private Integer total = 0;
    private Integer passedCount = 0;
    private Integer warnCount = 0;
    private Integer riskCount = 0;
    /** 审查 2.0 四级计数（2026-10-16 review §五-58；只统计未通过的检查，即当前生效的发现）。 */
    private Integer blockCount = 0;
    private Integer actionCount = 0;
    private Integer noticeCount = 0;
    private Integer infoCount = 0;
}
