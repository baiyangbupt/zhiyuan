package com.ytell.zhiyuan.web.interceptor;

import com.ytell.zhiyuan.model.enums.AuthTypeEnum;
import lombok.Data;

@Data
public class UserBaseData {
    private Long userId;
    private AuthTypeEnum authType;
    private String openId;
    private String unionId;
}
