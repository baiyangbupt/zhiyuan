package com.ytell.zhiyuan.model.dto.inner;

import lombok.Data;

import java.util.Map;
import java.util.Date;

@Data
public class PendingConfirmationRes {
    private Long chatSessionId;
    private String pendingId;
    private Long revision;
    private String kind;
    private String actionFamily;
    private String status;
    private String claimToken;
    private Date claimExpiresAt;
    private String resultCode;
    private String resolvedAction;
    private Map<String, Object> dataValue;
    private Boolean transitionApplied;
}
