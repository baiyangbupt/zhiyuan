package com.ytell.zhiyuan.model.dto.inner;

import lombok.Data;

import java.util.Date;

/**
 * applying 对账结果（J1）。只给有界状态，不返回 claimToken/完整 resultJson。
 */
@Data
public class PendingReconcileRes {
    public static final String OUTCOME_NO_PENDING = "no_pending";
    public static final String OUTCOME_NOT_APPLYING = "not_applying";
    public static final String OUTCOME_STILL_APPLYING = "still_applying";
    public static final String OUTCOME_APPLIED = "applied";
    public static final String OUTCOME_EXPIRED = "expired";

    public static final String RESULT_NO_OPERATION_SUBMITTED = "no_operation_submitted";
    public static final String RESULT_OPERATION_UNKNOWN = "operation_result_unknown";

    private String pendingId;
    private Long revision;
    private String pendingStatus;
    /** succeeded | running | missing | null。 */
    private String operationStatus;
    private String outcome;
    private String resultCode;
    private Integer resultPlanVersion;
    private Boolean receiptAvailable = false;
    private Date claimExpiresAt;
    private String message;
}
