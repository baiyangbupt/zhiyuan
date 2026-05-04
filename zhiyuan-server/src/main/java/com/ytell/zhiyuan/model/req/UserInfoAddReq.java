package com.ytell.zhiyuan.model.req;

import com.ytell.zhiyuan.model.dto.UserScoreBase;
import lombok.Data;

@Data
public class UserInfoAddReq {
    private String userName;
    private String avatarUrl;
    private UserScoreBase userScoreOb;
}