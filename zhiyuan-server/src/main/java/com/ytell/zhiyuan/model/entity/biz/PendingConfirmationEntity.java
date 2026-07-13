package com.ytell.zhiyuan.model.entity.biz;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.util.Date;

@Data
@TableName("assistant_chat_session_pending_confirmation")
public class PendingConfirmationEntity {
    @TableId(type = IdType.AUTO)
    private Long id;
    private Long tenantId;
    private Long chatSessionId;
    private String pendingId;
    private Long revision;
    private String kind;
    private String actionFamily;
    private String status;
    private String claimToken;
    private Date claimExpiresAt;
    private String dataValue;
    private String resultCode;
    private String resolvedAction;
    private Date createTime;
    private Date updateTime;
}
