package com.ytell.zhiyuan.model.entity.biz;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.util.Date;

@Data
@TableName("assistant_codex_thread_binding")
public class CodexThreadBindingEntity {
    @TableId(type = IdType.AUTO)
    private Long id;
    private Long tenantId;
    private Long chatSessionId;
    private Long userId;
    private String threadId;
    private String handleHash;
    private String allowedCapabilities;
    private Date expiresAt;
    private Date revokedAt;
    private Date createTime;
    private Date updateTime;
}
