package com.ytell.zhiyuan.model.dto.planning;

import com.google.common.collect.Lists;
import lombok.Data;

import java.util.List;

@Data
public class PendingPlanningCommandRes {
    private String operationId;
    private String pendingId;
    private String commandType;
    private Integer sourcePlanVersion;
    private Integer resultPlanVersion;
    /**
     * 显式执行状态（`applied` / `failed`）。没有它时网关只能从 `postconditionReport`
     * 或业务码反推成败——`update_score_detail` 这条路上没有满足度报告，把结论写在这儿
     * 比让消费者去猜"字段在不在"可靠（网关 `_status()` 优先读它）。
     */
    private String status;
    private Boolean replayed = false;
    private List<String> completedSteps = Lists.newArrayList();
    private PlanChangePostconditionReportDTO postconditionReport;
    private PlanningStateDTO planningState;
    /** add_units / replace_units 的逐条回执（冻结命令执行后的净变化）。 */
    private List<String> addedVolunteerIds = Lists.newArrayList();
    private List<String> addedUnitIds = Lists.newArrayList();
    private List<String> removedVolunteerIds = Lists.newArrayList();
    private List<String> removedUnitIds = Lists.newArrayList();
    private Integer addedVolunteerCount;
    private Integer addedUnitCount;
    private Integer removedVolunteerCount;
    private Integer targetCountBefore;
    private Integer targetCountAfter;
    /** 约束执行后的数量缺口（纯学费/替换类）：0 = 总数保持；>0 正常会被 40905 回滚。 */
    private Integer shortage;
    /** 紧凑审查回执（summary + top checks）；完整 reviewState 仍在 planningState 里。 */
    private ReviewStateDTO reviewState;
}
