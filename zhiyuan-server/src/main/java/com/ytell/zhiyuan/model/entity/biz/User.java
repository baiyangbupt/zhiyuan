package com.ytell.zhiyuan.model.entity.biz;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import com.ytell.zhiyuan.model.enums.UserLevel;
import lombok.Data;

import java.util.Date;

@Data
@TableName("assistant_user_base")
public class User {

    @TableId(type = IdType.AUTO)
    private Long id;
    /**
     * 租户ID
     */
    private Long tenantId;
    /**
     * 机器人ID
     */
    private Long botId;

    /**
     * 手机号
     */
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
     * 额外数据：用户性别、高考年份、高考省份、选科等
     */
    private String userScore;

    /**
     * 修改次数设置：修改基本信息次数、创建会话次数等
     */

    private String limitSettings;

    /**
     * 用户账号过期时间
     */
    private Date expiredDate;

    /**
     * 用户等级
     */

    private UserLevel userLevel;

    /**
     * 渠道
     */
    private String channel;

    /**
     * 创建时间
     */
    private Date createTime;
    /**
     * 更新时间
     */
    private Date updateTime;

    /**
     * 是否删除 0-未删除 1-已删除
     */
    private Integer isDeleted;

} 