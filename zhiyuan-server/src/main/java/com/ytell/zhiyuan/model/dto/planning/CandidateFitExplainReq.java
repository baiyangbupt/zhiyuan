package com.ytell.zhiyuan.model.dto.planning;

import lombok.Data;

/**
 * 适配性解释请求（**只读**）：解释**某一个**候选为什么匹配/不匹配。
 *
 * <p>与 {@link CandidateCompareReq} 同源：`entityId`（= volunteerId，来自
 * candidate-preview 的 `entityId`）只用于**定位候选行**，值由服务端从会话候选池
 * 真实载入——模型凭记忆复述候选字段这条路在这里同样堵死。</p>
 */
@Data
public class CandidateFitExplainReq {

    /** 会话 ID。相邻端点把 chatSessionId 放在 query 上，这条同时接受 body 字段；
     *  两处都给时以 body 为准（与 compare-candidates 同一口径）。 */
    private Long chatSessionId;

    /** 候选池实体 ID（= volunteerId，从 candidate-preview 的 entityId 取）。必填。 */
    private String entityId;
}
