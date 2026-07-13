package com.ytell.zhiyuan.model.dto.inner;

import lombok.Data;

import java.util.Map;

@Data
public class PendingConfirmationUpsertReq {
    private Long chatSessionId;
    private String pendingId;
    private Long expectedRevision = 0L;
    private String kind;
    private String actionFamily;
    private Map<String, Object> dataValue;
}
