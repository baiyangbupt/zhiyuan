package com.ytell.zhiyuan.model.dto;

import com.ytell.zhiyuan.model.enums.AuthTypeEnum;
import lombok.Data;

@Data
public class ThirdChannelLoginDto {
    private Integer userId;
    private String openId;
    private String unionId;
    private AuthTypeEnum authType;
    private String sessionKey;
    private Integer expiresIn;
}