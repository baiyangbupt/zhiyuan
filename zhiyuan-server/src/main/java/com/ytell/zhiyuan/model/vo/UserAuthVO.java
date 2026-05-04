package com.ytell.zhiyuan.model.vo;

import com.ytell.zhiyuan.model.enums.AuthTypeEnum;
import lombok.Data;

@Data
public class UserAuthVO {
    private AuthTypeEnum authType;
    private String openId;
    private String unionId;
    private String loginToken;
    private Boolean hasMobile;
}