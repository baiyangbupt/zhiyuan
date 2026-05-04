package com.ytell.zhiyuan.model.entity.biz;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import com.ytell.zhiyuan.model.enums.AuthTypeEnum;
import com.ytell.zhiyuan.model.vo.UserAuthVO;
import lombok.Data;

import java.util.Date;

@Data
@TableName("assistant_user_auth")
public class UserAuth {
    @TableId(type = IdType.AUTO)
    private Long authId;
    private Long userId;
    private AuthTypeEnum authType;
    private String openId;
    private String unionId;
    private String loginToken;
    private Integer expiresIn;
    private Date createTime;
    private Date updateTime;

    public UserAuthVO toVo() {
        UserAuthVO vo = new UserAuthVO();
        vo.setOpenId(this.getOpenId());
        vo.setUnionId(this.getUnionId());
        vo.setLoginToken(this.getLoginToken());
        vo.setAuthType(this.getAuthType());
        return vo;

    }
}