package com.ytell.zhiyuan.model.dto.evidence;

import lombok.Data;

/**
 * 证据归属范围：权威台账里的 tenant_id / chat_session_id / thread_id 三列。
 *
 * <p>范围不全时不签发——台账这三列是 NOT NULL，凭空补一个范围等于把证据挂到别人名下。</p>
 */
@Data
public class EvidenceScope {

    private Long tenantId;
    private Long chatSessionId;
    private String threadId;

    public static EvidenceScope of(Long tenantId, Long chatSessionId, String threadId) {
        EvidenceScope scope = new EvidenceScope();
        scope.setTenantId(tenantId);
        scope.setChatSessionId(chatSessionId);
        scope.setThreadId(threadId);
        return scope;
    }

    /** 无范围，用于不携带会话上下文的调用方：不会签发任何证据。 */
    public static EvidenceScope none() {
        return new EvidenceScope();
    }

    public boolean isComplete() {
        return tenantId != null && chatSessionId != null;
    }
}
