package com.ytell.zhiyuan.model.req;

import lombok.Data;

@Data
public class UserMobileLoginRequest {
    private String mobile;
    private String verifyCode;
} 