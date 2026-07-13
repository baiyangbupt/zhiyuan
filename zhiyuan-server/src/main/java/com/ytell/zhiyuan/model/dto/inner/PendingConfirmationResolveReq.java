package com.ytell.zhiyuan.model.dto.inner;

import lombok.Data;

import java.util.Map;

@Data
public class PendingConfirmationResolveReq {
    private Long chatSessionId;
    private String pendingId;
    private Long expectedRevision;
    private String action;
    private String claimToken;
    private String resultCode;
    private Map<String, Object> dataValue;
}
