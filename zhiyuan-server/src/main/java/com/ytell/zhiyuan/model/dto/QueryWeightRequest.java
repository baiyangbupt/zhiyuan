package com.ytell.zhiyuan.model.dto;

import lombok.Data;

@Data
public class QueryWeightRequest {
    /**
     * 用户信息
     */
    private CreateSessionReq studentinfo;

    /**
     * 用户画像信息
     */
    private UserProfileData profileinfo;

    /**
     * 查询信息
     */

    private QueryWeightDto queryinfo;
}
