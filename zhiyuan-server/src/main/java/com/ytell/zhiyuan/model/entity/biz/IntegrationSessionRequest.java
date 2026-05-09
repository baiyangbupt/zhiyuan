package com.ytell.zhiyuan.model.entity.biz;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.util.Date;

@Data
@TableName("integration_session_request")
public class IntegrationSessionRequest {
    @TableId(type = IdType.AUTO)
    private Long id;
    private Long tenantId;
    private Long userId;
    private String platform;
    private String externalRequestId;
    private String requestHash;
    private Long chatSessionId;
    private String status;
    private String errorMessage;
    private Date createTime;
    private Date updateTime;
}
