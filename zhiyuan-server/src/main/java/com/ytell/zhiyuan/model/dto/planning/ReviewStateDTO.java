package com.ytell.zhiyuan.model.dto.planning;

import com.google.common.collect.Lists;
import lombok.Data;

import java.util.List;

@Data
public class ReviewStateDTO {
    private String status = "idle";
    private String reviewedAt;
    private Integer sourceVersion;
    private ReviewSummaryDTO summary = new ReviewSummaryDTO();
    /**
     * 旧审查规则输出（兼容字段）。
     *
     * <p>J5.2 起新代码以 {@link #findings} 为准：summary 由 findings 派生，修复提案
     * 以 `findings.objectiveDelta.strategy` 为入口。checks 仅保留给旧 UI/旧工具与
     * 过渡期回退，不再新增规则；删除需等所有消费者迁移完成。</p>
     */
    private List<ReviewCheckDTO> checks = Lists.newArrayList();
    private CompensationPreviewDTO compensationPreview = new CompensationPreviewDTO();

    // ── J5.2a：统一评价（附加，不替换 checks）─────────────────────────────
    /** 评价版本（含 evaluatedStateVersion + 内容/候选/数据/目标模型摘要）。 */
    private String evaluationVersion;
    private String objectiveModelVersion;
    private Integer evaluatedStateVersion;
    private String evaluationStatus;
    private Integer probesRun;
    /** 派生值：completed && probesRun>0 && 所有 hard finding=pass。 */
    private Boolean hardFeasible;
    /** 15 个 probe 的全量 findings（含 pass）；checks 暂保留兼容。 */
    private List<EvaluationFindingDTO> findings = Lists.newArrayList();
}
