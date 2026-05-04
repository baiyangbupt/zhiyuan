package com.ytell.zhiyuan.model.enums;

import com.baomidou.mybatisplus.annotation.EnumValue;
import lombok.AllArgsConstructor;
import lombok.Getter;

@Getter
@AllArgsConstructor
public enum LoginType {
    MOBILE(0, "手机号登录"),
    EMAIL(1, "邮箱登录"),
    USERNAME(2, "用户名登录"),
    TOKEN(3, "token登录");
    @EnumValue
    private final int code;
    private final String desc;
}