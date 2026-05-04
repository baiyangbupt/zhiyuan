package com.ytell.zhiyuan.model.entity.biz;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import com.ytell.zhiyuan.model.enums.LoginType;
import lombok.Data;

import java.util.Date;

@Data
@TableName("assistant_user_credential")
public class UserCredential {
    @TableId(type = IdType.AUTO)
    private Long credentialId;
    private Long userId;
    private LoginType loginType;
    private String loginToken;
    private String channel;
    private String identifier;
    private String passwordHash;
    private Date createTime;
    private Date updateTime;
}