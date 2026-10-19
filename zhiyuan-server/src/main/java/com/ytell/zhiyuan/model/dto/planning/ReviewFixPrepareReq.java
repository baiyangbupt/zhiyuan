package com.ytell.zhiyuan.model.dto.planning;

import lombok.Data;

/**
 * 审查修复提案 prepare 请求：把只读预览里用户点中的那一份提案冻结成 pending。
 *
 * <p>几个摘要都是**预览回传值**，用来证明用户确认的就是服务端刚算出的那一份：
 * previewDigest 覆盖冻结方案与动作，commandDigest/evaluationVersion 绑定命令与评价输入，
 * sourceVersionGuard 绑定方案版本。</p>
 */
@Data
public class ReviewFixPrepareReq {
    private String proposalId;
    private String previewDigest;
    private String commandDigest;
    private String evaluationVersion;
    private Integer sourceVersionGuard;
    private Boolean regenerateOrderedPlan = Boolean.TRUE;
    private Boolean rerunReview = Boolean.TRUE;
}
