package com.ytell.zhiyuan.model.dto.planning;

import com.google.common.collect.Lists;
import com.ytell.zhiyuan.model.dto.CreateSessionReq;
import lombok.Data;

import java.util.List;

@Data
public class PendingPlanningCommandReq {
    private String operationId;
    private String pendingId;
    private String claimToken;
    private Integer expectedPlanVersion;
    private String commandType;
    private UpdateConstraintStateReq constraintUpdate;
    private Integer minTuitionPerYear;
    private Integer maxTuitionPerYear;
    private Boolean regenerateOrderedPlan = false;
    /**
     * add_units 新链路：执行后是否重跑审查。默认 null＝调用方未提供（由 frozenCommand 决定）；
     * legacy 默认不提供（保持旧行为）。显式提供时才与 frozen 比对。
     */
    private Boolean rerunReview;
    private List<String> unitIds = Lists.newArrayList();
    private List<String> volunteerIds = Lists.newArrayList();
    private FixProposalApplyReq proposalApply;
    /** `update_score_detail` 的执行输入：模型草稿原样（执行侧会与服务端既有成绩再合并一次）。 */
    private CreateSessionReq scoreUpdate;
}
