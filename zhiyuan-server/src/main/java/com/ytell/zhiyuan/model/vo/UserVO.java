package com.ytell.zhiyuan.model.vo;

import com.ytell.zhiyuan.model.dto.LimitSettingsOb;
import com.ytell.zhiyuan.model.dto.UserScoreBase;
import com.ytell.zhiyuan.model.enums.UserLevel;
import lombok.Data;

import java.util.Date;

@Data
public class UserVO {
    private Long id;
    private Long tenantId;
    private Long botId;
    private String mobile;
    /**
     * 昵称
     */
    private String userName;

    /**
     * 头像
     */
    private String avatarUrl;

    /**
     * 是否为C端用户
     */
    private Boolean isCustomer;
    /**
     * 用户渠道
     */
    private String channel;
    /**
     * 用户账号过期时间
     */
    private Date expiredDate;

    /**
     * 用户等级
     */

    private UserLevel userLevel;
    private Boolean hasAddInfo;
    private UserScoreBase userScoreOb;
    private LimitSettingsOb limitSettingsOb;

}