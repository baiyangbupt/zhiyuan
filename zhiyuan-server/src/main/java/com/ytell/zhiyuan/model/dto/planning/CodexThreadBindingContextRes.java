package com.ytell.zhiyuan.model.dto.planning;

import lombok.Data;

import java.util.ArrayList;
import java.util.List;

@Data
public class CodexThreadBindingContextRes {
    private Long chatSessionId;
    private Long userId;
    private String threadId;
    private List<String> allowedCapabilities = new ArrayList<String>();
    private String expiresAt;
}
