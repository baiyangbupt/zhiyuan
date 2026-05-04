package com.ytell.zhiyuan.model.dto;

import lombok.Data;

import java.util.List;

/**
 * 用户基本信息响应DTO
 */
@Data
public class UserBasicProfileResponse {

    /**
     * 用户分数信息
     */
    private List<ProfileKVDto> userScore;

    /**
     * 用户基本信息
     */
    private List<ProfileKVDto> userBasic;

    public UserBasicProfileResponse(List<ProfileKVDto> userScore, List<ProfileKVDto> userBasic) {
        this.userScore = userScore;
        this.userBasic = userBasic;
    }
}
