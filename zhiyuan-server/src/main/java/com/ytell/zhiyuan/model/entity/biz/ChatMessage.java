package com.ytell.zhiyuan.model.entity.biz;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import com.ytell.zhiyuan.model.enums.ContentType;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.Date;

@Data
@Builder
@AllArgsConstructor
@NoArgsConstructor
@TableName("assistant_chat_message")
public class ChatMessage {
    @TableId(type = IdType.AUTO)
    private Long id;
    private Long chatSessionId;
    private Long tenantId;
    private String messageFrom;
    private String messageFromUserName;
    private ContentType contentType;
    private String content;
    private Integer feedback;
    private Date createTime;
    private Date updateTime;

}
