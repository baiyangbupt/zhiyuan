package com.ytell.zhiyuan.model.req;

import lombok.Data;

@Data
public class UserTokenLoginRequest {
    private String token;
    private String channel;
} 