package com.ytell.zhiyuan.model.dto;

import lombok.Data;

@Data
public class SaveMessageRes {
    private Long id; // 消息ID
    private Boolean getProfileFlag = false; //是否刷新用户画像
}
