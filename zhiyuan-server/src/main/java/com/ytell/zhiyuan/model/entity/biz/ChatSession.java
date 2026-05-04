package com.ytell.zhiyuan.model.entity.biz;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import com.ytell.zhiyuan.model.enums.SessionStatus;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.Date;

@Data
@Builder
@AllArgsConstructor
@NoArgsConstructor
@TableName("assistant_chat_session")
public class ChatSession {
    @TableId(type = IdType.AUTO)
    private Long id;
    private Long tenantId;
    private Long botId;
    private Long userId;
    private String mobile;
    private String userName;
    private SessionStatus sessionStatus;
    private Date startTime;
    private Date endTime;
    private Date createTime;
    private Date updateTime;
}
