package com.ytell.zhiyuan.model.dto.planning;

import lombok.Data;

@Data
public class CodexThreadBindingResolveReq {
    private Long chatSessionId;
    private String threadId;
    private String handle;
    private String capability;
}
