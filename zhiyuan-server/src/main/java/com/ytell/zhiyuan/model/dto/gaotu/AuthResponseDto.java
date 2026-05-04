package com.ytell.zhiyuan.model.dto.gaotu;

import lombok.Data;

@Data
public class AuthResponseDto {
    private Boolean canUserChat;
    private String noPrivilegeRemindText;
}
