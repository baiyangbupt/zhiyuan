package com.ytell.zhiyuan.model.dto.planning;

import lombok.Data;

import java.util.ArrayList;
import java.util.List;

@Data
public class CodexThreadBindingContextRes {
    /** 绑定所属租户。恢复链路要拿它做归属核验：两个租户的会话号相同不是同一个人。 */
    private Long tenantId;
    private Long chatSessionId;
    private Long userId;
    private String threadId;
    private List<String> allowedCapabilities = new ArrayList<String>();
    private String expiresAt;
}
