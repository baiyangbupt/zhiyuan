package com.ytell.zhiyuan.model.dto.planning;

import lombok.Data;

/**
 * prepare 的结果。`status` 取值与语义：
 * <ul>
 *   <li>{@code prepared} —— 本次真的编译了新预览；</li>
 *   <li>{@code duplicate} —— 同一 requestId 同摘要，返回**原始结果**，没有重新编译；</li>
 *   <li>{@code superseded} —— 该 requestId 被后一次 prepare 取代，**不能复活**；</li>
 * </ul>
 * 三者必须是可区分的状态，不能都回一个"成功"：调用方据此决定是等待、还是
 * 提示用户重新发起。
 */
@Data
public class PrepareResultDTO {
    private String status;
    private String requestId;
    private String pendingId;
    private String operationId;
    private Object result;
    private String message;
}
