package com.ytell.zhiyuan.model.req;

import lombok.Data;

@Data
public class UserLoginRequest {
    private String userName;
    private String password;
} 