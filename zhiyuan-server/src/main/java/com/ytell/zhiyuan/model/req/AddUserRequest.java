package com.ytell.zhiyuan.model.req;

import lombok.Data;

@Data
public class AddUserRequest {
    private Long tenantId;
    private Long botId;
    private String userName;
    private String password;

} 