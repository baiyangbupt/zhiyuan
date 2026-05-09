package com.ytell.zhiyuan.model.dto.integration;

import lombok.Data;

@Data
public class ExternalReturnOptionsDTO {
    private String webBaseUrl;
    private String pathMode = "assistant-pc";
}
