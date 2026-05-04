package com.ytell.zhiyuan.model.vo;

import lombok.Data;

@Data
public class UserLoginVO {
    private Long userId;
    private String loginToken;
}