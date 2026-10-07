package com.ytell.zhiyuan.model.dto.planning;

import lombok.Data;

import java.util.ArrayList;
import java.util.List;

/**
 * 按候选池实体 ID 的比较请求（只读）。
 *
 * <p>与 {@link CandidateComparisonReq} 的分工：那条的实体连同**值**由调用方传入
 * （值从各自的来源链路取）；这条只有一个要求——**把 ID 给出来，值由服务端从
 * 会话候选池真实载入**。模型不该、也不能凭记忆填这些数字。</p>
 */
@Data
public class CandidateCompareReq {

    /** 会话 ID。相邻端点把 chatSessionId 放在 query 上（candidate-preview 同款），
     *  这条同时接受 body 字段；两处都给时以 body 为准。 */
    private Long chatSessionId;

    /** 2–5 个候选池实体 ID（= volunteerId，从 candidate-preview 的 entityId 取）。 */
    private List<String> entityIds = new ArrayList<String>();

    /** 要比较的维度；不传则用服务端白名单全集。 */
    private List<String> dimensions = new ArrayList<String>();
}
