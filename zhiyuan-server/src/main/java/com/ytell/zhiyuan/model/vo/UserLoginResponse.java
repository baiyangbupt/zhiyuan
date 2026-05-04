package com.ytell.zhiyuan.model.vo;

import lombok.Data;

@Data
public class UserLoginResponse {
    private String loginToken;
    private Long botId;
    private Long tenantId;
    private String channel;
    private Boolean isCustomer;
    private Boolean hasAddInfo;
} 